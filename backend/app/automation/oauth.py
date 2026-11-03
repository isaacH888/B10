"""Owner/session-bound Google OAuth; tokens never leave server adapters."""

import hashlib
import secrets
import time
from datetime import datetime, timezone
from urllib.parse import urlencode, urlsplit

from .google import AwsSecrets, GoogleFailure, GoogleHTTPAdapter

APP_SCOPE = "https://www.googleapis.com/auth/calendar.app.created"
EXISTING_SCOPE = "https://www.googleapis.com/auth/calendar.events"
# A rejected request did not create a calendar. Timeouts, conflicts, redirects,
# server failures and unknown outcomes still require deliberate recovery.
CALENDAR_CREATION_REJECTED_STATUSES = frozenset({400, 401, 403, 404, 405, 410, 422, 429})


def stamp(now):
    return datetime.fromtimestamp(now, timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(str(value).encode()).hexdigest()


class OAuthService:
    def __init__(self, settings, store, google=None, secrets=None, clock=None):
        self.settings, self.store = settings, store
        self.google = google or GoogleHTTPAdapter()
        self.secrets = secrets or AwsSecrets()
        self.clock = clock or time.time

    @property
    def scope(self):
        return EXISTING_SCOPE if self.settings.get("GOOGLE_EXISTING_CALENDAR_ID") else APP_SCOPE

    def _credentials(self):
        name = self.settings.get("GOOGLE_CLIENT_SECRET_ARN")
        value = self.secrets.get(name) if self._client_configured() else None
        if not value or not value.get("client_id") or not value.get("client_secret"):
            raise GoogleFailure(
                "invalid", "Configure the server Google OAuth client secret before connecting."
            )
        return value

    def _client_configured(self):
        name = self.settings.get("GOOGLE_CLIENT_SECRET_ARN", "")
        return bool(
            isinstance(name, str)
            and name.strip()
            and not any(
                marker in name.upper()
                for marker in ("ACCOUNT_ID", "PLACEHOLDER", "YOUR_", "<", ">")
            )
        )

    def _redirect(self):
        uri = self.settings.get("GOOGLE_REDIRECT_URI", "")
        parsed = urlsplit(uri)
        local = self.settings.get(
            "APP_ENV", "development"
        ) == "development" and parsed.hostname in {"localhost", "127.0.0.1"}
        if (
            not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or (parsed.scheme != "https" and not (local and parsed.scheme == "http"))
        ):
            raise GoogleFailure(
                "invalid", "Configure the exact registered Google OAuth callback URL."
            )
        return uri

    def _secret_name(self, owner_id):
        prefix = self.settings.get("GOOGLE_TOKEN_SECRET_PREFIX", "popssibilities/google-tokens")
        return prefix.rstrip("/") + "/" + digest(owner_id)

    def status(self, owner_id):
        with self.store.transaction() as tx:
            connection = tx.get_connection(owner_id) or {}
        configured = self._client_configured()
        return {
            key: connection.get(key)
            for key in ("status", "calendar_id", "scope", "last_error", "updated_at")
        } | {
            "status": connection.get("status", "disconnected"),
            "configured": configured,
            "setup_message": None
            if configured
            else (
                "Google Calendar setup is required. Ask your administrator to configure the Google OAuth client before connecting."
            ),
        }

    def start(self, owner_id, session_id):
        if not owner_id or not session_id:
            raise GoogleFailure("invalid", "Sign in again before connecting Google Calendar.")
        credentials, redirect = self._credentials(), self._redirect()
        state, now = secrets.token_urlsafe(32), self.clock()
        ttl = int(self.settings.get("GOOGLE_OAUTH_STATE_TTL_SECONDS", 600))
        with self.store.booking_lock("google:" + str(owner_id)), self.store.transaction() as tx:
            connection = tx.get_connection(owner_id) or {}
            tx.save_state(
                {
                    "state_hash": digest(state),
                    "owner_id": owner_id,
                    "session_id": digest(session_id),
                    "oauth_epoch": connection.get("oauth_epoch", 0),
                    "created_at": now,
                    "expires_at": now + ttl,
                }
            )
            tx.audit("google.oauth.started", owner_id, {"scope": self.scope}, now)
        query = urlencode(
            {
                "client_id": credentials["client_id"],
                "redirect_uri": redirect,
                "response_type": "code",
                "scope": self.scope,
                "state": state,
                "access_type": "offline",
                "prompt": "consent",
                "include_granted_scopes": "true",
            }
        )
        return {
            "authorization_url": "https://accounts.google.com/o/oauth2/v2/auth?" + query,
            "expires_in": ttl,
        }

    def finish(self, state, code, owner_id, session_id):
        if (
            not isinstance(state, str)
            or len(state) > 512
            or not isinstance(code, str)
            or not code
            or len(code) > 4096
        ):
            raise GoogleFailure(
                "invalid", "The Google connection request is invalid. Start connecting again."
            )
        now = self.clock()
        # Consume in a committed transaction before the exchange. A failed code
        # exchange cannot make the callback state usable a second time.
        with self.store.transaction() as tx:
            saved = tx.consume_state(digest(state), digest(session_id), now)
        if (
            not saved
            or saved.get("owner_id") != owner_id
            or saved.get("session_id") != digest(session_id)
            or float(saved.get("expires_at", 0)) <= now
        ):
            raise GoogleFailure(
                "invalid",
                "The Google connection request expired or belongs to another session. Connect again.",
            )
        with self.store.booking_lock("google:" + str(owner_id)):
            with self.store.transaction() as tx:
                connection = tx.get_connection(owner_id) or {"owner_id": owner_id}
            if saved.get("oauth_epoch", 0) != connection.get("oauth_epoch", 0):
                raise GoogleFailure(
                    "invalid",
                    "This Google connection request was cancelled by a disconnect. Start connecting again.",
                )
            old = (
                self.secrets.get(connection.get("secret_arn") or self._secret_name(owner_id)) or {}
            )
            tokens = self.google.exchange(code, self._credentials(), self._redirect())
            granted = tokens.get("scope", self.scope).split()
            if self.scope not in granted:
                raise GoogleFailure(
                    "reconnect_required",
                    "Google Calendar permission was not granted. Connect again and allow calendar access.",
                )
            tokens["refresh_token"] = tokens.get("refresh_token") or old.get("refresh_token")
            if not tokens.get("refresh_token") or not tokens.get("access_token"):
                raise GoogleFailure(
                    "reconnect_required",
                    "Google did not grant offline access. Reconnect and approve consent.",
                )
            tokens["expires_at"] = now + int(tokens.get("expires_in", 3600))
            secret_arn = self.secrets.put(
                connection.get("secret_arn") or self._secret_name(owner_id), tokens
            )
            # Store credentials before provisioning a calendar, and persist a
            # successful calendar ID immediately so reconnect reuses it.
            connection.update(
                secret_arn=secret_arn,
                scope=self.scope,
                status="connected",
                last_error=None,
                updated_at=stamp(now),
                connection_revision=int(connection.get("connection_revision", 0)) + 1,
            )
            configured = self.settings.get("GOOGLE_EXISTING_CALENDAR_ID")
            if configured:
                connection["calendar_id"] = configured
            with self.store.transaction() as tx:
                tx.save_connection(connection)
            if not connection.get("calendar_id"):
                if connection.get("calendar_provisioning"):
                    error = GoogleFailure(
                        "repair_required",
                        "An earlier calendar creation may have succeeded. Recover its calendar ID from Google Calendar settings before reconnecting.",
                    )
                    self._connection_error(owner_id, error)
                    raise error
                connection["calendar_provisioning"] = True
                connection.update(
                    status="repair_required",
                    last_error="Calendar creation may be in progress. If it was interrupted, recover its calendar ID before reconnecting.",
                )
                with self.store.transaction() as tx:
                    tx.save_connection(connection)
                try:
                    calendar = self.google.create_calendar(tokens["access_token"])
                except GoogleFailure as error:
                    self._connection_error(
                        owner_id,
                        error,
                        calendar_creation_rejected=error.status
                        in CALENDAR_CREATION_REJECTED_STATUSES,
                    )
                    raise
                connection["calendar_id"] = calendar["id"]
                connection["calendar_provisioning"] = False
                connection.update(status="connected", last_error=None)
                with self.store.transaction() as tx:
                    tx.save_connection(connection)
            try:
                self.google.check_calendar(tokens["access_token"], connection["calendar_id"])
            except GoogleFailure as error:
                self._connection_error(owner_id, error)
                raise
            with self.store.transaction() as tx:
                tx.audit(
                    "google.oauth.connected",
                    owner_id,
                    {"calendar_id": connection["calendar_id"]},
                    now,
                )
                # Reconnecting resumes durable work; explicit repair is still
                # required when the previously mapped calendar has changed.
                for booking in tx.list_bookings():
                    if booking.get("owner_id") == owner_id and booking["status"] in {
                        "confirmed",
                        "cancelled",
                    }:
                        booking["calendar_status"] = "pending"
                        booking["calendar_error"] = None
                        tx.save_booking(booking)
                        tx.enqueue(
                            f"google-reconnect:{owner_id}:{digest(state)}:{booking['id']}",
                            "calendar",
                            booking["id"],
                            booking["revision"],
                        )
        return self.status(owner_id)

    def _connection_error(self, owner_id, error, *, calendar_creation_rejected=False):
        with self.store.transaction() as tx:
            connection = tx.get_connection(owner_id) or {"owner_id": owner_id}
            if calendar_creation_rejected:
                connection["calendar_provisioning"] = False
            connection.update(
                status="reconnect_required"
                if error.category == "reconnect_required"
                else "repair_required",
                last_error=error.message,
                updated_at=stamp(self.clock()),
            )
            tx.save_connection(connection)

    def access_token(self, owner_id):
        with self.store.booking_lock("google:" + str(owner_id)):
            with self.store.transaction() as tx:
                connection = tx.get_connection(owner_id) or {}
            if connection.get("status") != "connected" or not connection.get("secret_arn"):
                raise GoogleFailure(
                    "reconnect_required", "Connect Google Calendar before synchronizing bookings."
                )
            tokens = self.secrets.get(connection["secret_arn"]) or {}
            if (
                tokens.get("access_token")
                and float(tokens.get("expires_at", 0)) > self.clock() + 60
            ):
                return tokens["access_token"]
            if not tokens.get("refresh_token"):
                error = GoogleFailure(
                    "reconnect_required", "Reconnect Google Calendar to restore offline access."
                )
                self._connection_error(owner_id, error)
                raise error
            try:
                refreshed = self.google.refresh(tokens["refresh_token"], self._credentials())
            except GoogleFailure as error:
                if error.category == "reconnect_required":
                    self._connection_error(owner_id, error)
                raise
            if not refreshed.get("access_token"):
                raise GoogleFailure(
                    "transient",
                    "Google returned an incomplete token response. Retry synchronization.",
                )
            refreshed["refresh_token"] = refreshed.get("refresh_token") or tokens["refresh_token"]
            refreshed["expires_at"] = self.clock() + int(refreshed.get("expires_in", 3600))
            self.secrets.put(connection["secret_arn"], refreshed)
            return refreshed["access_token"]

    def disconnect(self, owner_id):
        with self.store.booking_lock("google:" + str(owner_id)):
            with self.store.transaction() as tx:
                connection = tx.get_connection(owner_id) or {"owner_id": owner_id}
            if connection.get("secret_arn"):
                tokens = self.secrets.get(connection["secret_arn"]) or {}
                try:
                    if tokens.get("refresh_token") or tokens.get("access_token"):
                        self.google.revoke(tokens.get("refresh_token") or tokens["access_token"])
                except GoogleFailure:
                    # Local disconnection always proceeds. The runbook explains
                    # revocation in Google's account controls if Google is down.
                    pass
                self.secrets.delete(connection["secret_arn"])
            connection.update(
                status="disconnected",
                last_error=None,
                updated_at=stamp(self.clock()),
                oauth_epoch=int(connection.get("oauth_epoch", 0)) + 1,
                connection_revision=int(connection.get("connection_revision", 0)) + 1,
            )
            with self.store.transaction() as tx:
                tx.save_connection(connection)
                tx.audit("google.oauth.disconnected", owner_id, None, self.clock())
        return self.status(owner_id)
