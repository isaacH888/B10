"""Offline smoke coverage for the assembled Flask factory and Lambda WSGI edge."""

import base64
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from app import create_app
from app.automation import runtime
from app.automation.google import MemoryGoogle, MemorySecrets
from app.automation.store import MemoryStore
from flask import Flask, request


def test_lambda_packaging_excludes_private_env_tests_and_caches(tmp_path):
    script = Path(__file__).resolve().parents[1] / "scripts/build_automation_lambda.py"
    spec = importlib.util.spec_from_file_location("build_automation_lambda", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    source, artifact = tmp_path / "source", tmp_path / "artifact"
    (source / "app/__pycache__").mkdir(parents=True)
    (source / "certs").mkdir()
    (source / "tests").mkdir()
    for filename in (
        ".env",
        "app/.env",
        "app/.env.private",
        "app/__pycache__/private.pyc",
        "tests/test_private.py",
    ):
        (source / filename).write_text("synthetic-private-value")
    (source / "app/__init__.py").write_text("# application source\n")
    (source / "certs/mysql-ca.pem").write_text("synthetic-public-ca")
    module.copy_sources(source, artifact)
    assert {
        path.relative_to(artifact).as_posix() for path in artifact.rglob("*") if path.is_file()
    } == {"app/__init__.py", "certs/mysql-ca.pem"}


def test_enabled_factory_wires_external_adapters_without_credentials():
    app = create_app(
        {
            "TESTING": True,
            "APP_ENV": "development",
            "AUTH_ENABLED": False,
            "AUTOMATION_ENABLED": True,
            "AUTOMATION_MODE": "local",
            "AUTOMATION_STORE": MemoryStore(),
            "AUTOMATION_GOOGLE": MemoryGoogle(),
            "AUTOMATION_SECRETS": MemorySecrets(),
        }
    )
    assert app.extensions["google_oauth"] is app.extensions["automation_services"]["google_oauth"]
    assert app.extensions["processor"] is app.extensions["automation_services"]["processor"]
    assert app.test_client().get("/api/v1/admin/automation/bookings").status_code == 503


def test_lambda_adapter_preserves_repeated_cookies_and_query_values(monkeypatch):
    app = Flask(__name__)

    @app.get("/edge")
    def edge():
        response = app.json.response(
            {"values": request.args.getlist("value"), "owner_cookie": request.cookies.get("owner")}
        )
        response.set_cookie("one", "a", secure=True, httponly=True)
        response.set_cookie("two", "b", secure=True, httponly=True)
        return response

    monkeypatch.setattr(runtime, "_application", app)
    result = runtime.api_handler(
        {
            "httpMethod": "GET",
            "path": "/edge",
            "headers": {"Host": "example.invalid"},
            "multiValueHeaders": {"Cookie": ["owner=synthetic", "other=second"]},
            "multiValueQueryStringParameters": {"value": ["a", "b"]},
        },
        None,
    )
    assert result["statusCode"] == 200
    assert len(result["multiValueHeaders"]["Set-Cookie"]) == 2
    body = json.loads(base64.b64decode(result["body"]))
    assert body == {"values": ["a", "b"], "owner_cookie": "synthetic"}


def test_assembled_booking_outbox_calendar_mail_and_reminders_converge():
    """Real application services, stateful external fakes; no Google/AWS requests."""
    google = MemoryGoogle()
    vault = MemorySecrets(
        {"test-client": {"client_id": "synthetic-client", "client_secret": "synthetic-secret"}}
    )
    app = create_app(
        {
            "TESTING": True,
            "APP_ENV": "development",
            "AUTH_ENABLED": False,
            "AUTOMATION_ENABLED": True,
            "AUTOMATION_MODE": "local",
            "AUTOMATION_STORE": MemoryStore(),
            "AUTOMATION_CLOCK": lambda: datetime(2030, 1, 1, tzinfo=timezone.utc),
            "AUTOMATION_GOOGLE": google,
            "AUTOMATION_SECRETS": vault,
            "GOOGLE_CLIENT_SECRET_ARN": "test-client",
            "AUTOMATION_OWNER_EMAIL": "owner@example.invalid",
        }
    )
    services = app.extensions["automation_services"]
    oauth = services["google_oauth"]
    authorization = oauth.start("owner", "owner-session")
    state = parse_qs(urlsplit(authorization["authorization_url"]).query)["state"][0]
    oauth.finish(state, "synthetic-code", "owner", "owner-session")
    domain = app.extensions["booking_service"]
    booking = domain.create(
        {
            "start": "2030-02-20T14:00:00-06:00",
            "end": "2030-02-20T16:00:00-06:00",
            "timezone": "America/Chicago",
            "venue": "Test venue",
            "quantity": 50,
            "service_type": "delivery",
            "total_minor": 10001,
            "currency": "USD",
            "customer_email": "customer@example.invalid",
            "contract_url": "https://example.invalid/contract",
        },
        "owner",
    )
    domain.approve(booking["id"], {}, "owner")
    domain.verify_payment(
        booking["id"],
        {
            "reference": "first-payment",
            "amount_minor": 5001,
            "currency": "USD",
            "verification_details": "Owner checked the settled provider transaction",
        },
        "owner",
    )

    def drain():
        for _ in range(10):
            services["dispatcher"].dispatch()
            messages = services["queue"].messages[:]
            services["queue"].messages.clear()
            if not messages:
                return
            for message in messages:
                services["processor"].process(message["body"])
        raise AssertionError("outbox did not drain")

    drain()
    events = [event for event in google.events.values() if event.get("status") != "cancelled"]
    assert len(events) == 1
    original_event_id = events[0]["id"]
    assert len(services["mail"].messages) == 2
    assert "https://example.invalid/contract" in services["mail"].messages[0]["body"]
    assert len(services["scheduler"].schedules) == 1
    old_payload = next(iter(services["scheduler"].schedules.values()))["payload"]
    domain.reschedule(
        booking["id"],
        {
            "start": "2030-02-21T14:00:00-06:00",
            "end": "2030-02-21T16:00:00-06:00",
            "timezone": "America/Chicago",
        },
        "owner",
    )
    drain()
    events = [event for event in google.events.values() if event.get("status") != "cancelled"]
    assert [event["id"] for event in events] == [original_event_id]
    assert events[0]["start"]["dateTime"].startswith("2030-02-21")
    services["processor"].process(old_payload)
    assert len(services["mail"].messages) == 2
    domain.verify_payment(
        booking["id"],
        {
            "reference": "balance-payment",
            "amount_minor": 5000,
            "currency": "USD",
            "verification_details": "Owner checked the settled balance transaction",
        },
        "owner",
    )
    drain()
    current_payload = next(iter(services["scheduler"].schedules.values()))["payload"]
    services["processor"].process(current_payload)
    assert "final popsicle count" in services["mail"].messages[-1]["body"]
    assert "remaining payment" not in services["mail"].messages[-1]["body"]
    domain.cancel(booking["id"], "owner")
    drain()
    assert not [event for event in google.events.values() if event.get("status") != "cancelled"]
    assert services["scheduler"].schedules == {}
    with app.extensions["automation_store"].transaction() as tx:
        current = tx.get_booking(booking["id"])
        assert current["synced_revision"] == current["revision"]
        assert len(tx.payments(booking["id"])) == 2
