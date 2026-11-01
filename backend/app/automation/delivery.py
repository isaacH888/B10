"""Durable outbox, FIFO delivery, bounded retries, and transactional mail effects."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from uuid import uuid4

from .reminders import instant


UTC = timezone.utc


def stamp(value):
    return instant(value).isoformat()


def money(currency, minor):
    # Display USD exactly without floating-point rounding. Other currencies retain
    # their explicit minor-unit denomination instead of assuming two decimals.
    if currency == "USD":
        return f"USD {minor // 100}.{minor % 100:02d}"
    return f"{currency} {minor} minor units"


class RetryLater(Exception):
    def __init__(self, seconds=30):
        self.seconds = max(1, min(43200, int(seconds)))
        super().__init__("Job will be retried")


class MemoryQueue:
    def __init__(self):
        self.messages = []
        self.dead_letters = []

    def send(self, body, group_id, dedup_id):
        self.messages.append({"body": deepcopy(body), "group_id": group_id, "dedup_id": dedup_id})
        return str(len(self.messages))

    def dead_letter(self, body, group_id, dedup_id):
        self.dead_letters.append({"body": deepcopy(body), "group_id": group_id, "dedup_id": dedup_id})

    def delay(self, record, seconds):
        pass


class SqsQueue:
    def __init__(self, settings, client=None):
        self.settings, self._client = settings, client

    @property
    def client(self):
        if self._client is None:
            import boto3
            self._client = boto3.client("sqs")
        return self._client

    def send(self, body, group_id, dedup_id):
        result = self.client.send_message(QueueUrl=self.settings["AUTOMATION_QUEUE_URL"],
                                          MessageBody=json.dumps(body, sort_keys=True, separators=(",", ":")),
                                          MessageGroupId=group_id, MessageDeduplicationId=dedup_id)
        return result["MessageId"]

    def dead_letter(self, body, group_id, dedup_id):
        self.client.send_message(QueueUrl=self.settings["AUTOMATION_DLQ_URL"],
                                 MessageBody=json.dumps(body, sort_keys=True, separators=(",", ":")),
                                 MessageGroupId=group_id, MessageDeduplicationId=dedup_id)

    def delay(self, record, seconds):
        if record.get("receiptHandle"):
            self.client.change_message_visibility(QueueUrl=self.settings["AUTOMATION_QUEUE_URL"],
                                                   ReceiptHandle=record["receiptHandle"],
                                                   VisibilityTimeout=max(1, min(43200, int(seconds))))


class MemoryMail:
    def __init__(self):
        self.messages = []

    def send(self, recipient, subject, body, key):
        self.messages.append({"recipient": recipient, "subject": subject, "body": body, "key": key})
        return f"local-{len(self.messages)}"


class SesMail:
    def __init__(self, settings, client=None):
        self.settings, self._client = settings, client

    @property
    def client(self):
        if self._client is None:
            import boto3
            self._client = boto3.client("ses")
        return self._client

    def send(self, recipient, subject, body, key):
        # SES SendEmail has no idempotency token. See the documented crash window.
        result = self.client.send_email(Source=self.settings["AUTOMATION_FROM_EMAIL"],
                                        Destination={"ToAddresses": [recipient]},
                                        Message={"Subject": {"Data": subject, "Charset": "UTF-8"},
                                                 "Body": {"Text": {"Data": body, "Charset": "UTF-8"}}},
                                        Tags=[{"Name": "automation", "Value": sha256(key.encode()).hexdigest()[:32]}])
        return result["MessageId"]


class OutboxDispatcher:
    def __init__(self, settings, store, queue, clock=None):
        self.settings, self.store, self.queue = settings, store, queue
        self.clock = clock or (lambda: datetime.now(UTC))

    def dispatch(self, limit=100):
        """Lease committed rows, send outside the transaction, then mark published."""
        now = instant(self.clock())
        claims = []
        with self.store.transaction() as tx:
            rows = tx.list_outbox(statuses=["pending", "publishing"])
            for row in rows:
                if len(claims) >= limit:
                    break
                if row.get("next_attempt_at") and instant(row["next_attempt_at"]) > now:
                    continue
                if row.get("lease_until") and instant(row["lease_until"]) > now:
                    continue
                row.update(status="publishing", lease_token=uuid4().hex,
                           lease_until=stamp(now + timedelta(seconds=self.settings.get("AUTOMATION_LEASE_SECONDS", 120))),
                           publish_attempts=row.get("publish_attempts", 0) + 1)
                tx.save_outbox(row)
                claims.append(deepcopy(row))
        published = 0
        for claim in claims:
            try:
                generation = claim.get("replay_generation", 0)
                message_id = self.queue.send({"job_key": claim["key"], "delivery_generation": generation},
                                             claim["booking_id"],
                                             sha256(f"{claim['key']}:{generation}".encode()).hexdigest())
            except Exception:
                with self.store.transaction() as tx:
                    current = tx.get_outbox(claim["key"])
                    if current and current.get("lease_token") == claim["lease_token"]:
                        delay = min(900, 2 ** min(claim["publish_attempts"], 9))
                        current.update(status="pending", lease_until=None,
                                       next_attempt_at=stamp(now + timedelta(seconds=delay)),
                                       last_error="Queue publication failed; dispatcher will retry.")
                        tx.save_outbox(current)
                continue
            # A crash here leaves a lease. Re-publication after expiry uses stable deduplication.
            # Deduplication expires in SQS; consumer delivery records cover arbitrarily late repeats.
            with self.store.transaction() as tx:
                current = tx.get_outbox(claim["key"])
                if current and current.get("lease_token") == claim["lease_token"]:
                    current.update(status="published", lease_until=None, message_id=message_id,
                                   last_error=None, published_at=stamp(self.clock()))
                    tx.save_outbox(current)
                    published += 1
        return published


class JobProcessor:
    def __init__(self, settings, store, queue, mail, reminders, calendar_worker, clock=None):
        self.settings, self.store, self.queue, self.mail = settings, store, queue, mail
        self.reminders, self.calendar_worker = reminders, calendar_worker
        self.clock = clock or (lambda: datetime.now(UTC))

    def replay(self, key, actor):
        from .domain import DomainError
        with self.store.transaction() as tx:
            job, delivery = tx.get_outbox(key), tx.get_delivery(key)
            if not job:
                raise DomainError("Automation job was not found", 404, "not_found")
            if not delivery or delivery["status"] not in {"failed", "dead_letter"}:
                raise DomainError("Only failed or dead-letter jobs can be replayed", 409, "job_not_replayable")
            delivery.update(status="pending", attempts=0, lease_until=None, next_attempt_at=None,
                            last_error=None, replayed_at=stamp(self.clock()), replayed_by=actor,
                            generation=delivery.get("generation", 0) + 1)
            job.update(status="pending", lease_until=None, next_attempt_at=None,
                       replay_generation=delivery["generation"])
            tx.save_delivery(delivery)
            tx.save_outbox(job)
            tx.audit("automation.job.replayed", actor, {"job_key": key})
        return {"key": key, "status": "pending"}

    def process(self, payload):
        if payload.get("kind") == "scheduled_reminder":
            key = self.reminders.materialize(payload)
            if not key:
                return
        else:
            key = payload["job_key"]
        now = instant(self.clock())
        token = uuid4().hex
        with self.store.transaction() as tx:
            job = tx.get_outbox(key)
            if not job:
                raise ValueError("Unknown outbox job")
            delivery = tx.get_delivery(key) or {"key": key, "attempts": 0, "status": "pending"}
            if payload.get("delivery_generation", 0) != delivery.get("generation", 0):
                return
            if delivery["status"] in {"sent", "skipped", "dead_letter", "failed"}:
                return
            if delivery.get("next_attempt_at") and instant(delivery["next_attempt_at"]) > now:
                raise RetryLater((instant(delivery["next_attempt_at"]) - now).total_seconds())
            if delivery.get("lease_until") and instant(delivery["lease_until"]) > now:
                raise RetryLater((instant(delivery["lease_until"]) - now).total_seconds())
            delivery.update(status="sending", attempts=delivery["attempts"] + 1,
                            lease_token=token, updated_at=stamp(now),
                            lease_until=stamp(now + timedelta(seconds=self.settings.get("AUTOMATION_LEASE_SECONDS", 120))))
            tx.save_delivery(delivery)
        try:
            provider_id = self._execute(job)
        except Exception as error:
            category = getattr(error, "category", None)
            permanent = category in {"invalid", "missing", "repair_required", "reconnect_required"}
            # Provider exception strings may contain credentials, request bodies or PII.
            safe_error = {"invalid": "Correct event details, then retry.",
                          "repair_required": "Calendar needs owner repair.",
                          "missing": "Calendar or event is missing; owner repair is required.",
                          "reconnect_required": "Reconnect Google Calendar, then retry."}.get(
                              category, "An external service failed; retry is scheduled.")
            exhausted = delivery["attempts"] >= self.settings.get("AUTOMATION_MAX_ATTEMPTS", 6)
            if exhausted and not permanent:
                # Persist terminal state only after DLQ publication succeeds. A crash can duplicate
                # this diagnostic record but cannot silently lose the job.
                generation = delivery.get("generation", 0)
                self.queue.dead_letter({"job_key": key, "reason": "attempts_exhausted",
                                        "delivery_generation": generation}, job["booking_id"],
                                       sha256(f"dead:{key}:{generation}".encode()).hexdigest())
            delay = min(self.settings.get("AUTOMATION_RETRY_MAX_SECONDS", 900),
                        self.settings.get("AUTOMATION_RETRY_BASE_SECONDS", 30) * 2 ** (delivery["attempts"] - 1))
            with self.store.transaction() as tx:
                current = tx.get_delivery(key)
                if current and current.get("lease_token") == token:
                    current.update(status="failed" if permanent else "dead_letter" if exhausted else "pending",
                                   lease_until=None, next_attempt_at=stamp(now + timedelta(seconds=delay)),
                                   last_error=safe_error, updated_at=stamp(self.clock()))
                    tx.save_delivery(current)
                    if exhausted and job["kind"] == "calendar":
                        booking = tx.get_booking(job["booking_id"])
                        if (booking and booking["revision"] == job["revision"] and
                                booking.get("calendar_status") == "pending"):
                            booking.update(calendar_status="failed", calendar_error="Retries exhausted; inspect dead-letter job and retry.")
                            tx.save_booking(booking)
            if permanent or exhausted:
                return
            raise RetryLater(delay) from None
        with self.store.transaction() as tx:
            current = tx.get_delivery(key)
            if current and current.get("lease_token") == token:
                current.update(status="skipped" if provider_id is False else "sent", lease_until=None,
                               next_attempt_at=None, last_error=None, provider_id=provider_id,
                               updated_at=stamp(self.clock()))
                tx.save_delivery(current)

    def _execute(self, job):
        if job["kind"] == "calendar":
            return self.calendar_worker.run(job["booking_id"], job["revision"],
                                            repair=job.get("payload", {}).get("repair", False))
        if job["kind"] == "reminder_schedule":
            self.reminders.replace(job["booking_id"])
            return None
        # Recheck authoritative booking immediately before composing and submitting any email.
        with self.store.booking_lock(job["booking_id"]):
            with self.store.transaction() as tx:
                booking = tx.get_booking(job["booking_id"])
            if not booking:
                return False
            payload, kind = job.get("payload", {}), job["kind"]
            reference = booking.get("reference", booking["id"])
            total = money(booking["currency"], booking["total_minor"])
            remaining = money(booking["currency"], booking["remaining_minor"])
            summary = (f"Booking {reference}\nService: {booking['service_type']}\nVenue: {booking['venue']}\n"
                       f"Start: {booking['start']} ({booking['timezone']})\nEnd: {booking['end']}\n"
                       f"Popsicles: {booking['quantity']}\nAgreed total: {total}\nRemaining balance: {remaining}\n")
            recipient = booking["customer_email"]
            if kind == "reminder":
                items = self.reminders.outstanding(booking, payload)
                if not items:
                    return False
                subject = f"Outstanding items for booking {reference}"
                body = f"Your Popssibilities catering event is approaching.\nBooking {reference}\n"
                if "payment" in items:
                    body += f"Please arrange the remaining payment of {remaining} through your agreed payment method.\n"
                if "count" in items:
                    body += "Please confirm your final popsicle count with Popssibilities.\n"
                body += "This is a reminder, not a new payment deadline. Reply to coordinate any details.\n"
            elif kind in {"confirmation_customer", "confirmation_owner"}:
                if (booking["status"] != "confirmed" or
                        payload.get("confirmation_generation", 0) != booking.get("confirmation_generation", 0)):
                    return False
                subject = f"Popssibilities booking {reference} confirmed"
                body = "Your verified deposit confirms your catering booking.\n" + summary
                if kind == "confirmation_customer":
                    contract = booking.get("contract_url") or self.settings.get("AUTOMATION_CONTRACT_URL")
                    if not contract:
                        raise ValueError("Contract URL is required for confirmation")
                    body += f"Review your contract: {contract}\n"
                else:
                    recipient = self.settings["AUTOMATION_OWNER_EMAIL"]
                    body += f"Private dashboard: {self.settings['AUTOMATION_DASHBOARD_URL'].rstrip('/')}/{booking['id']}\n"
            elif kind == "deposit_request":
                if (booking["status"] != "awaiting_deposit" or
                        (booking.get("reservation_expires_at") or 0) <= instant(self.clock()).timestamp()):
                    return False
                subject = f"Deposit requested for Popssibilities booking {reference}"
                body = summary + f"Availability is approved. Deposit requested: {money(booking['currency'], booking['deposit_minor'])}.\n"
                body += "Arrange payment using the method agreed with Popssibilities. Payment is verified by the owner.\n"
            else:
                raise ValueError("Unsupported automation job kind")
            if not recipient:
                raise ValueError("Mail recipient is required")
            return self.mail.send(recipient, subject, body, job["key"])

    def handle_batch(self, event):
        failures, blocked = [], set()
        for record in event.get("Records", []):
            group = record.get("attributes", {}).get("MessageGroupId", "unknown")
            if group in blocked:
                failures.append({"itemIdentifier": record["messageId"]})
                continue
            try:
                self.process(json.loads(record["body"]))
            except Exception as error:
                failures.append({"itemIdentifier": record["messageId"]})
                blocked.add(group)
                try:
                    self.queue.delay(record, getattr(error, "seconds", 30))
                except Exception:
                    # Returning a partial failure still guarantees redelivery at queue visibility.
                    pass
        return {"batchItemFailures": failures}
