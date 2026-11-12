"""Saved-data dashboard and timezone-aware Calendar feed, independent of Google availability."""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pymysql
from flask import Blueprint, current_app, g, jsonify, request

from . import database
from .admin_orders import (
    BOOKING_EVENT_SQL,
    JOIN,
    STATUS_SQL,
    _decode,
    _memory,
    _memory_page,
    _owner,
    _sql_page,
    _unavailable,
    timestamp,
)
from .auth.errors import AuthError
from .auth.guards import require_admin
from .health import database_configured

overview = Blueprint("admin_overview", __name__)
MAX_EVENTS = 10000


def event_view(order, booking):
    event, catering, pricing = (
        (order[key] for key in ("event", "catering_request", "pricing")) if order else ({}, {}, {})
    )
    status = booking["status"] if booking else order["status"]
    status = "pending" if status in {"pending_review", "requested"} else status
    location = event.get("location", {})
    return {
        "id": booking["id"] if booking else order["id"],
        "reference": booking["reference"] if booking else order["id"],
        "order_id": order["id"] if order else None,
        "booking_id": booking["id"] if booking else None,
        "customer": order["customer"]["name"] if order else booking["customer_email"],
        "email": order["customer"]["email"] if order else booking["customer_email"],
        "phone": order["customer"]["phone"] if order else None,
        "start": booking["start"] if booking else event["starts_at"],
        "end": booking["end"] if booking else event.get("ends_at"),
        "timezone": booking["timezone"] if booking else event["timezone"],
        "venue": booking["venue"]
        if booking
        else ", ".join(
            location[key]
            for key in ("line1", "line2", "city", "region", "postal_code", "country_code")
            if location.get(key)
        ),
        "service_type": booking["service_type"] if booking else catering["service_type"],
        "quantity": booking["quantity"] if booking else catering["quantity"],
        "status": status,
        "calendar_status": booking["calendar_status"] if booking else "not_linked",
        "currency": booking["currency"] if booking else pricing["currency"],
        "total_cents": booking["total_minor"] if booking else pricing["total_cents"],
        "paid_cents": booking["paid_minor"] if booking else 0,
        "remaining_cents": booking["remaining_minor"] if booking else pricing["total_cents"],
    }


def manual_bookings():
    if database_configured(current_app.config):
        with database.connect(current_app.config) as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT b.data FROM automation_bookings b LEFT JOIN automation_order_links l ON l.booking_id=b.id WHERE l.booking_id IS NULL"
            )
            return [_decode(row["data"]) for row in cursor.fetchall()]
    store = current_app.extensions.get("automation_store")
    if not store:
        return []
    with store.transaction() as tx:
        return [booking for booking in tx.list_bookings() if not booking.get("source_order_id")]


def events_between(start, end, confirmed_only=False):
    query = dict(
        q="",
        status="confirmed" if confirmed_only else "",
        payment_status="",
        service_type="",
        page=1,
        page_size=MAX_EVENTS,
        event_from=start,
        event_to=end,
        exclude_cancelled=True,
    )
    persistent = database_configured(current_app.config)
    records, total = _sql_page(query) if persistent else _memory_page(query)
    if total > MAX_EVENTS:
        raise AuthError(
            "window_too_large", "Narrow the event window to at most 10,000 customer orders.", 422
        )
    events = [
        event_view(record["order"], record["booking"])
        for record in records
        if (record["booking"] or record["order"])["status"] != "cancelled"
    ]
    # Manual bookings are not duplicated as source orders, and always link to their booking.
    if persistent:
        with database.connect(current_app.config) as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT b.data FROM automation_bookings b LEFT JOIN automation_order_links l ON l.booking_id=b.id WHERE l.booking_id IS NULL AND "
                + ("b.status='confirmed'" if confirmed_only else "b.status<>'cancelled'")
                + " AND "
                + BOOKING_EVENT_SQL
                + ">=%s AND "
                + BOOKING_EVENT_SQL
                + "<%s ORDER BY b.start_at,b.id LIMIT %s",
                (start.replace(tzinfo=None), end.replace(tzinfo=None), MAX_EVENTS + 1),
            )
            manual = [_decode(row["data"]) for row in cursor.fetchall()]
    else:
        manual = [
            booking
            for booking in manual_bookings()
            if booking["status"] != "cancelled"
            and (not confirmed_only or booking["status"] == "confirmed")
            and start <= timestamp(booking["start"]) < end
        ]
    events.extend(event_view(None, booking) for booking in manual)
    if len(events) > MAX_EVENTS:
        raise AuthError(
            "window_too_large", "Narrow the event window to at most 10,000 events.", 422
        )
    return sorted(events, key=lambda event: (timestamp(event["start"]), event["id"]))


