"""Submission receipts persist before delivery and do not depend on owner routing."""

from unittest.mock import Mock

import pymysql
import pytest
from app import database, orders
from app.automation.delivery import RetryLater
from app.automation.runtime import build_services
from app.automation.store import MemoryStore, MemoryTransaction, Store, StoreUnavailable
from app.email.provider import MailFailure
from test_auth import auth_app as auth_app
from test_automation_store import sql_settings as sql_settings
from test_orders import HEADERS, bind_quote, order_payload, post_order


@pytest.fixture
def receipt_app(auth_app):
    auth_app.config.update(
        DB_USER="",
        DB_PASSWORD="",
        AUTOMATION_ENABLED=True,
        AUTOMATION_MODE="local",
        AUTOMATION_RETRY_BASE_SECONDS=2,
        AUTOMATION_CLOCK=lambda: auth_app.test_clock["now"],
    )
    store = MemoryStore()
    auth_app.extensions["automation_store"] = store
    auth_app.extensions.update(
        build_services(auth_app.config, store, auth_app.extensions["orders_memory"])
    )
    return auth_app


def deliver(app):
    app.extensions["dispatcher"].dispatch()
    queue = app.extensions["queue"]
    for message in queue.messages[:]:
        app.extensions["processor"].process(message["body"])
    queue.messages.clear()


@pytest.mark.parametrize("starts_at", ["2099-01-15T15:00:00-06:00", "2099-01-15T21:00:00Z"])
def test_new_request_sends_customer_receipt_without_google_or_owner_routing(receipt_app, starts_at):
    app = receipt_app
    body = order_payload()
    body["event"]["starts_at"] = starts_at
    result = post_order(app.test_client(), body)
    assert result.status_code == 201
    order = result.json["data"]
    assert app.extensions["mail"].messages == []  # No network side effects in HTTP submit.
    deliver(app)
    (message,) = app.extensions["mail"].messages
    assert message["recipient"] == order["customer"]["email"]
    assert message["subject"] == "Catering Request Received"
    for expected in (
        order["id"],
        order["customer"]["name"],
        order["event"]["location"]["line1"],
        "January 15, 2099 at 03:00 PM",
        "America/Chicago",
        "Delivery",
        "50",
        "awaiting review",
        "not confirmed yet",
        "No payment is due",
        "deposit payment link",
    ):
        assert expected in message["body"]
    assert "/admin/" not in message["body"]
    with app.extensions["automation_store"].transaction() as tx:
        assert tx.list_bookings() == tx.list_requests() == []
        (job,) = tx.list_outbox()
        assert tx.get_delivery(job["key"])["status"] == "sent"
    assert app.extensions["orders_memory"]["by_id"][order["id"]]["status"] == "pending_review"


def test_submission_replay_and_queue_redelivery_send_one_receipt(receipt_app):
    app, body = receipt_app, order_payload(service_type="full_service", quantity=100)
    client = app.test_client()
    first = post_order(client, body)
    assert post_order(client, body).json["data"] == first.json["data"]
    deliver(app)
    with app.extensions["automation_store"].transaction() as tx:
        (job,) = tx.list_outbox()
    app.extensions["processor"].process({"job_key": job["key"]})
    deliver(app)
    (message,) = app.extensions["mail"].messages
    assert "Full service" in message["body"] and "100" in message["body"]
    assert (
        post_order(client, body, headers={"Idempotency-Key": "another-request-key-001"}).status_code
        == 409
    )


def test_quotes_invalid_requests_and_historical_orders_do_not_send_receipts(receipt_app):
    app, body = receipt_app, order_payload()
    client = app.test_client()
    bind_quote(client, body)
    assert client.post("/api/v1/orders", json=body).status_code == 422
    with app.extensions["automation_store"].transaction() as tx:
        assert tx.list_outbox() == []
    app.config["AUTOMATION_ENABLED"] = False
    old = client.post("/api/v1/orders", json=body, headers=HEADERS)
    assert old.status_code == 201
    app.config["AUTOMATION_ENABLED"] = True
    assert (
        client.post("/api/v1/orders", json=body, headers=HEADERS).json["data"] == old.json["data"]
    )
    deliver(app)
    assert app.extensions["mail"].messages == []


