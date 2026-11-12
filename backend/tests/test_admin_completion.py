"""Durable admin integrations, stock invariants and current event data."""

import csv
import io
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from app import database
from app.automation.store import Store
from test_admin_orders import admin_app as admin_app
from test_admin_orders import assert_contract, submit
from test_auth import auth_app as auth_app
from test_auth import invite, sign_in
from test_automation_routes import owner_app as owner_app
from test_automation_routes import signed_owner
from test_automation_store import sql_settings as sql_settings

INVENTORY = "/api/v1/admin/inventory"
AUTOMATION = "/api/v1/admin/automation"


@pytest.fixture
def inventory_app(owner_app, sql_settings):
    owner_app.config.update(sql_settings)
    store = Store(sql_settings)
    owner_app.extensions["automation_store"] = store
    owner_app.extensions["booking_service"].store = store
    yield owner_app
    with database.connect(sql_settings) as connection, connection.cursor() as cursor:
        for table in (
            "inventory_reservations",
            "inventory_history",
            "inventory_actions",
            "inventory_items",
            "automation_order_links",
            "order_items",
            "orders",
            "customers",
        ):
            cursor.execute("DELETE FROM " + table)
        connection.commit()


def write(client, headers, path, body, method="POST", key=None):
    return client.open(
        path, method=method, json=body, headers={**headers, "Idempotency-Key": key or uuid4().hex}
    )


def create_item(client, headers, **changes):
    result = write(
        client,
        headers,
        INVENTORY,
        {
            "name": "Synthetic Mango",
            "category": "Fruit",
            "shape": "Standard",
            "onHand": 100,
            "minimum": 20,
            "notes": "Synthetic inventory",
            **changes,
        },
    )
    assert result.status_code == 201, result.json
    assert_contract(result, "InventoryItemResponse")
    return result.json["data"]["item"]


def confirmed_order(app, client, headers, key="confirmed-order-0123456789"):
    order = submit(app, key=key)
    result = client.post(
        AUTOMATION + f"/orders/{order['id']}/booking",
        json={"contract_url": "https://example.invalid/synthetic"},
        headers=headers,
    )
    assert result.status_code == 201
    booking = result.json["data"]
    path = AUTOMATION + "/bookings/" + booking["id"]
    assert client.post(path + "/approve", json={}, headers=headers).status_code == 200
    paid = client.post(
        path + "/payments",
        json={
            "reference": key,
            "amount_minor": booking["deposit_minor"],
            "currency": "USD",
            "verification_details": "Synthetic receipt verified in test fixture",
        },
        headers=headers,
    )
    assert paid.status_code == 200
    return order, paid.json["data"]


@pytest.mark.parametrize(
    "path",
    [
        "/admin/dashboard",
        "/admin/calendar?year=2099&month=1",
        "/admin/inventory",
        "/admin/inventory/unknown/history",
        "/admin/orders/export",
    ],
)
def test_new_admin_reads_require_owner(owner_app, path):
    owner_app.config.update(DB_USER="", DB_PASSWORD="")
    assert owner_app.test_client().get("/api/v1" + path).status_code == 401
    invite(owner_app, "staff")
    staff = owner_app.test_client()
    sign_in(staff, "admin")
    assert staff.get("/api/v1" + path).status_code == 403


def test_overview_and_calendar_use_current_saved_data_and_keep_same_day_events(admin_app):
    client, headers = signed_owner(admin_app)
    first, booking = confirmed_order(admin_app, client, headers)
    second = submit(admin_app, name="Second saved customer", key="second-order-0123456789")
    admin_app.config["ADMIN_CLOCK"] = lambda: datetime(2099, 1, 1, tzinfo=timezone.utc)
    response = client.get("/api/v1/admin/dashboard")
    assert response.status_code == 200, response.json
    assert_contract(response, "AdminDashboardResponse")
    data = response.json["data"]
    assert data["requests"] == 1
    assert data["upcoming_count"] == 1
    assert data["upcoming"][0]["order_id"] == first["id"]
    assert data["balances"] == [{"currency": "USD", "remaining_cents": booking["remaining_minor"]}]
    assert {row["order"]["id"] for row in data["recent_orders"]} == {first["id"], second["id"]}
    response = client.get("/api/v1/admin/calendar?year=2099&month=1")
    assert_contract(response, "AdminCalendarResponse")
    feed = response.json["data"]
    assert len(feed["events"]) == 2
    assert {event["order_id"] for event in feed["events"]} == {first["id"], second["id"]}
    assert feed["stats"]["confirmed"] == 1
    assert feed["stats"]["pending"] == 1
    assert feed["events"][0]["email"].endswith(".invalid")
    assert client.get("/api/v1/admin/calendar?year=2099&month=2").json["data"]["events"] == []
    assert client.get("/api/v1/admin/calendar?year=2098&month=1").json["data"]["events"] == []


