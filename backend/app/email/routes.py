"""One fixed confirmation message, sent only to the authenticated customer."""

from uuid import UUID

from flask import Blueprint, current_app, g, jsonify, request

from ..auth.errors import AuthError
from ..auth.guards import require_customer
from ..traffic import RequestBudget

email = Blueprint("customer_email", __name__)


@email.record_once
def configure_admission(state):
    state.app.extensions["email_ingress"] = RequestBudget(per_address=10, total=60)


@email.before_request
def admit_request():
    if not current_app.extensions["email_ingress"].allow(request.remote_addr):
        raise AuthError(
            "email_rate_limited", "Too many test email requests. Please wait a minute.", 429
        )


@email.post("/customer/test-email")
@require_customer
def customer_test_email():
    if (
        not request.is_json
        or (request.content_length or 0) > 1024
        or request.get_json(silent=True) != {}
    ):
        raise AuthError(
            "validation_error",
            "Send an empty JSON object; the customer and message are selected securely.",
            422,
        )
    key = request.headers.get("Idempotency-Key", "")
    try:
        parsed = UUID(key)
    except (ValueError, AttributeError):
        parsed = None
    if not parsed or parsed.version != 4 or str(parsed) != key:
        raise AuthError(
            "validation_error", "Supply a UUIDv4 Idempotency-Key for this test email.", 422
        )
    data = current_app.extensions["customer_mail_service"].send(g.principal, key)
    return jsonify(data=data, meta={"request_id": g.request_id})
