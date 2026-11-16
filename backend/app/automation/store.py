"""Booking persistence and transactional outbox, using the project's MySQL database.

All transactions briefly hold one durable mutex row. This deliberately conservative
MVP serializes capacity decisions, payment reference checks and job claims across
processes. Network calls belong outside transactions; booking_lock serializes a
single booking's external provider calls independently.
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

    def get_request(self, request_id):
        return deepcopy(self.state["requests"].get(request_id))

    def save_request(self, record):
        self.state["requests"][record["id"]] = deepcopy(record)

    def list_requests(self):
        return deepcopy(list(self.state["requests"].values()))

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

    def get_checkout(self, checkout_id):
        return deepcopy(self.state["square_checkouts"].get(checkout_id))

    def checkouts(self, booking_id):
        return deepcopy(
            [
                row
                for row in self.state["square_checkouts"].values()
                if row["booking_id"] == booking_id
            ]
        )

    def get_checkout_by_order(self, order_id):
        return deepcopy(
            next(
                (
                    row
                    for row in self.state["square_checkouts"].values()
                    if row.get("provider_order_id") == order_id and order_id
                ),
                None,
            )
        )

    def expired_checkouts(self, now, limit):
        return deepcopy(
            sorted(
                (
                    row
                    for row in self.state["square_checkouts"].values()
                    if row["status"] in {"creating", "open"}
                    and row["expires_at"] <= now
                    and "square_expire:" + row["id"] not in self.state["outbox"]
                ),
                key=lambda row: row["expires_at"],
            )[:limit]
        )

    def save_checkout(self, checkout):
        if any(
            row["id"] != checkout["id"]
            and any(
                checkout.get(key) and row.get(key) == checkout[key]
                for key in ("provider_link_id", "provider_order_id")
            )
            for row in self.state["square_checkouts"].values()
        ):
            raise ValueError("Square resource already belongs to another checkout")
        self.state["square_checkouts"][checkout["id"]] = deepcopy(checkout)

    def get_square_event(self, event_id):
        return deepcopy(self.state["square_events"].get(event_id))

    def save_square_event(self, event):
        self.state["square_events"][event["id"]] = deepcopy(event)

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
        self._state["requests"] = {}
        self._state["square_checkouts"] = {}
        self._state["square_events"] = {}
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

    def get_request(self, request_id):
        return self._read(
            "SELECT data FROM automation_requests WHERE id=%s FOR UPDATE", (request_id,)
        )

    def save_request(self, record):
        self._execute(
            "INSERT INTO automation_requests (id,order_id,data) VALUES (%s,%s,%s) "
            "ON DUPLICATE KEY UPDATE data=VALUES(data)",
            (record["id"], record["source_order_id"], _json(record)),
        )

    def list_requests(self):
        return self._read(
            "SELECT data FROM automation_requests ORDER BY order_id FOR UPDATE", many=True
        )

    def request_boundary(self):
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT COALESCE(MAX(id),0) AS boundary FROM orders")
            return int(cursor.fetchone()["boundary"])

    def request_orders(self, boundary, enabled=True, limit=100, order_id=None):
        # Orders themselves are durable intake intent. A dispatcher crash cannot
        # lose a committed request; a later sweep finds it again. This consistent
        # read takes no order row locks while holding the automation mutex.
        return self._read(
            "SELECT o.response_json AS data FROM orders o "
            "LEFT JOIN automation_requests r ON r.order_id=o.public_id "
            "LEFT JOIN automation_order_links l ON l.order_id=o.public_id "
            "WHERE l.order_id IS NULL AND ((r.id IS NULL AND "
            "o.id > %s AND %s) OR "
            "(r.id IS NOT NULL AND o.version > JSON_EXTRACT(r.data,'$.source_version'))) "
            "AND (%s IS NULL OR o.public_id=%s) ORDER BY o.id LIMIT %s",
            (boundary, enabled, order_id, order_id, limit),
            many=True,
        )

    def save_booking(self, booking):
        from .domain import DomainError

        if booking["status"] == "cancelled":
            self._execute(
                "UPDATE inventory_items i JOIN inventory_reservations r ON r.item_id=i.id "
                "SET i.version=i.version+1 WHERE r.booking_id=%s AND r.active=1",
                (booking["id"],),
            )
            self._execute(
                "UPDATE inventory_reservations SET active=0 WHERE booking_id=%s", (booking["id"],)
            )
        else:
            with self.connection.cursor() as cursor:
                cursor.execute(
                    "SELECT COALESCE(SUM(quantity),0) AS total FROM inventory_reservations WHERE booking_id=%s AND active=1",
                    (booking["id"],),
                )
                allocated = cursor.fetchone()["total"]
                if allocated and allocated > booking.get("quantity", 0):
                    raise DomainError(
                        "Reduce flavor allocations before lowering the booking quantity.",
                        409,
                        "stock_conflict",
                    )
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
        # The ledger is append-only. Shared locking reads see committed rows
        # without requiring UPDATE privileges; the transaction mutex serializes
        # payment insertion and booking decisions.
        return self._read(
            "SELECT data FROM automation_payments WHERE booking_id=%s ORDER BY reference FOR SHARE",
            (booking_id,),
            many=True,
        )

    def get_payment(self, reference):
        return self._read(
            "SELECT data FROM automation_payments WHERE reference=%s FOR SHARE", (reference,)
        )

    def get_checkout(self, checkout_id):
        return self._read(
            "SELECT data FROM square_checkouts WHERE id=%s FOR UPDATE", (checkout_id,)
        )

    def checkouts(self, booking_id):
        return self._read(
            "SELECT data FROM square_checkouts WHERE booking_id=%s FOR UPDATE",
            (booking_id,),
            many=True,
        )

    def save_checkout(self, checkout):
        if self.get_checkout(checkout["id"]):
            self._execute(
                "UPDATE square_checkouts SET provider_link_id=%s,provider_order_id=%s,status=%s,expires_at=%s,data=%s WHERE id=%s",
                (
                    checkout.get("provider_link_id"),
                    checkout.get("provider_order_id"),
                    checkout["status"],
                    checkout["expires_at"],
                    _json(checkout),
                    checkout["id"],
                ),
            )
        else:
            self._execute(
                "INSERT INTO square_checkouts (id,booking_id,provider_link_id,provider_order_id,status,expires_at,data) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (
                    checkout["id"],
                    checkout["booking_id"],
                    checkout.get("provider_link_id"),
                    checkout.get("provider_order_id"),
                    checkout["status"],
                    checkout["expires_at"],
                    _json(checkout),
                ),
            )

    def get_checkout_by_order(self, order_id):
        return self._read(
            "SELECT data FROM square_checkouts WHERE provider_order_id=%s FOR UPDATE", (order_id,)
        )

    def expired_checkouts(self, now, limit):
        return self._read(
            "SELECT data FROM square_checkouts AS c WHERE status IN ('creating','open') AND expires_at<=%s AND NOT EXISTS (SELECT 1 FROM automation_outbox AS o WHERE o.job_key=CONCAT('square_expire:',c.id)) ORDER BY expires_at,id LIMIT %s FOR UPDATE",
            (int(now), limit),
            many=True,
        )

    def get_square_event(self, event_id):
        return self._read("SELECT data FROM square_events WHERE id=%s FOR SHARE", (event_id,))

    def save_square_event(self, event):
        self._execute(
            "INSERT INTO square_events (id,data) VALUES (%s,%s)", (event["id"], _json(event))
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
