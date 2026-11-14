"""Contract tests for the OpenAPI ``submitOrder``, ``listOrders``, ``retrieveOrder`` and ``updateOrderStatus`` operations.

Requests are shaped like the synthetic ``SubmitOrderRequest`` example in
docs/api/openapi.json, with a far-future event date so the "no past events"
rule never makes the suite time-dependent. The database path is exercised with
a fake PyMySQL connection, so no MySQL server is needed.
"""

import json
import math
import re
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pymysql
import pytest
from app.automation.store import MemoryStore
from app.reports_queries import DEPOSIT_SQL, LINKED_ORDERS_SQL, STATUS_SQL
from test_auth import ORIGIN, invite, sign_in
from test_auth import auth_app as auth_app

OPENAPI_PATH = Path(__file__).resolve().parents[2] / "docs/api/openapi.json"
IDEMPOTENCY_KEY = "test-key-0123456789"
HEADERS = {"Idempotency-Key": IDEMPOTENCY_KEY}
REMOVE = object()


# --------------------------------------------------------------------------- #
# Fixtures and helpers
# --------------------------------------------------------------------------- #


@pytest.fixture
def app(auth_app):
    # Authentication uses its injected test store; orders use their memory store.
    auth_app.config.update(DB_USER="", DB_PASSWORD="")
    return auth_app


@pytest.fixture
def client(app):
    client = app.test_client()
    invite(app)
    sign_in(client, "admin")
    session = client.get("/api/v1/admin/session")
    client.admin_headers = {"Origin": ORIGIN, "X-CSRF-Token": session.json["data"]["csrf_token"]}
    return client


def order_payload(**catering):
    request = {
        "quantity": 50,
        "popsicle_shape": "standard",
        "flavor_requests": "",
        "add_ons": [],
        "service_type": "delivery",
        "dry_ice_blocks": None,
    }
    request.update(catering)
    return {
        "customer": {
            "name": "Example Customer",
            "email": "customer@example.invalid",
            "phone": "+1-202-555-0100",
        },
        "catering_request": request,
        "event": {
            "type": "Example celebration",
            "location": {
                "line1": "100 Example Street",
                "city": "Houston",
                "region": "TX",
                "postal_code": "77000",
                "country_code": "US",
            },
            "starts_at": "2099-01-15T15:00:00-06:00",
            "ends_at": "2099-01-15T17:00:00-06:00",
            "timezone": "America/Chicago",
            "notes": "Synthetic fixture - not a real event.",
        },
        "quote_id": "quote_example_001",
    }


def mutated(path, value):
    """Return a valid payload with the dotted ``path`` replaced (or removed with REMOVE)."""
    payload = order_payload()
    target = payload
    *parents, last = path.split(".")
    for part in parents:
        target = target[part]
    if value is REMOVE:
        del target[last]
    else:
        target[last] = value
    return payload


def post_order(client, payload=None, headers=HEADERS):
    return client.post(
        "/api/v1/orders", json=order_payload() if payload is None else payload, headers=headers
    )


def assert_validation_error(response, field):
    assert response.status_code == 422
    error = response.json["error"]
    assert error["code"] == "validation_error"
    assert error["request_id"] == response.headers["X-Request-ID"]
    assert all(set(item) == {"field", "message"} and item["message"] for item in error["fields"])
    assert field in [item["field"] for item in error["fields"]]


def assert_matches_openapi_order_response(body, schema_name="OrderResponse"):
    jsonschema = pytest.importorskip("jsonschema")
    referencing = pytest.importorskip("referencing")
    spec = json.loads(OPENAPI_PATH.read_text(encoding="utf-8"))
    uri = "urn:popssibilities:contract"
    registry = referencing.Registry().with_resource(
        uri,
        referencing.Resource.from_contents(
            spec, default_specification=referencing.jsonschema.DRAFT202012
        ),
    )
    schema = {"$ref": uri + "#/components/schemas/" + schema_name}
    jsonschema.Draft202012Validator(
        schema, registry=registry, format_checker=jsonschema.FormatChecker()
    ).validate(body)


