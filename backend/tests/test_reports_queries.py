"""Reporting queries against disposable MySQL: dashboard counts, order export, upcoming events.

Every test inserts its own fake rows inside one transaction and rolls it back, so nothing is
left behind. An imported order is one linked to a booking through automation_order_links; its
status and deposit status come from the booking, not from the order row frozen at import.
"""

import csv
import hashlib
import io
import json
from datetime import datetime

import pymysql
import pytest
from app.health import connection_options
from app.reports_queries import (
    EXPORT_COLUMNS,
    ExportTooLarge,
    dashboard_counts,
    export_rows,
    neutralize_formula,
    to_csv,
    upcoming_events,
)
from test_automation_store import sql_settings as sql_settings

pytestmark = pytest.mark.database

WINDOW = {"event_from": datetime(2031, 1, 1), "event_to": datetime(2032, 1, 1)}


@pytest.fixture
def cursor(sql_settings):
    connection = pymysql.connect(**connection_options(sql_settings))
    try:
        with connection.cursor() as cursor:
            yield cursor
    finally:
        connection.rollback()
        connection.close()


def add_booking(cursor, key, status, payment_status, start_at):
    booking_id = hashlib.md5(key.encode()).hexdigest()
    body = json.dumps({"id": booking_id, "status": status, "payment_status": payment_status})
    cursor.execute(
        "INSERT INTO automation_bookings (id, status, revision, start_at, end_at, data)"
        " VALUES (%s, %s, 0, %s, %s, %s)",
        (booking_id, status, start_at, start_at, body),
    )
    return booking_id


def add_order(
    cursor,
    public_id,
    status,
    starts_at,
    *,
    name="Test Customer",
    quantity=50,
    service="delivery",
    deposit="pending",
    booking=None,
):
    """Insert one order. booking is (status, payment_status) to import it, or None."""
    cursor.execute(
        "INSERT INTO customers (name, email, phone) VALUES (%s, %s, %s)",
        (name, public_id + "@example.test", "5555550100"),
    )
    body = json.dumps(
        {
            "id": public_id,
            "status": status,
            "event": {
                "type": "Wedding",
                "location": {"line1": "1 Main St", "city": "Houston"},
                "starts_at": starts_at.isoformat() + "Z",
                "timezone": "America/Chicago",
            },
            "catering_request": {"quantity": quantity, "service_type": service},
            "pricing": {"currency": "USD", "total_cents": 20000, "deposit_due_cents": 10000},
            "deposit": {"status": deposit},
        }
    )
    cursor.execute(
        "INSERT INTO orders (public_id, customer_id, status, version, quote_id, pricing_revision,"
        " total_cents, deposit_due_cents, event_starts_at, event_timezone, idempotency_key,"
        " response_json, request_hash, submission_json)"
        " VALUES (%s, %s, %s, 1, 'quote_test', 'rev_test', 20000, 10000, %s, 'America/Chicago',"
        " %s, %s, %s, %s)",
        (public_id, cursor.lastrowid, status, starts_at, "idem_" + public_id, body, "0" * 64, body),
    )
    if booking is not None:
        booking_id = add_booking(
            cursor, public_id, booking[0], booking[1], starts_at.isoformat() + "+00:00"
        )
        cursor.execute(
            "INSERT INTO automation_order_links (order_id, booking_id, data) VALUES (%s, %s, '{}')",
            (public_id, booking_id),
        )


def letters(found):
    """The last character of each order id, e.g. order_up_a -> a."""
    return [(item["order_id"] if isinstance(item, dict) else item)[-1] for item in found]


@pytest.fixture
def upcoming_orders(cursor):
    # Imported orders: the order row is frozen at pending_review, the booking has the truth.
    rows = [
        ("a", "pending_review", datetime(2031, 3, 1, 12), 50, "delivery", None),
        ("b", "confirmed", datetime(2031, 3, 2, 12), 120, "full_service", None),
        ("c", "cancelled", datetime(2031, 3, 3, 12), 60, "delivery", None),
        ("d", "fulfilled", datetime(2031, 3, 4, 12), 75, "delivery", None),
        ("e", "pending_review", datetime(2031, 3, 5, 12), 80, "delivery", ("confirmed", "paid")),
        ("f", "pending_review", datetime(2031, 3, 6, 12), 90, "delivery", ("cancelled", "unpaid")),
        (
            "g",
            "pending_review",
            datetime(2031, 3, 7, 12),
            100,
            "full_service",
            ("awaiting_deposit", "unpaid"),
        ),
    ]
    for suffix, status, starts_at, quantity, service, booking in rows:
        add_order(
            cursor,
            "order_up_" + suffix,
            status,
            starts_at,
            quantity=quantity,
            service=service,
            booking=booking,
        )


