"""Browser-bound Google approval, enrollment and application MFA boundaries."""

from copy import deepcopy

import pyotp
import pytest

from app.auth.errors import AuthError
from app.auth.service import digest
from app.auth.settings import cookie_name, mfa_cookie_name
from app.auth.store import AccessDeniedError, LoginCancelledError
from test_auth import MemoryStore, auth_app, begin, invite, NOW, ORIGIN, sign_in


class GoogleMemoryStore(MemoryStore):
    """HTTP fixture; transactional concurrency is tested against the real Store."""
    def __init__(self):
        super().__init__()
        self.pending, self.links, self.factors = {}, {}, {}

    def decorate(self, row):
        row = deepcopy(row)
        source = row.get("identity_id", row.get("id"))
        canonical = self.links.get(source)
        if canonical:
            identity = next(i for i in self.identities.values() if i["id"] == canonical)
            row.update(canonical_identity_id=canonical, is_google_alias=True,
                       admin_role=identity["admin_role"], admin_active=identity["admin_active"],
                       google_subject="google-stable-subject", provider_username="Google_google-stable-subject")
            factor = self.factors[canonical]
            row.update(mfa_version=factor["version"], mfa_enrolled=bool(factor["encrypted_secret"]),
                       enrollment_challenge_hash=factor["enrollment_challenge_hash"],
                       enrollment_expires_at=factor["enrollment_expires_at"])
        return row

    def find_identity(self, issuer, subject):
        row = super().find_identity(issuer, subject)
        return self.decorate(row) if row else None

    def upsert_identity(self, *args):
        return self.decorate(super().upsert_identity(*args))

    def get_session(self, *args):
        row = super().get_session(*args)
        return self.decorate(row) if row else None

    def cancel_login(self, binding_hash, area, now):
        super().cancel_login(binding_hash, area, now)
        if area == "admin":
            self.pending = {key: row for key, row in self.pending.items() if row["binding_hash"] != binding_hash}

    def put_google_challenge(self, row):
        if self.cancelled_flows.get((row["binding_hash"], "admin"), 0) > row["created_at"]:
            raise LoginCancelledError("Cancelled")
        canonical = self.links.get(row["identity_id"])
        if canonical and not next(i for i in self.identities.values() if i["id"] == canonical)["admin_active"]:
            raise AccessDeniedError("Disabled")
        self.pending[row["challenge_hash"]] = {**deepcopy(row), "attempts": 0}

    def get_google_challenge(self, key, binding, now):
        row = self.pending.get(key)
        if not row or row["binding_hash"] != binding or now >= row["expires_at"] or row["attempts"] >= 5:
            return None
        identity = next(i for i in self.identities.values() if i["id"] == row["identity_id"])
        return self.decorate({**identity, **row})

    def set_google_challenge_payload(self, key, binding, old, new, now):
        row = self.get_google_challenge(key, binding, now)
        if not row or row["encrypted_payload"] != old:
            return False
        self.pending[key]["encrypted_payload"] = new
        return True

    def get_google_factor(self, canonical):
        return deepcopy(self.factors[canonical])

    def fail_google_challenge(self, key, binding, now):
        if not self.get_google_challenge(key, binding, now):
            return False
        self.pending[key]["attempts"] += 1
        if self.pending[key]["attempts"] == 5:
            del self.pending[key]
        return True

    def complete_google_mfa(self, key, binding, now, counter, version, payload, session=None, encrypted_secret=None):
        row = self.get_google_challenge(key, binding, now)
        if not row or not row.get("admin_active") or row["encrypted_payload"] != payload:
            return False
        factor = self.factors[row["canonical_identity_id"]]
        if version != factor["version"] or counter <= factor["last_counter"]:
            return False
        if session:
            self.create_session(session)
        else:
            if (factor["enrollment_challenge_hash"] != key or now >= factor["enrollment_expires_at"]
                    or factor["encrypted_secret"]):
                return False
            factor.update(encrypted_secret=encrypted_secret, enrollment_challenge_hash=None, enrollment_expires_at=None)
        factor["last_counter"] = counter
        del self.pending[key]
        return True

    def approve(self, key, canonical, recovery=False):
        row = self.pending[key]
        self.links[row["identity_id"]] = canonical
        version = self.factors.get(canonical, {}).get("version", 0) + 1
        self.factors[canonical] = {"canonical_identity_id": canonical, "encrypted_secret": None, "version": version,
                                  "last_counter": -1, "enrollment_challenge_hash": key,
                                  "enrollment_expires_at": row["expires_at"]}
        if recovery:
            for token, session in self.sessions.items():
                if session["identity_id"] in {canonical, row["identity_id"]}:
                    self.revoke_session(token, NOW)


