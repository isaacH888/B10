"""Mocked Google tests. No Google/AWS credentials or live network are used."""

import logging
from urllib.parse import parse_qs, urlsplit

import pytest
from app.auth.logging import CallbackRedaction
from app.automation.google import GoogleFailure, GoogleHTTPAdapter, MemoryGoogle, MemorySecrets
from app.automation.oauth import APP_SCOPE, EXISTING_SCOPE, OAuthService
from app.automation.store import MemoryStore


@pytest.fixture
def oauth_setup():
    settings = {
        "APP_ENV": "development",
        "GOOGLE_REDIRECT_URI": "http://localhost:5000/api/v1/admin/automation/google/callback",
        "GOOGLE_CLIENT_SECRET_ARN": "client",
        "GOOGLE_TOKEN_SECRET_PREFIX": "test/tokens",
    }
    store, google = MemoryStore(), MemoryGoogle()
    vault = MemorySecrets(
        {"client": {"client_id": "server-client", "client_secret": "never-expose-this"}}
    )
    now = [1900000000]
    service = OAuthService(settings, store, google, vault, lambda: now[0])
    return service, store, google, vault, now


def connect(service, session="real-session"):
    result = service.start("owner", session)
    query = parse_qs(urlsplit(result["authorization_url"]).query)
    return service.finish(query["state"][0], "server-code", "owner", session)


@pytest.mark.parametrize(
    "name", ["", "arn:aws:secretsmanager:us-east-1:ACCOUNT_ID:secret:PLACEHOLDER"]
)
def test_missing_google_client_reports_setup_and_does_not_access_secrets(oauth_setup, name):
    service, _, _, vault, _ = oauth_setup
    service.settings["GOOGLE_CLIENT_SECRET_ARN"] = name

    def unexpected_secret_read(*args):
        raise AssertionError("Status and unconfigured connection must not access AWS secrets")

    vault.get = unexpected_secret_read
    status = service.status("owner")
    assert status["status"] == "disconnected"
    assert status["configured"] is False
    assert "setup is required" in status["setup_message"]
    assert "ACCOUNT_ID" not in str(status)
    with pytest.raises(GoogleFailure, match="Configure the server Google OAuth client secret"):
        service.start("owner", "real-session")


def test_configured_status_does_not_reveal_or_fetch_server_credentials(oauth_setup):
    service, _, _, vault, _ = oauth_setup
    vault.get = lambda *args: (_ for _ in ()).throw(
        AssertionError("Status must not fetch credentials")
    )
    status = service.status("owner")
    assert status["configured"] is True
    assert status["setup_message"] is None
    assert "secret_arn" not in status
    assert "client_id" not in status


def test_offline_small_scope_exact_callback_and_server_secrets(oauth_setup):
    service, store, google, vault, _ = oauth_setup
    request = service.start("owner", "real-session")
    query = parse_qs(urlsplit(request["authorization_url"]).query)
    assert query["redirect_uri"] == [service.settings["GOOGLE_REDIRECT_URI"]]
    assert query["scope"] == [APP_SCOPE]
    assert query["access_type"] == ["offline"]
    assert query["prompt"] == ["consent"]
    assert "never-expose-this" not in request["authorization_url"]
    result = service.finish(query["state"][0], "code", "owner", "real-session")
    assert result["status"] == "connected"
    assert "secret_arn" not in result
    assert "mock-refresh" not in str(result)
    with store.transaction() as tx:
        connection = tx.get_connection("owner")
    assert vault.get(connection["secret_arn"])["refresh_token"] == "mock-refresh"
    assert google.calls[0] == ("exchange", service.settings["GOOGLE_REDIRECT_URI"])


def test_state_is_session_bound_expiring_and_single_use(oauth_setup):
    service, _, google, _, now = oauth_setup
    result = service.start("owner", "session-one")
    state = parse_qs(urlsplit(result["authorization_url"]).query)["state"][0]
    with pytest.raises(GoogleFailure, match="another session"):
        service.finish(state, "code", "owner", "session-two")
    assert not google.calls
    service.finish(state, "code", "owner", "session-one")
    with pytest.raises(GoogleFailure):
        service.finish(state, "code", "owner", "session-one")
    expired = parse_qs(urlsplit(service.start("owner", "session-one")["authorization_url"]).query)[
        "state"
    ][0]
    now[0] += 601
    with pytest.raises(GoogleFailure, match="expired"):
        service.finish(expired, "code", "owner", "session-one")


