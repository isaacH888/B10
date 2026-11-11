"""Admin reporting: ``retrieveUpcomingEvents``, ``exportOrders`` and dashboard counts.

All three routes require an administrator session with ``bookings:read``. Each one
has a database path (parameterized PyMySQL queries) and an in-memory fallback that
filters the per-process order store, so both paths share the same shaping code.

Contract (docs/api/openapi.json, docs/api-contract.md):
  - ``GET /events/upcoming``: pages of persisted events, cancelled orders excluded,
    ordered by event start then order id. ``event_from`` is inclusive (default: now)
    and ``event_to`` exclusive; ``page`` >= 1 and ``page_size`` 1..100.
  - ``GET /orders/export``: UTF-8 CSV snapshot filtered by ``status`` and the event
    window. At most EXPORT_ROW_CAP rows; a larger result is 422 ``export_too_large``
    and is never truncated. Cells that could start a spreadsheet formula are neutralized.
  - ``GET /admin/dashboard/counts``: orders awaiting import into the booking workflow,
    bookings by status, bookings by payment status and upcoming confirmed bookings.
    Zero counts are always present for the known statuses.
"""

import csv
import io
import json
from datetime import datetime, timezone

import pymysql
from flask import Blueprint, Response, current_app, g, jsonify, request

from .auth.guards import require_admin
from .health import connection_options, database_configured
from .orders import (
    ORDER_STATUSES,
    _error,
    _field,
    _naive_utc,
    _query_instant,
    _query_integer,
    _service_unavailable,
)

reports_bp = Blueprint("reports", __name__)

