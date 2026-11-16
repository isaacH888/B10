"""Square-shaped provider, signed webhooks, payment races and real MySQL parity."""

import base64
import hmac
import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from unittest.mock import Mock

import pytest
from app import create_app
from app.automation.delivery import JobProcessor, MemoryMail, MemoryQueue, OutboxDispatcher
from app.automation.domain import BookingService, DomainError
from app.automation.store import MemoryStore, Store
from app.email.resend import ResendClient, ResendMail
from app.payments.service import CheckoutService
from app.payments.settings import API_VERSION, environment_settings, validate_settings
from app.payments.square import SquareFailure, SquareGateway, valid_signature
from test_auth import auth_app as auth_app
from test_automation_domain import NOW, payload, payment
from test_automation_routes import BASE, signed_owner
from test_automation_routes import owner_app as owner_app
from test_automation_store import sql_settings as sql_settings

SIGNATURE_KEY = "synthetic_square_webhook_key"
NOTIFICATION_URL = "https://api.example.invalid/api/v1/payments/square/webhook"


class Gateway:
    def __init__(self):
        self.links, self.orders, self.payments, self.calls, self.keys, self.deleted = (
            {},
            {},
            {},
            [],
            {},
            [],
        )
        self.timeout = False

    def create(self, params, key):
        self.calls.append((deepcopy(params), key))
        if key not in self.keys:
            checkout_id = params["order"]["reference_id"]
            self.keys[key] = checkout_id
            self.orders["order_" + checkout_id] = {
                **deepcopy(params["order"]),
                "id": "order_" + checkout_id,
                "state": "DRAFT",
                "total_money": deepcopy(params["order"]["line_items"][0]["base_price_money"]),
            }
            self.links[checkout_id] = {
                "id": "link_" + checkout_id,
                "order_id": "order_" + checkout_id,
                "url": "https://sandbox.square.link/u/" + checkout_id,
            }
        if self.timeout:
            raise SquareFailure("private token and provider error must not escape")
        checkout_id = self.keys[key]
        return {
            "payment_link": deepcopy(self.links[checkout_id]),
            "related_resources": {"orders": [self.order("order_" + checkout_id)]},
        }

    def order(self, order_id):
        return deepcopy(self.orders[order_id])

    def payment(self, payment_id):
        return deepcopy(self.payments[payment_id])

    def delete(self, link_id):
        checkout_id = link_id.removeprefix("link_")
        self.deleted.append(link_id)
        self.orders["order_" + checkout_id]["state"] = "CANCELED"
        return {"id": link_id, "cancelled_order_id": "order_" + checkout_id}

    def settle(self, checkout_id, status="COMPLETED"):
        order = self.orders["order_" + checkout_id]
        provider = {
            "id": "payment_" + checkout_id,
            "order_id": order["id"],
            "location_id": order["location_id"],
            "source_type": "CARD",
            "status": status,
            "card_details": {"status": "CAPTURED" if status == "COMPLETED" else "AUTHORIZED"},
            "amount_money": deepcopy(order["total_money"]),
            "total_money": deepcopy(order["total_money"]),
            "note": "Popssibilities checkout:" + checkout_id,
        }
        self.payments[provider["id"]] = provider
        order["tenders"] = [{"id": provider["id"]}]
        order["state"] = "OPEN"
        return deepcopy(provider)


def setup(store=None):
    store, clock, gateway = store or MemoryStore(), [NOW], Gateway()
    bookings = BookingService(store, clock=lambda: clock[0], checkout_enabled=True)
    settings = {
        "SQUARE_ENABLED": True,
        "SQUARE_ENVIRONMENT": "sandbox",
        "SQUARE_ACCESS_TOKEN": "synthetic-token",
        "SQUARE_MERCHANT_ID": "merchant_test",
        "SQUARE_LOCATION_ID": "location_test",
        "SQUARE_WEBHOOK_SIGNATURE_KEY": SIGNATURE_KEY,
        "SQUARE_WEBHOOK_NOTIFICATION_URL": NOTIFICATION_URL,
        "SQUARE_GATEWAY": gateway,
        "AUTH_ORIGIN": "https://example.invalid",
        "AUTOMATION_ENABLED": True,
    }
    service = CheckoutService(settings, store, bookings)
    booking = bookings.create(payload(), "owner")
    booking = bookings.approve(booking["id"], {}, "owner")
    return store, bookings, service, booking, clock, gateway