def test_event_date_filters_and_safe_csv_export(admin_app):
    client, headers = signed_owner(admin_app)
    order = submit(admin_app, name=' =HYPERLINK("https://example.invalid")')
    base = "/api/v1/admin/orders"
    assert (
        client.get(base + "?event_from=2099-01-15T21:00:00Z&event_to=2099-01-15T22:00:00Z").json[
            "data"
        ]["total"]
        == 1
    )
    assert client.get(base + "?event_to=2099-01-15T21:00:00Z").json["data"]["total"] == 0
    assert client.get(base + "?event_from=2099-01-15T22:00:00").status_code == 422
    exported = client.get(base + f"/{order['id']}/export")
    assert exported.status_code == 200
    assert exported.headers["Content-Type"].startswith("text/csv")
    assert exported.headers["Cache-Control"] == "no-store"
    rows = list(csv.DictReader(io.StringIO(exported.get_data(as_text=True))))
    assert rows[0]["customer_name"].startswith("'")
    assert rows[0]["order_id"] == order["id"]
    assert rows[0]["total_cents"] == str(order["pricing"]["total_cents"])
    assert client.get(base + "/export?q=Nobody").get_data(as_text=True).count("\n") == 1
    admin_app.test_clock["now"] += 301
    assert client.get(base + "/export").status_code == 403


@pytest.mark.parametrize(
    "query",
    [
        "year=bad&month=1",
        "year=2099&month=13",
        "year=2099&month=0",
        "year=2099&month=1&timezone=Bad/Zone",
        "year=2099&month=1&month=2",
        "year=2099&month=1&unknown=1",
    ],
)
def test_calendar_rejects_invalid_windows(owner_app, query):
    client, _ = signed_owner(owner_app)
    assert client.get("/api/v1/admin/calendar?" + query).status_code == 422


def test_stock_persists_replays_once_and_rejects_stale_or_fractional_updates(inventory_app):
    client, headers = signed_owner(inventory_app)
    item = create_item(client, headers)
    path = INVENTORY + "/" + item["id"]
    payload = {
        "expected_version": item["version"],
        "type": "add",
        "quantity": 10,
        "reason": "Synthetic batch",
    }
    key = uuid4().hex
    first = write(client, headers, path + "/adjust", payload, key=key)
    assert first.status_code == 200
    assert first.json["data"]["item"]["onHand"] == 110
    replay = write(client, headers, path + "/adjust", payload, key=key)
    assert replay.json["data"] == first.json["data"]
    assert client.get(INVENTORY).json["data"]["items"][0]["onHand"] == 110
    assert write(client, headers, path + "/adjust", payload).status_code == 409
    assert write(client, headers, path + "/adjust", {**payload, "quantity": 1.5}).status_code == 422
    assert (
        write(client, headers, path + "/adjust", {**payload, "quantity": 11}, key=key).status_code
        == 409
    )
    response = client.get(path + "/history")
    assert_contract(response, "InventoryHistoryResponse")
    history = response.json["data"]
    assert history["total"] == 2
    assert history["history"][0]["after"] == 110
    assert history["history"][0]["before"] == 100
    assert (
        client.post(
            path + "/adjust", json=payload, headers={"Origin": headers["Origin"]}
        ).status_code
        == 403
    )
    current = first.json["data"]["item"]
    updated = write(
        client,
        headers,
        path,
        {"expected_version": current["version"], "name": "Renamed synthetic mango"},
        method="PATCH",
    )
    assert updated.status_code == 200
    assert client.get(INVENTORY).json["data"]["items"][0]["name"] == "Renamed synthetic mango"
    archived = write(
        client,
        headers,
        path,
        {"expected_version": updated.json["data"]["item"]["version"]},
        method="DELETE",
    )
    assert archived.status_code == 200
    assert client.get(INVENTORY).json["data"]["items"] == []
    assert client.get(path + "/history").json["data"]["total"] == 2


