"""Authentication persistence contracts, exercised against disposable MySQL."""

from concurrent.futures import ThreadPoolExecutor
import hashlib
import os
import shutil
import threading
import time

import pytest

from app import database
from app.auth.store import AccessDeniedError, BootstrapRejectedError, LastOwnerError, LoginCancelledError, Store, StoreUnavailable
from app.migrations import MIGRATIONS, MigrationError, apply_migrations, statements


NOW = 1800000000
TABLES = ("auth_admin_recoveries", "auth_admin_native_flows", "auth_admin_google_challenges", "auth_admin_totp", "auth_admin_google_links", "auth_sessions", "auth_flows", "auth_flow_cancellations", "auth_admin_access", "auth_audit_events", "auth_rate_limits", "auth_admin_login_epochs", "auth_identities")


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


@pytest.fixture
def db_settings():
    if os.getenv("RUN_DATABASE_INTEGRATION") != "1":
        pytest.skip("No disposable MySQL configured")
    settings = {
        "APP_ENV": "development",
        "DB_HOST": os.getenv("DB_HOST", "127.0.0.1"),
        "DB_PORT": int(os.getenv("DB_PORT", "3306")),
        "DB_NAME": os.getenv("DB_NAME", "popssibilities_ci"),
        "DB_USER": os.getenv("DB_USER", ""),
        "DB_PASSWORD": os.getenv("DB_PASSWORD", ""),
        "DB_TLS_CA_FILE": os.getenv("DB_TLS_CA_FILE", ""),
    }
    name = settings["DB_NAME"].lower()
    if not (name.endswith(("_ci", "_test")) or name.startswith("test_")):
        pytest.fail("Auth persistence tests require a disposable database named *_ci, *_test, or test_*")
    return settings


@pytest.fixture
def store(db_settings):
    apply_migrations(db_settings)
    with database.connect(db_settings) as connection, connection.cursor() as cursor:
        for table in TABLES:
            cursor.execute("DELETE FROM " + table)
        connection.commit()
    return Store(db_settings)


def identity(store, area="customer", subject="test-subject", issuer=None):
    return store.upsert_identity(issuer or "https://issuer.example/" + area, subject, area,
                                 "test@example.invalid", "Test Person", NOW)


def session(store, person, token="opaque-test-session", binding=None):
    row = {
        "token_hash": digest(token), "identity_id": person["id"], "area": person["area"],
        "created_at": NOW, "last_seen": NOW, "expires_at": NOW + 3600, "auth_time": NOW,
        "assurance": {"mfa": person["area"] == "admin"}, "encrypted_tokens": "test-ciphertext",
        "login_binding_hash": binding,
    }
    store.create_session(row)
    return row


def test_credentials_missing_fail_closed():
    with pytest.raises(StoreUnavailable, match="Authentication persistence is unavailable"):
        Store({"DB_USER": "", "DB_PASSWORD": ""}).get_session(digest("session"), "admin")


def test_connection_verifies_tls_and_hostname(monkeypatch):
    observed = {}
    monkeypatch.setattr(database.pymysql, "connect", lambda **options: observed.update(options))
    database.connect({"APP_ENV": "production", "DB_HOST": "db.example.invalid", "DB_PORT": 3306,
                      "DB_NAME": "test_db", "DB_USER": "test_user", "DB_PASSWORD": "test_only",
                      "DB_TLS_CA_FILE": "/test/ca.pem"})
    assert observed["ssl_verify_cert"] is True
    assert observed["ssl_verify_identity"] is True
    assert observed["ssl_ca"] == "/test/ca.pem"
    with pytest.raises(database.pymysql.OperationalError, match="verified TLS"):
        database.connect({"APP_ENV": "production", "DB_HOST": "db.example.invalid", "DB_PORT": 3306,
                          "DB_NAME": "test_db", "DB_USER": "test_user", "DB_PASSWORD": "test_only"})


def test_migration_runner_rejects_nonresumable_ddl(tmp_path):
    path = tmp_path / "0001_unsafe.sql"
    path.write_text("DROP TABLE customers;\n")
    with pytest.raises(MigrationError, match="resumable"):
        statements(path)


