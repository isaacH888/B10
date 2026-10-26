"""POST /api/v1/quotes: translation of the 18 legacy boundary cases (TC-B01..TC-B18).

Source: docs/reference/legacy-node/popssibilities_tests.json. Contract changes:
money is integer cents and every rejection is 422 ``validation_error`` (legacy
used 400/422 with ``ERR_*`` codes). The legacy code is asserted via
``QuoteError.reason`` on the service layer so each rule is still distinguished.
"""

import json
from fractions import Fraction
from pathlib import Path

import pytest

from app import create_app
from app.quotes import (
    QuoteError,
    calculate_dry_ice_fee,
    calculate_heart_shape_surcharge,
    calculate_logistics_fees,
    load_business_rules,
    validate_quote_payload,
)

LEGACY_SUITE = Path(__file__).resolve().parents[2] / "docs/reference/legacy-node/popssibilities_tests.json"


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #

@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "http://localhost:5173")
    monkeypatch.setenv("DB_USER", "")
    monkeypatch.setenv("DB_PASSWORD", "")
    return create_app({"TESTING": True})


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def rules():
    return load_business_rules()


@pytest.fixture
def post_quote(client):
    def post(payload):
        return client.post("/api/v1/quotes", json=payload)
    return post


def base_payload(**overrides):
    payload = {"total_quantity": 50, "heart_shaped_quantity": 0, "service_type": "PICKUP", "dry_ice_blocks": 0}
    payload.update(overrides)
    return payload


def assert_validation_error(response, field):
    assert response.status_code == 422
    error = response.json["error"]
    assert error["code"] == "validation_error"
    assert [item["field"] for item in error["fields"]] == [field]
    assert error["fields"][0]["message"] == error["message"]
    assert error["request_id"] == response.headers["X-Request-ID"]
    assert "data" not in response.json


# --------------------------------------------------------------------------- #
# Legacy cases, as tables. Amounts are cents (legacy dollars x 100).
# --------------------------------------------------------------------------- #

# id: (payload, expected unit price, total, deposit)  -- TC-B02..B07
TIER_CASES = {
    "TC-B02": (base_payload(total_quantity=50), 350, 17500, 8750),      # MOQ, tier 1
    "TC-B03": (base_payload(total_quantity=51), 350, 17850, 8925),      # MOQ + 1
    "TC-B04": (base_payload(total_quantity=99), 350, 34650, 17325),     # tier 1 upper bound
    "TC-B05": (base_payload(total_quantity=100), 325, 32500, 16250),    # tier 2 lower bound
    "TC-B06": (base_payload(total_quantity=199), 325, 64675, 32338),    # tier 2 upper; deposit rounds UP
    "TC-B07": (base_payload(total_quantity=200), 300, 60000, 30000),    # tier 3 lower bound
}

# id: (payload, breakdown field, expected cents)  -- TC-B09, B10, B12, B13, B15
BREAKDOWN_CASES = {
    "TC-B09": (base_payload(heart_shaped_quantity=0), "heart_shaped_surcharge_cents", 0),
    "TC-B10": (base_payload(heart_shaped_quantity=50), "heart_shaped_surcharge_cents", 2500),
    "TC-B12": (base_payload(service_type="DELIVERY", delivery_distance_miles=0.0), "delivery_fee_cents", 2500),
    "TC-B13": (base_payload(service_type="DELIVERY", delivery_distance_miles=30.0), "delivery_fee_cents", 7500),
    "TC-B15": (base_payload(dry_ice_blocks=0), "dry_ice_cents", 0),
}

# id: (payload, offending field, legacy reason code)  -- TC-B01, B08, B11, B14, B16, B17
ERROR_CASES = {
    "TC-B01": (base_payload(total_quantity=49), "total_quantity", "ERR_BELOW_MINIMUM_ORDER"),
    "TC-B08": (base_payload(heart_shaped_quantity=-1), "heart_shaped_quantity", "ERR_INVALID_DATA_TYPE"),
    "TC-B11": (base_payload(heart_shaped_quantity=51), "heart_shaped_quantity", "ERR_HEART_EXCEEDS_TOTAL"),
    "TC-B16": (base_payload(dry_ice_blocks=-1), "dry_ice_blocks", "ERR_INVALID_DATA_TYPE"),
    "TC-B17": (base_payload(flavors=[{"flavor_name": "Strawberry", "quantity": 25},
                                     {"flavor_name": "Mango", "quantity": 23}]),
               "flavors", "ERR_FLAVOR_SUM_MISMATCH"),
}

