"""Quote calculation: Python port of the legacy Node pricing implementation.

Ported from docs/reference/legacy-node:
  - configLoader.js     -> load_business_rules()
  - quoteValidator.js   -> validate_quote_payload()
  - feeCalculator.js    -> calculate_heart_shape_surcharge() & friends
  - pricingEngine.js    -> calculate_order_quote()

Contract adaptations (docs/api-contract.md), the only intentional differences:
  - Route is ``POST /quotes`` under ``/api/v1``.
  - Money is integer cents (``*_cents``); the legacy float dollars are gone.
    All arithmetic is exact (Fraction), so no float rounding drift.
  - Every validation failure is HTTP 422 ``validation_error`` with a ``fields``
    array. The legacy per-rule code (e.g. ``ERR_BELOW_MINIMUM_ORDER``) is kept
    on ``QuoteError.reason`` for services, tests and logs, not in the envelope.
  - Client decision (supersedes the legacy 400): a DELIVERY distance beyond the
    radius is not an error. It returns 200 ``requires_review`` with null pricing
    and a ``contact_inquiry`` next action, so the form can redirect the customer
    to the Custom Event Inquiry / Contact Us page. Controlled by the config's
    ``exceeded_radius_action``. Missing, non-numeric or negative distances are
    still 422.
  - Two request formats are accepted. A payload with ``catering_request`` is the
    OpenAPI ``QuoteRequest`` and gets an OpenAPI ``Quote`` response; any other
    payload is the legacy flat format and keeps the flat response envelope.
    ``normalize_quote_payload`` adapts the first format to the second so both
    share one validator and one pricing engine.

Business rules live in ``pricing.config.json`` and are never hard-coded here
beyond the legacy fallback defaults.
"""

import copy
import json
import math
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from fractions import Fraction
from pathlib import Path
from urllib.parse import urlsplit

from flask import Blueprint, current_app, g, jsonify, request

quotes_bp = Blueprint("quotes", __name__)

DEFAULT_CONFIG_PATH = Path(__file__).with_name("pricing.config.json")
VALID_SERVICE_TYPES = ("DELIVERY", "FULL_SERVICE", "PICKUP")

# Legacy ``?? default`` fallbacks (configLoader.js / ``businessRules.x?.y ?? n``),
# in the same shape as pricing.config.json's ``business_rules``.
_DEFAULT_BUSINESS_RULES = {
    "moq": {"minimum_order_quantity": 50},
    "volume_tiers": [
        {"tier_name": "Tier 1", "min_quantity": 50, "max_quantity": 99, "unit_price": 3.50},
        {"tier_name": "Tier 2", "min_quantity": 100, "max_quantity": 199, "unit_price": 3.25},
        {"tier_name": "Tier 3", "min_quantity": 200, "max_quantity": None, "unit_price": 3.00},
    ],
    "customizations": {"heart_shaped_surcharge_per_unit": 0.50},
    "logistics": {
        "dry_ice": {"price_per_block": 15.00},
        "delivery": {"base_fee": 25.00, "max_fee": 75.00, "max_radius_miles": 30.0,
                     "exceeded_radius_action": "REDIRECT_CONTACT_FORM"},
        "full_service": {"flat_fee": 150.00},
    },
    "payments": {"deposit_rate": 0.50},
}


# --------------------------------------------------------------------------- #
# Errors and small numeric helpers
# --------------------------------------------------------------------------- #

class QuoteError(Exception):
    """A validation/calculation failure (legacy ``error.code/field/rejectedValue``)."""

    def __init__(self, message, reason, field=None, rejected_value=None):
        super().__init__(message)
        self.message = message
        self.reason = reason  # legacy machine code, e.g. ERR_BELOW_MINIMUM_ORDER
        self.field = field
        self.rejected_value = rejected_value


