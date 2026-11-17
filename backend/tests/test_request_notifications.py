"""Submitted orders reach the selected inbox and one tentative Google event."""

from copy import deepcopy
from urllib.parse import parse_qs, urlsplit

import pytest
from app import database
from app.automation.delivery import RetryLater
from app.automation.domain import BookingService, DomainError
from app.automation.google import GoogleFailure, MemoryGoogle, MemorySecrets
from app.automation.requests import request_id
from app.automation.runtime import build_services
from app.automation.store import MemoryStore, Store
from test_auth import auth_app as auth_app
from test_automation_routes import signed_owner
from test_automation_store import sql_settings as sql_settings
from test_orders import post_order

BASE = "/api/v1/admin/automation"
RECIPIENT = "owner@example.invalid"


@pytest.fixture
def scenario(auth_app):
    app = auth_app
    google = MemoryGoogle()
    app.config.update(
        DB_USER="",
        DB_PASSWORD="",
        AUTOMATION_ENABLED=True,
        AUTOMATION_MODE="local",
        AUTOMATION_GOOGLE=google,
        AUTOMATION_SECRETS=MemorySecrets(
            {"client": {"client_id": "test", "client_secret": "test"}}
        ),
        GOOGLE_CLIENT_SECRET_ARN="client",
        GOOGLE_EXISTING_CALENDAR_ID="",
        AUTOMATION_DASHBOARD_URL="https://example.invalid/admin/bookings",
        AUTOMATION_CLOCK=lambda: app.test_clock["now"],
    )
    store = MemoryStore()
    adapters = build_services(app.config, store, app.extensions["orders_memory"])
    app.extensions.update(
        adapters,
        automation_store=store,
        booking_service=BookingService(store, clock=lambda: app.test_clock["now"]),
    )
    client, headers = signed_owner(app)
    owner = client.get("/api/v1/admin/session").json["data"]["administrator"]["id"]
    oauth = adapters["google_oauth"]
    start = oauth.start(owner, "session")
    state = parse_qs(urlsplit(start["authorization_url"]).query)["state"][0]
    oauth.finish(state, "synthetic-code", owner, "session")
    return app, client, headers, owner, store, google, adapters


def enable(scenario):
    _, client, headers, _, _, _, _ = scenario
    response = client.post(
        BASE + "/requests", json={"recipient": RECIPIENT, "enabled": True}, headers=headers
    )
    assert response.status_code == 200, response.json
    return response.json["data"]


def drain(adapters):
    for _ in range(10):
        adapters["dispatcher"].dispatch()
        messages = adapters["queue"].messages[:]
        adapters["queue"].messages.clear()
        if not messages:
            return
        for message in messages:
            try:
                adapters["processor"].process(message["body"])
            except Exception as error:
                raise AssertionError(
                    f"Failed synthetic job {message['body']['job_key']}"
                ) from error.__context__
    raise AssertionError("Notifications did not drain")


def owner_messages(adapters):
    """Owner routing is separate from the unconditional customer receipt."""
    return [
        message
        for message in adapters["mail"].messages
        if message["key"].startswith("request_email:")
    ]


def events(google):
    return [event for event in google.events.values() if event.get("status") != "cancelled"]


def test_submission_emails_configured_inbox_and_creates_one_tentative_event(scenario):
    app, client, _, _, store, google, adapters = scenario
    enable(scenario)
    order = post_order(client).json["data"]
    # No side effect occurs in the public HTTP transaction.
    assert not events(google) and owner_messages(adapters) == []
    drain(adapters)
    assert len(events(google)) == 1
    event = events(google)[0]
    assert event["status"] == "tentative"
    assert event["transparency"] == "transparent"
    assert event["start"] == {
        "dateTime": "2099-01-15T15:00:00-06:00",
        "timeZone": "America/Chicago",
    }
    assert event["end"]["dateTime"] == "2099-01-15T17:00:00-06:00"
    assert event["summary"].startswith("Pending request")
    assert "/admin/orders/" + order["id"] in event["description"]
    assert "attendees" not in event and event["visibility"] == "private"
    assert len(owner_messages(adapters)) == 1
    message = owner_messages(adapters)[0]
    assert message["recipient"] == RECIPIENT
    assert order["event"]["starts_at"] in message["body"]
    assert "owner approval" in message["body"]
    assert (
        f"{order['pricing']['total_cents'] // 100}.{order['pricing']['total_cents'] % 100:02d}"
        in message["body"]
    )
    for _ in range(2):
        drain(adapters)
        with store.transaction() as tx:
            jobs = tx.list_outbox()
        for job in jobs:
            adapters["processor"].process({"job_key": job["key"]})
    assert len(events(google)) == len(owner_messages(adapters)) == 1
    assert app.extensions["orders_memory"]["by_id"][order["id"]]["status"] == "pending_review"


