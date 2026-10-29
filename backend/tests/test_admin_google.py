"""Retired Google admin entry points fail closed; customer login stays supported."""

import pytest
from app.auth.errors import AuthError
from app.auth.service import digest
from app.auth.settings import cookie_name, mfa_cookie_name
from test_auth import NOW, ORIGIN, begin, invite, sign_in
from test_auth import auth_app as auth_app


def unexpected_provider_io(*args, **kwargs):
    raise AssertionError("Retired administrator Google authentication must not contact Cognito.")


def test_admin_google_rejected_without_flow_or_session_creation(auth_app, monkeypatch):
    client = auth_app.test_client()
    monkeypatch.setattr(
        auth_app.test_providers["admin"], "authorization_url", unexpected_provider_io
    )
    response = client.post(
        "/api/v1/admin/login", json={"provider": "google"}, headers={"Origin": ORIGIN}
    )
    assert response.status_code == 422
    assert response.json["error"]["code"] == "validation_error"
    assert not response.headers.getlist("Set-Cookie")
    assert not auth_app.test_store.flows
    assert not auth_app.test_store.sessions


def test_service_admin_google_rejected_even_without_route_validation(auth_app, monkeypatch):
    monkeypatch.setattr(
        auth_app.test_providers["admin"], "authorization_url", unexpected_provider_io
    )
    with pytest.raises(AuthError) as failure:
        auth_app.extensions["auth_service"].start_login("admin", "google", "127.0.0.1")
    assert failure.value.status == 422
    assert not auth_app.test_store.flows


@pytest.mark.parametrize("legacy_method", ["google", "unsupported", None])
def test_old_admin_oauth_callback_rejected_before_exchange(auth_app, monkeypatch, legacy_method):
    client = auth_app.test_client()
    invite(auth_app)
    state = begin(client, "admin")
    service = auth_app.extensions["auth_service"]
    flow = auth_app.test_store.flows[digest(state)]
    payload = service.decrypt(flow["encrypted_payload"])
    payload["provider"] = legacy_method
    flow["encrypted_payload"] = service.encrypt(payload)
    monkeypatch.setattr(auth_app.test_providers["admin"], "exchange", unexpected_provider_io)
    response = client.get(
        "/api/v1/admin/callback", query_string={"state": state, "code": "legacy-code"}
    )
    assert response.location == ORIGIN + "/admin/login?error=authentication_failed"
    assert not auth_app.test_store.sessions
    assert not auth_app.test_store.flows
    assert client.get_cookie(cookie_name(auth_app.config, "admin")) is None
    assert any(event == "login_method_denied" for event, _ in auth_app.test_store.events)
    replay = client.get(
        "/api/v1/admin/callback", query_string={"state": state, "code": "legacy-code"}
    )
    assert replay.location == ORIGIN + "/admin/login?error=login_expired"


@pytest.mark.parametrize("is_alias", [False, True])
@pytest.mark.parametrize("endpoint", ["/api/v1/admin/session", "/_test/booking", "/_test/export"])
def test_old_google_admin_session_revoked_before_provider_io(
    auth_app, monkeypatch, is_alias, endpoint
):
    client = auth_app.test_client()
    invite(auth_app)
    sign_in(client, "admin")
    row = next(iter(auth_app.test_store.sessions.values()))
    identity = next(iter(auth_app.test_store.identities.values()))
    identity.update(
        is_google_alias=is_alias,
        mfa_enrolled=True,
        mfa_version=1,
        google_subject="historical-google-user",
    )
    # Include native-looking claims too: a legacy assurance marker must never
    # regain access merely because a future migration changes stored fields.
    row["assurance"].update(
        provider="google",
        method="app_totp",
        mfa_version=1,
        google_subject="historical-google-user",
        provider_auth_time=NOW,
        verified_at=NOW,
    )
    monkeypatch.setattr(auth_app.test_providers["admin"], "current_user", unexpected_provider_io)
    monkeypatch.setattr(auth_app.test_providers["admin"], "refresh", unexpected_provider_io)
    response = client.get(endpoint)
    assert response.status_code == 403
    assert row["revoked_at"] == NOW
    assert client.get("/api/v1/admin/session").status_code == 401