def sign(raw, url=NOTIFICATION_URL):
    return base64.b64encode(
        hmac.digest(SIGNATURE_KEY.encode(), url.encode() + raw, "sha256")
    ).decode()


def signed(checkout_id, event_id="event_test", event_type="payment.updated", **changes):
    event = {
        "merchant_id": "merchant_test",
        "event_id": event_id,
        "type": event_type,
        "data": {
            "type": "payment",
            "id": "payment_" + checkout_id,
            "object": {
                "payment": {
                    "id": "payment_" + checkout_id,
                    "order_id": "order_" + checkout_id,
                    "note": "Popssibilities checkout:" + checkout_id,
                }
            },
        },
        **changes,
    }
    raw = json.dumps(event, separators=(",", ":")).encode()
    return raw, sign(raw)


def test_server_priced_deposit_then_balance_requires_verified_square_payment():
    store, _, service, booking, _, gateway = setup()
    link = service.create(
        booking["id"], "deposit", expected_revision=booking["revision"], email=True
    )
    params, key = gateway.calls[0]
    assert params["order"]["line_items"][0]["base_price_money"] == {
        "amount": 5001,
        "currency": "USD",
    }
    assert params["checkout_options"]["allow_tipping"] is False
    assert params["checkout_options"]["accepted_payment_methods"]["bank_account"] is False
    assert params["pre_populated_data"]["buyer_email"] == booking["customer_email"]
    assert key == "checkout:" + link["id"]
    assert link["url"] == "https://example.invalid/payment/pay?checkout=" + link["id"]
    assert service.start(link["id"])["url"].startswith("https://sandbox.square.link/")
    gateway.settle(link["id"])
    assert service.public_status(link["id"])["status"] == "pending"
    service.webhook(*signed(link["id"]))
    with store.transaction() as tx:
        result = tx.get_booking(booking["id"])
        assert (result["status"], result["paid_minor"], result["remaining_minor"]) == (
            "confirmed",
            5001,
            5000,
        )
        assert len([j for j in tx.list_outbox() if j["kind"] == "confirmation_customer"]) == 1
    balance = service.create(booking["id"], "balance")
    assert balance["amount_minor"] == 5000
    gateway.settle(balance["id"])
    service.webhook(*signed(balance["id"], "event_balance"))
    with store.transaction() as tx:
        assert tx.get_booking(booking["id"])["payment_status"] == "paid"
        assert len(tx.payments(booking["id"])) == 2
    assert service.public_status(balance["id"]) == {
        "status": "paid",
        "can_pay": False,
        "amount_minor": 5000,
        "currency": "USD",
        "purpose": "balance",
        "environment": "sandbox",
    }
    with pytest.raises(DomainError):
        service.start(balance["id"])


def test_partial_manual_payment_reduces_outstanding_deposit():
    _, bookings, service, booking, _, _ = setup()
    bookings.verify_payment(booking["id"], payment(amount=1000), "owner")
    assert service.create(booking["id"], "deposit")["amount_minor"] == 4001


def test_timeout_retry_reuses_durable_creation_and_exact_square_parameters():
    store, _, service, booking, _, gateway = setup()
    gateway.timeout = True
    with pytest.raises(DomainError) as error:
        service.create(booking["id"], "deposit")
    assert error.value.status == 503
    assert "private" not in str(error.value)
    with store.transaction() as tx:
        assert tx.checkouts(booking["id"])[0]["status"] == "creating"
    gateway.timeout = False
    link = service.create(booking["id"], "deposit")
    assert gateway.calls[0] == gateway.calls[1]
    assert len(gateway.links) == 1
    assert service.create(booking["id"], "deposit") == link
    assert len(gateway.calls) == 2


def test_webhook_can_recover_creation_before_provider_ids_were_saved():
    store, _, service, booking, _, gateway = setup()
    gateway.timeout = True
    with pytest.raises(DomainError):
        service.create(booking["id"], "deposit")
    with store.transaction() as tx:
        row = tx.checkouts(booking["id"])[0]
    gateway.settle(row["id"])
    service.webhook(*signed(row["id"]))
    assert service.public_status(row["id"])["status"] == "paid"
    with store.transaction() as tx:
        assert tx.get_checkout(row["id"])["provider_order_id"] == "order_" + row["id"]
        assert len(tx.payments(booking["id"])) == 1


