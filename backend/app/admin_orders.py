"""Owner order reads combining saved intake with the current linked booking.

These routes never approve availability, verify payments or change an order.
Those actions continue through the existing versioned booking workflow.
"""

import csv
import io
import json
import re
from copy import deepcopy
from datetime import datetime, timezone

import pymysql
from flask import Blueprint, Response, current_app, g, jsonify, request

from . import database
from .auth.errors import AuthError
from .auth.guards import require_admin
from .health import database_configured

admin_orders = Blueprint("admin_orders", __name__)
STATUSES = ("pending", "awaiting_deposit", "confirmed", "owner_review", "fulfilled", "cancelled")
JOIN = (
    " FROM orders o LEFT JOIN automation_order_links l ON l.order_id=o.public_id"
    " LEFT JOIN automation_bookings b ON b.id=l.booking_id"
)
STATUS_SQL = "CASE WHEN COALESCE(b.status,o.status) IN ('requested','pending_review') THEN 'pending' ELSE COALESCE(b.status,o.status) END"
PAID_SQL = "COALESCE(CAST(JSON_EXTRACT(b.data,'$.paid_minor') AS UNSIGNED),0)"
TOTAL_SQL = "COALESCE(CAST(JSON_EXTRACT(b.data,'$.total_minor') AS UNSIGNED),o.total_cents)"
SERVICE_SQL = "COALESCE(JSON_UNQUOTE(JSON_EXTRACT(b.data,'$.service_type')),JSON_UNQUOTE(JSON_EXTRACT(o.response_json,'$.catering_request.service_type')))"
BOOKING_EVENT_SQL = "CAST(SUBSTRING_INDEX(REPLACE(b.start_at,'T',' '),'+',1) AS DATETIME(6))"
EVENT_SQL = f"COALESCE({BOOKING_EVENT_SQL},o.event_starts_at)"


def timestamp(value):
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None:
            raise ValueError
        return result.astimezone(timezone.utc)
    except (ValueError, TypeError, AttributeError, OverflowError):
        raise AuthError(
            "validation_error", "Use timestamps with an explicit UTC offset.", 422
        ) from None


def _owner():
    if g.principal.get("admin_role") != "owner":
        raise AuthError("forbidden", "Only the owner can access this order workspace.", 403)


def _query():
    allowed = {
        "q",
        "status",
        "payment_status",
        "service_type",
        "page",
        "page_size",
        "event_from",
        "event_to",
    }
    if set(request.args) - allowed or any(len(request.args.getlist(k)) != 1 for k in request.args):
        raise AuthError("validation_error", "Use supported, non-repeated order filters.", 422)
    values = {key: request.args.get(key, "").strip() for key in allowed}
    try:
        page = int(values["page"] or "1")
        size = int(values["page_size"] or "25")
        if not (1 <= page <= 1000000 and 1 <= size <= 100):
            raise ValueError
    except ValueError:
        raise AuthError(
            "validation_error", "Use page >= 1 and page_size between 1 and 100.", 422
        ) from None
    choices = {
        "status": STATUSES,
        "payment_status": ("unpaid", "partial", "paid"),
        "service_type": ("delivery", "full_service"),
    }
    if len(values["q"]) > 150 or any(values[k] and values[k] not in v for k, v in choices.items()):
        raise AuthError("validation_error", "One or more order filters are invalid.", 422)
    bounds = {
        key: timestamp(values[key]) if values[key] else None for key in ("event_from", "event_to")
    }
    if bounds["event_from"] and bounds["event_to"] and bounds["event_to"] <= bounds["event_from"]:
        raise AuthError("validation_error", "The event range end must follow its start.", 422)
    return {**values, **bounds, "page": page, "page_size": size}


def _decode(value):
    return json.loads(value) if isinstance(value, (str, bytes)) else value


def _record(order, booking=None):
    summary = None
    if booking:
        summary = {
            key: booking[key]
            for key in (
                "id",
                "reference",
                "status",
                "revision",
                "start",
                "end",
                "timezone",
                "venue",
                "service_type",
                "quantity",
                "currency",
                "total_minor",
                "deposit_minor",
                "paid_minor",
                "remaining_minor",
                "overpaid_minor",
                "payment_status",
                "calendar_status",
            )
        }
    return {"order": {**order, "admin_notes": order.get("admin_notes", "")}, "booking": summary}


