"""Business boundaries and durable owner decisions from the November group review."""

from datetime import datetime, timedelta, timezone

import pytest
from app.automation.delivery import JobProcessor, MemoryMail, MemoryQueue
from app.automation.domain import DomainError
from test_auth import auth_app as auth_app
from test_automation_domain import payload, payment
from test_automation_domain import setup as setup
from test_automation_routes import owner_app as owner_app
from test_automation_routes import signed_owner
from test_automation_store import sql_settings as sql_settings
from test_order_intake import intake_app as intake_app
from test_order_intake import mysql_app as mysql_app
from test_order_intake import submit
from test_orders import order_payload
from test_quotes import app as app
from test_quotes import client as client
from test_quotes import contract_payload

BASE = "/api/v1/admin/automation"


@pytest.mark.parametrize(
    "quantity,blocks,ice_cents",
    [
        (50, 3, 4500),
        (150, 3, 4500),
        (151, 6, 7500),
        (300, 6, 7500),
        (301, 9, 10500),
        (100000, 2001, 2002500),
    ],
)
@pytest.mark.parametrize("requested", [None, 0, 1])
def test_required_dry_ice_cannot_be_removed_from_quote(
    client, quantity, blocks, ice_cents, requested
):
    response = client.post(
        "/api/v1/quotes", json=contract_payload(quantity=quantity, dry_ice_blocks=requested)
    )
    assert response.status_code == 200
    pricing = response.json["data"]["pricing"]
    ice = next(item for item in pricing["line_items"] if item["code"] == "dry_ice")
    assert ice["amount_cents"] == ice_cents
    assert f"{blocks} blocks" in ice["description"]
    assert pricing["total_cents"] == quantity * 450 + ice_cents + 2500


def test_extra_dry_ice_is_kept(client):
    response = client.post("/api/v1/quotes", json=contract_payload(dry_ice_blocks=5))
    items = {
        item["code"]: item["amount_cents"]
        for item in response.json["data"]["pricing"]["line_items"]
    }
    assert items["dry_ice"] == 7500


@pytest.mark.parametrize(
    "quantity,blocks,expected_cents",
    [(150, 4, 6000), (150, 6, 9000), (151, 6, 7500), (151, 7, 8500), (301, 10, 11500)],
)
def test_volume_discount_keeps_first_three_blocks_at_full_price(
    client, quantity, blocks, expected_cents
):
    response = client.post(
        "/api/v1/quotes", json=contract_payload(quantity=quantity, dry_ice_blocks=blocks)
    )
    assert response.status_code == 200
    pricing = response.json["data"]["pricing"]
    ice = next(item for item in pricing["line_items"] if item["code"] == "dry_ice")
    assert ice["amount_cents"] == expected_cents
    assert pricing["deposit_due_cents"] == (pricing["total_cents"] + 1) // 2
    if quantity > 150:
        assert "first 3 at $15.00 each" in ice["description"]
        assert "additional at $10.00 each" in ice["description"]
    else:
        assert "at $15.00" in ice["description"]


@pytest.mark.parametrize("minutes,cents", [(30, 750), (60, 1500), (90, 2250), (135, 3375)])
def test_employee_charge_uses_only_actual_event_duration(client, minutes, cents):
    body = contract_payload(service_type="full_service")
    start = datetime.fromisoformat(body["event"]["starts_at"])
    body["event"]["ends_at"] = (start + timedelta(minutes=minutes)).isoformat()
    response = client.post("/api/v1/quotes", json=body)
    pricing = response.json["data"]["pricing"]
    items = {item["code"]: item["amount_cents"] for item in pricing["line_items"]}
    assert items == {
        "popsicles": 22500,
        "dry_ice": 4500,
        "full_service_fee": 15000,
        "employee_service": cents,
    }
    assert pricing["total_cents"] == 42000 + cents


def test_full_service_requires_end_time_before_it_can_quote(client):
    body = contract_payload(service_type="full_service")
    body["event"]["ends_at"] = None
    response = client.post("/api/v1/quotes", json=body)
    assert response.status_code == 422
    assert response.json["error"]["fields"][0]["field"] == "event.ends_at"


def test_invalid_event_timezone_boundary_returns_validation_error(client):
    body = contract_payload(service_type="full_service")
    body["event"]["starts_at"] = "0001-01-01T00:00:00+14:00"
    response = client.post("/api/v1/quotes", json=body)
    assert response.status_code == 422
    assert response.json["error"]["fields"][0]["field"] == "event.starts_at"


@pytest.mark.parametrize(
    "custom",
    [
        {"flavor_requests": "Lavender"},
        {"flavor_allocations": [{"flavor": "Lavender", "quantity": 50}]},
    ],
)
def test_custom_orders_obey_the_catering_notice_period(client, custom):
    body = contract_payload(**custom)
    body["event"]["starts_at"] = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    response = client.post("/api/v1/quotes", json=body)
    assert response.status_code == 422
    assert response.json["error"]["fields"][0]["field"].startswith("catering_request.flavor_")
    assert "14 days" in response.json["error"]["message"]


