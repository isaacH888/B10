"""Tests for ``retrieveUpcomingEvents``, ``exportOrders`` and the dashboard counts route.

The in-memory path runs against the per-process order store; the database path runs
against the fake PyMySQL connection from test_orders, so no MySQL server is needed.
"""

import copy
import csv
import io
import json
from datetime import datetime, timezone

import pymysql
import pytest
from app import reports
from app.admin_orders import EVENT_SQL
from app.automation.store import MemoryStore
from app.reports_queries import (
    EXPORT_COLUMNS,
    LINKED_ORDERS_SQL,
    STATUS_SQL,
    neutralize_formula,
    to_csv,
)
from test_auth import auth_app as auth_app
from test_orders import (
    FakeConnection,
    FakeCursor,
    app,
    assert_error,
    assert_validation_error,
    client,
    create_order_at,
    database,
    link_booking,
    order_payload,
    patch_status,
    post_order,
    stored_row,
)

__all__ = ["app", "auth_app", "client", "database"]

UPCOMING = "/api/v1/events/upcoming"
EXPORT = "/api/v1/orders/export"
COUNTS = "/api/v1/admin/dashboard/counts"
ALL_ROUTES = (UPCOMING, EXPORT, COUNTS)


@pytest.fixture
def three_orders(client):
    """Orders whose events start on 2099-01-10, 2099-01-15 and 2099-01-20 (UTC), oldest first."""
    return [
        create_order_at(client, f"2099-01-{day}T12:00:00+00:00", f"report-key-0123456789-{day}")
        for day in ("10", "15", "20")
    ]


def upcoming(client, **query):
    return client.get(UPCOMING, query_string=query)


def upcoming_ids(client, **query):
    return [item["order_id"] for item in upcoming(client, **query).json["data"]]


def export_table(client, **query):
    response = client.get(EXPORT, query_string=query)
    assert response.status_code == 200
    return list(csv.reader(io.StringIO(response.get_data(as_text=True))))


def rename_customer(client, name, key):
    payload = order_payload()
    payload["customer"]["name"] = name
    return post_order(client, payload, headers={"Idempotency-Key": key}).json["data"]


# --------------------------------------------------------------------------- #
# Admin authentication
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("path", ALL_ROUTES)
def test_routes_require_an_admin_session(app, path):
    response = app.test_client().get(path)
    assert response.status_code == 401
    assert response.json["error"]["code"] == "unauthenticated"
    assert response.json["error"]["request_id"] == response.headers["X-Request-ID"]


@pytest.mark.parametrize("path", ALL_ROUTES)
def test_unauthenticated_requests_never_reach_the_database(app, path, monkeypatch):
    def forbidden(**options):
        raise AssertionError("authentication must run before any query")

    app.config.update(DB_USER="orders_user", DB_PASSWORD="orders_password")
    monkeypatch.setattr(pymysql, "connect", forbidden)
    assert app.test_client().get(path).status_code == 401


@pytest.mark.parametrize("path", ALL_ROUTES)
def test_routes_reject_other_methods(client, path):
    assert_error(client.delete(path, headers=client.admin_headers), 405, "method_not_allowed")


# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "value,expected",
    [
        ("=SUM(A1)", "'=SUM(A1)"),
        ("+1", "'+1"),
        ("-1", "'-1"),
        ("@cmd", "'@cmd"),
        ("  =SUM(A1)", "'  =SUM(A1)"),
        ("\t=SUM(A1)", "'\t=SUM(A1)"),
        ("\rvalue", "'\rvalue"),
        ("Plain Name", "Plain Name"),
        ("a=b", "a=b"),
        ("", ""),
        (None, ""),
        (50, "50"),
    ],
)
def test_neutralize_prefixes_only_formula_like_text(value, expected):
    assert neutralize_formula(value) == expected


def test_to_csv_writes_the_header_and_quotes_special_characters():
    row = dict.fromkeys(EXPORT_COLUMNS, "x")
    row["customer_name"] = 'Smith, "Jo"\nJr'
    table = list(csv.reader(io.StringIO(to_csv([row]))))
    assert table[0] == list(EXPORT_COLUMNS)
    assert table[1][2] == 'Smith, "Jo"\nJr'


# --------------------------------------------------------------------------- #
# GET /orders/export: in-memory path
# --------------------------------------------------------------------------- #