class OutsideDeliveryRadius(QuoteError):
    """DELIVERY distance beyond the radius; routed to the contact inquiry, not a 422."""

    def __init__(self, message, distance):
        super().__init__(message, "ERR_DISTANCE_OUT_OF_RANGE", "delivery_distance_miles", distance)


def _is_number(value):
    """JS ``typeof x === 'number'`` for JSON values (bool is not a number there)."""
    if isinstance(value, bool):
        return False
    return isinstance(value, int) or (isinstance(value, float) and math.isfinite(value))


def _fraction(value):
    return Fraction(str(value))


def _round_half_up(value):
    """Round a non-negative Fraction to an int (matches ``toFixed(2)`` on dollars)."""
    return math.floor(value + Fraction(1, 2))


def _dollars_to_cents(value, name):
    if not _is_number(value) or value < 0:
        raise ValueError(f"pricing config value {name!r} must be a non-negative number")
    return _round_half_up(_fraction(value) * 100)


def _fmt(value):
    """Format like JS template literals: 30.0 -> '30', 1.5 -> '1.5'."""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _safe_text(value, limit=100):
    text = _fmt(value) if _is_number(value) else json.dumps(value, default=str)
    return text if len(text) <= limit else text[: limit - 3] + "..."


# --------------------------------------------------------------------------- #
# Configuration (configLoader.js)
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Tier:
    name: str
    min_quantity: int
    max_quantity: int | None
    unit_price_cents: int

    @property
    def label(self):
        span = f"{self.min_quantity}+" if self.max_quantity is None else f"{self.min_quantity}-{self.max_quantity}"
        return f"{self.name} ({span})"


@dataclass(frozen=True)
class PricingRules:
    minimum_order_quantity: int
    tiers: tuple
    heart_surcharge_cents: int
    dry_ice_block_cents: int
    delivery_base_cents: int
    delivery_max_cents: int
    delivery_max_radius_miles: float
    exceeded_radius_action: str
    full_service_flat_cents: int
    deposit_rate: Fraction
    revision: str = "pricing_config"


def _merge(defaults, override):
    merged = copy.deepcopy(defaults)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def parse_business_rules(business_rules, version=None):
    """Turn the ``business_rules`` JSON object (dollars) into cents-based rules."""
    rules = _merge(_DEFAULT_BUSINESS_RULES, business_rules)
    tiers = tuple(sorted(
        (Tier(name=str(t.get("tier_name", f"Tier {i}")), min_quantity=int(t["min_quantity"]),
              max_quantity=None if t.get("max_quantity") is None else int(t["max_quantity"]),
              unit_price_cents=_dollars_to_cents(t["unit_price"], "volume_tiers.unit_price"))
         for i, t in enumerate(rules["volume_tiers"], start=1)),
        key=lambda tier: tier.min_quantity))
    if not tiers:
        raise ValueError("pricing config must define at least one volume tier")
    delivery = rules["logistics"]["delivery"]
    radius = delivery["max_radius_miles"]
    deposit_rate = rules["payments"]["deposit_rate"]
    if not _is_number(radius) or radius <= 0:
        raise ValueError("pricing config delivery.max_radius_miles must be a positive number")
    if not _is_number(deposit_rate) or not 0 <= deposit_rate <= 1:
        raise ValueError("pricing config payments.deposit_rate must be between 0 and 1")
    return PricingRules(
        minimum_order_quantity=rules["moq"]["minimum_order_quantity"],
        tiers=tiers,
        heart_surcharge_cents=_dollars_to_cents(
            rules["customizations"]["heart_shaped_surcharge_per_unit"], "heart_shaped_surcharge_per_unit"),
        dry_ice_block_cents=_dollars_to_cents(
            rules["logistics"]["dry_ice"]["price_per_block"], "dry_ice.price_per_block"),
        delivery_base_cents=_dollars_to_cents(delivery["base_fee"], "delivery.base_fee"),
        delivery_max_cents=_dollars_to_cents(delivery["max_fee"], "delivery.max_fee"),
        delivery_max_radius_miles=radius,
        exceeded_radius_action=str(delivery["exceeded_radius_action"]),
        full_service_flat_cents=_dollars_to_cents(
            rules["logistics"]["full_service"]["flat_fee"], "full_service.flat_fee"),
        deposit_rate=_fraction(deposit_rate),
        revision=f"pricing_config_{version}" if isinstance(version, str) and version else "pricing_config",
    )