def test_concurrent_creation_and_duplicate_notifications_record_one_payment():
    store, _, service, booking, _, gateway = setup()
    with ThreadPoolExecutor(max_workers=5) as pool:
        links = list(
            pool.map(lambda _: service.create(booking["id"], "deposit", email=True), range(5))
        )
    assert len({link["id"] for link in links}) == 1
    assert len(gateway.calls) == 1
    gateway.settle(links[0]["id"])
    with ThreadPoolExecutor(max_workers=5) as pool:
        list(
            pool.map(
                lambda index: service.webhook(*signed(links[0]["id"], f"event_{index % 2}")),
                range(10),
            )
        )
    with store.transaction() as tx:
        assert len(tx.payments(booking["id"])) == 1
        assert tx.get_booking(booking["id"])["paid_minor"] == 5001
        assert len([j for j in tx.list_outbox() if j["kind"] == "checkout_email"]) == 1
        assert len([j for j in tx.list_outbox() if j["kind"] == "confirmation_customer"]) == 1


@pytest.mark.parametrize("header", ["", "bad", "\u00e9", "t=1,v1=not-square"])
def test_invalid_signatures_never_record_money(header):
    store, _, service, booking, _, gateway = setup()
    link = service.create(booking["id"], "deposit")
    gateway.settle(link["id"])
    raw, _ = signed(link["id"])
    with pytest.raises(DomainError, match="signature"):
        service.webhook(raw, header)
    with store.transaction() as tx:
        assert tx.payments(booking["id"]) == []


def test_signature_covers_exact_notification_url_and_raw_body():
    raw = b'{"hello":"world"}'
    header = sign(raw)
    assert valid_signature(raw, header, SIGNATURE_KEY, NOTIFICATION_URL)
    assert not valid_signature(raw + b" ", header, SIGNATURE_KEY, NOTIFICATION_URL)
    assert not valid_signature(raw, header, SIGNATURE_KEY, NOTIFICATION_URL + "/")
    assert not valid_signature(raw, header, "wrong-key", NOTIFICATION_URL)


def test_completed_notification_waits_for_provider_read_consistency():
    store, _, service, booking, _, gateway = setup()
    link = service.create(booking["id"], "deposit")
    gateway.settle(link["id"], "PENDING")
    raw, _ = signed(link["id"])
    event = json.loads(raw)
    event["data"]["object"]["payment"]["status"] = "COMPLETED"
    raw = json.dumps(event).encode()
    with pytest.raises(DomainError) as error:
        service.webhook(raw, sign(raw))
    assert error.value.status == 503
    with store.transaction() as tx:
        assert tx.get_square_event("event_test") is None
        assert not tx.payments(booking["id"])
    gateway.settle(link["id"])
    service.webhook(raw, sign(raw))
    assert service.public_status(link["id"])["status"] == "paid"


@pytest.mark.parametrize(
    "field,value",
    [
        ("amount_money", {"amount": 1, "currency": "USD"}),
        ("amount_money", {"amount": 5001, "currency": "EUR"}),
        ("total_money", {"amount": 6000, "currency": "USD"}),
        ("location_id", "other_location"),
        ("note", "other_checkout"),
        ("source_type", "EXTERNAL"),
        ("card_details", {"status": "AUTHORIZED"}),
        ("id", "other_payment"),
    ],
)
def test_mismatched_square_payment_never_credits_ledger(field, value):
    store, _, service, booking, _, gateway = setup()
    link = service.create(booking["id"], "deposit")
    gateway.settle(link["id"])
    gateway.payments["payment_" + link["id"]][field] = value
    with pytest.raises(DomainError) as error:
        service.webhook(*signed(link["id"]))
    assert error.value.code == "square_mismatch"
    with store.transaction() as tx:
        assert tx.payments(booking["id"]) == []
        assert tx.get_square_event("event_test") is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("total_money", {"amount": 1, "currency": "USD"}),
        ("metadata", {}),
        ("location_id", "other"),
        ("reference_id", "other"),
        ("id", "other_order"),
    ],
)
def test_mismatched_square_order_never_credits_ledger(field, value):
    store, _, service, booking, _, gateway = setup()
    link = service.create(booking["id"], "deposit")
    gateway.settle(link["id"])
    gateway.orders["order_" + link["id"]][field] = value
    with pytest.raises(DomainError) as error:
        service.webhook(*signed(link["id"]))
    assert error.value.code == "square_mismatch"
    with store.transaction() as tx:
        assert tx.payments(booking["id"]) == []


