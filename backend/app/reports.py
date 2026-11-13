"""Admin reporting: ``retrieveUpcomingEvents``, ``exportOrders`` and dashboard counts.

All three routes require an administrator session with ``bookings:read``. With database
credentials configured they call the SQL in ``reports_queries``; otherwise an in-memory
fallback applies the same rules to the per-process order and automation stores.

Contract (docs/api/openapi.json, docs/api-contract.md):
  - ``GET /events/upcoming``: pages of persisted events, cancelled orders excluded,
    ordered by event start then order id. ``event_from`` is inclusive (default: now)
    and ``event_to`` exclusive; ``page`` >= 1 and ``page_size`` 1..100.
  - ``GET /orders/export``: UTF-8 CSV snapshot, newest first, filtered by ``status`` and
    the event window. At most EXPORT_ROW_CAP rows; a larger result is 422
    ``export_too_large`` and is never truncated. Cells that could start a spreadsheet
    formula are neutralized.
  - ``GET /admin/dashboard/counts``: orders awaiting import into the booking workflow,
    bookings by status, bookings by payment status and upcoming confirmed bookings.
    Zero counts are always present for the known statuses.

An order linked to a booking reports the booking's status, deposit status, schedule and
amounts instead of the snapshot frozen at import (see ``reports_queries``).
"""

import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pymysql
from flask import Blueprint, Response, current_app, g, jsonify, request

from . import reports_queries as queries
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
    booking_order_state,
    linked_bookings,
)

reports_bp = Blueprint("reports", __name__)

EXPORT_ROW_CAP = queries.EXPORT_CAP


# --------------------------------------------------------------------------- #
# Database path
# --------------------------------------------------------------------------- #


def _read_database(query, *args, **kwargs):
    """Run one ``reports_queries`` function on a fresh cursor and always close the connection."""
    connection = pymysql.connect(**connection_options(current_app.config))
    try:
        with connection.cursor() as cursor:
            return query(cursor, *args, **kwargs)
    finally:
        connection.close()


# --------------------------------------------------------------------------- #
# In-memory fallback: same rules as reports_queries
# --------------------------------------------------------------------------- #


def _instant(text):
    """Naive UTC value of an ISO 8601 text with an offset; None when absent or invalid."""
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return None
    return _naive_utc(parsed) if parsed.tzinfo else None


def _memory_orders():
    """``(order, booking)`` pairs, newest first; booking is None for an order never imported."""
    store = current_app.extensions["orders_memory"]
    with store["lock"]:
        newest_first = list(reversed(store["by_id"].values()))
    bookings = linked_bookings([order["id"] for order in newest_first])
    return [(order, bookings.get(order["id"])) for order in newest_first]


def _effective(order, booking):
    """``(status, deposit_status, event_start)``; the booking supplies them when imported."""
    if booking is None:
        status, deposit_status = order["status"], order["deposit"]["status"]
    else:
        status, deposit_status = booking_order_state(booking)
    start = _instant(booking.get("start")) if booking else None
    return (
        status,
        deposit_status,
        start or _naive_utc(datetime.fromisoformat(order["event"]["starts_at"])),
    )


def _current(order, booking):
    return queries._current_values(order, json.dumps(booking) if booking else None)


def _in_window(start, event_from, event_to):
    return (event_from is None or start >= event_from) and (event_to is None or start < event_to)


def _upcoming_in_memory(event_from, event_to, page, page_size):
    matches = []
    for order, booking in _memory_orders():
        status, _, start = _effective(order, booking)
        if status != "cancelled" and _in_window(start, event_from, event_to):
            matches.append((start, order, booking, status))
    matches.sort(key=lambda match: (match[0], match[1]["id"]))
    offset = (page - 1) * page_size
    items = []
    for _, order, booking, status in matches[offset : offset + page_size]:
        current = _current(order, booking)
        item = {
            "order_id": order["id"],
            "order_status": status,
            **{key: current[key] for key in ("event", "quantity", "service_type")},
        }
        if current["venue"] is not None:
            item["venue"] = current["venue"]
        items.append(item)
    return {"items": items, "page": page, "page_size": page_size, "total": len(matches)}


