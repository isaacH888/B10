"""Read-only SQL behind the admin reporting routes: dashboard, order export, upcoming events.

Each function takes a plain PyMySQL tuple cursor, like the ones in orders.py, and returns
plain Python data. The routes validate parameters and convert event_from and event_to to
naive UTC datetimes before calling.

Status source: when an order is linked to a booking (automation_order_links), the order's own
status and deposit status are frozen at import, so the booking supplies them. The contract
allows only these order statuses (pending_review, confirmed, fulfilled, cancelled) and deposit
statuses (pending, confirmed, reversed), so booking values are mapped:

  booking confirmed -> confirmed        booking cancelled -> cancelled
  booking requested, owner_review, awaiting_deposit -> pending_review
  booking payment_status deposit_paid or paid -> deposit confirmed; unpaid or partial -> pending

fulfilled and reversed have no booking equivalent, so an imported order never shows them.
STATUS_SQL and DEPOSIT_SQL hold the mapping. Orders that were never imported keep their own
values.

Storage facts: orders.event_starts_at is naive UTC DATETIME(6). automation_bookings.start_at is
ISO text in UTC (for example "2026-12-01T18:00:00+00:00"), which compares correctly as text
while every value keeps that one format. payment_status lives only in the booking's data JSON.
"""

import csv
import io
import json
from datetime import timezone
from zoneinfo import ZoneInfo

EXPORT_CAP = 10000
EXPORT_COLUMNS = (
    "order_id",
    "status",
    "customer_name",
    "event_starts_at",
    "quantity",
    "service_type",
    "currency",
    "total_cents",
    "deposit_due_cents",
    "deposit_status",
)
BOOKING_STATUSES = ("requested", "owner_review", "awaiting_deposit", "confirmed", "cancelled")
PAYMENT_STATUSES = ("unpaid", "partial", "deposit_paid", "paid")

# Effective values: the booking's when the order was imported, else the order's own.
STATUS_SQL = (
    "CASE WHEN b.id IS NULL THEN o.status"
    " WHEN b.status = 'confirmed' THEN 'confirmed'"
    " WHEN b.status = 'cancelled' THEN 'cancelled'"
    " ELSE 'pending_review' END"
)
DEPOSIT_SQL = (
    "CASE WHEN b.id IS NULL THEN JSON_UNQUOTE(JSON_EXTRACT(o.response_json, '$.deposit.status'))"
    " WHEN JSON_UNQUOTE(JSON_EXTRACT(b.data, '$.payment_status')) IN ('deposit_paid', 'paid')"
    " THEN 'confirmed' ELSE 'pending' END"
)
LINKED_ORDERS_SQL = (
    " FROM orders o"
    " LEFT JOIN automation_order_links l ON l.order_id = o.public_id"
    " LEFT JOIN automation_bookings b ON b.id = l.booking_id"
)


class ExportTooLarge(Exception):
    """More rows match than the cap allows. The route returns 422 export_too_large."""


def _window(conditions, params, event_from, event_to):
    if event_from is not None:
        conditions.append("o.event_starts_at >= %s")
        params.append(event_from)
    if event_to is not None:
        conditions.append("o.event_starts_at < %s")
        params.append(event_to)


def dashboard_counts(cursor, now_text):
    """Counts for the admin dashboard. now_text is, for example, now in UTC as isoformat()."""
    cursor.execute(
        "SELECT COUNT(*) FROM orders o"
        " LEFT JOIN automation_order_links l ON l.order_id = o.public_id"
        " WHERE o.status = 'pending_review' AND l.order_id IS NULL"
    )
    awaiting_import = int(cursor.fetchone()[0])

    bookings_by_status = _grouped(
        cursor,
        "SELECT status, COUNT(*) FROM automation_bookings GROUP BY status",
        BOOKING_STATUSES,
    )
    # Cancelled bookings are left out: their payment state no longer needs action.
    payments_by_status = _grouped(
        cursor,
        "SELECT JSON_UNQUOTE(JSON_EXTRACT(data, '$.payment_status')) AS payment_status, COUNT(*)"
        " FROM automation_bookings WHERE status <> 'cancelled' GROUP BY payment_status",
        PAYMENT_STATUSES,
    )
    cursor.execute(
        "SELECT COUNT(*) FROM automation_bookings WHERE status = 'confirmed' AND start_at >= %s",
        (now_text,),
    )
    upcoming_confirmed = int(cursor.fetchone()[0])
    return {
        "orders_awaiting_import": awaiting_import,
        "bookings_by_status": bookings_by_status,
        "payments_by_status": payments_by_status,
        "upcoming_confirmed_bookings": upcoming_confirmed,
    }