def test_failed_exchange_does_not_reuse_state(oauth_setup):
    service, _, google, _, _ = oauth_setup
    state = parse_qs(urlsplit(service.start("owner", "session")["authorization_url"]).query)[
        "state"
    ][0]

    def failed(*args):
        raise GoogleFailure("transient", "Try again.")

    google.exchange = failed
    with pytest.raises(GoogleFailure, match="Try again"):
        service.finish(state, "code", "owner", "session")
    with pytest.raises(GoogleFailure, match="expired"):
        service.finish(state, "code", "owner", "session")


def test_reconnect_preserves_refresh_token_and_calendar(oauth_setup):
    service, store, google, vault, _ = oauth_setup
    first = connect(service)
    google.exchange = lambda *args: {"access_token": "new-access", "expires_in": 3600}
    second = connect(service)
    assert second["calendar_id"] == first["calendar_id"]
    assert len(google.calendars) == 1
    with store.transaction() as tx:
        secret = tx.get_connection("owner")["secret_arn"]
    assert vault.get(secret)["refresh_token"] == "mock-refresh"
    with store.transaction() as tx:
        assert tx.get_connection("owner")["connection_revision"] == 2
    service.disconnect("owner")
    with store.transaction() as tx:
        assert tx.get_connection("owner")["connection_revision"] == 3


def test_existing_calendar_requests_events_scope(oauth_setup):
    service, _, google, _, _ = oauth_setup
    service.settings["GOOGLE_EXISTING_CALENDAR_ID"] = "selected-owner-calendar"
    google.calendars["selected-owner-calendar"] = {"id": "selected-owner-calendar"}
    query = parse_qs(urlsplit(service.start("owner", "session")["authorization_url"]).query)
    assert query["scope"] == [EXISTING_SCOPE]
    service.finish(query["state"][0], "code", "owner", "session")
    assert not any(call[0] == "create_calendar" for call in google.calls)


def test_revoked_refresh_marks_reconnect_and_disconnect_keeps_calendar_id(oauth_setup):
    service, store, google, vault, now = oauth_setup
    connected = connect(service)
    now[0] += 3601
    google.refresh_error = GoogleFailure(
        "reconnect_required", "Reconnect Google Calendar to restore access."
    )
    with pytest.raises(GoogleFailure):
        service.access_token("owner")
    assert service.status("owner")["status"] == "reconnect_required"
    result = service.disconnect("owner")
    assert result["status"] == "disconnected"
    assert result["calendar_id"] == connected["calendar_id"]
    with store.transaction() as tx:
        assert vault.get(tx.get_connection("owner")["secret_arn"]) is None


def test_ambiguous_calendar_provisioning_does_not_create_duplicate(oauth_setup):
    service, store, google, _, _ = oauth_setup
    with store.transaction() as tx:
        tx.save_connection({"owner_id": "owner", "calendar_provisioning": True})
    with pytest.raises(GoogleFailure, match="earlier calendar creation"):
        connect(service)
    assert not google.calendars
    assert service.status("owner")["status"] == "repair_required"


@pytest.mark.parametrize("status", [400, 401, 403, 404, 405, 410, 422, 429])
def test_rejected_calendar_creation_can_be_retried_without_manual_recovery(oauth_setup, status):
    service, store, google, _, _ = oauth_setup
    create_calendar = google.create_calendar
    category = (
        "reconnect_required"
        if status in {401, 403}
        else "transient"
        if status == 429
        else "invalid"
    )

    def rejected(*args):
        raise GoogleFailure(category, "Correct the Google configuration and retry.", status=status)

    google.create_calendar = rejected
    with pytest.raises(GoogleFailure, match="Correct the Google configuration"):
        connect(service)
    with store.transaction() as tx:
        connection = tx.get_connection("owner")
    assert connection["calendar_provisioning"] is False
    assert not connection.get("calendar_id")
    assert connection["last_error"] == "Correct the Google configuration and retry."
    assert connection["status"] == (
        "reconnect_required" if category == "reconnect_required" else "repair_required"
    )

    google.create_calendar = create_calendar
    assert connect(service)["status"] == "connected"
    assert len(google.calendars) == 1


