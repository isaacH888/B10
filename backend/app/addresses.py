"""Private-key Geoapify address assistance and server-authoritative service area checks."""

import math
import re
from fractions import Fraction
from urllib.parse import urlsplit
from uuid import UUID

import requests
from flask import Blueprint, current_app, g, jsonify, request
from itsdangerous import BadData, URLSafeTimedSerializer

from .auth.errors import AuthError
from .postal_areas import (
    CENTER_NAME,
    CENTER_POSTAL_CODE,
    DISTANCE_METHOD,
    PostalCodeUnavailable,
    ZipRadiusProvider,
    clean_postal_location,
)
from .traffic import RequestBudget

addresses = Blueprint("addresses", __name__)
METERS_PER_MILE = Fraction(201168, 125)
PLACE_ID = re.compile(r"[A-Za-z0-9_.-]{1,2048}\Z")
ADDRESS_FIELDS = ("line1", "city", "region", "postal_code", "country_code")


class AddressProviderUnavailable(Exception):
    """Provider details, addresses and credentials must not escape in errors."""


def clean_location(value):
    if not isinstance(value, dict) or set(value) - {*ADDRESS_FIELDS, "line2"}:
        return None
    limits = dict(line1=200, city=100, region=2, postal_code=10, country_code=2)
    location = {}
    for key, limit in limits.items():
        item = value.get(key)
        if not isinstance(item, str) or not 1 <= len(item.strip()) <= limit:
            return None
        location[key] = item.strip()
    location["region"] = location["region"].upper()
    location["country_code"] = location["country_code"].upper()
    if (
        location["country_code"] != "US"
        or not re.fullmatch(r"[A-Z]{2}", location["region"])
        or not re.fullmatch(r"[0-9]{5}(?:-[0-9]{4})?", location["postal_code"])
    ):
        return None
    # Unit/suite details do not change which building is routed to.
    return location


class GeoapifyAddressProvider:
    def __init__(self, api_key, *, session=None):
        self.api_key = api_key
        self.session = session or requests.Session()
        self.signer = URLSafeTimedSerializer(api_key, salt="catering-address-selection-v1")
        # A per-worker safety net, not an account-wide quota across restarts/replicas.
        self.daily_budget = RequestBudget(per_address=2800, total=2800, seconds=86400)

    def _request(self, path, **params):
        if not self.daily_budget.allow("geoapify"):
            raise AddressProviderUnavailable()
        try:
            response = self.session.request(
                "GET",
                "https://api.geoapify.com/v1/" + path,
                params={**params, "apiKey": self.api_key, "format": "json"},
                headers={"Accept": "application/json"},
                timeout=(2, 5 if path == "geocode/autocomplete" else 3),
                allow_redirects=False,
            )
            if response.status_code != 200:
                raise AddressProviderUnavailable()
            data = response.json()
            if not isinstance(data, dict) or not isinstance(data.get("results"), list):
                raise AddressProviderUnavailable()
            return data["results"]
        except (requests.RequestException, ValueError):
            # Provider URLs contain the key; never propagate them or response bodies.
            raise AddressProviderUnavailable() from None

    @staticmethod
    def _location(item):
        if not isinstance(item, dict) or item.get("result_type") not in {"building", "amenity"}:
            raise AddressProviderUnavailable()
        parts = ("housenumber", "street", "city", "state_code", "postcode", "country_code")
        if any(not isinstance(item.get(key), str) or not item[key].strip() for key in parts):
            raise AddressProviderUnavailable()
        location = clean_location(
            {
                "line1": item["housenumber"].strip() + " " + item["street"].strip(),
                "city": item["city"],
                "region": item["state_code"],
                "postal_code": item["postcode"],
                "country_code": item["country_code"],
            }
        )
        if location is None:
            raise AddressProviderUnavailable()
        return location

    @staticmethod
    def _attributions(item):
        source = item.get("datasource", {})
        if not isinstance(source, dict):
            return []
        name, url = source.get("attribution"), source.get("url")
        if not isinstance(name, str) or not isinstance(url, str) or len(url) > 2000:
            return []
        try:
            parsed = urlsplit(url)
        except ValueError:
            return []
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            return []
        return [{"name": name[:300], "url": url}]

    def suggestions(self, text, session_token):
        items = self._request(
            "geocode/autocomplete",
            text=text,
            lang="en",
            limit=5,
            filter="countrycode:us",
        )
        results = []
        for item in items[:5]:
            try:
                location = self._location(item)
            except AddressProviderUnavailable:
                continue
            attributions = self._attributions(item)
            # Autocomplete already supplies address components. Signing avoids an
            # extra paid Details call or keeping customer searches in server memory.
            selection = self.signer.dumps(
                {
                    "location": location,
                    "session": session_token,
                    "attributions": attributions,
                }
            )
            if not PLACE_ID.fullmatch(selection):
                continue
            results.append(
                {
                    "place_id": selection,
                    "label": ", ".join(location[key] for key in ADDRESS_FIELDS),
                    "attributions": attributions,
                }
            )
        return results

    def resolve(self, place_id, session_token):
        try:
            data = self.signer.loads(place_id, max_age=900)
        except BadData:
            raise AddressProviderUnavailable() from None
        if not isinstance(data, dict) or data.get("session") != session_token:
            raise AddressProviderUnavailable()
        location = clean_location(data.get("location"))
        if location is None:
            raise AddressProviderUnavailable()
        return {"location": location, "attributions": data.get("attributions", [])}


