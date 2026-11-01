"""Opt-in automation configuration; no credentials belong in the browser."""

import os
from urllib.parse import urlsplit


def environment_settings(environment):
    def boolean(name, default=False):
        value = os.getenv(name, str(default)).lower()
        if value not in {"true", "false"}:
            raise ValueError(f"{name} must be true or false")
        return value == "true"

    settings = {
        "AUTOMATION_ENABLED": boolean("AUTOMATION_ENABLED"),
        "AUTOMATION_MODE": os.getenv("AUTOMATION_MODE", "local" if environment == "development" else "aws"),
        "AUTOMATION_DASHBOARD_URL": os.getenv("AUTOMATION_DASHBOARD_URL", "http://localhost:5173/admin/bookings" if environment == "development" else ""),
        "AUTOMATION_OWNER_EMAIL": os.getenv("AUTOMATION_OWNER_EMAIL", ""),
        "AUTOMATION_FROM_EMAIL": os.getenv("AUTOMATION_FROM_EMAIL", ""),
        "AUTOMATION_QUEUE_URL": os.getenv("AUTOMATION_QUEUE_URL", ""),
        "AUTOMATION_QUEUE_ARN": os.getenv("AUTOMATION_QUEUE_ARN", ""),
        "AUTOMATION_DLQ_URL": os.getenv("AUTOMATION_DLQ_URL", ""),
        "AUTOMATION_SCHEDULER_GROUP": os.getenv("AUTOMATION_SCHEDULER_GROUP", "popssibilities"),
        "AUTOMATION_SCHEDULER_ROLE_ARN": os.getenv("AUTOMATION_SCHEDULER_ROLE_ARN", ""),
        "AUTOMATION_SCHEDULER_DLQ_ARN": os.getenv("AUTOMATION_SCHEDULER_DLQ_ARN", ""),
        "AUTOMATION_MAX_ATTEMPTS": int(os.getenv("AUTOMATION_MAX_ATTEMPTS", "6")),
        "AUTOMATION_LEASE_SECONDS": int(os.getenv("AUTOMATION_LEASE_SECONDS", "120")),
        "AUTOMATION_RETRY_BASE_SECONDS": int(os.getenv("AUTOMATION_RETRY_BASE_SECONDS", "30")),
        "AUTOMATION_RETRY_MAX_SECONDS": int(os.getenv("AUTOMATION_RETRY_MAX_SECONDS", "900")),
        "AUTOMATION_COUNT_REMINDER_DAYS": int(os.getenv("AUTOMATION_COUNT_REMINDER_DAYS", "7")),
        "AUTOMATION_CAPACITY": int(os.getenv("AUTOMATION_CAPACITY", "1000")),
        "AUTOMATION_RESERVATION_SECONDS": int(os.getenv("AUTOMATION_RESERVATION_SECONDS", "172800")),
        "AUTOMATION_CONTRACT_URL": os.getenv("AUTOMATION_CONTRACT_URL", os.getenv("CONTRACT_URL", "")),
        "GOOGLE_CLIENT_SECRET_ARN": os.getenv("GOOGLE_CLIENT_SECRET_ARN", ""),
        "GOOGLE_TOKEN_SECRET_PREFIX": os.getenv("GOOGLE_TOKEN_SECRET_PREFIX", "popssibilities/google"),
        "GOOGLE_REDIRECT_URI": os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:5173/api/v1/admin/automation/google/callback" if environment == "development" else ""),
        "GOOGLE_EXISTING_CALENDAR_ID": os.getenv("GOOGLE_EXISTING_CALENDAR_ID", ""),
        "GOOGLE_OAUTH_STATE_TTL_SECONDS": int(os.getenv("GOOGLE_OAUTH_STATE_TTL_SECONDS", "600")),
    }
    if settings["AUTOMATION_MODE"] not in {"local", "aws"}:
        raise ValueError("AUTOMATION_MODE must be local or aws")
    if not 1 <= settings["AUTOMATION_MAX_ATTEMPTS"] <= 20:
        raise ValueError("AUTOMATION_MAX_ATTEMPTS must be between 1 and 20")
    if not 60 <= settings["AUTOMATION_LEASE_SECONDS"] <= 3600:
        raise ValueError("AUTOMATION_LEASE_SECONDS must be between 60 and 3600")
    if not 0 <= settings["AUTOMATION_COUNT_REMINDER_DAYS"] <= 365:
        raise ValueError("AUTOMATION_COUNT_REMINDER_DAYS must be between 0 and 365")
    if not 60 <= settings["GOOGLE_OAUTH_STATE_TTL_SECONDS"] <= 1800:
        raise ValueError("GOOGLE_OAUTH_STATE_TTL_SECONDS must be between 60 and 1800")
    if not 1 <= settings["AUTOMATION_RETRY_BASE_SECONDS"] <= settings["AUTOMATION_RETRY_MAX_SECONDS"] <= 43200:
        raise ValueError("Automation retry delays must be bounded between 1 and 43200 seconds")
    if settings["AUTOMATION_ENABLED"]:
        for name in ("AUTOMATION_DASHBOARD_URL", "GOOGLE_REDIRECT_URI"):
            value = urlsplit(settings[name])
            if (value.scheme not in ({"http", "https"} if environment == "development" else {"https"})
                    or not value.hostname or value.username or value.password or value.fragment or value.query):
                raise ValueError(f"{name} must be an exact absolute URL")
        if settings["AUTOMATION_MODE"] == "aws":
            required = ("AUTOMATION_QUEUE_URL", "AUTOMATION_QUEUE_ARN", "AUTOMATION_SCHEDULER_ROLE_ARN",
                        "AUTOMATION_OWNER_EMAIL", "AUTOMATION_FROM_EMAIL", "GOOGLE_CLIENT_SECRET_ARN")
            if any(not settings[key] for key in required):
                raise ValueError("AWS automation requires queue, scheduler, mail and Google secret configuration")
        elif environment != "development":
            raise ValueError("Hosted automation requires AWS adapters")
    return settings
