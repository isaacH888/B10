"""POST /api/v1/orders: submit one order (OpenAPI ``submitOrder``).

Contract (docs/api/openapi.json, docs/api-contract.md "Submit order"):
  - Body is ``SubmitOrderRequest``; the response is ``OrderResponse`` with HTTP 201.
  - ``Idempotency-Key`` is mandatory. The same key and payload replays the original
    order; the same key with a different payload is 409 ``idempotency_conflict``.
  - Client totals are never accepted (unknown keys are rejected). Pricing is always
    recomputed here with the quote engine, in exact integer cents (Fraction).

Known gaps, tracked in docs/decisions-and-blockers.md (T08):
  - Quotes are not persisted yet, so ``quote_id`` is validated and stored as the
    reference, but expiry/revision/equality lookups (409 ``quote_expired`` and
    ``quote_mismatch``) cannot be enforced until a quote store exists.
  - Bryson's schema is not in the repository. ``_save_in_database`` assumes the
    tables and columns it names and must be aligned with the approved migration.
    Without database credentials the order lives in a per-process memory store.
"""

import hashlib
import json
import re
import threading
import uuid
from datetime import datetime, timezone

import pymysql
from flask import Blueprint, current_app, g, jsonify, request

from .health import connection_options, database_configured
from .quotes import (
    _CONTRACT_FIELD_PATHS,
    QuoteError,
    calculate_order_quote,
    contract_priced_quote,
    normalize_quote_payload,
    validate_quote_payload,
)

orders_bp = Blueprint("orders", __name__)

_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9_-]+$")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$")
_PHONE = re.compile(r"^\+?[0-9 ().-]+$")
_TIMEZONE = re.compile(r"^[A-Za-z][A-Za-z0-9_+-]*(/[A-Za-z0-9_+-]+)*$")
_COUNTRY = re.compile(r"^[A-Z]{2}$")


class IdempotencyConflict(Exception):
    """The Idempotency-Key was already used with a different payload."""


@orders_bp.record_once
def _create_memory_store(state):
    state.app.extensions["orders_memory"] = {"lock": threading.Lock(), "orders": {}}


# --------------------------------------------------------------------------- #
# Validation (SubmitOrderRequest); collects every failure, never raises
# --------------------------------------------------------------------------- #

def _field(path, message):
    return {"field": path, "message": message}


def _join(path, key):
    return f"{path}.{key}" if path else key


def _object(errors, value, path, required, optional=()):
    """Return ``value`` when it is an object; report missing and unknown keys."""
    if not isinstance(value, dict):
        errors.append(_field(path or "body", "must be an object"))
        return None
    for key in required:
        if key not in value:
            errors.append(_field(_join(path, key), "is required"))
    for key in value:
        if key not in required and key not in optional:
            errors.append(_field(_join(path, key), "is not allowed"))
    return value


def _string(errors, data, key, path, limit, blank=False):
    """Trimmed string of 1..limit characters (0..limit when ``blank``); None when absent or invalid."""
    if key not in data:
        return None
    field = _join(path, key)
    value = data[key]
    if not isinstance(value, str):
        errors.append(_field(field, "must be a string"))
        return None
    value = value.strip()
    if not value and not blank:
        errors.append(_field(field, "must not be empty"))
    elif len(value) > limit:
        errors.append(_field(field, f"must be at most {limit} characters"))
    return value


def _integer(errors, data, key, path, minimum, maximum):
    value = data.get(key)
    if key not in data:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        errors.append(_field(_join(path, key), "must be an integer"))
        return None
    if not minimum <= value <= maximum:
        errors.append(_field(_join(path, key), f"must be between {minimum} and {maximum}"))
    return value


def _choice(errors, data, key, path, allowed):
    value = data.get(key)
    if key in data and value not in allowed:
        errors.append(_field(_join(path, key), "must be one of: " + ", ".join(allowed)))
    return value


def _timestamp(errors, data, key, path):
    """Return ``(text, datetime)`` for an ISO 8601 date-time that carries a UTC offset."""
    text = _string(errors, data, key, path, 40)
    if not text:
        return text, None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        parsed = None
    if parsed is None or parsed.tzinfo is None:
        errors.append(_field(_join(path, key), "must be an ISO 8601 date-time with a UTC offset"))
        return text, None
    return text, parsed


def _customer(errors, value):
    data = _object(errors, value, "customer", ("name", "email", "phone"))
    if data is None:
        return None
    name = _string(errors, data, "name", "customer", 150)
    email = _string(errors, data, "email", "customer", 254)
    phone = _string(errors, data, "phone", "customer", 30)
    if email and not _EMAIL.match(email):
        errors.append(_field("customer.email", "must be a valid email address"))
    if phone and (not _PHONE.match(phone) or sum(char.isdigit() for char in phone) < 7):
        errors.append(_field("customer.phone", "must be a valid phone number"))
    return {"name": name, "email": email, "phone": phone}