@pytest.mark.parametrize("status", ["PENDING", "APPROVED", "FAILED", "CANCELED"])
def test_authorized_pending_failed_and_cancelled_payments_never_confirm(status):
    store, _, service, booking, _, gateway = setup()
    link = service.create(booking["id"], "deposit")
    gateway.settle(link["id"], status)
    service.webhook(*signed(link["id"]))
    with store.transaction() as tx:
        assert tx.get_booking(booking["id"])["status"] == "awaiting_deposit"
        assert not tx.payments(booking["id"])
    gateway.settle(link["id"])
    service.webhook(*signed(link["id"], "event_paid"))
    service.webhook(*signed(link["id"], "event_old_failed"))
    assert service.public_status(link["id"])["status"] == "paid"


@pytest.mark.parametrize(
    "state", ["expired", "cancelled", "conditionally_confirmed", "new_approval"]
)
def test_late_money_is_retained_without_reviving_invalid_approvals(state):
    store, bookings, service, booking, clock, gateway = setup()
    link = service.create(booking["id"], "deposit")
    if state == "expired":
        clock[0] = booking["reservation_expires_at"] + 1
    elif state == "cancelled":
        bookings.cancel(booking["id"], "owner")
    else:
        bookings.decide(
            booking["id"],
            {"decision": "conditionally_confirm", "message": "Discuss flavor"},
            "owner",
        )
        if state == "new_approval":
            bookings.approve(booking["id"], {}, "owner")
    with pytest.raises(DomainError):
        service.start(link["id"])
    gateway.settle(link["id"])
    service.webhook(*signed(link["id"]))
    with store.transaction() as tx:
        current = tx.get_booking(booking["id"])
        assert current["paid_minor"] == 5001
        assert current["status"] == (
            state if state in {"cancelled", "conditionally_confirmed"} else "owner_review"
        )
        assert not [j for j in tx.list_outbox() if j["kind"] == "confirmation_customer"]


def test_expired_links_are_blocked_and_durable_sweep_deletes_them_at_square():
    store, _, service, booking, clock, gateway = setup()
    link = service.create(booking["id"], "deposit")
    clock[0] += 86401
    assert service.public_status(link["id"])["status"] == "expired"
    with pytest.raises(DomainError):
        service.start(link["id"])
    queue = MemoryQueue()
    dispatcher = OutboxDispatcher({}, store, queue)
    dispatcher.checkout = service
    dispatcher.dispatch()
    with store.transaction() as tx:
        job = tx.get_outbox("square_expire:" + link["id"])
        assert job["kind"] == "square_reconcile"
    service.reconcile(booking["id"])
    assert gateway.deleted == ["link_" + link["id"]]
    assert service.enqueue_expired() == 0
    replacement = service.create(booking["id"], "deposit")
    assert replacement["id"] != link["id"]


def test_cancellation_deletes_square_link_but_never_cancels_pending_payment():
    _, bookings, service, booking, _, gateway = setup()
    link = service.create(booking["id"], "deposit")
    gateway.settle(link["id"], "PENDING")
    bookings.cancel(booking["id"], "owner")
    with pytest.raises(DomainError, match="earlier payment"):
        service.reconcile(booking["id"])
    assert gateway.deleted == []
    gateway.payments["payment_" + link["id"]]["status"] = "FAILED"
    service.reconcile(booking["id"])
    assert gateway.deleted == ["link_" + link["id"]]


def test_webhook_transaction_rolls_back_payment_event_and_booking_atomically(monkeypatch):
    store, bookings, service, booking, _, gateway = setup()
    link = service.create(booking["id"], "deposit")
    gateway.settle(link["id"])
    save = bookings._save

    def broken(*args, **kwargs):
        save(*args, **kwargs)
        raise RuntimeError("crash before commit")

    monkeypatch.setattr(bookings, "_save", broken)
    with pytest.raises(RuntimeError):
        service.webhook(*signed(link["id"]))
    with store.transaction() as tx:
        assert tx.payments(booking["id"]) == []
        assert tx.get_square_event("event_test") is None
        assert tx.get_checkout(link["id"])["status"] == "open"
    monkeypatch.setattr(bookings, "_save", save)
    service.webhook(*signed(link["id"]))
    assert service.public_status(link["id"])["status"] == "paid"


