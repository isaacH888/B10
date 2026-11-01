"""Owner-only booking operations; all browser mutations use session CSRF checks."""

from functools import wraps

from flask import Blueprint, current_app, g, jsonify, redirect, request

from ..auth.errors import AuthError
from ..auth.guards import service


automation = Blueprint("automation", __name__)


def owner_only(fresh=False):
    def decorate(view):
        @wraps(view)
        def protected(*args, **kwargs):
            g.principal = service().authenticate(
                "admin", request, touch=True,
                csrf=request.method not in {"GET", "HEAD", "OPTIONS"}, fresh=fresh)
            if g.principal.get("admin_role") != "owner":
                raise AuthError("forbidden", "Only the owner can operate booking automation.", 403)
            if not current_app.config.get("AUTOMATION_ENABLED"):
                raise AuthError("automation_unavailable", "Booking automation is not configured.", 503)
            return view(*args, **kwargs)
        return protected
    return decorate


def response(data, status=200):
    return jsonify(data=data, meta={"request_id": g.request_id}), status


def payload():
    body = request.get_json(silent=True)
    if not request.is_json or not isinstance(body, dict):
        raise AuthError("validation_error", "Send a JSON object.", 422)
    return body


def actor():
    return g.principal["identity_id"]


def bookings():
    return current_app.extensions["booking_service"]


def oauth():
    return current_app.extensions["google_oauth"]


@automation.get("/google")
@owner_only()
def google_status():
    return response(oauth().status(actor()))


@automation.post("/google/connect")
@owner_only(fresh=True)
def google_connect():
    result = oauth().start(actor(), g.principal["token_hash"])
    return response(result if isinstance(result, dict) else {"authorization_url": result})


@automation.post("/google/disconnect")
@owner_only(fresh=True)
def google_disconnect():
    oauth().disconnect(actor())
    return response(oauth().status(actor()))


@automation.get("/google/callback")
@owner_only()
def google_callback():
    if request.args.get("error") or any(len(request.args.getlist(key)) != 1 for key in ("state", "code")):
        raise AuthError("oauth_failed", "Google access was declined. Start the connection again.", 400)
    oauth().finish(request.args["state"], request.args["code"], actor(), g.principal["token_hash"])
    return redirect(current_app.config["AUTH_ORIGIN"] + "/admin/automation?calendar=connected", code=303)


@automation.get("/bookings")
@owner_only()
def list_bookings():
    with current_app.extensions["automation_store"].transaction() as tx:
        return response(tx.list_bookings())


@automation.get("/bookings/<booking_id>")
@owner_only()
def read_booking(booking_id):
    with current_app.extensions["automation_store"].transaction() as tx:
        booking = tx.get_booking(booking_id)
        if not booking:
            raise AuthError("not_found", "Booking not found.", 404)
        jobs = [dict(job, delivery=tx.get_delivery(job["key"])) for job in tx.list_outbox()
                if job["booking_id"] == booking_id]
        return response({"booking": booking, "payments": tx.payments(booking_id), "jobs": jobs})


@automation.post("/jobs/<path:job_key>/retry")
@owner_only(fresh=True)
def replay_job(job_key):
    current_app.extensions["processor"].replay(job_key, actor())
    return response({"queued": True})


@automation.post("/bookings")
@owner_only(fresh=True)
def create_booking():
    return response(bookings().create(payload(), actor()), 201)


@automation.post("/bookings/<booking_id>/approve")
@owner_only(fresh=True)
def approve_booking(booking_id):
    return response(bookings().approve(booking_id, payload(), actor()))


@automation.post("/bookings/<booking_id>/payments")
@owner_only(fresh=True)
def verify_payment(booking_id):
    return response(bookings().verify_payment(booking_id, payload(), actor()))


@automation.post("/bookings/<booking_id>/reschedule")
@owner_only(fresh=True)
def reschedule_booking(booking_id):
    return response(bookings().reschedule(booking_id, payload(), actor()))


@automation.post("/bookings/<booking_id>/cancel")
@owner_only(fresh=True)
def cancel_booking(booking_id):
    return response(bookings().cancel(booking_id, actor(), expected_revision=payload().get("expected_revision")))


@automation.post("/bookings/<booking_id>/reopen")
@owner_only(fresh=True)
def reopen_booking(booking_id):
    return response(bookings().reopen(booking_id, payload(), actor()))


@automation.post("/bookings/<booking_id>/final-count")
@owner_only(fresh=True)
def finalize_count(booking_id):
    return response(bookings().finalize_count(booking_id, payload(), actor()))


@automation.post("/bookings/<booking_id>/retry")
@owner_only(fresh=True)
def retry_booking(booking_id):
    return response(bookings().retry(booking_id, actor()))


@automation.post("/bookings/<booking_id>/repair")
@owner_only(fresh=True)
def repair_booking(booking_id):
    return response(bookings().retry(booking_id, actor(), repair=True))
