"""Reusable server-side authorization for future business routes."""

from functools import wraps

from flask import current_app, g, request

from .errors import unavailable
from .settings import authentication_enabled


def service(area):
    if not authentication_enabled(current_app.config, area):
        raise unavailable()
    return current_app.extensions["auth_service"]


def require_admin(permission="bookings:read", fresh=False):
    def decorate(view):
        @wraps(view)
        def protected(*args, **kwargs):
            g.principal = service("admin").authenticate(
                "admin",
                request,
                touch=True,
                csrf=request.method not in {"GET", "HEAD", "OPTIONS"},
                permission=permission,
                fresh=fresh,
            )
            return view(*args, **kwargs)

        return protected

    return decorate


def require_customer(view):
    @wraps(view)
    def protected(*args, **kwargs):
        g.principal = service("customer").authenticate(
            "customer", request, touch=True, csrf=request.method not in {"GET", "HEAD", "OPTIONS"}
        )
        return view(*args, **kwargs)

    return protected
