"""Application factory shared by the component owners."""

from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from flask import Flask, g, jsonify
from flask_cors import CORS
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

from .config import read_settings
from .health import health
from .auth.errors import AuthError, unavailable
from .auth.settings import validate_settings
from .auth.store import Store, StoreUnavailable


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
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=app.config["AUTH_TRUSTED_PROXY_HOPS"],
                               x_proto=0, x_host=0, x_port=0, x_prefix=0)
    app.config["MAX_CONTENT_LENGTH"] = 65536
    app.logger.setLevel(app.config["LOG_LEVEL"])
    from .auth.logging import redact_development_access_logs
    redact_development_access_logs()
    CORS(app, resources={r"/api/v1/.*": {"origins": app.config["CORS_ORIGINS"]}},
         supports_credentials=True,
         allow_headers=["Content-Type", "Idempotency-Key", "X-CSRF-Token"],
         methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"])
    app.register_blueprint(health, url_prefix="/api/v1")
    from .auth.routes import auth
    from .auth.admin_cli import register_admin_commands
    app.extensions["auth_store"] = app.config.get("AUTH_STORE") or Store(app.config)
    if app.config["AUTH_ENABLED"]:
        from .auth.provider import CognitoProvider
        from .auth.service import AuthService
        providers = app.config.get("AUTH_PROVIDERS") or {
            area: CognitoProvider(app.config, area) for area in ("customer", "admin")}
        app.extensions["auth_service"] = AuthService(app.config, app.extensions["auth_store"], providers,
                                                     clock=app.config.get("AUTH_CLOCK"))
    app.register_blueprint(auth, url_prefix="/api/v1")
    register_admin_commands(app)
    from .email.routes import email
    from .email.service import CustomerMailService
    from .email.store import MailStore
    from .email.provider import SESMailer
    if app.config["AUTH_ENABLED"]:
        app.extensions["customer_mail_service"] = CustomerMailService(
            app.config, app.extensions["auth_service"],
            app.config.get("EMAIL_STORE") or MailStore(app.config),
            app.config.get("EMAIL_MAILER") or SESMailer(app.config),
        )
    app.register_blueprint(email, url_prefix="/api/v1")

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
        result = jsonify(error={"code": error.code, "message": error.message,
                                "fields": [], "request_id": g.request_id})
        if error.status == 429:
            result.headers["Retry-After"] = "60"
        return result, error.status

    @app.errorhandler(StoreUnavailable)
    def handle_auth_store_error(error):
        app.logger.warning("Authentication persistence unavailable; request_id=%s", g.request_id)
        return handle_auth_error(unavailable())

    @app.errorhandler(HTTPException)
    def handle_http_error(error):
        codes = {404: "not_found", 405: "method_not_allowed"}
        response = error.get_response()
        response.data = app.json.dumps({"error": {
            "code": codes.get(error.code, "request_error"), "message": error.description,
            "fields": [], "request_id": g.request_id}})
        response.content_type = "application/json"
        return response

    @app.errorhandler(Exception)
    def handle_unexpected_error(error):
        app.logger.error("Unhandled request failure; request_id=%s", g.request_id)
        return jsonify(error={"code": "internal_error", "message": "The request could not be completed.",
                              "fields": [], "request_id": g.request_id}), 500

    return app
