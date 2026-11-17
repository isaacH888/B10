"""An owned, approved order can open one server-priced Square deposit checkout."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy

import pytest
from app.payments.service import CheckoutService
from test_auth import auth_app as auth_app
from test_auth import customer_session
from test_automation_routes import owner_app as owner_app
from test_automation_routes import signed_owner
from test_automation_store import sql_settings as sql_settings
from test_customer_orders import another_customer
from test_order_intake import intake_app as intake_app
from test_order_intake import mysql_app as mysql_app
from test_orders import order_payload, post_order
from test_square_checkout import NOTIFICATION_URL, SIGNATURE_KEY, Gateway, signed


@pytest.fixture
def scenario(intake_app):
    app = intake_app
    booking_service = app.extensions["booking_service"]
    booking_service.checkout_enabled = True
    gateway = Gateway()
    settings = {
        **app.config,
        "SQUARE_ENABLED": True,
        "SQUARE_ENVIRONMENT": "sandbox",
        "SQUARE_ACCESS_TOKEN": "synthetic-token",
        "SQUARE_MERCHANT_ID": "merchant_test",
        "SQUARE_LOCATION_ID": "location_test",
        "SQUARE_WEBHOOK_SIGNATURE_KEY": SIGNATURE_KEY,
        "SQUARE_WEBHOOK_NOTIFICATION_URL": NOTIFICATION_URL,
        "SQUARE_GATEWAY": gateway,
    }
    checkout = CheckoutService(settings, app.extensions["automation_store"], booking_service)
    app.extensions["square_checkout"] = checkout
    customer = customer_session(app.test_client())
    order = post_order(customer, order_payload()).json["data"]
    owner, owner_headers = signed_owner(app)
    return app, customer, order, owner, owner_headers, checkout, gateway


def offer(scenario):
    _, customer, order, *_ = scenario
    result = customer.get("/api/v1/customer/orders")
    assert result.status_code == 200, result.json
    return next(
        item["payment"] for item in result.json["data"]["items"] if item["id"] == order["id"]
    )


def decide(scenario, decision="confirm"):
    _, _, order, owner, headers, *_ = scenario
    result = owner.post(
        f"/api/v1/admin/automation/orders/{order['id']}/decision",
        json={
            "decision": decision,
            "expected_version": order["version"],
            "message": "Synthetic owner review",
        },
        headers=headers,
    )
    assert result.status_code in {200, 201}, result.json
    return result.json["data"]


def pay(scenario, body=None, customer=None, **headers):
    _, owner_customer, order, *_ = scenario
    return (customer or owner_customer).post(
        f"/api/v1/customer/orders/{order['id']}/checkout",
        json=body if body is not None else {"expected_revision": offer(scenario)["revision"]},
        headers=headers,
    )


def test_approval_enables_checkout_and_verified_payment_removes_it(scenario):
    app, customer, order, _, _, checkout, gateway = scenario
    assert offer(scenario)["status"] == "awaiting_approval"
    assert pay(scenario, {"expected_revision": 1}).status_code == 409
    booking = decide(scenario)
    payment = offer(scenario)
    assert payment["status"] == "deposit_due" and payment["can_pay"]
    assert payment["amount_due_cents"] == order["pricing"]["deposit_due_cents"]
    assert gateway.calls == []  # Polling the account cannot create provider resources.
    result = pay(scenario)
    assert result.status_code == 200, result.json
    assert result.json["data"]["environment"] == "sandbox"
    assert result.json["data"]["url"].startswith("https://sandbox.square.link/")
    assert result.headers["Cache-Control"] == "no-store"
    assert pay(scenario).json["data"] == result.json["data"]
    with checkout.store.transaction() as tx:
        (row,) = tx.checkouts(booking["id"])
        assert row["amount_minor"] == payment["amount_due_cents"]
        assert not [job for job in tx.list_outbox() if job["kind"] == "checkout_email"]
    gateway.settle(row["id"])
    raw, signature = signed(row["id"])
    webhook = app.test_client().post(
        "/api/v1/payments/square/webhook",
        data=raw,
        headers={"X-Square-HmacSha256-Signature": signature},
    )
    assert webhook.status_code == 200, webhook.json
    assert offer(scenario)["status"] == "paid" and not offer(scenario)["can_pay"]
    assert pay(scenario).status_code == 409
    item = customer.get("/api/v1/customer/orders").json["data"]["items"][0]
    assert item["status"] == "confirmed" and item["deposit"]["status"] == "confirmed"


@pytest.mark.parametrize("decision", ["conditionally_confirm", "deny"])
def test_conditional_and_denied_orders_cannot_open_checkout(scenario, decision):
    decide(scenario, decision)
    assert not offer(scenario)["can_pay"]
    assert pay(scenario).status_code == 409
    assert scenario[-1].calls == []


def test_another_account_with_the_same_email_cannot_pay_the_order(scenario, monkeypatch):
    app, _, _, _, _, _, gateway = scenario
    decide(scenario)
    other = another_customer(app, monkeypatch)
    result = pay(scenario, customer=other)
    assert result.status_code == 404 and "data" not in result.json
    assert gateway.calls == []


@pytest.mark.parametrize("who", ["guest", "admin", "no_csrf", "wrong_origin"])
def test_customer_checkout_requires_own_customer_session_and_csrf(scenario, who):
    app, customer, _, owner, _, _, gateway = scenario
    decide(scenario)
    browser = app.test_client() if who == "guest" else owner if who == "admin" else customer
    headers = (
        {"X-CSRF-Token": ""}
        if who == "no_csrf"
        else {"Origin": "https://other.example.invalid"}
        if who == "wrong_origin"
        else {}
    )
    result = pay(scenario, customer=browser, **headers)
    assert result.status_code == (401 if who in {"guest", "admin"} else 403)
    assert gateway.calls == []


@pytest.mark.parametrize(
    "extra", [{"amount_minor": 1}, {"purpose": "balance"}, {"booking_id": "other"}, {"paid": True}]
)
def test_customer_cannot_supply_amount_purpose_or_booking(scenario, extra):
    decide(scenario)
    result = pay(scenario, {"expected_revision": offer(scenario)["revision"], **extra})
    assert result.status_code == 422 and scenario[-1].calls == []


def test_square_disabled_and_expired_reservations_never_enable_payment(scenario):
    app, _, _, _, _, checkout, gateway = scenario
    booking = decide(scenario)
    checkout.enabled = False
    assert not offer(scenario)["can_pay"]
    assert pay(scenario).status_code == 503
    checkout.enabled = True
    app.test_clock["now"] = booking["reservation_expires_at"] + 1
    # Keep the fixture's authenticated sessions current while advancing booking time.
    customer_session(scenario[1])
    assert offer(scenario)["status"] == "expired"
    assert pay(scenario).status_code == 409 and gateway.calls == []


def test_partial_payments_reduce_the_server_amount_and_stale_revision_is_rejected(scenario):
    app, _, _, _, _, checkout, gateway = scenario
    booking = decide(scenario)
    original = deepcopy(offer(scenario))
    app.extensions["booking_service"].verify_payment(
        booking["id"],
        {
            "reference": "synthetic-partial-deposit",
            "amount_minor": 2500,
            "currency": "USD",
            "verification_details": "Synthetic independently verified partial payment",
        },
        "owner",
    )
    assert pay(scenario, {"expected_revision": original["revision"]}).status_code == 409
    current = offer(scenario)
    assert current["amount_due_cents"] == original["amount_due_cents"] - 2500
    assert pay(scenario).status_code == 200
    with checkout.store.transaction() as tx:
        assert tx.checkouts(booking["id"])[0]["amount_minor"] == current["amount_due_cents"]
    assert len(gateway.links) == 1


def test_cancellation_after_display_and_provider_timeout_are_safe_to_retry(scenario):
    app, _, _, _, _, checkout, gateway = scenario
    booking = decide(scenario)
    current = offer(scenario)
    gateway.timeout = True
    assert pay(scenario).status_code == 503
    gateway.timeout = False
    assert pay(scenario).status_code == 200
    assert len(gateway.links) == 1
    app.extensions["booking_service"].cancel(booking["id"], "owner")
    assert pay(scenario, {"expected_revision": current["revision"]}).status_code == 409
    assert not offer(scenario)["can_pay"]


def test_customer_reuses_the_existing_emailed_deposit_link(scenario):
    _, _, _, _, _, checkout, gateway = scenario
    booking = decide(scenario)
    emailed = checkout.create(booking["id"], "deposit", actor="owner", email=True)
    result = pay(scenario)
    assert result.status_code == 200 and result.json["data"]["url"].endswith(emailed["id"])
    assert len(gateway.links) == 1
    with checkout.store.transaction() as tx:
        assert len([job for job in tx.list_outbox() if job["kind"] == "checkout_email"]) == 1


def test_cancellation_during_checkout_creation_blocks_the_final_handoff(scenario, monkeypatch):
    app, _, _, _, _, checkout, _ = scenario
    booking = decide(scenario)
    start = checkout.start

    def cancel_before_handoff(checkout_id):
        app.extensions["booking_service"].cancel(booking["id"], "owner")
        return start(checkout_id)

    monkeypatch.setattr(checkout, "start", cancel_before_handoff)
    result = pay(scenario)
    assert result.status_code == 409 and "data" not in result.json
    with checkout.store.transaction() as tx:
        assert tx.payments(booking["id"]) == []


def test_simultaneous_customer_clicks_reuse_one_checkout(scenario):
    app, source, order, _, _, checkout, gateway = scenario
    booking = decide(scenario)
    revision = offer(scenario)["revision"]

    def attempt(_):
        browser = customer_session(app.test_client(), source=source)
        return browser.post(
            f"/api/v1/customer/orders/{order['id']}/checkout", json={"expected_revision": revision}
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, range(2)))
    assert [result.status_code for result in results] == [200, 200]
    assert results[0].json["data"] == results[1].json["data"]
    assert len(gateway.links) == 1
    with checkout.store.transaction() as tx:
        assert len(tx.checkouts(booking["id"])) == 1