@pytest.mark.parametrize(
    "provider,method,is_alias",
    [(None, "app_totp", False), ("password", "app_totp", False), (None, None, True)],
)
def test_legacy_google_alias_or_app_factor_cannot_masquerade_as_native_session(
    auth_app, provider, method, is_alias
):
    client = auth_app.test_client()
    invite(auth_app)
    sign_in(client, "admin")
    row = next(iter(auth_app.test_store.sessions.values()))
    identity = next(iter(auth_app.test_store.identities.values()))
    identity["is_google_alias"] = is_alias
    row["assurance"].update(provider=provider, method=method)
    assert client.get("/api/v1/admin/session").status_code == 403
    assert row["revoked_at"] == NOW


@pytest.mark.parametrize(
    "method,path,payload",
    [
        ("GET", "/api/v1/admin/mfa", None),
        ("POST", "/api/v1/admin/mfa/enroll", {}),
        ("POST", "/api/v1/admin/mfa/verify", {"code": "123456"}),
        ("DELETE", "/api/v1/admin/mfa", None),
    ],
)
def test_retired_app_mfa_endpoints_cannot_create_access(auth_app, method, path, payload):
    client = auth_app.test_client()
    client.set_cookie(mfa_cookie_name(auth_app.config), "p" * 43)
    client.set_cookie(cookie_name(auth_app.config, "admin", flow=True), "b" * 43)
    response = client.open(
        path, method=method, json=payload, headers={"Origin": ORIGIN, "X-CSRF-Token": "legacy-csrf"}
    )
    assert response.status_code == 404
    assert not auth_app.test_store.sessions
    assert client.get("/api/v1/admin/session").status_code == 401


@pytest.mark.parametrize("method", ["password", "google"])
def test_customer_login_refresh_and_logout_still_work_with_native_admin(auth_app, method):
    client = auth_app.test_client()
    invite(auth_app)
    sign_in(client, "admin")
    state = begin(client, "customer", method)
    callback = client.get(
        "/api/v1/customer/callback", query_string={"state": state, "code": "customer-code"}
    )
    assert callback.location == ORIGIN + "/account"
    assert client.get("/api/v1/customer/session").status_code == 200
    assert client.get("/api/v1/admin/session").status_code == 200
    auth_app.test_clock["now"] += 271
    customer = client.get("/api/v1/customer/session")
    assert customer.status_code == 200
    assert auth_app.test_providers["customer"].refresh_count == 1
    logout = client.delete(
        "/api/v1/customer/session",
        headers={"Origin": ORIGIN, "X-CSRF-Token": customer.json["data"]["csrf_token"]},
    )
    assert logout.status_code == 200
    assert client.get("/api/v1/customer/session").status_code == 401
    assert client.get("/api/v1/admin/session").status_code == 200


def test_native_login_and_logout_clear_historical_mfa_cookie(auth_app):
    client = auth_app.test_client()
    invite(auth_app)
    client.set_cookie(mfa_cookie_name(auth_app.config), "p" * 43)
    callback = sign_in(client, "admin")
    assert callback.location == ORIGIN + "/admin"
    assert client.get_cookie(mfa_cookie_name(auth_app.config)) is None
    csrf = client.get("/api/v1/admin/session").json["data"]["csrf_token"]
    client.set_cookie(mfa_cookie_name(auth_app.config), "p" * 43)
    response = client.delete(
        "/api/v1/admin/session", headers={"Origin": ORIGIN, "X-CSRF-Token": csrf}
    )
    assert response.status_code == 200
    assert client.get_cookie(mfa_cookie_name(auth_app.config)) is None


def test_historical_google_alias_cannot_gain_password_admin_access(auth_app):
    client = auth_app.test_client()
    invite(auth_app)
    identity = next(iter(auth_app.test_store.identities.values()))
    identity["is_google_alias"] = True
    response = sign_in(client, "admin")
    assert response.location == ORIGIN + "/admin/login?error=admin_not_invited"
    assert not auth_app.test_store.sessions
