"""Customer-only development auth uses the existing OAuth/session protections."""

from importlib import import_module

import pytest
from app import create_app
from app.auth.settings import authentication_enabled, environment_settings, validate_settings
from app.email.settings import validate_settings as validate_email_settings
from test_auth import ORIGIN, begin, sign_in
from test_auth import auth_app as auth_app
from test_auth_store import db_settings as db_settings
from test_auth_store import store as store


@pytest.fixture
def customer_settings(auth_app):
    settings = dict(auth_app.config)
    settings.update(
        AUTH_ENABLED=False,
        CUSTOMER_AUTH_ENABLED=True,
        AUTH_PROVIDERS={"customer": auth_app.test_providers["customer"]},
    )
    for suffix in ("ISSUER", "CLIENT_ID", "CLIENT_SECRET", "DOMAIN"):
        settings["COGNITO_ADMIN_" + suffix] = ""
    return settings


@pytest.fixture
def customer_app(customer_settings):
    return create_app(customer_settings)


@pytest.mark.parametrize("shared", [False, True])
def test_unset_customer_override_preserves_shared_default(monkeypatch, shared):
    monkeypatch.setenv("AUTH_ENABLED", str(shared).lower())
    monkeypatch.delenv("CUSTOMER_AUTH_ENABLED", raising=False)
    settings = environment_settings("development")
    assert authentication_enabled(settings, "customer") is shared
    assert authentication_enabled(settings, "admin") is shared


@pytest.mark.parametrize("shared,customer", [(False, True), (True, False)])
def test_customer_override_does_not_change_admin_default(monkeypatch, shared, customer):
    monkeypatch.setenv("AUTH_ENABLED", str(shared).lower())
    monkeypatch.setenv("CUSTOMER_AUTH_ENABLED", str(customer).lower())
    settings = environment_settings("development")
    assert authentication_enabled(settings, "customer") is customer
    assert authentication_enabled(settings, "admin") is shared


@pytest.mark.parametrize("value", ["", "1", "yes", "false "])
def test_customer_flag_requires_an_explicit_boolean(monkeypatch, value):
    monkeypatch.setenv("CUSTOMER_AUTH_ENABLED", value)
    with pytest.raises(ValueError, match="CUSTOMER_AUTH_ENABLED must be true or false"):
        environment_settings("development")


def test_only_enabled_provider_is_constructed(customer_settings, monkeypatch):
    provider = customer_settings.pop("AUTH_PROVIDERS")["customer"]
    areas = []

    def construct(settings, area):
        areas.append(area)
        return provider

    monkeypatch.setattr("app.auth.provider.CognitoProvider", construct)
    app = create_app(customer_settings)
    assert areas == ["customer"]
    assert set(app.extensions["auth_service"].providers) == {"customer"}
    assert "customer_mail_service" in app.extensions


@pytest.mark.parametrize("provider", ["password", "google"])
def test_customer_login_session_and_csrf_logout_work_without_admin(customer_app, provider):
    client = customer_app.test_client()
    state = begin(client, provider=provider)
    callback = client.get(
        "/api/v1/customer/callback", query_string={"state": state, "code": "synthetic-code"}
    )
    assert callback.status_code == 303
    assert callback.location == ORIGIN + "/account"
    assert "HttpOnly" in callback.headers["Set-Cookie"]
    session = client.get("/api/v1/customer/session")
    assert session.status_code == 200
    assert session.json["data"]["customer"]["email"] == "synthetic@example.invalid"
    assert "private-" not in session.get_data(as_text=True)
    assert session.headers["Cache-Control"] == "no-store"
    assert client.delete("/api/v1/customer/session", headers={"Origin": ORIGIN}).status_code == 403
    logout = client.delete(
        "/api/v1/customer/session",
        headers={"Origin": ORIGIN, "X-CSRF-Token": session.json["data"]["csrf_token"]},
    )
    assert logout.status_code == 200
    assert client.get("/api/v1/customer/session").status_code == 401


@pytest.mark.parametrize(
    "method,path",
    [
        ("POST", "/admin/login"),
        ("GET", "/admin/session"),
        ("DELETE", "/admin/session"),
        ("GET", "/admin/password/transaction"),
        ("POST", "/admin/password/transaction"),
        ("DELETE", "/admin/password/transaction"),
        ("GET", "/admin/automation/bookings"),
        ("GET", "/admin/automation/google"),
        ("GET", "/orders/order_example"),
        ("PATCH", "/orders/order_example/status"),
    ],
)
def test_customer_session_cannot_activate_disabled_admin_routes(customer_app, method, path):
    client = customer_app.test_client()
    sign_in(client)
    session = client.get("/api/v1/customer/session").json["data"]
    client.set_cookie("popssibilities_admin", client.get_cookie("popssibilities_customer").value)
    result = client.open(
        "/api/v1" + path,
        method=method,
        json={} if method in {"POST", "PATCH"} else None,
        headers={"Origin": ORIGIN, "X-CSRF-Token": session["csrf_token"]},
    )
    assert result.status_code == 503
    assert result.json["error"]["code"] == "authentication_unavailable"
    assert client.get("/api/v1/customer/session").status_code == 200


