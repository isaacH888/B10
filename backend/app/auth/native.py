"""Browser-bound native Cognito challenges; no IAM or plaintext credential persistence."""

import hashlib
import hmac
import re
import secrets

from .errors import AuthError
from .settings import cookie_name, native_cookie_name
from .store import AccessDeniedError, LoginCancelledError


def hashed(value):
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def expired():
    return AuthError("login_expired", "This sign-in has expired. Please start again.")


class NativeAdminFlow:
    def _native_data(self, payload, credential, deadline):
        from .service import timestamp

        data = {
            "step": payload["step"],
            "csrf_token": self.csrf("admin-native", credential),
            "expires_at": timestamp(deadline),
        }
        if payload["step"] == "totp_enrollment":
            data["enrollment_secret"] = payload["enrollment_secret"]
        if payload.get("enrollment_complete"):
            data["enrollment_complete"] = True
        return data

    def _native_load(self, request, *, consume=False):
        credential = request.cookies.get(native_cookie_name(self.settings))
        binding = request.cookies.get(cookie_name(self.settings, "admin", flow=True))
        if not self.valid_token(credential) or not self.valid_token(binding):
            raise expired()
        if consume:
            self.check_origin(request)
            supplied = request.headers.get("X-CSRF-Token", "")
            if not hmac.compare_digest(
                supplied.encode(), self.csrf("admin-native", credential).encode()
            ):
                raise AuthError("forbidden", "This request is not allowed.", 403)
        lookup = (
            self.store.consume_admin_native_flow if consume else self.store.get_admin_native_flow
        )
        row = lookup(hashed(credential), hashed(binding), self.now())
        if not row:
            raise expired()
        return row, self.decrypt(row["encrypted_payload"]), credential, binding

    def _native_put(self, payload, binding, *, row=None):
        now = self.now()
        credential = secrets.token_urlsafe(32)
        if row is None:
            row = {"created_at": now, "expires_at": now + 300, "attempts": 0}
        if now >= row["expires_at"] or row["attempts"] >= 5:
            raise expired()
        pending = {
            **row,
            "token_hash": hashed(credential),
            "binding_hash": hashed(binding),
            "encrypted_payload": self.encrypt(payload),
        }
        try:
            self.store.put_admin_native_flow(pending)
        except LoginCancelledError:
            raise expired() from None
        return self._native_data(payload, credential, row["expires_at"]), credential, binding

    def native_transaction(self, request, request_id=None):
        # Bootstrap may be a same-origin GET without Origin; never allow a known
        # cross-origin request to replace the browser's private transaction.
        origin = request.headers.get("Origin")
        if origin is not None:
            self.check_origin(request)
        if request.headers.get("Sec-Fetch-Site") == "cross-site":
            raise AuthError("forbidden", "This request is not allowed.", 403)
        self.rate_limit("admin", "native_status", request.remote_addr)
        credential = request.cookies.get(native_cookie_name(self.settings))
        if self.valid_token(credential):
            row, payload, credential, binding = self._native_load(request)
            return self._native_data(payload, credential, row["expires_at"]), credential, binding
        self.rate_limit("admin", "login", request.remote_addr)
        binding = request.cookies.get(cookie_name(self.settings, "admin", flow=True))
        if not self.valid_token(binding):
            binding = secrets.token_urlsafe(32)
        self.store.audit(
            "admin_native_login_started", request_id=request_id, detail={"area": "admin"}
        )
        return self._native_put({"step": "password"}, binding)

    def _native_identity(self, payload):
        from .service import PERMISSIONS

        identity = self.store.find_identity(self.providers["admin"].issuer, payload["subject"])
        if (
            not identity
            or identity["id"] != payload["identity_id"]
            or identity["area"] != "admin"
            or identity.get("is_google_alias")
            or not identity.get("admin_active")
            or identity.get("admin_role") not in PERMISSIONS
            or identity.get("native_login_version", 0) != payload["access_version"]
        ):
            raise AuthError(
                "admin_not_invited", "This account is not authorized for administrator access.", 403
            )
        return identity

    def _native_select(self, email):
        from .service import PERMISSIONS

        matches = [
            i
            for i in self.store.find_identity_by_email(email, area="admin")
            if i["issuer"] == self.providers["admin"].issuer
            and i["area"] == "admin"
            and not i.get("is_google_alias")
            and i.get("admin_active")
            and i.get("admin_role") in PERMISSIONS
        ]
        if len(matches) != 1:
            # Do not disclose which accounts have private grants.
            raise AuthError(
                "authentication_failed", "Sign-in could not be completed. Please start again."
            )
        return matches[0]

    def _native_advance(self, payload, challenge):
        name = challenge["challenge"]
        next_payload = {
            **payload,
            "session": challenge["session"],
            "username": challenge["username"],
        }
        if name == "NEW_PASSWORD_REQUIRED":
            next_payload.update(
                step="new_password", required_attributes=challenge.get("required_attributes", [])
            )
        elif name == "SOFTWARE_TOKEN_MFA":
            next_payload.update(step="totp")
        elif name == "MFA_SETUP":
            self._native_identity(payload)
            secret, session = self.providers["admin"].native_associate(challenge["session"])
            self._native_identity(payload)
            next_payload.update(step="totp_enrollment", enrollment_secret=secret, session=session)
        else:
            raise AuthError(
                "authentication_failed", "Sign-in could not be completed. Please start again."
            )
        return next_payload

    @staticmethod
    def _native_input(body, fields):
        if (
            not isinstance(body, dict)
            or set(body) != fields
            or any(not isinstance(v, str) for v in body.values())
        ):
            raise AuthError(
                "validation_error", "Send only the fields required by this sign-in step.", 422
            )

    @staticmethod
    def _native_password_value(value, *, new=False):
        if not (16 if new else 1) <= len(value) <= 256 or (new and any(c.isspace() for c in value)):
            raise AuthError("validation_error", "Enter a valid administrator password.", 422)

    def native_submit(self, request, body, request_id=None):
        self.rate_limit("admin", "native_challenge", request.remote_addr)
        row, payload, credential, binding = self._native_load(request, consume=True)
        provider = self.providers["admin"]
        step = payload["step"]
        if step == "password":
            self._native_input(body, {"email", "password"})
            email = body["email"].strip().lower()
            if not 3 <= len(email) <= 254 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
                raise AuthError("validation_error", "Enter your team email address.", 422)
            self._native_password_value(body["password"])
            # Hash all attempted account selectors, including unknown accounts.
            account_key = hmac.new(
                self.settings["SECRET_KEY"].encode(), email.encode(), hashlib.sha256
            ).hexdigest()
            if not self.store.rate_limit(
                "admin:native_account:" + account_key, 10, 300, self.now()
            ):
                raise AuthError(
                    "rate_limited", "Too many sign-in attempts. Please wait a few minutes.", 429
                )
            identity = self._native_select(email)
            payload = {
                "identity_id": identity["id"],
                "subject": identity["subject"],
                "access_version": identity.get("native_login_version", 0),
            }
            challenge = provider.native_password(identity["subject"], body["password"])
            self._native_identity(payload)
            return (
                *self._native_put(self._native_advance(payload, challenge), binding, row=row),
                None,
            )
        identity = self._native_identity(payload)
        if step == "new_password":
            self._native_input(body, {"new_password"})
            self._native_password_value(body["new_password"], new=True)
            attributes = {field: identity[field] for field in payload["required_attributes"]}
            challenge = provider.native_new_password(
                payload["session"], payload["username"], body["new_password"], attributes
            )
            self._native_identity(payload)
            return (
                *self._native_put(self._native_advance(payload, challenge), binding, row=row),
                None,
            )
        if step not in {"totp", "totp_enrollment"}:
            raise expired()
        self._native_input(body, {"code"})
        if not re.fullmatch(r"[0-9]{6}", body["code"]):
            raise AuthError("validation_error", "Enter a six-digit authenticator code.", 422)
        if step == "totp_enrollment":
            provider.native_enroll(payload["session"], payload["username"], body["code"])
            self._native_identity(payload)
            if self.now() >= row["expires_at"]:
                raise expired()
            self.store.audit(
                "admin_native_enrollment_completed",
                identity_id=identity["id"],
                request_id=request_id,
                detail={"area": "admin"},
            )
            # Enrollment-issued tokens are revoked by the provider; registration
            # does not establish this application's MFA proof.
            return (
                *self._native_put({"step": "password", "enrollment_complete": True}, binding),
                None,
            )
        tokens = provider.native_totp(payload["session"], payload["username"], body["code"])
        now = self.now()
        claims = provider.validate_native(tokens, now, started_at=row["created_at"])
        if claims["subject"] != payload["subject"] or claims["issuer"] != provider.issuer:
            raise AuthError(
                "authentication_failed", "Sign-in could not be completed. Please start again."
            )
        provider.current_user(tokens["access_token"], claims["subject"])
        identity = self._native_identity(payload)
        now = self.now()
        if now >= row["expires_at"]:
            raise expired()
        identity = self.store.upsert_identity(
            claims["issuer"], claims["subject"], "admin", claims["email"], claims["name"], now
        )
        tokens["token_expires_at"] = claims["token_expires_at"]
        proof = {
            "method": "cognito_native_challenge",
            "provider": "password",
            "challenge": "SOFTWARE_TOKEN_MFA",
            "completed_at": now,
            "access_version": payload["access_version"],
        }
        token, session = self.new_session(
            "admin", identity["id"], hashed(binding), tokens, claims["auth_time"], proof, now
        )
        try:
            self.store.create_session(session)
        except (LoginCancelledError, AccessDeniedError):
            raise expired() from None
        self.revoke_old_session(
            "admin", request.cookies.get(cookie_name(self.settings, "admin")), now
        )
        self.store.audit(
            "admin_native_login_completed",
            identity_id=identity["id"],
            request_id=request_id,
            detail={"area": "admin"},
        )
        from .service import timestamp

        data = {
            "step": "complete",
            "csrf_token": self.csrf("admin", token),
            "expires_at": timestamp(session["expires_at"]),
        }
        return data, None, binding, token

    def native_cancel(self, request):
        row, payload, credential, binding = self._native_load(request, consume=True)
        self.store.cancel_login(row["binding_hash"], "admin", self.now())
        return {"step": "cancelled"}