@pytest.mark.parametrize("status", [None, 302, 408, 409, 418, 500, 503])
def test_uncertain_calendar_creation_preserves_marker_and_actual_failure(oauth_setup, status):
    service, store, google, _, _ = oauth_setup
    create_calendar = google.create_calendar

    def uncertain(*args):
        create_calendar(*args)
        raise GoogleFailure(
            "transient", "Google did not confirm the calendar creation.", status=status
        )

    google.create_calendar = uncertain
    with pytest.raises(GoogleFailure, match="did not confirm"):
        connect(service)
    with store.transaction() as tx:
        connection = tx.get_connection("owner")
    assert connection["calendar_provisioning"] is True
    assert connection["last_error"] == "Google did not confirm the calendar creation."
    assert connection["status"] == "repair_required"

    google.create_calendar = create_calendar
    with pytest.raises(GoogleFailure, match="earlier calendar creation"):
        connect(service)
    assert len(google.calendars) == 1
    assert len([call for call in google.calls if call[0] == "create_calendar"]) == 1


def test_disconnect_invalidates_pending_connect_callbacks(oauth_setup):
    service, _, google, _, _ = oauth_setup
    result = service.start("owner", "real-session")
    state = parse_qs(urlsplit(result["authorization_url"]).query)["state"][0]
    service.disconnect("owner")
    with pytest.raises(GoogleFailure, match="cancelled by a disconnect"):
        service.finish(state, "code", "owner", "real-session")
    assert not google.calendars
    assert service.status("owner")["status"] == "disconnected"
    assert connect(service)["status"] == "connected"


@pytest.mark.parametrize(
    "status,error,category",
    [
        (400, {"error": "invalid_grant"}, "reconnect_required"),
        (401, {}, "reconnect_required"),
        (429, {}, "transient"),
        (503, {}, "transient"),
        (403, {"error": {"errors": [{"reason": "rateLimitExceeded"}]}}, "transient"),
        (403, {"error": {"errors": [{"reason": "insufficientPermissions"}]}}, "reconnect_required"),
        (403, {"error": {"errors": None, "details": None}}, "reconnect_required"),
        (400, {"error": {"message": "secret-provider-detail"}}, "invalid"),
    ],
)
def test_google_errors_are_safe_and_classified(status, error, category):
    class Response:
        status_code = status
        content = b"body"

        def json(self):
            return error

    class Session:
        def request(self, *args, **kwargs):
            assert kwargs["timeout"] == (5, 20)
            assert kwargs["allow_redirects"] is False
            return Response()

    with pytest.raises(GoogleFailure) as raised:
        GoogleHTTPAdapter(Session()).refresh(
            "secret-token", {"client_id": "id", "client_secret": "secret"}
        )
    assert raised.value.category == category
    assert "secret-provider-detail" not in str(raised.value)
    assert "secret-token" not in str(raised.value)


@pytest.mark.parametrize(
    "provider_error",
    [
        {"errors": [{"reason": "accessNotConfigured"}]},
        {
            "details": [
                {
                    "@type": "type.googleapis.com/google.rpc.ErrorInfo",
                    "reason": "SERVICE_DISABLED",
                    "metadata": {"activationUrl": "https://example.com/secret-provider-detail"},
                }
            ]
        },
    ],
)
def test_disabled_calendar_api_has_safe_actionable_configuration_error(provider_error):
    class Response:
        status_code = 403
        content = b"body"

        def json(self):
            return {"error": dict(provider_error, message="secret-provider-detail")}

    class Session:
        def request(self, *args, **kwargs):
            return Response()

    with pytest.raises(GoogleFailure) as raised:
        GoogleHTTPAdapter(Session()).create_calendar("secret-token")
    assert raised.value.category == "invalid"
    assert raised.value.status == 403
    assert "Enable Google Calendar API in Google Cloud Console" in raised.value.message
    assert "secret-provider-detail" not in raised.value.message
    assert "secret-token" not in raised.value.message


def test_calendar_callback_access_log_redacts_code_and_state():
    record = logging.LogRecord(
        "werkzeug",
        logging.INFO,
        "",
        0,
        "GET /api/v1/admin/automation/google/callback?code=secret&state=private HTTP/1.1",
        (),
        None,
    )
    CallbackRedaction().filter(record)
    assert "secret" not in record.getMessage()
    assert "private" not in record.getMessage()
    assert "?<redacted>" in record.getMessage()