def _status(record):
    value = (record["booking"] or record["order"])["status"]
    return "pending" if value in {"requested", "pending_review"} else value


def _payment(record):
    booking = record["booking"]
    paid = booking["paid_minor"] if booking else 0
    total = booking["total_minor"] if booking else record["order"]["pricing"]["total_cents"]
    return "unpaid" if paid == 0 else "paid" if paid >= total else "partial"


def _memory(order_id=None):
    store = current_app.extensions["orders_memory"]
    automation = current_app.extensions.get("automation_store")
    # Match intake's lock order so a handoff cannot race a source read.
    with store["lock"]:
        orders = deepcopy(list(store["by_id"].values()))
        if order_id is not None:
            orders = [order for order in orders if order["id"] == order_id]
        if not automation:
            return [_record(order) for order in reversed(orders)]
        with automation.transaction() as tx:
            records = []
            for order in reversed(orders):
                link = tx.get_order_link(order["id"])
                booking = tx.get_booking(link["booking_id"]) if link else None
                records.append(_record(order, booking))
            return records


def _memory_page(query):
    records = []
    for record in _memory():
        order, booking = record["order"], record["booking"]
        if query.get("exclude_cancelled") and _status(record) == "cancelled":
            continue
        if query["q"].casefold() not in (order["customer"]["name"] + " " + order["id"]).casefold():
            continue
        if query["status"] and _status(record) != query["status"]:
            continue
        if query["payment_status"] and _payment(record) != query["payment_status"]:
            continue
        service = booking["service_type"] if booking else order["catering_request"]["service_type"]
        if query["service_type"] and service != query["service_type"]:
            continue
        start = timestamp(booking["start"] if booking else order["event"]["starts_at"])
        if query.get("event_from") and start < query["event_from"]:
            continue
        if query.get("event_to") and start >= query["event_to"]:
            continue
        records.append(record)
    offset = (query["page"] - 1) * query["page_size"]
    return records[offset : offset + query["page_size"]], len(records)


def _sql_page(query):
    clauses, parameters = [], []
    if query.get("exclude_cancelled"):
        clauses.append(STATUS_SQL + "<>'cancelled'")
    if query["q"]:
        pattern = (
            "%" + query["q"].lower().replace("!", "!!").replace("%", "!%").replace("_", "!_") + "%"
        )
        clauses.append(
            "(LOWER(JSON_UNQUOTE(JSON_EXTRACT(o.response_json,'$.customer.name'))) LIKE %s ESCAPE '!' OR LOWER(o.public_id) LIKE %s ESCAPE '!')"
        )
        parameters.extend((pattern, pattern))
    if query["status"]:
        clauses.append(STATUS_SQL + "=%s")
        parameters.append(query["status"])
    if query["payment_status"]:
        clauses.append(
            {
                "unpaid": PAID_SQL + "=0",
                "partial": f"({PAID_SQL}>0 AND {PAID_SQL}<{TOTAL_SQL})",
                "paid": f"({PAID_SQL}>0 AND {PAID_SQL}>={TOTAL_SQL})",
            }[query["payment_status"]]
        )
    if query["service_type"]:
        clauses.append(SERVICE_SQL + "=%s")
        parameters.append(query["service_type"])
    for key, operator in (("event_from", ">="), ("event_to", "<")):
        if query.get(key):
            clauses.append(EVENT_SQL + operator + "%s")
            parameters.append(query[key].replace(tzinfo=None))
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    with database.connect(current_app.config) as connection, connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) AS total" + JOIN + where, parameters)
        total = cursor.fetchone()["total"]
        cursor.execute(
            "SELECT o.response_json,b.data AS booking_json"
            + JOIN
            + where
            + " ORDER BY o.id DESC LIMIT %s OFFSET %s",
            [*parameters, query["page_size"], (query["page"] - 1) * query["page_size"]],
        )
        records = [
            _record(_decode(row["response_json"]), _decode(row["booking_json"]))
            for row in cursor.fetchall()
        ]
    return records, total