@pytest.fixture
def google_app(auth_app, monkeypatch):
    store = GoogleMemoryStore()
    auth_app.test_store = store
    manager = auth_app.extensions["auth_service"]
    manager.store = store
    provider = auth_app.test_providers["admin"]
    original_validate = provider.validate
    def validate(*args, provider="password", **kwargs):
        claims = original_validate(*args, provider=provider, **kwargs)
        if provider == "google":
            claims.update(subject="google-cognito-subject", google_subject="google-stable-subject",
                          provider_username="Google_google-stable-subject", assurance={})
        return claims
    monkeypatch.setattr(provider, "validate", validate)
    monkeypatch.setattr(provider, "current_user", lambda *args, **kwargs: (_ for _ in ()).throw(provider.fail) if provider.fail else None)
    invite(auth_app)
    return auth_app


def google_first(client):
    state = begin(client, "admin", "google")
    result = client.get("/api/v1/admin/callback", query_string={"state": state, "code": "test-google-code"})
    assert result.location == ORIGIN + "/admin/mfa", result.location
    pending = client.get("/api/v1/admin/mfa")
    assert pending.status_code == 200, pending.json
    return pending.json["data"]


def headers(pending):
    return {"Origin": ORIGIN, "X-CSRF-Token": pending["csrf_token"]}


def approve(app, client, recovery=False):
    key = digest(client.get_cookie(mfa_cookie_name(app.config)).value)
    canonical = app.test_store.identities[(app.test_providers["admin"].issuer, "admin-subject")]["id"]
    app.test_store.approve(key, canonical, recovery=recovery)
    return client.get("/api/v1/admin/mfa").json["data"]


def enroll(app, client):
    google_first(client)
    pending = approve(app, client)
    assert pending["status"] == "enrollment_required"
    result = client.post("/api/v1/admin/mfa/enroll", json={}, headers=headers(pending))
    assert result.status_code == 200, result.json
    secret = result.json["data"]["secret"]
    result = client.post("/api/v1/admin/mfa/verify", json={"code": pyotp.TOTP(secret).at(app.test_clock["now"])}, headers=headers(pending))
    assert result.json["data"]["status"] == "enrolled"
    assert client.get_cookie(cookie_name(app.config, "admin")) is None
    app.test_clock["now"] += 30
    return secret


def google_session(app, client, secret):
    pending = google_first(client)
    assert pending["status"] == "challenge_required"
    return client.post("/api/v1/admin/mfa/verify", json={"code": pyotp.TOTP(secret).at(app.test_clock["now"])}, headers=headers(pending))


def test_matching_verified_email_never_links_or_grants_access(google_app):
    client = google_app.test_client()
    pending = google_first(client)
    assert pending["status"] == "approval_required" and pending["approval_code"]
    assert client.get("/api/v1/admin/session").status_code == 401
    assert client.get("/_test/booking").status_code == 401
    assert not google_app.test_store.links and not google_app.test_store.sessions
    assert client.post("/api/v1/admin/mfa/enroll", json={}, headers=headers(pending)).status_code == 403
    assert client.post("/api/v1/admin/mfa/verify", json={"code": "123456"}, headers=headers(pending)).status_code == 403
    assert "private-" not in str(pending)


