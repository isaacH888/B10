"""Authentication configuration with no development identity bypass."""

import os
import re
from urllib.parse import urlsplit

from cryptography.fernet import Fernet


ISSUER_PATTERN = re.compile(r"https://cognito-idp\.([a-z0-9-]+)\.amazonaws\.com/([A-Za-z0-9_-]+)\Z")


def environment_settings(environment):
    enabled = os.getenv("AUTH_ENABLED", "false" if environment == "development" else "true").lower()
    if enabled not in {"true", "false"}:
        raise ValueError("AUTH_ENABLED must be true or false")
    settings = {
        "AUTH_ENABLED": enabled == "true",
        "AUTH_ORIGIN": os.getenv("FRONTEND_ORIGIN", "http://localhost:5173" if environment == "development" else ""),
        "AUTH_TOKEN_ENCRYPTION_KEY": os.getenv("AUTH_TOKEN_ENCRYPTION_KEY", ""),
        "AUTH_TRUSTED_PROXY_HOPS": int(os.getenv("AUTH_TRUSTED_PROXY_HOPS", "0")),
        "ADMIN_IDLE_SECONDS": 900,
        "ADMIN_SESSION_SECONDS": 28800,
        "CUSTOMER_IDLE_SECONDS": 86400,
        "CUSTOMER_SESSION_SECONDS": 604800,
    }
    for area in ("CUSTOMER", "ADMIN"):
        for suffix in ("ISSUER", "CLIENT_ID", "CLIENT_SECRET", "DOMAIN"):
            name = f"COGNITO_{area}_{suffix}"
            settings[name] = os.getenv(name, "")
    return settings


def validate_settings(settings):
    if not 0 <= settings["AUTH_TRUSTED_PROXY_HOPS"] <= 3:
        raise ValueError("AUTH_TRUSTED_PROXY_HOPS must be between zero and three")
    if not settings["AUTH_ENABLED"]:
        if settings["APP_ENV"] != "development":
            raise ValueError("Authentication must be enabled in hosted environments")
        return
    origin = urlsplit(settings["AUTH_ORIGIN"])
    allowed_schemes = {"http", "https"} if settings["APP_ENV"] == "development" else {"https"}
    if (origin.scheme not in allowed_schemes or not origin.hostname or origin.username or origin.password
            or origin.path or origin.query or origin.fragment or settings["CORS_ORIGINS"] != [settings["AUTH_ORIGIN"]]):
        raise ValueError("Authentication requires one exact frontend origin and same-origin API proxy")
    if origin.scheme == "http" and origin.hostname not in {"localhost", "127.0.0.1"}:
        raise ValueError("HTTP authentication is restricted to loopback development")
    if len(settings["SECRET_KEY"]) < 32:
        raise ValueError("Authentication requires an APP_SECRET_KEY of at least 32 characters")
    if not settings["DB_USER"] or not settings["DB_PASSWORD"]:
        raise ValueError("Authentication requires configured MySQL credentials")
    try:
        Fernet(settings["AUTH_TOKEN_ENCRYPTION_KEY"].encode("ascii"))
    except (ValueError, TypeError, UnicodeError) as error:
        raise ValueError("AUTH_TOKEN_ENCRYPTION_KEY must be a Fernet key") from error
    for area in ("CUSTOMER", "ADMIN"):
        prefix = f"COGNITO_{area}_"
        if not ISSUER_PATTERN.fullmatch(settings[prefix + "ISSUER"]):
            raise ValueError(f"{prefix}ISSUER must identify an AWS Cognito user pool")
        if not settings[prefix + "CLIENT_ID"] or not settings[prefix + "CLIENT_SECRET"]:
            raise ValueError(f"{prefix}CLIENT_ID and CLIENT_SECRET are required")
        domain = urlsplit(settings[prefix + "DOMAIN"])
        if (domain.scheme != "https" or not domain.hostname or domain.username or domain.password
                or domain.path or domain.query or domain.fragment or domain.port not in (None, 443)):
            raise ValueError(f"{prefix}DOMAIN must be an exact HTTPS origin")
    if settings["COGNITO_CUSTOMER_ISSUER"] == settings["COGNITO_ADMIN_ISSUER"]:
        raise ValueError("Customer and admin authentication require separate user pools")


def cookie_name(settings, area, flow=False):
    prefix = "__Host-" if settings["APP_ENV"] != "development" else ""
    suffix = "_flow" if flow else ""
    return f"{prefix}popssibilities_{area}{suffix}"
