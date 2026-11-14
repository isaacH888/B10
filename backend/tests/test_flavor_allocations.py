"""Requested flavor quantities must survive the real quote/order/booking workflow."""

from copy import deepcopy

import pytest
from test_admin_orders import admin_app as admin_app
from test_admin_orders import assert_contract
from test_auth import auth_app as auth_app
from test_automation_routes import owner_app as owner_app
from test_automation_routes import signed_owner
from test_automation_store import sql_settings as sql_settings
from test_orders import app as app
from test_orders import bind_quote, order_payload
from test_orders import client as client

FLAVORS = [
    "Mango Lime",
    "Strawberry Lime",
    "Mango Dragonfruit",
    "Strawberries and Cream",
    "Watermelon Strawberry and Kiwi",
]
MIX = [{"flavor": flavor, "quantity": 10} for flavor in FLAVORS]


def request_mix(client, endpoint, mix):
    body = order_payload()
    body["catering_request"]["flavor_allocations"] = mix
    if endpoint == "/quotes":
        body = {key: body[key] for key in ("catering_request", "event")}
    elif mix in (MIX, []):
        bind_quote(client, body)
    return client.post(
        "/api/v1" + endpoint,
        json=body,
        headers={"Idempotency-Key": "flavor-mix-synthetic-0123456789"},
    )


@pytest.mark.parametrize("endpoint", ["/quotes", "/orders"])
def test_valid_five_flavor_mix_matches_contract(client, endpoint):
    response = request_mix(client, endpoint, MIX)
    assert response.status_code == (200 if endpoint == "/quotes" else 201)
    assert response.json["data"]["catering_request"]["flavor_allocations"] == MIX
    assert_contract(response, "QuoteResponse" if endpoint == "/quotes" else "OrderResponse")


@pytest.mark.parametrize("endpoint", ["/quotes", "/orders"])
@pytest.mark.parametrize(
    "mix",
    [
        None,
        {},
        "Mango Lime",
        [{"flavor": "Mango Lime", "quantity": 49}],
        [{"flavor": "Mango Lime", "quantity": 51}],
        [{"flavor": "Mango Lime", "quantity": 0}],
        [{"flavor": "Mango Lime", "quantity": -1}],
        [{"flavor": "Mango Lime", "quantity": 50.0}],
        [{"flavor": "Mango Lime", "quantity": "50"}],
        [{"flavor": "Mango Lime", "quantity": True}],
        [{"flavor": "Mango Lime", "quantity": 100001}],
        [{"flavor": "", "quantity": 50}],
        [{"flavor": " " * 5, "quantity": 50}],
        [{"flavor": "x" * 101, "quantity": 50}],
        [{"flavor": 123, "quantity": 50}],
        [{"flavor": "Mango Lime"}],
        [{"flavor": "Mango Lime", "quantity": 50, "price": 1}],
        [None],
        [{"flavor": "Mango Lime", "quantity": 25}, {"flavor": " mango lime ", "quantity": 25}],
        [{"flavor": str(index), "quantity": 10} for index in range(6)],
    ],
)
def test_invalid_mix_is_rejected_by_quote_and_order_routes(client, endpoint, mix):
    response = request_mix(client, endpoint, mix)
    assert response.status_code == 422
    assert response.json["error"]["code"] == "validation_error"
    assert any(
        field["field"].startswith("catering_request.flavor_allocations")
        for field in response.json["error"]["fields"]
    )


def test_flavor_mix_does_not_add_unapproved_charges(client):
    body = order_payload()
    quote = {key: body[key] for key in ("catering_request", "event")}
    original = client.post("/api/v1/quotes", json=quote)
    selected = request_mix(client, "/quotes", MIX)
    assert original.status_code == selected.status_code == 200
    assert selected.json["data"]["pricing"] == original.json["data"]["pricing"]


@pytest.mark.parametrize("endpoint", ["/quotes", "/orders"])
def test_empty_mix_keeps_owner_choice_available(client, endpoint):
    response = request_mix(client, endpoint, [])
    assert response.status_code in (200, 201)
    assert response.json["data"]["catering_request"]["flavor_allocations"] == []


def test_flavor_mix_persists_through_owner_reads_intake_and_replay(admin_app):
    client, headers = signed_owner(admin_app)
    body = order_payload()
    body["catering_request"].update(
        flavor_allocations=deepcopy(MIX), flavor_requests="Please confirm allergy ingredients."
    )
    bind_quote(client, body)
    key = {"Idempotency-Key": "persisted-flavor-mix-0123456789"}
    response = client.post("/api/v1/orders", json=body, headers=key)
    assert response.status_code == 201
    order = response.json["data"]
    saved = client.get("/api/v1/admin/orders/" + order["id"])
    assert saved.status_code == 200
    assert saved.json["data"]["order"]["catering_request"]["flavor_allocations"] == MIX
    imported = client.post(
        "/api/v1/admin/automation/orders/" + order["id"] + "/booking",
        json={"contract_url": "https://example.invalid/synthetic"},
        headers=headers,
    )
    assert imported.status_code == 201
    assert imported.json["data"]["source_order"]["catering_request"]["flavor_allocations"] == MIX
    replay = client.post("/api/v1/orders", json=body, headers=key)
    assert replay.status_code == 201 and replay.json["data"] == order
    changed = deepcopy(body)
    changed["catering_request"]["flavor_allocations"][0]["quantity"] = 11
    changed["catering_request"]["flavor_allocations"][1]["quantity"] = 9
    assert client.post("/api/v1/orders", json=changed, headers=key).status_code == 409
