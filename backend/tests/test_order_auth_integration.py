"""Exercise the real order routes with sessions, CSRF and role permissions."""

import pytest
from app import create_app
from test_auth import ORIGIN, invite, sign_in
from test_auth import auth_app as auth_app
from test_orders import HEADERS, order_payload


@pytest.fixture
def order_app(auth_app):
    # Provider and auth persistence are injected by auth_app; no database is used.
    auth_app.config.update(DB_USER="", DB_PASSWORD="")
    return auth_app


def administrator(app, role="owner"):
    client = app.test_client()
    invite(app, role)
    sign_in(client, "admin")
    session = client.get("/api/v1/admin/session")
    return client, {"Origin": ORIGIN, "X-CSRF-Token": session.json["data"]["csrf_token"]}


def submit(app):
    response = app.test_client().post("/api/v1/orders", json=order_payload(), headers=HEADERS)
    assert response.status_code == 201
    return response.json["data"]


def test_public_quote_and_submission_work_with_authentication_enabled(order_app):
    client = order_app.test_client()
    payload = order_payload()
    quote = client.post(
        "/api/v1/quotes",
        json={key: payload[key] for key in ("catering_request", "event")},
    )
    assert quote.status_code == 200
    payload["quote_id"] = quote.json["data"]["id"]
    created = client.post("/api/v1/orders", json=payload, headers=HEADERS)
    assert created.status_code == 201
    assert created.json["data"]["pricing"] == quote.json["data"]["pricing"]
    assert created.headers["X-Content-Type-Options"] == "nosniff"
    assert created.headers["X-Request-ID"] == created.json["meta"]["request_id"]


@pytest.mark.parametrize("area", [None, "customer"])
def test_anonymous_and_customer_sessions_cannot_access_admin_orders(order_app, area):
    order = submit(order_app)
    client = order_app.test_client()
    if area:
        sign_in(client, area)
    for response in (
        client.get(f"/api/v1/orders/{order['id']}"),
        client.patch(
            f"/api/v1/orders/{order['id']}/status",
            json={"version": 1, "status": "confirmed"},
            headers={"Origin": ORIGIN},
        ),
    ):
        assert response.status_code == 401
        assert "customer@example.invalid" not in response.get_data(as_text=True)
    assert order_app.extensions["orders_memory"]["by_id"][order["id"]]["version"] == 1


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Origin": ORIGIN},
        {"Origin": "https://other.example.invalid", "X-CSRF-Token": "invalid"},
    ],
)
def test_order_status_changes_require_same_origin_and_valid_csrf(order_app, headers):
    order = submit(order_app)
    client, _ = administrator(order_app)
    response = client.patch(
        f"/api/v1/orders/{order['id']}/status",
        json={"version": 1, "status": "confirmed"},
        headers=headers,
    )
    assert response.status_code == 403
    assert client.get(f"/api/v1/orders/{order['id']}").json["data"]["version"] == 1


@pytest.mark.parametrize("status", ["confirmed", "cancelled", "pending_review"])
def test_staff_cannot_perform_owner_status_actions(order_app, status):
    order = submit(order_app)
    client, headers = administrator(order_app, "staff")
    assert client.get(f"/api/v1/orders/{order['id']}").status_code == 200
    response = client.patch(
        f"/api/v1/orders/{order['id']}/status",
        json={"version": 1, "status": status},
        headers=headers,
    )
    assert response.status_code == 403
    assert client.get(f"/api/v1/orders/{order['id']}").json["data"]["version"] == 1


def test_owner_confirmation_then_staff_fulfillment_preserves_prices(order_app):
    order = submit(order_app)
    owner, headers = administrator(order_app)
    confirmed = owner.patch(
        f"/api/v1/orders/{order['id']}/status",
        json={"version": 1, "status": "confirmed"},
        headers=headers,
    )
    assert confirmed.status_code == 200
    staff, headers = administrator(order_app, "staff")
    fulfilled = staff.patch(
        f"/api/v1/orders/{order['id']}/status",
        json={"version": 2, "status": "fulfilled"},
        headers=headers,
    )
    assert fulfilled.status_code == 200
    assert fulfilled.json["data"]["version"] == 3
    assert fulfilled.json["data"]["pricing"] == order["pricing"]
    assert fulfilled.json["data"]["status"] == "fulfilled"


def test_disabling_authentication_never_exposes_private_order_routes(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    app = create_app({"TESTING": True, "AUTH_ENABLED": False})
    client = app.test_client()
    assert client.get("/api/v1/orders/order_example").status_code == 503
    assert (
        client.patch(
            "/api/v1/orders/order_example/status", json={"version": 1, "status": "confirmed"}
        ).status_code
        == 503
    )


def test_revoked_admin_access_blocks_order_mutations(order_app):
    order = submit(order_app)
    client, headers = administrator(order_app)
    identity = next(iter(order_app.test_store.identities.values()))
    identity["admin_active"] = False
    response = client.patch(
        f"/api/v1/orders/{order['id']}/status",
        json={"version": 1, "status": "confirmed"},
        headers=headers,
    )
    assert response.status_code == 403
    assert order_app.extensions["orders_memory"]["by_id"][order["id"]]["version"] == 1
