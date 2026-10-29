"""Shared environment validation; feature configuration remains with its owner."""

import os
from urllib.parse import urlsplit

from .auth.settings import environment_settings


def read_settings():
    environment = os.getenv("APP_ENV", "development")
    if environment not in {"development", "staging", "production"}:
        raise ValueError("APP_ENV must be development, staging, or production")

    default_origin = "http://localhost:5173" if environment == "development" else ""
    origins = [
        value.strip()
        for value in os.getenv("CORS_ALLOWED_ORIGINS", default_origin).split(",")
        if value.strip()
    ]
    if not origins:
        raise ValueError("CORS_ALLOWED_ORIGINS is required")
    for origin in origins:
        parsed = urlsplit(origin)
        allowed_schemes = {"http", "https"} if environment == "development" else {"https"}
        if (
            parsed.scheme not in allowed_schemes
            or not parsed.hostname
            or "*" in origin
            or parsed.username
            or parsed.password
            or parsed.path
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("CORS_ALLOWED_ORIGINS must contain exact allowed origins")

    settings = {
        "APP_ENV": environment,
        "SECRET_KEY": os.getenv("APP_SECRET_KEY", ""),
        "CORS_ORIGINS": origins,
        "DB_HOST": os.getenv("DB_HOST", "localhost"),
        "DB_PORT": int(os.getenv("DB_PORT", "3306")),
        "DB_NAME": os.getenv("DB_NAME", "popssibilities_dev"),
        "DB_USER": os.getenv("DB_USER", ""),
        "DB_PASSWORD": os.getenv("DB_PASSWORD", ""),
        "DB_TLS_CA_FILE": os.getenv("DB_TLS_CA_FILE", ""),
        "LOG_LEVEL": os.getenv("LOG_LEVEL", "INFO").upper(),
    }
    if not 1 <= settings["DB_PORT"] <= 65535:
        raise ValueError("DB_PORT must be between 1 and 65535")
    if settings["LOG_LEVEL"] not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        raise ValueError("LOG_LEVEL is invalid")
    if environment != "development":
        required = ["SECRET_KEY", "DB_HOST", "DB_NAME", "DB_USER", "DB_PASSWORD", "DB_TLS_CA_FILE"]
        if any(not settings[key] for key in required):
            raise ValueError(
                "Hosted environments require application and TLS database configuration"
            )
    settings.update(environment_settings(environment))
    from .email.settings import environment_settings as email_settings

    settings.update(email_settings())
    return settings
