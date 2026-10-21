"""Application factory shared by the component owners."""

from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from flask import Flask, g, jsonify
from flask_cors import CORS
from werkzeug.exceptions import HTTPException

from .config import read_settings
from .health import health
from .quotes import quotes_bp


def create_app(test_config=None):
    if test_config is None:
        # Load backend settings only; frontend builds must never receive this file.
        load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
    app = Flask(__name__)
    app.config.from_mapping(read_settings())
    if test_config:
        app.config.update(test_config)
    app.logger.setLevel(app.config["LOG_LEVEL"])
    CORS(app, resources={r"/api/v1/.*": {"origins": app.config["CORS_ORIGINS"]}},
         supports_credentials=True,
         allow_headers=["Content-Type", "Idempotency-Key", "X-CSRF-Token"],
         methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"])
    app.register_blueprint(health, url_prefix="/api/v1")
    app.register_blueprint(quotes_bp, url_prefix="/api/v1")

    @app.before_request
    def assign_request_id():
        g.request_id = uuid4().hex

    @app.after_request
    def set_response_headers(response):
        response.headers["X-Request-ID"] = g.request_id
        response.headers["Cache-Control"] = "no-store"
        return response

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