COLUMNS = (
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
EXPORT_ROW_CAP = 10000
BOOKING_STATUSES = ("requested", "awaiting_deposit", "owner_review", "confirmed", "cancelled")
PAYMENT_STATUSES = ("unpaid", "partial", "deposit_paid", "paid")
_FORMULA_PREFIXES = ("=", "+", "-", "@")


class ExportTooLarge(Exception):
    """The filtered export has more than EXPORT_ROW_CAP rows."""


# --------------------------------------------------------------------------- #
# Shaping shared by the database and in-memory paths
# --------------------------------------------------------------------------- #


def _starts_at(order):
    return _naive_utc(datetime.fromisoformat(order["event"]["starts_at"]))


def upcoming_events(orders):
    """``UpcomingEvent`` items for already filtered and ordered order dictionaries."""
    return [
        {
            "order_id": order["id"],
            "order_status": order["status"],
            "event": order["event"],
            "quantity": order["catering_request"]["quantity"],
            "service_type": order["catering_request"]["service_type"],
        }
        for order in orders
    ]


def _neutralize(value):
    """Prefix text that a spreadsheet could read as a formula, even after leading whitespace."""
    if isinstance(value, str) and value:
        if value[0] in "\t\r" or value.lstrip()[:1] in _FORMULA_PREFIXES:
            return "'" + value
    return value


def export_rows(orders):
    """CSV rows (ordered as COLUMNS) for the orders; raises ExportTooLarge above the cap."""
    orders = list(orders)
    if len(orders) > EXPORT_ROW_CAP:
        raise ExportTooLarge
    return [
        (
            order["id"],
            order["status"],
            order["customer"]["name"],
            order["event"]["starts_at"],
            order["catering_request"]["quantity"],
            order["catering_request"]["service_type"],
            order["pricing"]["currency"],
            order["pricing"]["total_cents"],
            order["deposit"]["amount_due_cents"],
            order["deposit"]["status"],
        )
        for order in orders
    ]


def to_csv(rows):
    """UTF-8 CSV text with a header row; cells are quoted when needed and formula-neutralized."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(COLUMNS)
    for row in rows:
        writer.writerow([_neutralize(cell) for cell in row])
    return buffer.getvalue()


def _instant(text):
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return None
    return _naive_utc(parsed) if parsed.tzinfo else None


def dashboard_counts(awaiting_import, bookings, now):
    """Aggregate numbers; ``bookings`` holds ``(status, payment_status, start)`` tuples.

    ``now`` is a naive UTC datetime. A booking is upcoming when it is confirmed and starts
    at or after ``now``.
    """
    by_status = dict.fromkeys(BOOKING_STATUSES, 0)
    by_payment = dict.fromkeys(PAYMENT_STATUSES, 0)
    upcoming = 0
    for status, payment_status, start in bookings:
        by_status[status] = by_status.get(status, 0) + 1
        by_payment[payment_status] = by_payment.get(payment_status, 0) + 1
        starts_at = _instant(start) if status == "confirmed" else None
        if starts_at is not None and starts_at >= now:
            upcoming += 1
    return {
        "orders_awaiting_import": awaiting_import,
        "bookings_by_status": by_status,
        "payments_by_status": by_payment,
        "upcoming_confirmed_bookings": upcoming,
    }


# --------------------------------------------------------------------------- #
# Database path
# --------------------------------------------------------------------------- #


def _where(status, event_from, event_to, exclude_cancelled=False):
    """Parameterized WHERE clause; ``event_to`` is exclusive."""
    clauses, params = [], []
    if exclude_cancelled:
        clauses.append("status <> %s")
        params.append("cancelled")
    if status is not None:
        clauses.append("status = %s")
        params.append(status)
    if event_from is not None:
        clauses.append("event_starts_at >= %s")
        params.append(event_from)
    if event_to is not None:
        clauses.append("event_starts_at < %s")
        params.append(event_to)
    return (" WHERE " + " AND ".join(clauses) if clauses else ""), tuple(params)


def _connect():
    return pymysql.connect(**connection_options(current_app.config))


def _upcoming_in_database(event_from, event_to, page, page_size):
    where, params = _where(None, event_from, event_to, exclude_cancelled=True)
    connection = _connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM orders" + where, params)
            total = cursor.fetchone()[0]
            cursor.execute(
                "SELECT response_json FROM orders"
                + where
                + " ORDER BY event_starts_at ASC, public_id ASC LIMIT %s OFFSET %s",
                params + (page_size, (page - 1) * page_size),
            )
            rows = cursor.fetchall()
        return [json.loads(row[0]) for row in rows], total
    finally:
        connection.close()


def _export_in_database(status, event_from, event_to):
    where, params = _where(status, event_from, event_to)
    connection = _connect()
    try:
        with connection.cursor() as cursor:
            # One extra row is enough to detect an over-cap export without loading it all.
            cursor.execute(
                "SELECT response_json FROM orders" + where + " ORDER BY id ASC LIMIT %s",
                params + (EXPORT_ROW_CAP + 1,),
            )
            rows = cursor.fetchall()
        return [json.loads(row[0]) for row in rows]
    finally:
        connection.close()


def _dashboard_in_database(now):
    connection = _connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM orders o "
                "LEFT JOIN automation_order_links l ON l.order_id = o.public_id "
                "WHERE o.status = 'pending_review' AND l.order_id IS NULL"
            )
            awaiting = cursor.fetchone()[0]
            cursor.execute(
                "SELECT status, JSON_UNQUOTE(JSON_EXTRACT(data, '$.payment_status')), start_at "
                "FROM automation_bookings"
            )
            bookings = cursor.fetchall()
        return dashboard_counts(awaiting, bookings, now)
    finally:
        connection.close()


# --------------------------------------------------------------------------- #
# In-memory fallback: same filters and order as the SQL above
# --------------------------------------------------------------------------- #


def _memory_orders():
    store = current_app.extensions["orders_memory"]
    with store["lock"]:
        return list(store["by_id"].values())


def _in_window(order, status, event_from, event_to):
    starts_at = _starts_at(order)
    return (
        (status is None or order["status"] == status)
        and (event_from is None or starts_at >= event_from)
        and (event_to is None or starts_at < event_to)
    )


def _upcoming_in_memory(event_from, event_to, page, page_size):
    matches = [
        order
        for order in _memory_orders()
        if order["status"] != "cancelled" and _in_window(order, None, event_from, event_to)
    ]
    matches.sort(key=lambda order: (_starts_at(order), order["id"]))
    offset = (page - 1) * page_size
    return matches[offset : offset + page_size], len(matches)


def _export_in_memory(status, event_from, event_to):
    return [order for order in _memory_orders() if _in_window(order, status, event_from, event_to)][
        : EXPORT_ROW_CAP + 1
    ]


def _dashboard_in_memory(now):
    pending = [order["id"] for order in _memory_orders() if order["status"] == "pending_review"]
    store = current_app.extensions.get("automation_store")
    if store is None:
        return dashboard_counts(len(pending), [], now)
    with store.transaction() as tx:
        awaiting = sum(1 for order_id in pending if not tx.get_order_link(order_id))
        bookings = [(b["status"], b["payment_status"], b["start"]) for b in tx.list_bookings()]
    return dashboard_counts(awaiting, bookings, now)


# --------------------------------------------------------------------------- #
# HTTP layer
# --------------------------------------------------------------------------- #


def _now():
    return _naive_utc(datetime.now(timezone.utc))


def _event_window(errors):
    event_from = _query_instant(errors, "event_from")
    event_to = _query_instant(errors, "event_to")
    if event_from is not None and event_to is not None and event_to <= event_from:
        errors.append(_field("event_to", "must be after event_from"))
    return event_from, event_to


def _invalid(errors):
    return _error(422, "validation_error", "One or more fields are invalid.", errors)


@reports_bp.get("/events/upcoming")
@require_admin("bookings:read")
def retrieve_upcoming_events():
    errors = []
    event_from, event_to = _event_window(errors)
    page = _query_integer(errors, "page", 1, 1, 2**31 - 1)
    page_size = _query_integer(errors, "page_size", 25, 1, 100)
    if errors:
        return _invalid(errors)
    if event_from is None:
        event_from = _now()

    find = _upcoming_in_database if database_configured(current_app.config) else _upcoming_in_memory
    try:
        orders, total = find(event_from, event_to, page, page_size)
    except (pymysql.MySQLError, OSError):
        return _service_unavailable()
    return jsonify(
        data=upcoming_events(orders),
        meta={"page": page, "page_size": page_size, "total": total, "request_id": g.request_id},
    )


@reports_bp.get("/orders/export")
@require_admin("bookings:read")
def export_orders():
    errors = []
    status = request.args.get("status")
    if status is not None and status not in ORDER_STATUSES:
        errors.append(_field("status", "must be one of: " + ", ".join(ORDER_STATUSES)))
    if request.args.get("format", "csv") != "csv":
        errors.append(_field("format", "must be csv"))
    event_from, event_to = _event_window(errors)
    if errors:
        return _invalid(errors)

    find = _export_in_database if database_configured(current_app.config) else _export_in_memory
    try:
        rows = export_rows(find(status, event_from, event_to))
    except ExportTooLarge:
        return _error(422, "export_too_large", "Narrow the filters before exporting.")
    except (pymysql.MySQLError, OSError):
        return _service_unavailable()
    return Response(
        to_csv(rows),
        mimetype="text/csv",  # Werkzeug appends "; charset=utf-8" for text types
        headers={"Content-Disposition": 'attachment; filename="orders_export.csv"'},
    )


@reports_bp.get("/admin/dashboard/counts")
@require_admin("bookings:read")
def retrieve_dashboard_counts():
    count = (
        _dashboard_in_database if database_configured(current_app.config) else _dashboard_in_memory
    )
    try:
        data = count(_now())
    except (pymysql.MySQLError, OSError):
        return _service_unavailable()
    return jsonify(data=data, meta={"request_id": g.request_id})
