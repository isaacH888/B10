"""Native challenge/session boundaries with controlled Cognito, not live users."""

import json
from copy import deepcopy

import pytest
from app.auth.errors import AuthError
from app.auth.service import digest
from app.auth.settings import cookie_name, native_cookie_name
from app.auth.store import AccessDeniedError, LoginCancelledError, StoreUnavailable
from test_auth import NOW, ORIGIN, FakeProvider, MemoryStore, invite
from test_auth import auth_app as auth_app
from test_auth_store import db_settings as db_settings
from test_auth_store import store as store

mysql_store = store

URL = "/api/v1/admin/password/transaction"
SECRET = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"


class NativeStore(MemoryStore):
    def find_identity_by_email(self, email, area="admin"):
        return [
            deepcopy(i)
            for i in self.identities.values()
            if i["email"] == email and i["area"] == area
        ]

    def put_admin_native_flow(self, row):
        if self.cancelled_flows.get((row["binding_hash"], "admin"), 0) > row["created_at"]:
            raise LoginCancelledError()
        self.native[row["token_hash"]] = deepcopy(row)

    def get_admin_native_flow(self, token, binding, now):
        row = self.native.get(token)
        if (
            not row
            or row["binding_hash"] != binding
            or row["expires_at"] <= now
            or row["attempts"] >= 5
        ):
            return None
        return deepcopy(row)

    def consume_admin_native_flow(self, token, binding, now):
        row = self.get_admin_native_flow(token, binding, now)
        if row:
            del self.native[token]
            row["attempts"] += 1
        return row

    def cancel_login(self, binding, area, now):
        super().cancel_login(binding, area, now)
        if area == "admin":
            self.native = {k: v for k, v in self.native.items() if v["binding_hash"] != binding}

    def create_session(self, session):
        if session["assurance"].get("method") == "cognito_native_challenge":
            identity = next(
                i for i in self.identities.values() if i["id"] == session["identity_id"]
            )
            if (
                not identity.get("admin_active")
                or identity.get("is_google_alias")
                or identity.get("native_login_version", 0) != session["assurance"]["access_version"]
            ):
                raise AccessDeniedError()
        super().create_session(session)


class NativeProvider(FakeProvider):
    next_challenge = "SOFTWARE_TOKEN_MFA"
    password_calls = 0
    totp_calls = 0
    enrollment_calls = 0
    native_refresh_calls = 0
    native_revoke_calls = 0

    def native_password(self, username, password):
        self.password_calls += 1
        assert username == "admin-subject"
        assert password == "synthetic-password"
        if self.fail:
            raise self.fail
        return {
            "challenge": self.next_challenge,
            "username": username,
            "session": "private-cognito-session",
            "required_attributes": [],
        }

    def native_new_password(self, session, username, password, attributes):
        assert password == "synthetic-new-password"
        assert attributes == {}
        return {
            "challenge": "MFA_SETUP",
            "username": username,
            "session": "private-new-password-session",
        }

    def native_associate(self, session):
        return SECRET, "private-enrollment-session"

    def native_enroll(self, session, username, code):
        self.enrollment_calls += 1
        assert code == "123456"
        self.next_challenge = "SOFTWARE_TOKEN_MFA"

    def native_totp(self, session, username, code):
        self.totp_calls += 1
        assert code == "123456"
        if self.fail:
            raise self.fail
        return self.exchange("unused", "unused")

    def validate_native(self, tokens, now, *, started_at=None):
        result = self.validate(tokens, now)
        result.pop("assurance")
        return result

    def native_refresh(self, token):
        self.native_refresh_calls += 1
        return self.refresh(token)

    def native_revoke(self, token):
        self.native_revoke_calls += 1
        return self.revoke(token)


@pytest.fixture
def native_app(auth_app):
    store = auth_app.test_store
    store.__class__ = NativeStore
    store.native = {}
    provider = auth_app.test_providers["admin"]
    provider.__class__ = NativeProvider
    invite(auth_app)
    return auth_app


def bootstrap(client):
    response = client.get(URL)
    assert response.status_code == 200, response.json
    return response.json["data"]


def post(client, transaction, **payload):
    return client.post(
        URL, json=payload, headers={"Origin": ORIGIN, "X-CSRF-Token": transaction["csrf_token"]}
    )


