"""The service boundary is a ZIP-area radius from Stafford, independent of APIs."""

import math

import pytest
from address_fixtures import LOCATION
from app import create_app
from app.addresses import METERS_PER_MILE
from app.postal_areas import (
    CENTER_POSTAL_CODE,
    EARTH_RADIUS_METERS,
    PostalCodeUnavailable,
    ZipRadiusProvider,
    postal_centers,
)

ORIGIN = "http://localhost:5173"
BASE = "/api/v1/catering/address"


@pytest.fixture
def local_app(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    app = create_app(
        {
            "TESTING": True,
            "AUTH_ENABLED": False,
            "CUSTOMER_AUTH_ENABLED": False,
            "DB_USER": "",
            "DB_PASSWORD": "",
            "GEOAPIFY_API_KEY": "",
            "AUTH_ORIGIN": ORIGIN,
            "CORS_ORIGINS": [ORIGIN],
            "DELIVERY_ORIGIN_ADDRESS": "An old kitchen setting must not move the center",
            "AUTOMATION_ENABLED": False,
            "EMAIL_ENABLED": False,
        }
    )
    return app, app.test_client()


def check(client, code, **extra):
    return client.post(
        BASE + "/check",
        json={"location": {"postal_code": code, **extra}},
        headers={"Origin": ORIGIN},
    )


def test_published_stafford_point_and_leading_zeroes_are_preserved():
    points = postal_centers()
    assert len(points) == 33791
    assert points["77477"] == [29.623924, -95.567088]
    assert "00725" in points


@pytest.mark.parametrize(
    "code,within",
    [
        ("77477", True),
        ("77477-1234", True),
        ("77478", True),
        ("77479", True),
        ("77459", True),
        ("77002", True),
        ("77058", True),
        ("77550", False),
        ("77380", False),
        ("77301", False),
        ("34698", False),
        ("00725", False),
    ],
)
def test_zip_radius_works_without_an_api_key_or_street_match(local_app, monkeypatch, code, within):
    monkeypatch.setattr(
        "requests.sessions.Session.request",
        lambda *a, **kw: pytest.fail("ZIP checks must not call a network service"),
    )
    app, client = local_app
    config = client.get(BASE + "/config").json["data"]
    assert config["enabled"] is False
    assert config["service_area_enabled"] is True
    assert config["origin_postal_code"] == CENTER_POSTAL_CODE == "77477"
    assert config["distance_method"] == "zip_centroid_radius"
    response = check(client, code)
    assert response.status_code == 200
    assert response.json["data"]["status"] == ("within_area" if within else "outside_area")
    if code.startswith("77477"):
        assert response.json["data"]["distance_meters"] == 0


@pytest.mark.parametrize("code", ["00000", "00501"])
def test_missing_zcta_does_not_guess_a_distance_or_approve(local_app, code):
    _, client = local_app
    result = check(client, code).json["data"]
    assert result["status"] == "unavailable" and result["distance_miles"] is None
    with pytest.raises(PostalCodeUnavailable):
        ZipRadiusProvider().distance_meters("77477", {"postal_code": code})


@pytest.mark.parametrize("code", ["", "7747", "774770", "77477-12", None, 77477, "not-a-zip"])
def test_bad_zip_input_never_approves(local_app, code):
    _, client = local_app
    assert check(client, code).json["data"]["status"] == "invalid_address"


def test_zip_only_check_accepts_valid_zip_but_rejects_non_us_country(local_app):
    _, client = local_app
    assert check(client, "77477", line1="", city="").json["data"]["status"] == "within_area"
    assert check(client, "77477", country_code="CA").json["data"]["status"] == "invalid_address"


def test_old_kitchen_origin_cannot_move_the_fixed_stafford_anchor():
    provider = ZipRadiusProvider()
    assert provider.distance_meters("A different origin", {"postal_code": "77477"}) == 0


def test_radius_uses_geographic_distance_and_unrounded_boundary(local_app):
    app, client = local_app

    def lat(miles):
        return math.degrees(miles * float(METERS_PER_MILE) / EARTH_RADIUS_METERS)

    app.extensions["address_service"].distance_provider = ZipRadiusProvider(
        {
            "77477": [0, 0],
            "11111": [lat(29.999), 0],
            "22222": [lat(30.001), 0],
        }
    )
    assert check(client, "11111").json["data"]["status"] == "within_area"
    assert check(client, "22222").json["data"]["status"] == "outside_area"


def test_zip_check_does_not_remove_full_address_requirement_from_quotes(local_app):
    from test_orders import order_payload

    _, client = local_app
    body = order_payload()
    body["event"]["location"] = {"postal_code": "77477", "country_code": "US"}
    response = client.post(
        "/api/v1/quotes", json={k: body[k] for k in ("catering_request", "event")}
    )
    assert response.json["data"]["status"] == "requires_review"
    assert response.json["data"]["pricing"] is None
    assert response.json["data"]["estimate"]["subtotal_cents"] == 22500


def test_complete_local_quote_no_longer_needs_a_provider_street_match(local_app):
    from test_orders import order_payload

    _, client = local_app
    body = order_payload()
    body["event"]["location"] = {
        **LOCATION,
        "line1": "Customer-entered event street",
        "city": "Stafford",
        "postal_code": "77477",
    }
    body["event"]["delivery_distance_miles"] = 1000
    response = client.post(
        "/api/v1/quotes", json={k: body[k] for k in ("catering_request", "event")}
    )
    assert response.status_code == 200
    assert response.json["data"]["status"] == "priced"
    assert response.json["data"]["pricing"]["total_cents"] == 25000
    assert response.json["data"]["pricing_revision"] == "pricing_config_2.1.0"