def cents_values(node):
    """Yield every ``*_cents`` value found anywhere in a JSON document."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key.endswith("_cents"):
                yield value
            yield from cents_values(value)
    elif isinstance(node, list):
        for item in node:
            yield from cents_values(item)


# --------------------------------------------------------------------------- #
# Happy path and envelope
# --------------------------------------------------------------------------- #


def test_valid_order_returns_201_with_data_and_meta_envelope(client):
    response = post_order(client)
    assert response.status_code == 201
    assert set(response.json) == {"data", "meta"}
    data = response.json["data"]
    assert response.json["meta"] == {"request_id": response.headers["X-Request-ID"]}
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Location"] == f"/api/v1/orders/{data['id']}"
    assert re.fullmatch(r"order_[0-9a-f]{32}", data["id"])
    assert data["version"] == 1 and data["status"] == "pending_review"
    assert data["quote_id"] == "quote_example_001"
    assert data["pricing_revision"] == "pricing_config_2.1.0"
    assert data["payment_links"] == []
    assert data["workflow"] == {
        "customer_email": "pending",
        "business_email": "pending",
        "calendar": "not_scheduled",
        "contract_email": "waiting_for_deposit",
    }
    assert data["created_at"] == data["updated_at"]
    assert "admin_notes" not in data


def test_response_matches_the_openapi_order_response_schema(client):
    assert_matches_openapi_order_response(post_order(client).json)


def test_response_echoes_trimmed_customer_catering_and_event(client):
    payload = order_payload()
    payload["customer"]["name"] = "  Example Customer  "
    data = post_order(client, payload).json["data"]
    assert data["customer"]["name"] == "Example Customer"
    assert data["catering_request"] == payload["catering_request"]
    assert data["event"] == payload["event"]


def test_optional_fields_default_to_contract_values(client):
    payload = order_payload()
    for key in ("flavor_requests", "add_ons", "dry_ice_blocks"):
        del payload["catering_request"][key]
    del payload["event"]["ends_at"]
    del payload["event"]["notes"]
    response = post_order(client, payload)
    assert response.status_code == 201
    data = response.json["data"]
    assert data["catering_request"]["flavor_requests"] == ""
    assert data["catering_request"]["add_ons"] == []
    assert data["catering_request"]["dry_ice_blocks"] is None
    assert data["event"]["ends_at"] is None
    assert_matches_openapi_order_response(response.json)


# --------------------------------------------------------------------------- #
# Money: exact, server-calculated, non-negative integer cents
# --------------------------------------------------------------------------- #


def test_every_cents_field_is_a_nonnegative_integer(client):
    payloads = (
        order_payload(),
        order_payload(
            quantity=250, popsicle_shape="heart", dry_ice_blocks=3, service_type="full_service"
        ),
    )
    for index, payload in enumerate(payloads):
        response = post_order(
            client, payload, headers={"Idempotency-Key": f"cents-key-0123456789-{index}"}
        )
        values = list(cents_values(response.json["data"]))
        assert values
        assert all(type(value) is int and value >= 0 for value in values)


def test_line_items_sum_to_total_and_deposit_matches_summary(client):
    data = post_order(client).json["data"]
    pricing = data["pricing"]
    assert pricing["currency"] == "USD"
    # 50 popsicles at $4.50 plus the $25.00 delivery base fee.
    assert {item["code"]: item["amount_cents"] for item in pricing["line_items"]} == {
        "popsicles": 22500,
        "delivery_fee": 2500,
    }
    assert (
        sum(item["amount_cents"] for item in pricing["line_items"])
        == pricing["total_cents"]
        == 25000
    )
    assert pricing["deposit_due_cents"] == 12500
    assert data["deposit"] == {
        "status": "pending",
        "amount_due_cents": 12500,
        "amount_confirmed_cents": 0,
    }


def test_deposit_rounds_up_to_a_whole_cent(client, app):
    # A synthetic $25.01 fee exercises odd-cent rounding with the current rates.
    app.extensions["pricing_rules"] = replace(
        app.extensions["pricing_rules"], delivery_base_cents=2501
    )
    pricing = post_order(client, order_payload(quantity=101)).json["data"]["pricing"]
    assert pricing["total_cents"] == 47951
    assert pricing["deposit_due_cents"] == math.ceil(47951 / 2) == 23976


@pytest.mark.parametrize("shape", ["standard", "heart"])
def test_order_price_equals_the_quote_endpoint_price(client, shape):
    payload = order_payload(
        quantity=120, popsicle_shape=shape, dry_ice_blocks=2, service_type="full_service"
    )
    quote = client.post(
        "/api/v1/quotes",
        json={"catering_request": payload["catering_request"], "event": payload["event"]},
    )
    assert post_order(client, payload).json["data"]["pricing"] == quote.json["data"]["pricing"]


def test_price_revision_preserves_saved_order_and_idempotent_replay(client, app):
    current_rules = app.extensions["pricing_rules"]
    previous_tier = replace(current_rules.tiers[0], unit_price_cents=350)
    app.extensions["pricing_rules"] = replace(
        current_rules, tiers=(previous_tier,), revision="pricing_config_1.1.0"
    )
    payload = order_payload()
    previous = post_order(client, payload).json["data"]
    assert previous["pricing"]["total_cents"] == 20000

    app.extensions["pricing_rules"] = current_rules
    stored = client.get(f"/api/v1/orders/{previous['id']}").json["data"]
    replay = post_order(client, payload).json["data"]
    for order in (stored, replay):
        assert order["pricing"] == previous["pricing"]
        assert order["pricing_revision"] == "pricing_config_1.1.0"
    updated = post_order(
        client, payload, headers={"Idempotency-Key": "new-price-revision-key"}
    ).json["data"]
    assert updated["pricing"]["total_cents"] == 25000
    assert updated["pricing_revision"] == "pricing_config_2.1.0"


@pytest.mark.parametrize("path", ["pricing", "total_cents", "deposit_due_cents", "amount_cents"])
def test_client_supplied_totals_are_rejected(client, path):
    payload = order_payload()
    payload[path] = 1
    assert_validation_error(post_order(client, payload), path)


# --------------------------------------------------------------------------- #
# Validation: 422 validation_error with a fields array
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "path",
    [
        "customer",
        "catering_request",
        "event",
        "quote_id",
        "customer.name",
        "customer.email",
        "customer.phone",
        "catering_request.quantity",
        "catering_request.popsicle_shape",
        "catering_request.service_type",
        "event.type",
        "event.location",
        "event.starts_at",
        "event.timezone",
        "event.location.line1",
        "event.location.city",
        "event.location.region",
        "event.location.postal_code",
        "event.location.country_code",
    ],
)
def test_missing_required_field_is_422(client, path):
    assert_validation_error(post_order(client, mutated(path, REMOVE)), path)


@pytest.mark.parametrize(
    "path,value",
    [
        ("customer.name", ""),
        ("customer.name", "   "),
        ("customer.name", 7),
        ("customer.name", "x" * 151),
        ("customer.email", "not-an-email"),
        ("customer.email", "a@b"),
        ("customer.email", "a b@example.com"),
        ("customer.email", "a@@example.com"),
        ("customer.email", ""),
        ("customer.phone", "call me"),
        ("customer.phone", "12345"),
        ("customer.phone", "1" * 31),
        ("catering_request.quantity", 49),
        ("catering_request.quantity", 100001),
        ("catering_request.quantity", "50"),
        ("catering_request.quantity", 50.5),
        ("catering_request.quantity", True),
        ("catering_request.quantity", None),
        ("catering_request.popsicle_shape", "round"),
        ("catering_request.popsicle_shape", "Heart"),
        ("catering_request.service_type", "pickup"),
        ("catering_request.service_type", "DELIVERY"),
        ("catering_request.dry_ice_blocks", -1),
        ("catering_request.dry_ice_blocks", 1001),
        ("catering_request.dry_ice_blocks", 1.5),
        ("catering_request.dry_ice_blocks", "2"),
        ("catering_request.flavor_requests", 5),
        ("catering_request.flavor_requests", "x" * 2001),
        ("catering_request.add_ons", "ice"),
        ("catering_request.add_ons", ["a", "a"]),
        ("catering_request.add_ons", [str(n) for n in range(21)]),
        ("event.type", ""),
        ("event.location", "Houston"),
        ("event.location.country_code", "us"),
        ("event.location.country_code", "USA"),
        ("event.timezone", "not a zone"),
        ("event.notes", "x" * 2001),
        ("event.starts_at", "tomorrow"),
        ("event.starts_at", "2099-01-15T15:00:00"),
        ("event.starts_at", "2020-01-15T15:00:00-06:00"),
        ("event.ends_at", "2099-01-15T14:00:00-06:00"),
        ("event.ends_at", "2099-01-15T15:00:00-06:00"),
        ("event.ends_at", "2099-01-15T17:00:00"),
        ("quote_id", ""),
        ("quote_id", "bad id!"),
        ("quote_id", "q" * 101),
        ("quote_id", 7),
    ],
)
def test_invalid_field_value_is_422(client, path, value):
    assert_validation_error(post_order(client, mutated(path, value)), path)


def test_blank_add_on_is_reported_by_index(client):
    assert_validation_error(
        post_order(client, mutated("catering_request.add_ons", [""])), "catering_request.add_ons[0]"
    )


def test_unknown_fields_are_rejected_at_every_level(client):
    payload = order_payload()
    payload["unexpected"] = 1
    payload["customer"]["nickname"] = "x"
    payload["catering_request"]["discount"] = 1
    payload["event"]["location"]["floor"] = 2
    response = post_order(client, payload)
    for field in (
        "unexpected",
        "customer.nickname",
        "catering_request.discount",
        "event.location.floor",
    ):
        assert_validation_error(response, field)


def test_all_failures_are_reported_together(client):
    payload = order_payload(quantity=1)
    payload["customer"]["email"] = "bad"
    del payload["quote_id"]
    fields = [item["field"] for item in post_order(client, payload).json["error"]["fields"]]
    assert {"catering_request.quantity", "customer.email", "quote_id"} <= set(fields)


@pytest.mark.parametrize("body", [[], "text", 7, None])
def test_non_object_body_is_422(client, body):
    response = client.post(
        "/api/v1/orders", data=json.dumps(body), content_type="application/json", headers=HEADERS
    )
    assert_validation_error(response, "body")


def test_malformed_json_is_400_bad_request(client):
    response = client.post(
        "/api/v1/orders", data="{", content_type="application/json", headers=HEADERS
    )
    assert response.status_code == 400
    assert response.json["error"]["code"] == "bad_request"
    assert response.json["error"]["fields"] == []


def test_non_json_content_type_is_415(client):
    response = client.post("/api/v1/orders", data="x", content_type="text/plain", headers=HEADERS)
    assert response.status_code == 415
    assert response.json["error"]["code"] == "unsupported_media_type"


def test_a_failed_validation_does_not_store_the_idempotency_key(client):
    assert post_order(client, order_payload(quantity=1)).status_code == 422
    assert post_order(client).status_code == 201


# --------------------------------------------------------------------------- #
# Idempotency
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Idempotency-Key": ""},
        {"Idempotency-Key": "short"},
        {"Idempotency-Key": "has spaces in it!!"},
        {"Idempotency-Key": "k" * 129},
    ],
)
def test_missing_or_malformed_idempotency_key_is_422(client, headers):
    assert_validation_error(post_order(client, headers=headers), "Idempotency-Key")


def test_same_key_and_payload_replays_the_original_order(client):
    first = post_order(client)
    second = post_order(client)
    assert second.status_code == 201
    assert second.json["data"] == first.json["data"]
    assert second.headers["Location"] == first.headers["Location"]


def test_same_key_with_different_payload_is_409_conflict(client):
    post_order(client)
    response = post_order(client, order_payload(quantity=60))
    assert response.status_code == 409
    assert response.json["error"]["code"] == "idempotency_conflict"
    assert response.json["error"]["request_id"] == response.headers["X-Request-ID"]


def test_different_keys_create_different_orders(client):
    first = post_order(client).json["data"]["id"]
    second = post_order(client, headers={"Idempotency-Key": "another-key-0123456789"}).json["data"][
        "id"
    ]
    assert first != second


# --------------------------------------------------------------------------- #
# Database path: parameterized inserts in one atomic transaction
# --------------------------------------------------------------------------- #


class FakeCursor:
    lastrowid = 0

    def __init__(self, connection):
        self.connection = connection
        self.last_sql = ""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=()):
        if self.connection.fail_on and self.connection.fail_on in sql:
            raise pymysql.err.OperationalError(2003, "secret-host.internal refused the connection")
        self.connection.statements.append((sql, params))
        self.last_sql = sql
        if sql.startswith("INSERT"):
            self.connection.row_id += 1
            self.lastrowid = self.connection.row_id

    def executemany(self, sql, rows):
        self.connection.statements.append((sql, list(rows)))

    def fetchone(self):
        if self.last_sql.startswith("SELECT COUNT"):
            return (self.connection.total,)
        return self.connection.existing

    def fetchall(self):
        return self.connection.rows


class FakeConnection:
    def __init__(self, existing=None, fail_on=None, rows=(), total=0):
        self.existing = existing
        self.fail_on = fail_on
        self.rows = rows
        self.total = total
        self.statements = []
        self.row_id = 0
        self.committed = self.rolled_back = self.closed = False

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


@pytest.fixture
def database(app, monkeypatch):
    """Turn on database mode; ``database.connection`` is the connection the next request will use."""
    app.config.update(DB_USER="orders_user", DB_PASSWORD="orders_password")
    state = type("State", (), {"connection": FakeConnection()})()
    monkeypatch.setattr(pymysql, "connect", lambda **options: state.connection)
    return state


def inserts(connection):
    return [(sql, params) for sql, params in connection.statements if sql.startswith("INSERT")]


def test_database_mode_inserts_customer_order_and_items_then_commits(client, database):
    response = post_order(client)
    connection = database.connection
    assert response.status_code == 201
    assert connection.committed and connection.closed and not connection.rolled_back
    tables = [re.match(r"INSERT INTO (\w+)", sql).group(1) for sql, _ in inserts(connection)]
    assert tables == ["customers", "orders", "order_items"]
    orders_sql, orders_params = inserts(connection)[1]
    assert " response_json, request_hash, submission_json)" in orders_sql
    assert orders_params[0] == response.json["data"]["id"]  # public_id, not the BIGINT key
    assert orders_params[1] == 1  # customer_id is the customers row id
    assert orders_params[6:8] == (25000, 12500)
    assert orders_params[8] == datetime(2099, 1, 15, 21, 0)  # naive UTC for DATETIME(6)
    assert orders_params[9] == "America/Chicago"
    assert re.fullmatch(r"[0-9a-f]{64}", orders_params[-2])  # request_hash
    assert json.loads(orders_params[-3]) == json.loads(orders_params[-1]) == response.json["data"]
    _, item_rows = inserts(connection)[2]
    # order_id is the orders BIGINT key (the second insert), never the public id.
    assert item_rows == [
        (2, "popsicles", "50 regular paletas at $4.50 each", 22500),
        (2, "delivery_fee", "Delivery within our standard service area", 2500),
    ]


def test_database_statements_are_parameterized(client, database):
    post_order(client)
    for sql, params in database.connection.statements:
        assert sql.count("%s") == (len(params[0]) if isinstance(params, list) else len(params))
        assert "example.invalid" not in sql and IDEMPOTENCY_KEY not in sql


def test_database_error_rolls_back_and_returns_503_without_leaking_details(client, database):
    database.connection = FakeConnection(fail_on="INSERT INTO orders")
    response = post_order(client)
    connection = database.connection
    assert response.status_code == 503
    assert response.json["error"]["code"] == "service_unavailable"
    assert "secret-host" not in response.get_data(as_text=True)
    assert connection.rolled_back and connection.closed and not connection.committed


def test_connection_failure_returns_503(client, database, monkeypatch):
    def refuse(**options):
        raise pymysql.err.OperationalError(2003, "secret-host.internal refused the connection")

    monkeypatch.setattr(pymysql, "connect", refuse)
    response = post_order(client)
    assert response.status_code == 503
    assert "secret-host" not in response.get_data(as_text=True)


def test_database_replay_returns_the_stored_order_without_new_inserts(client, database):
    first = post_order(client)
    _, params = inserts(database.connection)[1]
    database.connection = FakeConnection(existing=(params[-2], params[-1]))
    second = post_order(client)
    assert second.status_code == 201
    assert second.json["data"] == first.json["data"]
    assert inserts(database.connection) == []
    assert database.connection.statements == [
        (
            "SELECT request_hash, submission_json FROM orders WHERE idempotency_key = %s",
            (IDEMPOTENCY_KEY,),
        )
    ]
    assert database.connection.closed and not database.connection.committed


def test_database_key_reuse_with_a_different_payload_is_409(client, database):
    database.connection = FakeConnection(existing=("0" * 64, json.dumps({"id": "order_other"})))
    response = post_order(client)
    assert response.status_code == 409
    assert response.json["error"]["code"] == "idempotency_conflict"
    assert database.connection.rolled_back and not database.connection.committed
    assert inserts(database.connection) == []


def test_mock_mode_never_opens_a_database_connection(client, monkeypatch):
    def forbidden(**options):
        raise AssertionError("no database credentials are configured")

    monkeypatch.setattr(pymysql, "connect", forbidden)
    assert post_order(client).status_code == 201


# --------------------------------------------------------------------------- #
# retrieveOrder and updateOrderStatus
# --------------------------------------------------------------------------- #


def create_order(client, quantity=50):
    return post_order(client, order_payload(quantity=quantity)).json["data"]


def patch_status(client, order_id, body, **options):
    options.setdefault("headers", client.admin_headers)
    return client.patch(f"/api/v1/orders/{order_id}/status", json=body, **options)


def assert_error(response, status, code):
    assert response.status_code == status
    error = response.json["error"]
    assert error["code"] == code and error["message"]
    assert error["fields"] == [] or code == "validation_error"
    assert error["request_id"] == response.headers["X-Request-ID"]


def test_retrieve_existing_order_returns_200_with_the_stored_fields(client):
    created = create_order(client)
    response = client.get(f"/api/v1/orders/{created['id']}")
    assert response.status_code == 200
    assert set(response.json) == {"data", "meta"}
    assert response.json["meta"] == {"request_id": response.headers["X-Request-ID"]}
    assert response.headers["Cache-Control"] == "no-store"
    data = response.json["data"]
    assert data == {**created, "admin_notes": ""}
    assert (
        data["id"] == created["id"] and data["status"] == "pending_review" and data["version"] == 1
    )
    assert data["pricing"]["total_cents"] == 25000 and data["deposit"]["amount_due_cents"] == 12500
    assert_matches_openapi_order_response(response.json, "AdminOrderResponse")


@pytest.mark.parametrize("order_id", ["order_" + "0" * 32, "missing", "bad id!", "x" * 101])
def test_retrieve_missing_order_returns_404_not_found(client, order_id):
    create_order(client)
    assert_error(client.get(f"/api/v1/orders/{order_id}"), 404, "not_found")


def test_status_update_returns_the_updated_admin_order(client):
    created = create_order(client)
    response = patch_status(
        client, created["id"], {"version": 1, "status": "confirmed", "reason": "Accepted."}
    )
    assert response.status_code == 200
    assert response.json["meta"] == {"request_id": response.headers["X-Request-ID"]}
    data = response.json["data"]
    assert data["status"] == "confirmed" and data["version"] == 2
    assert (
        data["updated_at"] >= created["updated_at"] and data["created_at"] == created["created_at"]
    )
    assert_matches_openapi_order_response(response.json, "AdminOrderResponse")
    unchanged = {
        key: value for key, value in data.items() if key not in ("status", "version", "updated_at")
    }
    assert unchanged == {
        key: value
        for key, value in created.items()
        if key not in ("status", "version", "updated_at")
    } | {"admin_notes": ""}


def test_status_update_is_visible_to_later_retrieval(client):
    order_id = create_order(client)["id"]
    patch_status(client, order_id, {"version": 1, "status": "cancelled"})
    data = client.get(f"/api/v1/orders/{order_id}").json["data"]
    assert data["status"] == "cancelled" and data["version"] == 2


@pytest.mark.parametrize(
    "path",
    [
        ["confirmed", "fulfilled"],
        ["confirmed", "cancelled"],
        ["cancelled"],
    ],
)
def test_valid_transition_chains_increment_the_version_each_time(client, path):
    order_id = create_order(client)["id"]
    for version, status in enumerate(path, start=1):
        response = patch_status(client, order_id, {"version": version, "status": status})
        assert response.status_code == 200
        assert response.json["data"]["status"] == status
        assert response.json["data"]["version"] == version + 1


def test_status_update_never_changes_money_fields(client):
    created = create_order(client, quantity=101)
    data = patch_status(client, created["id"], {"version": 1, "status": "confirmed"}).json["data"]
    assert data["pricing"] == created["pricing"] and data["deposit"] == created["deposit"]
    values = list(cents_values(data))
    assert 47950 in values and all(type(value) is int and value >= 0 for value in values)


def test_same_status_is_a_noop_after_a_valid_version_check(client):
    created = create_order(client)
    response = patch_status(client, created["id"], {"version": 1, "status": "pending_review"})
    assert response.status_code == 200
    assert response.json["data"]["version"] == 1
    assert response.json["data"]["updated_at"] == created["updated_at"]
    assert_error(
        patch_status(client, created["id"], {"version": 2, "status": "pending_review"}),
        409,
        "stale_version",
    )


def test_status_update_does_not_alter_the_idempotent_post_replay(client):
    created = create_order(client)
    patch_status(client, created["id"], {"version": 1, "status": "confirmed"})
    assert post_order(client).json["data"] == created


@pytest.mark.parametrize("terminal", ["fulfilled", "cancelled"])
@pytest.mark.parametrize("target", ["pending_review", "confirmed", "fulfilled", "cancelled"])
def test_terminal_orders_only_accept_their_own_status(client, terminal, target):
    order_id = create_order(client)["id"]
    patch_status(client, order_id, {"version": 1, "status": "confirmed"})
    patch_status(client, order_id, {"version": 2, "status": terminal})
    response = patch_status(client, order_id, {"version": 3, "status": target})
    if target == terminal:
        assert response.status_code == 200 and response.json["data"]["version"] == 3
    else:
        assert_error(response, 409, "invalid_transition")
        assert client.get(f"/api/v1/orders/{order_id}").json["data"]["status"] == terminal


@pytest.mark.parametrize(
    "current,target",
    [
        ("pending_review", "fulfilled"),
        ("confirmed", "pending_review"),
    ],
)
def test_other_illegal_transitions_are_409_invalid_transition(client, current, target):
    order_id = create_order(client)["id"]
    if current == "confirmed":
        patch_status(client, order_id, {"version": 1, "status": "confirmed"})
    version = 2 if current == "confirmed" else 1
    assert_error(
        patch_status(client, order_id, {"version": version, "status": target}),
        409,
        "invalid_transition",
    )


def test_stale_version_is_409_stale_version_and_changes_nothing(client):
    order_id = create_order(client)["id"]
    for version in (0, 2):
        response = patch_status(client, order_id, {"version": version, "status": "confirmed"})
        if version == 0:
            assert_validation_error(response, "version")
        else:
            assert_error(response, 409, "stale_version")
    assert client.get(f"/api/v1/orders/{order_id}").json["data"]["status"] == "pending_review"


def test_stale_version_is_checked_before_the_transition_rule(client):
    order_id = create_order(client)["id"]
    assert_error(
        patch_status(client, order_id, {"version": 5, "status": "fulfilled"}), 409, "stale_version"
    )


@pytest.mark.parametrize(
    "status", ["submitted", "in_preparation", "completed", "Confirmed", "", 7, None, ["confirmed"]]
)
def test_invalid_status_value_is_422_validation_error(client, status):
    order_id = create_order(client)["id"]
    assert_validation_error(
        patch_status(client, order_id, {"version": 1, "status": status}), "status"
    )


@pytest.mark.parametrize(
    "body,field",
    [
        ({"status": "confirmed"}, "version"),
        ({"version": 1}, "status"),
        ({"version": "1", "status": "confirmed"}, "version"),
        ({"version": 1.5, "status": "confirmed"}, "version"),
        ({"version": True, "status": "confirmed"}, "version"),
        ({"version": 1, "status": "confirmed", "reason": 5}, "reason"),
        ({"version": 1, "status": "confirmed", "reason": "r" * 501}, "reason"),
        ({"version": 1, "status": "confirmed", "total_cents": 1}, "total_cents"),
    ],
)
def test_invalid_status_body_is_422_validation_error(client, body, field):
    order_id = create_order(client)["id"]
    assert_validation_error(patch_status(client, order_id, body), field)


@pytest.mark.parametrize("body", [[], "text", 7, None])
def test_non_object_status_body_is_422(client, body):
    response = client.patch(
        "/api/v1/orders/order_x/status",
        data=json.dumps(body),
        content_type="application/json",
        headers=client.admin_headers,
    )
    assert_validation_error(response, "body")


def test_status_update_of_a_missing_order_is_404(client):
    assert_error(
        patch_status(client, "order_missing", {"version": 1, "status": "confirmed"}),
        404,
        "not_found",
    )


def test_status_update_with_malformed_json_is_400(client):
    response = client.patch(
        "/api/v1/orders/order_x/status",
        data="{",
        content_type="application/json",
        headers=client.admin_headers,
    )
    assert_error(response, 400, "bad_request")


def test_status_update_with_non_json_content_type_is_415(client):
    response = client.patch(
        "/api/v1/orders/order_x/status",
        data="x",
        content_type="text/plain",
        headers=client.admin_headers,
    )
    assert_error(response, 415, "unsupported_media_type")


def test_status_route_rejects_other_methods(client):
    assert_error(client.post("/api/v1/orders/order_x/status", json={}), 405, "method_not_allowed")


# --------------------------------------------------------------------------- #
# retrieveOrder and updateOrderStatus: database path
# --------------------------------------------------------------------------- #


def stored_row(client, database):
    """Create an order in database mode and return the ``(response_json,)`` row it stored."""
    post_order(client)
    params = inserts(database.connection)[1][1]
    return (params[-3],)


def test_database_retrieve_reads_the_order_by_public_id(client, database):
    row = stored_row(client, database)
    order_id = json.loads(row[0])["id"]
    database.connection = FakeConnection(existing=row)
    response = client.get(f"/api/v1/orders/{order_id}")
    connection = database.connection
    assert response.status_code == 200
    assert response.json["data"] == {**json.loads(row[0]), "admin_notes": ""}
    assert connection.statements == [
        ("SELECT response_json FROM orders WHERE public_id = %s", (order_id,))
    ]
    assert connection.closed


def test_database_retrieve_of_a_missing_order_is_404(client, database):
    database.connection = FakeConnection(existing=None)
    assert_error(client.get("/api/v1/orders/order_missing"), 404, "not_found")
    assert database.connection.closed


def test_database_status_update_locks_the_row_then_updates_in_one_transaction(client, database):
    row = stored_row(client, database)
    order = json.loads(row[0])
    database.connection = FakeConnection(existing=row)
    response = patch_status(client, order["id"], {"version": 1, "status": "confirmed"})
    connection = database.connection
    assert response.status_code == 200
    assert response.json["data"]["status"] == "confirmed" and response.json["data"]["version"] == 2
    assert connection.committed and connection.closed and not connection.rolled_back
    (select_sql, select_params), (update_sql, update_params) = connection.statements
    assert select_sql.endswith("FOR UPDATE") and select_params == (order["id"],)
    assert (
        update_sql.startswith("UPDATE orders SET")
        and update_sql.count("%s") == len(update_params) == 4
    )
    assert update_params[:2] == ("confirmed", 2) and update_params[3] == order["id"]
    assert json.loads(update_params[2]) == response.json["data"]


def test_database_noop_status_update_writes_nothing(client, database):
    row = stored_row(client, database)
    database.connection = FakeConnection(existing=row)
    response = patch_status(
        client, json.loads(row[0])["id"], {"version": 1, "status": "pending_review"}
    )
    assert response.status_code == 200 and response.json["data"]["version"] == 1
    assert len(database.connection.statements) == 1 and database.connection.committed


@pytest.mark.parametrize(
    "body,status,code",
    [
        ({"version": 2, "status": "confirmed"}, 409, "stale_version"),
        ({"version": 1, "status": "fulfilled"}, 409, "invalid_transition"),
    ],
)
def test_database_conflicts_roll_back_without_writing(client, database, body, status, code):
    row = stored_row(client, database)
    database.connection = FakeConnection(existing=row)
    assert_error(patch_status(client, json.loads(row[0])["id"], body), status, code)
    connection = database.connection
    assert connection.rolled_back and connection.closed and not connection.committed
    assert not any(sql.startswith("UPDATE") for sql, _ in connection.statements)


def test_database_status_update_of_a_missing_order_is_404(client, database):
    database.connection = FakeConnection(existing=None)
    assert_error(
        patch_status(client, "order_missing", {"version": 1, "status": "confirmed"}),
        404,
        "not_found",
    )
    assert database.connection.rolled_back and database.connection.closed


def test_database_failures_on_new_routes_return_503_without_leaking_details(client, database):
    row = stored_row(client, database)
    order_id = json.loads(row[0])["id"]
    database.connection = FakeConnection(existing=row, fail_on="SELECT")
    response = client.get(f"/api/v1/orders/{order_id}")
    assert response.status_code == 503 and "secret-host" not in response.get_data(as_text=True)
    database.connection = FakeConnection(existing=row, fail_on="UPDATE orders")
    response = patch_status(client, order_id, {"version": 1, "status": "confirmed"})
    assert_error(response, 503, "service_unavailable")
    assert "secret-host" not in response.get_data(as_text=True)
    assert database.connection.rolled_back and not database.connection.committed


# --------------------------------------------------------------------------- #
# listOrders
# --------------------------------------------------------------------------- #


def create_order_at(client, starts_at, key):
    payload = order_payload()
    payload["event"]["starts_at"] = starts_at
    del payload["event"]["ends_at"]
    return post_order(client, payload, headers={"Idempotency-Key": key}).json["data"]


@pytest.fixture
def three_orders(client):
    """Orders whose events start on 2099-01-10, 2099-01-15 and 2099-01-20 (UTC), oldest first."""
    return [
        create_order_at(client, f"2099-01-{day}T12:00:00+00:00", f"list-key-0123456789-{day}")
        for day in ("10", "15", "20")
    ]


def list_orders(client, **query):
    return client.get("/api/v1/orders", query_string=query)


def test_list_with_no_orders_returns_an_empty_page_envelope(client):
    response = list_orders(client)
    assert response.status_code == 200
    assert set(response.json) == {"data", "meta"}
    assert response.json["data"] == {"items": [], "page": 1, "page_size": 25, "total": 0}
    assert response.json["meta"] == {"request_id": response.headers["X-Request-ID"]}
    assert response.headers["Cache-Control"] == "no-store"


def test_default_list_is_newest_first_with_admin_orders(client, three_orders):
    response = list_orders(client)
    assert response.status_code == 200
    data = response.json["data"]
    assert (data["page"], data["page_size"], data["total"]) == (1, 25, 3)
    assert [item["id"] for item in data["items"]] == [
        order["id"] for order in reversed(three_orders)
    ]
    assert all(item["admin_notes"] == "" for item in data["items"])
    assert data["items"][2] == {**three_orders[0], "admin_notes": ""}
    assert_matches_openapi_order_response(response.json, "ListOrdersResponse")


def test_list_reflects_status_changes(client, three_orders):
    patch_status(client, three_orders[1]["id"], {"version": 1, "status": "confirmed"})
    items = list_orders(client).json["data"]["items"]
    assert [item["status"] for item in items] == ["pending_review", "confirmed", "pending_review"]


def test_status_filter_returns_only_that_status(client, three_orders):
    patch_status(client, three_orders[0]["id"], {"version": 1, "status": "confirmed"})
    patch_status(client, three_orders[2]["id"], {"version": 1, "status": "cancelled"})
    for status, expected in (
        ("confirmed", [0]),
        ("cancelled", [2]),
        ("pending_review", [1]),
        ("fulfilled", []),
    ):
        data = list_orders(client, status=status).json["data"]
        assert [item["id"] for item in data["items"]] == [
            three_orders[index]["id"] for index in expected
        ]
        assert data["total"] == len(expected)


def test_event_window_is_inclusive_from_and_exclusive_to(client, three_orders):
    def ids(**query):
        return [item["id"] for item in list_orders(client, **query).json["data"]["items"]]

    middle, last = three_orders[1]["id"], three_orders[2]["id"]
    assert ids(event_from="2099-01-15T12:00:00+00:00") == [last, middle]
    assert ids(event_to="2099-01-15T12:00:00+00:00") == [three_orders[0]["id"]]
    assert ids(event_from="2099-01-15T12:00:00Z", event_to="2099-01-20T12:00:00Z") == [middle]
    assert ids(event_from="2099-01-21T00:00:00Z") == []


def test_event_window_compares_instants_across_offsets(client, three_orders):
    # 06:00-06:00 on the 15th is 12:00 UTC, the exact start of the middle order.
    data = list_orders(
        client, event_from="2099-01-15T06:00:00-06:00", event_to="2099-01-15T07:00:00-06:00"
    ).json["data"]
    assert [item["id"] for item in data["items"]] == [three_orders[1]["id"]]


def test_status_and_window_filters_combine(client, three_orders):
    patch_status(client, three_orders[2]["id"], {"version": 1, "status": "confirmed"})
    data = list_orders(client, status="pending_review", event_from="2099-01-12T00:00:00Z").json[
        "data"
    ]
    assert [item["id"] for item in data["items"]] == [three_orders[1]["id"]]
    assert data["total"] == 1


def link_booking(app, order_id, status, payment_status):
    """Import an order: save an in-memory booking and the link the owner workflow creates."""
    store = app.extensions.setdefault("automation_store", MemoryStore())
    with store.transaction() as tx:
        booking_id = "booking_" + order_id
        tx.save_booking({"id": booking_id, "status": status, "payment_status": payment_status})
        tx.save_order_link({"order_id": order_id, "booking_id": booking_id})


@pytest.mark.parametrize(
    "booking_status,payment_status,order_status,deposit_status",
    [
        ("requested", "unpaid", "pending_review", "pending"),
        ("owner_review", "partial", "pending_review", "pending"),
        ("awaiting_deposit", "unpaid", "pending_review", "pending"),
        ("confirmed", "deposit_paid", "confirmed", "confirmed"),
        ("confirmed", "paid", "confirmed", "confirmed"),
        ("cancelled", "unpaid", "cancelled", "pending"),
    ],
)
def test_list_maps_booking_status_and_payment_for_imported_orders(
    app, client, three_orders, booking_status, payment_status, order_status, deposit_status
):
    order = three_orders[0]
    link_booking(app, order["id"], booking_status, payment_status)
    item = list_orders(client).json["data"]["items"][2]
    assert item["id"] == order["id"]
    assert (item["status"], item["deposit"]["status"]) == (order_status, deposit_status)
    assert item["pricing"] == order["pricing"]


@pytest.fixture
def mixed_orders(app, client):
    """Oldest first: three imported orders, one unimported fulfilled order, one more imported."""
    created = [
        create_order_at(client, "2099-02-01T12:00:00+00:00", f"mixed-key-0123456789-{n}")
        for n in range(5)
    ]
    a, b, c, d, e = (order["id"] for order in created)
    link_booking(app, a, "confirmed", "paid")
    link_booking(app, b, "owner_review", "partial")
    link_booking(app, c, "cancelled", "unpaid")
    patch_status(client, d, {"version": 1, "status": "confirmed"})
    patch_status(client, d, {"version": 2, "status": "fulfilled"})
    link_booking(app, e, "requested", "unpaid")
    return a, b, c, d, e


def test_unimported_orders_keep_their_own_status_and_deposit(client, mixed_orders):
    items = {item["id"]: item for item in list_orders(client).json["data"]["items"]}
    unimported = items[mixed_orders[3]]
    assert (unimported["status"], unimported["deposit"]["status"]) == ("fulfilled", "pending")


def test_status_filter_and_total_use_the_booking_status(client, mixed_orders):
    a, b, c, d, e = mixed_orders
    for status, expected in (
        ("confirmed", [a]),
        ("pending_review", [e, b]),
        ("cancelled", [c]),
        ("fulfilled", [d]),
    ):
        data = list_orders(client, status=status).json["data"]
        assert [item["id"] for item in data["items"]] == expected
        assert data["total"] == len(expected)
        assert {item["status"] for item in data["items"]} == {status}


def test_pagination_counts_the_booking_status(client, mixed_orders):
    a, b, c, d, e = mixed_orders
    pages = [
        list_orders(client, status="pending_review", page=number, page_size=1).json["data"]
        for number in (1, 2, 3)
    ]
    assert [[item["id"] for item in page["items"]] for page in pages] == [[e], [b], []]
    assert all(page["total"] == 2 for page in pages)
    everything = list_orders(client, page_size=2, page=2).json["data"]
    assert [item["id"] for item in everything["items"]] == [c, b]
    assert everything["total"] == 5


def test_pagination_slices_the_list_and_reports_the_total(client):
    created = [
        create_order_at(client, "2099-02-01T12:00:00+00:00", f"page-key-0123456789-{n}")["id"]
        for n in range(5)
    ]
    newest_first = list(reversed(created))
    pages = [list_orders(client, page=number, page_size=2).json["data"] for number in (1, 2, 3, 4)]
    assert [[item["id"] for item in page["items"]] for page in pages] == [
        newest_first[0:2],
        newest_first[2:4],
        newest_first[4:],
        [],
    ]
    assert all(page["total"] == 5 and page["page_size"] == 2 for page in pages)
    assert [page["page"] for page in pages] == [1, 2, 3, 4]


@pytest.mark.parametrize(
    "query,field",
    [
        ({"page": "0"}, "page"),
        ({"page": "-1"}, "page"),
        ({"page": "abc"}, "page"),
        ({"page": ""}, "page"),
        ({"page": "1.5"}, "page"),
        ({"page": "99999999999"}, "page"),
        ({"page_size": "0"}, "page_size"),
        ({"page_size": "101"}, "page_size"),
        ({"page_size": "-5"}, "page_size"),
        ({"page_size": "ten"}, "page_size"),
        ({"status": "submitted"}, "status"),
        ({"status": "Confirmed"}, "status"),
        ({"status": ""}, "status"),
        ({"event_from": "tomorrow"}, "event_from"),
        ({"event_from": "2099-01-15T12:00:00"}, "event_from"),
        ({"event_from": ""}, "event_from"),
        ({"event_from": "0001-01-01T00:00:00+14:00"}, "event_from"),
        ({"event_to": "not a date"}, "event_to"),
        ({"event_to": "2099-01-15"}, "event_to"),
        ({"event_from": "2099-01-15T12:00:00Z", "event_to": "2099-01-15T12:00:00Z"}, "event_to"),
        ({"event_from": "2099-01-15T12:00:00Z", "event_to": "2099-01-15T11:59:59Z"}, "event_to"),
    ],
)
def test_invalid_list_query_is_422(client, query, field):
    assert_validation_error(list_orders(client, **query), field)


def test_page_size_bounds_are_accepted(client):
    for page_size in (1, 100):
        assert list_orders(client, page_size=page_size).json["data"]["page_size"] == page_size


def test_all_list_query_failures_are_reported_together(client):
    fields = [
        item["field"]
        for item in list_orders(client, page="0", page_size="500", status="x").json["error"][
            "fields"
        ]
    ]
    assert {"page", "page_size", "status"} <= set(fields)


def test_list_requires_an_admin_session(app):
    response = app.test_client().get("/api/v1/orders")
    assert response.status_code == 401
    assert "items" not in response.get_data(as_text=True)


def test_list_route_rejects_other_methods(client):
    assert_error(client.delete("/api/v1/orders"), 405, "method_not_allowed")


# --------------------------------------------------------------------------- #
# listOrders: database path
# --------------------------------------------------------------------------- #


def stored_orders(client, database, count=2):
    """Create orders in database mode; return their ``(response_json,)`` rows, newest first."""
    rows = []
    for number in range(count):
        post_order(client, headers={"Idempotency-Key": f"db-list-key-0123456789-{number}"})
        rows.append((inserts(database.connection)[1][1][-3],))
        database.connection = FakeConnection()
    return rows[::-1]


def list_rows(stored, status="pending_review", deposit="pending", booking=None):
    """Tuple-cursor rows including the linked booking's verified payment amounts."""
    booking_json = json.dumps(booking) if booking is not None else None
    return [(body, status, deposit, booking_json) for (body,) in stored]


