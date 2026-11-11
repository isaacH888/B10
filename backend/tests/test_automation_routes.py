"""Exercise the actual Cognito session/CSRF/role guards with offline providers."""

import pytest
from app.automation.domain import BookingService
from app.automation.store import MemoryStore
from test_auth import ORIGIN, invite, sign_in
from test_auth import auth_app as auth_app

BASE = "/api/v1/admin/automation"
WRITES = [
    "/google/connect",
    "/google/disconnect",
    "/bookings",
    "/orders/unknown/booking",
    "/jobs/unknown/retry",
    *[
        "/bookings/unknown/" + action
        for action in (
            "approve",
            "payments",
            "reschedule",
            "cancel",
            "reopen",
            "final-count",
            "retry",
            "repair",
        )
    ],
]


class OfflineOAuth:
    def status(self, owner_id):
        return {"status": "disconnected", "calendar_id": None}

    def start(self, owner_id, session_id):
        return {"authorization_url": "https://accounts.google.com/o/oauth2/v2/auth?state=synthetic"}

    def disconnect(self, owner_id):
        return self.status(owner_id)


@pytest.fixture
def owner_app(auth_app):
    auth_app.config["AUTOMATION_ENABLED"] = True
    store = MemoryStore()
    auth_app.extensions.update(
        automation_store=store,
        google_oauth=OfflineOAuth(),
        booking_service=BookingService(store, clock=lambda: auth_app.test_clock["now"]),
    )
    return auth_app


def signed_owner(app):
    invite(app)
    client = app.test_client()
    sign_in(client, "admin")
    csrf = client.get("/api/v1/admin/session").json["data"]["csrf_token"]
    return client, {"Origin": ORIGIN, "X-CSRF-Token": csrf}


@pytest.mark.parametrize(
    "path",
    ["/google", "/orders", "/bookings", "/bookings/unknown", "/google/callback?state=x&code=x"],
)
def test_automation_reads_require_real_owner_session(owner_app, path):
    assert owner_app.test_client().get(BASE + path).status_code == 401
    invite(owner_app, role="staff")
    client = owner_app.test_client()
    sign_in(client, "admin")
    assert client.get(BASE + path).status_code == 403


@pytest.mark.parametrize("path", WRITES)
def test_every_owner_mutation_rejects_unsigned_or_csrf_missing_requests(owner_app, path):
    assert owner_app.test_client().post(BASE + path, json={}).status_code == 401
    client, headers = signed_owner(owner_app)
    assert client.post(BASE + path, json={}, headers={"Origin": ORIGIN}).status_code == 403
    headers["Origin"] = "https://attacker.example.invalid"
    assert client.post(BASE + path, json={}, headers=headers).status_code == 403


def test_staff_cannot_verify_payments_or_connect_google(owner_app):
    invite(owner_app, role="staff")
    client = owner_app.test_client()
    sign_in(client, "admin")
    csrf = client.get("/api/v1/admin/session").json["data"]["csrf_token"]
    for path in WRITES:
        assert (
            client.post(
                BASE + path, json={}, headers={"Origin": ORIGIN, "X-CSRF-Token": csrf}
            ).status_code
            == 403
        )


def test_owner_booking_deposit_and_cancellation_end_to_end(owner_app):
    client, headers = signed_owner(owner_app)
    request = {
        "start": "2027-06-12T14:00:00-05:00",
        "end": "2027-06-12T16:00:00-05:00",
        "timezone": "America/Chicago",
        "venue": "Synthetic venue",
        "quantity": 50,
        "service_type": "delivery",
        "total_minor": 10001,
        "currency": "USD",
        "customer_email": "synthetic@example.invalid",
        "contract_url": "https://example.invalid/contract",
    }
    result = client.post(BASE + "/bookings", json=request, headers=headers)
    assert result.status_code == 201
    booking = result.json["data"]
    path = BASE + "/bookings/" + booking["id"]
    assert (
        client.post(path + "/approve", json={}, headers=headers).json["data"]["status"]
        == "awaiting_deposit"
    )
    payment = {
        "reference": "external-payment-001",
        "amount_minor": 5001,
        "currency": "USD",
        "verification_details": "Owner checked settled transaction in provider account",
    }
    result = client.post(path + "/payments", json=payment, headers=headers)
    assert result.status_code == 200
    assert result.json["data"]["status"] == "confirmed"
    assert result.json["data"]["remaining_minor"] == 5000
    assert result.json["data"]["calendar_status"] == "pending"
    assert client.post(path + "/payments", json=payment, headers=headers).status_code == 200
    read = client.get(path).json["data"]
    assert len(read["payments"]) == 1
    assert (
        client.post(path + "/cancel", json={}, headers=headers).json["data"]["status"]
        == "cancelled"
    )
    assert len(client.get(path).json["data"]["payments"]) == 1
    assert client.get(BASE + "/bookings").status_code == 200


def test_payment_client_status_is_rejected_and_validation_is_useful(owner_app):
    client, headers = signed_owner(owner_app)
    bad = client.post(BASE + "/bookings", json={"quantity": 49}, headers=headers)
    assert bad.status_code == 400
    assert "start" in bad.json["error"]["message"]
    assert client.post(BASE + "/bookings", json=[], headers=headers).status_code == 422


def test_stale_authentication_and_revoked_owner_access_fail_closed(owner_app):
    client, headers = signed_owner(owner_app)
    owner_app.test_clock["now"] += 301
    result = client.post(BASE + "/google/connect", json={}, headers=headers)
    assert result.status_code == 403
    assert result.json["error"]["code"] == "reauthentication_required"
    assert client.get(BASE + "/google").status_code == 200
    identity = next(iter(owner_app.test_store.identities.values()))
    identity["admin_active"] = False
    assert client.get(BASE + "/bookings").status_code == 403


def test_google_callback_returns_owner_to_connection_controls(owner_app, monkeypatch):
    client, _ = signed_owner(owner_app)
    received = []
    monkeypatch.setattr(
        owner_app.extensions["google_oauth"],
        "finish",
        lambda *args: received.append(args),
        raising=False,
    )
    result = client.get(
        BASE + "/google/callback",
        query_string={"state": "synthetic-state", "code": "synthetic-code"},
    )
    assert result.status_code == 303
    assert result.location == ORIGIN + "/admin/automation?calendar=connected"
    assert received[0][:2] == ("synthetic-state", "synthetic-code")
    assert received[0][2] == next(iter(owner_app.test_store.identities.values()))["id"]
    assert received[0][3] in owner_app.test_store.sessions
