"""Browser-bound native Cognito transactions on disposable MySQL."""

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from app import database
from app.auth.store import LoginCancelledError, Store, StoreUnavailable
from app.migrations import MIGRATIONS, apply_migrations, checksum
from test_auth_store import NOW, digest, identity, session
from test_auth_store import db_settings as db_settings
from test_auth_store import store as store


def native_flow(label="first", binding=None, now=NOW, attempts=0):
    return {
        "token_hash": digest("native-challenge:" + label),
        "binding_hash": binding or digest("native-browser:" + label),
        "created_at": now,
        "expires_at": now + 300,
        "attempts": attempts,
        "encrypted_payload": "encrypted-cognito-state:" + label,
    }


@pytest.mark.parametrize(
    "created,expires", [(NOW, NOW), (NOW, NOW + 301), (-1, NOW), (True, NOW), (NOW, float(NOW + 1))]
)
def test_native_flow_rejects_invalid_lifetime_before_database_access(created, expires):
    flow = dict(native_flow(), created_at=created, expires_at=expires)
    with pytest.raises(ValueError, match="five minutes"):
        Store({}).put_admin_native_flow(flow)


@pytest.mark.parametrize("attempts", [-1, 6, True, 1.0])
def test_native_flow_rejects_invalid_attempt_count_before_database_access(attempts):
    with pytest.raises(ValueError, match="zero and five"):
        Store({}).put_admin_native_flow(native_flow(attempts=attempts))


@pytest.mark.database
def test_native_pending_is_browser_bound_expiring_and_consumed_once(store):
    pending = native_flow()
    store.put_admin_native_flow(pending)
    assert store.get_admin_native_flow(pending["token_hash"], digest("other-browser"), NOW) is None
    assert (
        store.consume_admin_native_flow(pending["token_hash"], digest("other-browser"), NOW) is None
    )
    assert (
        store.get_admin_native_flow(pending["token_hash"], pending["binding_hash"], NOW) == pending
    )
    assert (
        store.get_admin_native_flow(pending["token_hash"], pending["binding_hash"], NOW + 300)
        is None
    )
    assert (
        store.consume_admin_native_flow(pending["token_hash"], pending["binding_hash"], NOW + 300)
        is None
    )
    consumed = store.consume_admin_native_flow(pending["token_hash"], pending["binding_hash"], NOW)
    assert consumed == dict(pending, attempts=1)
    assert store.get_admin_native_flow(pending["token_hash"], pending["binding_hash"], NOW) is None
    assert (
        store.consume_admin_native_flow(pending["token_hash"], pending["binding_hash"], NOW) is None
    )


@pytest.mark.database
def test_native_rotation_keeps_initial_deadline_and_five_attempt_budget(store):
    pending = native_flow()
    for attempt in range(5):
        store.put_admin_native_flow(pending)
        consumed = store.consume_admin_native_flow(
            pending["token_hash"], pending["binding_hash"], NOW + attempt
        )
        assert consumed["attempts"] == attempt + 1
        assert consumed["created_at"] == NOW
        assert consumed["expires_at"] == NOW + 300
        assert (
            store.consume_admin_native_flow(pending["token_hash"], pending["binding_hash"], NOW)
            is None
        )
        pending = dict(
            consumed,
            token_hash=digest("rotated-challenge:" + str(attempt)),
            encrypted_payload="rotated-encrypted-cognito-state:" + str(attempt),
        )
    store.put_admin_native_flow(pending)
    assert (
        store.get_admin_native_flow(pending["token_hash"], pending["binding_hash"], NOW + 5) is None
    )
    assert (
        store.consume_admin_native_flow(pending["token_hash"], pending["binding_hash"], NOW + 5)
        is None
    )
    assert store.cleanup(NOW + 300)["auth_admin_native_flows"] == 1


@pytest.mark.database
def test_simultaneous_native_challenge_consumption_has_one_winner(store):
    pending = native_flow()
    store.put_admin_native_flow(pending)
    barrier = threading.Barrier(6)

    def consume(_):
        barrier.wait()
        return Store(store.settings).consume_admin_native_flow(
            pending["token_hash"], pending["binding_hash"], NOW
        )

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(consume, range(6)))
    assert sum(row is not None for row in results) == 1
    assert next(row for row in results if row is not None)["attempts"] == 1


@pytest.mark.database
def test_native_logout_cancels_pending_provider_inflight_rotation_and_session(store):
    person = identity(store, "admin")
    store.grant_admin(person["id"], "owner", NOW)
    pending = native_flow()
    store.put_admin_native_flow(pending)
    consumed = store.consume_admin_native_flow(pending["token_hash"], pending["binding_hash"], NOW)
    second = dict(pending, token_hash=digest("other-pending-native-challenge"))
    store.put_admin_native_flow(second)
    active_session = session(store, person, binding=pending["binding_hash"])
    store.cancel_login(pending["binding_hash"], "admin", NOW + 1)
    assert (
        store.get_admin_native_flow(second["token_hash"], second["binding_hash"], NOW + 2) is None
    )
    assert store.get_session(active_session["token_hash"], "admin") is None
    with pytest.raises(LoginCancelledError):
        store.put_admin_native_flow(dict(consumed, token_hash=digest("provider-inflight-rotation")))
    with pytest.raises(LoginCancelledError):
        session(store, person, "provider-inflight-session", binding=pending["binding_hash"])
    assert store.get_session(digest("provider-inflight-session"), "admin") is None


@pytest.mark.database
def test_native_logout_preserves_other_browsers_and_customer_area(store):
    pending = native_flow()
    independent = native_flow("other-browser")
    store.put_admin_native_flow(pending)
    store.put_admin_native_flow(independent)
    store.cancel_login(pending["binding_hash"], "customer", NOW + 1)
    assert (
        store.get_admin_native_flow(pending["token_hash"], pending["binding_hash"], NOW + 2)
        == pending
    )
    store.cancel_login(pending["binding_hash"], "admin", NOW + 2)
    assert (
        store.get_admin_native_flow(pending["token_hash"], pending["binding_hash"], NOW + 3) is None
    )
    assert (
        store.get_admin_native_flow(independent["token_hash"], independent["binding_hash"], NOW + 3)
        == independent
    )


@pytest.mark.database
def test_concurrent_native_rotation_and_logout_cannot_leave_usable_transaction(store):
    pending = native_flow()
    barrier = threading.Barrier(2)

    def rotate():
        barrier.wait()
        try:
            Store(store.settings).put_admin_native_flow(pending)
        except LoginCancelledError:
            pass

    def cancel():
        barrier.wait()
        Store(store.settings).cancel_login(pending["binding_hash"], "admin", NOW + 1)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(rotate), pool.submit(cancel)]
        for future in futures:
            future.result(timeout=10)
    assert (
        store.get_admin_native_flow(pending["token_hash"], pending["binding_hash"], NOW + 2) is None
    )


@pytest.mark.database
def test_native_logout_audit_failure_rolls_back_pending_deletion_and_cancellation(
    store, monkeypatch
):
    pending = native_flow()
    store.put_admin_native_flow(pending)

    def failed_audit(*args):
        raise database.pymysql.OperationalError("PRIVATE_DATABASE_DETAIL")

    monkeypatch.setattr(store, "_audit", failed_audit)
    with pytest.raises(StoreUnavailable):
        store.cancel_login(pending["binding_hash"], "admin", NOW + 1)
    assert (
        store.get_admin_native_flow(pending["token_hash"], pending["binding_hash"], NOW + 2)
        == pending
    )
    store.put_admin_native_flow(dict(pending, token_hash=digest("after-rollback")))


@pytest.mark.database
def test_native_expiry_prunes_encrypted_pending_without_changing_oauth_or_audit(store):
    pending = native_flow()
    store.put_admin_native_flow(pending)
    oauth = {
        "state_hash": digest("customer-oauth-state"),
        "binding_hash": pending["binding_hash"],
        "area": "customer",
        "created_at": NOW,
        "expires_at": NOW + 600,
        "encrypted_payload": "encrypted-oauth-state",
    }
    store.put_flow(oauth)
    store.audit("native.test_event", detail={"area": "admin"}, now=NOW)
    assert store.cleanup(NOW + 300)["auth_admin_native_flows"] == 1
    assert (
        store.consume_flow(oauth["state_hash"], oauth["binding_hash"], "customer", NOW + 300)
        == oauth
    )
    with database.connect(store.settings) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT COUNT(*) AS total FROM auth_audit_events WHERE event='native.test_event'"
        )
        assert cursor.fetchone()["total"] == 1


@pytest.mark.database
def test_native_migration_upgrade_preserves_prior_checksums_identities_access_and_sessions(
    store, db_settings
):
    person = identity(store, "admin")
    store.grant_admin(person["id"], "owner", NOW)
    active = session(store, person, "native-before-upgrade")
    earlier = {
        version: checksum(MIGRATIONS / name)
        for version, name in ((1, "0001_auth.sql"), (2, "0002_admin_google_mfa.sql"))
    }
    with database.connect(db_settings) as connection, connection.cursor() as cursor:
        cursor.execute("DROP TABLE auth_admin_native_flows")
        cursor.execute("DELETE FROM schema_migrations WHERE version=3")
        connection.commit()
    assert not store.ready()
    assert apply_migrations(db_settings) == ["0003_admin_native_login.sql"]
    assert apply_migrations(db_settings) == []
    assert store.ready()
    assert store.find_identity(person["issuer"], person["subject"])["admin_role"] == "owner"
    assert store.get_session(active["token_hash"], "admin") is not None
    with database.connect(db_settings) as connection, connection.cursor() as cursor:
        cursor.execute("SELECT version,checksum FROM schema_migrations WHERE version IN (1,2)")
        assert {row["version"]: row["checksum"] for row in cursor.fetchall()} == earlier


