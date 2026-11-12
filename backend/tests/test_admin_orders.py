"""Owner order reads must reflect durable intake and current booking state."""

import json
from pathlib import Path

import pymysql
import pytest
from app import database
from app.automation.store import Store
from jsonschema import Draft202012Validator, FormatChecker
from test_auth import auth_app as auth_app
from test_auth import invite, sign_in
from test_automation_routes import owner_app as owner_app
from test_automation_routes import signed_owner
from test_automation_store import sql_settings as sql_settings
from test_orders import order_payload

BASE = "/api/v1/admin/orders"
AUTOMATION = "/api/v1/admin/automation"


def assert_contract(response, name):
    spec = json.loads((Path(__file__).resolve().parents[2] / "docs/api/openapi.json").read_text())
    schema = {"components": spec["components"], "$ref": "#/components/schemas/" + name}
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(response.json)


@pytest.fixture(params=["memory", "mysql"])
def admin_app(request, owner_app):
    if request.param == "mysql":
        settings = request.getfixturevalue("sql_settings")
        owner_app.config.update(settings)
        store = Store(settings)
        owner_app.extensions["automation_store"] = store
        owner_app.extensions["booking_service"].store = store
    else:
        owner_app.config.update(DB_USER="", DB_PASSWORD="")
    yield owner_app
    if request.param == "mysql":
        with database.connect(owner_app.config) as connection, connection.cursor() as cursor:
            for table in ("automation_order_links", "order_items", "orders", "customers"):
                cursor.execute("DELETE FROM " + table)
            connection.commit()


def submit(app, name="Synthetic Customer", service="delivery", key="admin-order-0123456789"):
    body = order_payload(service_type=service)
    body["customer"]["name"] = name
    result = app.test_client().post("/api/v1/orders", json=body, headers={"Idempotency-Key": key})
    assert result.status_code == 201
    return result.json["data"]


@pytest.mark.parametrize("path", ["", "/order_unknown"])
def test_owner_workspace_rejects_anonymous_customer_and_staff(owner_app, path):
    owner_app.config.update(DB_USER="", DB_PASSWORD="")
    assert owner_app.test_client().get(BASE + path).status_code == 401
    customer = owner_app.test_client()
    sign_in(customer, "customer")
    assert customer.get(BASE + path).status_code == 401
    invite(owner_app, "staff")
    staff = owner_app.test_client()
    sign_in(staff, "admin")
    assert staff.get(BASE + path).status_code == 403


def test_revoked_owner_cannot_read_saved_contacts(owner_app):
    owner_app.config.update(DB_USER="", DB_PASSWORD="")
    order = submit(owner_app)
    client, _ = signed_owner(owner_app)
    identity = next(iter(owner_app.test_store.identities.values()))
    identity["admin_active"] = False
    for path in ("", "/" + order["id"]):
        result = client.get(BASE + path)
        assert result.status_code in {401, 403}
        assert "Synthetic Customer" not in result.get_data(as_text=True)


def test_saved_orders_filter_and_paginate_without_sample_records(admin_app):
    first = submit(admin_app, name="Alpha %_ Customer")
    second = submit(
        admin_app, name="Beta Customer", service="full_service", key="admin-order-9876543210"
    )
    client, _ = signed_owner(admin_app)
    result = client.get(BASE, query_string={"page_size": 1})
    assert result.status_code == 200
    assert_contract(result, "AdminWorkspaceOrdersResponse")
    assert result.headers["Cache-Control"] == "no-store"
    assert result.json["meta"]["request_id"] == result.headers["X-Request-ID"]
    data = result.json["data"]
    assert data["total"] == 2 and data["page"] == 1 and data["page_size"] == 1
    assert [row["order"]["id"] for row in data["items"]] == [second["id"]]
    assert data["storage"] == ("database" if admin_app.config["DB_USER"] else "memory")
    assert (
        client.get(BASE + "?page_size=1&page=2").json["data"]["items"][0]["order"]["id"]
        == first["id"]
    )
    for query, expected in (
        ({"q": "%_"}, [first["id"]]),
        ({"q": "beta"}, [second["id"]]),
        ({"q": first["id"]}, [first["id"]]),
        ({"service_type": "full_service"}, [second["id"]]),
        ({"status": "pending", "payment_status": "unpaid"}, [second["id"], first["id"]]),
        ({"payment_status": "paid"}, []),
        ({"page": 100}, []),
        ({"q": "' OR 1=1 --"}, []),
    ):
        response = client.get(BASE, query_string=query)
        assert response.status_code == 200
        assert [row["order"]["id"] for row in response.json["data"]["items"]] == expected, query
    detail = client.get(BASE + "/" + first["id"])
    assert_contract(detail, "AdminWorkspaceOrderResponse")
    assert detail.json["data"]["order"]["customer"]["name"] == "Alpha %_ Customer"
    assert detail.json["data"]["booking"] is None
    assert client.get(BASE + "/order_missing").status_code == 404