def test_disabled_admin_callback_does_not_consume_customer_login(customer_app):
    client = customer_app.test_client()
    state = begin(client)
    denied = client.get(
        "/api/v1/admin/callback", query_string={"state": state, "code": "synthetic-code"}
    )
    assert denied.location == ORIGIN + "/admin/login?error=authentication_unavailable"
    assert client.get("/api/v1/customer/session").status_code == 401
    accepted = client.get(
        "/api/v1/customer/callback", query_string={"state": state, "code": "synthetic-code"}
    )
    assert accepted.location == ORIGIN + "/account"
    assert client.get("/api/v1/customer/session").status_code == 200


@pytest.mark.parametrize(
    "name,value",
    [
        ("COGNITO_CUSTOMER_ISSUER", ""),
        ("COGNITO_CUSTOMER_CLIENT_ID", ""),
        ("COGNITO_CUSTOMER_CLIENT_SECRET", ""),
        ("COGNITO_CUSTOMER_DOMAIN", "http://untrusted.example.invalid"),
        ("AUTH_TOKEN_ENCRYPTION_KEY", ""),
        ("SECRET_KEY", "short"),
        ("AUTH_ORIGIN", "http://untrusted.example.invalid"),
    ],
)
def test_customer_only_mode_still_requires_secure_configuration(customer_settings, name, value):
    customer_settings[name] = value
    with pytest.raises(ValueError):
        create_app(customer_settings)


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_customer_only_mode_cannot_disable_hosted_admin_security(customer_settings, environment):
    customer_settings["APP_ENV"] = environment
    with pytest.raises(ValueError, match="both areas in hosted environments"):
        validate_settings(customer_settings)


@pytest.mark.parametrize("schema_ready", [True, False])
def test_readiness_checks_auth_storage_in_customer_only_mode(
    customer_app, monkeypatch, schema_ready
):
    monkeypatch.setattr(import_module("app.health"), "database_available", lambda: True)
    monkeypatch.setattr(
        customer_app.extensions["auth_store"], "ready", lambda: schema_ready, raising=False
    )
    result = customer_app.test_client().get("/api/v1/health")
    assert result.status_code == (200 if schema_ready else 503)
    assert result.json["data"]["authentication"] == ("ready" if schema_ready else "unavailable")


def test_customer_mail_requires_customer_authentication_even_when_admin_is_enabled():
    settings = {
        "AUTH_ENABLED": False,
        "CUSTOMER_AUTH_ENABLED": True,
        "EMAIL_ENABLED": True,
        "EMAIL_PROVIDER": "ses",
        "EMAIL_AWS_REGION": "us-east-1",
        "EMAIL_FROM_ADDRESS": "orders@example.invalid",
        "EMAIL_REPLY_TO_ADDRESS": "support@example.invalid",
    }
    validate_email_settings(settings)
    settings.update(AUTH_ENABLED=True, CUSTOMER_AUTH_ENABLED=False)
    with pytest.raises(ValueError, match="authenticated customer sessions"):
        validate_email_settings(settings)


def test_admin_only_development_does_not_require_customer_provider(auth_app):
    settings = dict(auth_app.config)
    settings.update(CUSTOMER_AUTH_ENABLED=False)
    for suffix in ("ISSUER", "CLIENT_ID", "CLIENT_SECRET", "DOMAIN"):
        settings["COGNITO_CUSTOMER_" + suffix] = ""
    app = create_app(settings)
    assert set(app.extensions["auth_service"].providers) == {"admin"}
    assert "customer_mail_service" not in app.extensions
    client = app.test_client()
    assert client.get("/api/v1/admin/session").status_code == 401
    assert client.get("/api/v1/customer/session").status_code == 503


@pytest.mark.database
@pytest.mark.parametrize("provider", ["password", "google"])
def test_customer_only_oauth_persists_and_revokes_real_mysql_sessions(
    customer_settings, store, provider
):
    customer_settings["AUTH_STORE"] = store
    app = create_app(customer_settings)
    client = app.test_client()
    state = begin(client, provider=provider)
    result = client.get(
        "/api/v1/customer/callback", query_string={"state": state, "code": "synthetic-code"}
    )
    assert result.location == ORIGIN + "/account"
    identity = store.find_identity(customer_settings["COGNITO_CUSTOMER_ISSUER"], "customer-subject")
    assert identity["area"] == "customer"
    session = client.get("/api/v1/customer/session")
    assert session.status_code == 200
    assert client.get("/api/v1/admin/session").status_code == 503
    logout = client.delete(
        "/api/v1/customer/session",
        headers={"Origin": ORIGIN, "X-CSRF-Token": session.json["data"]["csrf_token"]},
    )
    assert logout.status_code == 200
    assert client.get("/api/v1/customer/session").status_code == 401
