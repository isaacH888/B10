"""Submitted-request notifications, independent of availability and payment approval."""

import hashlib
from contextlib import nullcontext
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlsplit

from ..email.settings import valid_address
from .calendar import CalendarWorker
from .delivery import money, stamp
from .domain import DomainError
from .reminders import instant

CONFIG_ID = "company-request-calendar"


def request_id(order_id):
    return hashlib.sha256(("request:" + order_id).encode()).hexdigest()[:32]


class RequestCalendarWorker(CalendarWorker):
    def _get_record(self, tx, identifier):
        record = tx.get_request(identifier)
        if record and not tx.get_order_link(record["source_order_id"]):
            return record
        return None

    def _save_record(self, tx, record):
        tx.save_request(record)


class RequestNotifications:
    def __init__(self, settings, store, oauth, mail, orders=None, clock=None):
        self.settings, self.store, self.oauth, self.mail = settings, store, oauth, mail
        self.orders = orders
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.calendar = RequestCalendarWorker(
            settings, store, oauth, clock=lambda: instant(self.clock()).timestamp()
        )

    def status(self):
        with self.store.transaction() as tx:
            config = tx.get_connection(CONFIG_ID) or {}
            records = tx.list_requests() if config else []
            rows = []
            for record in sorted(records, key=lambda row: row["created_at"], reverse=True)[:20]:
                key = f"request_email:{record['id']}"
                delivery = tx.get_delivery(key) or {}
                linked = bool(tx.get_order_link(record["source_order_id"]))
                rows.append(
                    {
                        "order_id": record["source_order_id"],
                        "email_status": delivery.get("status", "pending"),
                        "email_error": delivery.get("last_error"),
                        "email_job": key,
                        "calendar_status": "booking"
                        if linked
                        else record.get("calendar_status", "pending"),
                        "calendar_error": None if linked else record.get("calendar_error"),
                    }
                )
            connection = tx.get_connection(config["target_owner_id"]) if config else None
        return {
            "enabled": bool(config.get("enabled")),
            "recipient": config.get("recipient") or self.settings.get("AUTOMATION_OWNER_EMAIL", ""),
            "calendar_id": (connection or {}).get("calendar_id"),
            "email_mode": "simulated"
            if self.settings.get("AUTOMATION_MODE", "local") == "local"
            else self.settings.get("EMAIL_PROVIDER", "ses"),
            "requests": rows,
        }

    def configure(self, actor, recipient, enabled=True):
        if not isinstance(enabled, bool):
            raise DomainError("enabled must be true or false")
        if enabled and not valid_address(recipient):
            raise DomainError("Enter one notification email address")
        lock = self.orders["lock"] if self.orders is not None else nullcontext()
        with lock, self.store.transaction() as tx:
            previous = tx.get_connection(CONFIG_ID) or {}
            # Configuration is transactional with the new schema readiness check.
            tx.list_requests()
            if enabled:
                connection = tx.get_connection(actor) or {}
                if connection.get("status") != "connected" or not connection.get("calendar_id"):
                    raise DomainError(
                        "Connect your Google Calendar before enabling incoming requests", 409
                    )
            config = {
                "owner_id": CONFIG_ID,
                "target_owner_id": actor if enabled else previous.get("target_owner_id", actor),
                "recipient": recipient if enabled else previous.get("recipient", ""),
                "enabled": enabled,
                "enabled_at": previous.get("enabled_at") or stamp(self.clock()),
                "boundary": previous.get("boundary", 0),
                "excluded_orders": previous.get("excluded_orders", []),
            }
            if enabled and not previous.get("enabled"):
                if self.orders is None:
                    config["boundary"] = tx.request_boundary()
                else:
                    config["excluded_orders"] = list(self.orders["by_id"])
            tx.save_connection(config)
            tx.audit("requests.configured", actor, {"enabled": enabled}, stamp(self.clock()))
        return self.status()

    def _new_record(self, order, config):
        event = order["event"]
        end = event.get("ends_at")
        if not end:
            end = (
                datetime.fromisoformat(event["starts_at"].replace("Z", "+00:00"))
                + timedelta(hours=1)
            ).isoformat()
        origin = urlsplit(self.settings["AUTOMATION_DASHBOARD_URL"])
        location = event["location"]
        return {
            "id": request_id(order["id"]),
            "reference": order["id"],
            "owner_id": config["target_owner_id"],
            "recipient": config["recipient"],
            "source_order_id": order["id"],
            "source_order": deepcopy(order),
            "source_version": order["version"],
            "status": "cancelled" if order["status"] == "cancelled" else "requested",
            "request_calendar": True,
            "request_dashboard_url": f"{origin.scheme}://{origin.netloc}/admin/orders/{quote(order['id'], safe='')}",
            "event_type": event["type"],
            "start": event["starts_at"],
            "end": end,
            "end_unspecified": not bool(event.get("ends_at")),
            "timezone": event["timezone"],
            "venue": ", ".join(
                location[key]
                for key in ("line1", "line2", "city", "region", "postal_code", "country_code")
                if location.get(key)
            )[:500],
            "service_type": order["catering_request"]["service_type"],
            "revision": 1,
            "schedule_revision": 1,
            "calendar_status": "pending",
            "created_at": order["created_at"],
        }

    def reconcile(self, limit=100, order_id=None):
        """Recover committed submissions on every dispatcher tick, including after crashes."""
        lock = self.orders["lock"] if self.orders is not None else nullcontext()
        with lock, self.store.transaction() as tx:
            config = tx.get_connection(CONFIG_ID) or {}
            if not config:
                return 0
            if self.orders is None:
                orders = tx.request_orders(config["boundary"], config["enabled"], limit, order_id)
            else:
                orders = list(self.orders["by_id"].values())
            captured = 0
            for order in orders:
                if order_id is not None and order["id"] != order_id:
                    continue
                if captured >= limit:
                    break
                if tx.get_order_link(order["id"]):
                    continue
                record = tx.get_request(request_id(order["id"]))
                if not record:
                    if not config.get("enabled") or order["id"] in config.get(
                        "excluded_orders", []
                    ):
                        continue
                    record = self._new_record(order, config)
                    tx.enqueue(f"request_email:{record['id']}", "request_email", record["id"], 1)
                elif record["source_version"] != order["version"]:
                    record.update(
                        source_version=order["version"],
                        source_order=deepcopy(order),
                        revision=record["revision"] + 1,
                    )
                    record["status"] = (
                        "cancelled" if order["status"] == "cancelled" else "requested"
                    )
                else:
                    continue
                record.update(calendar_status="pending", calendar_error=None)
                tx.save_request(record)
                tx.enqueue(
                    f"request_calendar:{record['id']}:{record['revision']}",
                    "request_calendar",
                    record["id"],
                    record["revision"],
                )
                captured += 1
            return captured

    def execute(self, job):
        if job["kind"] == "request_calendar":
            return self.calendar.run(job["booking_id"], job["revision"])
        with self.store.booking_lock(job["booking_id"]):
            with self.store.transaction() as tx:
                record = tx.get_request(job["booking_id"])
            if not record:
                return False
            order = record["source_order"]
            customer, event, catering, pricing = (
                order[key] for key in ("customer", "event", "catering_request", "pricing")
            )
            body = (
                f"A catering request was submitted. Availability and deposit still require owner approval.\n"
                f"Request: {order['id']}\nRequest status: {order['status']}\nCustomer: {customer['name']}\nEmail: {customer['email']}\nPhone: {customer['phone']}\n"
                f"Event: {event['type']}\nStart: {event['starts_at']} ({event['timezone']})\n"
                f"End: {event.get('ends_at') or 'Not provided'}\nLocation: {record['venue']}\n"
                f"Service: {catering['service_type']}\nQuantity: {catering['quantity']}\n"
                f"Quoted total: {money(pricing['currency'], pricing['total_cents'])}\n"
                f"Private dashboard: {record['request_dashboard_url']}\n"
            )
            return self.mail.send(
                record["recipient"],
                f"New catering request: {event['type']} ({order['id']})",
                body,
                job.get("mail_idempotency_key", job["key"]),
            )

    def retry_calendar(self, order_id, actor, repair=False):
        identifier = request_id(order_id)
        with self.store.booking_lock(identifier), self.store.transaction() as tx:
            record = tx.get_request(identifier)
            if not record:
                raise DomainError("Request notification was not found", 404, "not_found")
            if record["owner_id"] != actor:
                raise DomainError(
                    "Use the owner account connected to this request calendar", 403, "forbidden"
                )
            if tx.get_order_link(order_id):
                raise DomainError("This request is managed from its booking", 409)
            record.update(
                revision=record["revision"] + 1, calendar_status="pending", calendar_error=None
            )
            if repair:
                record["calendar_repair_requested"] = True
            tx.save_request(record)
            tx.enqueue(
                f"request_calendar:{identifier}:{record['revision']}",
                "request_calendar",
                identifier,
                record["revision"],
            )
            tx.audit("requests.calendar_retried", actor, {"order_id": order_id, "repair": repair})
        return {"status": "pending"}