def _unavailable():
    current_app.logger.error("Admin order read failed; request_id=%s", g.request_id)
    raise AuthError(
        "service_unavailable", "Orders are temporarily unavailable. Please try again.", 503
    )


@admin_orders.get("/admin/orders")
@require_admin("bookings:read")
def list_orders():
    _owner()
    query = _query()
    persistent = database_configured(current_app.config)
    try:
        records, total = _sql_page(query) if persistent else _memory_page(query)
    except (pymysql.MySQLError, OSError, ValueError):
        return _unavailable()
    return jsonify(
        data={
            "items": records,
            "total": total,
            "page": query["page"],
            "page_size": query["page_size"],
            "storage": "database" if persistent else "memory",
        },
        meta={"request_id": g.request_id},
    )


@admin_orders.get("/admin/orders/<order_id>")
@require_admin("bookings:read")
def read_order(order_id):
    _owner()
    if request.args:
        raise AuthError("validation_error", "Order detail does not accept query parameters.", 422)
    return jsonify(data=find_record(order_id), meta={"request_id": g.request_id})


def find_record(order_id):
    from .orders import _valid_order_id

    if not _valid_order_id(order_id):
        raise AuthError("not_found", "Order not found.", 404)
    try:
        if database_configured(current_app.config):
            with database.connect(current_app.config) as connection, connection.cursor() as cursor:
                cursor.execute(
                    "SELECT o.response_json,b.data AS booking_json"
                    + JOIN
                    + " WHERE o.public_id=%s",
                    (order_id,),
                )
                row = cursor.fetchone()
                record = (
                    _record(_decode(row["response_json"]), _decode(row["booking_json"]))
                    if row
                    else None
                )
        else:
            records = _memory(order_id)
            record = records[0] if records else None
    except (pymysql.MySQLError, OSError, ValueError):
        return _unavailable()
    if record is None:
        raise AuthError("not_found", "Order not found.", 404)
    return record


def csv_response(records, filename):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(
        (
            "order_id",
            "status",
            "customer_name",
            "customer_email",
            "customer_phone",
            "event_starts_at",
            "event_timezone",
            "quantity",
            "service_type",
            "currency",
            "total_cents",
            "deposit_due_cents",
            "verified_cents",
            "remaining_cents",
        )
    )
    for record in records:
        order, booking = record["order"], record["booking"]
        values = [
            order["id"],
            _status(record),
            order["customer"]["name"],
            order["customer"]["email"],
            order["customer"]["phone"],
            booking["start"] if booking else order["event"]["starts_at"],
            booking["timezone"] if booking else order["event"]["timezone"],
            booking["quantity"] if booking else order["catering_request"]["quantity"],
            booking["service_type"] if booking else order["catering_request"]["service_type"],
            booking["currency"] if booking else order["pricing"]["currency"],
            booking["total_minor"] if booking else order["pricing"]["total_cents"],
            booking["deposit_minor"] if booking else order["pricing"]["deposit_due_cents"],
            booking["paid_minor"] if booking else 0,
            booking["remaining_minor"] if booking else order["pricing"]["total_cents"],
        ]
        writer.writerow(
            [
                "'" + value
                if isinstance(value, str) and re.match(r"^[\s]*[=+@-]", value)
                else value
                for value in values
            ]
        )
    return Response(
        stream.getvalue(),
        content_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


@admin_orders.get("/admin/orders/export")
@require_admin("customers:export", fresh=True)
def export_orders():
    _owner()
    query = {**_query(), "page": 1, "page_size": 10000}
    try:
        records, total = (
            _sql_page(query) if database_configured(current_app.config) else _memory_page(query)
        )
    except (pymysql.MySQLError, OSError, ValueError):
        return _unavailable()
    if total > 10000:
        raise AuthError(
            "export_too_large", "Narrow the filters to export at most 10,000 orders.", 422
        )
    return csv_response(records, "orders.csv")


@admin_orders.get("/admin/orders/<order_id>/export")
@require_admin("customers:export", fresh=True)
def export_order(order_id):
    _owner()
    if request.args:
        raise AuthError("validation_error", "Order export does not accept query parameters.", 422)
    return csv_response([find_record(order_id)], "order-summary.csv")
