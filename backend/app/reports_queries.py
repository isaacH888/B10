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

Schedule, quantity, service and monetary values also follow the linked booking. The
source order's structured address remains intact; upcoming items expose the current
free-text booking venue separately. The same effective-start expression as the owner
workspace controls windowing and ordering. payment_status lives in the booking's data JSON.
"""

import csv
import io
import json
from datetime import datetime
from zoneinfo import ZoneInfo

from .admin_orders import EVENT_SQL

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
        conditions.append(EVENT_SQL + " >= %s")
        params.append(event_from)
    if event_to is not None:
        conditions.append(EVENT_SQL + " < %s")
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


def _current_values(order, booking_json):
    booking = json.loads(booking_json) if booking_json else {}
    event = {**order["event"]}
    event["timezone"] = booking.get("timezone", event["timezone"])
    zone = ZoneInfo(event["timezone"])
    for source, target in (("start", "starts_at"), ("end", "ends_at")):
        if booking.get(source) is not None:
            event[target] = (
                datetime.fromisoformat(booking[source].replace("Z", "+00:00"))
                .astimezone(zone)
                .isoformat()
            )
    catering, pricing = order["catering_request"], order["pricing"]
    return {
        "event": event,
        "quantity": booking.get("quantity", catering["quantity"]),
        "service_type": booking.get("service_type", catering["service_type"]),
        "currency": booking.get("currency", pricing["currency"]),
        "total_cents": booking.get("total_minor", pricing["total_cents"]),
        "deposit_due_cents": booking.get("deposit_minor", pricing["deposit_due_cents"]),
        "venue": booking.get("venue"),
    }


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
        + ", o.response_json, b.data"
        + LINKED_ORDERS_SQL
        + where
        + " ORDER BY "
        + EVENT_SQL
        + " ASC, o.public_id ASC LIMIT %s OFFSET %s",
        [*params, page_size, (page - 1) * page_size],
    )
    items = []
    for public_id, status, response_json, booking_json in cursor.fetchall():
        order = json.loads(response_json)
        current = _current_values(order, booking_json)
        item = {
            "order_id": public_id,
            "order_status": status,
            **{key: current[key] for key in ("event", "quantity", "service_type")},
        }
        if current["venue"] is not None:
            item["venue"] = current["venue"]
        items.append(item)
    return {"items": items, "page": page, "page_size": page_size, "total": total}


def neutralize_formula(value):
    """Stop spreadsheets from running a cell that starts like a formula."""
    text = "" if value is None else str(value)
    unsafe = text.startswith(("\t", "\r", "\n")) or text.lstrip().startswith(("=", "+", "-", "@"))
    return "'" + text if unsafe else text


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
        "SELECT o.public_id, "
        + STATUS_SQL
        + ", c.name, o.response_json, b.data, "
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
    for public_id, order_status, name, response_json, booking_json, deposit_status in fetched:
        current = _current_values(json.loads(response_json), booking_json)
        event = current["event"]
        local_start = (
            datetime.fromisoformat(event["starts_at"].replace("Z", "+00:00"))
            .astimezone(ZoneInfo(event["timezone"]))
            .isoformat()
        )
        rows.append(
            {
                "order_id": public_id,
                "status": order_status,
                "customer_name": name,
                "event_starts_at": local_start,
                **{
                    key: current[key]
                    for key in (
                        "quantity",
                        "service_type",
                        "currency",
                        "total_cents",
                        "deposit_due_cents",
                    )
                },
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