def test_upcoming_events_excludes_cancelled_orders_and_cancelled_bookings(cursor, upcoming_orders):
    data = upcoming_events(cursor, **WINDOW)
    assert letters(data["items"]) == ["a", "b", "d", "e", "g"]
    assert data["total"] == 5
    assert (data["page"], data["page_size"]) == (1, 25)


def test_upcoming_events_items_match_the_contract(cursor, upcoming_orders):
    item = upcoming_events(cursor, **WINDOW)["items"][1]
    assert set(item) == {"order_id", "order_status", "event", "quantity", "service_type"}
    assert item["order_status"] == "confirmed"
    assert (item["quantity"], item["service_type"]) == (120, "full_service")
    assert item["event"]["type"] == "Wedding"


def test_upcoming_events_status_comes_from_the_booking_when_imported(cursor, upcoming_orders):
    statuses = {
        item["order_id"][-1]: item["order_status"]
        for item in upcoming_events(cursor, **WINDOW)["items"]
    }
    assert statuses == {
        "a": "pending_review",
        "b": "confirmed",
        "d": "fulfilled",
        "e": "confirmed",
        "g": "pending_review",
    }


def test_upcoming_events_window_is_from_inclusive_and_to_exclusive(cursor, upcoming_orders):
    data = upcoming_events(
        cursor, event_from=datetime(2031, 3, 2, 12), event_to=datetime(2031, 3, 4, 12)
    )
    assert letters(data["items"]) == ["b"]
    assert data["total"] == 1


@pytest.mark.parametrize(
    ("page", "expected"), [(1, ["a", "b"]), (2, ["d", "e"]), (3, ["g"]), (4, [])]
)
def test_upcoming_events_pages_keep_the_total(cursor, upcoming_orders, page, expected):
    data = upcoming_events(cursor, page=page, page_size=2, **WINDOW)
    assert letters(data["items"]) == expected
    assert data["total"] == 5


@pytest.fixture
def export_orders(cursor):
    rows = [
        ("a", "pending_review", "Jane Smith", datetime(2031, 3, 1, 12), "pending", None),
        ("b", "confirmed", "Smith, Bob", datetime(2031, 3, 2, 12), "pending", None),
        ("c", "confirmed", '=HYPERLINK("http://example.test")', datetime(2031, 7, 2, 12), "paid", None),
        ("d", "pending_review", "Dana Paid", datetime(2031, 8, 1, 12), "pending", ("confirmed", "deposit_paid")),
        ("e", "pending_review", "Eli Waiting", datetime(2031, 8, 2, 12), "pending", ("awaiting_deposit", "partial")),
        ("f", "pending_review", "Fay Cancelled", datetime(2031, 8, 3, 12), "pending", ("cancelled", "unpaid")),
    ]  # fmt: skip
    for suffix, status, name, starts_at, deposit, booking in rows:
        add_order(
            cursor,
            "order_ex_" + suffix,
            status,
            starts_at,
            name=name,
            quantity=50 if suffix == "a" else 75,
            deposit=deposit,
            booking=booking,
        )


def test_export_returns_newest_first_with_contract_columns(cursor, export_orders):
    rows = export_rows(cursor, **WINDOW)
    assert letters(rows) == ["f", "e", "d", "c", "b", "a"]
    assert list(rows[0]) == list(EXPORT_COLUMNS)


def test_export_row_values_and_local_event_time(cursor, export_orders):
    by_id = {row["order_id"][-1]: row for row in export_rows(cursor, **WINDOW)}
    row = by_id["a"]
    assert (row["quantity"], row["service_type"], row["currency"]) == (50, "delivery", "USD")
    assert (row["total_cents"], row["deposit_due_cents"]) == (20000, 10000)
    assert row["event_starts_at"] == "2031-03-01T06:00:00-06:00"  # winter offset
    assert by_id["c"]["event_starts_at"] == "2031-07-02T07:00:00-05:00"  # daylight saving