@pytest.mark.database
def test_fresh_migration_rerun_and_interrupted_recovery(store, db_settings):
    person = identity(store)
    assert store.ready()
    assert apply_migrations(db_settings) == []
    with database.connect(db_settings) as connection, connection.cursor() as cursor:
        cursor.execute("UPDATE schema_migrations SET applied_at=NULL WHERE version=1")
        cursor.execute("DROP TABLE auth_rate_limits")
        connection.commit()
    assert not store.ready()
    assert apply_migrations(db_settings) == ["0001_auth.sql"]
    assert store.ready()
    assert store.find_identity(person["issuer"], person["subject"])["id"] == person["id"]


@pytest.mark.database
def test_migration_checksum_cannot_be_rewritten(store, db_settings, tmp_path):
    copied = tmp_path / "migrations"
    shutil.copytree(MIGRATIONS, copied)
    migration = copied / "0001_auth.sql"
    migration.write_text(migration.read_text() + "-- Changed migration checksum.\n")
    with pytest.raises(MigrationError, match="has changed"):
        apply_migrations(db_settings, copied)
    assert store.ready()


@pytest.mark.database
def test_identity_uses_case_sensitive_subject_not_email(store):
    first = identity(store, subject="SubjectA")
    other = identity(store, subject="subjecta")
    padded = identity(store, subject="SubjectA ")
    another_pool = identity(store, subject="SubjectA", issuer="https://issuer.example/another")
    assert len({first["id"], other["id"], padded["id"], another_pool["id"]}) == 4
    assert store.upsert_identity(first["issuer"], first["subject"], "customer",
                                 "changed@example.invalid", "Changed Name", NOW + 1)["id"] == first["id"]
    assert len(store.find_identity_by_email("test@example.invalid", "customer")) == 3
    with pytest.raises(ValueError, match="area cannot change"):
        store.upsert_identity(first["issuer"], first["subject"], "admin", first["email"], first["name"], NOW)


@pytest.mark.database
def test_customer_identity_never_receives_admin_access(store):
    customer = identity(store)
    assert customer["admin_role"] is None
    with pytest.raises(ValueError, match="administrator identity"):
        store.grant_admin(customer["id"], "owner", NOW)
    admin = identity(store, "admin")
    assert admin["admin_role"] is None
    with pytest.raises(AccessDeniedError):
        session(store, admin)


@pytest.mark.database
def test_flows_bind_browser_area_expiry_and_single_use(store):
    flow = {"state_hash": digest("state"), "binding_hash": digest("browser"), "area": "admin",
            "created_at": NOW, "expires_at": NOW + 300, "encrypted_payload": "encrypted-oauth-secrets"}
    store.put_flow(flow)
    assert store.consume_flow(flow["state_hash"], digest("wrong"), "admin", NOW) is None
    assert store.consume_flow(flow["state_hash"], flow["binding_hash"], "customer", NOW) is None
    assert store.consume_flow(flow["state_hash"], flow["binding_hash"], "admin", NOW + 300) is None
    assert store.consume_flow(flow["state_hash"], flow["binding_hash"], "admin", NOW) == flow
    assert store.consume_flow(flow["state_hash"], flow["binding_hash"], "admin", NOW) is None


@pytest.mark.database
def test_simultaneous_callback_consumption_accepts_once(store):
    flow = {"state_hash": digest("state"), "binding_hash": digest("browser"), "area": "customer",
            "created_at": NOW, "expires_at": NOW + 300, "encrypted_payload": "encrypted-oauth-secrets"}
    store.put_flow(flow)
    barrier = threading.Barrier(6)

    def consume(_):
        barrier.wait()
        return store.consume_flow(flow["state_hash"], flow["binding_hash"], "customer", NOW)

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(consume, range(6)))
    assert sum(result is not None for result in results) == 1