def test_export_with_no_orders_is_a_header_only_csv(client):
    response = client.get(EXPORT)
    assert response.status_code == 200
    assert response.get_data(as_text=True) == ",".join(EXPORT_COLUMNS) + "\r\n"


def test_export_returns_csv_with_download_headers(client, three_orders):
    response = client.get(EXPORT)
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "text/csv; charset=utf-8"
    assert response.headers["Content-Disposition"] == 'attachment; filename="orders_export.csv"'
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Request-ID"]


def test_export_rows_match_the_stored_orders(client, three_orders):
    table = export_table(client)
    assert tuple(table[0]) == EXPORT_COLUMNS
    assert len(table) == 4
    # Newest first, with the event start shown in the event's own time zone.
    assert table[3] == [
        three_orders[0]["id"],
        "pending_review",
        "Example Customer",
        "2099-01-10T06:00:00-06:00",
        "50",
        "delivery",
        "USD",
        "20000",
        "10000",
        "pending",
    ]
    assert [row[0] for row in table[1:]] == [order["id"] for order in reversed(three_orders)]


def test_export_filters_by_status_and_event_window(client, three_orders):
    patch_status(client, three_orders[0]["id"], {"version": 1, "status": "confirmed"})
    assert [row[0] for row in export_table(client, status="confirmed")[1:]] == [
        three_orders[0]["id"]
    ]
    window = export_table(
        client, event_from="2099-01-15T12:00:00Z", event_to="2099-01-20T12:00:00Z"
    )
    assert [row[0] for row in window[1:]] == [three_orders[1]["id"]]
    assert export_table(client, status="fulfilled")[1:] == []
    assert export_table(client, format="csv")[1:] != []


def test_export_neutralizes_formulas_and_escapes_cells(client):
    formula = rename_customer(client, '=HYPERLINK("http://x.invalid")', "export-key-0123456789-1")
    spaced = rename_customer(client, "  @SUM(A1)", "export-key-0123456789-2")
    comma = rename_customer(client, 'Smith, "Jo"', "export-key-0123456789-3")
    names = {row[0]: row[2] for row in export_table(client)[1:]}
    assert names[formula["id"]] == '\'=HYPERLINK("http://x.invalid")'
    assert names[spaced["id"]] == "'@SUM(A1)"  # the API trims the name before storing it
    assert names[comma["id"]] == 'Smith, "Jo"'


def test_export_over_the_cap_is_422_export_too_large(client, three_orders, monkeypatch):
    monkeypatch.setattr(reports, "EXPORT_ROW_CAP", 2)
    response = client.get(EXPORT)
    assert_error(response, 422, "export_too_large")
    assert response.json["error"]["message"] == "Narrow the filters before exporting."
    assert response.mimetype == "application/json"
    assert "Content-Disposition" not in response.headers
    assert len(export_table(client, status="pending_review", event_to="2099-01-20T12:00:00Z")) == 3


def test_export_at_exactly_the_cap_succeeds(client, three_orders, monkeypatch):
    monkeypatch.setattr(reports, "EXPORT_ROW_CAP", 3)
    assert len(export_table(client)) == 4


@pytest.mark.parametrize(
    "query,field",
    [
        ({"status": "submitted"}, "status"),
        ({"status": ""}, "status"),
        ({"format": "xlsx"}, "format"),
        ({"event_from": "tomorrow"}, "event_from"),
        ({"event_to": "2099-01-15"}, "event_to"),
        ({"event_from": "2099-01-15T12:00:00Z", "event_to": "2099-01-15T12:00:00Z"}, "event_to"),
    ],
)
def test_invalid_export_query_is_422(client, query, field):
    assert_validation_error(client.get(EXPORT, query_string=query), field)


def test_export_does_not_shadow_order_lookup(client, three_orders):
    assert client.get(f"/api/v1/orders/{three_orders[0]['id']}").status_code == 200
    assert client.get("/api/v1/orders/export").mimetype == "text/csv"


# --------------------------------------------------------------------------- #
# GET /events/upcoming: in-memory path
# --------------------------------------------------------------------------- #


def test_upcoming_with_no_orders_returns_an_empty_envelope(client):
    response = upcoming(client)
    assert response.status_code == 200
    assert response.json["data"] == []
    assert response.json["meta"] == {
        "page": 1,
        "page_size": 25,
        "total": 0,
        "request_id": response.headers["X-Request-ID"],
    }