def _grouped(cursor, sql, known):
    cursor.execute(sql)
    counts = {name: 0 for name in known}
    for name, count in cursor.fetchall():
        # A booking whose JSON has no payment_status groups under "unknown", not None.
        name = "unknown" if name is None else name
        counts[name] = counts.get(name, 0) + int(count)
    return counts


def upcoming_events(cursor, *, event_from=None, event_to=None, page=1, page_size=25):
    """GET /events/upcoming: half-open window, earliest first, cancelled excluded."""
    conditions = ["(" + STATUS_SQL + ") <> 'cancelled'"]
    params = []
    _window(conditions, params, event_from, event_to)
    where = " WHERE " + " AND ".join(conditions)

    cursor.execute("SELECT COUNT(*)" + LINKED_ORDERS_SQL + where, params)
    total = int(cursor.fetchone()[0])
    cursor.execute(
        "SELECT o.public_id, "
        + STATUS_SQL
        + ", o.response_json"
        + LINKED_ORDERS_SQL
        + where
        + " ORDER BY o.event_starts_at ASC, o.public_id ASC LIMIT %s OFFSET %s",
        [*params, page_size, (page - 1) * page_size],
    )
    items = []
    for public_id, status, response_json in cursor.fetchall():
        order = json.loads(response_json)
        items.append(
            {
                "order_id": public_id,
                "order_status": status,
                "event": order["event"],
                "quantity": order["catering_request"]["quantity"],
                "service_type": order["catering_request"]["service_type"],
            }
        )
    return {"items": items, "page": page, "page_size": page_size, "total": total}


def neutralize_formula(value):
    """Stop spreadsheets from running a cell that starts like a formula."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def export_rows(cursor, *, status=None, event_from=None, event_to=None, cap=EXPORT_CAP):
    """GET /orders/export rows, newest first. Raises ExportTooLarge past the cap."""
    conditions = []
    params = []
    if status is not None:
        conditions.append("(" + STATUS_SQL + ") = %s")
        params.append(status)
    _window(conditions, params, event_from, event_to)
    where = (" WHERE " + " AND ".join(conditions)) if conditions else ""

    # One SELECT is one consistent snapshot. Ask for cap + 1 rows so an oversized export is
    # detected instead of silently cut off.
    cursor.execute(
        "SELECT o.public_id, " + STATUS_SQL + ", c.name, o.event_starts_at, o.event_timezone,"
        " JSON_UNQUOTE(JSON_EXTRACT(o.response_json, '$.catering_request.quantity')),"
        " JSON_UNQUOTE(JSON_EXTRACT(o.response_json, '$.catering_request.service_type')),"
        " JSON_UNQUOTE(JSON_EXTRACT(o.response_json, '$.pricing.currency')),"
        " o.total_cents, o.deposit_due_cents, "
        + DEPOSIT_SQL
        + " FROM orders o JOIN customers c ON c.id = o.customer_id"
        " LEFT JOIN automation_order_links l ON l.order_id = o.public_id"
        " LEFT JOIN automation_bookings b ON b.id = l.booking_id"
        + where
        + " ORDER BY o.id DESC LIMIT %s",
        [*params, cap + 1],
    )
    fetched = cursor.fetchall()
    if len(fetched) > cap:
        raise ExportTooLarge()

    rows = []
    for (
        public_id,
        order_status,
        name,
        starts_at,
        tz_name,
        quantity,
        service_type,
        currency,
        total_cents,
        deposit_due_cents,
        deposit_status,
    ) in fetched:
        local_start = (
            starts_at.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(tz_name)).isoformat()
        )
        rows.append(
            {
                "order_id": public_id,
                "status": order_status,
                "customer_name": name,
                "event_starts_at": local_start,
                "quantity": int(quantity) if quantity is not None else None,
                "service_type": service_type,
                "currency": currency,
                "total_cents": int(total_cents),
                "deposit_due_cents": int(deposit_due_cents),
                "deposit_status": deposit_status,
            }
        )
    return rows


def to_csv(rows):
    """Render rows as CSV text: quoted where needed, formula prefixes neutralized."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(EXPORT_COLUMNS)
    for row in rows:
        writer.writerow([neutralize_formula(row[column]) for column in EXPORT_COLUMNS])
    return buffer.getvalue()
