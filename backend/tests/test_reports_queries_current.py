"""Reporting must follow real booking changes without rewriting customer snapshots."""

import csv
import io
import json
from datetime import datetime
from pathlib import Path

import pymysql
import pytest
from app import database
from app.automation.store import Store
from app.health import connection_options
from app.reports_queries import (
    dashboard_counts,
    export_rows,
    neutralize_formula,
    to_csv,
    upcoming_events,
)
from jsonschema import Draft202012Validator, FormatChecker
from test_admin_completion import confirmed_order
from test_auth import auth_app as auth_app
from test_automation_routes import owner_app as owner_app
from test_automation_routes import signed_owner
from test_automation_store import sql_settings as sql_settings
from test_orders import order_payload

JANUARY = {"event_from": datetime(2099, 1, 1), "event_to": datetime(2099, 1, 16)}
JULY = {"event_from": datetime(2099, 7, 1), "event_to": datetime(2099, 8, 1)}


@pytest.fixture
def report_app(owner_app, sql_settings):
    owner_app.config.update(sql_settings)
    store = Store(sql_settings)
    owner_app.extensions["automation_store"] = store
    owner_app.extensions["booking_service"].store = store
    yield owner_app
    with database.connect(sql_settings) as connection, connection.cursor() as cursor:
        for table in ("automation_order_links", "order_items", "orders", "customers"):
            cursor.execute("DELETE FROM " + table)
        connection.commit()


@pytest.fixture
def moved_order(report_app):
    client, headers = signed_owner(report_app)
    order, booking = confirmed_order(report_app, client, headers)
    body = order_payload()
    body["event"].update(starts_at="2099-01-20T15:00:00-06:00", ends_at="2099-01-20T17:00:00-06:00")
    sibling = client.post(
        "/api/v1/orders", json=body, headers={"Idempotency-Key": "report-sibling-0123456789"}
    )
    assert sibling.status_code == 201
    path = "/api/v1/admin/automation/bookings/" + booking["id"]
    counted = client.post(
        path + "/final-count",
        json={"expected_revision": booking["revision"], "quantity": 75},
        headers=headers,
    )
    assert counted.status_code == 200, counted.json
    moved = client.post(
        path + "/reschedule",
        json={
            "expected_revision": counted.json["data"]["revision"],
            "start": "2099-07-15T20:00:00Z",
            "end": "2099-07-15T22:00:00Z",
            "timezone": "America/Denver",
            "venue": "Updated synthetic reporting venue",
        },
        headers=headers,
    )
    assert moved.status_code == 200, moved.json
    return report_app, client, headers, order, sibling.json["data"], moved.json["data"]


@pytest.mark.database
def test_real_reschedule_moves_reporting_window_and_page_order(moved_order):
    app, _, _, order, sibling, _ = moved_order
    with (
        pymysql.connect(**connection_options(app.config)) as connection,
        connection.cursor() as cursor,
    ):
        assert upcoming_events(cursor, **JANUARY)["total"] == 0
        july = upcoming_events(cursor, **JULY)
        assert [item["order_id"] for item in july["items"]] == [order["id"]]
        first = upcoming_events(cursor, page_size=1)
        second = upcoming_events(cursor, page=2, page_size=1)
        assert first["total"] == second["total"] == 2
        assert first["items"][0]["order_id"] == sibling["id"]
        assert second["items"][0]["order_id"] == order["id"]
        assert upcoming_events(cursor, event_to=datetime(2099, 7, 15, 20))["total"] == 1
        assert upcoming_events(cursor, event_from=datetime(2099, 7, 15, 20))["total"] == 1
        assert upcoming_events(cursor, page=2, **JULY)["items"] == []


@pytest.mark.database
def test_upcoming_payload_uses_current_time_zone_count_and_venue(moved_order):
    app, client, _, order, _, _ = moved_order
    with (
        pymysql.connect(**connection_options(app.config)) as connection,
        connection.cursor() as cursor,
    ):
        result = upcoming_events(cursor, **JULY)
    item = result["items"][0]
    assert (item["order_status"], item["quantity"], item["service_type"]) == (
        "confirmed",
        75,
        "delivery",
    )
    assert item["event"]["starts_at"] == "2099-07-15T14:00:00-06:00"
    assert item["event"]["ends_at"] == "2099-07-15T16:00:00-06:00"
    assert item["event"]["timezone"] == "America/Denver"
    assert item["venue"] == "Updated synthetic reporting venue"
    assert item["event"]["location"] == order["event"]["location"]
    spec = json.loads((Path(__file__).resolve().parents[2] / "docs/api/openapi.json").read_text())
    Draft202012Validator(
        {"components": spec["components"], "$ref": "#/components/schemas/UpcomingEventsData"},
        format_checker=FormatChecker(),
    ).validate(result)
    actual = client.get("/api/v1/admin/calendar?year=2099&month=7").json["data"]["events"][0]
    assert actual["order_id"] == item["order_id"]
    assert actual["quantity"] == item["quantity"]
    assert datetime.fromisoformat(actual["start"]) == datetime.fromisoformat(
        item["event"]["starts_at"]
    )


