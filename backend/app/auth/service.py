"""Opaque sessions, single-use OAuth transactions, and permission checks."""

import hashlib
import hmac
import json
import secrets
import time
from datetime import datetime, timezone

from cryptography.fernet import Fernet, InvalidToken

from .errors import AuthError, unavailable
from .mfa import matching_counter, new_secret, provisioning_uri
from .settings import cookie_name, mfa_cookie_name
from .store import AccessDeniedError, LoginCancelledError


PERMISSIONS = {
    "staff": ["bookings:read", "bookings:contacts", "bookings:notes", "bookings:fulfill"],
    "owner": ["bookings:read", "bookings:contacts", "bookings:notes", "bookings:fulfill",
              "bookings:confirm", "bookings:cancel", "bookings:price", "payments:manage", "customers:export"],
}


def digest(value):
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def timestamp(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat().replace("+00:00", "Z")


class AuthService:
    def __init__(self, settings, store, providers, clock=None):
        self.settings = settings
        self.store = store
        self.providers = providers
        self.clock = clock or time.time
        self.cipher = Fernet(settings["AUTH_TOKEN_ENCRYPTION_KEY"].encode("ascii"))

    def now(self):
        return int(self.clock())

    def encrypt(self, payload):
        return self.cipher.encrypt(json.dumps(payload, separators=(",", ":")).encode()).decode("ascii")

    def decrypt(self, ciphertext):
        try:
            return json.loads(self.cipher.decrypt(ciphertext.encode("ascii")))
        except (InvalidToken, ValueError, TypeError, UnicodeError):
            raise unavailable() from None

    def check_origin(self, request):
        if request.headers.get("Origin") != self.settings["AUTH_ORIGIN"]:
            raise AuthError("forbidden", "This request is not allowed.", 403)

    def rate_limit(self, area, action, address):
        # Only trusted proxy middleware may change the peer address; raw headers are ignored here.
        private_key = hmac.new(self.settings["SECRET_KEY"].encode(), (address or "unknown").encode(), hashlib.sha256).hexdigest()
        bucket = f"{area}:{action}:{private_key}"
        if not self.store.rate_limit(bucket, 10 if action == "login" else 20, 60, self.now()):
            raise AuthError("rate_limited", "Too many sign-in attempts. Please wait a minute and try again.", 429)

    def start_login(self, area, provider, address, binding=None):
        if provider not in {"password", "google"}:
            raise AuthError("validation_error", "Choose a supported login method.", 422)
        self.rate_limit(area, "login", address)
        now = self.now()
        state = secrets.token_urlsafe(32)
        binding = binding if self.valid_token(binding) else secrets.token_urlsafe(32)
        payload = {"nonce": secrets.token_urlsafe(32), "verifier": secrets.token_urlsafe(64), "provider": provider}
        try:
            self.store.put_flow({"state_hash": digest(state), "binding_hash": digest(binding), "area": area,
                                 "created_at": now, "expires_at": now + 600, "encrypted_payload": self.encrypt(payload)})
        except LoginCancelledError:
            raise AuthError("login_expired", "This sign-in request has expired. Please start again.") from None
        url = self.providers[area].authorization_url(state, payload["nonce"], payload["verifier"], provider)
        self.store.audit("login_started", detail={"area": area})
        return url, binding

    def finish_login(self, area, state, binding, code, address, old_token=None):
        self.rate_limit(area, "callback", address)
        now = self.now()
        if not self.valid_token(state) or not self.valid_token(binding) or not isinstance(code, str) or not code or len(code) > 4096:
            raise AuthError("authentication_failed", "Sign-in could not be completed. Please start again.")
        flow = self.store.consume_flow(digest(state), digest(binding), area, now)
        if not flow:
            raise AuthError("login_expired", "This sign-in request has expired. Please start again.")
        payload = self.decrypt(flow["encrypted_payload"])
        provider = self.providers[area]
        tokens = provider.exchange(code, payload["verifier"])
        now = self.now()
        method = payload["provider"]
        claims = provider.validate(tokens, now, nonce=payload["nonce"], started_at=flow["created_at"], provider=method)
        provider.current_user(tokens["access_token"], claims["subject"], **self.provider_options(area, method, claims))
        now = self.now()
        if now >= flow["expires_at"]:
            raise AuthError("login_expired", "This sign-in request has expired. Please start again.")
        if area == "admin" and method == "google":
            identity = self.store.upsert_identity(claims["issuer"], claims["subject"], area, claims["email"], claims["name"], now)
            # This records a provider identity, never an access grant. Even a
            # verified matching email cannot authorize or link an administrator.
            if (identity.get("admin_role") and not identity.get("is_google_alias")):
                raise AuthError("admin_not_invited", "This account requires private operator review.", 403)
            challenge, proof = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            tokens["token_expires_at"] = claims["token_expires_at"]
            expires = min(now + 300, claims["token_expires_at"], flow["expires_at"])
            pending = {"challenge_hash": digest(challenge), "binding_hash": digest(binding),
                       "identity_id": identity["id"], "google_subject": claims["google_subject"],
                       "provider_username": claims["provider_username"], "proof_hash": digest(proof),
                       "created_at": now, "expires_at": expires,
                       "encrypted_payload": self.encrypt({"tokens": tokens, "claims": claims, "approval_code": proof})}
            try:
                self.store.put_google_challenge(pending)
            except LoginCancelledError:
                raise AuthError("login_expired", "This sign-in request has expired. Please start again.") from None
            except AccessDeniedError:
                raise AuthError("admin_not_invited", "This account is not authorized for administrator access.", 403) from None
            self.revoke_old_session(area, old_token, now)
            self.store.audit("admin.google_first_factor", identity_id=identity["id"], detail={"area": area})
            return {"challenge": challenge, "expires_at": expires}
        if area == "admin":
            identity = self.store.find_identity(claims["issuer"], claims["subject"])
            if (not identity or identity["area"] != "admin" or identity.get("is_google_alias")
                    or not identity.get("admin_active") or identity.get("admin_role") not in PERMISSIONS):
                self.store.audit("admin_login_denied", detail={"area": area})
                raise AuthError("admin_not_invited", "This account is not authorized for administrator access.", 403)
        identity = self.store.upsert_identity(claims["issuer"], claims["subject"], area, claims["email"], claims["name"], now)
        tokens["token_expires_at"] = claims["token_expires_at"]
        token, session = self.new_session(area, identity["id"], digest(binding), tokens,
                                          claims["auth_time"], claims["assurance"], now)
        try:
            self.store.create_session(session)
        except LoginCancelledError:
            raise AuthError("login_expired", "This sign-in request has expired. Please start again.") from None
        except AccessDeniedError:
            raise AuthError("admin_not_invited", "This account is not authorized for administrator access.", 403) from None
        self.revoke_old_session(area, old_token, now)
        self.store.audit("login_completed", identity_id=identity["id"], detail={"area": area})
        return token

    def new_session(self, area, identity_id, binding_hash, tokens, auth_time, assurance, now):
        token = secrets.token_urlsafe(32)
        return token, {"token_hash": digest(token), "identity_id": identity_id, "area": area,
                       "login_binding_hash": binding_hash, "created_at": now, "last_seen": now,
                       "expires_at": now + self.settings[f"{area.upper()}_SESSION_SECONDS"],
                       "auth_time": auth_time, "assurance": assurance, "encrypted_tokens": self.encrypt(tokens)}

    def revoke_old_session(self, area, token, now):
        if self.valid_token(token):
            self.store.revoke_session(digest(token), now)

    @staticmethod
    def provider_options(area, method, identity):
        return {"provider": "google", "google_subject": identity["google_subject"]} if area == "admin" and method == "google" else {}

    @staticmethod
    def admin_assured(session):
        assurance = session["assurance"]
        if not session.get("admin_active") or session.get("admin_role") not in PERMISSIONS:
            return False
        if assurance.get("provider") == "google":
            return (session.get("is_google_alias") and session.get("mfa_enrolled")
                    and assurance.get("method") == "app_totp"
                    and assurance.get("mfa_version") == session.get("mfa_version")
                    and assurance.get("google_subject") == session.get("google_subject")
                    and type(assurance.get("provider_auth_time")) is int
                    and assurance.get("verified_at") == session["auth_time"])
        return (not session.get("is_google_alias") and assurance.get("acr") == "urn:cognito:loa:4"
                and isinstance(assurance.get("amr"), list)
                and all(isinstance(method, str) for method in assurance["amr"])
                and {"pwd", "otp", "mfa"}.issubset(set(assurance["amr"])))

    @staticmethod
    def valid_token(value):
        return isinstance(value, str) and 40 <= len(value) <= 128 and all(char in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for char in value)

    def csrf(self, area, token):
        return hmac.new(self.settings["SECRET_KEY"].encode(), f"csrf:{area}:{token}".encode(), hashlib.sha256).hexdigest()

    def google_pending(self, request, mutation=False):
        token = request.cookies.get(mfa_cookie_name(self.settings))
        binding = request.cookies.get(cookie_name(self.settings, "admin", flow=True))
        if not self.valid_token(token) or not self.valid_token(binding):
            raise AuthError("mfa_challenge_expired", "This sign-in request has expired. Please start again.")
        if mutation:
            self.check_origin(request)
            if not hmac.compare_digest(request.headers.get("X-CSRF-Token", "").encode(), self.csrf("admin-mfa", token).encode()):
                raise AuthError("forbidden", "This request is not allowed.", 403)
        row = self.store.get_google_challenge(digest(token), digest(binding), self.now())
        if not row:
            raise AuthError("mfa_challenge_expired", "This sign-in request has expired. Please start again.")
        payload = self.decrypt(row["encrypted_payload"])
        if row.get("canonical_identity_id") and (not row.get("admin_active") or row.get("admin_role") not in PERMISSIONS):
            raise AuthError("admin_not_invited", "This account is not authorized for administrator access.", 403)
        return token, row, payload

    def pending_status(self, row):
        if not row.get("canonical_identity_id"):
            return "approval_required"
        if row.get("mfa_enrolled"):
            return "challenge_required"
        if (row.get("enrollment_challenge_hash") == row["challenge_hash"]
                and (row.get("enrollment_expires_at") or 0) > self.now()):
            return "enrollment_required"
        return "approval_required"

    def read_google_mfa(self, request):
        token, row, payload = self.google_pending(request)
        status = self.pending_status(row)
        data = {"status": status, "csrf_token": self.csrf("admin-mfa", token), "expires_at": timestamp(row["expires_at"])}
        if status in {"approval_required", "challenge_required"}:
            data["approval_code"] = payload["approval_code"]
        return data

    def mfa_rate_limit(self, request, row):
        # Both source-identity and peer limits are shared across workers and
        # fresh challenges. Creating a new browser transaction cannot reset them.
        for key, limit in (("principal:" + (row.get("canonical_identity_id") or row["identity_id"]), 5),
                           ("peer:" + (request.remote_addr or "unknown"), 10)):
            private = hmac.new(self.settings["SECRET_KEY"].encode(), key.encode(), hashlib.sha256).hexdigest()
            if not self.store.rate_limit("admin:mfa:" + private, limit, 60, self.now()):
                raise AuthError("rate_limited", "Too many sign-in attempts. Please wait a minute and try again.", 429)

    def check_google_pending_provider(self, row, payload):
        if row["issuer"] != self.providers["admin"].issuer or self.now() >= payload["tokens"]["token_expires_at"]:
            raise AuthError("mfa_challenge_expired", "This sign-in request has expired. Please start again.")
        self.providers["admin"].current_user(payload["tokens"]["access_token"], row["subject"],
                                               provider="google", google_subject=row["google_subject"])
        if self.now() >= row["expires_at"]:
            raise AuthError("mfa_challenge_expired", "This sign-in request has expired. Please start again.")

    def enroll_google_mfa(self, request):
        _, row, payload = self.google_pending(request, mutation=True)
        self.mfa_rate_limit(request, row)
        if self.pending_status(row) != "enrollment_required":
            raise AuthError("forbidden", "Private operator approval is required for authenticator enrollment.", 403)
        self.check_google_pending_provider(row, payload)
        if not payload.get("enrollment_secret"):
            payload["enrollment_secret"] = new_secret()
            if not self.store.set_google_challenge_payload(row["challenge_hash"], row["binding_hash"],
                                                          row["encrypted_payload"], self.encrypt(payload), self.now()):
                raise AuthError("mfa_challenge_expired", "This sign-in request has expired. Please start again.")
            self.store.audit("admin.google_mfa_enrollment_started", identity_id=row["canonical_identity_id"])
        return {"secret": payload["enrollment_secret"],
                "otpauth_uri": provisioning_uri(payload["enrollment_secret"], row["canonical_identity_id"]),
                "expires_at": timestamp(row["expires_at"])}

    def verify_google_mfa(self, request, code):
        _, row, payload = self.google_pending(request, mutation=True)
        self.mfa_rate_limit(request, row)
        status = self.pending_status(row)
        if status == "approval_required":
            raise AuthError("admin_not_invited", "This account is not authorized for administrator access.", 403)
        factor = self.store.get_google_factor(row["canonical_identity_id"])
        enrolling = status == "enrollment_required"
        if (not factor or factor["version"] != row["mfa_version"]
                or (not enrolling and not factor.get("encrypted_secret"))):
            raise AuthError("mfa_challenge_expired", "This sign-in request has expired. Please start again.")
        secret = payload.get("enrollment_secret") if enrolling else self.decrypt(factor["encrypted_secret"])["secret"]
        counter = matching_counter(secret, code, self.now()) if secret else None
        if counter is None or counter <= factor["last_counter"]:
            self.store.fail_google_challenge(row["challenge_hash"], row["binding_hash"], self.now())
            self.store.audit("admin.google_mfa_denied", identity_id=row["canonical_identity_id"])
            raise AuthError("invalid_mfa_code", "Enter a valid unused authenticator code.", 422)
        self.check_google_pending_provider(row, payload)
        now = self.now()
        # Recheck after network I/O: clock drift and provider latency must not
        # turn a stale OTP into a fresh administrator session.
        if matching_counter(secret, code, now) != counter:
            raise AuthError("invalid_mfa_code", "Enter a valid unused authenticator code.", 422)
        token = session = None
        if not enrolling:
            assurance = {"provider": "google", "method": "app_totp", "mfa_version": factor["version"],
                         "google_subject": row["google_subject"], "provider_auth_time": payload["claims"]["auth_time"],
                         "verified_at": now}
            token, session = self.new_session("admin", row["identity_id"], row["binding_hash"],
                                              payload["tokens"], now, assurance, now)
        completed = self.store.complete_google_mfa(row["challenge_hash"], row["binding_hash"], now, counter,
                                                    factor["version"], row["encrypted_payload"], session=session,
                                                    encrypted_secret=self.encrypt({"secret": secret}) if enrolling else None)
        if not completed:
            raise AuthError("mfa_challenge_expired", "This sign-in request has expired. Please start again.")
        if enrolling:
            self.revoke_pending_provider(row, payload)
        # The transaction records the completion audit together with the factor
        # or session. Enrollment consumes the proof but deliberately grants no session.
        return {"status": "enrolled" if enrolling else "authenticated", "token": token}

    def revoke_pending_provider(self, row, payload):
        try:
            self.providers["admin"].revoke(payload["tokens"]["refresh_token"])
        except AuthError:
            self.store.audit("admin.google_provider_revocation_pending", identity_id=row["identity_id"])

    def cancel_google_mfa(self, request):
        _, row, payload = self.google_pending(request, mutation=True)
        self.store.cancel_login(row["binding_hash"], "admin", self.now())
        self.revoke_pending_provider(row, payload)
        self.store.audit("admin.google_mfa_cancelled", identity_id=row["identity_id"])
        return self.providers["admin"].logout_url()

    def authenticate(self, area, request, touch=False, csrf=False, permission=None, fresh=False):
        token = request.cookies.get(cookie_name(self.settings, area))
        if not self.valid_token(token):
            raise AuthError("unauthenticated", "Please sign in to continue.")
        token_hash = digest(token)
        with self.store.session_lock(token_hash):
            session = self.store.get_session(token_hash, area)
            now = self.now()
            idle = self.settings[f"{area.upper()}_IDLE_SECONDS"]
            if not session or now >= session["expires_at"] or now >= session["last_seen"] + idle:
                if session:
                    self.store.revoke_session(token_hash, now)
                raise AuthError("session_expired", "Your session has expired. Please sign in again.")
            if csrf:
                self.check_origin(request)
                if not hmac.compare_digest(request.headers.get("X-CSRF-Token", "").encode(), self.csrf(area, token).encode()):
                    raise AuthError("forbidden", "This request is not allowed.", 403)
            if area == "admin":
                if not self.admin_assured(session):
                    self.store.revoke_session(token_hash, now)
                    raise AuthError("forbidden", "Administrator access is not available for this account.", 403)
                permissions = PERMISSIONS[session["admin_role"]]
                if permission and permission not in permissions:
                    raise AuthError("forbidden", "You do not have permission for this action.", 403)
                if fresh and now - session["auth_time"] > 300:
                    raise AuthError("reauthentication_required", "Sign in with your authenticator again before this action.", 403)
            provider = self.providers[area]
            if session["issuer"] != provider.issuer:
                self.store.revoke_session(token_hash, now)
                raise AuthError("unauthenticated", "Please sign in to continue.")
            tokens = self.decrypt(session["encrypted_tokens"])
            method = "google" if area == "admin" and session["assurance"].get("provider") == "google" else "password"
            try:
                if now >= tokens["token_expires_at"] - 30:
                    tokens = provider.refresh(tokens["refresh_token"])
                    now = self.now()
                    claims = provider.validate(tokens, now, provider=method)
                    original_auth_time = session["assurance"]["provider_auth_time"] if method == "google" else session["auth_time"]
                    if (claims["subject"] != session["subject"] or claims["auth_time"] != original_auth_time
                            or (method == "google" and claims["google_subject"] != session["google_subject"])):
                        raise AuthError("authentication_failed", "Invalid authentication response.")
                    tokens["token_expires_at"] = claims["token_expires_at"]
                    if not self.store.update_tokens(token_hash, self.encrypt(tokens), now):
                        raise AuthError("session_expired", "Your session has expired. Please sign in again.")
                provider.current_user(tokens["access_token"], session["subject"], **self.provider_options(area, method, session))
            except AuthError as error:
                if error.status != 503:
                    self.store.revoke_session(token_hash, now)
                raise
            # Access changes can commit while the provider request is in progress.
            now = self.now()
            current = self.store.get_session(token_hash, area)
            if not current or now >= current["expires_at"] or now >= current["last_seen"] + idle:
                raise AuthError("session_expired", "Your session has expired. Please sign in again.")
            if area == "admin":
                if not self.admin_assured(current):
                    self.store.revoke_session(token_hash, now)
                    raise AuthError("forbidden", "Administrator access is not available for this account.", 403)
                if permission and permission not in PERMISSIONS[current["admin_role"]]:
                    raise AuthError("forbidden", "You do not have permission for this action.", 403)
                if fresh and now - current["auth_time"] > 300:
                    raise AuthError("reauthentication_required", "Sign in with your authenticator again before this action.", 403)
            session = current
            if touch:
                self.store.touch_session(token_hash, now)
                session["last_seen"] = now
            session["csrf_token"] = self.csrf(area, token)
            return session

    def session_data(self, area, session):
        identity = {"id": session.get("canonical_identity_id") or session["identity_id"], "email": session["email"], "name": session["name"]}
        if area == "admin":
            identity.update(role=session["admin_role"], permissions=PERMISSIONS[session["admin_role"]])
        idle_expires = min(session["expires_at"], session["last_seen"] + self.settings[f"{area.upper()}_IDLE_SECONDS"])
        return {"administrator" if area == "admin" else "customer": identity,
                "expires_at": timestamp(session["expires_at"]), "idle_expires_at": timestamp(idle_expires),
                "csrf_token": session["csrf_token"]}

    def logout(self, area, request):
        # Local logout remains available even if the identity provider is down.
        self.check_origin(request)
        token = request.cookies.get(cookie_name(self.settings, area))
        if not self.valid_token(token):
            raise AuthError("unauthenticated", "Please sign in to continue.")
        if not hmac.compare_digest(request.headers.get("X-CSRF-Token", "").encode(), self.csrf(area, token).encode()):
            raise AuthError("forbidden", "This request is not allowed.", 403)
        token_hash = digest(token)
        with self.store.session_lock(token_hash):
            session = self.store.get_session(token_hash, area)
            binding = request.cookies.get(cookie_name(self.settings, area, flow=True))
            bindings = {digest(binding)} if self.valid_token(binding) else set()
            if session and session.get("login_binding_hash"):
                bindings.add(session["login_binding_hash"])
            # Shared binding cancels callbacks across overlapping browser tabs,
            # including consumed flows still waiting on provider I/O.
            for binding_hash in bindings:
                self.store.cancel_login(binding_hash, area, self.now())
            self.store.revoke_session(token_hash, self.now())
            if session:
                self.store.audit("logout", identity_id=session["identity_id"], detail={"area": area})
                try:
                    tokens = self.decrypt(session["encrypted_tokens"])
                    self.providers[area].revoke(tokens["refresh_token"])
                except AuthError:
                    self.store.audit("logout_provider_pending", identity_id=session["identity_id"], detail={"area": area})
        return self.providers[area].logout_url()