def test_explicit_allocations_prevent_overselling_and_cancellation_releases_stock(inventory_app):
    client, headers = signed_owner(inventory_app)
    item = create_item(client, headers, onHand=60)
    order, booking = confirmed_order(inventory_app, client, headers)
    path = INVENTORY + f"/bookings/{booking['id']}/allocations"
    allocated = write(
        client,
        headers,
        path,
        {
            "expected_revision": booking["revision"],
            "items": [{"item_id": item["id"], "quantity": 50}],
        },
    )
    assert allocated.status_code == 200, allocated.json
    assert_contract(allocated, "InventoryAllocationResponse")
    current = client.get(INVENTORY).json["data"]["items"][0]
    assert current["reserved"] == 50 and current["available"] == 10
    assert (
        write(
            client,
            headers,
            INVENTORY + f"/{item['id']}/adjust",
            {
                "expected_version": current["version"],
                "type": "set",
                "quantity": 49,
                "reason": "Synthetic count",
            },
        ).status_code
        == 409
    )
    booking_path = AUTOMATION + "/bookings/" + booking["id"]
    cancelled = client.post(
        booking_path + "/cancel",
        json={"expected_revision": allocated.json["data"]["revision"]},
        headers=headers,
    )
    assert cancelled.status_code == 200, cancelled.json
    assert client.get(INVENTORY).json["data"]["items"][0]["reserved"] == 0
    assert client.get(path).json["data"]["items"] == []


def test_simultaneous_stock_adjustments_cannot_lose_an_update(inventory_app):
    client, headers = signed_owner(inventory_app)
    item = create_item(client, headers)
    barrier = threading.Barrier(2)
    cookie = client.get_cookie("popssibilities_admin")

    def adjust(_):
        independent = inventory_app.test_client()
        independent.set_cookie(cookie.key, cookie.value)
        barrier.wait()
        return write(
            independent,
            headers,
            INVENTORY + f"/{item['id']}/adjust",
            {
                "expected_version": item["version"],
                "type": "add",
                "quantity": 10,
                "reason": "Concurrent batch",
            },
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(adjust, range(2))) == [200, 409]
    assert client.get(INVENTORY).json["data"]["items"][0]["onHand"] == 110


def test_inventory_create_replay_keeps_one_item_and_one_history_entry(inventory_app):
    client, headers = signed_owner(inventory_app)
    payload = {
        "name": "Replay Mango",
        "category": "Fruit",
        "shape": "Standard",
        "onHand": 100,
        "minimum": 20,
        "notes": "",
    }
    key = uuid4().hex
    first = write(client, headers, INVENTORY, payload, key=key)
    second = write(client, headers, INVENTORY, payload, key=key)
    assert first.status_code == second.status_code == 201
    assert first.json["data"] == second.json["data"]
    listed = client.get(INVENTORY)
    assert_contract(listed, "InventoryListResponse")
    assert len(listed.json["data"]["items"]) == 1
    item_id = first.json["data"]["item"]["id"]
    assert client.get(INVENTORY + f"/{item_id}/history").json["data"]["total"] == 1
    assert write(client, headers, INVENTORY, {**payload, "reserved": 100}).status_code == 422


@pytest.mark.parametrize(
    "method,path",
    [
        ("POST", INVENTORY),
        ("PATCH", INVENTORY + "/" + "a" * 32),
        ("DELETE", INVENTORY + "/" + "a" * 32),
        ("POST", INVENTORY + "/" + "a" * 32 + "/adjust"),
        ("POST", INVENTORY + "/bookings/" + "b" * 32 + "/allocations"),
    ],
)
def test_staff_cannot_mutate_inventory_even_with_valid_session_csrf(owner_app, method, path):
    invite(owner_app, "staff")
    client = owner_app.test_client()
    sign_in(client, "admin")
    token = client.get("/api/v1/admin/session").json["data"]["csrf_token"]
    assert (
        write(
            client,
            {"Origin": "http://localhost:5173", "X-CSRF-Token": token},
            path,
            {},
            method=method,
        ).status_code
        == 403
    )


def test_over_cap_export_is_rejected_instead_of_silently_truncated(owner_app, monkeypatch):
    client, _ = signed_owner(owner_app)
    monkeypatch.setattr("app.admin_orders._sql_page", lambda query: ([], 10001))
    result = client.get("/api/v1/admin/orders/export")
    assert result.status_code == 422 and result.json["error"]["code"] == "export_too_large"


