"""Booking persistence and transactional outbox, using the project's MySQL database.

All transactions briefly hold one durable mutex row. This deliberately conservative
MVP serializes capacity decisions, payment reference checks and job claims across
processes. Network calls belong outside transactions; booking_lock serializes a
single booking's Google calls independently.
"""

import hashlib
import hmac
import json
import threading
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone

import pymysql

from .. import database


class StoreUnavailable(RuntimeError):
    pass


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def _epoch(value):
    if isinstance(value, (int, float)):
        return value
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def _json(value):
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def _decode(value):
    if isinstance(value, dict):
        return value
    return json.loads(value)


class MemoryTransaction:
    def __init__(self, state):
        self.state = state

    def get_booking(self, booking_id):
        return deepcopy(self.state["bookings"].get(booking_id))

    def save_booking(self, booking):
        self.state["bookings"][booking["id"]] = deepcopy(booking)

    def list_bookings(self):
        return deepcopy(list(self.state["bookings"].values()))

    def get_order_link(self, order_id):
        return deepcopy(self.state["order_links"].get(order_id))

    def save_order_link(self, link):
        self.state["order_links"][link["order_id"]] = deepcopy(link)

    def add_payment(self, payment):
        if payment["reference"] in self.state["payments"]:
            return False
        self.state["payments"][payment["reference"]] = deepcopy(payment)
        return True

    def payments(self, booking_id):
        return deepcopy(
            [p for p in self.state["payments"].values() if p["booking_id"] == booking_id]
        )

    def get_payment(self, reference):
        return deepcopy(self.state["payments"].get(reference))

    def enqueue(self, key, kind, booking_id, revision, payload=None):
        if key in self.state["outbox"]:
            return False
        self.state["outbox"][key] = {
            "key": key,
            "kind": kind,
            "booking_id": booking_id,
            "revision": revision,
            "payload": deepcopy(payload or {}),
            "status": "pending",
            "attempts": 0,
            "created_at": utc_now(),
        }
        return True

    def get_outbox(self, key):
        return deepcopy(self.state["outbox"].get(key))

    def list_outbox(self, limit=None, statuses=None):
        rows = list(self.state["outbox"].values())
        if statuses is not None:
            rows = [row for row in rows if row["status"] in statuses]
        return deepcopy(rows if limit is None else rows[:limit])

    def save_outbox(self, job):
        self.state["outbox"][job["key"]] = deepcopy(job)

    def get_delivery(self, key):
        return deepcopy(self.state["deliveries"].get(key))

    def save_delivery(self, delivery):
        self.state["deliveries"][delivery["key"]] = deepcopy(delivery)

    def get_connection(self, owner_id="default"):
        return deepcopy(self.state["connections"].get(owner_id))

    def save_connection(self, connection):
        self.state["connections"][connection.get("owner_id", "default")] = deepcopy(connection)

    def save_state(self, state):
        self.state["states"][state["state_hash"]] = deepcopy(state)

    def consume_state(self, state_hash, session_id, now):
        state = self.state["states"].get(state_hash)
        if not state or not hmac.compare_digest(state["session_id"], session_id):
            return None
        del self.state["states"][state_hash]
        return deepcopy(state) if _epoch(state["expires_at"]) > _epoch(now) else None

    def audit(self, event, actor=None, detail=None, now=None):
        self.state["audits"].append(
            {
                "event": event,
                "actor": actor,
                "detail": deepcopy(detail or {}),
                "created_at": now or utc_now(),
            }
        )


class MemoryStore:
    """Offline adapter with real atomic rollback and cross-thread serialization."""

    def __init__(self):
        self._state = {
            name: {}
            for name in ("bookings", "payments", "outbox", "deliveries", "connections", "states")
        }
        self._state["audits"] = []
        self._state["order_links"] = {}
        self._lock = threading.RLock()
        self._booking_locks = {}
        self._local = threading.local()

    @contextmanager
    def transaction(self, capacity=False):
        if getattr(self._local, "transaction", False):
            raise RuntimeError("Booking transactions cannot be nested")
        with self._lock:
            self._local.transaction = True
            state = deepcopy(self._state)
            try:
                yield MemoryTransaction(state)
                self._state = state
            finally:
                self._local.transaction = False

    @contextmanager
    def booking_lock(self, booking_id):
        with self._lock:
            lock = self._booking_locks.setdefault(booking_id, threading.RLock())
        with lock:
            yield


