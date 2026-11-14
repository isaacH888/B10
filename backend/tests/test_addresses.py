"""Geoapify is mocked; full-address routing governs both quotes and orders."""

from copy import deepcopy
from uuid import uuid4

import pytest
import requests
from address_fixtures import LOCATION, FixedAddressProvider
from app import create_app
from app.addresses import AddressProviderUnavailable, GeoapifyAddressProvider
from app.traffic import RequestBudget
from test_orders import order_payload

ORIGIN = "http://localhost:5173"
BASE = "/api/v1/catering/address"


@pytest.fixture
def address_app(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    provider = FixedAddressProvider(16094)
    app = create_app(
        {
            "TESTING": True,
            "AUTH_ENABLED": False,
            "CUSTOMER_AUTH_ENABLED": False,
            "DB_USER": "",
            "DB_PASSWORD": "",
            "GEOAPIFY_API_KEY": "",
            "ADDRESS_PROVIDER": provider,
            "ADDRESS_DISTANCE_PROVIDER": provider,
            "AUTH_ORIGIN": ORIGIN,
            "CORS_ORIGINS": [ORIGIN],
            "AUTOMATION_ENABLED": False,
            "EMAIL_ENABLED": False,
        }
    )
    return app, app.test_client(), provider


def post(client, path, body):
    return client.post(BASE + path, json=body, headers={"Origin": ORIGIN})


def order(client, body, key="synthetic-address-order-key"):
    if body.get("quote_id") == "quote_example_001":
        priced = quote(client, body)
        if priced.status_code == 200:
            body["quote_id"] = priced.json["data"]["id"]
    return client.post("/api/v1/orders", json=body, headers={"Idempotency-Key": key})


def quote(client, body):
    return client.post(
        "/api/v1/quotes", json={key: body[key] for key in ("catering_request", "event")}
    )


def test_suggestions_and_resolution_autofill_the_address(address_app):
    app, client, provider = address_app
    token = str(uuid4())
    items = post(client, "/suggestions", {"input": "100 Exam", "session_token": token})
    assert items.status_code == 200
    assert items.json["data"]["suggestions"][0]["place_id"] == "synthetic.selection.signature"
    resolved = post(
        client, "/resolve", {"place_id": "synthetic.selection.signature", "session_token": token}
    )
    assert resolved.status_code == 200
    assert resolved.json["data"]["location"] == LOCATION
    assert resolved.json["data"]["service_area"]["status"] == "within_area"
    assert provider.calls[-1] == ("77477", {"postal_code": "77000", "country_code": "US"})
    assert items.headers["Cache-Control"] == "no-store"


def test_public_catering_contract_cannot_skip_routing_with_pickup(address_app):
    app, client, provider = address_app
    body = order_payload(service_type="pickup")
    assert quote(client, body).status_code == 422
    assert order(client, body).status_code == 422
    assert not provider.calls


def test_autofill_can_finish_before_any_distance_lookup(address_app):
    app, client, provider = address_app
    response = post(
        client,
        "/resolve",
        {
            "place_id": "synthetic.selection.signature",
            "session_token": str(uuid4()),
            "check_service_area": False,
        },
    )
    assert response.status_code == 200
    assert response.json["data"]["location"] == LOCATION
    assert "service_area" not in response.json["data"]
    assert not provider.calls
    assert post(client, "/check", {"location": LOCATION}).json["data"]["status"] == "within_area"
    assert len(provider.calls) == 1


@pytest.mark.parametrize("value", [None, 0, "false", {}, []])
def test_autofill_flag_must_be_boolean(address_app, value):
    _, client, provider = address_app
    assert (
        post(
            client,
            "/resolve",
            {
                "place_id": "synthetic.selection.signature",
                "session_token": str(uuid4()),
                "check_service_area": value,
            },
        ).status_code
        == 422
    )
    assert not provider.calls


@pytest.mark.parametrize("service", ["delivery", "full_service"])
@pytest.mark.parametrize("meters,outside", [(48280, False), (48281, True), (160935, True)])
def test_exact_thirty_mile_boundary_applies_to_both_services(address_app, service, meters, outside):
    app, client, provider = address_app
    provider.meters = meters
    checked = post(client, "/check", {"location": LOCATION}).json["data"]
    assert checked["status"] == ("outside_area" if outside else "within_area")
    body = order_payload(service_type=service)
    body["event"]["delivery_distance_miles"] = 0  # A forged browser value cannot authorize service.
    priced = quote(client, body)
    assert priced.status_code == 200
    assert priced.json["data"]["status"] == ("requires_review" if outside else "priced")
    if outside:
        estimate = priced.json["data"]["estimate"]
        assert estimate["subtotal_cents"] == 22500
        assert {line["code"] for line in estimate["line_items"]} == {"popsicles"}
        assert priced.json["data"]["pricing"] is None
    del body["event"]["delivery_distance_miles"]
    body["quote_id"] = priced.json["data"]["id"]
    result = order(client, body)
    assert result.status_code == (409 if outside else 201)
    if outside:
        assert result.json["error"]["code"] == "quote_not_finalized"
        assert not app.extensions["orders_memory"]["by_id"]


@pytest.mark.parametrize("mode", ["disabled", "outage", "rate_limited"])
def test_unverified_distance_has_no_price_and_cannot_create_an_order(address_app, mode):
    app, client, provider = address_app
    service = app.extensions["address_service"]
    if mode == "disabled":
        service.distance_provider = None
    elif mode == "outage":
        provider.fail = True
    else:
        service.check_budget = RequestBudget(per_address=0, total=0)
    body = order_payload()
    result = quote(client, body).json["data"]
    assert result["status"] == "requires_review"
    assert result["pricing"] is None
    assert result["estimate"]["subtotal_cents"] == 22500
    assert result["next_action"]["reason_code"] == "address_verification_unavailable"
    body["quote_id"] = result["id"]
    blocked = order(client, body)
    assert blocked.status_code == 409
    assert blocked.json["error"]["code"] == "quote_not_finalized"
    assert not app.extensions["orders_memory"]["by_id"]
    assert "private provider response" not in blocked.text


@pytest.mark.parametrize("service", ["delivery", "full_service"])
@pytest.mark.parametrize("shape,unit_cents", [("standard", 450), ("heart", 300)])
def test_owner_review_estimate_has_product_prices_without_logistics_or_deposit(
    address_app, service, shape, unit_cents
):
    app, client, provider = address_app
    provider.meters = 100000
    body = order_payload(service_type=service, popsicle_shape=shape, dry_ice_blocks=2)
    data = quote(client, body).json["data"]
    estimate = data["estimate"]
    assert data["status"] == "requires_review" and data["pricing"] is None
    assert estimate["subtotal_cents"] == 50 * unit_cents + 3000
    assert (
        sum(item["amount_cents"] for item in estimate["line_items"]) == estimate["subtotal_cents"]
    )
    assert not {"delivery_fee", "full_service_fee"}.intersection(
        item["code"] for item in estimate["line_items"]
    )
    assert "deposit_due_cents" not in estimate
    assert "owner" in data["next_action"]["message"]
    body["quote_id"] = data["id"]
    blocked = order(client, body)
    assert blocked.status_code == 409
    assert blocked.json["error"]["code"] == "quote_not_finalized"


def test_idempotent_order_replay_does_not_depend_on_provider_availability(address_app):
    app, client, provider = address_app
    body = order_payload()
    first = order(client, body)
    assert first.status_code == 201
    calls = len(provider.calls)
    provider.fail = True
    replay = order(client, body)
    assert replay.status_code == 201 and replay.json["data"] == first.json["data"]
    assert len(provider.calls) == calls
    body["event"]["location"]["line1"] = "200 Example Street"
    assert order(client, body).status_code == 409
    assert len(provider.calls) == calls
    assert order(client, body, "different-synthetic-address-key").status_code == 409
    assert order(client, body, "different-synthetic-address-key").json["error"]["code"] == (
        "quote_already_used"
    )
    assert len(app.extensions["orders_memory"]["by_id"]) == 1


@pytest.mark.parametrize(
    "location",
    [
        {},
        None,
        {**LOCATION, "country_code": "CA"},
        {**LOCATION, "postal_code": "not-a-zip"},
    ],
)
def test_incomplete_or_non_us_addresses_are_not_accepted(address_app, location):
    app, client, provider = address_app
    result = post(client, "/check", {"location": location})
    assert result.status_code == 200
    assert result.json["data"]["status"] == "invalid_address"
    assert not provider.calls


def test_address_endpoint_input_and_origin_limits(address_app):
    app, client, provider = address_app
    body = {"input": "100 Example", "session_token": str(uuid4())}
    assert client.post(BASE + "/suggestions", json=body).status_code == 403
    assert (
        client.post(
            BASE + "/suggestions", json=body, headers={"Origin": "https://other.invalid"}
        ).status_code
        == 403
    )
    assert post(client, "/suggestions", {**body, "extra": True}).status_code == 422
    assert post(client, "/suggestions", {**body, "session_token": "invalid"}).status_code == 422
    assert (
        post(
            client, "/resolve", {"place_id": "../../not-a-place", "session_token": str(uuid4())}
        ).status_code
        == 422
    )
    assert post(client, "/suggestions", {**body, "input": "x" * 5000}).status_code == 422
    app.extensions["address_service"].search_budget = RequestBudget(per_address=0, total=0)
    assert post(client, "/suggestions", body).status_code == 429


class Response:
    def __init__(self, data, status=200):
        self.data, self.status_code = data, status

    def json(self):
        return deepcopy(self.data)


class Session:
    def __init__(self, *data):
        self.data, self.calls = list(data), []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return Response(self.data.pop(0) if len(self.data) > 1 else self.data[0])


def address_result(**overrides):
    return {
        "housenumber": "100",
        "street": "Example Street",
        "city": "Houston",
        "state_code": "TX",
        "postcode": "77000",
        "country_code": "us",
        "result_type": "building",
        "lat": 29.7,
        "lon": -95.4,
        "rank": {"confidence": 1, "match_type": "full_match"},
        "datasource": {
            "attribution": "Synthetic source",
            "url": "https://example.invalid/source",
        },
        **overrides,
    }


def geocode_response(**overrides):
    return {"results": [address_result(**overrides)]}


def test_signed_geoapify_selection_round_trips_through_public_endpoints(address_app):
    app, client, _ = address_app
    session = Session(geocode_response())
    app.extensions["address_service"].provider = GeoapifyAddressProvider(
        "synthetic-key", session=session
    )
    token = str(uuid4())
    result = post(client, "/suggestions", {"input": "100 Exam", "session_token": token})
    selection = result.json["data"]["suggestions"][0]["place_id"]
    resolved = post(client, "/resolve", {"place_id": selection, "session_token": token})
    assert resolved.status_code == 200
    assert resolved.json["data"]["location"] == LOCATION
    assert resolved.json["data"]["service_area"]["status"] == "within_area"
    calls = len(session.calls)
    rejected = post(client, "/resolve", {"place_id": selection, "session_token": str(uuid4())})
    assert rejected.status_code == 503
    assert len(session.calls) == calls


@pytest.mark.parametrize("meters,outside", [(48280.32, False), (48280.321, True)])
def test_fractional_meter_boundary_is_not_rounded_for_eligibility(address_app, meters, outside):
    app, client, provider = address_app
    provider.meters = meters
    checked = post(client, "/check", {"location": LOCATION}).json["data"]
    assert checked["status"] == ("outside_area" if outside else "within_area")
    assert checked["distance_meters"] == meters


def test_autocomplete_signs_components_and_resolves_without_an_extra_provider_call():
    token = str(uuid4())
    session = Session(geocode_response(postcode="77000-1234"))
    provider = GeoapifyAddressProvider("synthetic-private-map-key", session=session)
    items = provider.suggestions("100 Exam", token)
    assert len(items) == 1
    selection = items[0]["place_id"]
    assert "synthetic-private-map-key" not in selection
    assert session.calls[0][1] == "https://api.geoapify.com/v1/geocode/autocomplete"
    params = session.calls[0][2]["params"]
    assert params["filter"] == "countrycode:us" and params["limit"] == 5
    assert "bias" not in params
    assert session.calls[0][2]["timeout"] == (2, 5)
    assert "sessionToken" not in params
    assert provider.resolve(selection, token) == {
        "location": {**LOCATION, "postal_code": "77000-1234"},
        "attributions": [{"name": "Synthetic source", "url": "https://example.invalid/source"}],
    }
    assert len(session.calls) == 1
    with pytest.raises(AddressProviderUnavailable):
        provider.resolve(selection, str(uuid4()))
    with pytest.raises(AddressProviderUnavailable):
        provider.resolve(selection + "tampered", token)


def test_expired_selection_requires_a_fresh_suggestion(monkeypatch):
    monkeypatch.setattr("itsdangerous.timed.TimestampSigner.get_timestamp", lambda _: 1700000000)
    provider = GeoapifyAddressProvider("synthetic-key", session=Session(geocode_response()))
    token = str(uuid4())
    selection = provider.suggestions("100 Exam", token)[0]["place_id"]
    monkeypatch.setattr("itsdangerous.timed.TimestampSigner.get_timestamp", lambda _: 1700000901)
    with pytest.raises(AddressProviderUnavailable):
        provider.resolve(selection, token)


@pytest.mark.parametrize(
    "url", ["javascript:alert(1)", "https://[", "https://user:pass@example.invalid"]
)
def test_autocomplete_drops_unsafe_source_links_and_incomplete_suggestions(url):
    session = Session(
        {
            "results": [
                address_result(datasource={"attribution": "Unsafe", "url": url}),
                address_result(result_type="street"),
                None,
            ]
        }
    )
    provider = GeoapifyAddressProvider("synthetic-key", session=session)
    items = provider.suggestions("100 Exam", str(uuid4()))
    assert len(items) == 1 and items[0]["attributions"] == []


def test_provider_budget_stops_network_calls_before_exceeding_local_allowance():
    session = Session(geocode_response())
    provider = GeoapifyAddressProvider("synthetic-key", session=session)
    provider.daily_budget = RequestBudget(per_address=1, total=1, seconds=86400)
    provider.suggestions("100 Exam", str(uuid4()))
    with pytest.raises(AddressProviderUnavailable):
        provider.suggestions("200 Exam", str(uuid4()))
    assert len(session.calls) == 1


@pytest.mark.parametrize("mode", ["timeout", "http", "json"])
def test_provider_errors_do_not_disclose_private_urls_or_addresses(mode):
    class FailedSession:
        def request(self, *args, **kwargs):
            if mode == "timeout":
                raise requests.Timeout("apiKey=synthetic-private-map-key and private address")
            if mode == "http":
                return Response({"error": "private provider response"}, status=429)
            raise ValueError("private provider response")

    with pytest.raises(AddressProviderUnavailable) as failure:
        GeoapifyAddressProvider("synthetic-private-map-key", session=FailedSession()).suggestions(
            "100 Exam", str(uuid4())
        )
    assert not str(failure.value)


def test_geoapify_config_registers_private_provider_without_exposing_the_key(address_app):
    _, client, _ = address_app
    app = create_app(
        {
            "TESTING": True,
            "AUTH_ENABLED": False,
            "CUSTOMER_AUTH_ENABLED": False,
            "DB_USER": "",
            "DB_PASSWORD": "",
            "GEOAPIFY_API_KEY": "synthetic-private-map-key",
            "AUTH_ORIGIN": ORIGIN,
            "CORS_ORIGINS": [ORIGIN],
            "AUTOMATION_ENABLED": False,
            "EMAIL_ENABLED": False,
        }
    )
    assert isinstance(app.extensions["address_service"].provider, GeoapifyAddressProvider)
    response = app.test_client().get(BASE + "/config")
    assert response.json["data"]["enabled"] is True
    assert response.json["data"]["radius_miles"] == 30
    assert "synthetic-private-map-key" not in response.text