def load_business_rules(path=None):
    """Read pricing.config.json. Unlike the Node loader, an unreadable file is fatal.

    Quoting silently with stale hard-coded prices is not acceptable once the
    config is the client-ratified source of truth.
    """
    config_path = Path(path or DEFAULT_CONFIG_PATH)
    with config_path.open(encoding="utf-8") as handle:
        parsed = json.load(handle)
    if not isinstance(parsed, dict) or not isinstance(parsed.get("business_rules"), dict):
        raise ValueError(f"{config_path.name} must contain a 'business_rules' object")
    return parse_business_rules(parsed["business_rules"], parsed.get("version"))


@quotes_bp.record_once
def _load_rules_on_registration(state):
    app = state.app
    app.extensions["pricing_rules"] = load_business_rules(app.config.get("PRICING_CONFIG_PATH"))


# --------------------------------------------------------------------------- #
# Fee calculation (feeCalculator.js); returns integer cents
# --------------------------------------------------------------------------- #

def calculate_heart_shape_surcharge(rules, total_qty, heart_qty=0):
    if not _is_number(heart_qty) or heart_qty < 0:
        raise QuoteError("Quantities cannot be negative.", "ERR_INVALID_DATA_TYPE",
                         "heart_shaped_quantity", heart_qty)
    if heart_qty > total_qty:
        raise QuoteError("Heart-shaped popsicle quantity cannot exceed total quantity.",
                         "ERR_HEART_EXCEEDS_TOTAL", "heart_shaped_quantity", heart_qty)
    return _round_half_up(_fraction(heart_qty) * rules.heart_surcharge_cents)


def calculate_dry_ice_fee(rules, blocks=0):
    if not _is_number(blocks) or blocks < 0:
        raise QuoteError("Quantities cannot be negative.", "ERR_INVALID_DATA_TYPE", "dry_ice_blocks", blocks)
    return _round_half_up(_fraction(blocks) * rules.dry_ice_block_cents)


def calculate_logistics_fees(rules, service_type="PICKUP", distance_miles=0):
    """Return ``(delivery_fee_cents, full_service_fee_cents)``."""
    if service_type == "PICKUP":
        return 0, 0
    if service_type == "FULL_SERVICE":
        return 0, rules.full_service_flat_cents
    if service_type == "DELIVERY":
        max_radius = rules.delivery_max_radius_miles
        if not _is_number(distance_miles) or distance_miles < 0 or distance_miles > max_radius:
            raise QuoteError(f"Delivery distance must be between 0 and {_fmt(max_radius)} miles.",
                             "ERR_DISTANCE_OUT_OF_RANGE", "delivery_distance_miles", distance_miles)
        # base_fee + ((max_fee - base_fee) / max_radius_miles) * distance
        fee = rules.delivery_base_cents + (
            Fraction(rules.delivery_max_cents - rules.delivery_base_cents)
            / _fraction(max_radius) * _fraction(distance_miles))
        return _round_half_up(fee), 0
    raise QuoteError(f"Invalid service type: {_safe_text(service_type)}", "ERR_INVALID_DATA_TYPE",
                     "service_type", service_type)


# --------------------------------------------------------------------------- #
# Validation (quoteValidator.js); first failure wins, same order as legacy
# --------------------------------------------------------------------------- #

def _js_falsy(value):
    return value is None or value is False or value == 0 or value == ""