class SQLTransaction:
    def __init__(self, connection):
        self.connection = connection

    def _read(self, query, args=(), many=False):
        with self.connection.cursor() as cursor:
            cursor.execute(query, args)
            rows = cursor.fetchall() if many else cursor.fetchone()
        if many:
            return [_decode(row["data"]) for row in rows]
        return _decode(rows["data"]) if rows else None

    def _execute(self, query, args=()):
        with self.connection.cursor() as cursor:
            cursor.execute(query, args)
            return cursor.rowcount

    def get_booking(self, booking_id):
        return self._read(
            "SELECT data FROM automation_bookings WHERE id=%s FOR UPDATE", (booking_id,)
        )

    def get_order_link(self, order_id):
        return self._read(
            "SELECT data FROM automation_order_links WHERE order_id=%s FOR UPDATE", (order_id,)
        )

    def save_order_link(self, link):
        self._execute(
            "INSERT INTO automation_order_links (order_id, booking_id, data) VALUES (%s,%s,%s)",
            (link["order_id"], link["booking_id"], _json(link)),
        )

    def save_booking(self, booking):
        self._execute(
            """INSERT INTO automation_bookings (id,status,revision,start_at,end_at,data)
            VALUES (%s,%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE
            status=VALUES(status),revision=VALUES(revision),start_at=VALUES(start_at),end_at=VALUES(end_at),data=VALUES(data)""",
            (
                booking["id"],
                booking["status"],
                booking["revision"],
                booking["start"],
                booking["end"],
                _json(booking),
            ),
        )

    def list_bookings(self):
        # Locking read sees latest committed capacity even under MySQL REPEATABLE READ.
        return self._read("SELECT data FROM automation_bookings ORDER BY id FOR UPDATE", many=True)

    def add_payment(self, payment):
        # Never UPDATE payment rows: duplicate references are checked by the caller.
        try:
            self._execute(
                """INSERT INTO automation_payments
                (reference,booking_id,amount_minor,currency,verified_by,verified_at,data)
                VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                (
                    payment["reference"],
                    payment["booking_id"],
                    payment["amount_minor"],
                    payment["currency"],
                    payment["verified_by"],
                    payment["verified_at"],
                    _json(payment),
                ),
            )
            return True
        except pymysql.IntegrityError as error:
            if error.args[0] == 1062:
                return False
            raise

    def payments(self, booking_id):
        return self._read(
            "SELECT data FROM automation_payments WHERE booking_id=%s ORDER BY reference FOR UPDATE",
            (booking_id,),
            many=True,
        )

    def get_payment(self, reference):
        return self._read(
            "SELECT data FROM automation_payments WHERE reference=%s FOR UPDATE", (reference,)
        )

    def enqueue(self, key, kind, booking_id, revision, payload=None):
        if self.get_outbox(key):
            return False
        data = {
            "key": key,
            "kind": kind,
            "booking_id": booking_id,
            "revision": revision,
            "payload": payload or {},
            "status": "pending",
            "attempts": 0,
            "created_at": utc_now(),
        }
        self._execute(
            "INSERT INTO automation_outbox (job_key,booking_id,status,data) VALUES (%s,%s,%s,%s)",
            (key, booking_id, "pending", _json(data)),
        )
        return True

    def get_outbox(self, key):
        return self._read("SELECT data FROM automation_outbox WHERE job_key=%s FOR UPDATE", (key,))

    def list_outbox(self, limit=None, statuses=None):
        query = "SELECT data FROM automation_outbox ORDER BY id"
        args = ()
        if statuses is not None:
            if not statuses:
                return []
            query = (
                "SELECT data FROM automation_outbox WHERE status IN ("
                + ",".join(["%s"] * len(statuses))
                + ") ORDER BY id"
            )
            args = tuple(statuses)
        if limit is not None:
            query += " LIMIT %s"
            args += (int(limit),)
        return self._read(query + " FOR UPDATE", args, many=True)

    def save_outbox(self, job):
        self._execute(
            "UPDATE automation_outbox SET status=%s,data=%s WHERE job_key=%s",
            (job["status"], _json(job), job["key"]),
        )

    def get_delivery(self, key):
        return self._read(
            "SELECT data FROM automation_deliveries WHERE delivery_key=%s FOR UPDATE", (key,)
        )

    def save_delivery(self, delivery):
        self._execute(
            """INSERT INTO automation_deliveries (delivery_key,data) VALUES (%s,%s)
            ON DUPLICATE KEY UPDATE data=VALUES(data)""",
            (delivery["key"], _json(delivery)),
        )

    def get_connection(self, owner_id="default"):
        return self._read(
            "SELECT data FROM automation_connections WHERE owner_id=%s FOR UPDATE", (owner_id,)
        )

    def save_connection(self, connection):
        self._execute(
            """INSERT INTO automation_connections (owner_id,data) VALUES (%s,%s)
            ON DUPLICATE KEY UPDATE data=VALUES(data)""",
            (connection.get("owner_id", "default"), _json(connection)),
        )

    def save_state(self, state):
        self._execute(
            "INSERT INTO automation_oauth_states (state_hash,session_id,expires_at,data) VALUES (%s,%s,%s,%s)",
            (
                state["state_hash"],
                state["session_id"],
                int(_epoch(state["expires_at"])),
                _json(state),
            ),
        )

    def consume_state(self, state_hash, session_id, now):
        state = self._read(
            "SELECT data FROM automation_oauth_states WHERE state_hash=%s FOR UPDATE", (state_hash,)
        )
        if not state or not hmac.compare_digest(state["session_id"], session_id):
            return None
        self._execute("DELETE FROM automation_oauth_states WHERE state_hash=%s", (state_hash,))
        return state if _epoch(state["expires_at"]) > _epoch(now) else None

    def audit(self, event, actor=None, detail=None, now=None):
        self._execute(
            "INSERT INTO automation_audit (event,actor,created_at,detail) VALUES (%s,%s,%s,%s)",
            (event, actor, str(now or utc_now()), _json(detail or {})),
        )


class Store:
    def __init__(self, settings):
        self.settings = settings
        self._local = threading.local()

    @contextmanager
    def transaction(self, capacity=False):
        if getattr(self._local, "transaction", False):
            raise RuntimeError("Booking transactions cannot be nested")
        connection = getattr(self._local, "connection", None)
        owned = connection is None
        try:
            if owned:
                connection = database.connect(self.settings)
            self._local.transaction = True
            with connection.cursor() as cursor:
                # ON DUPLICATE KEY UPDATE takes an exclusive record lock. INSERT
                # IGNORE can take shared duplicate-key locks in two transactions,
                # then deadlock when both upgrade via SELECT FOR UPDATE.
                cursor.execute(
                    "INSERT INTO automation_mutex (id) VALUES (1) ON DUPLICATE KEY UPDATE id=id"
                )
                cursor.execute("SELECT id FROM automation_mutex WHERE id=1 FOR UPDATE")
                cursor.fetchone()
            yield SQLTransaction(connection)
            connection.commit()
        except (pymysql.MySQLError, OSError):
            if connection:
                connection.rollback()
            raise StoreUnavailable("Booking persistence is unavailable") from None
        except Exception:
            if connection:
                connection.rollback()
            raise
        finally:
            self._local.transaction = False
            if owned and connection:
                connection.close()

    @contextmanager
    def booking_lock(self, booking_id):
        connection = getattr(self._local, "connection", None)
        owned = connection is None
        locked = False
        key = (
            "booking:"
            + hashlib.sha256((self.settings["DB_NAME"] + ":" + booking_id).encode()).hexdigest()[
                :48
            ]
        )
        try:
            if owned:
                connection = database.connect(self.settings)
            with connection.cursor() as cursor:
                cursor.execute("SELECT GET_LOCK(%s,10) AS acquired", (key,))
                locked = cursor.fetchone()["acquired"] == 1
            if not locked:
                raise StoreUnavailable("Booking synchronization is busy")
            self._local.connection = connection
            yield
        except (pymysql.MySQLError, OSError):
            raise StoreUnavailable("Booking persistence is unavailable") from None
        finally:
            if owned:
                self._local.connection = None
            if connection:
                try:
                    if locked:
                        with connection.cursor() as cursor:
                            cursor.execute("SELECT RELEASE_LOCK(%s)", (key,))
                finally:
                    if owned:
                        connection.close()