# TC-B14: legacy rejected with 400; per the client decision it is now a contact-inquiry redirect.
REDIRECT_CASES = {
    "TC-B14": base_payload(service_type="DELIVERY", delivery_distance_miles=30.1),
}

# TC-B18
PENNY_ROUNDING_PAYLOAD = {"total_quantity": 51, "heart_shaped_quantity": 1, "service_type": "DELIVERY",
                          "delivery_distance_miles": 28.5, "dry_ice_blocks": 1}

ALL_CASE_IDS = {f"TC-B{n:02d}" for n in range(1, 19)}


# --------------------------------------------------------------------------- #
# TC-B01..TC-B18
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("case_id", TIER_CASES)
def test_tier_boundaries_price_and_deposit_in_cents(post_quote, case_id):
    payload, unit_cents, total_cents, deposit_cents = TIER_CASES[case_id]
    response = post_quote(payload)
    assert response.status_code == 200
    data = response.json["data"]
    assert data["tier_applied"]["unit_price_cents"] == unit_cents
    assert data["pricing_summary"]["total_cents"] == total_cents
    assert data["pricing_summary"]["deposit_due_cents"] == deposit_cents
    assert data["pricing_summary"]["balance_due_cents"] == total_cents - deposit_cents


@pytest.mark.parametrize("case_id", BREAKDOWN_CASES)
def test_breakdown_boundaries(post_quote, case_id):
    payload, field, expected_cents = BREAKDOWN_CASES[case_id]
    response = post_quote(payload)
    assert response.status_code == 200
    assert response.json["data"]["breakdown"][field] == expected_cents


def test_tc_b10_all_hearts_total(post_quote):
    response = post_quote(base_payload(heart_shaped_quantity=50))
    assert response.json["data"]["pricing_summary"]["total_cents"] == 20000  # 17500 + 2500


@pytest.mark.parametrize("case_id", ERROR_CASES)
def test_rejections_are_422_validation_errors(post_quote, case_id):
    payload, field, _reason = ERROR_CASES[case_id]
    assert_validation_error(post_quote(payload), field)


@pytest.mark.parametrize("case_id", ERROR_CASES)
def test_rejections_keep_distinct_legacy_reason(rules, case_id):
    payload, field, reason = ERROR_CASES[case_id]
    with pytest.raises(QuoteError) as raised:
        validate_quote_payload(rules, payload)
    assert raised.value.reason == reason
    assert raised.value.field == field


def assert_contact_inquiry_redirect(response):
    assert response.status_code == 200
    data = response.json["data"]
    assert data["status"] == "requires_review"
    assert data["tier_applied"] is None and data["breakdown"] is None and data["pricing_summary"] is None
    assert data["unresolved_decisions"]
    action = data["next_action"]
    assert (action["type"], action["reason_code"]) == ("contact_inquiry", "outside_delivery_radius")
    assert action["message"] == "Delivery beyond 30 miles requires a custom event inquiry."
    assert "inquiry_url" in action
    assert "error" not in response.json
    return action


def test_tc_b14_distance_beyond_radius_redirects_to_contact_inquiry(post_quote, rules):
    assert_contact_inquiry_redirect(post_quote(REDIRECT_CASES["TC-B14"]))
    # The legacy rule is still identified at the service layer.
    with pytest.raises(QuoteError) as raised:
        validate_quote_payload(rules, REDIRECT_CASES["TC-B14"])
    assert (raised.value.reason, raised.value.field) == ("ERR_DISTANCE_OUT_OF_RANGE", "delivery_distance_miles")


@pytest.mark.parametrize("distance", ["30.01", "31", "500", "1e999"])
def test_any_distance_beyond_radius_redirects_without_a_price(client, distance):
    body = ('{"total_quantity": 50, "service_type": "DELIVERY", "delivery_distance_miles": %s}' % distance).encode()
    response = client.post("/api/v1/quotes", data=body, content_type="application/json")
    assert_contact_inquiry_redirect(response)


