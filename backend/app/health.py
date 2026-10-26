"""Infrastructure probes only; this module does not own domain queries or schema."""

import pymysql
from flask import Blueprint, current_app, g, jsonify

health = Blueprint("health", __name__)


def database_configured(config):
    return bool(config["DB_USER"] and config["DB_PASSWORD"])


def connection_options(config):
    options = {
        "host": config["DB_HOST"], "port": config["DB_PORT"],
        "user": config["DB_USER"], "password": config["DB_PASSWORD"],
        "database": config["DB_NAME"], "connect_timeout": 3,
        "read_timeout": 3, "write_timeout": 3,
    }
    if config["DB_TLS_CA_FILE"]:
        options.update(ssl_ca=config["DB_TLS_CA_FILE"], ssl_verify_cert=True, ssl_verify_identity=True)
    return options


def database_available():
    config = current_app.config
    if not database_configured(config):
        return False
    try:
        with pymysql.connect(**connection_options(config)) as connection:
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
    return jsonify(
        data={"status": "ok" if available else "degraded", "database": "ok" if available else "unavailable"},
        meta={"request_id": g.request_id},
    ), 200 if available else 503