def test_old_orders_and_quote_previews_are_not_notified(scenario):
    _, client, _, _, _, google, adapters = scenario
    old = post_order(client).json["data"]
    enable(scenario)
    quote = client.post(
        "/api/v1/quotes", json={"catering_request": old["catering_request"], "event": old["event"]}
    )
    assert quote.status_code == 200
    drain(adapters)
    assert events(google) == [] and owner_messages(adapters) == []


def test_handoff_and_verified_deposit_update_the_same_event(scenario):
    app, client, headers, owner, store, google, adapters = scenario
    enable(scenario)
    order = post_order(client).json["data"]
    drain(adapters)
    identifier = events(google)[0]["id"]
    response = client.post(
        BASE + f"/orders/{order['id']}/booking",
        json={"contract_url": "https://example.invalid/contract"},
        headers=headers,
    )
    assert response.status_code == 201, response.json
    booking = response.json["data"]
    assert booking["id"] == request_id(order["id"])
    drain(adapters)
    assert len(events(google)) == 1 and events(google)[0]["id"] == identifier
    assert events(google)[0]["status"] == "tentative"
    service = app.extensions["booking_service"]
    service.approve(booking["id"], {}, owner)
    drain(adapters)
    service.verify_payment(
        booking["id"],
        {
            "reference": "verified-deposit",
            "amount_minor": booking["deposit_minor"],
            "currency": "USD",
            "verification_details": "Owner verified settled provider transaction",
        },
        owner,
    )
    drain(adapters)
    assert len(events(google)) == 1
    assert events(google)[0]["id"] == identifier
    assert events(google)[0]["status"] == "confirmed"
    assert events(google)[0]["transparency"] == "opaque"
    with store.transaction() as tx:
        request_jobs = [row for row in tx.list_outbox() if row["kind"] == "request_calendar"]
    # Delayed old request messages cannot demote the confirmed booking.
    for job in request_jobs:
        adapters["request_notifications"].execute(job)
    assert events(google)[0]["status"] == "confirmed"


def test_missing_end_stays_unspecified_until_owner_supplies_it(scenario):
    app, client, _, _, _, google, adapters = scenario
    enable(scenario)
    from test_orders import order_payload

    body = order_payload()
    body["event"]["ends_at"] = None
    assert post_order(client, body).status_code == 201
    drain(adapters)
    assert events(google)[0]["endTimeUnspecified"] is True
    assert "not supplied an end time" in events(google)[0]["description"]


def test_owner_intake_before_dispatch_preserves_notification_and_pending_entry(scenario):
    _, client, headers, _, _, google, adapters = scenario
    enable(scenario)
    order = post_order(client).json["data"]
    response = client.post(
        BASE + f"/orders/{order['id']}/booking",
        json={"contract_url": "https://example.invalid/contract"},
        headers=headers,
    )
    assert response.status_code == 201, response.json
    drain(adapters)
    assert len(events(google)) == 1 and events(google)[0]["status"] == "tentative"
    assert len(owner_messages(adapters)) == 1


def test_cancellation_removes_pending_event_and_preserves_order(scenario):
    app, client, _, _, _, google, adapters = scenario
    enable(scenario)
    order = post_order(client).json["data"]
    drain(adapters)
    current = app.extensions["orders_memory"]["by_id"][order["id"]]
    current.update(status="cancelled", version=2)
    drain(adapters)
    assert events(google) == []
    assert app.extensions["orders_memory"]["by_id"][order["id"]]["status"] == "cancelled"