def test_radius_boundary_is_still_priced(post_quote):
    data = post_quote(base_payload(service_type="DELIVERY", delivery_distance_miles=30.0)).json["data"]
    assert data["status"] == "priced" and data["next_action"] is None


def test_inquiry_url_comes_from_environment_when_configured(client, monkeypatch):
    payload = base_payload(service_type="DELIVERY", delivery_distance_miles=45)
    monkeypatch.delenv("CUSTOM_EVENT_INQUIRY_URL", raising=False)
    assert assert_contact_inquiry_redirect(client.post("/api/v1/quotes", json=payload))["inquiry_url"] is None
    monkeypatch.setenv("CUSTOM_EVENT_INQUIRY_URL", "https://popssibilities.example.invalid/contact")
    action = assert_contact_inquiry_redirect(client.post("/api/v1/quotes", json=payload))
    assert action["inquiry_url"] == "https://popssibilities.example.invalid/contact"
    monkeypatch.setenv("CUSTOM_EVENT_INQUIRY_URL", "javascript:alert(1)")
    assert assert_contact_inquiry_redirect(client.post("/api/v1/quotes", json=payload))["inquiry_url"] is None


def test_tc_b18_penny_rounding_and_split_balance(post_quote):
    response = post_quote(PENNY_ROUNDING_PAYLOAD)
    assert response.status_code == 200
    data = response.json["data"]
    assert data["breakdown"] == {
        "base_popsicles_cents": 17850, "heart_shaped_surcharge_cents": 50, "dry_ice_cents": 1500,
        "delivery_fee_cents": 7250, "full_service_fee_cents": 0,
    }
    summary = data["pricing_summary"]
    assert summary["total_cents"] == 26650
    assert summary["deposit_due_cents"] + summary["balance_due_cents"] == summary["total_cents"]


def test_every_legacy_case_is_translated():
    covered = set(TIER_CASES) | set(BREAKDOWN_CASES) | set(ERROR_CASES) | set(REDIRECT_CASES) | {"TC-B18"}
    assert covered == ALL_CASE_IDS


@pytest.mark.skipif(not LEGACY_SUITE.exists(), reason="legacy reference suite not checked out")
def test_translated_payloads_match_legacy_suite_exactly():
    legacy = {item["name"].split(":")[0]: json.loads(item["request"]["body"]["raw"])
              for item in json.loads(LEGACY_SUITE.read_text(encoding="utf-8"))["item"]}
    assert set(legacy) == ALL_CASE_IDS
    translated = {case_id: spec[0] for case_id, spec in {**TIER_CASES, **BREAKDOWN_CASES, **ERROR_CASES}.items()}
    translated.update(REDIRECT_CASES)
    translated["TC-B18"] = PENNY_ROUNDING_PAYLOAD
    assert translated == legacy


# --------------------------------------------------------------------------- #
# Contract: route, envelope, money type
# --------------------------------------------------------------------------- #

def test_success_envelope_and_integer_cents(post_quote):
    response = post_quote(PENNY_ROUNDING_PAYLOAD)
    assert response.status_code == 200
    assert response.json["meta"]["request_id"] == response.headers["X-Request-ID"]
    assert response.json["data"]["currency"] == "USD"

    def amounts(node):
        for key, value in node.items():
            if isinstance(value, dict):
                yield from amounts(value)
            elif key.endswith("_cents"):
                yield value

    values = list(amounts(response.json["data"]))
    assert values and all(type(value) is int and value >= 0 for value in values)


def test_legacy_route_is_not_served(client):
    # "quote" now reads as an order ID for GET /orders/{order_id}, so a POST is 405 rather than 404.
    assert client.post("/api/v1/orders/quote", json=base_payload()).status_code in (404, 405)


def test_subtotal_equals_sum_of_line_items(post_quote):
    data = post_quote(base_payload(total_quantity=120, heart_shaped_quantity=7, service_type="DELIVERY",
                                   delivery_distance_miles=12.3, dry_ice_blocks=3)).json["data"]
    assert sum(data["breakdown"].values()) == data["pricing_summary"]["total_cents"]
    assert data["pricing_summary"]["subtotal_cents"] == data["pricing_summary"]["total_cents"]


# --------------------------------------------------------------------------- #
# Remaining legacy rules not covered by the 18 boundary cases
# --------------------------------------------------------------------------- #

