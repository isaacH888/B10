"""Browser-only OAuth initiation, callback, session bootstrap, and logout."""

from urllib.parse import urlencode

from flask import Blueprint, current_app, g, jsonify, redirect, request

from ..traffic import RequestBudget
from .errors import AuthError
from .guards import service
from .settings import cookie_name, mfa_cookie_name, native_cookie_name
from .store import StoreUnavailable


auth = Blueprint("auth", __name__)


@auth.record_once
def configure_admission(state):
    state.app.extensions["auth_ingress"] = RequestBudget(per_address=60, total=300)
    state.app.extensions["auth_denial_audits"] = RequestBudget(per_address=4, total=40)


def admit_unauthenticated_request():
    # Reject before parsing, persistent counters, or denial audits. Shared proxy
    # limits complement this bound when several application workers are running.
    if not current_app.extensions["auth_ingress"].allow(request.remote_addr):
        raise AuthError("rate_limited", "Too many sign-in attempts. Please wait a minute.", 429)


def audit_denial(event, detail):
    # Preserve a bounded sample of denied requests, never one DB insert per flood
    # request. Successful sign-ins and operator changes retain their full audits.
    if not current_app.extensions["auth_denial_audits"].allow(request.remote_addr):
        return
    try:
        current_app.extensions["auth_store"].audit(event, request_id=g.request_id, detail=detail)
    except StoreUnavailable:
        current_app.logger.warning("Authentication denial audit unavailable; request_id=%s", g.request_id)


def cookie_options():
    return {"httponly": True, "secure": current_app.config["APP_ENV"] != "development", "samesite": "Lax", "path": "/"}


def response(data):
    return jsonify(data=data, meta={"request_id": g.request_id})


def area_allowed(area):
    if area not in {"customer", "admin"}:
        raise AuthError("not_found", "The requested resource was not found.", 404)


@auth.post("/<area>/login")
def login(area):
    area_allowed(area)
    manager = service()
    manager.check_origin(request)
    if not request.is_json or (request.content_length or 0) > 2048:
        raise AuthError("validation_error", "Send a small JSON login request.", 422)
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise AuthError("validation_error", "Send a JSON login request.", 422)
    expected = {"provider"}
    provider = payload.get("provider", "password")
    methods = {"password"} if area == "admin" else {"password", "google"}
    if set(payload) - expected or not isinstance(provider, str) or provider not in methods:
        raise AuthError("validation_error", "Choose a supported login method.", 422)
    try:
        url, binding = manager.start_login(area, provider, request.remote_addr,
                                          request.cookies.get(cookie_name(current_app.config, area, flow=True)))
    except AuthError as error:
        if error.code != "login_expired":
            raise
        result = jsonify(error={"code": error.code, "message": error.message,
                                "fields": [], "request_id": g.request_id})
        result.status_code = error.status
        result.delete_cookie(cookie_name(current_app.config, area, flow=True), **cookie_options())
        return result
    result = response({"authorization_url": url})
    result.set_cookie(cookie_name(current_app.config, area, flow=True), binding, max_age=600, **cookie_options())
    return result


