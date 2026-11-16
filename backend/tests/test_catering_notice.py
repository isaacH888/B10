"""Only custom flavors require two weeks; short-notice catering uses available stock."""

from datetime import datetime, timedelta, timezone

import pytest
from app import orders, quotes
from app.quotes import QuoteError, validate_catering_notice
from test_auth import auth_app as auth_app
from test_orders import HEADERS, bind_quote, order_payload
from test_orders import app as app
from test_orders import client as client


@pytest.fixture
def clock(monkeypatch):
    instant = [datetime(2030, 1, 1, 12, tzinfo=timezone.utc)]

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant[0].astimezone(tz) if tz else instant[0].replace(tzinfo=None)

    monkeypatch.setattr(quotes, "datetime", FrozenDateTime)
    monkeypatch.setattr(orders, "datetime", FrozenDateTime)
    return instant


@pytest.mark.parametrize(
    "now,start",
    [
        ("2030-01-01T12:00:00+00:00", "2030-01-15T06:00:00-06:00"),
        ("2027-03-01T12:00:00-06:00", "2027-03-15T13:00:00-05:00"),
        ("2027-11-01T12:00:00-05:00", "2027-11-15T11:00:00-06:00"),
    ],
)
def test_exact_cutoff_and_central_daylight_saving_changes(now, start):
    now = datetime.fromisoformat(now)
    custom = {"flavor_requests": "Lavender"}
    validate_catering_notice(custom, {"starts_at": start}, now=now)
    too_soon = datetime.fromisoformat(start) - timedelta(microseconds=1)
    with pytest.raises(QuoteError, match="two weeks") as error:
        validate_catering_notice(custom, {"starts_at": too_soon.isoformat()}, now=now)
    assert error.value.reason == "ERR_CUSTOM_NOTICE"
    assert error.value.field == "catering_request.flavor_requests"


@pytest.mark.parametrize("service", ["delivery", "full_service"])
@pytest.mark.parametrize("days", [1, 3, 10.5, 13.999])
@pytest.mark.parametrize("shape", ["standard", "heart"])
def test_short_notice_menu_orders_shapes_and_add_ons_are_allowed(
    client, clock, service, days, shape
):
    body = order_payload(
        service_type=service,
        popsicle_shape=shape,
        allergy_notes="Nut allergy",
        add_ons=["Napkins"],
        flavor_allocations=[{"flavor": "Mango Lime", "quantity": 50}],
    )
    start = clock[0] + timedelta(days=days)
    body["event"].update(
        starts_at=start.isoformat(), ends_at=(start + timedelta(hours=2)).isoformat()
    )
    bind_quote(client, body)
    response = client.post("/api/v1/orders", json=body, headers=HEADERS)
    assert response.status_code == 201, response.json
    assert response.json["data"]["status"] == "pending_review"
    assert response.json["data"]["catering_request"]["allergy_notes"] == "Nut allergy"
    assert response.json["data"]["catering_request"]["add_ons"] == ["Napkins"]


@pytest.mark.parametrize("service", ["delivery", "full_service"])
@pytest.mark.parametrize("days", [-1, 0])
def test_past_or_current_event_starts_are_still_rejected(client, clock, service, days):
    body = order_payload(service_type=service)
    start = clock[0] + timedelta(days=days)
    body["event"].update(
        starts_at=start.isoformat(), ends_at=(start + timedelta(hours=2)).isoformat()
    )
    response = client.post(
        "/api/v1/quotes", json={key: body[key] for key in ("catering_request", "event")}
    )
    assert response.status_code == 422
    assert response.json["error"]["code"] == "validation_error"
    assert response.json["error"]["fields"][0]["field"] == "event.starts_at"
    assert "future" in response.json["error"]["message"]


