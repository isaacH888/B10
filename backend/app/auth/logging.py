"""Prevent development access logs from retaining OAuth callback parameters."""

import logging
import re


class CallbackRedaction(logging.Filter):
    def filter(self, record):
        message = record.getMessage()
        redacted = re.sub(r"(/api/v1/(?:admin|customer)/callback)\?[^\s\"\x1b]+", r"\1?<redacted>", message)
        if redacted != message:
            record.msg, record.args = redacted, ()
        return True


def redact_development_access_logs():
    logger = logging.getLogger("werkzeug")
    if not any(isinstance(item, CallbackRedaction) for item in logger.filters):
        logger.addFilter(CallbackRedaction())
