"""Customer-only test mail using real authentication guards and injected SES/storage."""

from copy import deepcopy
from uuid import uuid4

import pytest
from app.auth.errors import AuthError
from app.auth.provider import CognitoProvider
from app.email.provider import MailFailure
from app.email.service import CustomerMailService
from app.email.store import MailConflict, MailRateLimited, MailStoreUnavailable
from test_auth import ORIGIN, begin, invite, sign_in
from test_auth import auth_app as auth_app

URL = "/api/v1/customer/test-email"


class MemoryMailStore:
    def __init__(self):
        self.rows = {}
        self.reserve_failure = self.finish_failure = None

    def reserve(self, identity_id, request_hash, recipient_hash, now):
        if self.reserve_failure:
            raise self.reserve_failure
        if request_hash in self.rows:
            row = self.rows[request_hash]
            if row["recipient_hash"] != recipient_hash or row["identity_id"] != identity_id:
                raise MailConflict()
            return deepcopy(row), False
        row = {
            "identity_id": identity_id,
            "recipient_hash": recipient_hash,
            "status": "sending",
            "reference": "TEST-" + uuid4().hex,
            "error_code": None,
        }
        self.rows[request_hash] = row
        return deepcopy(row), True

    def finish(self, request_hash, status, now, *, message_id=None, error_code=None):
        if self.finish_failure:
            raise self.finish_failure
        self.rows[request_hash].update(
            status=status, provider_message_id=message_id, error_code=error_code
        )


class RecordingMailer:
    def __init__(self):
        self.calls = []
        self.failure = None

    def send(self, recipient, name, reference):
        self.calls.append((recipient, name, reference))
        if self.failure:
            raise self.failure
        return "synthetic-ses-message-id"


@pytest.fixture
def mail_app(auth_app):
    auth_app.config.update(EMAIL_ENABLED=True)
    store, mailer = MemoryMailStore(), RecordingMailer()
    manager = auth_app.extensions["auth_service"]
    auth_app.extensions["customer_mail_service"] = CustomerMailService(
        auth_app.config, manager, store, mailer
    )
    auth_app.mail_store, auth_app.mailer = store, mailer
    auth_app.mail_profile = {"email": "fresh-customer@example.invalid", "name": "Current Customer"}

    def profile(token, subject):
        assert token in {"private-access-token", "new-access-token"}
        assert subject == "customer-subject"
        return deepcopy(auth_app.mail_profile)

    auth_app.test_providers["customer"].verified_customer_profile = profile
    return auth_app


def customer_client(app, provider="password"):
    client = app.test_client()
    state = begin(client, provider=provider)
    client.get("/api/v1/customer/callback", query_string={"state": state, "code": "synthetic-code"})
    session = client.get("/api/v1/customer/session").json["data"]
    return client, {
        "Origin": ORIGIN,
        "X-CSRF-Token": session["csrf_token"],
        "Idempotency-Key": str(uuid4()),
    }


@pytest.mark.parametrize("provider", ["password", "google"])
def test_customer_password_and_google_send_only_to_current_verified_profile(mail_app, provider):
    client, headers = customer_client(mail_app, provider)
    result = client.post(URL, json={}, headers=headers)
    assert result.status_code == 200
    assert result.json["data"] == {
        "status": "accepted",
        "reference": mail_app.mailer.calls[0][2],
        "duplicate": False,
    }
    assert mail_app.mailer.calls[0][:2] == ("fresh-customer@example.invalid", "Current Customer")
    assert result.headers["Cache-Control"] == "no-store"
    assert result.json["meta"]["request_id"] == result.headers["X-Request-ID"]
    assert "@" not in result.get_data(as_text=True)
    assert "synthetic-ses-message-id" not in result.get_data(as_text=True)
    assert "fresh-customer@example.invalid" not in str(mail_app.mail_store.rows)


def test_signed_out_customer_and_admin_only_session_cannot_send(mail_app):
    client = mail_app.test_client()
    assert client.post(URL, json={}, headers={"Origin": ORIGIN}).status_code == 401
    invite(mail_app)
    sign_in(client, "admin")
    assert client.post(URL, json={}, headers={"Origin": ORIGIN}).status_code == 401
    assert not mail_app.mailer.calls