def test_defaults_to_pickup_with_no_addons(post_quote):
    response = post_quote({"total_quantity": 60})
    assert response.status_code == 200
    assert response.json["data"]["breakdown"] == {
        "base_popsicles_cents": 21000, "heart_shaped_surcharge_cents": 0, "dry_ice_cents": 0,
        "delivery_fee_cents": 0, "full_service_fee_cents": 0}


def test_tier_names_match_legacy_labels(post_quote):
    names = [post_quote(base_payload(total_quantity=q)).json["data"]["tier_applied"]["name"] for q in (50, 100, 200)]
    assert names == ["Tier 1 (50-99)", "Tier 2 (100-199)", "Tier 3 (200+)"]


def test_full_service_flat_fee_replaces_delivery(post_quote):
    data = post_quote(base_payload(service_type="FULL_SERVICE", delivery_distance_miles=99)).json["data"]
    assert data["breakdown"]["full_service_fee_cents"] == 15000
    assert data["breakdown"]["delivery_fee_cents"] == 0
    assert data["pricing_summary"]["total_cents"] == 17500 + 15000


def test_delivery_distance_is_ignored_for_non_delivery(post_quote):
    response = post_quote(base_payload(service_type="PICKUP", delivery_distance_miles=500))
    assert response.status_code == 200
    assert response.json["data"]["breakdown"]["delivery_fee_cents"] == 0


def test_dry_ice_price_per_block(post_quote):
    assert post_quote(base_payload(dry_ice_blocks=4)).json["data"]["breakdown"]["dry_ice_cents"] == 6000


def test_delivery_fee_is_linear_and_rounded_to_cent(post_quote):
    # 25 + (50/30) * 7 = 36.666... -> $36.67
    fee = post_quote(base_payload(service_type="DELIVERY", delivery_distance_miles=7)).json["data"]
    assert fee["breakdown"]["delivery_fee_cents"] == 3667


def test_flavors_matching_total_are_accepted(post_quote):
    flavors = [{"flavor_name": "Strawberry", "quantity": 25}, {"flavor_name": "Mango", "quantity": 25}]
    assert post_quote(base_payload(flavors=flavors)).status_code == 200


@pytest.mark.parametrize("flavors", [None, [], "mango", {"quantity": 3}])
def test_absent_or_non_list_flavors_are_ignored(post_quote, flavors):
    assert post_quote(base_payload(flavors=flavors)).status_code == 200


def test_missing_total_quantity(post_quote, rules):
    assert_validation_error(post_quote({"service_type": "PICKUP"}), "total_quantity")
    with pytest.raises(QuoteError) as raised:
        validate_quote_payload(rules, {})
    assert raised.value.reason == "ERR_MISSING_FIELD"


@pytest.mark.parametrize("body", [b"null", b"[]", b"5", b'"x"'])
def test_non_object_json_is_treated_as_missing_total_quantity(client, body):
    response = client.post("/api/v1/quotes", data=body, content_type="application/json")
    assert_validation_error(response, "total_quantity")


@pytest.mark.parametrize("value", [50.5, "50", True, [50], {"n": 50}])
def test_total_quantity_must_be_integer(post_quote, rules, value):
    assert_validation_error(post_quote(base_payload(total_quantity=value)), "total_quantity")
    with pytest.raises(QuoteError) as raised:
        validate_quote_payload(rules, base_payload(total_quantity=value))
    assert raised.value.reason == "ERR_INVALID_DATA_TYPE"


def test_whole_number_float_total_quantity_is_accepted(post_quote):
    # JSON 50.0 is an integer in the legacy runtime.
    response = post_quote(base_payload(total_quantity=50.0))
    assert response.status_code == 200
    assert response.json["data"]["pricing_summary"]["total_cents"] == 17500


@pytest.mark.parametrize("field", ["heart_shaped_quantity", "dry_ice_blocks"])
@pytest.mark.parametrize("value", [None, "3", True, -0.5])
def test_non_numeric_or_negative_addon_quantities(post_quote, field, value):
    # null is not defaulted (only an absent key is) and is rejected like a negative.
    assert_validation_error(post_quote(base_payload(**{field: value})), field)