def _add_ons(errors, data):
    path = "catering_request.add_ons"
    items = data.get("add_ons", [])
    if not isinstance(items, list):
        errors.append(_field(path, "must be an array"))
        return None
    cleaned = []
    for index, item in enumerate(items):
        text = item.strip() if isinstance(item, str) else ""
        if 1 <= len(text) <= 100:
            cleaned.append(text)
        else:
            errors.append(_field(f"{path}[{index}]", "must be text of 1 to 100 characters"))
    if len(items) > 20:
        errors.append(_field(path, "must contain at most 20 items"))
    if len(set(cleaned)) != len(cleaned):
        errors.append(_field(path, "must contain unique items"))
    return cleaned


def _catering_request(errors, value):
    path = "catering_request"
    data = _object(errors, value, path, ("quantity", "popsicle_shape", "service_type"),
                   ("flavor_requests", "add_ons", "dry_ice_blocks"))
    if data is None:
        return None
    dry_ice = data.get("dry_ice_blocks")
    return {
        "quantity": _integer(errors, data, "quantity", path, 50, 100000),
        "popsicle_shape": _choice(errors, data, "popsicle_shape", path, ("standard", "heart")),
        "flavor_requests": _string(errors, data, "flavor_requests", path, 2000, blank=True) or "",
        "add_ons": _add_ons(errors, data),
        "service_type": _choice(errors, data, "service_type", path, ("delivery", "full_service")),
        "dry_ice_blocks": None if dry_ice is None else _integer(errors, data, "dry_ice_blocks", path, 0, 1000),
    }


def _location(errors, value):
    path = "event.location"
    data = _object(errors, value, path, ("line1", "city", "region", "postal_code", "country_code"), ("line2",))
    if data is None:
        return None
    location = {
        "line1": _string(errors, data, "line1", path, 200),
        "city": _string(errors, data, "city", path, 100),
        "region": _string(errors, data, "region", path, 100),
        "postal_code": _string(errors, data, "postal_code", path, 20),
        "country_code": _string(errors, data, "country_code", path, 2),
    }
    if "line2" in data:
        location["line2"] = _string(errors, data, "line2", path, 200, blank=True)
    if location["country_code"] and not _COUNTRY.match(location["country_code"]):
        errors.append(_field("event.location.country_code", "must be an uppercase ISO 3166-1 alpha-2 code"))
    return location


def _event(errors, value):
    path = "event"
    data = _object(errors, value, path, ("type", "location", "starts_at", "timezone"), ("ends_at", "notes"))
    if data is None:
        return None
    zone = _string(errors, data, "timezone", path, 100)
    if zone and not _TIMEZONE.match(zone):
        errors.append(_field("event.timezone", "must be an IANA time zone name"))
    starts_text, starts_at = _timestamp(errors, data, "starts_at", path)
    if starts_at and starts_at <= datetime.now(timezone.utc):
        errors.append(_field("event.starts_at", "must be in the future"))
    ends_text = None
    if data.get("ends_at") is not None:
        ends_text, ends_at = _timestamp(errors, data, "ends_at", path)
        if starts_at and ends_at and ends_at <= starts_at:
            errors.append(_field("event.ends_at", "must be after starts_at"))
    return {
        "type": _string(errors, data, "type", path, 100),
        "location": _location(errors, data["location"]) if "location" in data else None,
        "starts_at": starts_text,
        "ends_at": ends_text,
        "timezone": zone,
        "notes": _string(errors, data, "notes", path, 2000, blank=True) or "",
    }


def validate_order_request(body):
    """Return ``(clean_request, errors)``; ``errors`` is a list of ``{field, message}``."""
    errors = []
    data = _object(errors, body, "", ("customer", "catering_request", "event", "quote_id"))
    if data is None:
        return None, errors
    quote_id = _string(errors, data, "quote_id", "", 100)
    if quote_id and not _IDENTIFIER.match(quote_id):
        errors.append(_field("quote_id", "may contain only letters, digits, underscores and hyphens"))
    clean = {
        "customer": _customer(errors, data["customer"]) if "customer" in data else None,
        "catering_request": _catering_request(errors, data["catering_request"]) if "catering_request" in data else None,
        "event": _event(errors, data["event"]) if "event" in data else None,
        "quote_id": quote_id,
    }
    return clean, errors


# --------------------------------------------------------------------------- #
# Pricing and order snapshot
# --------------------------------------------------------------------------- #

def _price(rules, clean):
    """Recompute the server price with the quote engine (integer cents, Fraction)."""
    raw = {"catering_request": clean["catering_request"], "event": clean["event"]}
    validated = validate_quote_payload(rules, normalize_quote_payload(raw))
    return contract_priced_quote(rules, raw, validated, calculate_order_quote(rules, validated))