def test_upcoming_items_follow_the_event_summary_shape(client, three_orders):
    response = upcoming(client)
    assert response.status_code == 200
    item = response.json["data"][0]
    assert set(item) == {"order_id", "order_status", "event", "quantity", "service_type"}
    assert item["order_id"] == three_orders[0]["id"]
    assert item["order_status"] == "pending_review"
    assert item["event"] == three_orders[0]["event"]
    assert (item["quantity"], item["service_type"]) == (50, "delivery")
    assert response.json["meta"]["total"] == 3


def test_upcoming_orders_by_event_start_then_order_id(client):
    late = create_order_at(client, "2099-03-01T12:00:00+00:00", "upcoming-key-0123456789-a")
    early = create_order_at(client, "2099-02-01T12:00:00+00:00", "upcoming-key-0123456789-b")
    tied = [
        create_order_at(client, "2099-02-15T12:00:00+00:00", f"upcoming-key-0123456789-t{n}")
        for n in range(4)
    ]
    expected = [early["id"], *sorted(order["id"] for order in tied), late["id"]]
    assert upcoming_ids(client) == expected


def test_upcoming_excludes_cancelled_orders(client, three_orders):
    patch_status(client, three_orders[1]["id"], {"version": 1, "status": "cancelled"})
    patch_status(client, three_orders[2]["id"], {"version": 1, "status": "confirmed"})
    response = upcoming(client)
    assert [item["order_id"] for item in response.json["data"]] == [
        three_orders[0]["id"],
        three_orders[2]["id"],
    ]
    assert response.json["meta"]["total"] == 2


def test_upcoming_window_is_inclusive_from_and_exclusive_to(client, three_orders):
    first, middle, last = (order["id"] for order in three_orders)
    assert upcoming_ids(client, event_from="2099-01-15T12:00:00+00:00") == [middle, last]
    assert upcoming_ids(client, event_to="2099-01-15T12:00:00+00:00") == [first]
    assert upcoming_ids(
        client, event_from="2099-01-15T12:00:00Z", event_to="2099-01-20T12:00:00Z"
    ) == [middle]
    # 06:00-06:00 on the 15th is the exact instant of the middle event.
    assert upcoming_ids(
        client, event_from="2099-01-15T06:00:00-06:00", event_to="2099-01-15T07:00:00-06:00"
    ) == [middle]
    assert upcoming_ids(client, event_from="2099-01-21T00:00:00Z") == []


def test_upcoming_defaults_to_events_that_have_not_started(app, client, three_orders):
    past = copy.deepcopy(three_orders[0])
    past["id"] = "order_in_the_past"
    past["event"]["starts_at"] = "2000-01-01T12:00:00+00:00"
    app.extensions["orders_memory"]["by_id"][past["id"]] = past
    assert past["id"] not in upcoming_ids(client)
    assert upcoming_ids(client, event_from="1999-01-01T00:00:00Z")[0] == past["id"]


def test_upcoming_pagination_slices_and_reports_the_total(client):
    created = [
        create_order_at(client, f"2099-02-0{day}T12:00:00+00:00", f"page-key-0123456789-{day}")[
            "id"
        ]
        for day in range(1, 6)
    ]
    pages = [upcoming(client, page=number, page_size=2).json for number in (1, 2, 3, 4)]
    assert [[item["order_id"] for item in page["data"]] for page in pages] == [
        created[0:2],
        created[2:4],
        created[4:],
        [],
    ]
    assert all(page["meta"]["total"] == 5 and page["meta"]["page_size"] == 2 for page in pages)
    assert [page["meta"]["page"] for page in pages] == [1, 2, 3, 4]


def test_upcoming_page_size_bounds_are_accepted(client):
    for page_size in (1, 100):
        assert upcoming(client, page_size=page_size).json["meta"]["page_size"] == page_size


@pytest.mark.parametrize(
    "query,field",
    [
        ({"page": "0"}, "page"),
        ({"page": "abc"}, "page"),
        ({"page": "1.5"}, "page"),
        ({"page_size": "0"}, "page_size"),
        ({"page_size": "101"}, "page_size"),
        ({"page_size": "ten"}, "page_size"),
        ({"event_from": "tomorrow"}, "event_from"),
        ({"event_from": "2099-01-15T12:00:00"}, "event_from"),
        ({"event_to": "not a date"}, "event_to"),
        ({"event_from": "2099-01-15T12:00:00Z", "event_to": "2099-01-15T11:00:00Z"}, "event_to"),
    ],
)
def test_invalid_upcoming_query_is_422(client, query, field):
    assert_validation_error(upcoming(client, **query), field)