class AddressService:
    def __init__(self, rules, *, provider=None, distance_provider=None):
        self.rules, self.origin, self.provider = rules, CENTER_POSTAL_CODE, provider
        self.distance_provider = (
            distance_provider if distance_provider is not None else ZipRadiusProvider()
        )
        self.search_budget = RequestBudget(per_address=60, total=300)
        self.check_budget = RequestBudget(per_address=120, total=1200)

    @property
    def config(self):
        return {
            "enabled": self.provider is not None,
            "radius_miles": self.rules.delivery_max_radius_miles,
            "origin_name": CENTER_NAME,
            "origin_postal_code": CENTER_POSTAL_CODE,
            "distance_method": DISTANCE_METHOD,
            "service_area_enabled": self.distance_provider is not None,
        }

    def check(self, location, address=None):
        result = {
            **self.config,
            "status": "unavailable",
            "distance_miles": None,
            "message": "We could not locate this ZIP code. You can continue to a quote estimate and contact the owner for review.",
        }
        clean = clean_postal_location(location)
        if clean is None:
            return {
                **result,
                "status": "invalid_address",
                "message": "Enter a valid US ZIP code to check the service area.",
            }
        if self.distance_provider is None or not self.check_budget.allow(address):
            return result
        try:
            meters = self.distance_provider.distance_meters(self.origin, clean)
            if type(meters) not in {int, float} or not math.isfinite(meters) or meters < 0:
                raise AddressProviderUnavailable()
        except (
            AddressProviderUnavailable,
            PostalCodeUnavailable,
            TypeError,
            KeyError,
            AttributeError,
        ):
            return result
        miles = Fraction(str(meters)) / METERS_PER_MILE
        outside = miles > Fraction(str(self.rules.delivery_max_radius_miles))
        radius = f"{self.rules.delivery_max_radius_miles:g}"
        return {
            **result,
            "status": "outside_area" if outside else "within_area",
            # Keep the boundary comparison exact; round only the displayed value up.
            "distance_miles": math.ceil(miles * 100) / 100,
            "distance_meters": meters,
            "message": (
                f"This ZIP is outside our {radius}-mile radius from Stafford 77477. You can continue to a quote estimate for owner review."
                if outside
                else f"This ZIP is within our {radius}-mile radius from Stafford 77477."
            ),
        }


def register_addresses(app):
    rules = app.extensions["pricing_rules"]
    key = app.config.get("GEOAPIFY_API_KEY", "").strip()
    provider = app.config.get("ADDRESS_PROVIDER")
    if provider is None and key:
        provider = GeoapifyAddressProvider(key)
    app.extensions["address_service"] = AddressService(
        rules,
        provider=provider,
        distance_provider=app.config.get("ADDRESS_DISTANCE_PROVIDER"),
    )
    app.register_blueprint(addresses, url_prefix="/api/v1/catering/address")


def _data(value):
    return jsonify(data=value, meta={"request_id": g.request_id})


def _input(fields, optional=()):
    if request.headers.get("Origin") != current_app.config["AUTH_ORIGIN"]:
        raise AuthError("forbidden", "This request is not allowed.", 403)
    if not request.is_json or (request.content_length or 0) > 4096:
        raise AuthError("validation_error", "Send a small JSON address request.", 422)
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or not fields <= set(body) or set(body) - fields - set(optional):
        raise AuthError("validation_error", "Send only the required address fields.", 422)
    return body


def _session_token(value):
    try:
        return isinstance(value, str) and len(value) == 36 and UUID(value).version == 4
    except ValueError:
        return False


@addresses.get("/config")
def configuration():
    return _data(current_app.extensions["address_service"].config)


@addresses.post("/suggestions")
def suggestions():
    body = _input({"input", "session_token"})
    text = body["input"]
    if (
        not isinstance(text, str)
        or not 4 <= len(text.strip()) <= 200
        or not _session_token(body["session_token"])
    ):
        raise AuthError("validation_error", "Enter at least four address characters.", 422)
    service = current_app.extensions["address_service"]
    if service.provider is None:
        raise AuthError(
            "address_unavailable", "Address suggestions are temporarily unavailable.", 503
        )
    if not service.search_budget.allow(request.remote_addr):
        raise AuthError("rate_limited", "Please wait before searching again.", 429)
    try:
        items = service.provider.suggestions(text.strip(), body["session_token"])
    except (AddressProviderUnavailable, TypeError, KeyError, AttributeError):
        raise AuthError(
            "address_unavailable", "Address suggestions are temporarily unavailable.", 503
        ) from None
    return _data({"suggestions": items})


@addresses.post("/resolve")
def resolve():
    body = _input({"place_id", "session_token"}, optional={"check_service_area"})
    if (
        not isinstance(body["place_id"], str)
        or not PLACE_ID.fullmatch(body["place_id"])
        or not _session_token(body["session_token"])
        or type(body.get("check_service_area", True)) is not bool
    ):
        raise AuthError("validation_error", "Select an address suggestion.", 422)
    service = current_app.extensions["address_service"]
    if service.provider is None:
        raise AuthError(
            "address_unavailable", "Address suggestions are temporarily unavailable.", 503
        )
    if not service.search_budget.allow(request.remote_addr):
        raise AuthError("rate_limited", "Please wait before searching again.", 429)
    try:
        resolved = service.provider.resolve(body["place_id"], body["session_token"])
        location = resolved["location"]
    except (AddressProviderUnavailable, TypeError, KeyError, AttributeError):
        raise AuthError(
            "address_unavailable", "Enter the address manually and try the distance check.", 503
        ) from None
    result = {"location": location, "attributions": resolved.get("attributions", [])}
    if body.get("check_service_area", True):
        result["service_area"] = service.check(location, request.remote_addr)
    return _data(result)


@addresses.post("/check")
def check():
    body = _input({"location"})
    return _data(
        current_app.extensions["address_service"].check(body["location"], request.remote_addr)
    )