def _flavor_quantity_sum(flavors):
    total = 0
    for item in flavors:
        if item is None:
            # JS: ``null.quantity`` throws TypeError -> legacy ERR_CALCULATION_FAILED.
            raise QuoteError("Each flavor entry must be an object.", "ERR_CALCULATION_FAILED", "flavors", None)
        quantity = item.get("quantity") if isinstance(item, dict) else None  # other JS values: undefined
        if _js_falsy(quantity):
            continue
        if not _is_number(quantity):
            raise QuoteError("Flavor quantities must be numbers.", "ERR_INVALID_DATA_TYPE", "flavors", None)
        total += quantity
    return total


def validate_quote_payload(rules, payload):
    """Return the sanitized payload or raise QuoteError."""
    data = payload if isinstance(payload, dict) else {}
    total_quantity = data.get("total_quantity")
    heart_shaped_quantity = data.get("heart_shaped_quantity", 0)  # default only when absent, not null
    service_type = data.get("service_type", "PICKUP")
    delivery_distance_miles = data.get("delivery_distance_miles")
    dry_ice_blocks = data.get("dry_ice_blocks", 0)
    flavors = data.get("flavors")

    # 1. Presence
    if total_quantity is None:
        raise QuoteError('Field "total_quantity" is required.', "ERR_MISSING_FIELD", "total_quantity", None)

    # 2. Integer type (JSON ``50.0`` is an integer in JS, so it is accepted here too)
    if not _is_number(total_quantity) or (isinstance(total_quantity, float) and not total_quantity.is_integer()):
        raise QuoteError('Field "total_quantity" must be an integer.', "ERR_INVALID_DATA_TYPE",
                         "total_quantity", total_quantity)
    total_quantity = int(total_quantity)

    # 3. Minimum order quantity
    if total_quantity < rules.minimum_order_quantity:
        raise QuoteError(f"Minimum order quantity is {rules.minimum_order_quantity} popsicles.",
                         "ERR_BELOW_MINIMUM_ORDER", "total_quantity", total_quantity)

    # 4. Negative / non-numeric add-on quantities
    if not _is_number(heart_shaped_quantity) or heart_shaped_quantity < 0:
        raise QuoteError("Quantities cannot be negative.", "ERR_INVALID_DATA_TYPE",
                         "heart_shaped_quantity", heart_shaped_quantity)
    if not _is_number(dry_ice_blocks) or dry_ice_blocks < 0:
        raise QuoteError("Quantities cannot be negative.", "ERR_INVALID_DATA_TYPE",
                         "dry_ice_blocks", dry_ice_blocks)

    # 5. Heart-shaped cannot exceed total
    if heart_shaped_quantity > total_quantity:
        raise QuoteError("Heart-shaped popsicle quantity cannot exceed total quantity.",
                         "ERR_HEART_EXCEEDS_TOTAL", "heart_shaped_quantity", heart_shaped_quantity)

    # 6. service_type enum
    if not isinstance(service_type, str) or service_type not in VALID_SERVICE_TYPES:
        raise QuoteError(f"Invalid service type: {_safe_text(service_type)}", "ERR_INVALID_DATA_TYPE",
                         "service_type", service_type)

    # 7. Distance required and bounded for DELIVERY only (ignored otherwise)
    sanitized_distance = 0
    if service_type == "DELIVERY":
        max_radius = rules.delivery_max_radius_miles
        out_of_range = QuoteError(f"Delivery distance must be between 0 and {_fmt(max_radius)} miles.",
                                  "ERR_DISTANCE_OUT_OF_RANGE", "delivery_distance_miles", delivery_distance_miles)
        is_real = isinstance(delivery_distance_miles, (int, float)) and not isinstance(delivery_distance_miles, bool)
        if not is_real or delivery_distance_miles < 0:
            raise out_of_range
        if delivery_distance_miles > max_radius:  # includes JSON 1e999 (inf)
            if rules.exceeded_radius_action != "REDIRECT_CONTACT_FORM":
                raise out_of_range
            raise OutsideDeliveryRadius(
                f"Delivery beyond {_fmt(max_radius)} miles requires a custom event inquiry.",
                delivery_distance_miles)
        sanitized_distance = delivery_distance_miles

    # 8. Flavor integrity; only checked for a non-empty list, otherwise ignored
    sanitized_flavors = None
    if isinstance(flavors, list) and flavors:
        flavor_sum = _flavor_quantity_sum(flavors)
        if flavor_sum != total_quantity:
            raise QuoteError(
                f"Sum of flavor quantities ({_fmt(flavor_sum)}) does not match total quantity ({total_quantity}).",
                "ERR_FLAVOR_SUM_MISMATCH", "flavors", flavor_sum)
        sanitized_flavors = flavors

    return {
        "total_quantity": total_quantity,
        "heart_shaped_quantity": heart_shaped_quantity,
        "service_type": service_type,
        "delivery_distance_miles": sanitized_distance,
        "dry_ice_blocks": dry_ice_blocks,
        "flavors": sanitized_flavors,
    }


