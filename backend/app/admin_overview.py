"""Saved-data dashboard and timezone-aware Calendar feed, independent of Google availability."""

import csv
import io
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pymysql
from flask import Blueprint, Response, current_app, g, jsonify, request

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
    _status,
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
                    event["status"]
                    in {"pending", "awaiting_deposit", "owner_review", "conditionally_confirmed"}
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


def _clean_cell(value):
    if value is None:
        return ""
    text = str(value)
    if re.match(r"^[\s]*[=+@-]", text):
        return "'" + text
    return text


def dashboard_report_csv():
    now = current_app.config.get("ADMIN_CLOCK", lambda: datetime.now(timezone.utc))()
    query = dict(q="", status="", payment_status="", service_type="", page=1, page_size=25)
    persistent = database_configured(current_app.config)
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

        try:
            with database.connect(current_app.config) as connection, connection.cursor() as cursor:
                cursor.execute(ITEMS + " WHERE i.active=1")
                items = [item_view(row) for row in cursor.fetchall()]
                low = sum(item["available"] < item["minimum"] for item in items)
                reserved = sum(item["reserved"] for item in items)
        except Exception:
            pass

    stream = io.StringIO()
    writer = csv.writer(stream)

    # Header / Title
    writer.writerow([_clean_cell("ADMIN DASHBOARD - GENERAL INFORMATION REPORT")])
    writer.writerow([_clean_cell("Generated At (UTC)"), _clean_cell(now.isoformat())])
    writer.writerow(
        [_clean_cell("Storage Mode"), _clean_cell("database" if persistent else "memory")]
    )
    writer.writerow([])

    # Section 1: KPI Metrics
    writer.writerow([_clean_cell("--- KEY OPERATIONAL METRICS ---")])
    writer.writerow([_clean_cell("Metric"), _clean_cell("Value"), _clean_cell("Notes")])
    writer.writerow(
        [
            _clean_cell("New Catering Requests"),
            _clean_cell(counts.get("pending", 0)),
            _clean_cell("Awaiting availability review"),
        ]
    )
    writer.writerow(
        [
            _clean_cell("Upcoming Confirmed Events"),
            _clean_cell(len(upcoming)),
            _clean_cell("Scheduled in next 30 days"),
        ]
    )
    writer.writerow(
        [
            _clean_cell("Upcoming Paletas Required"),
            _clean_cell(sum(event["quantity"] for event in upcoming)),
            _clean_cell("Total units for next 30 days"),
        ]
    )

    formatted_balances = "None"
    if balances:
        formatted_balances = " / ".join(
            f"{b['currency']} {b['remaining_cents']/100:.2f}" for b in balances
        )
    writer.writerow(
        [
            _clean_cell("Outstanding Balances"),
            _clean_cell(formatted_balances),
            _clean_cell("Remaining on confirmed bookings"),
        ]
    )
    writer.writerow(
        [
            _clean_cell("Awaiting Deposits"),
            _clean_cell(counts.get("awaiting_deposit", 0)),
            _clean_cell("Requests approved, deposit pending"),
        ]
    )
    writer.writerow(
        [
            _clean_cell("Bookings Needing Review"),
            _clean_cell(counts.get("owner_review", 0)),
            _clean_cell("Special attention required"),
        ]
    )
    writer.writerow(
        [
            _clean_cell("Low-Stock Flavor Items"),
            _clean_cell(low if low is not None else "N/A"),
            _clean_cell("Available below minimum threshold"),
        ]
    )
    writer.writerow(
        [
            _clean_cell("Reserved Flavor Units"),
            _clean_cell(reserved if reserved is not None else "N/A"),
            _clean_cell("Units allocated to bookings"),
        ]
    )
    writer.writerow([])

    # Section 2: Upcoming Confirmed Events
    writer.writerow([_clean_cell("--- UPCOMING CONFIRMED EVENTS (NEXT 30 DAYS) ---")])
    writer.writerow(
        [
            _clean_cell("Event / Ref ID"),
            _clean_cell("Customer"),
            _clean_cell("Email"),
            _clean_cell("Phone"),
            _clean_cell("Start Time"),
            _clean_cell("End Time"),
            _clean_cell("Timezone"),
            _clean_cell("Service Type"),
            _clean_cell("Quantity"),
            _clean_cell("Venue / Location"),
            _clean_cell("Status"),
            _clean_cell("Total Amount"),
            _clean_cell("Paid Amount"),
            _clean_cell("Remaining Balance"),
        ]
    )
    if not upcoming:
        writer.writerow(
            [_clean_cell("No upcoming confirmed events scheduled in the next 30 days.")]
        )
    else:
        for ev in upcoming:
            curr = ev.get("currency", "USD")
            total_str = f"{curr} {ev['total_cents']/100:.2f}" if "total_cents" in ev else ""
            paid_str = f"{curr} {ev['paid_cents']/100:.2f}" if "paid_cents" in ev else ""
            rem_str = f"{curr} {ev['remaining_cents']/100:.2f}" if "remaining_cents" in ev else ""
            writer.writerow(
                [
                    _clean_cell(ev.get("reference") or ev.get("id")),
                    _clean_cell(ev.get("customer")),
                    _clean_cell(ev.get("email")),
                    _clean_cell(ev.get("phone")),
                    _clean_cell(ev.get("start")),
                    _clean_cell(ev.get("end")),
                    _clean_cell(ev.get("timezone")),
                    _clean_cell(ev.get("service_type")),
                    _clean_cell(ev.get("quantity")),
                    _clean_cell(ev.get("venue")),
                    _clean_cell(ev.get("status")),
                    _clean_cell(total_str),
                    _clean_cell(paid_str),
                    _clean_cell(rem_str),
                ]
            )
    writer.writerow([])

    # Section 3: Recent Orders Snapshot
    writer.writerow([_clean_cell("--- RECENT ORDERS & CATERING REQUESTS ---")])
    writer.writerow(
        [
            _clean_cell("Order ID"),
            _clean_cell("Customer Name"),
            _clean_cell("Customer Email"),
            _clean_cell("Customer Phone"),
            _clean_cell("Event Date / Start"),
            _clean_cell("Service Type"),
            _clean_cell("Quantity"),
            _clean_cell("Order Status"),
            _clean_cell("Total Amount"),
            _clean_cell("Deposit Status"),
        ]
    )
    if not recent:
        writer.writerow([_clean_cell("No recent orders recorded.")])
    else:
        for rec in recent:
            order, booking = rec.get("order"), rec.get("booking")
            if not order:
                continue
            cust = order.get("customer", {})
            event = order.get("event", {})
            cat = order.get("catering_request", {})
            pricing = order.get("pricing", {})
            dep = order.get("deposit", {})
            status = _status(rec)
            start = booking.get("start") if booking else event.get("starts_at")
            curr = pricing.get("currency", "USD")
            total_amt = (
                f"{curr} {pricing.get('total_cents', 0)/100:.2f}" if "total_cents" in pricing else ""
            )
            writer.writerow(
                [
                    _clean_cell(order.get("id")),
                    _clean_cell(cust.get("name")),
                    _clean_cell(cust.get("email")),
                    _clean_cell(cust.get("phone")),
                    _clean_cell(start),
                    _clean_cell(booking.get("service_type") if booking else cat.get("service_type")),
                    _clean_cell(booking.get("quantity") if booking else cat.get("quantity")),
                    _clean_cell(status),
                    _clean_cell(total_amt),
                    _clean_cell(dep.get("status")),
                ]
            )

    return stream.getvalue()


@overview.get("/admin/dashboard/export")
@require_admin("bookings:read")
def export_dashboard():
    _owner()
    try:
        csv_data = dashboard_report_csv()
    except (pymysql.MySQLError, OSError, ValueError):
        return _unavailable()

    timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"admin_report_{timestamp_str}.csv"
    return Response(
        csv_data,
        content_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )
