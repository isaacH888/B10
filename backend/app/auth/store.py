"""Durable authentication state shared by every Flask worker."""

from contextlib import contextmanager, nullcontext
import hashlib
import hmac
import json
import threading
import time
from uuid import uuid4

import pymysql

from .. import database


class StoreUnavailable(RuntimeError):
    """Persistence failed; authentication must fail closed."""


class LastOwnerError(ValueError):
    """An operator cannot remove the final active owner."""


class BootstrapRejectedError(ValueError):
    """An active owner already exists in the configured identity issuer."""


class AccessDeniedError(ValueError):
    """The local identity cannot create a session in this authentication area."""


class LoginCancelledError(ValueError):
    """Logout cancelled this browser's pending authentication transaction."""


IDENTITY_SELECT = """SELECT i.*, a.role AS admin_role, a.active AS admin_active,
    COALESCE(e.version,0) AS native_login_version,
    COALESCE(l.admin_identity_id,i.id) AS canonical_identity_id,
    (l.provider_identity_id IS NOT NULL) AS is_google_alias,
    l.google_subject, l.provider_username, f.version AS mfa_version,
    (f.encrypted_secret IS NOT NULL) AS mfa_enrolled
    FROM auth_identities i
    LEFT JOIN auth_admin_google_links l ON l.provider_identity_id=i.id
    LEFT JOIN auth_admin_access a ON a.identity_id=COALESCE(l.admin_identity_id,i.id)
    LEFT JOIN auth_admin_login_epochs e ON e.identity_id=COALESCE(l.admin_identity_id,i.id)
    LEFT JOIN auth_admin_totp f ON f.canonical_identity_id=COALESCE(l.admin_identity_id,i.id)"""
SESSION_SELECT = """SELECT s.*, i.issuer, i.subject, i.email, i.name,
    COALESCE(e.version,0) AS native_login_version,
    a.role AS admin_role, a.active AS admin_active,
    COALESCE(l.admin_identity_id,i.id) AS canonical_identity_id,
    (l.provider_identity_id IS NOT NULL) AS is_google_alias,
    l.google_subject, l.provider_username, f.version AS mfa_version,
    (f.encrypted_secret IS NOT NULL) AS mfa_enrolled
    FROM auth_sessions s JOIN auth_identities i ON i.id=s.identity_id
    LEFT JOIN auth_admin_google_links l ON l.provider_identity_id=i.id
    LEFT JOIN auth_admin_access a ON a.identity_id=COALESCE(l.admin_identity_id,i.id)
    LEFT JOIN auth_admin_login_epochs e ON e.identity_id=COALESCE(l.admin_identity_id,i.id)
    LEFT JOIN auth_admin_totp f ON f.canonical_identity_id=COALESCE(l.admin_identity_id,i.id)"""
GOOGLE_CHALLENGE_SELECT = """SELECT c.*, i.issuer, i.subject, i.email, i.name,
    l.admin_identity_id AS canonical_identity_id, a.role AS admin_role, a.active AS admin_active,
    f.version AS mfa_version, (f.encrypted_secret IS NOT NULL) AS mfa_enrolled,
    f.enrollment_challenge_hash, f.enrollment_expires_at
    FROM auth_admin_google_challenges c JOIN auth_identities i ON i.id=c.identity_id
    LEFT JOIN auth_admin_google_links l ON l.provider_identity_id=c.identity_id
    LEFT JOIN auth_admin_access a ON a.identity_id=l.admin_identity_id
    LEFT JOIN auth_admin_totp f ON f.canonical_identity_id=l.admin_identity_id"""


def _area(area):
    if area not in {"customer", "admin"}:
        raise ValueError("Unknown authentication area")
    return area


def _role(role):
    if role not in {"owner", "staff"}:
        raise ValueError("Unknown administrator role")
    return role


def _decode_identity(row):
    if row:
        for key in ("issuer", "subject", "google_subject"):
            if isinstance(row.get(key), bytes):
                row[key] = row[key].decode("utf-8")
        # MySQL promotes COALESCE(unsigned BIGINT, signed literal) to DECIMAL.
        # Native state and assurance require the stable integer version, not a
        # Decimal that cannot be serialized into encrypted JSON.
        if "native_login_version" in row:
            row["native_login_version"] = int(row["native_login_version"])
    return row