def test_allergy_notes_and_custom_requests_are_allowed_with_two_weeks_notice(client):
    body = contract_payload(allergy_notes="Nut allergy")
    assert client.post("/api/v1/quotes", json=body).status_code == 200
    body["catering_request"]["flavor_requests"] = "Custom lavender"
    assert client.post("/api/v1/quotes", json=body).status_code == 200


def test_conditional_decision_requires_message_and_does_not_reserve_or_confirm_payment(setup):
    store, service, _ = setup
    booking = service.create(payload(), "owner")
    with pytest.raises(DomainError, match="Explain"):
        service.decide(
            booking["id"], {"decision": "conditionally_confirm", "expected_revision": 1}, "owner"
        )
    conditional = service.decide(
        booking["id"],
        {
            "decision": "conditionally_confirm",
            "message": "Date works; please discuss another flavor.",
            "expected_revision": 1,
        },
        "owner",
    )
    assert conditional["status"] == "conditionally_confirmed"
    assert conditional["reservation_expires_at"] is None
    paid = service.verify_payment(booking["id"], payment(), "owner")
    assert paid["status"] == "conditionally_confirmed"
    with store.transaction() as tx:
        assert len([job for job in tx.list_outbox() if job["kind"] == "decision_customer"]) == 1
    confirmed = service.approve(booking["id"], {}, "owner")
    assert confirmed["status"] == "confirmed"


def test_decision_email_retries_once_and_suppresses_an_obsolete_conditional(setup):
    store, service, _ = setup
    booking = service.create(payload(), "owner")
    conditional = service.decide(
        booking["id"],
        {"decision": "conditionally_confirm", "message": "Can we use mango instead?"},
        "owner",
    )
    denied = service.decide(
        booking["id"],
        {
            "decision": "deny",
            "message": "We cannot serve this date.",
            "expected_revision": conditional["revision"],
        },
        "owner",
    )
    mail = MemoryMail()
    worker = JobProcessor({}, store, MemoryQueue(), mail, None, None)
    with store.transaction() as tx:
        jobs = [job for job in tx.list_outbox() if job["kind"] == "decision_customer"]
    for job in jobs:
        worker.process({"job_key": job["key"]})
        worker.process({"job_key": job["key"]})
    assert len(mail.messages) == 1
    assert "denied" in mail.messages[0]["subject"]
    assert "We cannot serve this date." in mail.messages[0]["body"]
    with pytest.raises(DomainError, match="Reopen"):
        service.decide(denied["id"], {"decision": "confirm"}, "owner")


@pytest.mark.parametrize("decision", ["conditionally_confirm", "deny", "confirm"])
def test_owner_can_review_an_unlinked_order_atomically(intake_app, decision):
    client, headers = signed_owner(intake_app)
    order, _ = submit(client)
    body = {
        "decision": decision,
        "message": "Please discuss an alternative flavor.",
        "expected_version": order["version"],
    }
    response = client.post(BASE + f"/orders/{order['id']}/decision", json=body, headers=headers)
    assert response.status_code == 200, response.json
    booking = response.json["data"]
    assert booking["contract_url"] == ""
    assert (
        booking["status"]
        == {
            "confirm": "awaiting_deposit",
            "conditionally_confirm": "conditionally_confirmed",
            "deny": "cancelled",
        }[decision]
    )
    with intake_app.extensions["automation_store"].transaction() as tx:
        assert len(tx.list_bookings()) == 1
        assert tx.get_order_link(order["id"])["booking_id"] == booking["id"]
        assert any(
            job["kind"] in {"decision_customer", "deposit_request"} for job in tx.list_outbox()
        )
    repeated = client.post(BASE + f"/orders/{order['id']}/decision", json=body, headers=headers)
    assert repeated.status_code == 409
    stale = client.post(
        BASE + f"/bookings/{booking['id']}/decision",
        json={"decision": "deny", "expected_revision": 1},
        headers=headers,
    )
    assert stale.status_code == 409


def test_failed_review_rolls_back_the_handoff_and_outbox(intake_app):
    client, headers = signed_owner(intake_app)
    order, _ = submit(client)
    response = client.post(
        BASE + f"/orders/{order['id']}/decision",
        json={"decision": "conditionally_confirm", "expected_version": 1, "message": ""},
        headers=headers,
    )
    assert response.status_code == 400
    with intake_app.extensions["automation_store"].transaction() as tx:
        assert tx.get_order_link(order["id"]) is None
        assert tx.list_bookings() == []
        assert tx.list_outbox() == []