@pytest.mark.database
def test_native_migration_interruption_resumes_and_readiness_requires_completion(
    store, db_settings
):
    pending = native_flow()
    store.put_admin_native_flow(pending)
    with database.connect(db_settings) as connection, connection.cursor() as cursor:
        cursor.execute("UPDATE schema_migrations SET applied_at=NULL WHERE version=3")
        connection.commit()
    assert not store.ready()
    assert apply_migrations(db_settings) == ["0003_admin_native_login.sql"]
    assert store.ready()
    assert (
        store.get_admin_native_flow(pending["token_hash"], pending["binding_hash"], NOW) == pending
    )


@pytest.mark.database
@pytest.mark.parametrize("action", ["revoke", "role", "disable"])
def test_operator_changes_fence_consumed_native_challenge_even_without_existing_session(
    store, action
):
    from app.auth.store import AccessDeniedError

    person = identity(store, "admin")
    store.grant_admin(person["id"], "staff", NOW)
    person = store.find_identity(person["issuer"], person["subject"])
    version = person["native_login_version"]
    pending = native_flow()
    store.put_admin_native_flow(pending)
    assert store.consume_admin_native_flow(pending["token_hash"], pending["binding_hash"], NOW)
    if action == "revoke":
        store.revoke_identity_sessions(person["id"], NOW + 1)
    elif action == "role":
        store.set_admin_access(person["id"], role="owner", now=NOW + 1)
    else:
        store.set_admin_access(person["id"], active=False, now=NOW + 1)
    current = store.find_identity(person["issuer"], person["subject"])
    assert current["native_login_version"] == version + 1
    candidate = {
        "token_hash": digest("late-native-session"),
        "identity_id": person["id"],
        "area": "admin",
        "created_at": NOW + 2,
        "last_seen": NOW + 2,
        "expires_at": NOW + 3600,
        "auth_time": NOW,
        "login_binding_hash": pending["binding_hash"],
        "encrypted_tokens": "encrypted-provider-tokens",
        "assurance": {
            "method": "cognito_native_challenge",
            "provider": "password",
            "challenge": "SOFTWARE_TOKEN_MFA",
            "completed_at": NOW + 2,
            "access_version": version,
        },
    }
    with pytest.raises(AccessDeniedError):
        store.create_session(candidate)
    assert store.get_session(candidate["token_hash"], "admin") is None


@pytest.mark.database
@pytest.mark.parametrize("missing_or_wrong", [None, True, -1, "1"])
def test_native_session_requires_integer_current_approval_version(store, missing_or_wrong):
    from app.auth.store import AccessDeniedError

    person = identity(store, "admin")
    store.grant_admin(person["id"], "owner", NOW)
    candidate = {
        "token_hash": digest("invalid-native-version"),
        "identity_id": person["id"],
        "area": "admin",
        "created_at": NOW,
        "last_seen": NOW,
        "expires_at": NOW + 3600,
        "auth_time": NOW,
        "encrypted_tokens": "encrypted-provider-tokens",
        "assurance": {"method": "cognito_native_challenge", "access_version": missing_or_wrong},
    }
    with pytest.raises(AccessDeniedError):
        store.create_session(candidate)


@pytest.mark.database
def test_epoch_migration_is_additive_and_resumable_without_rewriting_existing_versions(
    store, db_settings
):
    person = identity(store, "admin")
    store.grant_admin(person["id"], "owner", NOW)
    active = session(store, person, "before-epoch-upgrade")
    prior = {int(p.name[:4]): checksum(p) for p in MIGRATIONS.glob("000[123]_*.sql")}
    with database.connect(db_settings) as connection, connection.cursor() as cursor:
        cursor.execute("DROP TABLE auth_admin_login_epochs")
        cursor.execute("DELETE FROM schema_migrations WHERE version=4")
        connection.commit()
    assert not store.ready()
    assert apply_migrations(db_settings) == ["0004_admin_login_epochs.sql"]
    assert store.ready()
    assert store.get_session(active["token_hash"], "admin") is not None
    assert store.find_identity(person["issuer"], person["subject"])["admin_role"] == "owner"
    with database.connect(db_settings) as connection, connection.cursor() as cursor:
        cursor.execute("SELECT version,checksum FROM schema_migrations WHERE version<4")
        assert {r["version"]: r["checksum"] for r in cursor.fetchall()} == prior
        cursor.execute("UPDATE schema_migrations SET applied_at=NULL WHERE version=4")
        connection.commit()
    assert not store.ready()
    assert apply_migrations(db_settings) == ["0004_admin_login_epochs.sql"]
    assert apply_migrations(db_settings) == []