def test_database_list_counts_then_selects_newest_first_with_limit_and_offset(client, database):
    rows = list_rows(stored_orders(client, database))
    database.connection = FakeConnection(rows=rows, total=7)
    response = list_orders(client, page=2, page_size=2)
    connection = database.connection
    assert response.status_code == 200
    data = response.json["data"]
    assert (data["page"], data["page_size"], data["total"]) == (2, 2, 7)
    assert data["items"] == [{**json.loads(row[0]), "admin_notes": ""} for row in rows]
    assert connection.statements == [
        ("SELECT COUNT(*)" + LINKED_ORDERS_SQL, ()),
        (
            "SELECT o.response_json, "
            + STATUS_SQL
            + ", "
            + DEPOSIT_SQL
            + ", b.data"
            + LINKED_ORDERS_SQL
            + " ORDER BY o.id DESC LIMIT %s OFFSET %s",
            (2, 2),
        ),
    ]
    assert connection.closed and not connection.committed


def test_database_list_reports_the_effective_status_and_deposit_status(client, database):
    rows = list_rows(
        stored_orders(client, database, count=1),
        "confirmed",
        "confirmed",
        {"deposit_minor": 12500, "paid_minor": 12500},
    )
    database.connection = FakeConnection(rows=rows, total=1)
    item = list_orders(client).json["data"]["items"][0]
    stored = json.loads(rows[0][0])
    assert stored["status"] == "pending_review" and stored["deposit"]["status"] == "pending"
    assert item["status"] == "confirmed"
    assert item["deposit"] == {
        **stored["deposit"],
        "status": "confirmed",
        "amount_confirmed_cents": 12500,
    }
    assert {key: item[key] for key in item if key not in ("status", "deposit")} == {
        **{key: stored[key] for key in stored if key not in ("status", "deposit")},
        "admin_notes": "",
    }


