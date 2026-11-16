"""Owner Checkout creation and a public signature-authenticated Square webhook."""

from flask import Blueprint, current_app, request

from ..automation.domain import DomainError
from ..automation.routes import actor, owner_only, payload, response

payments = Blueprint("payments", __name__)


def checkout():
    service = current_app.extensions.get("square_checkout")
    if not service:
        raise DomainError("Square Checkout is not configured yet.", 503, "square_unavailable")
    return service


@payments.get("/admin/automation/square")
@owner_only()
def square_status():
    return response(checkout().available())


@payments.post("/admin/automation/bookings/<booking_id>/checkout")
@owner_only(fresh=True)
def create_checkout(booking_id):
    body = payload()
    if (
        set(body) - {"purpose", "expected_revision"}
        or type(body.get("expected_revision")) is not int
    ):
        raise DomainError("Send purpose and the current expected_revision only.", 422)
    return response(
        checkout().create(
            booking_id,
            body.get("purpose"),
            expected_revision=body["expected_revision"],
            actor=actor(),
            email=True,
        )
    )


@payments.get("/payments/square/<checkout_id>")
def checkout_status(checkout_id):
    return response(checkout().public_status(checkout_id))


@payments.post("/payments/square/<checkout_id>/start")
def start_checkout(checkout_id):
    # The emailed, unguessable capability authorizes payment, not an account cookie.
    # Enforce the browser origin as well; never accept a browser amount or payment status.
    if request.headers.get("Origin") != current_app.config["AUTH_ORIGIN"]:
        raise DomainError(
            "Open the payment link on the Popssibilities website.", 403, "invalid_origin"
        )
    if payload():
        raise DomainError("This action does not accept payment details or amounts.", 422)
    return response(checkout().start(checkout_id))


@payments.post("/payments/square/webhook")
def square_webhook():
    # Authentication is the Square signature over the untouched raw bytes, never session cookies.
    checkout().webhook(
        request.get_data(cache=False), request.headers.get("X-Square-HmacSha256-Signature", "")
    )
    return response({"received": True})