def password(client):
    transaction = bootstrap(client)
    result = post(
        client, transaction, email="synthetic@example.invalid", password="synthetic-password"
    )
    assert result.status_code == 200, result.json
    return result.json["data"]


def login(client):
    transaction = password(client)
    result = post(client, transaction, code="123456")
    assert result.status_code == 200, result.json
    assert result.json["data"]["step"] == "complete"
    return result


def test_only_completed_bound_totp_challenge_can_create_admin_session(native_app):
    client = native_app.test_client()
    pending = password(client)
    assert pending["step"] == "totp"
    assert not native_app.test_store.sessions
    assert client.get("/api/v1/admin/session").status_code == 401
    result = post(client, pending, code="123456")
    assert result.status_code == 200
    assert native_app.test_providers["admin"].totp_calls == 1
    read = client.get("/api/v1/admin/session")
    assert read.status_code == 200
    assert read.json["data"]["administrator"]["role"] == "owner"
    session = next(iter(native_app.test_store.sessions.values()))
    assert session["assurance"] == {
        "method": "cognito_native_challenge",
        "provider": "password",
        "challenge": "SOFTWARE_TOKEN_MFA",
        "completed_at": NOW,
        "access_version": 0,
    }
    assert "acr" not in session["assurance"]
    for secret in (
        "synthetic-password",
        "123456",
        "private-cognito-session",
        "private-access-token",
        SECRET,
    ):
        assert secret not in json.dumps(session)
        assert secret not in json.dumps(native_app.test_store.native)
        assert secret not in json.dumps(native_app.test_store.events)
        assert secret not in result.get_data(as_text=True)


def test_temporary_password_and_enrollment_never_grant_a_session(native_app):
    provider = native_app.test_providers["admin"]
    provider.next_challenge = "NEW_PASSWORD_REQUIRED"
    client = native_app.test_client()
    setup = password(client)
    assert setup["step"] == "new_password"
    enrollment = post(client, setup, new_password="synthetic-new-password").json["data"]
    assert enrollment["step"] == "totp_enrollment"
    assert enrollment["enrollment_secret"] == SECRET
    ciphertext = next(iter(native_app.test_store.native.values()))["encrypted_payload"]
    assert SECRET not in ciphertext and "synthetic-new-password" not in ciphertext
    result = post(client, enrollment, code="123456")
    assert result.json["data"]["step"] == "password"
    assert result.json["data"]["enrollment_complete"] is True
    assert not native_app.test_store.sessions
    assert client.get("/api/v1/admin/session").status_code == 401
    pending = post(
        client,
        result.json["data"],
        email="synthetic@example.invalid",
        password="synthetic-password",
    )
    assert pending.json["data"]["step"] == "totp"
    assert post(client, pending.json["data"], code="123456").json["data"]["step"] == "complete"
    assert provider.enrollment_calls == 1 and provider.totp_calls == 1


@pytest.mark.parametrize("step", ["password", "totp"])
@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Origin": "https://evil.example.invalid", "X-CSRF-Token": "wrong"},
        {"Origin": ORIGIN, "X-CSRF-Token": "wrong"},
    ],
)
def test_all_submissions_require_exact_origin_and_bound_csrf(native_app, step, headers):
    client = native_app.test_client()
    if step == "password":
        bootstrap(client)
    else:
        password(client)
    body = (
        {"email": "synthetic@example.invalid", "password": "synthetic-password"}
        if step == "password"
        else {"code": "123456"}
    )
    result = client.post(URL, json=body, headers=headers)
    assert result.status_code == 403
    assert not native_app.test_store.sessions
    assert native_app.test_providers["admin"].totp_calls == 0


@pytest.mark.parametrize(
    "change",
    [
        {"admin_active": False},
        {"is_google_alias": True},
        {"admin_role": "customer"},
        {"issuer": "https://different.example.invalid"},
    ],
)
def test_unapproved_or_foreign_identity_is_not_authenticated_or_enrolled(native_app, change):
    person = next(iter(native_app.test_store.identities.values()))
    person.update(change)
    client = native_app.test_client()
    data = bootstrap(client)
    result = post(client, data, email="synthetic@example.invalid", password="synthetic-password")
    assert result.status_code == 401
    assert native_app.test_providers["admin"].password_calls == 0
    assert not native_app.test_store.sessions