@pytest.mark.database
def test_logout_cancels_pending_and_already_consumed_login_flows(store):
    person = identity(store)
    binding = digest("pending-login-browser")
    flow = {"state_hash": digest("consumed-state"), "binding_hash": binding, "area": "customer",
            "created_at": NOW, "expires_at": NOW + 600, "encrypted_payload": "encrypted-oauth-secrets"}
    store.put_flow(flow)
    consumed = store.consume_flow(flow["state_hash"], binding, "customer", NOW)
    assert consumed == flow
    pending = dict(flow, state_hash=digest("still-pending-state"))
    store.put_flow(pending)
    store.cancel_login(binding, "customer", NOW + 1)
    assert store.consume_flow(pending["state_hash"], binding, "customer", NOW + 2) is None
    with pytest.raises(LoginCancelledError):
        session(store, person, binding=binding)
    assert store.get_session(digest("opaque-test-session"), "customer") is None


@pytest.mark.database
def test_logout_revokes_sessions_created_by_its_pending_flow_only(store):
    customer = identity(store)
    admin = identity(store, "admin")
    store.grant_admin(admin["id"], "owner", NOW)
    binding = digest("pending-login-browser")
    bound = session(store, customer, "bound-customer-session", binding=binding)
    independent = session(store, customer, "other-browser-session", binding=digest("other-browser"))
    other_area = session(store, admin, "admin-session", binding=binding)
    store.cancel_login(binding, "customer", NOW + 1)
    assert store.get_session(bound["token_hash"], "customer") is None
    assert store.get_session(independent["token_hash"], "customer") is not None
    assert store.get_session(other_area["token_hash"], "admin") is not None


@pytest.mark.database
def test_concurrent_callback_session_creation_and_logout_cannot_leave_session_active(store):
    person = identity(store)
    binding = digest("consumed-login-browser")
    barrier = threading.Barrier(2)

    def create():
        barrier.wait()
        try:
            session(store, person, binding=binding)
        except LoginCancelledError:
            pass

    def cancel():
        barrier.wait()
        store.cancel_login(binding, "customer", NOW + 1)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(create), pool.submit(cancel)]
        for future in futures:
            future.result(timeout=5)
    assert store.get_session(digest("opaque-test-session"), "customer") is None


@pytest.mark.database
def test_cancel_login_audit_failure_rolls_back_tombstone_flow_delete_and_revocation(store, monkeypatch):
    person = identity(store)
    binding = digest("pending-login-browser")
    row = session(store, person, binding=binding)
    flow = {"state_hash": digest("pending-state"), "binding_hash": binding, "area": "customer",
            "created_at": NOW, "expires_at": NOW + 600, "encrypted_payload": "encrypted-oauth-secrets"}
    store.put_flow(flow)

    def failed_audit(*args):
        raise database.pymysql.OperationalError("PRIVATE_DATABASE_DETAIL")

    monkeypatch.setattr(store, "_audit", failed_audit)
    with pytest.raises(StoreUnavailable):
        store.cancel_login(binding, "customer", NOW + 1)
    assert store.get_session(row["token_hash"], "customer") is not None
    assert store.consume_flow(flow["state_hash"], binding, "customer", NOW + 2) == flow
    session(store, person, "new-session-after-rollback", binding=binding)


@pytest.mark.database
def test_cancellation_retention_is_idempotent_and_cleanup_preserves_audit(store):
    binding = digest("pending-login-browser")
    store.cancel_login(binding, "customer", NOW)
    store.cancel_login(binding, "customer", NOW - 1)
    assert store.cleanup(NOW + 599)["auth_flow_cancellations"] == 0
    assert store.cleanup(NOW + 600)["auth_flow_cancellations"] == 1
    with database.connect(store.settings) as connection, connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) AS total FROM auth_audit_events WHERE event='login.cancelled'")
        assert cursor.fetchone()["total"] == 2


@pytest.mark.database
def test_cancelled_browser_binding_cannot_start_another_flow(store):
    binding = digest("cancelled-login-browser")
    store.cancel_login(binding, "customer", NOW)
    flow = {"state_hash": digest("new-state"), "binding_hash": binding, "area": "customer",
            "created_at": NOW + 1, "expires_at": NOW + 601, "encrypted_payload": "encrypted-oauth-secrets"}
    with pytest.raises(LoginCancelledError):
        store.put_flow(flow)
    assert store.consume_flow(flow["state_hash"], binding, "customer", NOW + 2) is None


