"""Opaque sessions, single-use OAuth transactions, and permission checks."""

import hashlib
import hmac
import json
import secrets
import time
from datetime import datetime, timezone

from cryptography.fernet import Fernet, InvalidToken

from .errors import AuthError, unavailable
from .settings import cookie_name
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
        if provider not in ({"password"} if area == "admin" else {"password", "google"}):
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
        method = payload.get("provider")
        if not isinstance(method, str) or method not in ({"password"} if area == "admin" else {"password", "google"}):
            self.store.audit("login_method_denied", detail={"area": area})
            raise AuthError("authentication_failed", "Sign-in could not be completed. Please start again.")
        provider = self.providers[area]
        tokens = provider.exchange(code, payload["verifier"])
        now = self.now()
        claims = provider.validate(tokens, now, nonce=payload["nonce"], started_at=flow["created_at"], provider=method)
        provider.current_user(tokens["access_token"], claims["subject"])
        now = self.now()
        if now >= flow["expires_at"]:
            raise AuthError("login_expired", "This sign-in request has expired. Please start again.")
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
    def admin_assured(session):
        assurance = session["assurance"]
        if (not isinstance(assurance, dict) or not session.get("admin_active")
                or session.get("admin_role") not in PERMISSIONS):
            return False
        return (assurance.get("provider") in (None, "password")
                and assurance.get("method") != "app_totp"
                and not session.get("is_google_alias") and assurance.get("acr") == "urn:cognito:loa:4"
                and isinstance(assurance.get("amr"), list)
                and all(isinstance(method, str) for method in assurance["amr"])
                and {"pwd", "otp", "mfa"}.issubset(set(assurance["amr"])))

    @staticmethod
    def valid_token(value):
        return isinstance(value, str) and 40 <= len(value) <= 128 and all(char in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for char in value)

    def csrf(self, area, token):
        return hmac.new(self.settings["SECRET_KEY"].encode(), f"csrf:{area}:{token}".encode(), hashlib.sha256).hexdigest()

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
            try:
                if now >= tokens["token_expires_at"] - 30:
                    tokens = provider.refresh(tokens["refresh_token"])
                    now = self.now()
                    claims = provider.validate(tokens, now)
                    if claims["subject"] != session["subject"] or claims["auth_time"] != session["auth_time"]:
                        raise AuthError("authentication_failed", "Invalid authentication response.")
                    tokens["token_expires_at"] = claims["token_expires_at"]
                    if not self.store.update_tokens(token_hash, self.encrypt(tokens), now):
                        raise AuthError("session_expired", "Your session has expired. Please sign in again.")
                provider.current_user(tokens["access_token"], session["subject"])
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