def test_google_failure_does_not_lose_order_or_prevent_owner_email(scenario, monkeypatch):
    app, client, headers, _, store, google, adapters = scenario
    enable(scenario)
    order = post_order(client).json["data"]
    original = google.insert_event

    def fail(*args):
        raise GoogleFailure("reconnect_required", "Reconnect Google Calendar")

    monkeypatch.setattr(google, "insert_event", fail)
    drain(adapters)
    assert len(owner_messages(adapters)) == 1
    assert order["id"] in app.extensions["orders_memory"]["by_id"]
    with store.transaction() as tx:
        assert tx.get_request(request_id(order["id"]))["calendar_status"] == "reconnect_required"
    monkeypatch.setattr(google, "insert_event", original)
    # A fresh real OAuth connection resumes failed request projections.
    owner = client.get("/api/v1/admin/session").json["data"]["administrator"]["id"]
    oauth = adapters["google_oauth"]
    authorization = oauth.start(owner, "another-session")
    state = parse_qs(urlsplit(authorization["authorization_url"]).query)["state"][0]
    oauth.finish(state, "synthetic-code", owner, "another-session")
    drain(adapters)
    assert len(events(google)) == 1 and len(owner_messages(adapters)) == 1


def test_disable_and_reenable_only_start_new_submissions(scenario):
    _, client, headers, _, _, google, adapters = scenario
    enable(scenario)
    assert (
        client.post(BASE + "/requests", json={"enabled": False}, headers=headers).status_code == 200
    )
    post_order(client)
    enable(scenario)
    drain(adapters)
    assert events(google) == [] and owner_messages(adapters) == []


def test_changing_inbox_only_routes_new_requests_and_can_be_stopped(scenario):
    _, client, headers, _, _, google, adapters = scenario
    original = enable(scenario)
    first = post_order(client).json["data"]
    adapters["dispatcher"].dispatch()

    replacement = "replacement@example.invalid"
    response = client.post(
        BASE + "/requests",
        json={"recipient": replacement, "enabled": True},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json["data"]["calendar_id"] == original["calendar_id"]
    second = post_order(client, headers={"Idempotency-Key": "request-after-inbox-change"}).json[
        "data"
    ]
    drain(adapters)
    recipients = {
        order["id"]: next(
            message["recipient"]
            for message in owner_messages(adapters)
            if order["id"] in message["body"]
        )
        for order in (first, second)
    }
    assert recipients == {first["id"]: RECIPIENT, second["id"]: replacement}
    assert len(events(google)) == 2

    assert (
        client.post(BASE + "/requests", json={"enabled": False}, headers=headers).status_code == 200
    )
    assert (
        post_order(client, headers={"Idempotency-Key": "request-after-stopping"}).status_code == 201
    )
    drain(adapters)
    assert len(events(google)) == len(owner_messages(adapters)) == 2


def test_email_failure_does_not_block_the_calendar_fifo_group(scenario, monkeypatch):
    _, client, _, _, _, google, adapters = scenario
    enable(scenario)
    post_order(client)
    adapters["dispatcher"].dispatch()
    messages = adapters["queue"].messages
    assert len({message["group_id"] for message in messages}) == 3

    def fail(*args):
        raise OSError("synthetic mail outage")

    monkeypatch.setattr(adapters["mail"], "send", fail)
    email = next(
        message for message in messages if message["group_id"].startswith("request_email:")
    )
    calendar = next(
        message for message in messages if message["group_id"].startswith("request_calendar:")
    )
    with pytest.raises(RetryLater):
        adapters["processor"].process(email["body"])
    adapters["processor"].process(calendar["body"])
    assert len(events(google)) == 1


def test_exhausted_calendar_retries_are_visible_and_email_remains_sent(scenario, monkeypatch):
    app, client, _, _, store, google, adapters = scenario
    enable(scenario)
    order = post_order(client).json["data"]
    app.config["AUTOMATION_MAX_ATTEMPTS"] = 1

    def fail(*args):
        raise GoogleFailure("transient", "Temporary Calendar outage")

    monkeypatch.setattr(google, "insert_event", fail)
    drain(adapters)
    with store.transaction() as tx:
        assert tx.get_request(request_id(order["id"]))["calendar_status"] == "failed"
    assert len(owner_messages(adapters)) == 1
    assert len(adapters["queue"].dead_letters) == 1


@pytest.mark.parametrize(
    "recipient",
    ["bad", "a@example.invalid\r\nBcc:b@example.invalid", "a@example.invalid,b@example.invalid"],
)
def test_invalid_notification_destinations_are_rejected(scenario, recipient):
    _, client, headers, _, _, _, _ = scenario
    assert (
        client.post(BASE + "/requests", json={"recipient": recipient}, headers=headers).status_code
        == 400
    )


def test_configuration_requires_connected_owner_calendar_and_is_csrf_protected(scenario):
    _, client, headers, owner, store, _, adapters = scenario
    assert client.post(BASE + "/requests", json={"recipient": RECIPIENT}).status_code == 403
    with store.transaction() as tx:
        connection = tx.get_connection(owner)
        connection["status"] = "disconnected"
        tx.save_connection(connection)
    with pytest.raises(DomainError, match="Connect your Google Calendar"):
        adapters["request_notifications"].configure(owner, RECIPIENT)


def test_dispatcher_recovers_submission_after_process_restart(scenario):
    app, client, _, _, store, google, old = scenario
    enable(scenario)
    post_order(client)
    replacement = build_services(app.config, store, app.extensions["orders_memory"])
    drain(replacement)
    assert len(events(google)) == 1
    assert len(owner_messages(replacement)) == 1 and owner_messages(old) == []


def test_work_local_discovers_new_requests_before_consuming_jobs(scenario, monkeypatch, capsys):
    import sys

    import dotenv
    from app.automation import runtime

    app, client, _, _, _, google, adapters = scenario
    enable(scenario)
    post_order(client)
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *args, **kwargs: False)
    monkeypatch.setattr(runtime, "services", lambda: adapters)
    monkeypatch.setattr(runtime, "application", lambda: app)
    monkeypatch.setattr(sys, "argv", ["automation.runtime", "work-local"])
    runtime.main()
    assert len(events(google)) == 1
    assert len(owner_messages(adapters)) == 1
    assert '"simulated_mail": 2' in capsys.readouterr().out


