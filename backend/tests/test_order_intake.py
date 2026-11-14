"""Customer API -> durable owner intake -> existing booking/payment workflow."""

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy

import pytest
from app import database
from app.automation.intake import import_order
from app.automation.store import MemoryTransaction, SQLTransaction, Store, StoreUnavailable
from test_auth import auth_app as auth_app
from test_automation_routes import owner_app as owner_app
from test_automation_routes import signed_owner
from test_automation_store import sql_settings as sql_settings
from test_orders import order_payload

BASE = "/api/v1/admin/automation"
CONTRACT = {"contract_url": "https://example.invalid/contracts/synthetic"}


@pytest.fixture
def mysql_app(owner_app, sql_settings):
    owner_app.config.update(sql_settings)
    store = Store(sql_settings)
    owner_app.extensions["automation_store"] = store
    owner_app.extensions["booking_service"].store = store
    yield owner_app
    with database.connect(sql_settings) as connection, connection.cursor() as cursor:
        for table in ("automation_order_links", "order_items", "orders", "customers", "quotes"):
            cursor.execute("DELETE FROM " + table)
        connection.commit()


@pytest.fixture(params=["memory", "mysql"])
def intake_app(request, owner_app):
    if request.param == "mysql":
        return request.getfixturevalue("mysql_app")
    owner_app.config.update(DB_USER="", DB_PASSWORD="")
    return owner_app


def submit(client, **changes):
    body = order_payload(**changes)
    quote_body = {key: body[key] for key in ("catering_request", "event")}
    quote = client.post("/api/v1/quotes", json=quote_body)
    assert quote.status_code == 200
    body["quote_id"] = quote.json["data"]["id"]
    result = client.post(
        "/api/v1/orders", json=body, headers={"Idempotency-Key": "intake-key-0123456789"}
    )
    assert result.status_code == 201
    return result.json["data"], body


def stored_order(app, order):
    return order if app.config["DB_USER"] else {**order, "admin_notes": ""}


def test_customer_order_enters_owner_workflow_losslessly_and_once(intake_app):
    client, headers = signed_owner(intake_app)
    order, body = submit(client, flavor_requests="Mango and strawberry", dry_ice_blocks=2)
    source = stored_order(intake_app, order)
    assert client.get(BASE + "/orders").json["data"] == [source]
    path = BASE + f"/orders/{order['id']}/booking"
    result = client.post(path, json=CONTRACT, headers=headers)
    assert result.status_code == 201
    booking = result.json["data"]
    assert booking["source_order"] == source
    assert booking["source_order_id"] == order["id"]
    assert booking["owner_id"] == next(iter(intake_app.test_store.identities.values()))["id"]
    assert booking["total_minor"] == order["pricing"]["total_cents"]
    assert booking["deposit_minor"] == order["pricing"]["deposit_due_cents"]
    assert booking["status"] == "requested"
    legacy_update = client.patch(
        f"/api/v1/orders/{order['id']}/status",
        json={"status": "cancelled", "version": 1},
        headers=headers,
    )
    assert legacy_update.status_code == 409
    assert legacy_update.json["error"]["code"] == "booking_managed"
    assert client.get(BASE + "/orders").json["data"] == []
    retry = client.post(path, json=CONTRACT, headers=headers)
    assert retry.status_code == 200 and retry.json["data"] == booking
    assert (
        client.post(
            path, json={"contract_url": "https://example.invalid/other"}, headers=headers
        ).status_code
        == 409
    )
    with intake_app.extensions["automation_store"].transaction() as tx:
        assert len(tx.list_bookings()) == 1
        assert tx.list_outbox() == []
    booking_path = BASE + "/bookings/" + booking["id"]
    approved = client.post(booking_path + "/approve", json={}, headers=headers)
    assert approved.json["data"]["status"] == "awaiting_deposit"
    payment = {
        "reference": "intake-deposit",
        "amount_minor": booking["deposit_minor"],
        "currency": "USD",
        "verification_details": "Owner checked settled transaction at external provider",
    }
    confirmed = client.post(booking_path + "/payments", json=payment, headers=headers)
    assert confirmed.status_code == 200 and confirmed.json["data"]["status"] == "confirmed"
    detail = client.get(booking_path).json["data"]
    assert {job["kind"] for job in detail["jobs"]} == {
        "deposit_request",
        "calendar",
        "confirmation_customer",
        "confirmation_owner",
        "reminder_schedule",
    }
    assert detail["booking"]["source_order"] == source
    replay = client.post(
        "/api/v1/orders", json=body, headers={"Idempotency-Key": "intake-key-0123456789"}
    )
    assert replay.status_code == 201 and replay.json["data"] == order


