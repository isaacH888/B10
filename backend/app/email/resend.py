"""Private Resend HTTP transport shared by customer mail and booking notifications."""

from hashlib import sha256

import requests

from .provider import MailFailure
from .settings import valid_address, validate_resend_settings, validate_settings
from .templates import render_confirmation


class ResendClient:
    def __init__(self, settings, *, http=None):
        self.settings = settings
        self.http = http or requests.Session()

    def send(self, sender, recipient, subject, text, key, *, html=None, reply_to=None):
        try:
            validate_resend_settings(self.settings)
        except ValueError:
            raise MailFailure("unavailable", "resend_misconfigured") from None
        if not valid_address(sender) or not valid_address(recipient):
            raise MailFailure("rejected", "invalid_mailbox")
        if reply_to and not valid_address(reply_to):
            raise MailFailure("rejected", "invalid_reply_to")
        if not isinstance(key, str) or not key:
            raise MailFailure("rejected", "idempotency_key_required")
        payload = {"from": sender, "to": [recipient], "subject": subject, "text": text}
        if html is not None:
            payload["html"] = html
        if reply_to:
            payload["reply_to"] = reply_to
        try:
            response = self.http.post(
                "https://api.resend.com/emails",
                json=payload,
                headers={
                    "Authorization": "Bearer " + self.settings["RESEND_API_KEY"],
                    "Idempotency-Key": "b10-" + sha256(key.encode()).hexdigest(),
                    "Accept": "application/json",
                },
                timeout=(3, 8),
                allow_redirects=False,
            )
        except requests.RequestException:
            # The provider may have accepted the request. A retry must retain
            # the same durable key and stay within Resend's 24-hour window.
            raise MailFailure("uncertain", "resend_delivery_uncertain") from None
        if response.status_code == 429:
            raise MailFailure("unavailable", "resend_throttled")
        if response.status_code == 409:
            try:
                concurrent = response.json().get("name") == "concurrent_idempotent_requests"
            except (ValueError, AttributeError):
                concurrent = False
            raise MailFailure(
                "unavailable" if concurrent else "rejected",
                "resend_busy" if concurrent else "resend_idempotency_conflict",
            )
        if 400 <= response.status_code < 500:
            raise MailFailure("rejected", "resend_rejected")
        if not 200 <= response.status_code < 300:
            raise MailFailure("uncertain", "resend_delivery_uncertain")
        try:
            data = response.json()
            message_id = data.get("id") if isinstance(data, dict) else None
        except ValueError:
            message_id = None
        if not isinstance(message_id, str) or not message_id or len(message_id) > 256:
            raise MailFailure("uncertain", "resend_response_invalid")
        return message_id


class ResendMailer:
    """Customer test-mail adapter; recipients still come from verified sessions."""

    def __init__(self, settings, *, client=None):
        self.settings = settings
        self.client = client or ResendClient(settings)

    def send(self, recipient, name, reference):
        if not self.settings.get("EMAIL_ENABLED", False):
            raise MailFailure("unavailable", "email_disabled")
        try:
            validate_settings(self.settings)
        except ValueError:
            raise MailFailure("unavailable", "email_misconfigured") from None
        message = render_confirmation(name, reference)
        return self.client.send(
            self.settings["EMAIL_FROM_ADDRESS"],
            recipient,
            message["subject"],
            message["text"],
            "customer-test:" + reference,
            html=message["html"],
            reply_to=self.settings["EMAIL_REPLY_TO_ADDRESS"],
        )


class ResendMail:
    """Booking mail uses its persistent outbox key for provider deduplication."""

    def __init__(self, settings, *, client=None):
        self.settings = settings
        self.client = client or ResendClient(settings)

    def send(self, recipient, subject, body, key):
        return self.client.send(
            self.settings["AUTOMATION_FROM_EMAIL"],
            recipient,
            subject,
            body,
            "automation:" + key,
            reply_to=self.settings.get("EMAIL_REPLY_TO_ADDRESS") or None,
        )