@pytest.mark.parametrize("service", ["delivery", "full_service"])
@pytest.mark.parametrize(
    "custom,field",
    [
        ({"flavor_requests": "Lavender"}, "catering_request.flavor_requests"),
        (
            {"flavor_allocations": [{"flavor": "Lavender", "quantity": 50}]},
            "catering_request.flavor_allocations",
        ),
    ],
)
def test_short_notice_custom_flavors_are_rejected(client, clock, service, custom, field):
    body = order_payload(service_type=service, **custom)
    start = clock[0] + timedelta(days=1)
    body["event"].update(
        starts_at=start.isoformat(), ends_at=(start + timedelta(hours=2)).isoformat()
    )
    response = client.post(
        "/api/v1/quotes", json={key: body[key] for key in ("catering_request", "event")}
    )
    assert response.status_code == 422
    assert response.json["error"]["fields"][0]["field"] == field
    assert "14 days" in response.json["error"]["message"]


@pytest.mark.parametrize("service", ["delivery", "full_service"])
def test_custom_flavors_accept_exactly_fourteen_days(client, clock, service):
    body = order_payload(service_type=service, flavor_requests="Lavender")
    start = clock[0] + timedelta(days=14)
    body["event"].update(
        starts_at=start.isoformat(), ends_at=(start + timedelta(hours=2)).isoformat()
    )
    bind_quote(client, body)
    response = client.post("/api/v1/orders", json=body, headers=HEADERS)
    assert response.status_code == 201, response.json


def test_custom_quote_cannot_authorize_order_inside_notice_period(client, app, clock):
    body = order_payload(flavor_requests="Lavender")
    start = clock[0] + timedelta(days=14, minutes=1)
    body["event"].update(
        starts_at=start.isoformat(), ends_at=(start + timedelta(hours=2)).isoformat()
    )
    quote = bind_quote(client, body)
    clock[0] += timedelta(minutes=2)
    response = client.post("/api/v1/orders", json=body, headers=HEADERS)
    assert response.status_code == 422
    assert response.json["error"]["fields"][0]["field"] == "catering_request.flavor_requests"
    assert app.extensions["orders_memory"]["by_id"] == {}
    assert app.extensions["quotes_memory"]["quotes"][quote["id"]]["is_used"] is False


def test_successful_custom_submission_replays_after_crossing_notice_cutoff(client, clock):
    body = order_payload(flavor_requests="Lavender")
    start = clock[0] + timedelta(days=14)
    body["event"].update(
        starts_at=start.isoformat(), ends_at=(start + timedelta(hours=2)).isoformat()
    )
    bind_quote(client, body)
    first = client.post("/api/v1/orders", json=body, headers=HEADERS)
    assert first.status_code == 201
    clock[0] += timedelta(minutes=2)
    replay = client.post("/api/v1/orders", json=body, headers=HEADERS)
    assert replay.status_code == 201
    assert replay.json["data"] == first.json["data"]


def test_menu_order_remains_allowed_when_quote_crosses_custom_cutoff(client, clock):
    body = order_payload(flavor_requests="   ")
    start = clock[0] + timedelta(days=14, minutes=1)
    body["event"].update(
        starts_at=start.isoformat(), ends_at=(start + timedelta(hours=2)).isoformat()
    )
    bind_quote(client, body)
    clock[0] += timedelta(minutes=2)
    response = client.post("/api/v1/orders", json=body, headers=HEADERS)
    assert response.status_code == 201, response.json


@pytest.mark.parametrize("quantity", [150, 200, 201])
def test_short_notice_quantity_uses_owner_review_instead_of_an_arbitrary_cap(
    client, clock, quantity
):
    body = order_payload(quantity=quantity)
    start = clock[0] + timedelta(days=1)
    body["event"].update(
        starts_at=start.isoformat(), ends_at=(start + timedelta(hours=2)).isoformat()
    )
    bind_quote(client, body)
    response = client.post("/api/v1/orders", json=body, headers=HEADERS)
    assert response.status_code == 201, response.json
    assert response.json["data"]["status"] == "pending_review"
