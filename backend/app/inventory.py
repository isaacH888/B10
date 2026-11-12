"""Owner-only durable stock operations, with audited replay and explicit allocations."""

import hashlib
import json
import re
from datetime import timezone
from uuid import uuid4

import pymysql
from flask import Blueprint, current_app, g, jsonify, request

from . import database
from .admin_orders import _owner
from .auth.errors import AuthError
from .auth.guards import require_admin
from .automation.store import Store
from .health import database_configured

inventory = Blueprint("inventory", __name__)
ITEMS = """SELECT i.*,COALESCE(r.reserved,0) AS reserved FROM inventory_items i
LEFT JOIN (SELECT item_id,SUM(quantity) AS reserved FROM inventory_reservations
WHERE active=1 GROUP BY item_id) r ON r.item_id=i.id"""


@inventory.errorhandler(pymysql.MySQLError)
@inventory.errorhandler(OSError)
def database_unavailable(error):
    return jsonify(
        error={
            "code": "service_unavailable",
            "message": "Inventory storage is temporarily unavailable.",
            "fields": [],
            "request_id": g.request_id,
        }
    ), 503


def require_storage():
    _owner()
    if not database_configured(current_app.config):
        raise AuthError(
            "service_unavailable", "Inventory requires configured database storage.", 503
        )


def output(data, status=200):
    return jsonify(data=data, meta={"request_id": g.request_id}), status


def integer(value, name, minimum=0, maximum=1000000000):
    if type(value) is not int or not minimum <= value <= maximum:
        raise AuthError(
            "validation_error", f"{name} must be a whole number from {minimum} to {maximum}.", 422
        )
    return value


def text(value, name, maximum, blank=False):
    if (
        not isinstance(value, str)
        or len(value.strip()) > maximum
        or (not blank and not value.strip())
    ):
        raise AuthError(
            "validation_error",
            f"{name} must contain {'0' if blank else '1'} to {maximum} characters.",
            422,
        )
    return value.strip()


def body(required, optional=()):
    data = request.get_json(silent=True)
    if (
        not request.is_json
        or not isinstance(data, dict)
        or set(data) - set(required) - set(optional)
        or set(required) - set(data)
    ):
        raise AuthError(
            "validation_error",
            "Send the required fields in a JSON object, without unknown fields.",
            422,
        )
    return data


def item_view(row):
    reserved = int(row["reserved"])
    return {
        "id": row["id"],
        "name": row["name"],
        "category": row["category"],
        "shape": row["shape"],
        "onHand": row["on_hand"],
        "reserved": reserved,
        "available": row["on_hand"] - reserved,
        "minimum": row["minimum"],
        "notes": row["notes"],
        "version": row["version"],
        "active": bool(row["active"]),
    }


def read_item(cursor, item_id, active=True):
    if not re.fullmatch(r"[a-f0-9]{32}", item_id):
        raise AuthError("not_found", "Inventory item not found.", 404)
    cursor.execute(ITEMS + " WHERE i.id=%s", (item_id,))
    row = cursor.fetchone()
    if row is None or (active and not row["active"]):
        raise AuthError("not_found", "Inventory item not found.", 404)
    return item_view(row)


def mutate(data, action):
    key = request.headers.get("Idempotency-Key", "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", key):
        raise AuthError("validation_error", "Supply a 16-128 character Idempotency-Key.", 422)
    actor = g.principal["identity_id"]
    scoped = hashlib.sha256(f"{actor}:{request.method}:{request.path}:{key}".encode()).hexdigest()
    digest = hashlib.sha256(
        json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    with Store(current_app.config).transaction() as tx, tx.connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO inventory_actions (action_key,request_hash,created_at) VALUES (%s,%s,UTC_TIMESTAMP(6)) ON DUPLICATE KEY UPDATE action_key=action_key",
            (scoped, digest),
        )
        cursor.execute(
            "SELECT request_hash,response_json FROM inventory_actions WHERE action_key=%s",
            (scoped,),
        )
        previous = cursor.fetchone()
        if previous["request_hash"] != digest:
            raise AuthError(
                "idempotency_conflict", "This action key belongs to a different request.", 409
            )
        if previous["response_json"] is not None:
            return json.loads(previous["response_json"])
        result = action(tx, cursor, actor)
        cursor.execute(
            "UPDATE inventory_actions SET response_json=%s WHERE action_key=%s",
            (json.dumps(result), scoped),
        )
        return result


def version(data, item):
    expected = integer(data["expected_version"], "expected_version", 1, 2**31 - 1)
    if expected != item["version"]:
        raise AuthError("stale_version", "This item changed. Refresh before trying again.", 409)


def history(cursor, item_id, kind, quantity, before, after, reason, note, actor):
    cursor.execute(
        "INSERT INTO inventory_history (item_id,type,quantity,before_count,after_count,reason,note,actor,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,UTC_TIMESTAMP(6))",
        (item_id, kind, quantity, before, after, reason, note, actor),
    )