# --------------------------------------------------------------------------- #
# Pricing engine (pricingEngine.js)
# --------------------------------------------------------------------------- #

def select_tier(rules, total_quantity):
    """Highest tier whose minimum is met (legacy: >=200, >=100, else tier 1)."""
    applied = rules.tiers[0]
    for tier in rules.tiers:
        if total_quantity >= tier.min_quantity:
            applied = tier
    return applied


def calculate_order_quote(rules, payload):
    """Price an already-validated payload. All amounts are integer cents."""
    total_quantity = payload["total_quantity"]
    tier = select_tier(rules, total_quantity)
    base_cents = total_quantity * tier.unit_price_cents

    heart_cents = calculate_heart_shape_surcharge(rules, total_quantity, payload.get("heart_shaped_quantity", 0))
    dry_ice_cents = calculate_dry_ice_fee(rules, payload.get("dry_ice_blocks", 0))
    delivery_cents, full_service_cents = calculate_logistics_fees(
        rules, payload.get("service_type", "PICKUP"), payload.get("delivery_distance_miles", 0))

    total_cents = base_cents + heart_cents + dry_ice_cents + delivery_cents + full_service_cents
    # RoundUp(total_amount * deposit_rate, 2): always round the deposit up to a whole cent.
    deposit_cents = math.ceil(total_cents * rules.deposit_rate)
    balance_cents = total_cents - deposit_cents

    return {
        "status": "priced",
        "next_action": None,
        "tier_applied": {"name": tier.label, "unit_price_cents": tier.unit_price_cents},
        "breakdown": {
            "base_popsicles_cents": base_cents,
            "heart_shaped_surcharge_cents": heart_cents,
            "dry_ice_cents": dry_ice_cents,
            "delivery_fee_cents": delivery_cents,
            "full_service_fee_cents": full_service_cents,
        },
        "pricing_summary": {
            "subtotal_cents": total_cents,
            "total_cents": total_cents,
            "deposit_due_cents": deposit_cents,
            "balance_due_cents": balance_cents,
        },
        "currency": "USD",
    }


# --------------------------------------------------------------------------- #
# Input adapter: OpenAPI QuoteRequest -> legacy flat payload
# --------------------------------------------------------------------------- #

# Validator field name -> dotted path in the OpenAPI QuoteRequest, for error ``fields``.
_CONTRACT_FIELD_PATHS = {
    "total_quantity": "catering_request.quantity",
    "heart_shaped_quantity": "catering_request.popsicle_shape",
    "popsicle_shape": "catering_request.popsicle_shape",
    "dry_ice_blocks": "catering_request.dry_ice_blocks",
    "service_type": "catering_request.service_type",
    "delivery_distance_miles": "event.delivery_distance_miles",
}
QUOTE_VALIDITY = timedelta(minutes=15)  # proposed technical limit in the contract