def test_same_email_never_links_privileged_identities(native_app):
    store = native_app.test_store
    provider = native_app.test_providers["admin"]
    store.upsert_identity(
        provider.issuer, "Google_other", "admin", "synthetic@example.invalid", "Google User", NOW
    )
    store.identities[(provider.issuer, "Google_other")].update(
        admin_active=True, admin_role="owner", is_google_alias=True
    )
    client = native_app.test_client()
    login(client)
    assert (
        next(iter(store.sessions.values()))["identity_id"]
        == store.identities[(provider.issuer, "admin-subject")]["id"]
    )
    assert len(store.identities) == 2


@pytest.mark.parametrize(
    "change", [{"admin_active": False}, {"native_login_version": 1}, {"is_google_alias": True}]
)
def test_access_changes_invalidate_pending_mfa_before_provider_io(native_app, change):
    client = native_app.test_client()
    data = password(client)
    next(iter(native_app.test_store.identities.values())).update(change)
    assert post(client, data, code="123456").status_code == 403
    assert native_app.test_providers["admin"].totp_calls == 0
    assert not native_app.test_store.sessions


def test_operator_revocation_during_final_provider_call_cannot_create_session(
    native_app, monkeypatch
):
    client = native_app.test_client()
    data = password(client)
    provider = native_app.test_providers["admin"]
    original = provider.native_totp

    def revoke(*args):
        result = original(*args)
        next(iter(native_app.test_store.identities.values()))["native_login_version"] = 1
        return result

    monkeypatch.setattr(provider, "native_totp", revoke)
    assert post(client, data, code="123456").status_code == 403
    assert not native_app.test_store.sessions


def test_replay_or_foreign_browser_never_reuses_cognito_session(native_app):
    client = native_app.test_client()
    data = password(client)
    old_cookie = client.get_cookie(native_cookie_name(native_app.config)).value
    binding = client.get_cookie(cookie_name(native_app.config, "admin", flow=True)).value
    alien = native_app.test_client()
    alien.set_cookie(native_cookie_name(native_app.config), old_cookie)
    alien.set_cookie(cookie_name(native_app.config, "admin", flow=True), "x" * 43)
    assert post(alien, data, code="123456").status_code == 401
    assert post(client, data, code="123456").status_code == 200
    replay = native_app.test_client()
    replay.set_cookie(native_cookie_name(native_app.config), old_cookie)
    replay.set_cookie(cookie_name(native_app.config, "admin", flow=True), binding)
    assert post(replay, data, code="123456").status_code == 401
    assert native_app.test_providers["admin"].totp_calls == 1


@pytest.mark.parametrize(
    "failure",
    [
        AuthError("authentication_failed", "Safe failure"),
        AuthError("authentication_unavailable", "Safe failure", 503),
    ],
)
def test_bad_code_or_provider_outage_consumes_transaction_and_grants_nothing(native_app, failure):
    client = native_app.test_client()
    data = password(client)
    native_app.test_providers["admin"].fail = failure
    assert post(client, data, code="123456").status_code == failure.status
    assert not native_app.test_store.sessions and not native_app.test_store.native
    assert client.get_cookie(native_cookie_name(native_app.config)) is None


def test_expiration_before_or_during_totp_denies_session(native_app, monkeypatch):
    client = native_app.test_client()
    data = password(client)
    provider = native_app.test_providers["admin"]
    original = provider.native_totp

    def slow(*args):
        native_app.test_clock["now"] = NOW + 300
        return original(*args)

    monkeypatch.setattr(provider, "native_totp", slow)
    assert post(client, data, code="123456").status_code == 401
    assert not native_app.test_store.sessions


def test_cancel_requires_csrf_and_cancels_inflight_browser_generation(native_app):
    client = native_app.test_client()
    data = password(client)
    result = client.delete(URL, headers={"Origin": ORIGIN, "X-CSRF-Token": data["csrf_token"]})
    assert result.status_code == 200
    assert not native_app.test_store.native
    assert client.get_cookie(native_cookie_name(native_app.config)) is None
    assert post(client, data, code="123456").status_code == 401