@pytest.mark.database
def test_export_uses_current_booking_window_and_values(moved_order):
    app, _, _, order, _, booking = moved_order
    with (
        pymysql.connect(**connection_options(app.config)) as connection,
        connection.cursor() as cursor,
    ):
        assert export_rows(cursor, **JANUARY) == []
        rows = export_rows(cursor, **JULY)
        assert len(rows) == 1
        row = rows[0]
        assert (row["order_id"], row["status"], row["deposit_status"]) == (
            order["id"],
            "confirmed",
            "confirmed",
        )
        assert (row["event_starts_at"], row["quantity"]) == ("2099-07-15T14:00:00-06:00", 75)
        assert (row["total_cents"], row["deposit_due_cents"]) == (
            booking["total_minor"],
            booking["deposit_minor"],
        )
        assert export_rows(cursor, event_to=datetime(2099, 7, 15, 20)) != rows
        assert export_rows(cursor, event_from=datetime(2099, 7, 15, 20)) == rows


@pytest.mark.database
def test_reporting_leaves_original_submission_and_replay_intact(moved_order):
    app, client, _, order, _, _ = moved_order
    with (
        pymysql.connect(**connection_options(app.config)) as connection,
        connection.cursor() as cursor,
    ):
        upcoming_events(cursor)
        export_rows(cursor)
        cursor.execute(
            "SELECT response_json,submission_json FROM orders WHERE public_id=%s", (order["id"],)
        )
        assert all(json.loads(snapshot) == order for snapshot in cursor.fetchone())
    body = order_payload()
    body["customer"]["name"] = "Synthetic Customer"
    replay = client.post(
        "/api/v1/orders", json=body, headers={"Idempotency-Key": "confirmed-order-0123456789"}
    )
    assert replay.status_code == 201 and replay.json["data"] == order


@pytest.mark.database
def test_cancelled_real_booking_is_excluded_and_export_keeps_current_details(moved_order):
    app, client, headers, _, _, booking = moved_order
    result = client.post(
        "/api/v1/admin/automation/bookings/" + booking["id"] + "/cancel",
        json={"expected_revision": booking["revision"]},
        headers=headers,
    )
    assert result.status_code == 200
    with (
        pymysql.connect(**connection_options(app.config)) as connection,
        connection.cursor() as cursor,
    ):
        assert upcoming_events(cursor, **JULY)["total"] == 0
        row = export_rows(cursor, status="cancelled", **JULY)[0]
        assert (row["quantity"], row["event_starts_at"]) == (75, "2099-07-15T14:00:00-06:00")
        counts = dashboard_counts(cursor, "2099-01-01T00:00:00+00:00")
        assert counts["upcoming_confirmed_bookings"] == 0


@pytest.mark.database
def test_csv_neutralizes_stored_name_with_whitespace_and_quotes(moved_order):
    app, _, _, order, _, _ = moved_order
    name = ' \n=HYPERLINK("https://example.invalid", "Synthetic, name")'
    with (
        pymysql.connect(**connection_options(app.config)) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "UPDATE customers c JOIN orders o ON o.customer_id=c.id SET c.name=%s WHERE o.public_id=%s",
            (name, order["id"]),
        )
        rows = export_rows(cursor, **JULY)
        parsed = list(csv.DictReader(io.StringIO(to_csv(rows))))
    assert len(parsed) == 1
    assert parsed[0]["customer_name"] == "'" + name


@pytest.mark.parametrize("prefix", ["=", "+", "-", "@"])
@pytest.mark.parametrize("whitespace", ["", " ", "  ", "\t", "\r", "\n", " \t\n", "\u00a0"])
def test_csv_formula_prefixes_are_neutralized_after_whitespace(prefix, whitespace):
    value = whitespace + prefix + "SUM(1,2)"
    assert neutralize_formula(value) == "'" + value


@pytest.mark.parametrize("value", [None, "", "Plain name", "  Plain name", "50", 50, " "])
def test_csv_preserves_safe_values(value):
    assert neutralize_formula(value) == ("" if value is None else str(value))
