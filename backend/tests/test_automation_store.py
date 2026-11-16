"""Transactional adapter parity, including optional disposable MySQL checks."""

import hashlib
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from uuid import uuid4

import pymysql
import pytest
from app import database
from app.automation.store import MemoryStore, Store, StoreUnavailable
from app.migrations import MIGRATIONS, apply_migrations, checksum, statements


def test_booking_migration_is_resumable_and_has_payment_uniqueness():
    commands = statements(MIGRATIONS / "0007_booking_automation.sql")
    assert len(commands) == 8
    assert "reference VARCHAR(190)" in commands[2]
    assert "ON DELETE RESTRICT" in commands[2]


def test_existing_email_branch_migration_history_is_preserved():
    originals = {
        "0005_admin_recovery.sql": "4882d97e827fa29665a44a67d3e4a7fcab61c7e5b8481f3fe0ac4b2c9dda0683",
        "0006_customer_test_email.sql": "034952129eb2f1d6f0602325dca57b98e2d741cc4f5570c1d5b0dc9de4e53f11",
    }
    for name, expected in originals.items():
        assert checksum(MIGRATIONS / name) == expected
    assert (MIGRATIONS / "0007_booking_automation.sql").exists()
    assert not (MIGRATIONS / "0005_booking_automation.sql").exists()
    quote_migration = MIGRATIONS / "0011_quotes_persistence.sql"
    assert quote_migration.exists()
    assert "CREATE TABLE IF NOT EXISTS quotes" in quote_migration.read_text(encoding="utf-8")
    assert statements(quote_migration)  # resumable for the shared migration runner


def test_memory_transactions_rollback_all_changes_and_copy_reads():
    store = MemoryStore()
    with store.transaction() as tx:
        tx.save_booking({"id": "booking", "status": "requested"})
    with pytest.raises(RuntimeError):
        with store.transaction() as tx:
            booking = tx.get_booking("booking")
            booking["status"] = "confirmed"
            tx.save_booking(booking)
            tx.audit("must.rollback")
            raise RuntimeError("fail")
    with store.transaction() as tx:
        assert tx.get_booking("booking")["status"] == "requested"
        copy = tx.get_booking("booking")
        copy["status"] = "changed without save"
        assert tx.get_booking("booking")["status"] == "requested"


def test_memory_state_expiry_binding_and_single_use():
    store = MemoryStore()
    state = {
        "state_hash": "hash",
        "session_id": "session",
        "expires_at": "2030-01-01T00:05:00+00:00",
    }
    with store.transaction() as tx:
        tx.save_state(state)
        assert tx.consume_state("hash", "wrong", "2030-01-01T00:00:00+00:00") is None
        assert tx.consume_state("hash", "session", "2030-01-01T00:00:00+00:00") == state
        assert tx.consume_state("hash", "session", "2030-01-01T00:00:00+00:00") is None
        tx.save_state(state)
        assert tx.consume_state("hash", "session", "2030-01-01T00:05:00+00:00") is None


def test_outbox_unique_keys_status_filter_and_deliveries():
    store = MemoryStore()
    with store.transaction() as tx:
        assert tx.enqueue("same", "calendar", "booking", 1)
        assert not tx.enqueue("same", "calendar", "booking", 1)
        job = tx.get_outbox("same")
        job["status"] = "published"
        tx.save_outbox(job)
        assert tx.list_outbox(statuses=["pending"]) == []
        tx.save_delivery({"key": "same", "status": "sent"})
        assert tx.get_delivery("same")["status"] == "sent"


def test_sql_missing_credentials_fail_closed():
    with pytest.raises(StoreUnavailable, match="Booking persistence is unavailable"):
        with Store({"DB_USER": "", "DB_PASSWORD": ""}).transaction():
            pass


@pytest.fixture
def sql_settings():
    if os.getenv("RUN_DATABASE_INTEGRATION") != "1":
        pytest.skip("No disposable MySQL configured")
    settings = {
        "APP_ENV": "development",
        "DB_HOST": os.getenv("DB_HOST", "127.0.0.1"),
        "DB_PORT": int(os.getenv("DB_PORT", "3306")),
        "DB_NAME": os.getenv("DB_NAME", "popssibilities_ci"),
        "DB_USER": os.getenv("DB_USER", ""),
        "DB_PASSWORD": os.getenv("DB_PASSWORD", ""),
        "DB_TLS_CA_FILE": "",
    }
    name = settings["DB_NAME"].lower()
    if not (name.endswith(("_test", "_ci")) or name.startswith("test_")):
        pytest.fail("Booking persistence tests require a disposable database")
    apply_migrations(settings)
    with database.connect(settings) as connection, connection.cursor() as cursor:
        for table in (
            "square_events",
            "square_checkouts",
            "automation_requests",
            "automation_order_links",
            "automation_payments",
            "automation_bookings",
            "automation_outbox",
            "automation_deliveries",
            "automation_connections",
            "automation_oauth_states",
            "automation_audit",
        ):
            cursor.execute("DELETE FROM " + table)
        connection.commit()
    return settings


