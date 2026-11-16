"""Opt-in private Square hosted Checkout settings."""

import os
import re
from urllib.parse import urlsplit

API_VERSION = "2026-09-16"


def environment_settings():
    enabled = os.getenv("SQUARE_ENABLED", "false").lower()
    if enabled not in {"true", "false"}:
        raise ValueError("SQUARE_ENABLED must be true or false")
    return {
        "SQUARE_ENABLED": enabled == "true",
        "SQUARE_ENVIRONMENT": os.getenv("SQUARE_ENVIRONMENT", "sandbox"),
        **{
            key: os.getenv(key, "")
            for key in (
                "SQUARE_ACCESS_TOKEN",
                "SQUARE_LOCATION_ID",
                "SQUARE_MERCHANT_ID",
                "SQUARE_WEBHOOK_SIGNATURE_KEY",
                "SQUARE_WEBHOOK_NOTIFICATION_URL",
            )
        },
    }


def validate_settings(settings):
    if not settings.get("SQUARE_ENABLED"):
        return
    if settings.get("SQUARE_ENVIRONMENT") not in {"sandbox", "production"}:
        raise ValueError("SQUARE_ENVIRONMENT must be sandbox or production")
    if not settings.get("AUTOMATION_ENABLED"):
        raise ValueError("Square requires booking automation")
    for key in ("SQUARE_ACCESS_TOKEN", "SQUARE_WEBHOOK_SIGNATURE_KEY"):
        value = settings.get(key, "")
        if not value or value != value.strip() or any(c.isspace() for c in value):
            raise ValueError(key + " is required and cannot contain whitespace")
    for key in ("SQUARE_LOCATION_ID", "SQUARE_MERCHANT_ID"):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", settings.get(key, "")):
            raise ValueError(key + " is required")
    try:
        url = urlsplit(settings.get("SQUARE_WEBHOOK_NOTIFICATION_URL", ""))
        port = url.port
    except ValueError:
        raise ValueError(
            "Square requires its exact public HTTPS webhook notification URL"
        ) from None
    if (
        url.scheme != "https"
        or not url.hostname
        or url.username
        or url.password
        or url.query
        or url.fragment
        or port not in {None, 443}
        or not url.path.endswith("/api/v1/payments/square/webhook")
    ):
        raise ValueError("Square requires its exact public HTTPS webhook notification URL")
    origin = urlsplit(settings.get("AUTH_ORIGIN", ""))
    if (
        origin.scheme not in {"http", "https"}
        or not origin.hostname
        or origin.username
        or origin.password
        or origin.path
        or origin.query
        or origin.fragment
        or (origin.scheme == "http" and origin.hostname not in {"localhost", "127.0.0.1"})
    ):
        raise ValueError("Square requires the canonical customer AUTH_ORIGIN")
