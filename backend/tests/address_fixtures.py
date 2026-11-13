"""Explicit address-provider fixtures; business tests never call a live provider."""

from app.addresses import AddressProviderUnavailable

LOCATION = {
    "line1": "100 Example Street",
    "city": "Houston",
    "region": "TX",
    "postal_code": "77000",
    "country_code": "US",
}


class FixedAddressProvider:
    def __init__(self, meters=0):
        self.meters = meters
        self.fail = False
        self.calls = []

    def distance_meters(self, origin, location):
        self.calls.append((origin, location))
        if self.fail:
            raise AddressProviderUnavailable("private provider response")
        return self.meters

    def suggestions(self, text, session_token):
        return [
            {
                "place_id": "synthetic.selection.signature",
                "label": "100 Example Street, Houston, TX, USA",
            }
        ]

    def resolve(self, place_id, session_token):
        return {"location": dict(LOCATION), "attributions": []}