@pytest.mark.parametrize(
    "supplement",
    [
        {},
        {"end": "invalid", **CONTRACT},
        {"contract_url": "http://example.invalid/contract"},
        {"total_minor": 1, **CONTRACT},
    ],
)
def test_invalid_intake_cannot_create_partial_or_repriced_bookings(intake_app, supplement):
    client, headers = signed_owner(intake_app)
    order, _ = submit(client)
    result = client.post(BASE + f"/orders/{order['id']}/booking", json=supplement, headers=headers)
    assert result.status_code == 400
    assert client.get(BASE + "/orders").json["data"] == [stored_order(intake_app, order)]
    assert client.get(BASE + "/bookings").json["data"] == []


def test_missing_end_requires_owner_input_and_cancelled_orders_cannot_import(intake_app):
    client, headers = signed_owner(intake_app)
    order, _ = submit(client)
    if intake_app.config["DB_USER"]:
        with database.connect(intake_app.config) as connection, connection.cursor() as cursor:
            changed = deepcopy(order)
            changed["event"]["ends_at"] = None
            cursor.execute(
                "UPDATE orders SET response_json=%s WHERE public_id=%s",
                (json.dumps(changed), order["id"]),
            )
            connection.commit()
    else:
        intake_app.extensions["orders_memory"]["by_id"][order["id"]]["event"]["ends_at"] = None
    path = BASE + f"/orders/{order['id']}/booking"
    assert client.post(path, json=CONTRACT, headers=headers).status_code == 400
    cancelled = client.patch(
        f"/api/v1/orders/{order['id']}/status",
        json={"status": "cancelled", "version": 1},
        headers=headers,
    )
    assert cancelled.status_code == 200
    assert (
        client.post(
            path, json={"end": order["event"]["ends_at"], **CONTRACT}, headers=headers
        ).status_code
        == 409
    )


def test_failed_link_rolls_back_booking_and_audit_but_keeps_customer_order(intake_app, monkeypatch):
    client, headers = signed_owner(intake_app)
    order, _ = submit(client)
    transaction = SQLTransaction if intake_app.config["DB_USER"] else MemoryTransaction

    def unavailable(*args):
        raise StoreUnavailable("Synthetic link failure")

    monkeypatch.setattr(transaction, "save_order_link", unavailable)
    result = client.post(BASE + f"/orders/{order['id']}/booking", json=CONTRACT, headers=headers)
    assert result.status_code == 503
    assert client.get(BASE + "/orders").json["data"] == [stored_order(intake_app, order)]
    with intake_app.extensions["automation_store"].transaction() as tx:
        assert tx.list_bookings() == [] and tx.list_outbox() == []
    if intake_app.config["DB_USER"]:
        with database.connect(intake_app.config) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) AS count FROM automation_audit")
            assert cursor.fetchone()["count"] == 0
    else:
        assert intake_app.extensions["automation_store"]._state["audits"] == []


def test_concurrent_handoffs_create_one_booking(intake_app):
    client, _ = signed_owner(intake_app)
    order, _ = submit(client)
    barrier = threading.Barrier(2)

    def attempt(_):
        with intake_app.app_context():
            barrier.wait()
            return import_order(order["id"], CONTRACT, "owner")

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, range(2)))
    assert sum(created for _, created in results) == 1
    assert results[0][0] == results[1][0]


@pytest.mark.database
def test_mysql_submission_replay_is_immutable_after_status_update(mysql_app):
    client, headers = signed_owner(mysql_app)
    order, body = submit(client)
    update = client.patch(
        f"/api/v1/orders/{order['id']}/status",
        json={"status": "confirmed", "version": 1},
        headers=headers,
    )
    assert update.status_code == 200 and update.json["data"]["version"] == 2
    replay = client.post(
        "/api/v1/orders", json=body, headers={"Idempotency-Key": "intake-key-0123456789"}
    )
    assert replay.json["data"] == order


@pytest.mark.database
@pytest.mark.parametrize("conflicting", [False, True])
def test_concurrent_mysql_customer_submissions_do_not_duplicate_customers_or_orders(
    mysql_app, conflicting
):
    body = order_payload()
    with mysql_app.test_client() as client:
        quote = client.post(
            "/api/v1/quotes",
            json={key: body[key] for key in ("catering_request", "event")},
        )
        assert quote.status_code == 200
        body["quote_id"] = quote.json["data"]["id"]
    barrier = threading.Barrier(2)

    def attempt(index):
        payload = deepcopy(body)
        if conflicting and index:
            payload["customer"]["name"] = "Other customer"
        with mysql_app.test_client() as client:
            barrier.wait()
            return client.post(
                "/api/v1/orders",
                json=payload,
                headers={"Idempotency-Key": "concurrent-key-0123456789"},
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, range(2)))
    assert sorted(result.status_code for result in results) == (
        [201, 409] if conflicting else [201, 201]
    )
    if not conflicting:
        assert results[0].json["data"] == results[1].json["data"]
    with database.connect(mysql_app.config) as connection, connection.cursor() as cursor:
        for table in ("customers", "orders"):
            cursor.execute("SELECT COUNT(*) AS count FROM " + table)
            assert cursor.fetchone()["count"] == 1
