"""Authentication boundaries with injected providers and a test-only store."""

from contextlib import contextmanager
from copy import deepcopy
import json
from urllib.parse import parse_qs, urlsplit

from cryptography.fernet import Fernet
from flask import jsonify
import pytest

from app import create_app
from app.auth.errors import AuthError
from app.auth.guards import require_admin, require_customer
from app.auth.service import digest
from app.auth.settings import cookie_name
from app.auth.store import LoginCancelledError, StoreUnavailable


ORIGIN = "http://localhost:5173"
NOW = 1791410400


class MemoryStore:
    """Only test fixtures use this store; web startup always selects MySQL."""
    def __init__(self):
        self.flows, self.identities, self.sessions, self.buckets = {}, {}, {}, {}
        self.events = []
        self.cancelled_flows = {}

    def rate_limit(self, bucket, limit, window, now):
        key = (bucket, now // window)
        self.buckets[key] = self.buckets.get(key, 0) + 1
        return self.buckets[key] <= limit

    def audit(self, event, **kwargs):
        self.events.append((event, kwargs))

    def put_flow(self, flow):
        if self.cancelled_flows.get((flow["binding_hash"], flow["area"]), 0) > flow["created_at"]:
            raise LoginCancelledError("Cancelled test transaction")
        self.flows[flow["state_hash"]] = deepcopy(flow)

    def consume_flow(self, state_hash, binding_hash, area, now):
        flow = self.flows.get(state_hash)
        if not flow or flow["binding_hash"] != binding_hash or flow["area"] != area or flow["expires_at"] <= now:
            return None
        return self.flows.pop(state_hash)

    def find_identity(self, issuer, subject):
        return deepcopy(self.identities.get((issuer, subject)))

    def cancel_login(self, binding_hash, area, now):
        self.cancelled_flows[(binding_hash, area)] = now + 600
        self.flows = {key: flow for key, flow in self.flows.items()
                      if (flow["binding_hash"], flow["area"]) != (binding_hash, area)}
        for token_hash, session in self.sessions.items():
            if (session.get("login_binding_hash"), session["area"]) == (binding_hash, area):
                self.revoke_session(token_hash, now)

    def upsert_identity(self, issuer, subject, area, email, name, now):
        row = self.identities.setdefault((issuer, subject), {
            "id": str(len(self.identities) + 1), "issuer": issuer, "subject": subject,
            "area": area, "admin_role": None, "admin_active": False})
        assert row["area"] == area
        row.update(email=email, name=name)
        return deepcopy(row)

    def create_session(self, session):
        if self.cancelled_flows.get((session.get("login_binding_hash"), session["area"]), 0) > session["created_at"]:
            raise LoginCancelledError("Cancelled test transaction")
        self.sessions[session["token_hash"]] = deepcopy(session)

    def get_session(self, token_hash, area):
        row = self.sessions.get(token_hash)
        if not row or row["area"] != area or row.get("revoked_at"):
            return None
        identity = next(i for i in self.identities.values() if i["id"] == row["identity_id"])
        return {**deepcopy(identity), **deepcopy(row)}

    def revoke_session(self, token_hash, now):
        if token_hash in self.sessions:
            self.sessions[token_hash]["revoked_at"] = now

    def touch_session(self, token_hash, now):
        self.sessions[token_hash]["last_seen"] = now

    def update_tokens(self, token_hash, encrypted, now):
        if self.sessions[token_hash].get("revoked_at"):
            return False
        self.sessions[token_hash]["encrypted_tokens"] = encrypted
        return True

    @contextmanager
    def session_lock(self, token_hash):
        yield


class FakeProvider:
    def __init__(self, area, clock):
        self.area, self.clock = area, clock
        self.issuer = f"https://cognito-idp.us-east-1.amazonaws.com/us-east-1_{area}"
        self.nonce, self.fail, self.revoke_fail = None, None, False
        self.refresh_count = 0
        self.auth_time = clock["now"]

    def authorization_url(self, state, nonce, verifier, provider):
        self.nonce = nonce
        return f"https://{self.area}.example.invalid/authorize?state={state}&method={provider}"

    def exchange(self, code, verifier):
        return {"access_token": "private-access-token", "id_token": "private-id-token", "refresh_token": "private-refresh-token"}

    def validate(self, tokens, now, nonce=None, started_at=None, provider="password"):
        if self.fail:
            raise self.fail
        if nonce is not None:
            assert nonce == self.nonce
        return {"issuer": self.issuer, "subject": f"{self.area}-subject", "email": "synthetic@example.invalid",
                "name": "Synthetic Person", "auth_time": self.auth_time,
                "assurance": {"acr": "urn:cognito:loa:4", "amr": ["pwd", "otp", "mfa"]},
                "token_expires_at": now + 300}

    def current_user(self, access_token, subject):
        if self.fail:
            raise self.fail

    def refresh(self, refresh_token):
        self.refresh_count += 1
        return {"access_token": "new-access-token", "id_token": "new-id-token", "refresh_token": "new-refresh-token"}

    def revoke(self, refresh_token):
        if self.revoke_fail:
            raise AuthError("authentication_unavailable", "Private provider failure", 503)

    def logout_url(self):
        return f"https://{self.area}.example.invalid/logout"


@pytest.fixture
def auth_app(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    clock = {"now": NOW}
    store = MemoryStore()
    providers = {area: FakeProvider(area, clock) for area in ("customer", "admin")}
    settings = {"TESTING": True, "APP_ENV": "development", "AUTH_ENABLED": True,
                "AUTH_ORIGIN": ORIGIN, "CORS_ORIGINS": [ORIGIN], "SECRET_KEY": "synthetic-test-secret-" * 3,
                "AUTH_TOKEN_ENCRYPTION_KEY": Fernet.generate_key().decode(),
                "DB_USER": "synthetic", "DB_PASSWORD": "synthetic", "AUTH_STORE": store,
                "AUTH_PROVIDERS": providers, "AUTH_CLOCK": lambda: clock["now"]}
    for area in ("customer", "admin"):
        prefix = f"COGNITO_{area.upper()}_"
        settings.update({prefix + "ISSUER": providers[area].issuer, prefix + "CLIENT_ID": area + "-client",
                         prefix + "CLIENT_SECRET": "synthetic-test-only", prefix + "DOMAIN": f"https://{area}.example.invalid"})
    app = create_app(settings)
    app.test_store, app.test_providers, app.test_clock = store, providers, clock

    @app.route("/_test/export", methods=["GET", "POST"])
    @require_admin("customers:export", fresh=True)
    def export():
        return jsonify(ok=True)

    @app.route("/_test/booking", methods=["GET", "POST"])
    @require_admin()
    def booking():
        return jsonify(ok=True)

    @app.get("/_test/account")
    @require_customer
    def account():
        return jsonify(ok=True)

    return app


def invite(app, role="owner"):
    provider = app.test_providers["admin"]
    app.test_store.upsert_identity(provider.issuer, "admin-subject", "admin", "synthetic@example.invalid", "Synthetic", NOW)
    app.test_store.identities[(provider.issuer, "admin-subject")].update(admin_role=role, admin_active=True)


def begin(client, area="customer", provider="password"):
    result = client.post(f"/api/v1/{area}/login", json={"provider": provider}, headers={"Origin": ORIGIN})
    assert result.status_code == 200, result.json
    state = parse_qs(urlsplit(result.json["data"]["authorization_url"]).query)["state"][0]
    return state


def sign_in(client, area="customer"):
    state = begin(client, area)
    result = client.get(f"/api/v1/{area}/callback", query_string={"state": state, "code": "synthetic-code"})
    assert result.status_code == 303
    return result


def test_unconfigured_authentication_never_grants_access(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("AUTH_ENABLED", "false")
    client = create_app({"TESTING": True}).test_client()
    for area in ("customer", "admin"):
        assert client.get(f"/api/v1/{area}/session").status_code == 503
        assert client.post(f"/api/v1/{area}/login", json={}, headers={"Origin": ORIGIN}).status_code == 503


def test_customer_flow_cookie_and_session_do_not_expose_tokens(auth_app):
    client = auth_app.test_client()
    callback = sign_in(client)
    assert callback.location == ORIGIN + "/account"
    session = client.get("/api/v1/customer/session")
    assert session.status_code == 200
    assert session.json["data"]["customer"]["email"] == "synthetic@example.invalid"
    assert session.json["data"]["csrf_token"]
    assert session.headers["Cache-Control"] == "no-store"
    assert "HttpOnly" in callback.headers["Set-Cookie"]
    assert "SameSite=Lax" in callback.headers["Set-Cookie"]
    assert "private-" not in session.get_data(as_text=True)
    row = next(iter(auth_app.test_store.sessions.values()))
    assert "private-" not in row["encrypted_tokens"]
    flow = next(iter(auth_app.test_store.flows.values()), None)
    assert flow is None


def test_both_realms_offer_google_and_raw_credentials_are_rejected(auth_app):
    client = auth_app.test_client()
    assert "method=google" in client.post("/api/v1/customer/login", json={"provider": "google"}, headers={"Origin": ORIGIN}).json["data"]["authorization_url"]
    assert "method=google" in client.post("/api/v1/admin/login", json={"provider": "google"}, headers={"Origin": ORIGIN}).json["data"]["authorization_url"]
    assert client.post("/api/v1/admin/login", json={"email": "owner@example.invalid", "password": "private"}, headers={"Origin": ORIGIN}).status_code == 422


@pytest.mark.parametrize("provider", [[], {}, None, 12, "unsupported"])
def test_malformed_customer_provider_is_validation_error(auth_app, provider):
    response = auth_app.test_client().post("/api/v1/customer/login", json={"provider": provider}, headers={"Origin": ORIGIN})
    assert response.status_code == 422
    assert response.json["error"]["code"] == "validation_error"


@pytest.mark.parametrize("origin", [None, "https://evil.example.invalid", "null"])
def test_login_requires_exact_origin(auth_app, origin):
    headers = {} if origin is None else {"Origin": origin}
    assert auth_app.test_client().post("/api/v1/customer/login", json={}, headers=headers).status_code == 403


def test_callback_bound_to_browser_area_and_consumed_once(auth_app):
    client = auth_app.test_client()
    state = begin(client)
    foreign = auth_app.test_client()
    assert "error=authentication_failed" in foreign.get("/api/v1/customer/callback", query_string={"state": state, "code": "code"}).location
    assert "error=authentication_failed" in client.get("/api/v1/admin/callback", query_string={"state": state, "code": "code"}).location
    assert client.get("/api/v1/customer/callback", query_string={"state": state, "code": "code"}).location == ORIGIN + "/account"
    assert "error=" in client.get("/api/v1/customer/callback", query_string={"state": state, "code": "code"}).location
    assert len(auth_app.test_store.sessions) == 1


def test_duplicate_callback_parameters_and_expired_flow_rejected(auth_app):
    client = auth_app.test_client()
    state = begin(client)
    assert "error=" in client.get(f"/api/v1/customer/callback?state={state}&state={state}&code=test").location
    state = begin(client)
    auth_app.test_clock["now"] += 601
    assert "error=login_expired" in client.get("/api/v1/customer/callback", query_string={"state": state, "code": "code"}).location


def test_admin_requires_invitation_and_mfa(auth_app):
    client = auth_app.test_client()
    assert "error=admin_not_invited" in sign_in(client, "admin").location
    assert not auth_app.test_store.sessions
    invite(auth_app)
    auth_app.test_providers["admin"].fail = AuthError("mfa_required", "Complete enrollment", 403)
    assert "error=mfa_required" in sign_in(client, "admin").location
    assert not auth_app.test_store.sessions


def test_customer_cannot_access_admin_routes(auth_app):
    client = auth_app.test_client()
    sign_in(client)
    assert client.get("/api/v1/admin/session").status_code == 401
    assert client.get("/_test/export").status_code == 401
    assert client.get("/_test/account").status_code == 200


def test_staff_owner_and_immediate_demotion_disable(auth_app):
    invite(auth_app, "staff")
    client = auth_app.test_client()
    sign_in(client, "admin")
    assert client.get("/_test/booking").status_code == 200
    assert client.get("/_test/export").status_code == 403
    row = next(i for i in auth_app.test_store.identities.values() if i["area"] == "admin")
    row["admin_role"] = "owner"
    assert client.get("/_test/export").status_code == 200
    row["admin_role"] = "staff"
    assert client.get("/_test/export").status_code == 403
    row["admin_active"] = False
    assert client.get("/_test/booking").status_code == 403
    assert client.get("/api/v1/admin/session").status_code == 401


def test_mutations_require_csrf_and_origin(auth_app):
    invite(auth_app)
    client = auth_app.test_client()
    sign_in(client, "admin")
    csrf = client.get("/api/v1/admin/session").json["data"]["csrf_token"]
    assert client.post("/_test/booking", headers={"Origin": ORIGIN}).status_code == 403
    assert client.post("/_test/booking", headers={"Origin": "https://evil.example.invalid", "X-CSRF-Token": csrf}).status_code == 403
    assert client.post("/_test/booking", headers={"Origin": ORIGIN, "X-CSRF-Token": csrf}).status_code == 200


def test_polling_does_not_extend_idle_and_absolute_expiry(auth_app):
    invite(auth_app)
    client = auth_app.test_client()
    sign_in(client, "admin")
    auth_app.test_clock["now"] += 600
    assert client.get("/api/v1/admin/session").status_code == 200
    auth_app.test_clock["now"] += 301
    assert client.get("/api/v1/admin/session").status_code == 401
    auth_app.test_providers["admin"].auth_time = auth_app.test_clock["now"]
    sign_in(client, "admin")
    auth_app.test_clock["now"] += 28800
    assert client.get("/api/v1/admin/session").status_code == 401


def test_sensitive_operation_requires_recent_mfa(auth_app):
    invite(auth_app)
    client = auth_app.test_client()
    sign_in(client, "admin")
    auth_app.test_clock["now"] += 301
    result = client.get("/_test/export")
    assert result.status_code == 403
    assert result.json["error"]["code"] == "reauthentication_required"
    assert client.get("/_test/booking").status_code == 200


def test_concurrent_revocation_during_provider_request_cannot_authorize(auth_app, monkeypatch):
    invite(auth_app)
    client = auth_app.test_client()
    sign_in(client, "admin")
    def revoke(*args):
        for token_hash in auth_app.test_store.sessions:
            auth_app.test_store.revoke_session(token_hash, NOW)
    monkeypatch.setattr(auth_app.test_providers["admin"], "current_user", revoke)
    assert client.get("/_test/export").status_code == 401


@pytest.mark.parametrize("endpoint,elapsed,status", [("/_test/export", 301, 403), ("/_test/booking", 901, 401)])
def test_provider_delay_cannot_cross_expiry_or_mfa_freshness(auth_app, monkeypatch, endpoint, elapsed, status):
    invite(auth_app)
    client = auth_app.test_client()
    sign_in(client, "admin")
    monkeypatch.setattr(auth_app.test_providers["admin"], "current_user", lambda *args: auth_app.test_clock.update(now=NOW+elapsed))
    assert client.get(endpoint).status_code == status


def test_forwarded_address_is_not_trusted_by_default(auth_app):
    client = auth_app.test_client()
    for index in range(10):
        result = client.post("/api/v1/customer/login", json={}, headers={"Origin": ORIGIN, "X-Forwarded-For": f"198.51.100.{index}"})
        assert result.status_code == 200
    result = client.post("/api/v1/customer/login", json={}, headers={"Origin": ORIGIN, "X-Forwarded-For": "203.0.113.1"})
    assert result.status_code == 429


def test_refresh_rotates_encrypted_tokens_without_extending_authentication(auth_app):
    invite(auth_app)
    client = auth_app.test_client()
    sign_in(client, "admin")
    row = next(iter(auth_app.test_store.sessions.values()))
    original_expiry, original_auth_time = row["expires_at"], row["auth_time"]
    auth_app.test_clock["now"] += 280
    assert client.get("/api/v1/admin/session").status_code == 200
    assert auth_app.test_providers["admin"].refresh_count == 1
    assert row["auth_time"] == original_auth_time and row["expires_at"] == original_expiry
    assert "new-access-token" not in row["encrypted_tokens"]


def test_development_access_log_redacts_callback_credentials():
    import logging
    from app.auth.logging import CallbackRedaction
    record = logging.LogRecord("werkzeug", logging.INFO, "server", 1, '%s',
                               ('GET /api/v1/admin/callback?code=PRIVATE_CODE&state=PRIVATE_STATE HTTP/1.1',), None)
    assert CallbackRedaction().filter(record)
    assert "PRIVATE_CODE" not in record.getMessage() and "PRIVATE_STATE" not in record.getMessage()


def test_rotated_login_invalidates_old_browser_session(auth_app):
    client = auth_app.test_client()
    sign_in(client)
    old = client.get_cookie(cookie_name(auth_app.config, "customer")).value
    sign_in(client)
    other = auth_app.test_client()
    other.set_cookie(cookie_name(auth_app.config, "customer"), old)
    assert other.get("/api/v1/customer/session").status_code == 401
    assert client.get("/api/v1/customer/session").status_code == 200


def test_logout_revokes_locally_even_when_provider_unavailable(auth_app):
    client = auth_app.test_client()
    sign_in(client)
    token = client.get_cookie(cookie_name(auth_app.config, "customer")).value
    csrf = client.get("/api/v1/customer/session").json["data"]["csrf_token"]
    assert client.delete("/api/v1/customer/session", headers={"Origin": ORIGIN}).status_code == 403
    auth_app.test_providers["customer"].revoke_fail = True
    result = client.delete("/api/v1/customer/session", headers={"Origin": ORIGIN, "X-CSRF-Token": csrf})
    assert result.status_code == 200
    assert result.json["data"]["logout_url"].startswith("https://")
    assert client.get_cookie(cookie_name(auth_app.config, "customer")) is None
    assert auth_app.test_store.sessions[digest(token)]["revoked_at"]
    assert any(event == "logout_provider_pending" for event, _ in auth_app.test_store.events)


def test_logout_cancels_pending_login_and_clears_both_cookies(auth_app):
    client = auth_app.test_client()
    sign_in(client)
    csrf = client.get("/api/v1/customer/session").json["data"]["csrf_token"]
    state = begin(client)
    binding = client.get_cookie(cookie_name(auth_app.config, "customer", flow=True)).value
    result = client.delete("/api/v1/customer/session", headers={"Origin": ORIGIN, "X-CSRF-Token": csrf})
    assert result.status_code == 200
    assert client.get_cookie(cookie_name(auth_app.config, "customer", flow=True)) is None
    assert client.get_cookie(cookie_name(auth_app.config, "customer")) is None
    client.set_cookie(cookie_name(auth_app.config, "customer", flow=True), binding)
    result = client.get("/api/v1/customer/callback", query_string={"state": state, "code": "code"})
    assert "error=login_expired" in result.location
    assert all(row.get("revoked_at") for row in auth_app.test_store.sessions.values())


def test_logout_while_callback_waits_on_provider_cannot_recreate_session(auth_app, monkeypatch):
    from types import SimpleNamespace
    client = auth_app.test_client()
    sign_in(client)
    token = client.get_cookie(cookie_name(auth_app.config, "customer")).value
    state = begin(client)
    binding = client.get_cookie(cookie_name(auth_app.config, "customer", flow=True)).value
    service = auth_app.extensions["auth_service"]
    provider = auth_app.test_providers["customer"]
    original_exchange = provider.exchange
    request = SimpleNamespace(cookies={cookie_name(auth_app.config, "customer"): token,
                                      cookie_name(auth_app.config, "customer", flow=True): binding},
                              headers={"Origin": ORIGIN, "X-CSRF-Token": service.csrf("customer", token)})
    def exchange(*args):
        # The callback has consumed its one-use flow before this provider call.
        assert not auth_app.test_store.flows
        service.logout("customer", request)
        return original_exchange(*args)
    monkeypatch.setattr(provider, "exchange", exchange)
    with pytest.raises(AuthError) as failure:
        service.finish_login("customer", state, binding, "code", "127.0.0.1", token)
    assert failure.value.code == "login_expired"
    assert all(row.get("revoked_at") for row in auth_app.test_store.sessions.values())


def test_callback_provider_delay_cannot_outlive_flow_deadline(auth_app, monkeypatch):
    client = auth_app.test_client()
    state = begin(client)
    monkeypatch.setattr(auth_app.test_providers["customer"], "current_user", lambda *args: auth_app.test_clock.update(now=NOW+601))
    result = client.get("/api/v1/customer/callback", query_string={"state": state, "code": "code"})
    assert "error=login_expired" in result.location
    assert not auth_app.test_store.sessions


def test_overlapping_tabs_share_binding_and_logout_cancels_older_consumed_callback(auth_app, monkeypatch):
    client = auth_app.test_client()
    sign_in(client)
    csrf = client.get("/api/v1/customer/session").json["data"]["csrf_token"]
    state = begin(client)
    binding = client.get_cookie(cookie_name(auth_app.config, "customer", flow=True)).value
    token = client.get_cookie(cookie_name(auth_app.config, "customer")).value
    service = auth_app.extensions["auth_service"]
    provider = auth_app.test_providers["customer"]
    nonce = provider.nonce
    original_exchange = provider.exchange
    def exchange(*args):
        begin(client)
        assert client.get_cookie(cookie_name(auth_app.config, "customer", flow=True)).value == binding
        response = client.delete("/api/v1/customer/session", headers={"Origin": ORIGIN, "X-CSRF-Token": csrf})
        assert response.status_code == 200
        provider.nonce = nonce
        return original_exchange(*args)
    monkeypatch.setattr(provider, "exchange", exchange)
    with pytest.raises(AuthError) as failure:
        service.finish_login("customer", state, binding, "code", "127.0.0.1", token)
    assert failure.value.code == "login_expired"
    assert not auth_app.test_store.flows
    assert all(row.get("revoked_at") for row in auth_app.test_store.sessions.values())


def test_cancelled_binding_rejects_stale_login_then_allows_explicit_retry(auth_app):
    client = auth_app.test_client()
    sign_in(client)
    binding = client.get_cookie(cookie_name(auth_app.config, "customer", flow=True)).value
    csrf = client.get("/api/v1/customer/session").json["data"]["csrf_token"]
    assert client.delete("/api/v1/customer/session", headers={"Origin": ORIGIN, "X-CSRF-Token": csrf}).status_code == 200
    client.set_cookie(cookie_name(auth_app.config, "customer", flow=True), binding)
    response = client.post("/api/v1/customer/login", json={}, headers={"Origin": ORIGIN})
    assert response.status_code == 401
    assert response.json["error"]["code"] == "login_expired"
    assert client.get_cookie(cookie_name(auth_app.config, "customer", flow=True)) is None
    begin(client)
    assert client.get_cookie(cookie_name(auth_app.config, "customer", flow=True)).value != binding


def test_logout_cancels_session_generation_when_binding_cookie_is_absent(auth_app):
    client = auth_app.test_client()
    sign_in(client)
    original = next(iter(auth_app.test_store.sessions.values()))
    other = {**original, "token_hash": digest("x" * 43)}
    auth_app.test_store.create_session(other)
    client.delete_cookie(cookie_name(auth_app.config, "customer", flow=True))
    csrf = client.get("/api/v1/customer/session").json["data"]["csrf_token"]
    assert client.delete("/api/v1/customer/session", headers={"Origin": ORIGIN, "X-CSRF-Token": csrf}).status_code == 200
    assert all(row.get("revoked_at") for row in auth_app.test_store.sessions.values())


def test_provider_revocation_denies_next_request_and_outage_fails_closed(auth_app):
    client = auth_app.test_client()
    sign_in(client)
    provider = auth_app.test_providers["customer"]
    provider.fail = AuthError("authentication_unavailable", "Safe unavailable", 503)
    assert client.get("/api/v1/customer/session").status_code == 503
    provider.fail = None
    assert client.get("/api/v1/customer/session").status_code == 200
    provider.fail = AuthError("session_expired", "Safe expired")
    assert client.get("/api/v1/customer/session").status_code == 401
    provider.fail = None
    assert client.get("/api/v1/customer/session").status_code == 401


def test_shared_rate_limit_and_safe_store_failure(auth_app, monkeypatch):
    client = auth_app.test_client()
    for _ in range(10):
        begin(client)
    limited = client.post("/api/v1/customer/login", json={}, headers={"Origin": ORIGIN})
    assert limited.status_code == 429
    assert limited.headers["Retry-After"] == "60"

    def fail(*args, **kwargs):
        raise StoreUnavailable("PRIVATE SQL PASSWORD")
    monkeypatch.setattr(auth_app.test_store, "rate_limit", fail)
    failed = client.post("/api/v1/customer/login", json={}, headers={"Origin": ORIGIN})
    assert failed.status_code == 503
    assert "PRIVATE" not in failed.get_data(as_text=True)


def test_hosted_cookie_security(auth_app):
    auth_app.config["APP_ENV"] = "production"
    invite(auth_app)
    client = auth_app.test_client()
    result = sign_in(client, "admin")
    cookie = result.headers.getlist("Set-Cookie")[0]
    assert cookie.startswith("__Host-popssibilities_admin=")
    assert "Secure" in cookie and "HttpOnly" in cookie and "Path=/" in cookie
    assert "Domain=" not in cookie
    assert result.headers["Strict-Transport-Security"]


@pytest.mark.parametrize("setting,value", [
    ("SECRET_KEY", "short"), ("AUTH_TOKEN_ENCRYPTION_KEY", "invalid"),
    ("COGNITO_ADMIN_ISSUER", "https://evil.example.invalid"),
    ("COGNITO_ADMIN_DOMAIN", "http://admin.example.invalid"),
    ("AUTH_ORIGIN", "http://public.example.invalid"), ("COGNITO_ADMIN_CLIENT_SECRET", ""),
])
def test_unsafe_configuration_rejected(auth_app, setting, value):
    from app.auth.settings import validate_settings
    settings = dict(auth_app.config)
    settings[setting] = value
    with pytest.raises(ValueError):
        validate_settings(settings)
