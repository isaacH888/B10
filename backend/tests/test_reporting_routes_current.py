"""Reporting HTTP contracts and verified deposit summaries across memory and MySQL."""

import pytest
from test_admin_completion import confirmed_order
from test_admin_orders import admin_app as admin_app
from test_admin_orders import assert_contract, submit
from test_auth import auth_app as auth_app
from test_automation_routes import owner_app as owner_app
from test_automation_routes import signed_owner
from test_automation_store import sql_settings as sql_settings
from test_orders import order_payload

AUTOMATION = "/api/v1/admin/automation"


@pytest.mark.parametrize("page", [1, 2])
def test_upcoming_http_response_matches_openapi_with_populated_and_empty_pages(admin_app, page):
    client, headers = signed_owner(admin_app)
    order, _ = confirmed_order(admin_app, client, headers)
    response = client.get("/api/v1/events/upcoming", query_string={"page": page, "page_size": 1})
    assert response.status_code == 200
    assert_contract(response, "UpcomingEventsResponse")
    data = response.json["data"]
    assert (data["page"], data["page_size"], data["total"]) == (page, 1, 1)
    assert [item["order_id"] for item in data["items"]] == ([order["id"]] if page == 1 else [])
    assert response.json["meta"] == {"request_id": response.headers["X-Request-ID"]}


@pytest.mark.parametrize(
    "paid_cents,deposit_status,confirmed_cents",
    [
        (0, "pending", 0),
        (2500, "pending", 2500),
        (10000, "confirmed", 10000),
        (20000, "confirmed", 10000),
        (25000, "confirmed", 10000),
    ],
)
def test_list_projects_verified_deposit_amounts_without_changing_the_source_order(
    admin_app, paid_cents, deposit_status, confirmed_cents
):
    client, headers = signed_owner(admin_app)
    key = "current-reporting-payments-0123456789"
    order = submit(admin_app, key=key)
    imported = client.post(
        AUTOMATION + f"/orders/{order['id']}/booking",
        json={"contract_url": "https://example.invalid/synthetic"},
        headers=headers,
    )
    assert imported.status_code == 201
    path = AUTOMATION + "/bookings/" + imported.json["data"]["id"]
    approved = client.post(path + "/approve", json={}, headers=headers)
    assert approved.status_code == 200
    booking = approved.json["data"]
    if paid_cents:
        paid = client.post(
            path + "/payments",
            json={
                "reference": key,
                "amount_minor": paid_cents,
                "currency": "USD",
                "verification_details": "Synthetic payment verified in isolated regression test",
            },
            headers=headers,
        )
        assert paid.status_code == 200
        booking = paid.json["data"]
    assert booking["paid_minor"] == paid_cents
    assert booking["deposit_minor"] == 10000

    response = client.get("/api/v1/orders")
    assert response.status_code == 200
    assert_contract(response, "ListOrdersResponse")
    item = response.json["data"]["items"][0]
    assert item["id"] == order["id"]
    assert item["deposit"] == {
        "status": deposit_status,
        "amount_due_cents": 10000,
        "amount_confirmed_cents": confirmed_cents,
    }
    assert item["pricing"] == order["pricing"]
    assert client.get(f"/api/v1/orders/{order['id']}").json["data"] == {**order, "admin_notes": ""}
    body = order_payload()
    body["customer"]["name"] = "Synthetic Customer"
    replay = client.post("/api/v1/orders", json=body, headers={"Idempotency-Key": key})
    assert replay.status_code == 201 and replay.json["data"] == order


def test_cancelled_order_keeps_its_verified_deposit_amount(admin_app):
    client, headers = signed_owner(admin_app)
    order, booking = confirmed_order(admin_app, client, headers)
    cancelled = client.post(
        AUTOMATION + "/bookings/" + booking["id"] + "/cancel",
        json={"expected_revision": booking["revision"]},
        headers=headers,
    )
    assert cancelled.status_code == 200
    response = client.get("/api/v1/orders?status=cancelled")
    assert response.status_code == 200
    assert_contract(response, "ListOrdersResponse")
    item = response.json["data"]["items"][0]
    assert item["id"] == order["id"] and item["status"] == "cancelled"
    assert item["deposit"] == {
        "status": "confirmed",
        "amount_due_cents": 10000,
        "amount_confirmed_cents": 10000,
    }