def test_secure_enrollment_has_no_session_and_requires_unused_code_on_new_login(google_app):
    client = google_app.test_client()
    secret = enroll(google_app, client)
    assert client.get("/api/v1/admin/session").status_code == 401
    pending = google_first(client)
    previous = pyotp.TOTP(secret).at(google_app.test_clock["now"] - 30)
    assert client.post("/api/v1/admin/mfa/verify", json={"code": previous}, headers=headers(pending)).status_code == 422
    code = pyotp.TOTP(secret).at(google_app.test_clock["now"])
    result = client.post("/api/v1/admin/mfa/verify", json={"code": code}, headers=headers(pending))
    assert result.json["data"] == {"status": "authenticated"}
    assert client.get("/_test/export").status_code == 200
    assert client.post("/api/v1/admin/mfa/verify", json={"code": code}, headers=headers(pending)).status_code == 401
    assert secret not in str(google_app.test_store.factors)
    assert "private-" not in str(google_app.test_store.pending)


def test_both_methods_share_canonical_role_and_disable_is_immediate(google_app):
    google_client, password_client = google_app.test_client(), google_app.test_client()
    secret = enroll(google_app, google_client)
    assert google_session(google_app, google_client, secret).status_code == 200
    sign_in(password_client, "admin")
    google_identity = google_client.get("/api/v1/admin/session").json["data"]["administrator"]
    native_identity = password_client.get("/api/v1/admin/session").json["data"]["administrator"]
    assert google_identity["id"] == native_identity["id"] and google_identity["role"] == native_identity["role"] == "owner"
    canonical = google_app.test_store.identities[(google_app.test_providers["admin"].issuer, "admin-subject")]
    canonical["admin_role"] = "staff"
    for client in (google_client, password_client):
        assert client.get("/_test/export").status_code == 403
        assert client.get("/_test/booking").status_code == 200
    canonical["admin_active"] = False
    for client in (google_client, password_client):
        assert client.get("/_test/booking").status_code == 403
        assert client.get("/api/v1/admin/session").status_code == 401


def test_google_refresh_preserves_mfa_time_and_absolute_expiry(google_app):
    client = google_app.test_client()
    secret = enroll(google_app, client)
    assert google_session(google_app, client, secret).status_code == 200
    row = next(iter(google_app.test_store.sessions.values()))
    auth_time, expires = row["auth_time"], row["expires_at"]
    google_app.test_clock["now"] += 280
    assert client.get("/api/v1/admin/session").status_code == 200
    assert google_app.test_providers["admin"].refresh_count == 1
    assert row["auth_time"] == auth_time and row["expires_at"] == expires
    google_app.test_clock["now"] += 21
    assert client.get("/_test/export").json["error"]["code"] == "reauthentication_required"
    assert client.get("/_test/booking").status_code == 200


def test_google_refresh_rejects_changed_stable_provider_identity(google_app, monkeypatch):
    client = google_app.test_client()
    secret = enroll(google_app, client)
    assert google_session(google_app, client, secret).status_code == 200
    provider = google_app.test_providers["admin"]
    original = provider.validate
    def changed(*args, **kwargs):
        return {**original(*args, **kwargs), "google_subject": "different-provider-identity"}
    monkeypatch.setattr(provider, "validate", changed)
    google_app.test_clock["now"] += 280
    assert client.get("/api/v1/admin/session").status_code == 401
    assert all(row.get("revoked_at") for row in google_app.test_store.sessions.values())


def test_lost_authenticator_can_supply_fresh_private_recovery_receipt(google_app):
    client = google_app.test_client()
    enroll(google_app, client)
    pending = google_first(client)
    assert pending["status"] == "challenge_required" and pending["approval_code"]
    key = digest(client.get_cookie(mfa_cookie_name(google_app.config)).value)
    assert digest(pending["approval_code"]) == google_app.test_store.pending[key]["proof_hash"]
    assert client.get("/api/v1/admin/session").status_code == 401
    assert client.post("/api/v1/admin/mfa/enroll", json={}, headers=headers(pending)).status_code == 403