def test_deposit_email_uses_application_gate_and_stale_emails_are_suppressed():
    store, bookings, service, booking, _, _ = setup()
    mail = MemoryMail()
    worker = JobProcessor(service.settings, store, None, mail, None, None)
    worker.checkout = service
    with store.transaction() as tx:
        job = next(j for j in tx.list_outbox() if j["kind"] == "deposit_request")
    worker._execute(job)
    assert "https://example.invalid/payment/pay?checkout=" in mail.messages[0]["body"]
    link = service.create(booking["id"], "deposit", email=True)
    bookings.cancel(booking["id"], "owner")
    with store.transaction() as tx:
        email_job = tx.get_outbox("checkout_email:" + link["id"])
    assert worker._execute(email_job) is False
    service.enabled = False
    assert service.email_checkout(link["id"], booking) is None
    assert len(mail.messages) == 1


def test_approval_resend_deposit_and_balance_use_the_same_verified_checkout_flow():
    import re

    store, _, service, booking, clock, gateway = setup()
    service.settings.update(
        EMAIL_PROVIDER="resend",
        RESEND_API_KEY="re_synthetic_private_key_for_offline_tests",
        AUTOMATION_FROM_EMAIL="notifications@example.invalid",
        EMAIL_REPLY_TO_ADDRESS="owner@example.invalid",
    )
    http = Mock()
    http.post.return_value = Mock(status_code=200)
    http.post.return_value.json.return_value = {"id": "resend-accepted"}
    mail = ResendMail(service.settings, client=ResendClient(service.settings, http=http))
    worker = JobProcessor(
        service.settings, store, MemoryQueue(), mail, None, None, clock=lambda: clock[0]
    )
    worker.checkout = service
    with store.transaction() as tx:
        deposit_job = next(j for j in tx.list_outbox() if j["kind"] == "deposit_request")
    worker.process({"job_key": deposit_job["key"]})
    worker.process({"job_key": deposit_job["key"]})
    assert http.post.call_count == 1
    email = http.post.call_args.kwargs["json"]
    assert email["to"] == [booking["customer_email"]]
    deposit_id = re.search(r"/payment/pay\?checkout=([a-f0-9]{32})", email["text"])[1]
    assert service.public_status(deposit_id)["purpose"] == "deposit"
    assert service.start(deposit_id)["url"].startswith("https://sandbox.square.link/")
    gateway.settle(deposit_id)
    # A return redirect or even a settled provider payment does not update
    # local money before the authenticated, provider-verified notification.
    assert service.public_status(deposit_id)["status"] == "pending"
    service.webhook(*signed(deposit_id, "deposit-resend-flow"))
    service.webhook(*signed(deposit_id, "deposit-resend-flow"))
    assert service.public_status(deposit_id)["status"] == "paid"
    with store.transaction() as tx:
        assert tx.get_booking(booking["id"])["status"] == "confirmed"
        assert len(tx.payments(booking["id"])) == 1
        confirmation = next(j for j in tx.list_outbox() if j["kind"] == "confirmation_customer")
    worker.process({"job_key": confirmation["key"]})
    assert "Your verified deposit confirms" in http.post.call_args.kwargs["json"]["text"]
    balance = service.create(booking["id"], "balance", email=True)
    worker.process({"job_key": "checkout_email:" + balance["id"]})
    assert balance["url"] in http.post.call_args.kwargs["json"]["text"]
    assert balance["amount_minor"] == 5000
    gateway.settle(balance["id"])
    service.webhook(*signed(balance["id"], "balance-resend-flow"))
    assert service.public_status(balance["id"])["status"] == "paid"
    with store.transaction() as tx:
        assert tx.get_booking(booking["id"])["payment_status"] == "paid"
        assert len(tx.payments(booking["id"])) == 2


def test_overpayment_race_retains_money_and_flags_review():
    store, bookings, service, booking, _, gateway = setup()
    link = service.create(booking["id"], "deposit")
    bookings.verify_payment(booking["id"], payment(amount=10001), "owner")
    gateway.settle(link["id"])
    service.webhook(*signed(link["id"]))
    with store.transaction() as tx:
        current = tx.get_booking(booking["id"])
        assert (current["paid_minor"], current["overpaid_minor"], current["remaining_minor"]) == (
            15002,
            5001,
            0,
        )
        assert "exceeds" in current["owner_review_reason"]