@pytest.mark.parametrize("value", ["pickup", "", None, 5, "DELIVER"])
def test_invalid_service_type(post_quote, rules, value):
    assert_validation_error(post_quote(base_payload(service_type=value)), "service_type")
    with pytest.raises(QuoteError) as raised:
        validate_quote_payload(rules, base_payload(service_type=value))
    assert raised.value.reason == "ERR_INVALID_DATA_TYPE"


@pytest.mark.parametrize("distance", ["missing", None, "5", True, -0.1])
def test_delivery_requires_bounded_numeric_distance(post_quote, distance):
    payload = base_payload(service_type="DELIVERY")
    if distance != "missing":
        payload["delivery_distance_miles"] = distance
    assert_validation_error(post_quote(payload), "delivery_distance_miles")


def test_validation_order_matches_legacy(rules):
    """First failure wins: total_quantity checks, then add-ons, heart>total, service, distance, flavors."""
    cases = [
        ({"total_quantity": 10, "heart_shaped_quantity": -1}, "ERR_BELOW_MINIMUM_ORDER"),
        ({"total_quantity": 50, "heart_shaped_quantity": 99, "dry_ice_blocks": -1}, "ERR_INVALID_DATA_TYPE"),
        ({"total_quantity": 50, "heart_shaped_quantity": 99, "service_type": "X"}, "ERR_HEART_EXCEEDS_TOTAL"),
        ({"total_quantity": 50, "service_type": "X", "flavors": [{"quantity": 1}]}, "ERR_INVALID_DATA_TYPE"),
        ({"total_quantity": 50, "service_type": "DELIVERY", "flavors": [{"quantity": 1}]},
         "ERR_DISTANCE_OUT_OF_RANGE"),
    ]
    for payload, reason in cases:
        with pytest.raises(QuoteError) as raised:
            validate_quote_payload(rules, payload)
        assert raised.value.reason == reason, payload


def test_flavor_entries_with_falsy_or_missing_quantity_count_as_zero(post_quote):
    flavors = [{"flavor_name": "A", "quantity": 50}, {"flavor_name": "B"}, {"flavor_name": "C", "quantity": 0}]
    assert post_quote(base_payload(flavors=flavors)).status_code == 200


def test_null_flavor_entry_is_rejected(post_quote):
    assert_validation_error(post_quote(base_payload(flavors=[None])), "flavors")


def test_rejected_value_is_retained_on_service_errors(rules):
    with pytest.raises(QuoteError) as raised:
        validate_quote_payload(rules, base_payload(total_quantity=49))
    assert raised.value.rejected_value == 49
    with pytest.raises(QuoteError) as raised:
        validate_quote_payload(rules, base_payload(flavors=[{"quantity": 20}, {"quantity": 28}]))
    assert raised.value.rejected_value == 48  # the computed flavor sum, as in legacy


@pytest.mark.parametrize("body", [b"", b"{not json", b'{"total_quantity": NaN}', b'{"total_quantity": Infinity}'])
def test_malformed_json_is_validation_error(client, body):
    response = client.post("/api/v1/quotes", data=body, content_type="application/json")
    assert response.status_code == 422
    assert response.json["error"]["code"] == "validation_error"
    assert response.json["error"]["fields"] == []


# --------------------------------------------------------------------------- #
# Fee calculator defensive checks (feeCalculator.js validates independently)
# --------------------------------------------------------------------------- #

def test_fee_calculators_revalidate_their_inputs(rules):
    with pytest.raises(QuoteError) as raised:
        calculate_heart_shape_surcharge(rules, 50, -1)
    assert (raised.value.reason, raised.value.field) == ("ERR_INVALID_DATA_TYPE", "heart_shaped_quantity")
    with pytest.raises(QuoteError) as raised:
        calculate_heart_shape_surcharge(rules, 50, 51)
    assert raised.value.reason == "ERR_HEART_EXCEEDS_TOTAL"
    with pytest.raises(QuoteError) as raised:
        calculate_dry_ice_fee(rules, -1)
    assert (raised.value.reason, raised.value.field) == ("ERR_INVALID_DATA_TYPE", "dry_ice_blocks")
    for distance in (-1, 30.1):
        with pytest.raises(QuoteError) as raised:
            calculate_logistics_fees(rules, "DELIVERY", distance)
        assert raised.value.reason == "ERR_DISTANCE_OUT_OF_RANGE"
    with pytest.raises(QuoteError) as raised:
        calculate_logistics_fees(rules, "TELEPORT", 0)
    assert (raised.value.reason, raised.value.field) == ("ERR_INVALID_DATA_TYPE", "service_type")