def test_concurrent_factor_recovery_before_secret_read_fails_closed(google_app, monkeypatch):
    client = google_app.test_client()
    secret = enroll(google_app, client)
    pending = google_first(client)
    original = google_app.test_store.get_google_factor
    def replaced(canonical):
        factor = original(canonical)
        return {**factor, "version": factor["version"] + 1, "encrypted_secret": None}
    monkeypatch.setattr(google_app.test_store, "get_google_factor", replaced)
    result = client.post("/api/v1/admin/mfa/verify", json={"code": pyotp.TOTP(secret).at(google_app.test_clock["now"])}, headers=headers(pending))
    assert result.status_code == 401 and result.json["error"]["code"] == "mfa_challenge_expired"
    assert not google_app.test_store.sessions


@pytest.mark.parametrize("code", ["000000", None, 123456, "１２３４５６", "12345", [], {}])
def test_bad_codes_cannot_create_admin_session(google_app, code):
    client = google_app.test_client()
    secret = enroll(google_app, client)
    pending = google_first(client)
    assert code != pyotp.TOTP(secret).at(google_app.test_clock["now"])
    assert client.post("/api/v1/admin/mfa/verify", json={"code": code}, headers=headers(pending)).status_code == 422
    assert client.get("/_test/booking").status_code == 401


def test_mfa_csrf_binding_expiration_and_provider_revocation(google_app):
    client = google_app.test_client()
    google_first(client)
    pending = approve(google_app, client)
    assert client.post("/api/v1/admin/mfa/enroll", json={}, headers={"Origin": ORIGIN}).status_code == 403
    assert client.post("/api/v1/admin/mfa/enroll", json={}, headers={**headers(pending), "Origin": "https://evil.invalid"}).status_code == 403
    foreign = google_app.test_client()
    foreign.set_cookie(mfa_cookie_name(google_app.config), client.get_cookie(mfa_cookie_name(google_app.config)).value)
    assert foreign.get("/api/v1/admin/mfa").status_code == 401
    google_app.test_providers["admin"].fail = AuthError("session_expired", "Expired")
    assert client.post("/api/v1/admin/mfa/enroll", json={}, headers=headers(pending)).status_code == 401
    google_app.test_providers["admin"].fail = None
    google_app.test_clock["now"] += 300
    assert client.get("/api/v1/admin/mfa").status_code == 401
    assert not google_app.test_store.sessions


def test_attempt_limit_and_principal_limit_survive_new_challenges(google_app):
    client = google_app.test_client()
    secret = enroll(google_app, client)
    google_app.test_clock["now"] += 60
    pending = google_first(client)
    for _ in range(5):
        assert client.post("/api/v1/admin/mfa/verify", json={"code": "000000"}, headers=headers(pending)).status_code == 422
    assert client.get("/api/v1/admin/mfa").status_code == 401
    pending = google_first(client)
    assert client.post("/api/v1/admin/mfa/verify", json={"code": pyotp.TOTP(secret).at(google_app.test_clock["now"])}, headers=headers(pending)).status_code == 429
    assert not google_app.test_store.sessions


def test_logout_cancels_pending_mfa_without_affecting_customer(google_app):
    client = google_app.test_client()
    sign_in(client, "customer")
    pending = google_first(client)
    google_app.test_providers["admin"].revoke_fail = True
    result = client.delete("/api/v1/admin/mfa", headers=headers(pending))
    assert result.status_code == 200
    assert not google_app.test_store.pending
    assert client.get_cookie(mfa_cookie_name(google_app.config)) is None
    assert client.get("/api/v1/customer/session").status_code == 200
    assert any(event == "admin.google_provider_revocation_pending" for event, _ in google_app.test_store.events)


