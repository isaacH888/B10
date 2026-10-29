"""Infrastructure probes only; this module does not own domain queries or schema."""

from threading import Lock
from time import monotonic

import pymysql
from flask import Blueprint, current_app, g, jsonify

from .auth.store import StoreUnavailable

health = Blueprint("health", __name__)


class ReadinessCache:
    """Allow one probe per worker every five seconds without queuing callers."""

    def __init__(self, *, seconds=5, clock=monotonic):
        self.seconds, self.clock = seconds, clock
        self._cached = None
        self._probing = Lock()

    def read(self, probe):
        cached = self._cached
        if cached and self.clock() < cached[0]:
            return cached[1]
        if not self._probing.acquire(blocking=False):
            # Never serve an expired success or tie up workers waiting for SQL.
            return None
        try:
            cached = self._cached
            if cached and self.clock() < cached[0]:
                return cached[1]
            data = probe()
            self._cached = (self.clock() + self.seconds, data)
            return data
        finally:
            self._probing.release()


@health.record_once
def configure_readiness(state):
    state.app.extensions["readiness_cache"] = ReadinessCache()


def database_configured(config):
    return bool(config["DB_USER"] and config["DB_PASSWORD"])


def connection_options(config):
    options = {
        "host": config["DB_HOST"],
        "port": config["DB_PORT"],
        "user": config["DB_USER"],
        "password": config["DB_PASSWORD"],
        "database": config["DB_NAME"],
        "connect_timeout": 3,
        "read_timeout": 3,
        "write_timeout": 3,
    }
    if config["DB_TLS_CA_FILE"]:
        options.update(
            ssl_ca=config["DB_TLS_CA_FILE"], ssl_verify_cert=True, ssl_verify_identity=True
        )
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


def probe_readiness():
    available = database_available()
    authentication_ready = not current_app.config["AUTH_ENABLED"]
    if available and current_app.config["AUTH_ENABLED"]:
        try:
            authentication_ready = current_app.extensions["auth_store"].ready()
        except StoreUnavailable:
            authentication_ready = False
    return available, authentication_ready


@health.get("/health")
def readiness():
    cached = current_app.extensions["readiness_cache"].read(probe_readiness)
    available, authentication_ready = cached or (False, False)
    ready = available and authentication_ready
    # Cache only probe facts: each response gets its own request identifier and
    # still carries no-store, including failures and concurrent cold probes.
    return jsonify(
        data={
            "status": "ok" if ready else "degraded",
            "database": "ok" if available else "unavailable",
            "authentication": "ready"
            if current_app.config["AUTH_ENABLED"] and authentication_ready
            else "disabled"
            if not current_app.config["AUTH_ENABLED"]
            else "unavailable",
        },
        meta={"request_id": g.request_id},
    ), 200 if ready else 503