def test_all_upcoming_query_failures_are_reported_together(client):
    response = upcoming(client, page="0", page_size="500", event_from="x")
    fields = {item["field"] for item in response.json["error"]["fields"]}
    assert {"page", "page_size", "event_from"} <= fields


# --------------------------------------------------------------------------- #
# GET /admin/dashboard/counts: in-memory path
# --------------------------------------------------------------------------- #


def booking(booking_id, status, payment_status, start):
    return {"id": booking_id, "status": status, "payment_status": payment_status, "start": start}


def test_dashboard_counts_schema_with_no_data(client):
    response = client.get(COUNTS)
    assert response.status_code == 200
    assert set(response.json) == {"data", "meta"}
    assert response.json["meta"] == {"request_id": response.headers["X-Request-ID"]}
    assert response.json["data"] == {
        "orders_awaiting_import": 0,
        "bookings_by_status": {
            "requested": 0,
            "awaiting_deposit": 0,
            "owner_review": 0,
            "confirmed": 0,
            "cancelled": 0,
        },
        "payments_by_status": {"unpaid": 0, "partial": 0, "deposit_paid": 0, "paid": 0},
        "upcoming_confirmed_bookings": 0,
    }


def test_dashboard_awaiting_import_counts_pending_orders_without_a_booking(client, three_orders):
    assert client.get(COUNTS).json["data"]["orders_awaiting_import"] == 3
    patch_status(client, three_orders[0]["id"], {"version": 1, "status": "confirmed"})
    patch_status(client, three_orders[1]["id"], {"version": 1, "status": "cancelled"})
    assert client.get(COUNTS).json["data"]["orders_awaiting_import"] == 1


def test_dashboard_aggregates_orders_links_and_bookings(app, client, three_orders):
    store = app.extensions["automation_store"] = MemoryStore()
    with store.transaction() as tx:
        tx.save_booking(booking("b1", "confirmed", "paid", "2099-01-15T12:00:00+00:00"))
        tx.save_booking(booking("b2", "confirmed", "deposit_paid", "2000-01-15T12:00:00+00:00"))
        tx.save_booking(booking("b3", "awaiting_deposit", "unpaid", "2099-02-01T12:00:00+00:00"))
        tx.save_booking(booking("b4", "cancelled", "partial", "2099-02-02T12:00:00+00:00"))
        tx.save_booking({"id": "b5", "status": "requested", "start": "2099-02-03T12:00:00Z"})
        tx.save_order_link({"order_id": three_orders[0]["id"], "booking_id": "b1"})
    data = client.get(COUNTS).json["data"]
    assert data["orders_awaiting_import"] == 2
    assert data["bookings_by_status"] == {
        "requested": 1,
        "awaiting_deposit": 1,
        "owner_review": 0,
        "confirmed": 2,
        "cancelled": 1,
    }
    # The cancelled booking is left out; a booking with no payment status counts as unknown.
    assert data["payments_by_status"] == {
        "unpaid": 1,
        "partial": 0,
        "deposit_paid": 1,
        "paid": 1,
        "unknown": 1,
    }
    assert data["upcoming_confirmed_bookings"] == 1


# --------------------------------------------------------------------------- #
# Imported orders follow their booking: in-memory path
# --------------------------------------------------------------------------- #


def import_order(app, order_id, status, payment_status, **fields):
    """Link an order to an in-memory booking carrying the given live values."""
    link_booking(app, order_id, status, payment_status)
    store = app.extensions["automation_store"]
    with store.transaction() as tx:
        saved = tx.get_booking("booking_" + order_id)
        tx.save_booking({**saved, **fields})