def test_database_list_filters_are_parameterized_naive_utc_values(client, database):
    database.connection = FakeConnection(total=0)
    response = list_orders(
        client,
        status="confirmed",
        event_from="2099-01-15T06:00:00-06:00",
        event_to="2099-01-20T12:00:00Z",
    )
    assert response.status_code == 200
    assert response.json["data"] == {"items": [], "page": 1, "page_size": 25, "total": 0}
    where = (
        " WHERE (" + STATUS_SQL + ") = %s AND o.event_starts_at >= %s AND o.event_starts_at < %s"
    )
    params = ("confirmed", datetime(2099, 1, 15, 12, 0), datetime(2099, 1, 20, 12, 0))
    assert database.connection.statements == [
        ("SELECT COUNT(*)" + LINKED_ORDERS_SQL + where, params),
        (
            "SELECT o.response_json, "
            + STATUS_SQL
            + ", "
            + DEPOSIT_SQL
            + ", b.data"
            + LINKED_ORDERS_SQL
            + where
            + " ORDER BY o.id DESC LIMIT %s OFFSET %s",
            params + (25, 0),
        ),
    ]
    for sql, values in database.connection.statements:
        # The status mapping itself names statuses; the caller's value must still be a parameter.
        own_sql = sql.replace(STATUS_SQL, "").replace(DEPOSIT_SQL, "")
        assert sql.count("%s") == len(values) and "confirmed" not in own_sql


def test_database_list_does_not_query_when_the_request_is_invalid(client, database):
    assert list_orders(client, page="0").status_code == 422
    assert database.connection.statements == []


def test_database_list_failure_returns_503_without_leaking_details(client, database):
    database.connection = FakeConnection(fail_on="SELECT COUNT")
    response = list_orders(client)
    assert_error(response, 503, "service_unavailable")
    assert "secret-host" not in response.get_data(as_text=True)
    assert database.connection.closed
