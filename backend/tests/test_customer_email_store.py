"""Delivery reservations and abuse budgets on a disposable MySQL database."""

from concurrent.futures import ThreadPoolExecutor
import threading
from uuid import NAMESPACE_URL, uuid5

import pytest

from app import database
from app.auth.store import Store
from app.email.store import MailConflict, MailRateLimited, MailStore, MailStoreUnavailable
from app.migrations import apply_migrations
from test_auth_store import NOW, db_settings, digest


TABLES = ("email_test_messages", "email_test_budgets")


def customer(label):
    return str(uuid5(NAMESPACE_URL, "customer-email-test:" + label))


@pytest.fixture
def mail_store(db_settings):
    apply_migrations(db_settings)
    with database.connect(db_settings) as connection, connection.cursor() as cursor:
        for table in TABLES:
            cursor.execute("DELETE FROM " + table)
        connection.commit()
    yield MailStore(db_settings)
    with database.connect(db_settings) as connection, connection.cursor() as cursor:
        for table in TABLES:
            cursor.execute("DELETE FROM " + table)
        connection.commit()


def reserve(store, label="first", *, identity="first", recipient="first", now=NOW):
    return store.reserve(customer(identity), digest("request:" + label),
                         digest("recipient:" + recipient), now)


def message_count(settings):
    with database.connect(settings) as connection, connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) AS total FROM email_test_messages")
        return cursor.fetchone()["total"]


def test_customer_email_store_fails_closed_without_database_credentials():
    store = MailStore({"DB_USER": "", "DB_PASSWORD": ""})
    with pytest.raises(MailStoreUnavailable):
        reserve(store)
    with pytest.raises(MailStoreUnavailable):
        store.finish(digest("request:first"), "failed", NOW, error_code="mail_unavailable")


@pytest.mark.database
def test_reservation_contains_only_recipient_digest_and_stable_reference(mail_store):
    row, created = reserve(mail_store)
    assert created is True
    assert row["identity_id"] == customer("first")
    assert row["request_hash"] == digest("request:first")
    assert row["recipient_hash"] == digest("recipient:first")
    assert row["status"] == "sending"
    assert row["created_at"] == NOW
    assert row["reference"]
    assert not row.get("provider_message_id")
    repeated, created = reserve(mail_store)
    assert created is False
    assert repeated["reference"] == row["reference"]
    assert message_count(mail_store.settings) == 1


@pytest.mark.database
def test_same_request_is_reserved_once_across_concurrent_connections(mail_store):
    barrier = threading.Barrier(6)

    def claim(_):
        barrier.wait()
        return reserve(MailStore(mail_store.settings))

    with ThreadPoolExecutor(max_workers=6) as executor:
        results = list(executor.map(claim, range(6)))
    assert sum(created for _, created in results) == 1
    assert len({row["reference"] for row, _ in results}) == 1
    assert message_count(mail_store.settings) == 1


@pytest.mark.database
@pytest.mark.parametrize("changed", [{"identity": "another"}, {"recipient": "another"}])
def test_request_collision_cannot_be_reused_for_different_identity_or_recipient(mail_store, changed):
    reserve(mail_store)
    with pytest.raises(MailConflict):
        reserve(mail_store, **changed)
    assert message_count(mail_store.settings) == 1


@pytest.mark.database
def test_global_one_per_second_limit_is_shared_by_all_customers(mail_store):
    reserve(mail_store)
    with pytest.raises(MailRateLimited):
        reserve(MailStore(mail_store.settings), "second", identity="second", recipient="second")
    row, created = reserve(mail_store, "second", identity="second", recipient="second", now=NOW + 1)
    assert created is True
    assert row["status"] == "sending"
    assert message_count(mail_store.settings) == 2


@pytest.mark.database
def test_concurrent_different_requests_cannot_exceed_global_pacing(mail_store):
    barrier = threading.Barrier(6)

    def claim(number):
        barrier.wait()
        label = str(number)
        try:
            _, created = reserve(MailStore(mail_store.settings), label,
                                 identity=label, recipient=label)
            return created
        except MailRateLimited:
            return False

    with ThreadPoolExecutor(max_workers=6) as executor:
        results = list(executor.map(claim, range(6)))
    assert sum(results) == 1
    assert message_count(mail_store.settings) == 1


@pytest.mark.database
def test_customer_hourly_budget_cannot_be_bypassed_by_changing_email(mail_store):
    for number in range(3):
        reserve(mail_store, str(number), recipient=str(number), now=NOW + number * 2)
    with pytest.raises(MailRateLimited):
        reserve(mail_store, "fourth", recipient="new-address", now=NOW + 6)
    assert message_count(mail_store.settings) == 3
    assert reserve(mail_store, "next-hour", recipient="new-address", now=NOW + 3601)[1] is True