def test_fee_calculator_values(rules):
    assert calculate_heart_shape_surcharge(rules, 100, 3) == 150
    assert calculate_dry_ice_fee(rules, 2) == 3000
    assert calculate_logistics_fees(rules, "PICKUP") == (0, 0)
    assert calculate_logistics_fees(rules, "FULL_SERVICE") == (0, 15000)
    assert calculate_logistics_fees(rules, "DELIVERY", 15) == (5000, 0)


# --------------------------------------------------------------------------- #
# Configuration stays decoupled from logic
# --------------------------------------------------------------------------- #

def test_shipped_config_is_loaded_from_json_file(app, rules):
    assert app.extensions["pricing_rules"] == rules
    assert rules.minimum_order_quantity == 50
    assert [(t.min_quantity, t.max_quantity, t.unit_price_cents) for t in rules.tiers] == [
        (50, 99, 350), (100, 199, 325), (200, None, 300)]
    assert (rules.heart_surcharge_cents, rules.dry_ice_block_cents, rules.full_service_flat_cents) == (50, 1500, 15000)
    assert (rules.delivery_base_cents, rules.delivery_max_cents, rules.delivery_max_radius_miles) == (2500, 7500, 30.0)
    assert rules.deposit_rate == Fraction(1, 2)


def test_editing_config_changes_prices_without_code_changes(monkeypatch, tmp_path):
    config = json.loads((Path(__file__).resolve().parents[1] / "app/pricing.config.json").read_text(encoding="utf-8"))
    rules = config["business_rules"]
    rules["moq"]["minimum_order_quantity"] = 20
    rules["volume_tiers"][0].update(min_quantity=20, unit_price=4.00)
    rules["payments"]["deposit_rate"] = 0.30
    rules["logistics"]["delivery"]["max_radius_miles"] = 10.0
    path = tmp_path / "pricing.config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "http://localhost:5173")
    monkeypatch.setenv("DB_USER", "")
    monkeypatch.setenv("DB_PASSWORD", "")
    client = create_app({"TESTING": True, "PRICING_CONFIG_PATH": str(path)}).test_client()

    response = client.post("/api/v1/quotes", json=base_payload(total_quantity=20))
    assert response.status_code == 200
    summary = response.json["data"]["pricing_summary"]
    assert (summary["total_cents"], summary["deposit_due_cents"]) == (8000, 2400)
    outside = client.post("/api/v1/quotes", json=base_payload(service_type="DELIVERY", delivery_distance_miles=10.5))
    assert_contact_inquiry_redirect_message(outside, "Delivery beyond 10 miles requires a custom event inquiry.")

    # exceeded_radius_action is also config-driven: anything else restores the legacy rejection.
    rules["logistics"]["delivery"]["exceeded_radius_action"] = "REJECT"
    path.write_text(json.dumps(config), encoding="utf-8")
    strict = create_app({"TESTING": True, "PRICING_CONFIG_PATH": str(path)}).test_client()
    assert_validation_error(strict.post("/api/v1/quotes", json=base_payload(
        service_type="DELIVERY", delivery_distance_miles=10.5)), "delivery_distance_miles")


def assert_contact_inquiry_redirect_message(response, message):
    assert response.status_code == 200
    assert response.json["data"]["status"] == "requires_review"
    assert response.json["data"]["next_action"]["message"] == message


def test_unreadable_config_fails_at_startup(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "http://localhost:5173")
    monkeypatch.setenv("DB_USER", "")
    monkeypatch.setenv("DB_PASSWORD", "")
    with pytest.raises(FileNotFoundError):
        create_app({"TESTING": True, "PRICING_CONFIG_PATH": str(tmp_path / "missing.json")})


# --------------------------------------------------------------------------- #
# OpenAPI QuoteRequest / Quote format (catering_request + event)
# --------------------------------------------------------------------------- #

OPENAPI_PATH = Path(__file__).resolve().parents[2] / "docs/api/openapi.json"