def is_contract_payload(raw_payload):
    """True when the body is an OpenAPI QuoteRequest (it carries ``catering_request``)."""
    return isinstance(raw_payload, dict) and "catering_request" in raw_payload


def normalize_quote_payload(raw_payload):
    """Adapt an OpenAPI ``QuoteRequest`` to the flat payload the validator expects.

    A payload without ``catering_request`` is already flat and is returned
    unchanged, which preserves the legacy behavior exactly. Values are mapped
    but not validated here; ``validate_quote_payload`` does that, so a bad
    value produces the same 422 as in the legacy format.
    """
    if not is_contract_payload(raw_payload):
        return raw_payload
    catering = raw_payload["catering_request"] if isinstance(raw_payload["catering_request"], dict) else {}
    event = raw_payload.get("event") if isinstance(raw_payload.get("event"), dict) else {}

    flat = {"total_quantity": catering.get("quantity")}

    shape = catering.get("popsicle_shape", "standard")
    shape = shape.strip().lower() if isinstance(shape, str) else shape
    if shape == "heart":
        flat["heart_shaped_quantity"] = catering.get("quantity")  # every unit is heart-shaped
    elif shape not in (None, "standard"):
        raise QuoteError("Popsicle shape must be standard or heart.", "ERR_INVALID_DATA_TYPE",
                         "popsicle_shape", shape)

    if "service_type" in catering:
        service_type = catering["service_type"]
        flat["service_type"] = service_type.strip().upper() if isinstance(service_type, str) else service_type

    dry_ice = catering.get("dry_ice_blocks")
    flat["dry_ice_blocks"] = 0 if dry_ice is None else dry_ice

    distance = raw_payload.get("delivery_distance_miles")
    if distance is None:
        distance = event.get("delivery_distance_miles")
    if distance is None and flat.get("service_type") == "DELIVERY":
        # Synthetic payloads carry no measured distance; the contract's backend-side
        # distance lookup (D04) does not exist yet, so this prices at the base fee.
        distance = 0.0
    if distance is not None:
        flat["delivery_distance_miles"] = distance
    return flat


# --------------------------------------------------------------------------- #
# OpenAPI Quote response
# --------------------------------------------------------------------------- #

def _money(cents):
    return f"${cents // 100}.{cents % 100:02d}"


def _line_items(rules, payload, calculation):
    breakdown = calculation["breakdown"]
    tier = calculation["tier_applied"]
    items = [{
        "code": "popsicles",
        "description": f"{payload['total_quantity']} popsicles, {tier['name']}, {_money(tier['unit_price_cents'])} each",
        "amount_cents": breakdown["base_popsicles_cents"],
    }]
    optional = [
        ("heart_shaped_surcharge", f"Heart-shaped surcharge, {_fmt(payload['heart_shaped_quantity'])} units at "
                                   f"{_money(rules.heart_surcharge_cents)}", breakdown["heart_shaped_surcharge_cents"]),
        ("dry_ice", f"Dry ice, {_fmt(payload['dry_ice_blocks'])} blocks at {_money(rules.dry_ice_block_cents)}",
         breakdown["dry_ice_cents"]),
        ("delivery_fee", f"Delivery, {_fmt(payload['delivery_distance_miles'])} miles",
         breakdown["delivery_fee_cents"]),
        ("full_service_fee", "Full service flat fee", breakdown["full_service_fee_cents"]),
    ]
    items.extend({"code": code, "description": text, "amount_cents": cents}
                 for code, text, cents in optional if cents)
    return items