@auth.get("/<area>/callback")
def callback(area):
    area_allowed(area)
    admit_unauthenticated_request()
    landing = "/admin/login" if area == "admin" else "/login"
    try:
        if request.args.get("error") or any(len(request.args.getlist(key)) != 1 for key in ("state", "code")):
            raise AuthError("authentication_failed", "Sign-in could not be completed. Please start again.")
        token = service().finish_login(area, request.args.get("state"),
                                       request.cookies.get(cookie_name(current_app.config, area, flow=True)),
                                       request.args.get("code"), request.remote_addr,
                                       request.cookies.get(cookie_name(current_app.config, area)))
        result = redirect(current_app.config["AUTH_ORIGIN"] + ("/admin" if area == "admin" else "/account"), code=303)
        result.set_cookie(cookie_name(current_app.config, area), token,
                          max_age=current_app.config[f"{area.upper()}_SESSION_SECONDS"], **cookie_options())
        if area == "admin":
            result.delete_cookie(mfa_cookie_name(current_app.config), **cookie_options())
    except (AuthError, StoreUnavailable) as error:
        code = error.code if isinstance(error, AuthError) else "authentication_unavailable"
        reason = getattr(error, "reason", None)
        detail = {"area": area, "error_code": code}
        if reason:
            detail["reason"] = reason
        diagnostics = getattr(error, "diagnostics", None)
        if isinstance(diagnostics, dict):
            # Keep only boolean claim-presence facts; never retain token claims.
            for field in ("id_acr_present", "id_amr_present", "access_acr_present",
                          "access_amr_present", "access_totp_assured"):
                if type(diagnostics.get(field)) is bool:
                    detail[field] = diagnostics[field]
        audit_denial("login_denied", detail)
        result = redirect(current_app.config["AUTH_ORIGIN"] + landing + "?" + urlencode({"error": code}), code=303)
        current_app.logger.info("Authentication callback denied; code=%s; reason=%s; request_id=%s", code, reason, g.request_id)
    # Retain the private binding until its TTL so overlapping callbacks share
    # one logout cancellation context. State and codes remain single-use.
    return result


@auth.get("/<area>/session")
def read_session(area):
    area_allowed(area)
    manager = service()
    # Background bootstrap/poll requests do not extend the user's idle timeout.
    session = manager.authenticate(area, request)
    return response(manager.session_data(area, session))


@auth.delete("/<area>/session")
def logout(area):
    area_allowed(area)
    result = response({"logout_url": service().logout(area, request)})
    result.delete_cookie(cookie_name(current_app.config, area), **cookie_options())
    result.delete_cookie(cookie_name(current_app.config, area, flow=True), **cookie_options())
    if area == "admin":
        result.delete_cookie(mfa_cookie_name(current_app.config), **cookie_options())
        result.delete_cookie(native_cookie_name(current_app.config), **dict(cookie_options(), samesite="Strict"))
    return result


@auth.route("/admin/password/transaction", methods=["GET", "POST", "DELETE"])
def native_admin_transaction():
    admit_unauthenticated_request()
    manager = service()
    options = dict(cookie_options(), samesite="Strict")
    try:
        if request.method == "GET":
            data, credential, binding = manager.native_transaction(request, request_id=g.request_id)
            token = None
        elif request.method == "DELETE":
            data = manager.native_cancel(request)
            credential = binding = token = None
        else:
            manager.check_origin(request)
            if not request.is_json or (request.content_length or 0) > 4096:
                raise AuthError("validation_error", "Send a small JSON sign-in request.", 422)
            data, credential, binding, token = manager.native_submit(request, request.get_json(silent=True), request_id=g.request_id)
        result = response(data)
        if binding:
            result.set_cookie(cookie_name(current_app.config, "admin", flow=True), binding, max_age=600, **cookie_options())
        else:
            result.delete_cookie(cookie_name(current_app.config, "admin", flow=True), **cookie_options())
        if credential:
            result.set_cookie(native_cookie_name(current_app.config), credential, max_age=300, **options)
        else:
            result.delete_cookie(native_cookie_name(current_app.config), **options)
        if token:
            result.set_cookie(cookie_name(current_app.config, "admin"), token,
                              max_age=current_app.config["ADMIN_SESSION_SECONDS"], **cookie_options())
            result.delete_cookie(mfa_cookie_name(current_app.config), **cookie_options())
        return result
    except (AuthError, StoreUnavailable) as failure:
        error = failure if isinstance(failure, AuthError) else AuthError(
            "authentication_unavailable", "Sign-in is temporarily unavailable.", 503)
        audit_denial("admin_native_login_denied", {"area": "admin", "error_code": error.code})
        result = jsonify(error={"code": error.code, "message": error.message, "fields": [], "request_id": g.request_id})
        result.status_code = error.status
        if error.status == 429:
            result.headers["Retry-After"] = "60"
        result.delete_cookie(native_cookie_name(current_app.config), **options)
        if error.code == "login_expired":
            result.delete_cookie(cookie_name(current_app.config, "admin", flow=True), **cookie_options())
        return result