@pytest.mark.database
def test_recipient_hourly_budget_is_shared_by_separate_customer_identities(mail_store):
    for number in range(3):
        reserve(mail_store, str(number), identity=str(number), now=NOW + number * 2)
    with pytest.raises(MailRateLimited):
        reserve(mail_store, "fourth", identity="fourth", now=NOW + 6)
    assert message_count(mail_store.settings) == 3
    assert reserve(mail_store, "next-hour", identity="next-hour", now=NOW + 3601)[1] is True


@pytest.mark.database
def test_rejected_recipient_does_not_consume_global_or_customer_budgets(mail_store):
    for number in range(3):
        reserve(mail_store, str(number), identity=str(number), now=NOW + number * 2)
    with pytest.raises(MailRateLimited):
        reserve(mail_store, "blocked", identity="another-customer", now=NOW + 6)
    # All earlier bucket changes must roll back when a later bucket rejects a
    # request, leaving this same-second request to a different mailbox usable.
    assert reserve(mail_store, "allowed", identity="another-customer",
                   recipient="another-mailbox", now=NOW + 6)[1] is True
    assert message_count(mail_store.settings) == 4


@pytest.mark.database
def test_daily_budget_is_shared_and_rolls_over_at_utc_midnight(mail_store):
    day = (NOW // 86400) * 86400
    for number in range(60):
        label = str(number)
        assert reserve(mail_store, label, identity=label, recipient=label,
                       now=day + number * 2)[1] is True
    with pytest.raises(MailRateLimited):
        reserve(mail_store, "over-daily-limit", identity="new", recipient="new", now=day + 120)
    assert message_count(mail_store.settings) == 60
    assert reserve(mail_store, "next-day", identity="new", recipient="new", now=day + 86400)[1] is True


@pytest.mark.database
def test_duplicate_request_does_not_consume_customer_budget(mail_store):
    original, _ = reserve(mail_store)
    for _ in range(5):
        row, created = reserve(mail_store)
        assert created is False
        assert row["reference"] == original["reference"]
    assert reserve(mail_store, "second", now=NOW + 1)[1] is True
    assert reserve(mail_store, "third", now=NOW + 2)[1] is True
    with pytest.raises(MailRateLimited):
        reserve(mail_store, "fourth", now=NOW + 3)


@pytest.mark.database
@pytest.mark.parametrize("status", ["accepted", "failed", "uncertain"])
def test_finished_send_is_durable_and_cannot_be_rewritten_or_resent(mail_store, status):
    row, _ = reserve(mail_store)
    message_id = "ses-test-message" if status == "accepted" else None
    error_code = "mail_unavailable" if status != "accepted" else None
    mail_store.finish(row["request_hash"], status, NOW + 1,
                      message_id=message_id, error_code=error_code)
    mail_store.finish(row["request_hash"], "failed", NOW + 2, error_code="later-error")
    repeated, created = reserve(MailStore(mail_store.settings), now=NOW + 60)
    assert created is False
    assert repeated["status"] == status
    assert repeated.get("provider_message_id") == message_id
    assert repeated.get("error_code") == error_code
    assert repeated["reference"] == row["reference"]
    assert message_count(mail_store.settings) == 1


@pytest.mark.database
def test_interrupted_send_becomes_uncertain_without_another_reservation(mail_store):
    row, _ = reserve(mail_store)
    in_flight, created = reserve(mail_store, now=NOW + 29)
    assert created is False
    assert in_flight["status"] == "sending"
    abandoned, created = reserve(MailStore(mail_store.settings), now=NOW + 30)
    assert created is False
    assert abandoned["status"] == "uncertain"
    assert abandoned["reference"] == row["reference"]
    mail_store.finish(row["request_hash"], "accepted", NOW + 31, message_id="late-ses-response")
    reconciled, created = reserve(mail_store, now=NOW + 32)
    assert created is False
    assert reconciled["status"] == "accepted"
    assert reconciled["provider_message_id"] == "late-ses-response"
    assert message_count(mail_store.settings) == 1


@pytest.mark.database
def test_auth_readiness_does_not_require_optional_email_migration(mail_store, db_settings):
    assert Store(db_settings).ready()
    try:
        with database.connect(db_settings) as connection, connection.cursor() as cursor:
            cursor.execute("UPDATE schema_migrations SET applied_at=NULL WHERE version=6")
            for table in TABLES:
                cursor.execute("DROP TABLE " + table)
            connection.commit()
        assert Store(db_settings).ready()
        with pytest.raises(MailStoreUnavailable):
            reserve(mail_store)
    finally:
        apply_migrations(db_settings)