def test_completed_google_logout_and_controlled_recovery_revoke_both_methods(google_app):
    google_client, password_client = google_app.test_client(), google_app.test_client()
    secret = enroll(google_app, google_client)
    assert google_session(google_app, google_client, secret).status_code == 200
    sign_in(password_client, "admin")
    data = google_client.get("/api/v1/admin/session").json["data"]
    assert google_client.delete("/api/v1/admin/session", headers=headers(data)).status_code == 200
    assert google_client.get("/api/v1/admin/session").status_code == 401
    recovery_client = google_app.test_client()
    google_first(recovery_client)
    pending = approve(google_app, recovery_client, recovery=True)
    assert pending["status"] == "enrollment_required"
    assert password_client.get("/api/v1/admin/session").status_code == 401
    assert not any(not row.get("revoked_at") for row in google_app.test_store.sessions.values())


def test_provider_delay_and_concurrent_disable_cannot_complete_mfa(google_app, monkeypatch):
    client = google_app.test_client()
    secret = enroll(google_app, client)
    pending = google_first(client)
    code = pyotp.TOTP(secret).at(google_app.test_clock["now"])
    canonical = google_app.test_store.identities[(google_app.test_providers["admin"].issuer, "admin-subject")]
    monkeypatch.setattr(google_app.test_providers["admin"], "current_user", lambda *args, **kwargs: canonical.update(admin_active=False))
    assert client.post("/api/v1/admin/mfa/verify", json={"code": code}, headers=headers(pending)).status_code == 401
    assert not google_app.test_store.sessions


@pytest.mark.parametrize("elapsed,status", [(90, 422), (300, 401)])
def test_delayed_provider_check_cannot_accept_stale_code_or_expired_pending(google_app, monkeypatch, elapsed, status):
    client = google_app.test_client()
    secret = enroll(google_app, client)
    pending = google_first(client)
    now = google_app.test_clock["now"]
    code = pyotp.TOTP(secret).at(now)
    monkeypatch.setattr(google_app.test_providers["admin"], "current_user",
                        lambda *args, **kwargs: google_app.test_clock.update(now=now + elapsed))
    assert client.post("/api/v1/admin/mfa/verify", json={"code": code}, headers=headers(pending)).status_code == status
    assert not google_app.test_store.sessions


def test_logout_while_google_callback_waits_cannot_create_pending_challenge(google_app, monkeypatch):
    from types import SimpleNamespace
    client = google_app.test_client()
    sign_in(client, "admin")
    token = client.get_cookie(cookie_name(google_app.config, "admin")).value
    state = begin(client, "admin", "google")
    binding = client.get_cookie(cookie_name(google_app.config, "admin", flow=True)).value
    manager = google_app.extensions["auth_service"]
    request = SimpleNamespace(cookies={cookie_name(google_app.config, "admin"): token,
                                       cookie_name(google_app.config, "admin", flow=True): binding},
                              headers={"Origin": ORIGIN, "X-CSRF-Token": manager.csrf("admin", token)})
    provider = google_app.test_providers["admin"]
    original = provider.exchange
    def delayed(*args):
        manager.logout("admin", request)
        return original(*args)
    monkeypatch.setattr(provider, "exchange", delayed)
    result = client.get("/api/v1/admin/callback", query_string={"state": state, "code": "google-code"})
    assert "error=login_expired" in result.location
    assert not google_app.test_store.pending
    assert all(row.get("revoked_at") for row in google_app.test_store.sessions.values())


def test_old_password_session_cannot_bypass_google_pending_mfa(google_app):
    client = google_app.test_client()
    sign_in(client, "admin")
    old = client.get_cookie(cookie_name(google_app.config, "admin")).value
    google_first(client)
    assert client.get("/_test/booking").status_code == 401
    other = google_app.test_client()
    other.set_cookie(cookie_name(google_app.config, "admin"), old)
    assert other.get("/_test/booking").status_code == 401
