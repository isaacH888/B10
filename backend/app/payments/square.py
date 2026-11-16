"""Square's versioned REST API and documented HMAC notification authentication."""

import base64
import hashlib
import hmac
import re
from urllib.parse import quote

import requests

from ..automation.domain import DomainError
from .settings import API_VERSION


class SquareFailure(RuntimeError):
    """Private provider details must never reach responses, delivery jobs or logs."""


def valid_signature(body, signature, key, notification_url):
    expected = base64.b64encode(
        hmac.new(
            key.encode("utf-8"),
            notification_url.encode("utf-8") + body,
            hashlib.sha256,
        ).digest()
    )
    return isinstance(signature, str) and hmac.compare_digest(expected, signature.encode("utf-8"))


class SquareGateway:
    def __init__(self, settings, http=None):
        self.base = (
            "https://connect.squareupsandbox.com"
            if settings["SQUARE_ENVIRONMENT"] == "sandbox"
            else "https://connect.squareup.com"
        )
        self.headers = {
            "Authorization": "Bearer " + settings["SQUARE_ACCESS_TOKEN"],
            "Square-Version": API_VERSION,
            "Content-Type": "application/json",
        }
        self.http = http or requests.Session()

    @staticmethod
    def _id(value):
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
            raise DomainError(
                "Square returned an invalid resource identifier.", 409, "square_mismatch"
            )
        return quote(value, safe="")

    def _request(self, method, path, *, body=None, missing=False):
        try:
            response = self.http.request(
                method,
                self.base + path,
                json=body,
                headers=self.headers,
                timeout=(3, 7),
                allow_redirects=False,
            )
            if missing and response.status_code == 404:
                return None
            if not 200 <= response.status_code < 300:
                raise SquareFailure("Square request failed")
            data = response.json()
            if not isinstance(data, dict) or data.get("errors"):
                raise SquareFailure("Square request failed")
            return data
        except (requests.RequestException, ValueError):
            raise SquareFailure("Square request failed") from None

    def create(self, params, key):
        return self._request(
            "POST", "/v2/online-checkout/payment-links", body={**params, "idempotency_key": key}
        )

    def order(self, order_id):
        return self._request("GET", "/v2/orders/" + self._id(order_id))["order"]

    def payment(self, payment_id):
        return self._request("GET", "/v2/payments/" + self._id(payment_id))["payment"]

    def delete(self, link_id):
        return self._request(
            "DELETE", "/v2/online-checkout/payment-links/" + self._id(link_id), missing=True
        )
