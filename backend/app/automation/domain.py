"""Owner-approved catering bookings and audited external-payment verification."""

import re
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

MAX_MONEY = 10**12  # Per payment and aggregate, comfortably inside signed BIGINT.


class DomainError(ValueError):
    def __init__(self, message, status=400, code="invalid_booking"):
        super().__init__(message)
        self.status = status
        self.status_code = status
        self.code = code


def iso(value):
    if isinstance(value, (int, float)):
        value = datetime.fromtimestamp(value, timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def instant(value, field="time"):
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None or result.utcoffset() is None:
            raise ValueError()
        return result.astimezone(timezone.utc)
    except (ValueError, TypeError, AttributeError, OverflowError):
        raise DomainError(
            f"{field} must be an ISO 8601 date and time with an explicit UTC offset"
        ) from None


def integer(value, field, minimum=1, maximum=MAX_MONEY):
    if type(value) is not int or not minimum <= value <= maximum:
        raise DomainError(f"{field} must be an integer from {minimum} to {maximum}")
    return value


def text(value, field, maximum=500, minimum=1):
    if not isinstance(value, str) or not minimum <= len(value.strip()) <= maximum:
        raise DomainError(f"{field} is required and must contain {minimum} to {maximum} characters")
    return value.strip()


def currency(value):
    if not isinstance(value, str) or not re.fullmatch("[A-Z]{3}", value):
        raise DomainError("currency must be a three-letter uppercase currency code")
    return value


def schedule(payload):
    start, end = instant(payload.get("start"), "start"), instant(payload.get("end"), "end")
    if end <= start:
        raise DomainError("end must follow start")
    name = text(payload.get("timezone"), "timezone", 100)
    try:
        ZoneInfo(name)
    except (ValueError, ZoneInfoNotFoundError):
        raise DomainError("timezone must be a valid IANA time zone") from None
    # Ensure supplied offsets actually describe local wall times in the declared
    # zone, including folds. Offset-aware inputs avoid inventing a DST fold.
    for key, utc in (("start", start), ("end", end)):
        supplied = datetime.fromisoformat(payload[key].replace("Z", "+00:00"))
        if (
            supplied.utcoffset() != utc.astimezone(ZoneInfo(name)).utcoffset()
            and supplied.utcoffset().total_seconds() != 0
        ):
            raise DomainError(f"{key} UTC offset does not match timezone at that instant")
    return {"start": iso(start), "end": iso(end), "timezone": name}


class ManualPaymentAdapter:
    """Only an authenticated owner route may call this audited adapter.

    Notes must describe independently checking the external provider account.
    Customer screenshots and redirect parameters are never passed to this method.
    """

    def verify(self, booking, payload, actor, now):
        actor = text(actor, "verifying owner", 128)
        reference = text(payload.get("reference"), "reference", 190)
        amount = integer(payload.get("amount_minor"), "amount_minor")
        code = currency(payload.get("currency"))
        if code != booking["currency"]:
            raise DomainError("Payment currency does not match the agreed booking currency")
        details = text(payload.get("verification_details"), "verification_details", 2000, 10)
        if any(key in payload for key in ("verified", "payment_status", "paid", "screenshot")):
            raise DomainError(
                "Payment verification requires the owner's independent provider-account check"
            )
        return {
            "id": uuid4().hex,
            "booking_id": booking["id"],
            "reference": reference,
            "amount_minor": amount,
            "currency": code,
            "verified_by": actor,
            "verified_at": iso(now),
            "verification_details": details,
            "provider": text(payload.get("provider", "manual"), "provider", 40),
            "adapter": "owner_manual",
        }


class BookingService:
    def __init__(
        self,
        store,
        clock=time.time,
        capacity=1000,
        reservation_seconds=172800,
        payment_adapter=None,
    ):
        self.store = store
        self.clock = clock
        self.capacity = integer(capacity, "capacity", 50, 10000000)
        self.reservation_seconds = integer(reservation_seconds, "reservation_seconds", 60, 604800)
        self.payment_adapter = payment_adapter or ManualPaymentAdapter()

    def _now(self):
        value = self.clock()
        return value.timestamp() if isinstance(value, datetime) else float(value)

    @staticmethod
    def _actor(actor):
        return text(actor, "owner", 128)

    @staticmethod
    def _get(tx, booking_id, payload=None):
        booking = tx.get_booking(booking_id)
        if not booking:
            raise DomainError("Booking was not found", 404, "not_found")
        expected = (payload or {}).get("expected_revision")
        if expected is not None and (type(expected) is not int or expected != booking["revision"]):
            raise DomainError(
                "Booking changed; reload before applying this action", 409, "revision_conflict"
            )
        return booking

    def _available(self, tx, booking, now):
        start, end = instant(booking["start"]), instant(booking["end"])
        # Sweep the overlap endpoints: summing all intersecting events would
        # incorrectly reject disjoint reservations within a long candidate.
        points = [(start, booking["quantity"]), (end, -booking["quantity"])]
        for other in tx.list_bookings():
            if other["id"] == booking["id"]:
                continue
            reserved = other["status"] == "confirmed" or (
                other["status"] == "awaiting_deposit"
                and (other.get("reservation_expires_at") or 0) > now
            )
            if not reserved:
                continue
            left, right = max(start, instant(other["start"])), min(end, instant(other["end"]))
            if left < right:
                points.extend(((left, other["quantity"]), (right, -other["quantity"])))
        used = 0
        # Releases precede acquisitions at the same instant (half-open events).
        for _, delta in sorted(points, key=lambda item: (item[0], item[1])):
            used += delta
            if used > self.capacity:
                return False
        return True

    def _reserve(self, tx, booking, payload, now):
        if instant(booking["start"]).timestamp() <= now:
            raise DomainError("The event must start in the future")
        if not self._available(tx, booking, now):
            raise DomainError(
                "Capacity is unavailable for this event interval", 409, "capacity_unavailable"
            )
        duration = integer(
            payload.get("reservation_seconds", self.reservation_seconds),
            "reservation_seconds",
            60,
            604800,
        )
        booking["reservation_expires_at"] = min(
            now + duration, instant(booking["start"]).timestamp()
        )
        booking["approved_at"] = iso(now)

    @staticmethod
    def _money(tx, booking):
        paid = sum(payment["amount_minor"] for payment in tx.payments(booking["id"]))
        if paid > MAX_MONEY:
            raise DomainError("Aggregate verified payments exceed the supported amount")
        booking["paid_minor"] = paid
        booking["remaining_minor"] = max(0, booking["total_minor"] - paid)
        booking["overpaid_minor"] = max(0, paid - booking["total_minor"])
        booking["payment_status"] = (
            "paid"
            if paid >= booking["total_minor"]
            else "deposit_paid"
            if paid >= booking["deposit_minor"]
            else "partial"
            if paid
            else "unpaid"
        )

    @staticmethod
    def _enqueue(tx, booking, kind, payload=None, key=None):
        tx.enqueue(
            key or f"{kind}:{booking['id']}:{booking['revision']}",
            kind,
            booking["id"],
            booking["revision"],
            payload or {},
        )

    def _save(self, tx, booking, actor, action, now, kinds=()):
        booking["revision"] += 1
        booking["updated_at"] = iso(now)
        tx.save_booking(booking)
        tx.audit(
            "booking." + action,
            actor,
            {"booking_id": booking["id"], "revision": booking["revision"]},
            iso(now),
        )
        for kind in kinds:
            payload = {"schedule_revision": booking["schedule_revision"]}
            if kind in {"confirmation_customer", "confirmation_owner"}:
                payload["confirmation_generation"] = booking["confirmation_generation"]
            self._enqueue(tx, booking, kind, payload)
        return booking

    def _confirm(self, booking, now):
        booking["status"] = "confirmed"
        booking["confirmed_at"] = iso(now)
        booking["reservation_expires_at"] = None
        booking["owner_review_reason"] = None
        booking["calendar_status"] = "pending"
        booking["calendar_error"] = None
        booking["schedule_revision"] += 1
        booking["confirmation_generation"] = booking.get("confirmation_generation", 0) + 1

    def create(self, payload, actor):
        with self.store.transaction(capacity=True) as tx:
            return self.create_in_transaction(tx, payload, actor)

    def create_in_transaction(self, tx, payload, actor, *, source_order=None):
        """Reuse owner validation inside an atomic customer-order handoff."""
        actor, now = self._actor(actor), self._now()
        data = schedule(payload)
        if instant(data["start"]).timestamp() <= now:
            raise DomainError("The event must start in the future")
        service_type = payload.get("service_type")
        if service_type not in {"delivery", "full_service"}:
            raise DomainError("service_type must be delivery or full_service")
        email = text(payload.get("customer_email"), "customer_email", 254)
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
            raise DomainError("customer_email must be a valid email address")
        contract = text(payload.get("contract_url"), "contract_url", 2000)
        try:
            parsed = urlsplit(contract)
        except ValueError:
            raise DomainError("contract_url must be an absolute HTTPS link") from None
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise DomainError("contract_url must be an absolute HTTPS link")
        total = integer(payload.get("total_minor"), "total_minor")
        booking_id = uuid4().hex
        booking = {
            "id": booking_id,
            "reference": "POP-" + booking_id[:10].upper(),
            **data,
            "venue": text(payload.get("venue"), "venue"),
            "quantity": integer(payload.get("quantity"), "quantity", 50, 10000000),
            "service_type": service_type,
            "customer_email": email,
            "contract_url": contract,
            "owner_id": actor,
            "status": "requested",
            "payment_status": "unpaid",
            "total_minor": total,
            "deposit_minor": (total + 1) // 2,
            "paid_minor": 0,
            "remaining_minor": total,
            "overpaid_minor": 0,
            "currency": currency(payload.get("currency")),
            "count_finalized": False,
            "revision": 0,
            "schedule_revision": 0,
            "confirmation_generation": 0,
            "calendar_status": "pending",
            "google_event_id": None,
            "google_calendar_id": None,
            "synced_revision": None,
            "last_synced_at": None,
            "calendar_error": None,
            "reservation_expires_at": None,
            "owner_review_reason": None,
            "created_at": iso(now),
        }
        if source_order is not None:
            booking["source_order_id"] = source_order["id"]
            booking["source_order"] = source_order
            booking["deposit_minor"] = source_order["pricing"]["deposit_due_cents"]
        return self._save(tx, booking, actor, "created", now)

    def approve(self, booking_id, payload, actor):
        actor, now = self._actor(actor), self._now()
        with self.store.booking_lock(booking_id), self.store.transaction(capacity=True) as tx:
            now = self._now()
            booking = self._get(tx, booking_id, payload)
            if booking["status"] not in {"requested", "awaiting_deposit", "owner_review"}:
                raise DomainError("Only requested or review bookings can be approved", 409)
            self._reserve(tx, booking, payload, now)
            self._money(tx, booking)
            booking["owner_review_reason"] = None
            kinds = ("deposit_request",)
            if booking["paid_minor"] >= booking["deposit_minor"]:
                self._confirm(booking, now)
                kinds = (
                    "calendar",
                    "confirmation_customer",
                    "confirmation_owner",
                    "reminder_schedule",
                )
            else:
                booking["status"] = "awaiting_deposit"
            return self._save(tx, booking, actor, "approved", now, kinds)

    def verify_payment(self, booking_id, payload, actor):
        actor, now = self._actor(actor), self._now()
        with self.store.booking_lock(booking_id), self.store.transaction(capacity=True) as tx:
            now = self._now()
            booking = self._get(tx, booking_id, payload)
            payment = self.payment_adapter.verify(booking, payload, actor, now)
            previous = tx.get_payment(payment["reference"])
            if previous:
                if any(
                    previous[key] != payment[key]
                    for key in ("booking_id", "amount_minor", "currency")
                ):
                    raise DomainError(
                        "Payment reference already belongs to a different payment",
                        409,
                        "payment_reference_conflict",
                    )
                return booking
            if not tx.add_payment(payment):
                raise DomainError(
                    "Payment reference was already verified", 409, "payment_reference_conflict"
                )
            self._money(tx, booking)
            kinds = ()
            if (
                booking["status"] != "cancelled"
                and booking["status"] != "confirmed"
                and booking["paid_minor"] >= booking["deposit_minor"]
            ):
                valid = (
                    booking["status"] == "awaiting_deposit"
                    and (booking.get("reservation_expires_at") or 0) > now
                    and instant(booking["start"]).timestamp() > now
                    and self._available(tx, booking, now)
                )
                if valid:
                    self._confirm(booking, now)
                    kinds = (
                        "calendar",
                        "confirmation_customer",
                        "confirmation_owner",
                        "reminder_schedule",
                    )
                else:
                    booking["status"] = "owner_review"
                    booking["reservation_expires_at"] = None
                    booking["owner_review_reason"] = (
                        "Payment retained; owner must approve availability and a new capacity reservation"
                    )
            elif booking["status"] == "confirmed":
                # Keep Google synced_revision truthful after financial changes;
                # worker reads the latest state and updates its stable event.
                booking["calendar_status"] = "pending"
                kinds = ("calendar",)
            elif booking["status"] == "cancelled":
                booking["owner_review_reason"] = (
                    "Payment received after cancellation; retained for owner review. Handle any refund separately."
                )
            tx.audit(
                "payment.verified",
                actor,
                {
                    "booking_id": booking_id,
                    "reference": payment["reference"],
                    "amount_minor": payment["amount_minor"],
                    "currency": payment["currency"],
                },
                iso(now),
            )
            return self._save(tx, booking, actor, "payment_recorded", now, kinds)

    def reschedule(self, booking_id, payload, actor):
        actor, now = self._actor(actor), self._now()
        data = schedule(payload)
        with self.store.booking_lock(booking_id), self.store.transaction(capacity=True) as tx:
            now = self._now()
            booking = self._get(tx, booking_id, payload)
            if booking["status"] == "cancelled":
                raise DomainError("Reopen a cancelled booking before rescheduling", 409)
            booking.update(data)
            if "venue" in payload:
                booking["venue"] = text(payload["venue"], "venue")
            if instant(booking["start"]).timestamp() <= now:
                raise DomainError("The event must start in the future")
            if booking["status"] in {"confirmed", "awaiting_deposit"}:
                self._reserve(tx, booking, payload, now)
                if booking["status"] == "confirmed":
                    booking["reservation_expires_at"] = None
            booking["schedule_revision"] += 1
            booking["calendar_status"] = "pending"
            kinds = ("calendar", "reminder_schedule") if booking["status"] == "confirmed" else ()
            return self._save(tx, booking, actor, "rescheduled", now, kinds)

    def cancel(self, booking_id, actor, expected_revision=None):
        actor, now = self._actor(actor), self._now()
        with self.store.booking_lock(booking_id), self.store.transaction(capacity=True) as tx:
            now = self._now()
            booking = self._get(tx, booking_id, {"expected_revision": expected_revision})
            if booking["status"] == "cancelled":
                return booking
            booking["status"] = "cancelled"
            booking["cancelled_at"] = iso(now)
            booking["reservation_expires_at"] = None
            booking["calendar_status"] = "pending"
            booking["schedule_revision"] += 1
            return self._save(
                tx, booking, actor, "cancelled", now, ("calendar", "reminder_schedule")
            )

    def finalize_count(self, booking_id, payload, actor):
        actor, now = self._actor(actor), self._now()
        with self.store.booking_lock(booking_id), self.store.transaction(capacity=True) as tx:
            now = self._now()
            booking = self._get(tx, booking_id, payload)
            if booking["status"] == "cancelled":
                raise DomainError("A cancelled booking cannot finalize its count", 409)
            if "quantity" in payload:
                booking["quantity"] = integer(payload["quantity"], "quantity", 50, 10000000)
                if booking["status"] in {"confirmed", "awaiting_deposit"} and not self._available(
                    tx, booking, now
                ):
                    raise DomainError(
                        "Capacity is unavailable for this quantity", 409, "capacity_unavailable"
                    )
            booking["count_finalized"] = True
            booking["calendar_status"] = "pending"
            kinds = ("calendar",) if booking["status"] == "confirmed" else ()
            return self._save(tx, booking, actor, "count_finalized", now, kinds)

    def reopen(self, booking_id, payload, actor):
        actor, now = self._actor(actor), self._now()
        reason = text(payload.get("reason"), "reopen reason", 500)
        with self.store.booking_lock(booking_id), self.store.transaction(capacity=True) as tx:
            now = self._now()
            booking = self._get(tx, booking_id, payload)
            if booking["status"] != "cancelled":
                raise DomainError("Only cancelled bookings can be reopened", 409)
            self._reserve(tx, booking, payload, now)
            self._money(tx, booking)
            booking["reopened_at"] = iso(now)
            booking["reopen_reason"] = reason
            if booking["paid_minor"] >= booking["deposit_minor"]:
                self._confirm(booking, now)
                kinds = (
                    "calendar",
                    "confirmation_customer",
                    "confirmation_owner",
                    "reminder_schedule",
                )
            else:
                booking["status"] = "awaiting_deposit"
                booking["schedule_revision"] += 1
                booking["calendar_status"] = "pending"
                # Pending deletes may be obsolete; still reconcile any old event.
                kinds = ("calendar", "reminder_schedule", "deposit_request")
            return self._save(tx, booking, actor, "reopened", now, kinds)

    def retry(self, booking_id, actor, repair=False):
        actor, now = self._actor(actor), self._now()
        with self.store.booking_lock(booking_id), self.store.transaction() as tx:
            now = self._now()
            booking = self._get(tx, booking_id)
            booking["calendar_status"] = "pending"
            booking["calendar_error"] = None
            if repair:
                booking["calendar_repair_requested"] = True
            result = self._save(
                tx,
                booking,
                actor,
                "repair_requested" if repair else "retry_requested",
                now,
                ("reminder_schedule",),
            )
            self._enqueue(tx, booking, "calendar", {"repair": bool(repair)})
            return result
