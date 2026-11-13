"""Offline ZIP-area radius checks from the fixed Stafford 77477 center.

Census ZCTA representative points approximate ZIP centers, not delivery routes
or individual street addresses. See data/README.md for provenance/limitations.
"""

import json
import math
import re
from functools import lru_cache
from pathlib import Path

CENTER_POSTAL_CODE = "77477"
CENTER_NAME = "Stafford, TX 77477"
DISTANCE_METHOD = "zip_centroid_radius"
EARTH_RADIUS_METERS = 6371008.8
POSTAL_CODE = re.compile(r"[0-9]{5}(?:-[0-9]{4})?\Z")


class PostalCodeUnavailable(Exception):
    """The published dataset has no reliable point for this ZIP."""


def clean_postal_location(value):
    if not isinstance(value, dict) or set(value) - {
        "line1",
        "line2",
        "city",
        "region",
        "postal_code",
        "country_code",
    }:
        return None
    code, country = value.get("postal_code"), value.get("country_code", "US")
    if (
        not isinstance(code, str)
        or not POSTAL_CODE.fullmatch(code.strip())
        or not isinstance(country, str)
        or country.strip().upper() != "US"
    ):
        return None
    return {"postal_code": code.strip()[:5], "country_code": "US"}


@lru_cache(maxsize=1)
def postal_centers():
    path = Path(__file__).with_name("data") / "us-zcta-centers-2026.json"
    data = json.loads(path.read_text())
    if CENTER_POSTAL_CODE not in data:
        raise ValueError("The Stafford service-area center is missing")
    for code, point in data.items():
        if (
            not re.fullmatch(r"[0-9]{5}", code)
            or not isinstance(point, list)
            or len(point) != 2
            or any(type(n) not in {int, float} or not math.isfinite(n) for n in point)
            or not -90 <= point[0] <= 90
            or not -180 <= point[1] <= 180
        ):
            raise ValueError("Invalid published ZIP-area coordinates")
    return data


def geographic_distance_meters(start, end):
    lat1, lon1, lat2, lon2 = map(math.radians, (*start, *end))
    haversine = math.sin((lat2 - lat1) / 2) ** 2 + (
        math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * EARTH_RADIUS_METERS * math.asin(math.sqrt(min(1.0, max(0.0, haversine))))


class ZipRadiusProvider:
    def __init__(self, centers=None):
        self.centers = postal_centers() if centers is None else centers

    def distance_meters(self, origin, location):
        # The anchor is deliberately fixed; legacy kitchen settings cannot move it.
        start = self.centers.get(CENTER_POSTAL_CODE)
        end = self.centers.get(location["postal_code"][:5])
        if start is None or end is None:
            raise PostalCodeUnavailable()
        return geographic_distance_meters(start, end)