def test_native_refresh_preserves_proof_freshness_and_logout_revokes(native_app):
    client = native_app.test_client()
    login(client)
    session = client.get("/api/v1/admin/session").json["data"]
    original = deepcopy(next(iter(native_app.test_store.sessions.values()))["assurance"])
    native_app.test_clock["now"] = NOW + 301
    assert client.get("/api/v1/admin/session").status_code == 200
    assert native_app.test_providers["admin"].native_refresh_calls == 1
    assert next(iter(native_app.test_store.sessions.values()))["assurance"] == original
    assert client.get("/_test/export").json["error"]["code"] == "reauthentication_required"
    result = client.delete(
        "/api/v1/admin/session", headers={"Origin": ORIGIN, "X-CSRF-Token": session["csrf_token"]}
    )
    assert result.status_code == 200
    assert native_app.test_providers["admin"].native_revoke_calls == 1
    assert client.get("/api/v1/admin/session").status_code == 401


@pytest.mark.parametrize("role", ["owner", "staff"])
def test_native_roles_and_sensitive_permissions_remain_enforced(native_app, role):
    next(iter(native_app.test_store.identities.values()))["admin_role"] = role
    client = native_app.test_client()
    login(client)
    assert client.get("/_test/export").status_code == (200 if role == "owner" else 403)
    assert client.get("/_test/booking").status_code == 200


def test_native_ip_and_account_limits_are_durable_and_deny_without_tokens(native_app):
    client = native_app.test_client()
    for attempt in range(10):
        data = bootstrap(client)
        assert (
            post(
                client, data, email="unknown@example.invalid", password="synthetic-password"
            ).status_code
            == 401
        )
    result = client.get(URL)
    assert result.status_code == 429
    assert result.headers["Retry-After"] == "60"
    assert not native_app.test_store.sessions


@pytest.mark.parametrize(
    "body",
    [
        {"code": "12345"},
        {"code": "abcdef"},
        {"code": "123456", "subject": "admin-subject"},
        {"code": 123456},
        [],
        None,
    ],
)
def test_challenge_payloads_cannot_override_identity_or_proof(native_app, body):
    client = native_app.test_client()
    data = password(client)
    result = client.post(
        URL, json=body, headers={"Origin": ORIGIN, "X-CSRF-Token": data["csrf_token"]}
    )
    assert result.status_code == 422
    assert not native_app.test_store.sessions
    assert native_app.test_providers["admin"].totp_calls == 0


def test_native_denial_diagnostics_do_not_log_provider_secrets(native_app, caplog):
    client = native_app.test_client()
    data = password(client)
    native_app.test_providers["admin"].fail = AuthError("authentication_failed", "Safe failure")
    result = post(client, data, code="123456")
    denied = [e for e in native_app.test_store.events if e[0] == "admin_native_login_denied"][-1]
    assert denied[1]["detail"] == {"area": "admin", "error_code": "authentication_failed"}
    for secret in ("123456", "synthetic-password", "private-cognito-session", SECRET):
        assert (
            secret not in json.dumps(denied)
            and secret not in caplog.text
            and secret not in result.get_data(as_text=True)
        )


@pytest.mark.parametrize(
    "mutation",
    [
        {"method": "app_totp"},
        {"provider": "google"},
        {"challenge": "EMAIL_MFA"},
        {"completed_at": True},
        {"completed_at": NOW + 1},
        {"access_version": True},
    ],
)
def test_corrupt_or_foreign_native_session_proof_is_denied_before_provider_io(native_app, mutation):
    client = native_app.test_client()
    login(client)
    next(iter(native_app.test_store.sessions.values()))["assurance"].update(mutation)
    assert client.get("/api/v1/admin/session").status_code == 403


def test_refresh_cannot_change_native_identity_or_original_authentication_time(
    native_app, monkeypatch
):
    client = native_app.test_client()
    login(client)
    native_app.test_clock["now"] = NOW + 301
    provider = native_app.test_providers["admin"]
    provider.auth_time = NOW + 301
    result = client.get("/api/v1/admin/session")
    assert result.status_code == 401
    assert next(iter(native_app.test_store.sessions.values())).get("revoked_at")