def contract_payload(**catering):
    """Synthetic OpenAPI QuoteRequest, shaped like docs/api/examples.json quote_request."""
    request = {"quantity": 50, "popsicle_shape": "standard", "flavor_requests": "", "add_ons": [],
               "service_type": "delivery", "dry_ice_blocks": None}
    request.update(catering)
    return {
        "catering_request": request,
        "event": {"type": "Example celebration",
                  "location": {"line1": "100 Example Street", "city": "Houston", "region": "TX",
                               "postal_code": "77000", "country_code": "US"},
                  "starts_at": "2026-11-07T15:00:00-06:00", "ends_at": "2026-11-07T17:00:00-06:00",
                  "timezone": "America/Chicago", "notes": "Synthetic fixture - not a real event."},
    }


def assert_matches_openapi_quote_response(body):
    jsonschema = pytest.importorskip("jsonschema")
    referencing = pytest.importorskip("referencing")
    spec = json.loads(OPENAPI_PATH.read_text(encoding="utf-8"))
    uri = "urn:popssibilities:contract"
    registry = referencing.Registry().with_resource(uri, referencing.Resource.from_contents(
        spec, default_specification=referencing.jsonschema.DRAFT202012))
    schema = {"$ref": uri + "#/components/schemas/QuoteResponse"}
    jsonschema.Draft202012Validator(schema, registry=registry,
                                    format_checker=jsonschema.FormatChecker()).validate(body)


def line_item_map(pricing):
    return {item["code"]: item["amount_cents"] for item in pricing["line_items"]}


def test_openapi_quote_request_returns_priced_quote_with_line_items(post_quote):
    request = contract_payload()
    response = post_quote(request)
    assert response.status_code == 200
    data = response.json["data"]
    assert data["status"] == "priced"
    assert data["catering_request"] == request["catering_request"]
    assert data["event"] == request["event"]
    assert data["unresolved_decisions"] == [] and data["next_action"] is None
    assert data["pricing_revision"] == "pricing_config_1.1.0"
    pricing = data["pricing"]
    assert pricing["currency"] == "USD"
    # 50 popsicles at $3.50, delivery with no supplied distance defaults to 0 miles ($25.00 base fee)
    assert line_item_map(pricing) == {"popsicles": 17500, "delivery_fee": 2500}
    assert pricing["total_cents"] == 20000
    assert pricing["deposit_due_cents"] == 10000
    assert sum(line_item_map(pricing).values()) == pricing["total_cents"]
    assert all(type(item["amount_cents"]) is int and item["description"] for item in pricing["line_items"])
    assert response.json["meta"]["request_id"] == response.headers["X-Request-ID"]
    assert_matches_openapi_quote_response(response.json)