def _export_in_memory(status, event_from, event_to, cap):
    rows = []
    for order, booking in _memory_orders():
        order_status, deposit_status, start = _effective(order, booking)
        if (status is None or order_status == status) and _in_window(start, event_from, event_to):
            current = _current(order, booking)
            event = current["event"]
            local_start = (
                datetime.fromisoformat(event["starts_at"].replace("Z", "+00:00"))
                .astimezone(ZoneInfo(event["timezone"]))
                .isoformat()
            )
            rows.append(
                {
                    "order_id": order["id"],
                    "status": order_status,
                    "customer_name": order["customer"]["name"],
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
    if len(rows) > cap:
        raise queries.ExportTooLarge
    return rows


def _dashboard_in_memory(now):
    pending = [order["id"] for order, _ in _memory_orders() if order["status"] == "pending_review"]
    store = current_app.extensions.get("automation_store")
    bookings, imported = [], set()
    if store is not None:
        with store.transaction() as tx:
            imported = {order_id for order_id in pending if tx.get_order_link(order_id)}
            bookings = tx.list_bookings()

    by_status = dict.fromkeys(queries.BOOKING_STATUSES, 0)
    by_payment = dict.fromkeys(queries.PAYMENT_STATUSES, 0)
    upcoming = 0
    for booking in bookings:
        status = booking["status"]
        by_status[status] = by_status.get(status, 0) + 1
        # Cancelled bookings are left out of the payment counts, as in the SQL.
        if status != "cancelled":
            payment = booking.get("payment_status") or "unknown"
            by_payment[payment] = by_payment.get(payment, 0) + 1
        start = _instant(booking.get("start")) if status == "confirmed" else None
        if start is not None and start >= now:
            upcoming += 1
    return {
        "orders_awaiting_import": len(pending) - len(imported),
        "bookings_by_status": by_status,
        "payments_by_status": by_payment,
        "upcoming_confirmed_bookings": upcoming,
    }


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

    try:
        if database_configured(current_app.config):
            result = _read_database(
                queries.upcoming_events,
                event_from=event_from,
                event_to=event_to,
                page=page,
                page_size=page_size,
            )
        else:
            result = _upcoming_in_memory(event_from, event_to, page, page_size)
    except (pymysql.MySQLError, OSError):
        return _service_unavailable()
    return jsonify(
        data=result["items"],
        meta={
            "page": result["page"],
            "page_size": result["page_size"],
            "total": result["total"],
            "request_id": g.request_id,
        },
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

    try:
        if database_configured(current_app.config):
            rows = _read_database(
                queries.export_rows,
                status=status,
                event_from=event_from,
                event_to=event_to,
                cap=EXPORT_ROW_CAP,
            )
        else:
            rows = _export_in_memory(status, event_from, event_to, EXPORT_ROW_CAP)
    except queries.ExportTooLarge:
        return _error(422, "export_too_large", "Narrow the filters before exporting.")
    except (pymysql.MySQLError, OSError):
        return _service_unavailable()
    return Response(
        queries.to_csv(rows),
        mimetype="text/csv",  # Werkzeug appends "; charset=utf-8" for text types
        headers={"Content-Disposition": 'attachment; filename="orders_export.csv"'},
    )


@reports_bp.get("/admin/dashboard/counts")
@require_admin("bookings:read")
def retrieve_dashboard_counts():
    try:
        if database_configured(current_app.config):
            data = _read_database(queries.dashboard_counts, datetime.now(timezone.utc).isoformat())
        else:
            data = _dashboard_in_memory(_now())
    except (pymysql.MySQLError, OSError):
        return _service_unavailable()
    return jsonify(data=data, meta={"request_id": g.request_id})
