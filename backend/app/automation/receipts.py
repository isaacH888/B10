"""Customer acknowledgments for new, successfully saved catering requests."""

from copy import deepcopy
from datetime import datetime
from hashlib import sha256
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def receipt_job(order):
    # A separate identity keeps this job independent of later booking/Calendar jobs.
    identifier = sha256(("customer-receipt:" + order["id"]).encode()).hexdigest()[:32]
    return {
        "key": f"request_received:{identifier}",
        "kind": "request_received",
        "booking_id": identifier,
        "revision": 1,
        "payload": {
            "order_id": order["id"],
            "customer": deepcopy(order["customer"]),
            "event": deepcopy(order["event"]),
            "service_type": order["catering_request"]["service_type"],
            "quantity": order["catering_request"]["quantity"],
        },
    }


def send_receipt(mail, job):
    payload = job["payload"]
    customer, event = payload["customer"], payload["event"]
    start = datetime.fromisoformat(event["starts_at"].replace("Z", "+00:00"))
    try:
        start = start.astimezone(ZoneInfo(event["timezone"]))
        timezone_name = event["timezone"]
    except ZoneInfoNotFoundError:
        # The intake API also accepts unrecognized IANA-shaped names. Preserve
        # the explicit timestamp offset rather than giving a misleading label.
        timezone_name = f"UTC offset {start.strftime('%z')}"
    location = ", ".join(
        event["location"][key]
        for key in ("line1", "line2", "city", "region", "postal_code")
        if event["location"].get(key)
    )
    service = "Full service" if payload["service_type"] == "full_service" else "Delivery"
    body = (
        f"Hi {customer['name']},\n\n"
        "Thank you for choosing Popssibilities! We've received your catering request.\n\n"
        f"Request reference: {payload['order_id']}\n"
        f"Event: {event['type']}\n"
        f"Date and time: {start.strftime('%B %d, %Y at %I:%M %p')} ({timezone_name})\n"
        f"Location: {location}\n"
        f"Service: {service}\n"
        f"Paletas requested: {payload['quantity']}\n\n"
        "Our team will review availability and your event details. Your booking is awaiting "
        "review and is not confirmed yet. No payment is due at this stage.\n\n"
        "Once your request is approved, we'll email you a deposit payment link. "
        "That link opens our website and takes you to Square's secure checkout.\n\n"
        "Thank you,\nThe Popssibilities team\n"
    )
    return mail.send(
        customer["email"],
        "Catering Request Received",
        body,
        job.get("mail_idempotency_key", job["key"]),
    )