@pytest.fixture(params=[False, True], ids=["normal-grants", "append-only-ledgers"])
def ledger_settings(sql_settings, request):
    if not request.param:
        yield sql_settings
        return
    password = os.getenv("DB_TEST_ADMIN_PASSWORD")
    if not password:
        pytest.skip("No disposable MySQL administrator configured for privilege tests")
    admin = {**sql_settings, "DB_USER": "root", "DB_PASSWORD": password}
    user, credential = "b10_ledger_" + uuid4().hex[:16], uuid4().hex
    database_name = sql_settings["DB_NAME"]
    assert database_name.replace("_", "").isalnum()
    with database.connect(admin, autocommit=True) as connection, connection.cursor() as cursor:
        cursor.execute("CREATE USER %s IDENTIFIED BY %s", (user, credential))
        try:
            for table in (
                "automation_mutex",
                "automation_bookings",
                "automation_outbox",
                "inventory_reservations",
            ):
                cursor.execute(
                    f"GRANT SELECT, INSERT, UPDATE ON `{database_name}`.`{table}` TO %s", (user,)
                )
            for table in ("automation_payments", "square_events", "automation_audit"):
                cursor.execute(
                    f"GRANT SELECT, INSERT ON `{database_name}`.`{table}` TO %s", (user,)
                )
            yield {**sql_settings, "DB_USER": user, "DB_PASSWORD": credential}
        finally:
            cursor.execute("DROP USER %s", (user,))


@pytest.mark.database
def test_sql_capacity_and_payment_identity_are_cross_process_atomic(ledger_settings):
    from app.automation.domain import BookingService, DomainError

    now = datetime(2030, 1, 1, tzinfo=timezone.utc).timestamp()
    services = [
        BookingService(Store(ledger_settings), capacity=50, clock=lambda: now) for _ in range(2)
    ]
    base = {
        "start": "2030-02-20T14:00:00-06:00",
        "end": "2030-02-20T16:00:00-06:00",
        "timezone": "America/Chicago",
        "venue": "Houston",
        "quantity": 50,
        "service_type": "delivery",
        "customer_email": "a@example.invalid",
        "total_minor": 10001,
        "currency": "USD",
        "contract_url": "https://example.invalid/contract",
    }
    rows = [service.create(base, "owner") for service in services]
    barrier = threading.Barrier(2)

    def attempt(index):
        barrier.wait()
        try:
            return services[index].approve(rows[index]["id"], {}, "owner")
        except DomainError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        approved = [row for row in pool.map(attempt, range(2)) if row]
    assert len(approved) == 1
    payment = {
        "reference": "provider-transaction",
        "amount_minor": 5001,
        "currency": "USD",
        "verification_details": "Owner verified settled transaction at provider",
    }
    barrier = threading.Barrier(2)

    def verify(index):
        barrier.wait()
        return services[index].verify_payment(approved[0]["id"], payment, "owner")

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(verify, range(2)))
    assert results[0] == results[1]
    with services[0].store.transaction() as tx:
        assert len(tx.payments(approved[0]["id"])) == 1
        event = {"id": "square-event-regression"}
        assert tx.get_square_event(event["id"]) is None
        tx.save_square_event(event)
        assert tx.get_square_event(event["id"]) == event
    if ledger_settings["DB_USER"].startswith("b10_ledger_"):
        # Successful approval and duplicate payment verification must never
        # require permission to edit or remove the immutable ledger records.
        with database.connect(ledger_settings) as connection, connection.cursor() as cursor:
            for table in ("automation_payments", "square_events"):
                for statement in (
                    f"UPDATE {table} SET data=data WHERE 1=0",
                    f"DELETE FROM {table} WHERE 1=0",
                ):
                    with pytest.raises(pymysql.MySQLError) as failure:
                        cursor.execute(statement)
                    assert failure.value.args[0] == 1142


@pytest.mark.database
def test_sql_rollback_single_use_state_and_nested_named_locks(sql_settings):
    store = Store(sql_settings)
    booking = {
        "id": "b" * 32,
        "status": "confirmed",
        "revision": 1,
        "start": "2030-02-20T20:00:00+00:00",
        "end": "2030-02-20T22:00:00+00:00",
    }
    with store.booking_lock(booking["id"]):
        with store.booking_lock("google:owner"):
            with store.transaction() as tx:
                tx.save_booking(booking)
        # Releasing the inner owner lock must preserve the outer connection.
        with store.transaction() as tx:
            assert tx.get_booking(booking["id"]) == booking
    with pytest.raises(RuntimeError):
        with store.transaction() as tx:
            tx.add_payment(
                {
                    "reference": "rollback-payment",
                    "booking_id": booking["id"],
                    "amount_minor": 1,
                    "currency": "USD",
                    "verified_by": "owner",
                    "verified_at": "2030-01-01T00:00:00+00:00",
                }
            )
            tx.enqueue("rollback-outbox", "calendar", booking["id"], 1)
            tx.audit("rollback.audit", "owner", {}, "2030-01-01T00:00:00+00:00")
            raise RuntimeError("rollback all three writes")
    with store.transaction() as tx:
        assert tx.payments(booking["id"]) == []
        assert tx.get_outbox("rollback-outbox") is None
        state = {
            "state_hash": hashlib.sha256(b"state").hexdigest(),
            "session_id": hashlib.sha256(b"session").hexdigest(),
            "expires_at": "2030-01-01T00:05:00+00:00",
        }
        tx.save_state(state)
    barrier = threading.Barrier(2)

    def consume(_):
        barrier.wait()
        with Store(sql_settings).transaction() as tx:
            return tx.consume_state(
                state["state_hash"], state["session_id"], "2030-01-01T00:00:00+00:00"
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(row is not None for row in pool.map(consume, range(2))) == 1
    with database.connect(sql_settings) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT COUNT(*) AS total FROM automation_audit WHERE event='rollback.audit'"
        )
        assert cursor.fetchone()["total"] == 0