@pytest.mark.database
def test_sql_capture_restart_handoff_and_payment_preserve_one_event(scenario, sql_settings):
    app, client, headers, owner, _, google, _ = scenario
    app.config.update(sql_settings)
    store = Store(sql_settings)
    adapters = build_services(app.config, store)
    app.extensions.update(
        adapters,
        automation_store=store,
        booking_service=BookingService(store, clock=lambda: app.test_clock["now"]),
    )
    oauth = adapters["google_oauth"]
    authorization = oauth.start(owner, "sql-session")
    state = parse_qs(urlsplit(authorization["authorization_url"]).query)["state"][0]
    oauth.finish(state, "synthetic-code", owner, "sql-session")
    sql_scenario = app, client, headers, owner, store, google, adapters
    try:
        old = post_order(client).json["data"]
        adapters["request_notifications"].configure(owner, RECIPIENT)
        enable(sql_scenario)
        # Old submissions are excluded by the durable SQL boundary, not timestamps.
        drain(adapters)
        assert events(google) == []
        body = deepcopy(old)
        for key in list(body):
            if key not in {"customer", "event", "catering_request", "quote_id"}:
                body.pop(key)
        body["quote_id"] = "quote_example_001"
        response = post_order(
            client, body, headers={"Idempotency-Key": "sql-notifications-second-001"}
        )
        assert response.status_code == 201, response.json
        order = response.json["data"]
        replacement = build_services(app.config, Store(sql_settings))
        drain(replacement)
        assert len(events(google)) == 1 and len(owner_messages(replacement)) == 1
        original_event = events(google)[0]["id"]
        result = client.post(
            BASE + f"/orders/{order['id']}/booking",
            json={"contract_url": "https://example.invalid/contract"},
            headers=headers,
        )
        assert result.status_code == 201, result.json
        booking = result.json["data"]
        service = app.extensions["booking_service"]
        service.approve(booking["id"], {}, owner)
        service.verify_payment(
            booking["id"],
            {
                "reference": "sql-verified-deposit",
                "amount_minor": booking["deposit_minor"],
                "currency": "USD",
                "verification_details": "Owner independently checked settled payment",
            },
            owner,
        )
        drain(adapters)
        assert len(events(google)) == 1 and events(google)[0]["id"] == original_event
        assert events(google)[0]["status"] == "confirmed"
        service.cancel(booking["id"], owner)
        drain(adapters)
        assert events(google) == []
    finally:
        with database.connect(sql_settings) as connection, connection.cursor() as cursor:
            for table in (
                "customer_order_accounts",
                "customer_quote_accounts",
                "automation_requests",
                "automation_order_links",
                "order_items",
                "orders",
                "customers",
                "quotes",
            ):
                cursor.execute("DELETE FROM " + table)
            connection.commit()