@inventory.get("/admin/inventory")
@require_admin("bookings:read")
def list_items():
    require_storage()
    if request.args:
        raise AuthError(
            "validation_error", "Inventory catalog does not accept query parameters.", 422
        )
    with database.connect(current_app.config) as connection, connection.cursor() as cursor:
        cursor.execute(ITEMS + " WHERE i.active=1 ORDER BY i.name,i.id")
        items = [item_view(row) for row in cursor.fetchall()]
    return output({"items": items})


@inventory.post("/admin/inventory")
@require_admin("bookings:read")
def create_item():
    require_storage()
    data = body(("name", "category", "shape", "onHand", "minimum", "notes"))
    fields = {
        key: text(data[key], key, limit, key == "notes")
        for key, limit in (("name", 100), ("category", 40), ("shape", 40), ("notes", 2000))
    }
    count, minimum = integer(data["onHand"], "onHand"), integer(data["minimum"], "minimum", 1)

    def create(tx, cursor, actor):
        item_id = uuid4().hex
        cursor.execute(
            "INSERT INTO inventory_items (id,name,category,shape,on_hand,minimum,notes,version,active) VALUES (%s,%s,%s,%s,%s,%s,%s,1,1)",
            (
                item_id,
                fields["name"],
                fields["category"],
                fields["shape"],
                count,
                minimum,
                fields["notes"],
            ),
        )
        history(cursor, item_id, "add", count, 0, count, "Initial stock", "", actor)
        tx.audit("inventory.created", actor, {"item_id": item_id})
        return {"item": read_item(cursor, item_id)}

    return output(mutate(data, create), 201)


@inventory.patch("/admin/inventory/<item_id>")
@require_admin("bookings:read")
def update_item(item_id):
    require_storage()
    data = body(("expected_version",), ("name", "category", "shape", "minimum", "notes"))
    if len(data) == 1:
        raise AuthError("validation_error", "Supply at least one item field to update.", 422)
    changes = {
        key: text(data[key], key, limit, key == "notes")
        for key, limit in (("name", 100), ("category", 40), ("shape", 40), ("notes", 2000))
        if key in data
    }
    if "minimum" in data:
        changes["minimum"] = integer(data["minimum"], "minimum", 1)

    def update(tx, cursor, actor):
        item = read_item(cursor, item_id)
        version(data, item)
        assignments = ",".join(key + "=%s" for key in changes)
        cursor.execute(
            "UPDATE inventory_items SET " + assignments + ",version=version+1 WHERE id=%s",
            [*changes.values(), item_id],
        )
        tx.audit("inventory.updated", actor, {"item_id": item_id})
        return {"item": read_item(cursor, item_id)}

    return output(mutate(data, update))


@inventory.post("/admin/inventory/<item_id>/adjust")
@require_admin("bookings:read")
def adjust_item(item_id):
    require_storage()
    data = body(("expected_version", "type", "quantity", "reason"), ("note",))
    kind = data["type"]
    if kind not in ("add", "remove", "set"):
        raise AuthError("validation_error", "Stock adjustment must be add, remove or set.", 422)
    qty = integer(data["quantity"], "quantity", 0 if kind == "set" else 1)
    reason = text(data["reason"], "reason", 100)
    note = text(data.get("note", ""), "note", 2000, True)

    def adjust(tx, cursor, actor):
        item = read_item(cursor, item_id)
        version(data, item)
        after = (
            item["onHand"] + qty
            if kind == "add"
            else item["onHand"] - qty
            if kind == "remove"
            else qty
        )
        if not item["reserved"] <= after <= 1000000000:
            raise AuthError(
                "stock_conflict",
                "Stock cannot fall below reserved units or exceed the supported limit.",
                409,
            )
        cursor.execute(
            "UPDATE inventory_items SET on_hand=%s,version=version+1 WHERE id=%s", (after, item_id)
        )
        history(cursor, item_id, kind, qty, item["onHand"], after, reason, note, actor)
        tx.audit("inventory.stock_adjusted", actor, {"item_id": item_id})
        return {"item": read_item(cursor, item_id)}

    return output(mutate(data, adjust))


@inventory.delete("/admin/inventory/<item_id>")
@require_admin("bookings:read")
def archive_item(item_id):
    require_storage()
    data = body(("expected_version",))

    def archive(tx, cursor, actor):
        item = read_item(cursor, item_id)
        version(data, item)
        if item["reserved"]:
            raise AuthError(
                "stock_conflict",
                "Release this item's booking allocations before archiving it.",
                409,
            )
        cursor.execute(
            "UPDATE inventory_items SET active=0,version=version+1 WHERE id=%s", (item_id,)
        )
        tx.audit("inventory.archived", actor, {"item_id": item_id})
        return {"ok": True}

    return output(mutate(data, archive))