def test_linked_booking_controls_status_and_payment_filters(admin_app):
    order = submit(admin_app)
    client, headers = signed_owner(admin_app)
    booking = client.post(
        AUTOMATION + f"/orders/{order['id']}/booking",
        json={"contract_url": "https://example.invalid/synthetic-contract"},
        headers=headers,
    ).json["data"]
    booking_path = AUTOMATION + "/bookings/" + booking["id"]
    approved = client.post(booking_path + "/approve", json={}, headers=headers)
    assert approved.status_code == 200
    deposit = client.post(
        booking_path + "/payments",
        headers=headers,
        json={
            "reference": "admin-read-deposit",
            "amount_minor": booking["deposit_minor"],
            "currency": "USD",
            "verification_details": "Owner checked synthetic settled receipt",
        },
    )
    assert deposit.status_code == 200 and deposit.json["data"]["status"] == "confirmed"
    response = client.get(BASE + "/" + order["id"])
    assert_contract(response, "AdminWorkspaceOrderResponse")
    detail = response.json["data"]
    assert detail["order"]["status"] == "pending_review"
    assert detail["booking"]["status"] == "confirmed"
    assert detail["booking"]["paid_minor"] == booking["deposit_minor"]
    assert detail["booking"]["remaining_minor"] == booking["total_minor"] - booking["deposit_minor"]
    assert "contract_url" not in detail["booking"]
    assert "source_order" not in detail["booking"]
    filtered = client.get(BASE + "?status=confirmed&payment_status=partial").json["data"]
    assert filtered["total"] == 1 and filtered["items"] == [detail]
    assert client.get(BASE + "?status=pending").json["data"]["total"] == 0
    final = client.post(
        booking_path + "/payments",
        headers=headers,
        json={
            "reference": "admin-read-final",
            "amount_minor": booking["total_minor"] - booking["deposit_minor"],
            "currency": "USD",
            "verification_details": "Owner checked synthetic final receipt",
        },
    )
    assert final.status_code == 200
    assert client.get(BASE + "?payment_status=paid").json["data"]["total"] == 1
    assert client.get(BASE + "?payment_status=partial").json["data"]["total"] == 0
    cancelled = client.post(booking_path + "/cancel", json={}, headers=headers)
    assert cancelled.status_code == 200
    assert (
        client.get(BASE + "?status=cancelled").json["data"]["items"][0]["booking"]["status"]
        == "cancelled"
    )


@pytest.mark.parametrize(
    "query",
    [
        "page=0",
        "page_size=101",
        "page=garbage",
        "page=-1",
        "status=garbage",
        "payment_status=review",
        "service_type=pickup",
        "unknown=1",
        "page=1&page=2",
        "q=" + "x" * 151,
    ],
)
def test_invalid_filters_are_rejected_before_reading_storage(owner_app, monkeypatch, query):
    client, _ = signed_owner(owner_app)

    def forbidden(*args):
        pytest.fail("Invalid filters must not reach storage")

    monkeypatch.setattr("app.admin_orders._sql_page", forbidden)
    monkeypatch.setattr("app.admin_orders._memory_page", forbidden)
    assert client.get(BASE + "?" + query).status_code == 422


def test_database_failure_has_no_sample_or_memory_fallback(owner_app, monkeypatch):
    client, _ = signed_owner(owner_app)

    def unavailable(*args, **kwargs):
        raise pymysql.OperationalError("PRIVATE_DATABASE_DETAILS")

    monkeypatch.setattr(database, "connect", unavailable)
    for path in ("", "/order_unknown"):
        response = client.get(BASE + path)
        assert response.status_code == 503
        assert "PRIVATE_DATABASE_DETAILS" not in response.get_data(as_text=True)
        assert "items" not in response.json