def test_conditional_email_is_skipped_after_legacy_cancellation(setup):
    store, service, _ = setup
    booking = service.create(payload(), "owner")
    conditional = service.decide(
        booking["id"],
        {"decision": "conditionally_confirm", "message": "Discuss another flavor."},
        "owner",
    )
    service.cancel(booking["id"], "owner", expected_revision=conditional["revision"])
    mail = MemoryMail()
    worker = JobProcessor({}, store, MemoryQueue(), mail, None, None)
    with store.transaction() as tx:
        job = next(job for job in tx.list_outbox() if job["kind"] == "decision_customer")
    worker.process({"job_key": job["key"]})
    assert mail.messages == []


def test_malformed_contract_cannot_partially_approve(setup):
    store, service, _ = setup
    booking = service.create(payload(), "owner")
    with pytest.raises(DomainError, match="HTTPS"):
        service.decide(
            booking["id"], {"decision": "confirm", "contract_url": "https://[bad"}, "owner"
        )
    with store.transaction() as tx:
        assert tx.get_booking(booking["id"])["status"] == "requested"
        assert tx.list_outbox() == []


def test_reapproval_suppresses_the_previous_deposit_email(setup):
    store, service, clock = setup
    booking = service.create(payload(), "owner")
    first = service.approve(booking["id"], {}, "owner")
    service.decide(
        first["id"],
        {"decision": "conditionally_confirm", "message": "Discuss another flavor."},
        "owner",
    )
    latest = service.approve(
        booking["id"], {"message": "Flavor agreed; please arrange the deposit."}, "owner"
    )
    mail = MemoryMail()
    worker = JobProcessor(
        {},
        store,
        MemoryQueue(),
        mail,
        None,
        None,
        clock=lambda: datetime.fromtimestamp(clock[0], timezone.utc),
    )
    with store.transaction() as tx:
        jobs = [job for job in tx.list_outbox() if job["kind"] == "deposit_request"]
    assert len(jobs) == 2
    for job in jobs:
        worker.process({"job_key": job["key"]})
    assert latest["status"] == "awaiting_deposit"
    assert len(mail.messages) == 1
    assert "Flavor agreed" in mail.messages[0]["body"]


def test_reopening_a_denied_request_requires_real_end_but_no_contract(intake_app):
    client, headers = signed_owner(intake_app)
    body = order_payload()
    body["event"]["ends_at"] = None
    quote = client.post(
        "/api/v1/quotes", json={key: body[key] for key in ("event", "catering_request")}
    )
    assert quote.status_code == 200
    body["quote_id"] = quote.json["data"]["id"]
    created = client.post(
        "/api/v1/orders", json=body, headers={"Idempotency-Key": "reopen-review-0123456789"}
    )
    assert created.status_code == 201
    order = created.json["data"]
    denied = client.post(
        BASE + f"/orders/{order['id']}/decision",
        json={"decision": "deny", "expected_version": 1},
        headers=headers,
    )
    assert denied.status_code == 200
    booking = denied.json["data"]
    path = BASE + f"/bookings/{booking['id']}/reopen"
    request = {
        "reason": "Customer accepted the revised details",
        "expected_revision": booking["revision"],
    }
    assert client.post(path, json=request, headers=headers).status_code == 400
    request["end"] = "2099-01-15T17:00:00-06:00"
    reopened = client.post(path, json=request, headers=headers)
    assert reopened.status_code == 200, reopened.json
    assert reopened.json["data"]["status"] == "awaiting_deposit"
    assert reopened.json["data"]["end_unspecified"] is False
    assert reopened.json["data"]["contract_url"] == ""


def test_final_quantity_keeps_the_required_dry_ice_count(setup):
    _, service, _ = setup
    booking = service.create(payload(quantity=150), "owner")
    assert booking["dry_ice_blocks"] == 3
    updated = service.finalize_count(booking["id"], {"quantity": 151}, "owner")
    assert updated["dry_ice_blocks"] == 6
    assert updated["total_minor"] == booking["total_minor"]


@pytest.mark.parametrize(
    "decision,status", [("deny", 200), ("conditionally_confirm", 400), ("confirm", 400)]
)
def test_past_customer_requests_can_be_denied_but_not_approved(intake_app, decision, status):
    client, headers = signed_owner(intake_app)
    order, _ = submit(client)
    intake_app.extensions["booking_service"].clock = lambda: datetime(
        2100, 1, 1, tzinfo=timezone.utc
    ).timestamp()
    response = client.post(
        BASE + f"/orders/{order['id']}/decision",
        json={
            "decision": decision,
            "message": "The event date has passed.",
            "contract_url": "https://example.invalid/contract",
            "expected_version": order["version"],
        },
        headers=headers,
    )
    assert response.status_code == status, response.json
    with intake_app.extensions["automation_store"].transaction() as tx:
        link = tx.get_order_link(order["id"])
        assert bool(link) == (decision == "deny")
        if link:
            assert tx.get_booking(link["booking_id"])["status"] == "cancelled"