def test_openapi_quote_envelope_fields_and_expiry(post_quote):
    from datetime import datetime, timedelta, timezone
    first = post_quote(contract_payload()).json["data"]
    second = post_quote(contract_payload()).json["data"]
    assert first["id"] != second["id"] and first["id"].startswith("quote_")
    expires_at = datetime.strptime(first["expires_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    assert timedelta(minutes=14) < expires_at - datetime.now(timezone.utc) <= timedelta(minutes=15)
    assert "tier_applied" not in first and "pricing_summary" not in first


def test_openapi_heart_shape_maps_every_unit_to_heart_shaped(post_quote):
    response = post_quote(contract_payload(quantity=100, popsicle_shape="heart", service_type="full_service"))
    assert response.status_code == 200
    pricing = response.json["data"]["pricing"]
    # 100 x $3.25 + 100 x $0.50 heart surcharge + $150.00 full service
    assert line_item_map(pricing) == {"popsicles": 32500, "heart_shaped_surcharge": 5000, "full_service_fee": 15000}
    assert (pricing["total_cents"], pricing["deposit_due_cents"]) == (52500, 26250)
    assert_matches_openapi_quote_response(response.json)


def test_openapi_standard_shape_has_no_heart_surcharge(post_quote):
    pricing = post_quote(contract_payload(popsicle_shape="standard")).json["data"]["pricing"]
    assert "heart_shaped_surcharge" not in line_item_map(pricing)


@pytest.mark.parametrize("service_type", ["delivery", "DELIVERY", "Delivery"])
def test_openapi_service_type_is_case_insensitive(post_quote, service_type):
    pricing = post_quote(contract_payload(service_type=service_type)).json["data"]["pricing"]
    assert line_item_map(pricing)["delivery_fee"] == 2500


def test_openapi_dry_ice_null_defaults_to_zero_and_blocks_are_priced(post_quote):
    assert "dry_ice" not in line_item_map(post_quote(contract_payload(dry_ice_blocks=None)).json["data"]["pricing"])
    pricing = post_quote(contract_payload(dry_ice_blocks=2)).json["data"]["pricing"]
    assert line_item_map(pricing)["dry_ice"] == 3000
    assert pricing["total_cents"] == 23000


def test_openapi_distance_comes_from_event_or_top_level_with_top_level_first(post_quote):
    from_event = contract_payload()
    from_event["event"]["delivery_distance_miles"] = 15
    assert line_item_map(post_quote(from_event).json["data"]["pricing"])["delivery_fee"] == 5000

    both = contract_payload()
    both["event"]["delivery_distance_miles"] = 15
    both["delivery_distance_miles"] = 30
    assert line_item_map(post_quote(both).json["data"]["pricing"])["delivery_fee"] == 7500


def test_openapi_missing_distance_only_defaults_for_delivery(post_quote):
    pricing = post_quote(contract_payload(service_type="full_service")).json["data"]["pricing"]
    assert "delivery_fee" not in line_item_map(pricing)


def test_openapi_distance_beyond_radius_is_requires_review_quote(client):
    request = contract_payload()
    request["event"]["delivery_distance_miles"] = 45
    response = client.post("/api/v1/quotes", json=request)
    assert response.status_code == 200
    data = response.json["data"]
    assert data["status"] == "requires_review"
    assert data["pricing"] is None and data["pricing_revision"] is None
    assert data["unresolved_decisions"]
    assert data["next_action"]["type"] == "contact_inquiry"
    assert data["next_action"]["reason_code"] == "outside_delivery_radius"
    assert data["catering_request"] == request["catering_request"]
    assert "delivery_distance_miles" not in data["event"]  # input-only; not part of the schema's Event
    assert_matches_openapi_quote_response(response.json)


@pytest.mark.parametrize("catering, field", [
    ({"quantity": 49}, "catering_request.quantity"),
    ({"quantity": None}, "catering_request.quantity"),
    ({"quantity": 50.5}, "catering_request.quantity"),
    ({"popsicle_shape": "star"}, "catering_request.popsicle_shape"),
    ({"service_type": "teleport"}, "catering_request.service_type"),
    ({"dry_ice_blocks": -1}, "catering_request.dry_ice_blocks"),
])
def test_openapi_validation_errors_use_dotted_contract_field_paths(post_quote, catering, field):
    assert_validation_error(post_quote(contract_payload(**catering)), field)


def test_openapi_distance_out_of_range_error_path(post_quote):
    request = contract_payload()
    request["event"]["delivery_distance_miles"] = -1
    assert_validation_error(post_quote(request), "event.delivery_distance_miles")


def test_openapi_payload_without_catering_request_object_is_missing_quantity(post_quote):
    assert_validation_error(post_quote({"catering_request": None, "event": {}}), "catering_request.quantity")


def test_flat_payload_passes_through_normalizer_and_keeps_flat_response(post_quote):
    from app.quotes import normalize_quote_payload
    flat = base_payload(total_quantity=60)
    assert normalize_quote_payload(flat) is flat
    data = post_quote(flat).json["data"]
    assert "tier_applied" in data and "pricing_summary" in data and "pricing" not in data


def test_normalizer_maps_openapi_fields_to_flat_payload():
    from app.quotes import normalize_quote_payload
    request = contract_payload(quantity=120, popsicle_shape="heart", service_type="Full_Service", dry_ice_blocks=3)
    assert normalize_quote_payload(request) == {
        "total_quantity": 120, "heart_shaped_quantity": 120, "service_type": "FULL_SERVICE", "dry_ice_blocks": 3}
    delivery = normalize_quote_payload(contract_payload(dry_ice_blocks=None))
    assert delivery == {"total_quantity": 50, "service_type": "DELIVERY", "dry_ice_blocks": 0,
                        "delivery_distance_miles": 0.0}