def test_manual_bookings_have_real_booking_links_and_never_become_fake_orders(inventory_app):
    client, headers = signed_owner(inventory_app)
    body = {
        "start": "2099-01-15T21:00:00Z",
        "end": "2099-01-15T23:00:00Z",
        "timezone": "America/Chicago",
        "venue": "Synthetic hall",
        "quantity": 50,
        "service_type": "delivery",
        "customer_email": "manual@example.invalid",
        "total_minor": 20000,
        "currency": "USD",
        "contract_url": "https://example.invalid/synthetic",
    }
    created = client.post(AUTOMATION + "/bookings", json=body, headers=headers)
    assert created.status_code == 201
    events = client.get("/api/v1/admin/calendar?year=2099&month=1").json["data"]["events"]
    assert len(events) == 1 and events[0]["order_id"] is None
    assert events[0]["booking_id"] == created.json["data"]["id"]
    assert client.get("/api/v1/admin/orders").json["data"]["total"] == 0


def test_allocations_across_bookings_cannot_oversubscribe_the_same_stock(inventory_app):
    client, headers = signed_owner(inventory_app)
    item = create_item(client, headers, onHand=75)
    _, first = confirmed_order(inventory_app, client, headers, key="first-allocation-order-012345")
    _, second = confirmed_order(
        inventory_app, client, headers, key="second-allocation-order-012345"
    )

    def reserve(booking):
        return write(
            client,
            headers,
            INVENTORY + f"/bookings/{booking['id']}/allocations",
            {
                "expected_revision": booking["revision"],
                "items": [{"item_id": item["id"], "quantity": 50}],
            },
        )

    assert reserve(first).status_code == 200
    assert reserve(second).status_code == 409
    assert client.get(INVENTORY).json["data"]["items"][0]["reserved"] == 50
    assert (
        client.get(INVENTORY + f"/bookings/{second['id']}/allocations").json["data"]["items"] == []
    )


def test_calendar_and_date_filters_follow_rescheduling_and_cancellation(admin_app):
    client, headers = signed_owner(admin_app)
    order, booking = confirmed_order(admin_app, client, headers)
    path = AUTOMATION + "/bookings/" + booking["id"]
    moved = client.post(
        path + "/reschedule",
        json={
            "expected_revision": booking["revision"],
            "start": "2099-02-15T21:00:00Z",
            "end": "2099-02-15T23:00:00Z",
            "timezone": "America/Chicago",
            "venue": "Updated synthetic hall",
        },
        headers=headers,
    )
    assert moved.status_code == 200, moved.json
    assert client.get("/api/v1/admin/calendar?year=2099&month=1").json["data"]["events"] == []
    events = client.get("/api/v1/admin/calendar?year=2099&month=2").json["data"]["events"]
    assert len(events) == 1 and events[0]["order_id"] == order["id"]
    assert events[0]["venue"] == "Updated synthetic hall"
    assert (
        client.get("/api/v1/admin/orders?event_to=2099-02-01T00:00:00Z").json["data"]["total"] == 0
    )
    assert (
        client.post(
            path + "/cancel",
            json={"expected_revision": moved.json["data"]["revision"]},
            headers=headers,
        ).status_code
        == 200
    )
    assert client.get("/api/v1/admin/calendar?year=2099&month=2").json["data"]["events"] == []


def test_event_month_boundaries_use_requested_timezone(inventory_app):
    client, headers = signed_owner(inventory_app)
    body = {
        "start": "2099-03-01T03:00:00Z",
        "end": "2099-03-01T04:00:00Z",
        "timezone": "America/Chicago",
        "venue": "Synthetic hall",
        "quantity": 50,
        "service_type": "delivery",
        "customer_email": "boundary@example.invalid",
        "total_minor": 20000,
        "currency": "USD",
        "contract_url": "https://example.invalid/synthetic",
    }
    assert client.post(AUTOMATION + "/bookings", json=body, headers=headers).status_code == 201
    assert len(client.get("/api/v1/admin/calendar?year=2099&month=2").json["data"]["events"]) == 1
    assert client.get("/api/v1/admin/calendar?year=2099&month=3").json["data"]["events"] == []
    assert (
        len(
            client.get("/api/v1/admin/calendar?year=2099&month=3&timezone=UTC").json["data"][
                "events"
            ]
        )
        == 1
    )
