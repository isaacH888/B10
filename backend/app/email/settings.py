"""Email stays disabled until a verified sender and mailer credentials are configured."""

import os
import re

ADDRESS = re.compile(
    r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,63}\Z"
)
REGION = re.compile(r"[a-z]{2}(?:-[a-z]+)+-\d\Z")
CONFIGURATION_SET = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")


def valid_address(value):
    """Require one bare ASCII mailbox; display names and header controls are rejected."""
    return (
        isinstance(value, str)
        and len(value) <= 254
        and ADDRESS.fullmatch(value) is not None
        and len(value.split("@", 1)[0]) <= 64
        and ".." not in value
    )


def environment_settings():
    enabled = os.getenv("EMAIL_ENABLED", "false").lower()
    if enabled not in {"true", "false"}:
        raise ValueError("EMAIL_ENABLED must be true or false")
    return {
        "EMAIL_ENABLED": enabled == "true",
        "EMAIL_PROVIDER": os.getenv("EMAIL_PROVIDER", "ses"),
        "EMAIL_AWS_REGION": os.getenv("EMAIL_AWS_REGION", "us-east-1"),
        "EMAIL_FROM_ADDRESS": os.getenv("EMAIL_FROM_ADDRESS", ""),
        "EMAIL_REPLY_TO_ADDRESS": os.getenv("EMAIL_REPLY_TO_ADDRESS", ""),
        "EMAIL_SES_CONFIGURATION_SET": os.getenv("EMAIL_SES_CONFIGURATION_SET", ""),
        "EMAIL_AWS_ACCESS_KEY_ID": os.getenv("EMAIL_AWS_ACCESS_KEY_ID", ""),
        "EMAIL_AWS_SECRET_ACCESS_KEY": os.getenv("EMAIL_AWS_SECRET_ACCESS_KEY", ""),
        "EMAIL_AWS_SESSION_TOKEN": os.getenv("EMAIL_AWS_SESSION_TOKEN", ""),
    }


def validate_settings(settings):
    if not settings.get("EMAIL_ENABLED", False):
        return
    if not settings.get("AUTH_ENABLED"):
        raise ValueError("Email requires authenticated customer sessions")
    if settings.get("EMAIL_PROVIDER") != "ses":
        raise ValueError("EMAIL_PROVIDER must be ses")
    for key in ("EMAIL_FROM_ADDRESS", "EMAIL_REPLY_TO_ADDRESS"):
        if not valid_address(settings.get(key)):
            raise ValueError(f"{key} must be one bare email address")
    if not REGION.fullmatch(settings.get("EMAIL_AWS_REGION", "")):
        raise ValueError("EMAIL_AWS_REGION must identify an AWS region")
    configuration_set = settings.get("EMAIL_SES_CONFIGURATION_SET", "")
    if configuration_set and not CONFIGURATION_SET.fullmatch(configuration_set):
        raise ValueError("EMAIL_SES_CONFIGURATION_SET is invalid")
    access = settings.get("EMAIL_AWS_ACCESS_KEY_ID", "")
    secret = settings.get("EMAIL_AWS_SECRET_ACCESS_KEY", "")
    token = settings.get("EMAIL_AWS_SESSION_TOKEN", "")
    if bool(access) != bool(secret) or (token and not access):
        raise ValueError("Dedicated email credentials require both an access key and a secret key")