def test_uncertain_receipt_delivery_survives_worker_restart_with_same_resend_key(receipt_app):
    app = receipt_app
    app.config["EMAIL_PROVIDER"] = "resend"
    mail = app.config["AUTOMATION_MAIL"] = Mock()
    mail.send.side_effect = [MailFailure("uncertain", "resend_delivery_uncertain"), "accepted-id"]
    store = app.extensions["automation_store"]
    post_order(app.test_client())
    with store.transaction() as tx:
        (job,) = tx.list_outbox()
    first_worker = build_services(app.config, store)["processor"]
    with pytest.raises(RetryLater):
        first_worker.process({"job_key": job["key"]})
    app.test_clock["now"] += 3
    restarted = build_services(app.config, store)["processor"]
    restarted.process({"job_key": job["key"]})
    restarted.process({"job_key": job["key"]})
    assert mail.send.call_count == 2
    assert mail.send.call_args_list[0] == mail.send.call_args_list[1]
    assert mail.send.call_args.args[-1].endswith(":0")
    with store.transaction() as tx:
        assert tx.get_delivery(job["key"])["provider_id"] == "accepted-id"


def test_failed_memory_receipt_intent_does_not_consume_quote_or_save_order(
    receipt_app, monkeypatch
):
    app, body = receipt_app, order_payload()
    client = app.test_client()
    bind_quote(client, body)
    with monkeypatch.context() as patch:
        patch.setattr(MemoryTransaction, "enqueue", Mock(side_effect=StoreUnavailable("Synthetic")))
        assert client.post("/api/v1/orders", json=body, headers=HEADERS).status_code == 503
    assert app.extensions["orders_memory"]["by_id"] == {}
    assert not app.extensions["quotes_memory"]["quotes"][body["quote_id"]]["is_used"]
    assert client.post("/api/v1/orders", json=body, headers=HEADERS).status_code == 201


@pytest.mark.database
def test_sql_order_and_receipt_commit_together_and_replay_after_restart(
    receipt_app, sql_settings, monkeypatch
):
    app = receipt_app
    app.config.update(sql_settings)
    app.extensions["automation_store"] = Store(app.config)
    client, body = app.test_client(), order_payload()
    try:
        bind_quote(client, body)
        enqueue = orders._queue_customer_receipt

        def fail_after_enqueue(*args):
            enqueue(*args)
            raise pymysql.OperationalError(2003, "Synthetic failure after receipt insert")

        with monkeypatch.context() as patch:
            patch.setattr(orders, "_queue_customer_receipt", fail_after_enqueue)
            assert client.post("/api/v1/orders", json=body, headers=HEADERS).status_code == 503
        with database.connect(app.config) as connection, connection.cursor() as cursor:
            for table in ("orders", "customers", "automation_outbox"):
                cursor.execute("SELECT COUNT(*) AS count FROM " + table)
                assert cursor.fetchone()["count"] == 0
            cursor.execute("SELECT is_used FROM quotes WHERE id=%s", (body["quote_id"],))
            assert not cursor.fetchone()["is_used"]
        result = client.post("/api/v1/orders", json=body, headers=HEADERS)
        assert result.status_code == 201
        assert (
            client.post("/api/v1/orders", json=body, headers=HEADERS).json["data"]
            == result.json["data"]
        )
        app.extensions.update(build_services(app.config, Store(app.config)))
        deliver(app)
        (message,) = app.extensions["mail"].messages
        assert message["subject"] == "Catering Request Received"
        assert message["recipient"] == body["customer"]["email"]
        with Store(app.config).transaction() as tx:
            (job,) = tx.list_outbox()
            assert tx.get_delivery(job["key"])["status"] == "sent"
    finally:
        with database.connect(app.config) as connection, connection.cursor() as cursor:
            for table in (
                "customer_order_accounts",
                "customer_quote_accounts",
                "order_items",
                "orders",
                "customers",
                "quotes",
            ):
                cursor.execute("DELETE FROM " + table)
            connection.commit()
