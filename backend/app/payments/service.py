"""Square Checkout intents, authenticated notifications and an atomic payment ledger."""

import json
import re
from contextlib import nullcontext
from urllib.parse import urlsplit
from uuid import uuid4

from ..automation.domain import DomainError, instant, iso
from .square import SquareFailure, SquareGateway, valid_signature


class CheckoutService:
    def __init__(self, settings, store, bookings):
        self.settings, self.store, self.bookings = settings, store, bookings
        self.enabled = bool(settings.get("SQUARE_ENABLED"))
        self.gateway = settings.get("SQUARE_GATEWAY") or (
            SquareGateway(settings) if self.enabled else None
        )

    def available(self):
        return {
            "enabled": self.enabled,
            "environment": self.settings.get("SQUARE_ENVIRONMENT", "sandbox"),
        }

    def require_enabled(self):
        if not self.enabled:
            raise DomainError("Square Checkout is not configured yet.", 503, "square_unavailable")

    @staticmethod
    def due(booking, purpose, now):
        if purpose == "deposit":
            if (
                booking["status"] != "awaiting_deposit"
                or (booking.get("reservation_expires_at") or 0) <= now
            ):
                raise DomainError(
                    "Approve availability and reserve capacity before requesting a deposit.", 409
                )
            amount = booking["deposit_minor"] - booking["paid_minor"]
        elif purpose == "balance":
            if booking["status"] != "confirmed":
                raise DomainError(
                    "Confirm the booking before requesting its remaining balance.", 409
                )
            amount = booking["remaining_minor"]
        else:
            raise DomainError("Choose deposit or balance.", 422)
        if booking["currency"] != "USD" or not 100 <= amount <= 99999999:
            raise DomainError("Checkout requires a USD payment between $1.00 and $999,999.99.", 409)
        return amount

    @staticmethod
    def fingerprint(booking):
        return [
            booking.get("decision_generation", 0),
            booking["schedule_revision"],
            booking.get("reservation_expires_at"),
        ]

    def eligible(self, row, booking, now):
        try:
            amount = self.due(booking, row["purpose"], now)
        except DomainError:
            return False
        return (
            amount == row["amount_minor"]
            and booking["currency"] == row["currency"]
            and self.fingerprint(booking) == row["fingerprint"]
        )

    @staticmethod
    def _provider(call):
        try:
            return call()
        except (SquareFailure, KeyError, TypeError):
            raise DomainError(
                "Square is temporarily unavailable. Retry this same action.",
                503,
                "square_unavailable",
            ) from None

    def _validate_order(self, row, order):
        metadata = row["params"]["order"]["metadata"]
        if (
            not order.get("id")
            or (row.get("provider_order_id") and order["id"] != row["provider_order_id"])
            or order.get("reference_id") != row["id"]
            or order.get("location_id") != row["location_id"]
            or order.get("total_money")
            != {"amount": row["amount_minor"], "currency": row["currency"]}
            or any(
                (order.get("metadata") or {}).get(key) != value for key, value in metadata.items()
            )
            or row["environment"] != self.settings["SQUARE_ENVIRONMENT"]
            or row["merchant_id"] != self.settings["SQUARE_MERCHANT_ID"]
        ):
            raise DomainError(
                "Square order details do not match this Checkout.", 409, "square_mismatch"
            )

    def _create_intent(self, row):
        # Quarantine ambiguous old requests instead of rotating a possibly-used idempotency key.
        if self.bookings._now() - row["created_at"] >= 23 * 3600:
            raise DomainError(
                "An unresolved Checkout needs owner review in Square before another link can be created.",
                409,
                "square_review_required",
            )
        result = self._provider(lambda: self.gateway.create(row["params"], "checkout:" + row["id"]))
        link = result.get("payment_link") or {}
        if not link.get("id") or not link.get("order_id"):
            raise DomainError("Square returned an incomplete payment link.", 503)
        if row.get("provider_link_id") and row["provider_link_id"] != link["id"]:
            raise DomainError("Square payment link mismatch.", 409, "square_mismatch")
        orders = result.get("related_resources", {}).get("orders", [])
        order = next((o for o in orders if o.get("id") == link["order_id"]), None)
        if not order:
            order = self._provider(lambda: self.gateway.order(link["order_id"]))
        self._validate_order(row, order)
        if order["id"] != link["order_id"]:
            raise DomainError("Square payment link order mismatch.", 409, "square_mismatch")
        parsed = urlsplit(link.get("url") or "")
        hosts = (
            {"sandbox.square.link", "connect.squareupsandbox.com"}
            if row["environment"] == "sandbox"
            else {"square.link", "checkout.square.site"}
        )
        if (
            parsed.scheme != "https"
            or parsed.hostname not in hosts
            or parsed.username
            or parsed.password
            or parsed.port not in {None, 443}
        ):
            raise DomainError("Square returned an invalid Checkout destination.", 503)
        row.update(
            provider_link_id=link["id"],
            provider_order_id=link["order_id"],
            provider_url=link["url"],
            status="expired" if order.get("state") == "CANCELED" else "open",
        )
        with self.store.transaction() as tx:
            tx.save_checkout(row)
        return row

    def _close(self, row):
        if row["status"] == "creating":
            row = self._create_intent(row)
        if row["status"] != "open":
            return
        order = self._provider(lambda: self.gateway.order(row["provider_order_id"]))
        self._validate_order(row, order)
        # Deleting a payment link cancels its order. Never cancel an order with a
        # settled or in-flight tender while awaiting its authoritative notification.
        for tender in order.get("tenders", []):
            payment = self._provider(
                lambda t=tender: self.gateway.payment(t.get("payment_id") or t["id"])
            )
            if payment.get("status") in {"APPROVED", "PENDING", "COMPLETED"}:
                raise DomainError(
                    "Square is confirming an earlier payment. Wait for verification before requesting another.",
                    409,
                )
        if order.get("state") != "CANCELED":
            result = self._provider(lambda: self.gateway.delete(row["provider_link_id"]))
            if result is not None and (
                result.get("id") != row["provider_link_id"]
                or result.get("cancelled_order_id") != row["provider_order_id"]
            ):
                raise DomainError(
                    "Square cancellation did not match the payment link.", 409, "square_mismatch"
                )
        row.update(status="expired", provider_url=None)
        with self.store.transaction() as tx:
            tx.save_checkout(row)

    def create(
        self, booking_id, purpose, *, expected_revision=None, actor=None, email=False, locked=False
    ):
        self.require_enabled()
        with nullcontext() if locked else self.store.booking_lock(booking_id):
            now = self.bookings._now()
            with self.store.transaction() as tx:
                booking = self.bookings._get(
                    tx, booking_id, {"expected_revision": expected_revision}
                )
                self.bookings._money(tx, booking)
                amount = self.due(booking, purpose, now)
                rows = tx.checkouts(booking_id)
                if any(
                    row["environment"] != self.settings["SQUARE_ENVIRONMENT"]
                    or row["merchant_id"] != self.settings["SQUARE_MERCHANT_ID"]
                    or row["location_id"] != self.settings["SQUARE_LOCATION_ID"]
                    for row in rows
                ):
                    raise DomainError(
                        "This booking belongs to a different Square environment or account. Use a separate booking.",
                        409,
                        "square_environment_conflict",
                    )
            row = None
            for previous in rows:
                if previous["status"] in {"open", "creating"}:
                    if (
                        previous["purpose"] == purpose
                        and self.eligible(previous, booking, now)
                        and previous["expires_at"] > now
                    ):
                        row = previous
                    else:
                        self._close(previous)
            if row is None:
                deadline = now + 86400
                if purpose == "deposit":
                    deadline = min(
                        deadline,
                        booking["reservation_expires_at"],
                        instant(booking["start"]).timestamp(),
                    )
                if deadline < now + 60:
                    raise DomainError(
                        "The payment window is ending. Renew availability or arrange payment with the owner.",
                        409,
                    )
                checkout_id = uuid4().hex
                metadata = {
                    "checkout_id": checkout_id,
                    "booking_id": booking_id,
                    "purpose": purpose,
                }
                params = {
                    "description": f"Popssibilities {purpose} {booking['reference']}",
                    "order": {
                        "location_id": self.settings["SQUARE_LOCATION_ID"],
                        "reference_id": checkout_id,
                        "metadata": metadata,
                        "line_items": [
                            {
                                "name": f"Popssibilities {purpose} · {booking['reference']}",
                                "quantity": "1",
                                "base_price_money": {
                                    "amount": amount,
                                    "currency": booking["currency"],
                                },
                            }
                        ],
                        "pricing_options": {
                            "auto_apply_discounts": False,
                            "auto_apply_taxes": False,
                        },
                    },
                    "checkout_options": {
                        "allow_tipping": False,
                        "ask_for_shipping_address": False,
                        "redirect_url": f"{self.settings['AUTH_ORIGIN']}/payment/return?checkout={checkout_id}",
                        "accepted_payment_methods": {
                            "apple_pay": True,
                            "google_pay": True,
                            "cash_app_pay": False,
                            "afterpay_clearpay": False,
                            "bank_account": False,
                        },
                    },
                    "pre_populated_data": {"buyer_email": booking["customer_email"]},
                    "payment_note": "Popssibilities checkout:" + checkout_id,
                }
                row = {
                    "id": checkout_id,
                    "booking_id": booking_id,
                    "purpose": purpose,
                    "amount_minor": amount,
                    "currency": booking["currency"],
                    "fingerprint": self.fingerprint(booking),
                    "created_at": now,
                    "expires_at": int(deadline),
                    "status": "creating",
                    "params": params,
                    "environment": self.settings["SQUARE_ENVIRONMENT"],
                    "merchant_id": self.settings["SQUARE_MERCHANT_ID"],
                    "location_id": self.settings["SQUARE_LOCATION_ID"],
                }
                with self.store.transaction() as tx:
                    tx.save_checkout(row)
                    tx.audit(
                        "square.checkout.requested",
                        actor,
                        {"checkout_id": row["id"], "booking_id": booking_id},
                    )
            if row["status"] == "creating":
                row = self._create_intent(row)
            if row["status"] != "open":
                raise DomainError(
                    "This Checkout has ended. Refresh the booking to request a new link.", 409
                )
            if email:
                with self.store.transaction() as tx:
                    tx.enqueue(
                        "checkout_email:" + row["id"],
                        "checkout_email",
                        booking_id,
                        booking["revision"],
                        {"checkout_id": row["id"]},
                    )
            return self.owner_view(row)

    def owner_view(self, row):
        return {
            **{
                key: row.get(key)
                for key in ("id", "purpose", "amount_minor", "currency", "status", "expires_at")
            },
            "url": f"{self.settings['AUTH_ORIGIN']}/payment/pay?checkout={row['id']}",
        }

    def reconcile(self, booking_id):
        if not self.enabled:
            return False
        with self.store.booking_lock(booking_id):
            with self.store.transaction() as tx:
                booking, rows = tx.get_booking(booking_id), tx.checkouts(booking_id)
            for row in rows:
                if row["status"] in {"creating", "open"} and (
                    row["expires_at"] <= self.bookings._now()
                    or not self.eligible(row, booking, self.bookings._now())
                ):
                    self._close(row)
        return None

    def enqueue_expired(self, limit=100):
        if not self.enabled:
            return 0
        with self.store.transaction() as tx:
            rows = tx.expired_checkouts(self.bookings._now(), limit)
            return sum(
                tx.enqueue(
                    "square_expire:" + row["id"],
                    "square_reconcile",
                    row["booking_id"],
                    0,
                    {"checkout_id": row["id"]},
                )
                for row in rows
            )

    def email_checkout(self, checkout_id, booking):
        if not self.enabled:
            return None
        with self.store.transaction() as tx:
            row = tx.get_checkout(checkout_id)
        if (
            not row
            or row["status"] != "open"
            or row["expires_at"] <= self.bookings._now()
            or not self.eligible(row, booking, self.bookings._now())
        ):
            return None
        return self.owner_view(row)

    def public_status(self, checkout_id):
        self.require_enabled()
        self._valid_id(checkout_id)
        with self.store.transaction() as tx:
            row = tx.get_checkout(checkout_id)
            if not row:
                raise DomainError("Payment link not found.", 404, "not_found")
            booking = self.bookings._get(tx, row["booking_id"])
        payable = (
            row["status"] == "open"
            and row["expires_at"] > self.bookings._now()
            and row["environment"] == self.settings["SQUARE_ENVIRONMENT"]
            and self.eligible(row, booking, self.bookings._now())
        )
        status = (
            "paid"
            if row["status"] == "paid"
            else "pending"
            if payable or row["status"] == "creating"
            else "expired"
        )
        return {
            "status": status,
            "can_pay": payable,
            "amount_minor": row["amount_minor"],
            "currency": row["currency"],
            "purpose": row["purpose"],
            "environment": row["environment"],
        }

    @staticmethod
    def _valid_id(checkout_id):
        if not isinstance(checkout_id, str) or not re.fullmatch(r"[a-f0-9]{32}", checkout_id):
            raise DomainError("Payment link not found.", 404, "not_found")

    def start(self, checkout_id):
        self.require_enabled()
        self._valid_id(checkout_id)
        with self.store.transaction() as tx:
            row = tx.get_checkout(checkout_id)
            if not row:
                raise DomainError("Payment link not found.", 404, "not_found")
        with self.store.booking_lock(row["booking_id"]), self.store.transaction() as tx:
            row = tx.get_checkout(checkout_id)
            booking = self.bookings._get(tx, row["booking_id"])
            self.bookings._money(tx, booking)
            if (
                row["status"] != "open"
                or row["expires_at"] <= self.bookings._now()
                or row["environment"] != self.settings["SQUARE_ENVIRONMENT"]
                or row["merchant_id"] != self.settings["SQUARE_MERCHANT_ID"]
                or not self.eligible(row, booking, self.bookings._now())
            ):
                raise DomainError(
                    "This payment link is no longer available. Contact Popssibilities for your booking status or a new link.",
                    409,
                )
            return {"url": row["provider_url"]}

    def webhook(self, raw_body, signature):
        self.require_enabled()
        if not valid_signature(
            raw_body,
            signature,
            self.settings["SQUARE_WEBHOOK_SIGNATURE_KEY"],
            self.settings["SQUARE_WEBHOOK_NOTIFICATION_URL"],
        ):
            raise DomainError("Invalid Square webhook signature.", 400, "invalid_signature")
        try:
            event = json.loads(raw_body)
            if not isinstance(event, dict):
                raise ValueError
            if event.get("merchant_id") != self.settings["SQUARE_MERCHANT_ID"]:
                raise DomainError("Square webhook merchant mismatch.", 400, "square_mismatch")
            if event.get("type") not in {"payment.created", "payment.updated"}:
                return
            event_id, obj = event["event_id"], event["data"]["object"]["payment"]
            payment_id = obj["id"]
            if (
                not isinstance(event_id, str)
                or not 1 <= len(event_id) <= 255
                or not isinstance(payment_id, str)
            ):
                raise ValueError
        except (ValueError, KeyError, TypeError):
            raise DomainError("Invalid Square notification body.", 400, "invalid_webhook") from None
        with self.store.transaction() as tx:
            if tx.get_square_event(event_id):
                return
            row = tx.get_checkout_by_order(obj.get("order_id", ""))
            # A payment can finish before a timed-out creation response was saved.
            if not row:
                note = obj.get("note")
                match = (
                    re.fullmatch(r"Popssibilities checkout:([a-f0-9]{32})", note)
                    if isinstance(note, str)
                    else None
                )
                row = tx.get_checkout(match[1]) if match else None
            if not row:
                return  # A POS/other application payment, not one of our payment links.
        with self.store.booking_lock(row["booking_id"]):
            with self.store.transaction() as tx:
                row = tx.get_checkout(row["id"])
                if tx.get_square_event(event_id):
                    return
            provider = self._provider(lambda: self.gateway.payment(payment_id))
            if obj.get("status") == "COMPLETED" and provider.get("status") != "COMPLETED":
                raise DomainError(
                    "Square is still confirming the payment. Retry this notification.",
                    503,
                    "square_unavailable",
                )
            if (
                provider.get("id") != payment_id
                or provider.get("location_id") != row["location_id"]
                or provider.get("note") != row["params"]["payment_note"]
                or provider.get("amount_money")
                != {"amount": row["amount_minor"], "currency": row["currency"]}
                or provider.get("total_money") != provider.get("amount_money")
                or provider.get("source_type") != "CARD"
            ):
                raise DomainError(
                    "Square payment details do not match this Checkout.", 409, "square_mismatch"
                )
            order = self._provider(lambda: self.gateway.order(provider["order_id"]))
            self._validate_order(row, order)
            if order["id"] != provider["order_id"]:
                raise DomainError("Square payment order mismatch.", 409, "square_mismatch")
            paid = provider.get("status") == "COMPLETED"
            if paid and provider.get("card_details", {}).get("status") != "CAPTURED":
                raise DomainError(
                    "Square card payment has not been captured.", 409, "square_mismatch"
                )
            with self.store.transaction(capacity=True) as tx:
                if tx.get_square_event(event_id):
                    return
                booking = self.bookings._get(tx, row["booking_id"])
                if paid:
                    if booking["status"] == "awaiting_deposit" and not self.eligible(
                        row, booking, self.bookings._now()
                    ):
                        booking.update(status="owner_review", reservation_expires_at=None)
                    payment = {
                        "id": uuid4().hex,
                        "booking_id": row["booking_id"],
                        "reference": "square:" + payment_id,
                        "amount_minor": row["amount_minor"],
                        "currency": row["currency"],
                        "provider": "square",
                        "adapter": "square_webhook",
                        "square_environment": row["environment"],
                        "verified_by": "square_webhook",
                        "verified_at": iso(self.bookings._now()),
                        "verification_details": "Verified Square payment " + payment_id,
                    }
                    self.bookings.record_payment_in_transaction(
                        tx, booking, payment, "square_webhook", self.bookings._now()
                    )
                    row["status"] = "paid"
                row["provider_order_id"] = order["id"]
                tx.save_checkout(row)
                tx.save_square_event(
                    {"id": event_id, "type": event["type"], "checkout_id": row["id"]}
                )