def test_balance_after_event_and_invalid_state_revision_and_ambiguous_creation():
    _, bookings, service, booking, clock, gateway = setup()
    with pytest.raises(DomainError, match="changed"):
        service.create(booking["id"], "deposit", expected_revision=0)
    with pytest.raises(DomainError):
        service.create(booking["id"], "balance")
    bookings.verify_payment(booking["id"], payment(), "owner")
    clock[0] = NOW + 100 * 86400
    assert service.create(booking["id"], "balance")["amount_minor"] == 5000
    _, _, service, booking, clock, gateway = setup()
    gateway.timeout = True
    with pytest.raises(DomainError):
        service.create(booking["id"], "deposit")
    clock[0] += 23 * 3600
    with pytest.raises(DomainError) as error:
        service.create(booking["id"], "deposit")
    assert error.value.code == "square_review_required"


def test_sandbox_booking_cannot_be_reused_in_production():
    _, _, service, booking, _, gateway = setup()
    link = service.create(booking["id"], "deposit")
    gateway.settle(link["id"])
    service.webhook(*signed(link["id"]))
    production = CheckoutService(
        {**service.settings, "SQUARE_ENVIRONMENT": "production"}, service.store, service.bookings
    )
    assert production.public_status(link["id"])["environment"] == "sandbox"
    with pytest.raises(DomainError) as error:
        production.create(booking["id"], "balance")
    assert error.value.code == "square_environment_conflict"


def test_manual_square_fallback_has_shared_payment_reference_namespace():
    store, bookings, service, booking, _, gateway = setup()
    link = service.create(booking["id"], "deposit")
    bookings.verify_payment(
        booking["id"], payment(reference="payment_" + link["id"], provider="square"), "owner"
    )
    gateway.settle(link["id"])
    service.webhook(*signed(link["id"]))
    with store.transaction() as tx:
        assert len(tx.payments(booking["id"])) == 1
        assert tx.get_booking(booking["id"])["paid_minor"] == 5001


@pytest.mark.parametrize("notification", [False, True])
def test_legacy_raw_square_reference_is_not_counted_again(notification):
    store, bookings, service, booking, _, gateway = setup()
    link = service.create(booking["id"], "deposit")
    reference = "payment_" + link["id"]
    legacy = bookings.payment_adapter.verify(
        booking, payment(reference=reference, provider="Square"), "owner", NOW
    )
    with store.transaction(capacity=True) as tx:
        bookings.record_payment_in_transaction(
            tx, tx.get_booking(booking["id"]), legacy, "owner", NOW
        )
    if notification:
        gateway.settle(link["id"])
        service.webhook(*signed(link["id"]))
        assert service.public_status(link["id"])["status"] == "paid"
    else:
        bookings.verify_payment(
            booking["id"], payment(reference=reference, provider="square"), "owner"
        )
    with store.transaction() as tx:
        assert tx.get_booking(booking["id"])["paid_minor"] == 5001
        assert len(tx.payments(booking["id"])) == 1
        assert tx.get_payment(reference) == legacy
        assert tx.get_payment("square:" + reference) is None


def test_legacy_reference_on_another_booking_or_provider_is_not_reused():
    store, bookings, _, booking, _, _ = setup()
    other = bookings.create(payload(), "owner")
    legacy = bookings.payment_adapter.verify(
        booking, payment(reference="legacy-payment", provider="square"), "owner", NOW
    )
    with store.transaction() as tx:
        tx.add_payment(legacy)
    with pytest.raises(DomainError) as conflict:
        bookings.verify_payment(
            other["id"], payment(reference="legacy-payment", provider="Square"), "owner"
        )
    assert conflict.value.code == "payment_reference_conflict"
    with store.transaction() as tx:
        legacy["provider"] = "venmo"
        # Simulate a historical provider with the same reference, without rewriting payment history.
        tx.add_payment({**legacy, "reference": "another-provider"})
    with pytest.raises(DomainError) as conflict:
        bookings.verify_payment(
            booking["id"], payment(reference="another-provider", provider="Square"), "owner"
        )
    assert conflict.value.code == "payment_reference_conflict"