def test_logout_while_cognito_totp_response_is_inflight_fences_new_session(native_app, monkeypatch):
    client = native_app.test_client()
    pending = password(client)
    binding = client.get_cookie(cookie_name(native_app.config, "admin", flow=True)).value
    provider = native_app.test_providers["admin"]
    original = provider.native_totp

    def cancel(*args):
        result = original(*args)
        native_app.test_store.cancel_login(digest(binding), "admin", NOW)
        return result

    monkeypatch.setattr(provider, "native_totp", cancel)
    result = post(client, pending, code="123456")
    assert result.status_code == 401
    assert not native_app.test_store.sessions


def test_native_database_failure_never_grants_access_or_exposes_driver_details(
    native_app, monkeypatch
):
    client = native_app.test_client()
    pending = password(client)

    def fail(*args):
        raise StoreUnavailable("PRIVATE_CONNECTION_PASSWORD")

    monkeypatch.setattr(native_app.test_store, "create_session", fail)
    result = post(client, pending, code="123456")
    assert result.status_code == 503
    assert "PRIVATE_" not in result.get_data(as_text=True)
    assert not native_app.test_store.sessions


def test_native_access_logger_redacts_accidental_query_credentials():
    import logging

    from app.auth.logging import CallbackRedaction

    record = logging.LogRecord(
        "werkzeug",
        logging.INFO,
        "",
        0,
        "POST /api/v1/admin/password/transaction?password=PRIVATE_PASSWORD&code=PRIVATE_CODE HTTP/1.1",
        (),
        None,
    )
    assert CallbackRedaction().filter(record)
    assert "PRIVATE_" not in record.getMessage()
    assert "?<redacted>" in record.getMessage()


def test_access_change_during_enrollment_association_does_not_expose_secret(
    native_app, monkeypatch
):
    provider = native_app.test_providers["admin"]
    provider.next_challenge = "MFA_SETUP"

    def disable(session):
        next(iter(native_app.test_store.identities.values()))["admin_active"] = False
        return SECRET, "private-enrollment-session"

    monkeypatch.setattr(provider, "native_associate", disable)
    client = native_app.test_client()
    data = bootstrap(client)
    result = post(client, data, email="synthetic@example.invalid", password="synthetic-password")
    assert result.status_code == 403
    assert SECRET not in result.get_data(as_text=True)
    assert not native_app.test_store.sessions


@pytest.mark.database
@pytest.mark.parametrize("existing_epoch", [False, True])
def test_full_native_login_api_uses_real_mysql_state_sessions_and_integer_versions(
    native_app, mysql_store, existing_epoch
):
    from app import database

    provider = native_app.test_providers["admin"]
    person = mysql_store.upsert_identity(
        provider.issuer, "admin-subject", "admin", "synthetic@example.invalid", "Synthetic", NOW
    )
    mysql_store.grant_admin(person["id"], "owner", NOW)
    if not existing_epoch:
        with database.connect(mysql_store.settings) as connection, connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM auth_admin_login_epochs WHERE identity_id=%s", (person["id"],)
            )
            connection.commit()
    native_app.test_store = mysql_store
    native_app.extensions["auth_store"] = mysql_store
    native_app.extensions["auth_service"].store = mysql_store
    selected = mysql_store.find_identity(provider.issuer, "admin-subject")
    assert type(selected["native_login_version"]) is int
    client = native_app.test_client()
    pending = password(client)
    assert pending["step"] == "totp"
    assert client.get("/api/v1/admin/session").status_code == 401
    result = post(client, pending, code="123456")
    assert result.status_code == 200
    session = client.get("/api/v1/admin/session")
    assert session.status_code == 200
    assert session.json["data"]["administrator"]["role"] == "owner"
    with database.connect(mysql_store.settings) as connection, connection.cursor() as cursor:
        cursor.execute("SELECT encrypted_payload FROM auth_admin_native_flows")
        assert cursor.fetchall() == ()
        cursor.execute("SELECT assurance,encrypted_tokens FROM auth_sessions")
        saved = cursor.fetchone()
        assert json.loads(saved["assurance"])["access_version"] == int(existing_epoch)
        assert "private-access-token" not in saved["encrypted_tokens"]