def aggregate():
    counts, balances = {}, {}
    if database_configured(current_app.config):
        with database.connect(current_app.config) as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT "
                + STATUS_SQL
                + " AS status,COALESCE(JSON_UNQUOTE(JSON_EXTRACT(b.data,'$.currency')),JSON_UNQUOTE(JSON_EXTRACT(o.response_json,'$.pricing.currency'))) AS currency,COUNT(*) AS count,SUM(COALESCE(CAST(JSON_EXTRACT(b.data,'$.remaining_minor') AS UNSIGNED),o.total_cents)) AS remaining"
                + JOIN
                + " GROUP BY 1,2"
            )
            groups = list(cursor.fetchall())
            cursor.execute(
                "SELECT b.status,JSON_UNQUOTE(JSON_EXTRACT(b.data,'$.currency')) AS currency,COUNT(*) AS count,SUM(CAST(JSON_EXTRACT(b.data,'$.remaining_minor') AS UNSIGNED)) AS remaining FROM automation_bookings b LEFT JOIN automation_order_links l ON l.booking_id=b.id WHERE l.booking_id IS NULL GROUP BY 1,2"
            )
            groups.extend(cursor.fetchall())
    else:
        groups = []
        for record in _memory():
            event = event_view(record["order"], record["booking"])
            groups.append(
                {
                    "status": event["status"],
                    "currency": event["currency"],
                    "count": 1,
                    "remaining": event["remaining_cents"],
                }
            )
        groups.extend(
            {
                "status": booking["status"],
                "currency": booking["currency"],
                "count": 1,
                "remaining": booking["remaining_minor"],
            }
            for booking in manual_bookings()
        )
    for group in groups:
        state = "pending" if group["status"] in {"requested", "pending_review"} else group["status"]
        counts[state] = counts.get(state, 0) + group["count"]
        if state == "confirmed":
            balances[group["currency"]] = balances.get(group["currency"], 0) + int(
                group["remaining"]
            )
    return counts, [
        {"currency": code, "remaining_cents": amount} for code, amount in sorted(balances.items())
    ]


@overview.get("/admin/calendar")
@require_admin("bookings:read")
def calendar():
    _owner()
    if set(request.args) - {"year", "month", "timezone"} or any(
        len(request.args.getlist(k)) != 1 for k in request.args
    ):
        raise AuthError(
            "validation_error", "Use non-repeated year, month and timezone parameters.", 422
        )
    try:
        year, month = int(request.args.get("year", "0")), int(request.args.get("month", "0"))
        if not 2000 <= year <= 2200 or not 1 <= month <= 12:
            raise ValueError
        zone = ZoneInfo(request.args.get("timezone", "America/Chicago"))
        start = datetime(year, month, 1, tzinfo=zone).astimezone(timezone.utc)
        end = datetime(year + (month == 12), month % 12 + 1, 1, tzinfo=zone).astimezone(
            timezone.utc
        )
    except (ValueError, ZoneInfoNotFoundError):
        raise AuthError(
            "validation_error", "Use a valid year, month and IANA timezone.", 422
        ) from None
    try:
        events = events_between(start, end)
    except (pymysql.MySQLError, OSError, ValueError):
        return _unavailable()
    return jsonify(
        data={
            "events": events,
            "timezone": str(zone),
            "stats": {
                "confirmed": sum(event["status"] == "confirmed" for event in events),
                "pending": sum(
                    event["status"] in {"pending", "awaiting_deposit", "owner_review"}
                    for event in events
                ),
                "confirmed_quantity": sum(
                    event["quantity"] for event in events if event["status"] == "confirmed"
                ),
            },
        },
        meta={"request_id": g.request_id},
    )


@overview.get("/admin/dashboard")
@require_admin("bookings:read")
def dashboard():
    _owner()
    if request.args:
        raise AuthError("validation_error", "Dashboard does not accept query parameters.", 422)
    now = current_app.config.get("ADMIN_CLOCK", lambda: datetime.now(timezone.utc))()
    query = dict(q="", status="", payment_status="", service_type="", page=1, page_size=5)
    persistent = database_configured(current_app.config)
    try:
        counts, balances = aggregate()
        recent, _ = _sql_page(query) if persistent else _memory_page(query)
        upcoming = [
            event
            for event in events_between(now, now + timedelta(days=30), confirmed_only=True)
            if event["status"] == "confirmed"
        ]
        low, reserved = None, None
        if persistent:
            from .inventory import ITEMS, item_view

            with database.connect(current_app.config) as connection, connection.cursor() as cursor:
                cursor.execute(ITEMS + " WHERE i.active=1")
                items = [item_view(row) for row in cursor.fetchall()]
                low = sum(item["available"] < item["minimum"] for item in items)
                reserved = sum(item["reserved"] for item in items)
    except (pymysql.MySQLError, OSError, ValueError):
        return _unavailable()
    return jsonify(
        data={
            "requests": counts.get("pending", 0),
            "awaiting_deposit": counts.get("awaiting_deposit", 0),
            "owner_review": counts.get("owner_review", 0),
            "balances": balances,
            "low_stock": low,
            "reserved_units": reserved,
            "upcoming_count": len(upcoming),
            "upcoming_quantity": sum(event["quantity"] for event in upcoming),
            "upcoming": upcoming[:3],
            "window_end": (now + timedelta(days=30)).isoformat(),
            "recent_orders": recent,
            "storage": "database" if persistent else "memory",
        },
        meta={"request_id": g.request_id},
    )