def test_owner_and_public_routes_enforce_prices_origin_and_signature(owner_app):
    store, bookings, service, booking, _, gateway = setup()
    owner_app.extensions.update(
        square_checkout=service, automation_store=store, booking_service=bookings
    )
    client, headers = signed_owner(owner_app)
    url = BASE + f"/bookings/{booking['id']}/checkout"
    body = {"purpose": "deposit", "expected_revision": booking["revision"]}
    assert client.post(url, json={**body, "amount_minor": 1}, headers=headers).status_code == 422
    result = client.post(url, json=body, headers=headers)
    assert result.status_code == 200
    link, public = result.json["data"], owner_app.test_client()
    status_url = "/api/v1/payments/square/" + link["id"]
    result = public.get(status_url)
    assert result.status_code == 200
    assert result.headers["Cache-Control"] == "no-store"
    assert not set(result.json["data"]) & {
        "customer",
        "customer_email",
        "booking_id",
        "url",
        "provider_url",
    }
    assert public.get("/api/v1/payments/square/" + booking["id"]).status_code == 404
    assert public.post(status_url + "/start", json={}).status_code == 403
    assert (
        public.post(
            status_url + "/start", json={}, headers={"Origin": "https://attacker.invalid"}
        ).status_code
        == 403
    )
    owner_app.config["AUTH_ORIGIN"] = service.settings["AUTH_ORIGIN"]
    origin = {"Origin": service.settings["AUTH_ORIGIN"]}
    assert (
        public.post(status_url + "/start", json={"amount_minor": 1}, headers=origin).status_code
        == 422
    )
    assert (
        public.post(status_url + "/start", json={}, headers=origin)
        .json["data"]["url"]
        .startswith("https://sandbox.square.link/")
    )
    hook = "/api/v1/payments/square/webhook"
    assert public.post(hook, data=b"{}").status_code == 400
    raw, signature = signed(link["id"], merchant_id="other")
    assert (
        public.post(
            hook, data=raw, headers={"X-Square-HmacSha256-Signature": signature}
        ).status_code
        == 400
    )
    gateway.settle(link["id"])
    raw, signature = signed(link["id"])
    assert (
        public.post(
            hook, data=raw, headers={"X-Square-HmacSha256-Signature": signature}
        ).status_code
        == 200
    )
    assert public.get(status_url).json["data"]["status"] == "paid"


@pytest.mark.parametrize(
    "change",
    [
        {"AUTOMATION_ENABLED": False},
        {"SQUARE_ENVIRONMENT": "test"},
        {"SQUARE_ACCESS_TOKEN": ""},
        {"SQUARE_WEBHOOK_SIGNATURE_KEY": ""},
        {"SQUARE_MERCHANT_ID": ""},
        {"SQUARE_LOCATION_ID": ""},
        {"SQUARE_WEBHOOK_NOTIFICATION_URL": "http://localhost/api/v1/payments/square/webhook"},
        {"SQUARE_WEBHOOK_NOTIFICATION_URL": NOTIFICATION_URL + "?key=bad"},
    ],
)
def test_enabled_configuration_fails_closed(change):
    with pytest.raises(ValueError):
        validate_settings({**setup()[2].settings, **change})


def test_disabled_configuration_needs_no_credentials(monkeypatch):
    monkeypatch.setenv("SQUARE_ENABLED", "false")
    settings = environment_settings()
    validate_settings(settings)
    service = CheckoutService(settings, MemoryStore(), BookingService(MemoryStore()))
    assert not service.available()["enabled"]
    with pytest.raises(DomainError) as error:
        service.create("any", "deposit")
    assert error.value.status == 503


def test_unrelated_pos_payment_with_null_note_is_ignored_without_provider_calls():
    store, _, service, booking, _, gateway = setup()
    raw = json.dumps(
        {
            "merchant_id": "merchant_test",
            "event_id": "event_pos",
            "type": "payment.updated",
            "data": {
                "object": {"payment": {"id": "pos_payment", "order_id": "pos_order", "note": None}}
            },
        }
    ).encode()
    service.webhook(raw, sign(raw))
    assert gateway.payments == {}
    with store.transaction() as tx:
        assert not tx.payments(booking["id"])


def test_expiry_sweep_advances_past_previously_queued_work():
    store, _, service, booking, clock, _ = setup()
    service.create(booking["id"], "deposit")
    _, _, second, other, _, _ = setup(store)
    second.create(other["id"], "deposit")
    clock[0] += 86401
    assert service.enqueue_expired(limit=1) == 1
    assert service.enqueue_expired(limit=1) == 1
    assert service.enqueue_expired(limit=1) == 0


