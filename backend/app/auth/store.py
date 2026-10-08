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


IDENTITY_SELECT = """SELECT i.*, a.role AS admin_role, a.active AS admin_active
    FROM auth_identities i LEFT JOIN auth_admin_access a ON a.identity_id=i.id"""
SESSION_SELECT = """SELECT s.*, i.issuer, i.subject, i.email, i.name,
    a.role AS admin_role, a.active AS admin_active
    FROM auth_sessions s JOIN auth_identities i ON i.id=s.identity_id
    LEFT JOIN auth_admin_access a ON a.identity_id=i.id"""


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
        for key in ("issuer", "subject"):
            if isinstance(row.get(key), bytes):
                row[key] = row[key].decode("utf-8")
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
        from ..migrations import MIGRATIONS, checksum

        with self._transaction() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT checksum, applied_at FROM schema_migrations WHERE version=1")
            row = cursor.fetchone()
            if not row or row["applied_at"] is None or row["checksum"] != checksum(MIGRATIONS / "0001_auth.sql"):
                return False
            for query in (
                "SELECT id, issuer, subject, area, email, name FROM auth_identities LIMIT 0",
                "SELECT identity_id, role, active FROM auth_admin_access LIMIT 0",
                "SELECT token_hash, login_binding_hash, expires_at, revoked_at, encrypted_tokens FROM auth_sessions LIMIT 0",
                "SELECT state_hash, binding_hash, encrypted_payload FROM auth_flows LIMIT 0",
                "SELECT binding_hash, area, expires_at FROM auth_flow_cancellations LIMIT 0",
                "SELECT event, detail FROM auth_audit_events LIMIT 0",
                "SELECT bucket_hash, attempts, window_start FROM auth_rate_limits LIMIT 0",
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
    def _revoke_identity(cursor, identity_id, now):
        cursor.execute("""UPDATE auth_sessions SET revoked_at=%s,encrypted_tokens=''
            WHERE identity_id=%s AND revoked_at IS NULL""", (now, identity_id))
        return cursor.rowcount

    def grant_admin(self, identity_id, role, now, actor_id=None, bootstrap=False):
        _role(role)
        with self._transaction() as connection:
            with self._advisory_lock(connection, "auth-admin-access", "all"):
                with connection.cursor() as cursor:
                    cursor.execute(IDENTITY_SELECT + " WHERE i.id=%s FOR UPDATE", (identity_id,))
                    row = _decode_identity(cursor.fetchone())
                    if not row or row["area"] != "admin":
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
                    if not row or row["area"] != "admin" or row["admin_role"] is None:
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
                        or (area == "admin" and not identity["admin_active"])):
                    raise AccessDeniedError("Identity has no access to this authentication area")
                fields = ("token_hash", "identity_id", "area", "created_at", "last_seen", "expires_at", "auth_time")
                values = tuple(session[key] for key in fields) + (
                    json.dumps(session.get("assurance", {}), separators=(",", ":")), session["encrypted_tokens"], binding,
                )
                cursor.execute("""INSERT INTO auth_sessions
                    (token_hash,identity_id,area,created_at,last_seen,expires_at,auth_time,assurance,encrypted_tokens,login_binding_hash)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", values)
                connection.commit()

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
        with self._transaction() as connection, connection.cursor() as cursor:
            count = self._revoke_identity(cursor, identity_id, now)
            self._audit(cursor, "identity.sessions_revoked", identity_id, None, {"count": count}, now)
            return count

    def update_tokens(self, token_hash, encrypted, now):
        with self._transaction() as connection, connection.cursor() as cursor:
            cursor.execute("""UPDATE auth_sessions SET encrypted_tokens=%s
                WHERE token_hash=%s AND revoked_at IS NULL AND expires_at>%s""", (encrypted, token_hash, now))
            return cursor.rowcount == 1

    def cleanup(self, now):
        """Purge expired credential-bearing state; retain audit history."""
        with self._transaction() as connection, connection.cursor() as cursor:
            counts = {}
            for table in ("auth_flows", "auth_flow_cancellations", "auth_rate_limits", "auth_sessions"):
                cursor.execute("DELETE FROM " + table + " WHERE expires_at<=%s", (now,))
                counts[table] = cursor.rowcount
            return counts
