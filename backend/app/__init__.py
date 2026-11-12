"""Application factory shared by the component owners."""

import time
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from flask import Flask, g, jsonify
from flask_cors import CORS
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

from .auth.errors import AuthError, unavailable
from .auth.settings import authentication_enabled, validate_settings
from .auth.store import Store, StoreUnavailable
from .config import read_settings
from .health import health
from .orders import orders_bp
from .quotes import quotes_bp
from .reports import reports_bp


def create_app(test_config=None):
    if test_config is None:
        # Load backend settings only; frontend builds must never receive this file.
        load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
    app = Flask(__name__)
    app.config.from_mapping(read_settings())
    if test_config:
        app.config.update(test_config)
    validate_settings(app.config)
    from .email.settings import validate_settings as validate_email_settings

    validate_email_settings(app.config)
    if app.config["AUTH_TRUSTED_PROXY_HOPS"]:
        app.wsgi_app = ProxyFix(
            app.wsgi_app,
            x_for=app.config["AUTH_TRUSTED_PROXY_HOPS"],
            x_proto=0,
            x_host=0,
            x_port=0,
            x_prefix=0,
        )
    app.config["MAX_CONTENT_LENGTH"] = 65536
    app.logger.setLevel(app.config["LOG_LEVEL"])
    from .auth.logging import redact_development_access_logs

    redact_development_access_logs()
    CORS(
        app,
        resources={r"/api/v1/.*": {"origins": app.config["CORS_ORIGINS"]}},
        supports_credentials=True,
        allow_headers=["Content-Type", "Idempotency-Key", "X-CSRF-Token"],
        methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    )
    app.register_blueprint(health, url_prefix="/api/v1")
    from .auth.admin_cli import register_admin_commands
    from .auth.routes import auth

    app.extensions["auth_store"] = app.config.get("AUTH_STORE") or Store(app.config)
    if authentication_enabled(app.config):
        from .auth.provider import CognitoProvider
        from .auth.service import AuthService

        configured_providers = app.config.get("AUTH_PROVIDERS")
        providers = {
            area: configured_providers[area]
            if configured_providers
            else CognitoProvider(app.config, area)
            for area in ("customer", "admin")
            if authentication_enabled(app.config, area)
        }
        app.extensions["auth_service"] = AuthService(
            app.config, app.extensions["auth_store"], providers, clock=app.config.get("AUTH_CLOCK")
        )
    app.register_blueprint(auth, url_prefix="/api/v1")
    register_admin_commands(app)
    from .automation.domain import BookingService, DomainError
    from .automation.google import GoogleFailure
    from .automation.routes import automation
    from .automation.store import Store as AutomationStore
    from .automation.store import StoreUnavailable as AutomationUnavailable
    from .email.provider import SESMailer

    app.register_blueprint(automation, url_prefix="/api/v1/admin/automation")
    if app.config.get("AUTOMATION_ENABLED"):
        automation_store = app.config.get("AUTOMATION_STORE") or AutomationStore(app.config)
        app.extensions["automation_store"] = automation_store
        app.extensions["booking_service"] = app.config.get("BOOKING_SERVICE") or BookingService(
            automation_store,
            clock=app.config.get("AUTOMATION_CLOCK") or time.time,
            capacity=app.config.get("AUTOMATION_CAPACITY", 1000),
            reservation_seconds=app.config.get("AUTOMATION_RESERVATION_SECONDS", 172800),
        )
        if app.config.get("AUTOMATION_SERVICES") is not None:
            services = app.config["AUTOMATION_SERVICES"]
        else:
            from .automation.runtime import build_services

            services = build_services(app.config, automation_store)
        app.extensions.update(services)
        app.extensions["automation_services"] = services
    from .email.routes import email
    from .email.service import CustomerMailService
    from .email.store import MailStore

    if authentication_enabled(app.config, "customer"):
        app.extensions["customer_mail_service"] = CustomerMailService(
            app.config,
            app.extensions["auth_service"],
            app.config.get("EMAIL_STORE") or MailStore(app.config),
            app.config.get("EMAIL_MAILER") or SESMailer(app.config),
        )
    app.register_blueprint(email, url_prefix="/api/v1")
    app.register_blueprint(quotes_bp, url_prefix="/api/v1")
    app.register_blueprint(orders_bp, url_prefix="/api/v1")
    app.register_blueprint(reports_bp, url_prefix="/api/v1")
    from .admin_orders import admin_orders

    app.register_blueprint(admin_orders, url_prefix="/api/v1")
    from .inventory import inventory

    app.register_blueprint(inventory, url_prefix="/api/v1")
    from .admin_overview import overview

    app.register_blueprint(overview, url_prefix="/api/v1")

    @app.before_request
    def assign_request_id():
        g.request_id = uuid4().hex

    @app.after_request
    def set_response_headers(response):
        response.headers["X-Request-ID"] = g.request_id
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
        if app.config["APP_ENV"] != "development":
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    @app.errorhandler(AuthError)
    def handle_auth_error(error):
        result = jsonify(
            error={
                "code": error.code,
                "message": error.message,
                "fields": [],
                "request_id": g.request_id,
            }
        )
        if error.status == 429:
            result.headers["Retry-After"] = "60"
        return result, error.status

    @app.errorhandler(StoreUnavailable)
    def handle_auth_store_error(error):
        app.logger.warning("Authentication persistence unavailable; request_id=%s", g.request_id)
        return handle_auth_error(unavailable())

    @app.errorhandler(DomainError)
    def handle_booking_error(error):
        return handle_auth_error(AuthError(error.code, str(error), error.status))

    @app.errorhandler(AutomationUnavailable)
    def handle_automation_store_error(error):
        return handle_auth_error(
            AuthError("automation_unavailable", "Booking storage is temporarily unavailable.", 503)
        )

    @app.errorhandler(GoogleFailure)
    def handle_google_error(error):
        status = 503 if error.category == "transient" else 409
        return handle_auth_error(AuthError("google_" + error.category, error.message, status))

    @app.errorhandler(HTTPException)
    def handle_http_error(error):
        codes = {404: "not_found", 405: "method_not_allowed"}
        response = error.get_response()
        response.data = app.json.dumps(
            {
                "error": {
                    "code": codes.get(error.code, "request_error"),
                    "message": error.description,
                    "fields": [],
                    "request_id": g.request_id,
                }
            }
        )
        response.content_type = "application/json"
        return response

    @app.errorhandler(Exception)
    def handle_unexpected_error(error):
        app.logger.error("Unhandled request failure; request_id=%s", g.request_id)
        return jsonify(
            error={
                "code": "internal_error",
                "message": "The request could not be completed.",
                "fields": [],
                "request_id": g.request_id,
            }
        ), 500

    return app