def test_export_status_and_deposit_follow_the_booking(app, client, three_orders):
    first, middle, last = (order["id"] for order in three_orders)
    import_order(app, first, "confirmed", "paid")
    import_order(app, middle, "cancelled", "unpaid")
    patch_status(client, last, {"version": 1, "status": "confirmed"})
    rows = {row[0]: (row[1], row[9]) for row in export_table(client)[1:]}
    assert rows == {
        first: ("confirmed", "confirmed"),
        middle: ("cancelled", "pending"),
        last: ("confirmed", "pending"),
    }
    assert [row[0] for row in export_table(client, status="confirmed")[1:]] == [last, first]
    assert [row[0] for row in export_table(client, status="pending_review")[1:]] == []


def test_export_uses_the_booking_schedule_amounts_and_window(app, client, three_orders):
    first = three_orders[0]["id"]
    import_order(
        app,
        first,
        "confirmed",
        "paid",
        start="2099-03-01T18:00:00Z",
        quantity=80,
        service_type="full_service",
        currency="USD",
        total_minor=31000,
        deposit_minor=15500,
    )
    row = export_table(client, event_from="2099-03-01T00:00:00Z")[1]
    assert row == [
        first,
        "confirmed",
        "Example Customer",
        "2099-03-01T12:00:00-06:00",
        "80",
        "full_service",
        "USD",
        "31000",
        "15500",
        "confirmed",
    ]
    assert export_table(client, event_to="2099-01-12T00:00:00Z")[1:] == []


def test_upcoming_follows_the_booking_status_and_schedule(app, client, three_orders):
    first, middle, last = (order["id"] for order in three_orders)
    import_order(app, first, "cancelled", "unpaid")
    import_order(
        app,
        middle,
        "owner_review",
        "unpaid",
        start="2099-01-25T15:00:00Z",
        quantity=120,
        venue="The Pavilion",
    )
    data = upcoming(client).json
    assert [item["order_id"] for item in data["data"]] == [last, middle]
    assert data["meta"]["total"] == 2
    moved = data["data"][1]
    assert moved["order_status"] == "pending_review"
    assert moved["quantity"] == 120 and moved["venue"] == "The Pavilion"
    assert moved["event"]["starts_at"] == "2099-01-25T09:00:00-06:00"
    assert "venue" not in data["data"][0]
    window = upcoming_ids(
        client, event_from="2099-01-22T00:00:00Z", event_to="2099-01-30T00:00:00Z"
    )
    assert window == [middle]


def test_memory_mode_never_opens_a_database_connection(client, three_orders, monkeypatch):
    def forbidden(**options):
        raise AssertionError("no database credentials are configured")

    monkeypatch.setattr(pymysql, "connect", forbidden)
    for path in ALL_ROUTES:
        assert client.get(path).status_code == 200


# --------------------------------------------------------------------------- #
# Database path
# --------------------------------------------------------------------------- #


def select_statements(connection):
    return [(sql, params) for sql, params in connection.statements if sql.startswith("SELECT")]


def upcoming_row(client, database):
    """``(public_id, status, response_json, booking_json)`` as the upcoming query returns it."""
    body = stored_row(client, database)[0]
    return (json.loads(body)["id"], "pending_review", body, None)


def export_row(client, database):
    """``(public_id, status, name, response_json, booking_json, deposit_status)``."""
    body = stored_row(client, database)[0]
    return (json.loads(body)["id"], "confirmed", "Example Customer", body, None, "confirmed")


def test_database_upcoming_calls_reports_queries_with_a_parameterized_ordered_query(
    client, database
):
    row = upcoming_row(client, database)
    database.connection = FakeConnection(rows=[row], total=7)
    response = upcoming(client, page=3, page_size=2, event_from="2099-01-01T06:00:00-06:00")
    connection = database.connection
    assert response.status_code == 200
    assert response.json["meta"] == {
        "page": 3,
        "page_size": 2,
        "total": 7,
        "request_id": response.headers["X-Request-ID"],
    }
    assert [item["order_id"] for item in response.json["data"]] == [row[0]]
    assert response.json["data"][0]["order_status"] == "pending_review"
    count, page = select_statements(connection)
    where = " WHERE (" + STATUS_SQL + ") <> 'cancelled' AND " + EVENT_SQL + " >= %s"
    start = datetime(2099, 1, 1, 12, 0)
    assert count == ("SELECT COUNT(*)" + LINKED_ORDERS_SQL + where, [start])
    assert page[0].endswith(" ASC, o.public_id ASC LIMIT %s OFFSET %s")
    assert where in page[0] and "ORDER BY " + EVENT_SQL in page[0]
    assert page[1] == [start, 2, 4]
    assert connection.closed