@inventory.get("/admin/inventory/<item_id>/history")
@require_admin("bookings:read")
def stock_history(item_id):
    require_storage()
    if set(request.args) - {"page", "page_size"} or any(
        len(request.args.getlist(k)) != 1 for k in request.args
    ):
        raise AuthError("validation_error", "Use non-repeated page and page_size parameters.", 422)
    try:
        page, size = int(request.args.get("page", "1")), int(request.args.get("page_size", "25"))
        if not (1 <= page <= 1000000 and 1 <= size <= 100):
            raise ValueError
    except ValueError:
        raise AuthError("validation_error", "Invalid history page or page size.", 422) from None
    with database.connect(current_app.config) as connection, connection.cursor() as cursor:
        read_item(cursor, item_id, active=False)
        cursor.execute(
            "SELECT COUNT(*) AS total FROM inventory_history WHERE item_id=%s", (item_id,)
        )
        total = cursor.fetchone()["total"]
        cursor.execute(
            "SELECT type,quantity,before_count,after_count,reason,note,actor,created_at FROM inventory_history WHERE item_id=%s ORDER BY id DESC LIMIT %s OFFSET %s",
            (item_id, size, (page - 1) * size),
        )
        rows = [
            {
                "type": row["type"],
                "qty": row["quantity"],
                "before": row["before_count"],
                "after": row["after_count"],
                "reason": row["reason"],
                "note": row["note"],
                "actor": row["actor"],
                "date": row["created_at"].replace(tzinfo=timezone.utc).isoformat(),
            }
            for row in cursor.fetchall()
        ]
    return output({"history": rows, "total": total, "page": page, "page_size": size})


@inventory.post("/admin/inventory/bookings/<booking_id>/allocations")
@require_admin("bookings:read")
def allocate_booking(booking_id):
    require_storage()
    data = body(("expected_revision", "items"))
    expected = integer(data["expected_revision"], "expected_revision", 0, 2**31 - 1)
    if not isinstance(data["items"], list) or len(data["items"]) > 100:
        raise AuthError("validation_error", "Supply at most 100 allocation rows.", 422)
    allocations = {}
    for item in data["items"]:
        if (
            not isinstance(item, dict)
            or set(item) != {"item_id", "quantity"}
            or not isinstance(item["item_id"], str)
            or item["item_id"] in allocations
        ):
            raise AuthError(
                "validation_error", "Each allocation needs a distinct item_id and quantity.", 422
            )
        allocations[item["item_id"]] = integer(item["quantity"], "quantity", 1)

    def allocate(tx, cursor, actor):
        booking = tx.get_booking(booking_id)
        if not booking:
            raise AuthError("not_found", "Booking not found.", 404)
        if booking["revision"] != expected:
            raise AuthError("stale_version", "Refresh the booking before allocating stock.", 409)
        if allocations and booking["status"] != "confirmed":
            raise AuthError("invalid_transition", "Only confirmed bookings can reserve stock.", 409)
        if sum(allocations.values()) > booking["quantity"]:
            raise AuthError(
                "stock_conflict", "Allocated units cannot exceed the booking quantity.", 409
            )
        cursor.execute(
            "SELECT item_id,quantity FROM inventory_reservations WHERE booking_id=%s AND active=1",
            (booking_id,),
        )
        old = {row["item_id"]: row["quantity"] for row in cursor.fetchall()}
        for item_id, qty in allocations.items():
            item = read_item(cursor, item_id)
            if qty > item["available"] + old.get(item_id, 0):
                raise AuthError(
                    "stock_conflict", "Not enough available stock for this allocation.", 409
                )
        cursor.execute(
            "UPDATE inventory_reservations SET active=0 WHERE booking_id=%s", (booking_id,)
        )
        for item_id, qty in allocations.items():
            cursor.execute(
                "INSERT INTO inventory_reservations (booking_id,item_id,quantity,active) VALUES (%s,%s,%s,1) ON DUPLICATE KEY UPDATE quantity=VALUES(quantity),active=1",
                (booking_id, item_id, qty),
            )
        for item_id in set(old) | set(allocations):
            cursor.execute("UPDATE inventory_items SET version=version+1 WHERE id=%s", (item_id,))
        booking["revision"] += 1
        tx.save_booking(booking)
        tx.audit(
            "inventory.allocations_updated", actor, {"booking_id": booking_id, "items": allocations}
        )
        return {
            "booking_id": booking_id,
            "revision": booking["revision"],
            "items": [{"item_id": k, "quantity": v} for k, v in allocations.items()],
        }

    return output(mutate(data, allocate))


@inventory.get("/admin/inventory/bookings/<booking_id>/allocations")
@require_admin("bookings:read")
def read_allocations(booking_id):
    require_storage()
    if not re.fullmatch(r"[a-f0-9]{32}", booking_id) or request.args:
        raise AuthError("not_found", "Booking not found.", 404)
    with database.connect(current_app.config) as connection, connection.cursor() as cursor:
        cursor.execute("SELECT revision FROM automation_bookings WHERE id=%s", (booking_id,))
        booking = cursor.fetchone()
        if not booking:
            raise AuthError("not_found", "Booking not found.", 404)
        cursor.execute(
            "SELECT item_id,quantity FROM inventory_reservations WHERE booking_id=%s AND active=1 ORDER BY item_id",
            (booking_id,),
        )
        rows = cursor.fetchall()
    return output({"booking_id": booking_id, "revision": booking["revision"], "items": rows})