@pytest.mark.parametrize(
    "changes",
    [
        {"Origin": "https://evil.example"},
        {"X-CSRF-Token": "wrong"},
        {"Origin": None},
        {"X-CSRF-Token": None},
    ],
)
def test_send_requires_exact_origin_and_bound_csrf(mail_app, changes):
    client, headers = customer_client(mail_app)
    headers.update(changes)
    headers = {key: value for key, value in headers.items() if value is not None}
    assert client.post(URL, json={}, headers=headers).status_code == 403
    assert not mail_app.mailer.calls
    assert not mail_app.mail_store.rows


@pytest.mark.parametrize(
    "payload",
    [
        {"email": "another@example.invalid"},
        {"recipient": "another@example.invalid"},
        {"subject": "arbitrary"},
        {"html": "arbitrary"},
        [],
        None,
        "arbitrary",
    ],
)
def test_browser_cannot_supply_recipient_or_message(mail_app, payload):
    client, headers = customer_client(mail_app)
    assert client.post(URL, json=payload, headers=headers).status_code == 422
    assert not mail_app.mailer.calls


@pytest.mark.parametrize(
    "key", [None, "not-a-uuid", "a" * 500, "00000000-0000-0000-0000-000000000000"]
)
def test_idempotency_key_is_required_and_validated(mail_app, key):
    client, headers = customer_client(mail_app)
    headers.pop("Idempotency-Key")
    if key:
        headers["Idempotency-Key"] = key
    assert client.post(URL, json={}, headers=headers).status_code == 422
    assert not mail_app.mailer.calls


def test_replayed_request_returns_same_reference_without_resending(mail_app):
    client, headers = customer_client(mail_app)
    original = client.post(URL, json={}, headers=headers)
    replay = client.post(URL, json={}, headers=headers)
    assert replay.status_code == 200
    assert replay.json["data"]["duplicate"] is True
    assert replay.json["data"]["reference"] == original.json["data"]["reference"]
    assert len(mail_app.mailer.calls) == 1


def test_same_request_cannot_be_repurposed_after_verified_email_changes(mail_app):
    client, headers = customer_client(mail_app)
    assert client.post(URL, json={}, headers=headers).status_code == 200
    mail_app.mail_profile["email"] = "changed@example.invalid"
    result = client.post(URL, json={}, headers=headers)
    assert result.status_code == 409
    assert result.json["error"]["code"] == "idempotency_conflict"
    assert len(mail_app.mailer.calls) == 1


def test_email_disabled_never_touches_mail_storage_or_provider(mail_app):
    client, headers = customer_client(mail_app)
    mail_app.config["EMAIL_ENABLED"] = False
    result = client.post(URL, json={}, headers=headers)
    assert result.status_code == 503
    assert result.json["error"]["code"] == "email_unavailable"
    assert not mail_app.mailer.calls and not mail_app.mail_store.rows


@pytest.mark.parametrize(
    "failure,code,status",
    [
        (MailRateLimited(), "email_rate_limited", 429),
        (MailStoreUnavailable(), "email_unavailable", 503),
    ],
)
def test_no_send_without_available_budget_and_durable_reservation(mail_app, failure, code, status):
    client, headers = customer_client(mail_app)
    mail_app.mail_store.reserve_failure = failure
    result = client.post(URL, json={}, headers=headers)
    assert result.status_code == status
    assert result.json["error"]["code"] == code
    assert not mail_app.mailer.calls


@pytest.mark.parametrize(
    "kind,code,status",
    [
        ("uncertain", "email_delivery_uncertain", 409),
        ("unavailable", "email_unavailable", 503),
        ("rejected", "email_rejected", 503),
    ],
)
def test_provider_failures_are_safe_and_same_key_never_resends(mail_app, kind, code, status):
    client, headers = customer_client(mail_app)
    mail_app.mailer.failure = MailFailure(kind, "private-safe-label")
    for _ in range(2):
        result = client.post(URL, json={}, headers=headers)
        assert result.status_code == status
        assert result.json["error"]["code"] == code
        assert "private" not in result.get_data(as_text=True)
    assert len(mail_app.mailer.calls) == 1


