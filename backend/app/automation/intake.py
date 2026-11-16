"""Lossless, owner-reviewed handoff from customer orders to booking automation.

Delivery requests may omit an event end; customer requests do not supply a contract URL.
The owner supplies these before confirming availability. Plain imports do not approve
capacity or payment. Decision imports atomically save the owner review and email intent.
"""

import hashlib
import json
from contextlib import contextmanager
from copy import deepcopy
from datetime import timedelta

from flask import current_app

from ..health import database_configured
from .domain import DomainError, instant


@contextmanager
def intake_transaction(capacity=False):
    store = current_app.extensions["automation_store"]
    if database_configured(current_app.config):
        with store.transaction(capacity=capacity) as tx:
            yield tx, None
    else:
        # Keep a source status change from racing an in-memory import.
        orders = current_app.extensions["orders_memory"]
        with orders["lock"], store.transaction(capacity=capacity) as tx:
            yield tx, orders["by_id"]


def pending_orders():
    with intake_transaction() as (tx, memory):
        if memory is None:
            with tx.connection.cursor() as cursor:
                cursor.execute(
                    "SELECT o.response_json FROM orders o "
                    "LEFT JOIN automation_order_links l ON l.order_id=o.public_id "
                    "WHERE o.status='pending_review' AND l.order_id IS NULL "
                    "ORDER BY o.id DESC LIMIT 100"
                )
                return [json.loads(row["response_json"]) for row in cursor.fetchall()]
        return deepcopy(
            [
                order
                for order in reversed(list(memory.values()))
                if order["status"] == "pending_review" and not tx.get_order_link(order["id"])
            ][:100]
        )


def import_order(order_id, payload, actor, *, decision=False):
    from .requests import request_id

    allowed = {"end", "contract_url"} | (
        {"decision", "message", "expected_version"} if decision else set()
    )
    if set(payload) - allowed:
        raise DomainError(
            "Use supported review fields only; customer details and prices come from the saved order"
            if decision
            else "Only end and contract_url may be supplied; customer details and prices come from the saved order"
        )
    notifications = current_app.extensions.get("request_notifications")
    if notifications:
        # A fast owner handoff can precede the next scheduled dispatcher tick.
        # Capture this committed request before linking it to a booking.
        notifications.reconcile(order_id=order_id)
    store = current_app.extensions["automation_store"]
    with (
        store.booking_lock(request_id(order_id)),
        intake_transaction(capacity=decision) as (tx, memory),
    ):
        if memory is None:
            with tx.connection.cursor() as cursor:
                cursor.execute(
                    "SELECT response_json FROM orders WHERE public_id=%s FOR UPDATE", (order_id,)
                )
                row = cursor.fetchone()
                order = json.loads(row["response_json"]) if row else None
        else:
            order = deepcopy(memory.get(order_id))
        if order is None:
            raise DomainError("Customer order was not found", 404, "not_found")
        if decision and (
            type(payload.get("expected_version")) is not int
            or payload["expected_version"] != order["version"]
        ):
            raise DomainError("Order changed; reload before reviewing it", 409, "revision_conflict")
        supplement = {
            "end": payload.get("end") or order["event"].get("ends_at"),
            "contract_url": payload.get("contract_url"),
        }
        digest = hashlib.sha256(json.dumps(supplement, sort_keys=True).encode()).hexdigest()
        link = tx.get_order_link(order_id)
        if link:
            if decision:
                raise DomainError(
                    "This order has entered the booking workflow. Reload before reviewing it.",
                    409,
                    "order_already_linked",
                )
            if link["request_hash"] != digest:
                raise DomainError(
                    "This order already has a booking. Open that booking to make changes.",
                    409,
                    "order_already_linked",
                )
            return tx.get_booking(link["booking_id"]), False
        if order["status"] != "pending_review":
            raise DomainError(
                "Only a pending customer order can enter the booking workflow",
                409,
                "invalid_transition",
            )
        event, catering, pricing = order["event"], order["catering_request"], order["pricing"]
        location = event["location"]
        venue = ", ".join(
            location[key]
            for key in ("line1", "line2", "city", "region", "postal_code", "country_code")
            if location.get(key)
        )
        body = {
            "start": event["starts_at"],
            "end": supplement["end"],
            "timezone": event["timezone"],
            # The full address remains in source_order; the existing Calendar
            # venue field is a bounded display summary.
            "venue": venue[:500],
            "quantity": catering["quantity"],
            "service_type": catering["service_type"],
            "customer_email": order["customer"]["email"],
            "total_minor": pricing["total_cents"],
            "currency": pricing["currency"],
            "contract_url": supplement["contract_url"],
        }
        missing_end = not body["end"]
        if decision and payload.get("decision") != "confirm" and missing_end:
            body["end"] = (instant(event["starts_at"]) + timedelta(hours=1)).isoformat()
        routing = tx.get_connection("company-request-calendar")
        projection = tx.get_request(request_id(order_id)) if routing else None
        booking = current_app.extensions["booking_service"].create_in_transaction(
            tx,
            body,
            actor,
            source_order=order,
            calendar_projection=projection,
            review_only=decision and payload.get("decision") != "confirm",
            deny_past_request=decision and payload.get("decision") == "deny",
        )
        if decision:
            booking["end_unspecified"] = missing_end
            service = current_app.extensions["booking_service"]
            booking = service.decide_in_transaction(tx, booking, payload, actor, service._now())
        tx.save_order_link(
            {"order_id": order_id, "booking_id": booking["id"], "request_hash": digest}
        )
        return booking, True
