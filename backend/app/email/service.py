"""Customer-initiated sample mail, bound to a fresh verified Cognito mailbox."""

import hashlib
import hmac

from ..auth.errors import AuthError
from .provider import MailFailure
from .settings import valid_address
from .store import MailConflict, MailRateLimited, MailStoreUnavailable


def unavailable():
    return AuthError(
        "email_unavailable",
        "Test email is unavailable. Check the email service configuration.",
        503,
    )


def uncertain():
    return AuthError(
        "email_delivery_uncertain",
        "The email may have been sent. Check your inbox before requesting another.",
        409,
    )


class CustomerMailService:
    def __init__(self, settings, auth_service, store, mailer):
        self.settings, self.auth, self.store, self.mailer = settings, auth_service, store, mailer

    def send(self, principal, key):
        if not self.settings["EMAIL_ENABLED"]:
            raise unavailable()
        # GetUser uses this customer's access token, never operator IAM. Recheck
        # verification now rather than sending to a stale email saved at sign-in.
        tokens = self.auth.decrypt(principal["encrypted_tokens"])
        profile = self.auth.providers["customer"].verified_customer_profile(
            tokens["access_token"], principal["subject"]
        )
        recipient, name = profile.get("email"), profile.get("name")
        if not valid_address(recipient):
            raise AuthError(
                "email_verification_required",
                "Verify your customer email before requesting a test email.",
                403,
            )
        identity_id = principal["identity_id"]
        request_hash = hashlib.sha256((identity_id + ":" + key).encode()).hexdigest()
        recipient_hash = hmac.new(
            self.settings["SECRET_KEY"].encode(), recipient.lower().encode(), hashlib.sha256
        ).hexdigest()
        try:
            row, is_new = self.store.reserve(
                identity_id, request_hash, recipient_hash, self.auth.now()
            )
        except MailRateLimited:
            raise AuthError(
                "email_rate_limited", "Too many test emails. Please wait before trying again.", 429
            ) from None
        except MailConflict:
            raise AuthError(
                "idempotency_conflict",
                "Your email address changed. Refresh the page before trying again.",
                409,
            ) from None
        except MailStoreUnavailable:
            raise unavailable() from None
        if not is_new:
            if row["status"] == "accepted":
                return {"status": "accepted", "reference": row["reference"], "duplicate": True}
            if row["status"] in {"sending", "uncertain"}:
                raise uncertain()
            code = row.get("error_code") or "email_unavailable"
            raise AuthError(
                code,
                "This test email was not accepted. Check the service configuration before requesting another.",
                503,
            )
        try:
            message_id = self.mailer.send(recipient, name, row["reference"])
        except MailFailure as failure:
            status = "uncertain" if failure.kind == "uncertain" else "failed"
            code = (
                "email_delivery_uncertain"
                if status == "uncertain"
                else ("email_rejected" if failure.kind == "rejected" else "email_unavailable")
            )
            try:
                self.store.finish(request_hash, status, self.auth.now(), error_code=code)
            except MailStoreUnavailable:
                # The pre-send reservation remains, preventing a second send.
                raise uncertain() from None
            if status == "uncertain":
                raise uncertain() from None
            raise AuthError(
                code,
                "The test email could not be sent. Check the email service configuration.",
                503,
            ) from None
        except Exception:
            # An unexpected adapter failure might occur after network delivery.
            # Retain the reservation and reveal no provider exception or mailbox.
            raise uncertain() from None
        try:
            self.store.finish(request_hash, "accepted", self.auth.now(), message_id=message_id)
        except MailStoreUnavailable:
            raise uncertain() from None
        return {"status": "accepted", "reference": row["reference"], "duplicate": False}