def _utc_text(moment):
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _build_order(clean, quote):
    now = _utc_text(datetime.now(timezone.utc))
    pricing = quote["pricing"]
    return {
        "id": f"order_{uuid.uuid4().hex}",
        "version": 1,
        "status": "pending_review",
        "customer": clean["customer"],
        "catering_request": clean["catering_request"],
        "event": clean["event"],
        "quote_id": clean["quote_id"],
        "pricing_revision": quote["pricing_revision"],
        "pricing": pricing,
        "deposit": {"status": "pending", "amount_due_cents": pricing["deposit_due_cents"],
                    "amount_confirmed_cents": 0},
        "payment_links": [],
        "workflow": {"customer_email": "pending", "business_email": "pending",
                     "calendar": "not_scheduled", "contract_email": "waiting_for_deposit"},
        "created_at": now,
        "updated_at": now,
    }


# --------------------------------------------------------------------------- #
# Persistence: both savers return the stored order (the original one on replay)
# --------------------------------------------------------------------------- #

def _save_in_memory(key, digest, order):
    store = current_app.extensions["orders_memory"]
    with store["lock"]:
        saved = store["orders"].setdefault(key, (digest, order))
    if saved[0] != digest:
        raise IdempotencyConflict
    return saved[1]


def _save_in_database(key, digest, order):
    """Insert customer, order and items in one transaction: commit on success, roll back on any error."""
    connection = pymysql.connect(**connection_options(current_app.config))
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT request_hash, response_json FROM orders WHERE idempotency_key = %s", (key,))
            row = cursor.fetchone()
            if row:
                if row[0] != digest:
                    raise IdempotencyConflict
                connection.rollback()
                return json.loads(row[1])
            customer = order["customer"]
            cursor.execute("INSERT INTO customers (name, email, phone) VALUES (%s, %s, %s)",
                           (customer["name"], customer["email"], customer["phone"]))
            starts_at = datetime.fromisoformat(order["event"]["starts_at"]).astimezone(timezone.utc)
            cursor.execute(
                "INSERT INTO orders (public_id, customer_id, status, version, quote_id, pricing_revision,"
                " total_cents, deposit_due_cents, event_starts_at, event_timezone, idempotency_key,"
                " request_hash, response_json) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (order["id"], cursor.lastrowid, order["status"], order["version"], order["quote_id"],
                 order["pricing_revision"], order["pricing"]["total_cents"], order["pricing"]["deposit_due_cents"],
                 starts_at.replace(tzinfo=None), order["event"]["timezone"], key, digest,
                 json.dumps(order, separators=(",", ":"))))
            cursor.executemany(
                "INSERT INTO order_items (order_id, code, description, amount_cents) VALUES (%s, %s, %s, %s)",
                [(cursor.lastrowid, item["code"], item["description"], item["amount_cents"])
                 for item in order["pricing"]["line_items"]])
        connection.commit()
        return order
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


# --------------------------------------------------------------------------- #
# HTTP layer
# --------------------------------------------------------------------------- #

def _error(status, code, message, fields=()):
    return jsonify(error={"code": code, "message": message, "fields": list(fields),
                          "request_id": g.request_id}), status


@orders_bp.post("/orders")
def submit_order():
    if not request.is_json:
        return _error(415, "unsupported_media_type", "Use application/json for this request.")
    try:
        body = json.loads(request.get_data())
    except ValueError:
        return _error(400, "bad_request", "The request could not be parsed.")

    key = request.headers.get("Idempotency-Key", "").strip()
    clean, errors = validate_order_request(body)
    if not _IDEMPOTENCY_KEY.match(key):
        errors.insert(0, _field("Idempotency-Key", "must be 16 to 128 letters, digits, underscores or hyphens"))
    if errors:
        return _error(422, "validation_error", "One or more fields are invalid.", errors)

    try:
        quote = _price(current_app.extensions["pricing_rules"], clean)
    except QuoteError as error:
        return _error(422, "validation_error", error.message,
                      [_field(_CONTRACT_FIELD_PATHS.get(error.field, error.field or "body"), error.message)])

    order = _build_order(clean, quote)
    digest = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    save = _save_in_database if database_configured(current_app.config) else _save_in_memory
    try:
        saved = save(key, digest, order)
    except IdempotencyConflict:
        return _error(409, "idempotency_conflict", "The Idempotency-Key was already used with a different request.")
    except (pymysql.MySQLError, OSError):
        # Driver messages can include private connection details.
        current_app.logger.error("Order persistence failed; request_id=%s", g.request_id)
        return _error(503, "service_unavailable", "A required service is temporarily unavailable.")

    response = jsonify(data=saved, meta={"request_id": g.request_id})
    response.status_code = 201
    response.headers["Location"] = f"/api/v1/orders/{saved['id']}"
    return response