@pytest.mark.database
def test_new_browser_generation_can_start_after_previous_generation_cancelled(store):
    store.cancel_login(digest("cancelled-login-browser"), "customer", NOW)
    flow = {"state_hash": digest("fresh-state"), "binding_hash": digest("fresh-login-browser"), "area": "customer",
            "created_at": NOW + 1, "expires_at": NOW + 601, "encrypted_payload": "encrypted-oauth-secrets"}
    store.put_flow(flow)
    assert store.consume_flow(flow["state_hash"], flow["binding_hash"], "customer", NOW + 2) == flow


@pytest.mark.database
def test_concurrent_new_flow_and_logout_cannot_leave_usable_flow(store):
    binding = digest("cancelled-login-browser")
    flow = {"state_hash": digest("racing-state"), "binding_hash": binding, "area": "customer",
            "created_at": NOW, "expires_at": NOW + 600, "encrypted_payload": "encrypted-oauth-secrets"}
    barrier = threading.Barrier(2)

    def start():
        barrier.wait()
        try:
            store.put_flow(flow)
        except LoginCancelledError:
            pass

    def cancel():
        barrier.wait()
        store.cancel_login(binding, "customer", NOW + 1)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(start), pool.submit(cancel)]
        for future in futures:
            future.result(timeout=5)
    assert store.consume_flow(flow["state_hash"], binding, "customer", NOW + 2) is None


@pytest.mark.database
def test_rate_limit_is_shared_atomic_and_resets_next_window(store):
    barrier = threading.Barrier(8)

    def attempt(_):
        barrier.wait()
        return Store(store.settings).rate_limit("login:test-ip", 3, 60, NOW)

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(attempt, range(8)))
    assert sum(results) == 3
    assert store.rate_limit("login:test-ip", 3, 60, NOW + 60)
    assert store.rate_limit("login:other-ip", 3, 60, NOW)


@pytest.mark.database
def test_session_area_expiry_refresh_and_revocation(store):
    person = identity(store)
    row = session(store, person)
    assert store.get_session(row["token_hash"], "admin") is None
    fetched = store.get_session(row["token_hash"], "customer")
    assert fetched["identity_id"] == person["id"]
    assert fetched["assurance"] == {"mfa": False}
    assert store.touch_session(row["token_hash"], NOW)
    assert store.touch_session(row["token_hash"], NOW + 10)
    assert not store.touch_session(row["token_hash"], NOW + 3600)
    assert store.update_tokens(row["token_hash"], "new-ciphertext", NOW)
    assert not store.update_tokens(row["token_hash"], "late-ciphertext", NOW + 3600)
    assert store.revoke_session(row["token_hash"], NOW + 20)
    assert not store.revoke_session(row["token_hash"], NOW + 20)
    assert store.get_session(row["token_hash"], "customer") is None
    assert not store.update_tokens(row["token_hash"], "revoked-ciphertext", NOW + 21)


@pytest.mark.database
def test_refresh_lock_serializes_workers_and_rechecks_tokens(store):
    row = session(store, identity(store))
    observed = []
    first_has_lock = threading.Event()

    def first():
        with store.session_lock(row["token_hash"]):
            first_has_lock.set()
            time.sleep(0.1)
            store.update_tokens(row["token_hash"], "rotated-ciphertext", NOW)

    def second():
        first_has_lock.wait(2)
        with Store(store.settings).session_lock(row["token_hash"]):
            observed.append(store.get_session(row["token_hash"], "customer")["encrypted_tokens"])

    with ThreadPoolExecutor(max_workers=2) as pool:
        tasks = [pool.submit(first), pool.submit(second)]
        for task in tasks:
            task.result(timeout=5)
    assert observed == ["rotated-ciphertext"]


