"""Shared MySQL connection configuration, without schema changes at web startup."""

import pymysql
from pymysql.constants import CLIENT


def connect(settings, *, autocommit=False):
    """Open a bounded connection with verified TLS when configured."""
    if not settings.get("DB_USER") or not settings.get("DB_PASSWORD"):
        raise pymysql.OperationalError("Database credentials are not configured")
    options = {
        "host": settings["DB_HOST"],
        "port": settings["DB_PORT"],
        "user": settings["DB_USER"],
        "password": settings["DB_PASSWORD"],
        "database": settings["DB_NAME"],
        "charset": "utf8mb4",
        "cursorclass": pymysql.cursors.DictCursor,
        "client_flag": CLIENT.FOUND_ROWS,
        "connect_timeout": 5,
        "read_timeout": 10,
        "write_timeout": 10,
        "autocommit": autocommit,
    }
    if settings.get("DB_TLS_CA_FILE"):
        options.update(
            ssl_ca=settings["DB_TLS_CA_FILE"],
            ssl_verify_cert=True,
            ssl_verify_identity=True,
        )
    elif settings.get("APP_ENV", "development") != "development":
        raise pymysql.OperationalError("Hosted database connections require verified TLS")
    return pymysql.connect(**options)
