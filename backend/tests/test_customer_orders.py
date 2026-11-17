"""Customer sign-in, quote ownership, private history and live order tracking."""

import json

import pytest
from app import create_app
from test_auth import ORIGIN, customer_session, invite, sign_in
from test_auth import auth_app as auth_app
from test_automation_routes import owner_app as owner_app
from test_automation_store import sql_settings as sql_settings
from test_order_intake import intake_app as intake_app
from test_order_intake import mysql_app as mysql_app
from test_orders import FakeConnection, bind_quote, link_booking, order_payload, post_order
from test_orders import app as app
from test_orders import client as client
from test_orders import database as database


def another_customer(app, monkeypatch):
    provider = app.test_providers["customer"]
    original = provider.validate

    def claims(*args, **kwargs):
        return {**original(*args, **kwargs), "subject": "another-customer"}

    # The provider deliberately returns the same verified email: ownership is
    # still the stable account identity, not the contact or provider email.
    monkeypatch.setattr(provider, "validate", claims)
    return customer_session(app.test_client())


@pytest.mark.parametrize("area", [None, "admin"])
def test_guest_and_admin_session_cannot_create_quotes_or_orders_or_read_history(app, area):
    browser = app.test_client()
    if area:
        invite(app)
        sign_in(browser, area)
    for response in (
        browser.post("/api/v1/quotes", json={}),
        browser.post("/api/v1/orders", json={}),
        browser.get("/api/v1/customer/orders"),
    ):
        assert response.status_code == 401
        assert "data" not in response.json
    assert not app.extensions["quotes_memory"]["quotes"]
    assert not app.extensions["orders_memory"]["orders"]


@pytest.mark.parametrize("path", ["/quotes", "/orders"])
@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": ORIGIN, "X-CSRF-Token": ""},
        {"Origin": "https://other.example.invalid"},
        {"Origin": ""},
    ],
)
def test_customer_writes_require_csrf_and_same_origin(client, path, headers):
    response = client.post("/api/v1" + path, json={}, headers=headers)
    assert response.status_code == 403


def test_disabled_authentication_does_not_allow_guest_checkout(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    browser = create_app({"TESTING": True, "AUTH_ENABLED": False}).test_client()
    assert browser.post("/api/v1/quotes", json={}).status_code == 503
    assert browser.post("/api/v1/orders", json={}).status_code == 503
    assert browser.get("/api/v1/customer/orders").status_code == 503


def test_quote_cannot_be_used_by_another_customer(app, client, monkeypatch):
    body = order_payload()
    bind_quote(client, body)
    other = another_customer(app, monkeypatch)
    response = other.post(
        "/api/v1/orders", json=body, headers={"Idempotency-Key": "other-account-order-012345"}
    )
    assert response.status_code == 404
    assert response.json["error"]["code"] == "not_found"
    assert not app.extensions["quotes_memory"]["quotes"][body["quote_id"]]["is_used"]
    assert post_order(client, body).status_code == 201


def test_history_and_submission_replay_are_private_even_with_matching_email(
    app, client, monkeypatch
):
    body = order_payload()
    first = post_order(client, body).json["data"]
    other = another_customer(app, monkeypatch)
    history = other.get("/api/v1/customer/orders").json["data"]
    assert history["items"] == [] and history["total"] == 0
    replay = post_order(other, body)
    assert replay.status_code == 409
    assert first["id"] not in replay.get_data(as_text=True)
    own = client.get("/api/v1/customer/orders")
    assert own.status_code == 200
    assert [item["id"] for item in own.json["data"]["items"]] == [first["id"]]
    assert "admin_notes" not in own.get_data(as_text=True)
    assert "identity_id" not in own.get_data(as_text=True)


def test_later_sign_in_restores_history_and_live_booking_status(app, client):
    body = order_payload()
    order = post_order(client, body).json["data"]
    app.extensions["orders_memory"]["by_id"][order["id"]]["admin_notes"] = "private-owner-note"
    link_booking(
        app, order["id"], "confirmed", "deposit_paid", deposit_minor=14750, paid_minor=14750
    )
    browser = customer_session(app.test_client())
    response = browser.get("/api/v1/customer/orders")
    item = response.json["data"]["items"][0]
    assert item["id"] == order["id"] and item["status"] == "confirmed"
    assert item["deposit"]["status"] == "confirmed"
    assert item["deposit"]["amount_confirmed_cents"] == 14750
    assert "private-owner-note" not in response.get_data(as_text=True)
    assert post_order(client, body).json["data"] == order  # immutable submission replay


def test_customer_history_is_paginated_and_rejects_invalid_pages(client):
    orders = [
        post_order(client, headers={"Idempotency-Key": f"customer-page-0123456789-{i}"}).json[
            "data"
        ]
        for i in range(3)
    ]
    result = client.get("/api/v1/customer/orders?page=2&page_size=2").json["data"]
    assert result["total"] == 3 and result["page"] == 2
    assert [item["id"] for item in result["items"]] == [orders[0]["id"]]
    assert client.get("/api/v1/customer/orders?page=0").status_code == 422
    assert client.get("/api/v1/customer/orders?page_size=101").status_code == 422


def test_sql_history_filters_account_before_counting_or_paging(client, database):
    order = post_order(client).json["data"]
    database.connection = FakeConnection(
        rows=[(json.dumps(order), "confirmed", "pending", None)], total=1
    )
    response = client.get("/api/v1/customer/orders?page=2&page_size=1")
    assert response.status_code == 200
    assert response.json["data"]["items"][0]["status"] == "confirmed"
    identity = client.get("/api/v1/customer/session").json["data"]["customer"]["id"]
    queries = database.connection.statements
    assert len(queries) == 2
    for sql, params in queries:
        assert "JOIN customer_order_accounts a ON a.order_id = o.public_id" in sql
        assert "WHERE a.identity_id = %s" in sql
        assert params[0] == identity
    assert queries[1][1] == (identity, 1, 1)


@pytest.mark.parametrize("table", ["customer_quote_accounts", "customer_order_accounts"])
def test_account_link_failure_rolls_back_creation(client, database, table):
    database.connection = FakeConnection(fail_on="INSERT INTO " + table)
    response = (
        client.post(
            "/api/v1/quotes",
            json={key: order_payload()[key] for key in ("catering_request", "event")},
        )
        if table == "customer_quote_accounts"
        else post_order(client)
    )
    assert response.status_code == 503
    assert database.connection.rolled_back and not database.connection.committed


def test_account_owned_checkout_and_history_with_real_persistence(intake_app, monkeypatch):
    app = intake_app
    browser = customer_session(app.test_client())
    body = order_payload()
    order = post_order(browser, body).json["data"]
    restored = customer_session(app.test_client())
    response = restored.get("/api/v1/customer/orders")
    assert response.status_code == 200
    assert [item["id"] for item in response.json["data"]["items"]] == [order["id"]]
    other = another_customer(app, monkeypatch)
    assert other.get("/api/v1/customer/orders").json["data"]["total"] == 0
    assert post_order(other, body).status_code == 409
    # A fresh quote also cannot cross accounts, even before it is used.
    fresh = order_payload()
    bind_quote(browser, fresh)
    assert (
        post_order(
            other, fresh, headers={"Idempotency-Key": "cross-account-fresh-01234"}
        ).status_code
        == 404
    )