def test_export_status_and_deposit_follow_the_booking_for_imported_orders(cursor, export_orders):
    by_id = {row["order_id"][-1]: row for row in export_rows(cursor, **WINDOW)}
    got = {key: (row["status"], row["deposit_status"]) for key, row in by_id.items()}
    assert got == {
        "a": ("pending_review", "pending"),
        "b": ("confirmed", "pending"),
        "c": ("confirmed", "paid"),  # never imported: its own deposit value is kept
        "d": ("confirmed", "confirmed"),  # booking confirmed, deposit_paid
        "e": ("pending_review", "pending"),  # booking awaiting_deposit, partial
        "f": ("cancelled", "pending"),  # booking cancelled
    }


@pytest.mark.parametrize(
    ("status", "expected"),
    [("confirmed", ["d", "c", "b"]), ("pending_review", ["e", "a"]), ("cancelled", ["f"])],
)
def test_export_status_filter_uses_the_effective_status(cursor, export_orders, status, expected):
    assert letters(export_rows(cursor, status=status, **WINDOW)) == expected


def test_export_window_is_from_inclusive_and_to_exclusive(cursor, export_orders):
    rows = export_rows(
        cursor, event_from=datetime(2031, 3, 2, 12), event_to=datetime(2031, 7, 2, 12)
    )
    assert letters(rows) == ["b"]


def test_export_cap_raises_instead_of_truncating(cursor, export_orders):
    with pytest.raises(ExportTooLarge):
        export_rows(cursor, cap=2, **WINDOW)
    assert len(export_rows(cursor, cap=6, **WINDOW)) == 6


def test_export_csv_quotes_cells_and_neutralizes_formulas(cursor, export_orders):
    parsed = list(csv.reader(io.StringIO(to_csv(export_rows(cursor, **WINDOW)))))
    assert parsed[0] == list(EXPORT_COLUMNS)
    assert len(parsed) == 7
    names = [row[2] for row in parsed[1:]]
    assert "Smith, Bob" in names
    assert any(name.startswith("'=HYPERLINK") for name in names)
    assert neutralize_formula("+1") == "'+1"


def test_dashboard_counts_rise_by_what_was_added(cursor):
    now_text = "2031-06-01T00:00:00+00:00"
    before = dashboard_counts(cursor, now_text)
    july = datetime(2031, 7, 1, 12)
    add_order(cursor, "order_dash_a", "pending_review", july)
    add_order(cursor, "order_dash_b", "pending_review", july)
    add_order(
        cursor, "order_dash_c", "pending_review", july, booking=("awaiting_deposit", "unpaid")
    )
    add_order(cursor, "order_dash_d", "fulfilled", july)
    add_booking(cursor, "dash1", "requested", "unpaid", "2031-07-01T18:00:00+00:00")
    add_booking(cursor, "dash3", "confirmed", "deposit_paid", "2031-07-03T18:00:00+00:00")
    add_booking(cursor, "dash4", "confirmed", "paid", "2031-05-01T18:00:00+00:00")  # in the past
    add_booking(cursor, "dash5", "cancelled", "unpaid", "2031-07-05T18:00:00+00:00")
    after = dashboard_counts(cursor, now_text)

    assert set(after) == {
        "orders_awaiting_import",
        "bookings_by_status",
        "payments_by_status",
        "upcoming_confirmed_bookings",
    }
    # The linked order c is already imported, so only a and b await import.
    assert after["orders_awaiting_import"] - before["orders_awaiting_import"] == 2
    expected_bookings = {
        "requested": 1,
        "owner_review": 0,
        "awaiting_deposit": 1,
        "confirmed": 2,
        "cancelled": 1,
    }
    for name, amount in expected_bookings.items():
        assert after["bookings_by_status"][name] - before["bookings_by_status"][name] == amount
    # Cancelled bookings are left out of the payment counts.
    expected_payments = {"unpaid": 2, "partial": 0, "deposit_paid": 1, "paid": 1}
    for name, amount in expected_payments.items():
        assert after["payments_by_status"][name] - before["payments_by_status"][name] == amount
    # Only the confirmed booking that has not started yet counts.
    assert after["upcoming_confirmed_bookings"] - before["upcoming_confirmed_bookings"] == 1
