"""Infrastructure probes only; this module does not own domain queries or schema."""

import pymysql
from flask import Blueprint, current_app, g, jsonify
from .auth.store import StoreUnavailable

health = Blueprint("health", __name__)


def database_available():
    config = current_app.config
    if not config["DB_USER"] or not config["DB_PASSWORD"]:
        return False
    options = {
        "host": config["DB_HOST"], "port": config["DB_PORT"],
        "user": config["DB_USER"], "password": config["DB_PASSWORD"],
        "database": config["DB_NAME"], "connect_timeout": 3,
        "read_timeout": 3, "write_timeout": 3,
    }
    if config["DB_TLS_CA_FILE"]:
        options.update(ssl_ca=config["DB_TLS_CA_FILE"], ssl_verify_cert=True, ssl_verify_identity=True)
    try:
        with pymysql.connect(**options) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                return cursor.fetchone() == (1,)
    except (pymysql.MySQLError, OSError):
        # Driver messages can include private connection details.
        current_app.logger.warning("Database readiness probe failed; request_id=%s", g.request_id)
        return False


@health.get("/live")
def live():
    return jsonify(data={"status": "ok"}, meta={"request_id": g.request_id})


@health.get("/health")
def readiness():
    available = database_available()
    authentication_ready = not current_app.config["AUTH_ENABLED"]
    if available and current_app.config["AUTH_ENABLED"]:
        try:
            authentication_ready = current_app.extensions["auth_store"].ready()
        except StoreUnavailable:
            authentication_ready = False
    ready = available and authentication_ready
    return jsonify(
        data={"status": "ok" if ready else "degraded", "database": "ok" if available else "unavailable",
              "authentication": "ready" if current_app.config["AUTH_ENABLED"] and authentication_ready else
                                "disabled" if not current_app.config["AUTH_ENABLED"] else "unavailable"},
        meta={"request_id": g.request_id},
    ), 200 if ready else 503