def test_database_upcoming_defaults_the_start_to_now(client, database):
    database.connection = FakeConnection()
    before = datetime.now(timezone.utc).replace(tzinfo=None)
    assert upcoming(client).status_code == 200
    after = datetime.now(timezone.utc).replace(tzinfo=None)
    (event_from,) = select_statements(database.connection)[0][1]
    assert before <= event_from <= after


def test_database_export_returns_csv_and_limits_the_rows_read(client, database):
    row = export_row(client, database)
    database.connection = FakeConnection(rows=[row])
    response = client.get(
        EXPORT, query_string={"status": "confirmed", "event_to": "2100-01-01T00:00:00Z"}
    )
    sql, params = select_statements(database.connection)[0]
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "text/csv; charset=utf-8"
    assert response.headers["Content-Disposition"] == 'attachment; filename="orders_export.csv"'
    assert " WHERE (" + STATUS_SQL + ") = %s AND " + EVENT_SQL + " < %s" in sql
    assert sql.endswith(" ORDER BY o.id DESC LIMIT %s")
    assert params == ["confirmed", datetime(2100, 1, 1), reports.EXPORT_ROW_CAP + 1]
    table = list(csv.reader(io.StringIO(response.get_data(as_text=True))))
    assert tuple(table[0]) == EXPORT_COLUMNS
    assert table[1][:3] == [row[0], "confirmed", "Example Customer"]
    assert table[1][-1] == "confirmed"
    assert database.connection.closed


def test_database_export_over_the_cap_is_422_export_too_large(client, database):
    row = export_row(client, database)
    database.connection = FakeConnection(rows=[row] * (reports.EXPORT_ROW_CAP + 1))
    response = client.get(EXPORT)
    assert_error(response, 422, "export_too_large")
    assert response.json["error"]["code"] == "export_too_large"
    assert database.connection.closed


class DashboardCursor(FakeCursor):
    """Answers each dashboard query by the shape of its SQL."""

    def fetchone(self):
        return (4,) if "l.order_id IS NULL" in self.last_sql else (1,)

    def fetchall(self):
        if "GROUP BY status" in self.last_sql:
            return [("confirmed", 2), ("requested", 1)]
        return [("unpaid", 2), ("paid", 1), (None, 1)]


class DashboardConnection(FakeConnection):
    def cursor(self):
        return DashboardCursor(self)


def test_database_dashboard_calls_reports_queries(client, database):
    database.connection = DashboardConnection()
    before = datetime.now(timezone.utc)
    response = client.get(COUNTS)
    assert response.status_code == 200
    assert response.json["data"] == {
        "orders_awaiting_import": 4,
        "bookings_by_status": {
            "requested": 1,
            "owner_review": 0,
            "awaiting_deposit": 0,
            "confirmed": 2,
            "cancelled": 0,
        },
        "payments_by_status": {
            "unpaid": 2,
            "partial": 0,
            "deposit_paid": 0,
            "paid": 1,
            "unknown": 1,
        },
        "upcoming_confirmed_bookings": 1,
    }
    awaiting, by_status, by_payment, upcoming_confirmed = select_statements(database.connection)
    assert "LEFT JOIN automation_order_links" in awaiting[0] and "l.order_id IS NULL" in awaiting[0]
    assert "WHERE status <> 'cancelled'" in by_payment[0]
    (now_text,) = upcoming_confirmed[1]
    assert before <= datetime.fromisoformat(now_text) <= datetime.now(timezone.utc)
    assert database.connection.closed


@pytest.mark.parametrize("path", ALL_ROUTES)
def test_database_failures_return_503_without_leaking_details(client, database, path):
    database.connection = FakeConnection(fail_on="SELECT")
    response = client.get(path)
    assert_error(response, 503, "service_unavailable")
    assert "secret-host" not in response.get_data(as_text=True)
    assert database.connection.closed


@pytest.mark.parametrize("path", ALL_ROUTES)
def test_database_connection_failure_returns_503(client, database, monkeypatch, path):
    def refuse(**options):
        raise pymysql.err.OperationalError(2003, "secret-host.internal refused the connection")

    monkeypatch.setattr(pymysql, "connect", refuse)
    response = client.get(path)
    assert_error(response, 503, "service_unavailable")
    assert "secret-host" not in response.get_data(as_text=True)