def test_provider_outage_is_retryable_without_acknowledging_or_logging_private_details(
    owner_app, monkeypatch
):
    store, bookings, service, booking, _, gateway = setup()
    link = service.create(booking["id"], "deposit")
    owner_app.extensions.update(
        square_checkout=service, automation_store=store, booking_service=bookings
    )

    def fail(*args):
        raise SquareFailure("private token")

    monkeypatch.setattr(gateway, "payment", fail)
    raw, signature = signed(link["id"])
    result = owner_app.test_client().post(
        "/api/v1/payments/square/webhook",
        data=raw,
        headers={"X-Square-HmacSha256-Signature": signature},
    )
    assert result.status_code == 503
    assert "private" not in result.text
    with store.transaction() as tx:
        assert tx.get_square_event("event_test") is None
        assert not tx.payments(booking["id"])


class HTTP:
    def __init__(self, body=None, status=200):
        self.body, self.status, self.calls = body or {}, status, []

    def request(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self

    @property
    def status_code(self):
        return self.status

    def json(self):
        return self.body


def test_square_rest_adapter_uses_correct_hosts_headers_idempotency_and_no_redirects():
    settings = setup()[2].settings
    http = HTTP({"payment_link": {"id": "example"}})
    gateway = SquareGateway(settings, http=http)
    gateway.create({"description": "sample"}, "durable-key")
    args, kwargs = http.calls[0]
    assert args == ("POST", "https://connect.squareupsandbox.com/v2/online-checkout/payment-links")
    assert kwargs["json"] == {"description": "sample", "idempotency_key": "durable-key"}
    assert kwargs["headers"]["Square-Version"] == API_VERSION == "2026-09-16"
    assert kwargs["headers"]["Authorization"] == "Bearer synthetic-token"
    assert kwargs["allow_redirects"] is False
    assert (
        SquareGateway({**settings, "SQUARE_ENVIRONMENT": "production"}).base
        == "https://connect.squareup.com"
    )
    http.body = {"order": {"id": "order"}}
    assert gateway.order("order") == {"id": "order"}
    http.body = {"payment": {"id": "payment"}}
    assert gateway.payment("payment") == {"id": "payment"}
    http.status = 404
    assert gateway.delete("link") is None
    with pytest.raises(SquareFailure):
        gateway.order("order")
    with pytest.raises(DomainError):
        gateway.payment("../other")


@pytest.mark.parametrize(
    "status,body", [(302, {}), (500, {}), (200, {"errors": [{"code": "bad"}]}), (200, [])]
)
def test_rest_error_responses_never_leak_provider_details(status, body):
    gateway = SquareGateway(setup()[2].settings, http=HTTP(body, status))
    # Preserve a deliberately non-object response instead of the helper's empty default.
    gateway.http.body = body
    with pytest.raises(SquareFailure):
        gateway.create({}, "key")


@pytest.mark.database
def test_mysql_concurrent_notifications_are_atomic_and_expiration_columns_are_durable(sql_settings):
    store, bookings, service, booking, clock, gateway = setup(Store(sql_settings))
    link = service.create(booking["id"], "deposit", email=True)
    gateway.settle(link["id"])

    def process(index):
        instance = CheckoutService(service.settings, Store(sql_settings), bookings)
        instance.webhook(*signed(link["id"], f"event_mysql_{index % 2}"))

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(process, range(8)))
    with store.transaction() as tx:
        assert len(tx.payments(booking["id"])) == 1
        assert tx.get_checkout_by_order("order_" + link["id"])["status"] == "paid"
        assert tx.get_square_event("event_mysql_0")
    balance = service.create(booking["id"], "balance")
    clock[0] += 86401
    assert service.enqueue_expired() == 1
    service.reconcile(booking["id"])
    with store.transaction() as tx:
        assert tx.get_checkout(balance["id"])["status"] == "expired"
        assert tx.expired_checkouts(clock[0], 100) == []


def test_factory_wires_square_into_worker_and_expiration_dispatcher():
    app = create_app(
        {
            "TESTING": True,
            "AUTOMATION_ENABLED": True,
            "AUTOMATION_STORE": MemoryStore(),
            "AUTOMATION_MODE": "local",
        }
    )
    assert app.extensions["processor"].checkout is app.extensions["square_checkout"]
    assert app.extensions["dispatcher"].checkout is app.extensions["square_checkout"]
