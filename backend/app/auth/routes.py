"""Browser-only OAuth initiation, callback, session bootstrap, and logout."""

from urllib.parse import urlencode

from flask import Blueprint, current_app, g, jsonify, redirect, request

from .errors import AuthError
from .guards import service
from .settings import cookie_name
from .store import StoreUnavailable


auth = Blueprint("auth", __name__)


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
    expected = {"provider"} if area == "customer" else set()
    provider = payload.get("provider", "password")
    if set(payload) - expected or not isinstance(provider, str) or provider not in {"password", "google"}:
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
    except (AuthError, StoreUnavailable) as error:
        code = error.code if isinstance(error, AuthError) else "authentication_unavailable"
        result = redirect(current_app.config["AUTH_ORIGIN"] + landing + "?" + urlencode({"error": code}), code=303)
        current_app.logger.info("Authentication callback denied; code=%s; request_id=%s", code, g.request_id)
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
    return result
