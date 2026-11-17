"""Owner Checkout creation and a public signature-authenticated Square webhook."""

from flask import Blueprint, current_app, g, request

from ..auth.guards import require_customer
from ..automation.domain import DomainError
from ..automation.routes import actor, owner_only, payload, response
from ..orders import customer_booking_id

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


@payments.post("/customer/orders/<order_id>/checkout")
@require_customer
def customer_deposit_checkout(order_id):
    body = payload()
    if (
        set(body) != {"expected_revision"}
        or type(body.get("expected_revision")) is not int
        or body["expected_revision"] < 1
    ):
        raise DomainError("Send the current expected_revision only.", 422)
    booking_id = customer_booking_id(order_id, g.principal["identity_id"])
    if booking_id is None:
        raise DomainError(
            "Your request must be approved before you can pay a deposit.", 409, "approval_required"
        )
    service = checkout()
    link = service.create(
        booking_id,
        "deposit",
        expected_revision=body["expected_revision"],
        actor="customer:" + g.principal["identity_id"],
    )
    # Reuse the existing checked handoff, including a second approval/amount/window
    # check if the owner changed the booking while Square created the link.
    return response(
        {
            **service.start(link["id"]),
            "environment": service.settings["SQUARE_ENVIRONMENT"],
        }
    )


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