@pytest.mark.database
def test_admin_access_changes_revoke_sessions_and_preserve_final_owner(store, db_settings):
    owner = identity(store, "admin", "owner")
    store.grant_admin(owner["id"], "owner", NOW, bootstrap=True)
    assert store.count_active_owners(owner["issuer"]) == 1
    with pytest.raises(LastOwnerError):
        store.set_admin_access(owner["id"], active=False, now=NOW)
    with pytest.raises(LastOwnerError):
        store.set_admin_access(owner["id"], role="staff", now=NOW)
    with pytest.raises(LastOwnerError):
        store.grant_admin(owner["id"], "staff", NOW)
    other = identity(store, "admin", "other-owner")
    with pytest.raises(BootstrapRejectedError):
        store.grant_admin(other["id"], "owner", NOW, bootstrap=True)
    store.grant_admin(other["id"], "owner", NOW)
    row = session(store, owner)
    store.set_admin_access(owner["id"], role="staff", now=NOW + 1)
    assert store.get_session(row["token_hash"], "admin") is None
    assert store.find_identity(owner["issuer"], "owner")["admin_role"] == "staff"
    with database.connect(db_settings) as connection, connection.cursor() as cursor:
        cursor.execute("SELECT event,detail FROM auth_audit_events WHERE identity_id=%s ORDER BY id", (owner["id"],))
        events = cursor.fetchall()
    assert [event["event"] for event in events] == ["admin.access_granted", "admin.access_changed"]


@pytest.mark.database
def test_bootstrap_owner_is_atomic_across_operators(store):
    people = [identity(store, "admin", "owner-" + str(index)) for index in range(2)]
    barrier = threading.Barrier(2)

    def bootstrap(person):
        barrier.wait()
        try:
            store.grant_admin(person["id"], "owner", NOW, bootstrap=True)
            return True
        except BootstrapRejectedError:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(bootstrap, people)) == 1
    assert store.count_active_owners(people[0]["issuer"]) == 1


@pytest.mark.database
def test_concurrent_owner_demotions_preserve_one_active_owner(store):
    people = [identity(store, "admin", "owner-" + str(index)) for index in range(2)]
    for person in people:
        store.grant_admin(person["id"], "owner", NOW)
    barrier = threading.Barrier(2)

    def demote(person):
        barrier.wait()
        try:
            store.set_admin_access(person["id"], role="staff", now=NOW + 1)
            return True
        except LastOwnerError:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(demote, people)) == 1
    assert store.count_active_owners(people[0]["issuer"]) == 1


@pytest.mark.database
def test_admin_change_rolls_back_if_durable_audit_fails(store, monkeypatch):
    owner = identity(store, "admin", "owner")
    staff = identity(store, "admin", "staff")
    store.grant_admin(owner["id"], "owner", NOW)
    store.grant_admin(staff["id"], "staff", NOW)
    row = session(store, staff)

    def failed_audit(*args):
        raise database.pymysql.OperationalError("PRIVATE_DATABASE_DETAIL")

    monkeypatch.setattr(store, "_audit", failed_audit)
    with pytest.raises(StoreUnavailable) as failure:
        store.set_admin_access(staff["id"], active=False, now=NOW + 1)
    assert "PRIVATE_DATABASE_DETAIL" not in str(failure.value)
    assert store.find_identity(staff["issuer"], staff["subject"])["admin_active"] == 1
    assert store.get_session(row["token_hash"], "admin") is not None


@pytest.mark.database
def test_cleanup_removes_expired_secrets_but_retains_audits(store):
    person = identity(store)
    row = session(store, person)
    store.audit("test.security_event", person["id"], detail={"area": "customer"}, now=NOW)
    store.put_flow({"state_hash": digest("state"), "binding_hash": digest("browser"), "area": "customer",
                    "created_at": NOW, "expires_at": NOW + 300, "encrypted_payload": "ciphertext"})
    store.rate_limit("test-rate", 2, 60, NOW)
    assert store.cleanup(NOW + 3600) == {"auth_flows": 1, "auth_flow_cancellations": 0, "auth_admin_google_challenges": 0, "auth_admin_native_flows": 0, "auth_rate_limits": 1, "auth_sessions": 1}
    assert store.get_session(row["token_hash"], "customer") is None
    with database.connect(store.settings) as connection, connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) AS total FROM auth_audit_events")
        assert cursor.fetchone()["total"] == 1