class Store:
    def __init__(self, settings):
        self.settings = settings
        self._local = threading.local()

    @contextmanager
    def _transaction(self):
        connection = getattr(self._local, "connection", None)
        owned = connection is None
        try:
            if owned:
                connection = database.connect(self.settings)
            yield connection
            connection.commit()
        except (pymysql.MySQLError, OSError):
            if connection is not None:
                try:
                    connection.rollback()
                except (pymysql.MySQLError, OSError):
                    pass
            raise StoreUnavailable("Authentication persistence is unavailable") from None
        except Exception:
            if connection is not None:
                connection.rollback()
            raise
        finally:
            if owned and connection is not None:
                connection.close()

    @contextmanager
    def _advisory_lock(self, connection, namespace, value):
        key = namespace + ":" + hashlib.sha256(
            (self.settings["DB_NAME"] + ":" + value).encode()
        ).hexdigest()[:40]
        with connection.cursor() as cursor:
            cursor.execute("SELECT GET_LOCK(%s, 5) AS acquired", (key,))
            if cursor.fetchone()["acquired"] != 1:
                raise StoreUnavailable("Authentication persistence is busy")
        try:
            yield
        finally:
            with connection.cursor() as cursor:
                cursor.execute("SELECT RELEASE_LOCK(%s)", (key,))

    @contextmanager
    def session_lock(self, token_hash):
        """Serialize refreshes, sharing one connection but fresh transactions per call."""
        if getattr(self._local, "connection", None) is not None:
            raise RuntimeError("Session locks cannot be nested")
        with self._transaction() as connection:
            with self._advisory_lock(connection, "auth-refresh", token_hash):
                self._local.connection = connection
                try:
                    yield
                finally:
                    self._local.connection = None

    def ready(self):
        from ..migrations import checksum, migration_files

        with self._transaction() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT version,name,checksum,applied_at FROM schema_migrations")
            history = {row["version"]: row for row in cursor.fetchall()}
            for path in migration_files():
                row = history.get(int(path.name[:4]))
                if (not row or row["applied_at"] is None or row["name"] != path.name
                        or row["checksum"] != checksum(path)):
                    return False
            for query in (
                "SELECT id, issuer, subject, area, email, name FROM auth_identities LIMIT 0",
                "SELECT identity_id, role, active FROM auth_admin_access LIMIT 0",
                "SELECT token_hash, login_binding_hash, expires_at, revoked_at, encrypted_tokens FROM auth_sessions LIMIT 0",
                "SELECT state_hash, binding_hash, encrypted_payload FROM auth_flows LIMIT 0",
                "SELECT binding_hash, area, expires_at FROM auth_flow_cancellations LIMIT 0",
                "SELECT event, detail FROM auth_audit_events LIMIT 0",
                "SELECT bucket_hash, attempts, window_start FROM auth_rate_limits LIMIT 0",
                "SELECT provider_identity_id,admin_identity_id,google_subject,provider_username FROM auth_admin_google_links LIMIT 0",
                "SELECT canonical_identity_id,encrypted_secret,version,last_counter FROM auth_admin_totp LIMIT 0",
                "SELECT challenge_hash,binding_hash,proof_hash,encrypted_payload,attempts FROM auth_admin_google_challenges LIMIT 0",
                "SELECT token_hash,binding_hash,created_at,expires_at,attempts,encrypted_payload FROM auth_admin_native_flows LIMIT 0",
                "SELECT identity_id,version,updated_at FROM auth_admin_login_epochs LIMIT 0",
            ):
                cursor.execute(query)
        return True

    @staticmethod
    def _audit(cursor, event, identity_id, request_id, detail, now):
        cursor.execute(
            "INSERT INTO auth_audit_events (event,identity_id,request_id,created_at,detail) VALUES (%s,%s,%s,%s,%s)",
            (event, identity_id, request_id, now, json.dumps(detail or {}, separators=(",", ":"))),
        )

    def audit(self, event, identity_id=None, request_id=None, detail=None, now=None):
        with self._transaction() as connection, connection.cursor() as cursor:
            self._audit(cursor, event, identity_id, request_id, detail, int(time.time()) if now is None else now)

    def rate_limit(self, bucket, limit, window, now):
        if limit < 1 or window < 1:
            raise ValueError("Rate limit and window must be positive")
        start = int(now) // window * window
        bucket_hash = hashlib.sha256(bucket.encode()).hexdigest()
        with self._transaction() as connection, connection.cursor() as cursor:
            cursor.execute("""INSERT INTO auth_rate_limits (bucket_hash,window_start,attempts,expires_at)
                VALUES (%s,%s,1,%s) ON DUPLICATE KEY UPDATE
                attempts=IF(window_start=VALUES(window_start),LEAST(attempts+1,2147483647),1),
                window_start=VALUES(window_start), expires_at=VALUES(expires_at)""",
                (bucket_hash, start, start + window),
            )
            cursor.execute("SELECT attempts FROM auth_rate_limits WHERE bucket_hash=%s", (bucket_hash,))
            return cursor.fetchone()["attempts"] <= limit

    def put_flow(self, flow):
        _area(flow["area"])
        with self._transaction() as connection:
            with self._advisory_lock(connection, "auth-flow", flow["binding_hash"]):
                with connection.cursor() as cursor:
                    cursor.execute("""SELECT binding_hash FROM auth_flow_cancellations
                        WHERE binding_hash=%s AND area=%s AND expires_at>%s""",
                        (flow["binding_hash"], flow["area"], flow["created_at"]))
                    if cursor.fetchone():
                        raise LoginCancelledError("This sign-in transaction was cancelled")
                    cursor.execute("""INSERT INTO auth_flows
                        (state_hash,binding_hash,area,created_at,expires_at,encrypted_payload)
                        VALUES (%s,%s,%s,%s,%s,%s)""",
                        tuple(flow[key] for key in ("state_hash", "binding_hash", "area", "created_at", "expires_at", "encrypted_payload")),
                    )
                    connection.commit()

    def consume_flow(self, state_hash, binding_hash, area, now):
        _area(area)
        with self._transaction() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT * FROM auth_flows WHERE state_hash=%s FOR UPDATE", (state_hash,))
            row = cursor.fetchone()
            if (not row or row["area"] != area or row["expires_at"] <= now
                    or not hmac.compare_digest(row["binding_hash"], binding_hash)):
                return None
            cursor.execute("DELETE FROM auth_flows WHERE state_hash=%s", (state_hash,))
            return row

    def put_admin_native_flow(self, flow):
        """Persist a short native challenge under the shared logout cancellation lock."""
        created = flow["created_at"]
        expires = flow["expires_at"]
        attempts = flow.get("attempts", 0)
        if (type(created) is not int or type(expires) is not int or created < 0
                or not created < expires <= created + 300):
            raise ValueError("Native sign-in challenges expire within five minutes")
        if type(attempts) is not int or not 0 <= attempts <= 5:
            raise ValueError("Native sign-in challenge attempts must be between zero and five")
        with self._transaction() as connection:
            with self._advisory_lock(connection, "auth-flow", flow["binding_hash"]):
                with connection.cursor() as cursor:
                    cursor.execute("""SELECT binding_hash FROM auth_flow_cancellations
                        WHERE binding_hash=%s AND area='admin' AND expires_at>%s""",
                        (flow["binding_hash"], created))
                    if cursor.fetchone():
                        raise LoginCancelledError("This sign-in transaction was cancelled")
                    cursor.execute("""INSERT INTO auth_admin_native_flows
                        (token_hash,binding_hash,created_at,expires_at,attempts,encrypted_payload)
                        VALUES (%s,%s,%s,%s,%s,%s)""",
                        (flow["token_hash"], flow["binding_hash"], created, expires,
                         attempts, flow["encrypted_payload"]))
                    connection.commit()

    def get_admin_native_flow(self, token_hash, binding_hash, now):
        """Read pending state only for its initiating browser and before its deadline."""
        with self._transaction() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT * FROM auth_admin_native_flows WHERE token_hash=%s", (token_hash,))
            row = cursor.fetchone()
            if (not row or row["expires_at"] <= now or row["attempts"] >= 5
                    or not hmac.compare_digest(row["binding_hash"], binding_hash)):
                return None
            return row

    def consume_admin_native_flow(self, token_hash, binding_hash, now):
        """Consume before calling Cognito so racing attempts cannot replay its session."""
        with self._transaction() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT * FROM auth_admin_native_flows WHERE token_hash=%s FOR UPDATE", (token_hash,))
            row = cursor.fetchone()
            if (not row or row["expires_at"] <= now or row["attempts"] >= 5
                    or not hmac.compare_digest(row["binding_hash"], binding_hash)):
                return None
            cursor.execute("DELETE FROM auth_admin_native_flows WHERE token_hash=%s", (token_hash,))
            row["attempts"] += 1
            return row

    def cancel_login(self, binding_hash, area, now):
        _area(area)
        with self._transaction() as connection:
            with self._advisory_lock(connection, "auth-flow", binding_hash):
                with connection.cursor() as cursor:
                    cursor.execute("""INSERT INTO auth_flow_cancellations (binding_hash,area,expires_at)
                        VALUES (%s,%s,%s) ON DUPLICATE KEY UPDATE
                        expires_at=GREATEST(expires_at,VALUES(expires_at))""", (binding_hash, area, now + 600))
                    cursor.execute("DELETE FROM auth_flows WHERE binding_hash=%s AND area=%s", (binding_hash, area))
                    cursor.execute("""UPDATE auth_sessions SET revoked_at=%s,encrypted_tokens=''
                        WHERE login_binding_hash=%s AND area=%s AND revoked_at IS NULL""", (now, binding_hash, area))
                    if area == "admin":
                        cursor.execute("DELETE FROM auth_admin_native_flows WHERE binding_hash=%s", (binding_hash,))
                        cursor.execute("DELETE FROM auth_admin_google_challenges WHERE binding_hash=%s", (binding_hash,))
                    self._audit(cursor, "login.cancelled", None, None, {"area": area}, now)
                    connection.commit()

    def upsert_identity(self, issuer, subject, area, email, name, now):
        _area(area)
        with self._transaction() as connection, connection.cursor() as cursor:
            cursor.execute("""INSERT INTO auth_identities
                (id,issuer,subject,area,email,name,created_at,updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE id=id""",
                (uuid4().hex, issuer, subject, area, email, name, now, now),
            )
            cursor.execute(IDENTITY_SELECT + " WHERE i.issuer=%s AND i.subject=%s FOR UPDATE", (issuer, subject))
            row = _decode_identity(cursor.fetchone())
            if row["area"] != area:
                raise ValueError("Identity authentication area cannot change")
            cursor.execute("UPDATE auth_identities SET email=%s,name=%s,updated_at=%s WHERE id=%s",
                           (email, name, now, row["id"]))
            row.update(email=email, name=name, updated_at=now)
            return row

    def find_identity(self, issuer, subject):
        with self._transaction() as connection, connection.cursor() as cursor:
            cursor.execute(IDENTITY_SELECT + " WHERE i.issuer=%s AND i.subject=%s", (issuer, subject))
            return _decode_identity(cursor.fetchone())

    def find_identity_by_email(self, email, area="admin"):
        _area(area)
        with self._transaction() as connection, connection.cursor() as cursor:
            cursor.execute(IDENTITY_SELECT + " WHERE i.email=%s AND i.area=%s ORDER BY i.id", (email, area))
            return [_decode_identity(row) for row in cursor.fetchall()]

    @staticmethod
    def _owner_count(cursor, issuer):
        cursor.execute("""SELECT COUNT(*) AS total FROM auth_admin_access a
            JOIN auth_identities i ON i.id=a.identity_id WHERE i.issuer=%s AND a.role='owner' AND a.active=TRUE""",
            (issuer,))
        return cursor.fetchone()["total"]

    def count_active_owners(self, issuer):
        with self._transaction() as connection, connection.cursor() as cursor:
            return self._owner_count(cursor, issuer)

    @staticmethod
    def _revoke_identity(cursor, identity_id, now, keep_challenge_hash=None):
        cursor.execute("SELECT admin_identity_id FROM auth_admin_google_links WHERE provider_identity_id=%s", (identity_id,))
        link = cursor.fetchone()
        canonical = link["admin_identity_id"] if link else identity_id
        cursor.execute("""INSERT INTO auth_admin_login_epochs (identity_id,version,updated_at)
            VALUES (%s,1,%s) ON DUPLICATE KEY UPDATE version=version+1,updated_at=VALUES(updated_at)""",
            (canonical, now))
        cursor.execute("""UPDATE auth_sessions SET revoked_at=%s,encrypted_tokens=''
            WHERE revoked_at IS NULL AND (identity_id=%s OR identity_id IN (
                SELECT provider_identity_id FROM auth_admin_google_links WHERE admin_identity_id=%s))""", (now, canonical, canonical))
        count = cursor.rowcount
        cursor.execute("""DELETE FROM auth_admin_google_challenges WHERE
            (identity_id=%s OR identity_id IN (SELECT provider_identity_id FROM auth_admin_google_links WHERE admin_identity_id=%s))
            AND (%s IS NULL OR challenge_hash<>%s)""", (canonical, canonical, keep_challenge_hash, keep_challenge_hash))
        cursor.execute("""UPDATE auth_admin_totp SET enrollment_challenge_hash=NULL,enrollment_expires_at=NULL
            WHERE canonical_identity_id=%s""", (canonical,))
        return count

    def grant_admin(self, identity_id, role, now, actor_id=None, bootstrap=False):
        _role(role)
        with self._transaction() as connection:
            with self._advisory_lock(connection, "auth-admin-access", "all"):
                with connection.cursor() as cursor:
                    cursor.execute(IDENTITY_SELECT + " WHERE i.id=%s FOR UPDATE", (identity_id,))
                    row = _decode_identity(cursor.fetchone())
                    if not row or row["area"] != "admin" or row["is_google_alias"]:
                        raise ValueError("An administrator identity is required")
                    owners = self._owner_count(cursor, row["issuer"])
                    if bootstrap and (role != "owner" or owners):
                        raise BootstrapRejectedError("An active owner already exists")
                    if row["admin_role"] == "owner" and row["admin_active"] and role != "owner" and owners <= 1:
                        raise LastOwnerError("The final active owner cannot be demoted")
                    cursor.execute("""INSERT INTO auth_admin_access (identity_id,role,active,created_at,updated_at)
                        VALUES (%s,%s,TRUE,%s,%s) ON DUPLICATE KEY UPDATE
                        role=VALUES(role),active=TRUE,updated_at=VALUES(updated_at)""", (identity_id, role, now, now))
                    self._revoke_identity(cursor, identity_id, now)
                    self._audit(cursor, "admin.access_granted", identity_id, None,
                                {"role": role, "active": True, "actor_id": actor_id, "bootstrap": bootstrap}, now)
                    row.update(admin_role=role, admin_active=1)
                    connection.commit()
                    return row

    def set_admin_access(self, identity_id, role=None, active=None, now=None, actor_id=None):
        if role is not None:
            _role(role)
        if active is not None and not isinstance(active, bool):
            raise ValueError("Administrator active status must be boolean")
        now = int(time.time()) if now is None else now
        with self._transaction() as connection:
            with self._advisory_lock(connection, "auth-admin-access", "all"):
                with connection.cursor() as cursor:
                    cursor.execute(IDENTITY_SELECT + " WHERE i.id=%s FOR UPDATE", (identity_id,))
                    row = _decode_identity(cursor.fetchone())
                    if not row or row["area"] != "admin" or row["admin_role"] is None or row["is_google_alias"]:
                        raise ValueError("Existing administrator access is required")
                    next_role = row["admin_role"] if role is None else role
                    next_active = bool(row["admin_active"]) if active is None else active
                    if (row["admin_role"] == "owner" and row["admin_active"]
                            and (next_role != "owner" or not next_active)
                            and self._owner_count(cursor, row["issuer"]) <= 1):
                        raise LastOwnerError("The final active owner cannot be removed")
                    cursor.execute("UPDATE auth_admin_access SET role=%s,active=%s,updated_at=%s WHERE identity_id=%s",
                                   (next_role, next_active, now, identity_id))
                    self._revoke_identity(cursor, identity_id, now)
                    self._audit(cursor, "admin.access_changed", identity_id, None,
                                {"role": next_role, "active": next_active, "actor_id": actor_id}, now)
                    row.update(admin_role=next_role, admin_active=int(next_active))
                    connection.commit()
                    return row

    def create_session(self, session):
        area = _area(session["area"])
        binding = session.get("login_binding_hash")
        with self._transaction() as connection:
            lock = self._advisory_lock(connection, "auth-flow", binding) if binding else nullcontext()
            with lock, connection.cursor() as cursor:
                if binding:
                    cursor.execute("""SELECT binding_hash FROM auth_flow_cancellations
                        WHERE binding_hash=%s AND area=%s AND expires_at>%s""", (binding, area, session["created_at"]))
                    if cursor.fetchone():
                        raise LoginCancelledError("This sign-in transaction was cancelled")
                cursor.execute(IDENTITY_SELECT + " WHERE i.id=%s FOR UPDATE", (session["identity_id"],))
                identity = _decode_identity(cursor.fetchone())
                if (not identity or identity["area"] != area
                        or identity["is_google_alias"]
                        or (area == "admin" and not identity["admin_active"])):
                    raise AccessDeniedError("Identity has no access to this authentication area")
                if area == "admin" and session.get("assurance", {}).get("method") == "cognito_native_challenge":
                    cursor.execute("SELECT version FROM auth_admin_login_epochs WHERE identity_id=%s FOR UPDATE",
                                   (session["identity_id"],))
                    epoch = cursor.fetchone()
                    version = epoch["version"] if epoch else 0
                    supplied = session["assurance"].get("access_version")
                    if type(supplied) is not int or supplied != version:
                        raise AccessDeniedError("Administrator login was revoked")
                self._insert_session(cursor, session)
                connection.commit()

    @staticmethod
    def _insert_session(cursor, session):
        fields = ("token_hash", "identity_id", "area", "created_at", "last_seen", "expires_at", "auth_time")
        values = tuple(session[key] for key in fields) + (
            json.dumps(session.get("assurance", {}), separators=(",", ":")), session["encrypted_tokens"], session.get("login_binding_hash"),
        )
        cursor.execute("""INSERT INTO auth_sessions
            (token_hash,identity_id,area,created_at,last_seen,expires_at,auth_time,assurance,encrypted_tokens,login_binding_hash)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", values)

    def get_session(self, token_hash, area):
        _area(area)
        with self._transaction() as connection, connection.cursor() as cursor:
            cursor.execute(SESSION_SELECT + " WHERE s.token_hash=%s AND s.area=%s AND s.revoked_at IS NULL",
                           (token_hash, area))
            row = _decode_identity(cursor.fetchone())
            if row:
                row["assurance"] = json.loads(row["assurance"])
            return row

    def touch_session(self, token_hash, now):
        with self._transaction() as connection, connection.cursor() as cursor:
            cursor.execute("""UPDATE auth_sessions SET last_seen=GREATEST(last_seen,%s)
                WHERE token_hash=%s AND revoked_at IS NULL AND expires_at>%s""", (now, token_hash, now))
            return cursor.rowcount == 1

    def revoke_session(self, token_hash, now):
        with self._transaction() as connection, connection.cursor() as cursor:
            cursor.execute("""UPDATE auth_sessions SET revoked_at=%s,encrypted_tokens=''
                WHERE token_hash=%s AND revoked_at IS NULL""", (now, token_hash))
            return cursor.rowcount == 1

    def revoke_identity_sessions(self, identity_id, now):
        with self._transaction() as connection:
            with self._advisory_lock(connection, "auth-admin-access", "all"):
                with connection.cursor() as cursor:
                    count = self._revoke_identity(cursor, identity_id, now)
                    self._audit(cursor, "identity.sessions_revoked", identity_id, None, {"count": count}, now)
                    connection.commit()
                    return count

    @staticmethod
    def _google_source(row):
        subject = row.get("google_subject")
        username = row.get("provider_username")
        return (isinstance(subject, str) and 0 < len(subject.encode()) <= 128
                and isinstance(username, str)
                and username in {"Google_" + subject, "google_" + subject.lower()})

    def put_google_challenge(self, row):
        if (not self._google_source(row) or row["expires_at"] <= row["created_at"]
                or row["expires_at"] > row["created_at"] + 300):
            raise ValueError("Google challenge source and lifetime must be valid")
        with self._transaction() as connection:
            with self._advisory_lock(connection, "auth-admin-access", "all"):
                with self._advisory_lock(connection, "auth-flow", row["binding_hash"]):
                    with connection.cursor() as cursor:
                        cursor.execute("""SELECT binding_hash FROM auth_flow_cancellations
                            WHERE binding_hash=%s AND area='admin' AND expires_at>%s""",
                            (row["binding_hash"], row["created_at"]))
                        if cursor.fetchone():
                            raise LoginCancelledError("This sign-in transaction was cancelled")
                        cursor.execute(IDENTITY_SELECT + " WHERE i.id=%s FOR UPDATE", (row["identity_id"],))
                        identity = _decode_identity(cursor.fetchone())
                        if (not identity or identity["area"] != "admin"
                                or (identity["admin_role"] is not None and not identity["is_google_alias"])
                                or (identity["is_google_alias"] and
                                    (not identity["admin_active"] or identity["google_subject"] != row["google_subject"]
                                     or identity["provider_username"] != row["provider_username"]))):
                            raise AccessDeniedError("Google administrator access is not available")
                        fields = ("challenge_hash", "binding_hash", "identity_id", "google_subject", "provider_username",
                                  "proof_hash", "created_at", "expires_at", "encrypted_payload")
                        cursor.execute("""INSERT INTO auth_admin_google_challenges
                            (challenge_hash,binding_hash,identity_id,google_subject,provider_username,proof_hash,
                            created_at,expires_at,encrypted_payload) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                            tuple(row[key] for key in fields))
                        connection.commit()

    @staticmethod
    def _pending_valid(row, binding_hash, now):
        return (row is not None and row["expires_at"] > now and row["attempts"] < 5
                and hmac.compare_digest(row["binding_hash"], binding_hash))

    def get_google_challenge(self, challenge_hash, binding_hash, now):
        with self._transaction() as connection, connection.cursor() as cursor:
            cursor.execute(GOOGLE_CHALLENGE_SELECT + " WHERE c.challenge_hash=%s", (challenge_hash,))
            row = _decode_identity(cursor.fetchone())
            return row if self._pending_valid(row, binding_hash, now) else None

    def get_google_proof(self, proof_hash, issuer, now):
        with self._transaction() as connection, connection.cursor() as cursor:
            cursor.execute(GOOGLE_CHALLENGE_SELECT + " WHERE c.proof_hash=%s AND i.issuer=%s", (proof_hash, issuer))
            row = _decode_identity(cursor.fetchone())
            if row is None or row["expires_at"] <= now or row["attempts"] >= 5:
                return None
            row.pop("encrypted_payload", None)
            return row

    def set_google_challenge_payload(self, challenge_hash, binding_hash, expected_payload, new_payload, now):
        with self._transaction() as connection, connection.cursor() as cursor:
            cursor.execute("""UPDATE auth_admin_google_challenges SET encrypted_payload=%s
                WHERE challenge_hash=%s AND binding_hash=%s AND encrypted_payload=%s
                AND expires_at>%s AND attempts<5""", (new_payload, challenge_hash, binding_hash, expected_payload, now))
            return cursor.rowcount == 1

    def fail_google_challenge(self, challenge_hash, binding_hash, now):
        with self._transaction() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT * FROM auth_admin_google_challenges WHERE challenge_hash=%s FOR UPDATE", (challenge_hash,))
            row = cursor.fetchone()
            if not self._pending_valid(row, binding_hash, now):
                return False
            if row["attempts"] >= 4:
                cursor.execute("DELETE FROM auth_admin_google_challenges WHERE challenge_hash=%s", (challenge_hash,))
            else:
                cursor.execute("UPDATE auth_admin_google_challenges SET attempts=attempts+1 WHERE challenge_hash=%s", (challenge_hash,))
            return True

    def revoke_google_challenge(self, challenge_hash, binding_hash, now):
        with self._transaction() as connection, connection.cursor() as cursor:
            cursor.execute(GOOGLE_CHALLENGE_SELECT + " WHERE c.challenge_hash=%s FOR UPDATE", (challenge_hash,))
            row = _decode_identity(cursor.fetchone())
            if row is None or not hmac.compare_digest(row["binding_hash"], binding_hash):
                return None
            cursor.execute("DELETE FROM auth_admin_google_challenges WHERE challenge_hash=%s", (challenge_hash,))
            return row

    def get_google_factor(self, canonical_id):
        with self._transaction() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT * FROM auth_admin_totp WHERE canonical_identity_id=%s", (canonical_id,))
            return cursor.fetchone()

    def admin_provider_identities(self, canonical_id):
        with self._transaction() as connection, connection.cursor() as cursor:
            cursor.execute(IDENTITY_SELECT + " WHERE i.id=%s OR l.admin_identity_id=%s ORDER BY i.id", (canonical_id, canonical_id))
            rows = [_decode_identity(row) for row in cursor.fetchall()]
            for row in rows:
                row["provider_username"] = row["provider_username"] or row["subject"]
            return rows

    def _approve_google(self, proof_hash, target_id, issuer, now, actor_id, recovery):
        with self._transaction() as connection:
            with self._advisory_lock(connection, "auth-admin-access", "all"):
                with connection.cursor() as cursor:
                    cursor.execute(GOOGLE_CHALLENGE_SELECT + " WHERE c.proof_hash=%s AND i.issuer=%s FOR UPDATE", (proof_hash, issuer))
                    proof = _decode_identity(cursor.fetchone())
                    if (not proof or proof["expires_at"] <= now or proof["attempts"] >= 5
                            or not self._google_source(proof)):
                        raise ValueError("A fresh exact Google identity proof is required")
                    cursor.execute(IDENTITY_SELECT + " WHERE i.id=%s FOR UPDATE", (target_id,))
                    target = _decode_identity(cursor.fetchone())
                    if (not target or target["area"] != "admin" or target["issuer"] != issuer
                            or target["is_google_alias"] or not target["admin_active"]
                            or target["admin_role"] not in {"owner", "staff"} or target_id == proof["identity_id"]):
                        raise ValueError("An active canonical administrator is required")
                    cursor.execute("SELECT identity_id FROM auth_admin_access WHERE identity_id=%s", (proof["identity_id"],))
                    if cursor.fetchone():
                        raise ValueError("A role-owning identity cannot become a Google alias")
                    cursor.execute("""SELECT * FROM auth_admin_google_links WHERE provider_identity_id=%s
                        OR admin_identity_id=%s OR google_subject=%s FOR UPDATE""",
                        (proof["identity_id"], target_id, proof["google_subject"]))
                    links = [_decode_identity(row) for row in cursor.fetchall()]
                    if any(row["provider_identity_id"] != proof["identity_id"] or row["admin_identity_id"] != target_id
                           or row["google_subject"] != proof["google_subject"]
                           or row["provider_username"] != proof["provider_username"] for row in links):
                        raise ValueError("Google aliases cannot be reassigned")
                    if recovery and not links:
                        raise ValueError("Recovery requires the existing Google alias")
                    cursor.execute("SELECT * FROM auth_admin_totp WHERE canonical_identity_id=%s FOR UPDATE", (target_id,))
                    factor = cursor.fetchone()
                    if not recovery and factor and factor["encrypted_secret"] is not None:
                        raise ValueError("An enrolled factor requires the recovery command")
                    if not links:
                        cursor.execute("""INSERT INTO auth_admin_google_links
                            (provider_identity_id,admin_identity_id,google_subject,provider_username,created_at)
                            VALUES (%s,%s,%s,%s,%s)""", (proof["identity_id"], target_id, proof["google_subject"], proof["provider_username"], now))
                    self._revoke_identity(cursor, target_id, now, keep_challenge_hash=proof["challenge_hash"])
                    if factor is None:
                        cursor.execute("""INSERT INTO auth_admin_totp
                            (canonical_identity_id,enrollment_challenge_hash,enrollment_expires_at) VALUES (%s,%s,%s)""",
                            (target_id, proof["challenge_hash"], proof["expires_at"]))
                    else:
                        version = factor["version"] + (1 if recovery else 0)
                        cursor.execute("""UPDATE auth_admin_totp SET encrypted_secret=NULL,version=%s,last_counter=-1,
                            enrollment_challenge_hash=%s,enrollment_expires_at=%s WHERE canonical_identity_id=%s""",
                            (version, proof["challenge_hash"], proof["expires_at"], target_id))
                    cursor.execute("UPDATE auth_admin_google_challenges SET proof_hash=NULL WHERE challenge_hash=%s", (proof["challenge_hash"],))
                    self._audit(cursor, "admin.google_factor_recovery" if recovery else "admin.google_link_approved", target_id, None,
                                {"provider_identity_id": proof["identity_id"], "actor_id": actor_id}, now)
                    connection.commit()
                    proof.update(canonical_identity_id=target_id, admin_role=target["admin_role"], admin_active=target["admin_active"], proof_hash=None)
                    return proof

    def approve_google_link(self, proof_hash, target_id, issuer, now, actor_id=None):
        return self._approve_google(proof_hash, target_id, issuer, now, actor_id, recovery=False)

    def recover_google_factor(self, proof_hash, target_id, issuer, now, actor_id=None):
        return self._approve_google(proof_hash, target_id, issuer, now, actor_id, recovery=True)

    def complete_google_mfa(self, challenge_hash, binding_hash, now, counter, expected_version, expected_payload,
                            session=None, encrypted_secret=None):
        if type(counter) is not int or counter < 0:
            return False
        with self._transaction() as connection:
            with self._advisory_lock(connection, "auth-admin-access", "all"):
                with self._advisory_lock(connection, "auth-flow", binding_hash):
                    with connection.cursor() as cursor:
                        cursor.execute(GOOGLE_CHALLENGE_SELECT + " WHERE c.challenge_hash=%s FOR UPDATE", (challenge_hash,))
                        pending = _decode_identity(cursor.fetchone())
                        if (not self._pending_valid(pending, binding_hash, now) or not pending["admin_active"]
                                or pending["admin_role"] not in {"owner", "staff"}
                                or pending["canonical_identity_id"] is None
                                or not hmac.compare_digest(pending["encrypted_payload"], expected_payload)):
                            return False
                        cursor.execute("SELECT * FROM auth_admin_google_links WHERE provider_identity_id=%s", (pending["identity_id"],))
                        link = _decode_identity(cursor.fetchone())
                        if (not link or link["google_subject"] != pending["google_subject"]
                                or link["provider_username"] != pending["provider_username"]):
                            return False
                        cursor.execute("SELECT binding_hash FROM auth_flow_cancellations WHERE binding_hash=%s AND area='admin' AND expires_at>%s",
                                       (binding_hash, now))
                        if cursor.fetchone():
                            return False
                        cursor.execute("SELECT * FROM auth_admin_totp WHERE canonical_identity_id=%s FOR UPDATE", (pending["canonical_identity_id"],))
                        factor = cursor.fetchone()
                        if not factor or factor["version"] != expected_version or counter <= factor["last_counter"]:
                            return False
                        if session is None:
                            if (factor["encrypted_secret"] is not None or not isinstance(encrypted_secret, str) or not encrypted_secret
                                    or factor["enrollment_challenge_hash"] != challenge_hash
                                    or factor["enrollment_expires_at"] is None or factor["enrollment_expires_at"] <= now):
                                return False
                            cursor.execute("""UPDATE auth_admin_totp SET encrypted_secret=%s,last_counter=%s,
                                enrollment_challenge_hash=NULL,enrollment_expires_at=NULL WHERE canonical_identity_id=%s""",
                                (encrypted_secret, counter, pending["canonical_identity_id"]))
                            event = "admin.google_factor_enrolled"
                        else:
                            assurance = session.get("assurance", {})
                            if (factor["encrypted_secret"] is None or encrypted_secret is not None
                                    or session["identity_id"] != pending["identity_id"] or session["area"] != "admin"
                                    or session.get("login_binding_hash") != binding_hash or session["auth_time"] != now
                                    or assurance.get("provider") != "google" or assurance.get("method") != "app_totp"
                                    or assurance.get("mfa_version") != expected_version
                                    or assurance.get("google_subject") != pending["google_subject"]
                                    or assurance.get("verified_at") != now):
                                return False
                            self._insert_session(cursor, session)
                            cursor.execute("UPDATE auth_admin_totp SET last_counter=%s WHERE canonical_identity_id=%s",
                                           (counter, pending["canonical_identity_id"]))
                            event = "admin.google_mfa_completed"
                        cursor.execute("DELETE FROM auth_admin_google_challenges WHERE challenge_hash=%s", (challenge_hash,))
                        self._audit(cursor, event, pending["canonical_identity_id"], None, {}, now)
                        connection.commit()
                        return True

    def update_tokens(self, token_hash, encrypted, now):
        with self._transaction() as connection, connection.cursor() as cursor:
            cursor.execute("""UPDATE auth_sessions SET encrypted_tokens=%s
                WHERE token_hash=%s AND revoked_at IS NULL AND expires_at>%s""", (encrypted, token_hash, now))
            return cursor.rowcount == 1

    def cleanup(self, now):
        """Purge expired credential-bearing state; retain audit history."""
        with self._transaction() as connection, connection.cursor() as cursor:
            counts = {}
            for table in ("auth_flows", "auth_flow_cancellations", "auth_admin_google_challenges", "auth_admin_native_flows", "auth_rate_limits", "auth_sessions"):
                cursor.execute("DELETE FROM " + table + " WHERE expires_at<=%s", (now,))
                counts[table] = cursor.rowcount
            return counts