def _contract_quote(raw_payload, status, pricing, rules, unresolved_decisions, next_action):
    expires_at = datetime.now(timezone.utc) + QUOTE_VALIDITY
    event = raw_payload.get("event")
    # delivery_distance_miles is accepted as input but is not part of the schema's Event, so do not echo it.
    event = {key: value for key, value in event.items() if key != "delivery_distance_miles"} \
        if isinstance(event, dict) else {}
    return {
        "id": f"quote_{uuid.uuid4().hex}",  # not persisted yet; order creation will bind a stored quote
        "status": status,
        "expires_at": expires_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "catering_request": raw_payload["catering_request"],
        "event": event,
        "pricing": pricing,
        "pricing_revision": rules.revision if pricing is not None else None,
        "unresolved_decisions": unresolved_decisions,
        "next_action": next_action,
    }


def contract_priced_quote(rules, raw_payload, payload, calculation):
    """OpenAPI ``Quote`` for a priced request. ``deposit_due_cents`` is the schema's deposit field."""
    summary = calculation["pricing_summary"]
    pricing = {
        "currency": calculation["currency"],
        "line_items": _line_items(rules, payload, calculation),
        "total_cents": summary["total_cents"],
        "deposit_due_cents": summary["deposit_due_cents"],
    }
    return _contract_quote(raw_payload, "priced", pricing, rules, [], None)


def contract_review_quote(rules, raw_payload, message):
    """OpenAPI ``Quote`` for an out-of-area delivery: null pricing plus the inquiry action."""
    review = requires_review_quote(message)
    return _contract_quote(raw_payload, "requires_review", None, rules,
                           review["unresolved_decisions"], review["next_action"])


# --------------------------------------------------------------------------- #
# HTTP layer: POST /api/v1/quotes
# --------------------------------------------------------------------------- #

def _inquiry_url():
    """Approved Custom Event Inquiry destination; null until CUSTOM_EVENT_INQUIRY_URL is set."""
    url = str(current_app.config.get("CUSTOM_EVENT_INQUIRY_URL", os.getenv("CUSTOM_EVENT_INQUIRY_URL", ""))).strip()
    parsed = urlsplit(url)
    return url if parsed.scheme in {"http", "https"} and parsed.hostname and len(url) <= 2000 else None


def requires_review_quote(message):
    """No price is returned for an out-of-area delivery (never a normal delivery fee)."""
    return {
        "status": "requires_review",
        "tier_applied": None,
        "breakdown": None,
        "pricing_summary": None,
        "currency": "USD",
        "unresolved_decisions": ["D04"],  # delivery distance method/postal code still open
        "next_action": {
            "type": "contact_inquiry",
            "reason_code": "outside_delivery_radius",
            "message": message,
            "inquiry_url": _inquiry_url(),
        },
    }


def _reject_json_constant(name):
    raise ValueError(f"Non-standard JSON constant {name}")


def _validation_error(message, field=None):
    fields = [{"field": field, "message": message}] if field else []
    return jsonify(error={"code": "validation_error", "message": message, "fields": fields,
                          "request_id": g.request_id}), 422


@quotes_bp.post("/quotes")
def create_quote():
    try:
        payload = json.loads(request.get_data(), parse_constant=_reject_json_constant)
    except ValueError:
        return _validation_error("Malformed JSON payload")
    rules = current_app.extensions["pricing_rules"]
    contract = is_contract_payload(payload)
    try:
        flat = normalize_quote_payload(payload)
        validated = validate_quote_payload(rules, flat)
        calculation = calculate_order_quote(rules, validated)
        quote = contract_priced_quote(rules, payload, validated, calculation) if contract else calculation
    except OutsideDeliveryRadius as error:
        quote = contract_review_quote(rules, payload, error.message) if contract else requires_review_quote(error.message)
    except QuoteError as error:
        field, message = error.field, error.message
        if contract and field in _CONTRACT_FIELD_PATHS:
            field = _CONTRACT_FIELD_PATHS[field]
            message = message.replace('"total_quantity"', '"catering_request.quantity"')
        return _validation_error(message, field)
    return jsonify(data=quote, meta={"request_id": g.request_id})