def test_provider_success_with_lost_database_ack_remains_reserved(mail_app):
    client, headers = customer_client(mail_app)
    mail_app.mail_store.finish_failure = MailStoreUnavailable()
    assert client.post(URL, json={}, headers=headers).status_code == 409
    mail_app.mail_store.finish_failure = None
    assert client.post(URL, json={}, headers=headers).status_code == 409
    assert len(mail_app.mailer.calls) == 1


def test_unexpected_failure_does_not_log_or_expose_private_provider_data(mail_app, caplog):
    client, headers = customer_client(mail_app)
    mail_app.mailer.failure = RuntimeError("sensitive-provider-token-and-recipient")
    result = client.post(URL, json={}, headers=headers)
    assert result.status_code == 409
    assert "sensitive-provider" not in result.get_data(as_text=True) + caplog.text
    assert client.post(URL, json={}, headers=headers).status_code == 409
    assert len(mail_app.mailer.calls) == 1


@pytest.mark.parametrize("invalidate", ["expired", "revoked", "provider_disabled"])
def test_expired_revoked_or_provider_disabled_customer_cannot_send(mail_app, invalidate):
    client, headers = customer_client(mail_app)
    if invalidate == "expired":
        mail_app.test_clock["now"] += mail_app.config["CUSTOMER_SESSION_SECONDS"] + 1
    elif invalidate == "revoked":
        next(iter(mail_app.test_store.sessions.values()))["revoked_at"] = mail_app.test_clock["now"]
    else:
        mail_app.test_providers["customer"].fail = AuthError(
            "unauthenticated", "Private provider error"
        )
    assert client.post(URL, json={}, headers=headers).status_code == 401
    assert not mail_app.mailer.calls


def test_logout_revokes_access_to_test_email(mail_app):
    client, headers = customer_client(mail_app)
    assert client.delete("/api/v1/customer/session", headers=headers).status_code == 200
    assert client.post(URL, json={}, headers=headers).status_code == 401
    assert not mail_app.mailer.calls


def test_customer_token_refresh_preserves_email_access(mail_app):
    client, headers = customer_client(mail_app)
    mail_app.test_clock["now"] += 280
    assert client.post(URL, json={}, headers=headers).status_code == 200
    assert mail_app.test_providers["customer"].refresh_count == 1


def test_unverified_email_from_current_cognito_profile_blocks_send(mail_app):
    client, headers = customer_client(mail_app)

    def unverified(*args):
        raise AuthError("email_verification_required", "Verify your email.", 403)

    mail_app.test_providers["customer"].verified_customer_profile = unverified
    assert client.post(URL, json={}, headers=headers).status_code == 403
    assert not mail_app.mailer.calls and not mail_app.mail_store.rows


def test_ingress_limits_reject_before_touching_authentication(mail_app):
    client = mail_app.test_client()
    results = [client.post(URL, json={}) for _ in range(12)]
    assert [result.status_code for result in results] == [401] * 10 + [429] * 2
    assert not mail_app.mailer.calls


@pytest.mark.parametrize("verified", ["true", "false", None])
def test_live_customer_profile_requires_matching_subject_and_current_verified_email(
    mail_app, monkeypatch, verified
):
    provider = CognitoProvider(mail_app.config, "customer")
    attributes = [
        {"Name": "sub", "Value": "stable-customer"},
        {"Name": "email", "Value": "current@example.invalid"},
    ]
    if verified is not None:
        attributes.append({"Name": "email_verified", "Value": verified})
    calls = []

    def operation(token, name):
        calls.append((token, name))
        return {"UserAttributes": attributes}

    monkeypatch.setattr(provider, "_user_operation", operation)
    if verified == "true":
        assert (
            provider.verified_customer_profile("private-access", "stable-customer")["email"]
            == "current@example.invalid"
        )
    else:
        with pytest.raises(AuthError) as error:
            provider.verified_customer_profile("private-access", "stable-customer")
        assert error.value.code == "email_verification_required"
    with pytest.raises(AuthError) as error:
        provider.verified_customer_profile("private-access", "different-subject")
    assert error.value.code == "authentication_failed"
    assert all(name == "GetUser" for _, name in calls)
