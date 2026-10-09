"""Explicit Google aliases and canonical TOTP state on disposable MySQL."""

from concurrent.futures import ThreadPoolExecutor
import threading

import pytest

from app import database
from app.auth.store import AccessDeniedError, LoginCancelledError, StoreUnavailable
from app.migrations import MIGRATIONS, apply_migrations, checksum
from test_auth_store import NOW, db_settings, digest, identity, session, store


pytestmark = pytest.mark.database


def owner(store, subject="native-owner"):
    person = identity(store, "admin", subject)
    store.grant_admin(person["id"], "owner", NOW)
    return person


def challenge(store, google=None, label="first", now=NOW, uid="google-user-123", binding=None):
    google = google or identity(store, "admin", "google-cognito-sub")
    row = {"challenge_hash": digest("challenge:" + label), "binding_hash": binding or digest("browser:" + label),
           "identity_id": google["id"], "google_subject": uid, "provider_username": "google_" + uid.lower(),
           "proof_hash": digest("proof:" + label), "created_at": now, "expires_at": now + 300,
           "encrypted_payload": "ciphertext:" + label}
    store.put_google_challenge(row)
    return row


def approve_and_enroll(store, canonical, pending, now=NOW):
    store.approve_google_link(pending["proof_hash"], canonical["id"], canonical["issuer"], now, actor_id="test-operator")
    factor = store.get_google_factor(canonical["id"])
    assert store.complete_google_mfa(pending["challenge_hash"], pending["binding_hash"], now, now // 30,
                                     factor["version"], pending["encrypted_payload"], encrypted_secret="encrypted-totp-secret")
    return store.get_google_factor(canonical["id"])


def google_session(pending, factor, now, token="google-session"):
    return {"token_hash": digest(token), "identity_id": pending["identity_id"], "area": "admin",
            "login_binding_hash": pending["binding_hash"], "created_at": now, "last_seen": now,
            "expires_at": now + 3600, "auth_time": now, "encrypted_tokens": "encrypted-google-tokens",
            "assurance": {"provider": "google", "method": "app_totp", "mfa_version": factor["version"],
                          "google_subject": pending["google_subject"], "provider_auth_time": NOW,
                          "verified_at": now}}


def test_google_pending_requires_explicit_link_and_exact_operator_proof(store):
    canonical = owner(store)
    pending = challenge(store)
    assert store.get_google_challenge(pending["challenge_hash"], digest("wrong-browser"), NOW) is None
    assert store.get_google_proof(pending["proof_hash"], "https://other-issuer", NOW) is None
    assert store.get_google_proof(pending["proof_hash"], canonical["issuer"], NOW + 300) is None
    proof = store.get_google_proof(pending["proof_hash"], canonical["issuer"], NOW)
    assert proof["provider_username"] == pending["provider_username"]
    assert "encrypted_payload" not in proof
    assert proof["admin_role"] is None
    assert not store.complete_google_mfa(pending["challenge_hash"], pending["binding_hash"], NOW,
                                        NOW // 30, 1, pending["encrypted_payload"], encrypted_secret="secret")
    store.approve_google_link(pending["proof_hash"], canonical["id"], canonical["issuer"], NOW)
    assert store.get_google_proof(pending["proof_hash"], canonical["issuer"], NOW) is None
    linked = store.get_google_challenge(pending["challenge_hash"], pending["binding_hash"], NOW)
    assert linked["canonical_identity_id"] == canonical["id"]
    assert linked["admin_role"] == "owner"
    assert linked["enrollment_challenge_hash"] == pending["challenge_hash"]
    assert linked["enrollment_expires_at"] == pending["expires_at"]


def test_link_refuses_email_auto_match_role_owner_reassignment_and_uid_collision(store):
    canonical = owner(store)
    another = owner(store, "other-owner")
    with pytest.raises(AccessDeniedError):
        challenge(store, canonical, label="native-role")
    pending = challenge(store)
    store.approve_google_link(pending["proof_hash"], canonical["id"], canonical["issuer"], NOW)
    alias = store.find_identity(canonical["issuer"], "google-cognito-sub")
    assert alias["canonical_identity_id"] == canonical["id"]
    assert alias["is_google_alias"] == 1
    with pytest.raises(AccessDeniedError):
        session(store, alias)
    with pytest.raises(ValueError, match="administrator identity"):
        store.grant_admin(alias["id"], "owner", NOW)
    second = challenge(store, alias, label="reassign")
    with pytest.raises(ValueError, match="reassigned"):
        store.approve_google_link(second["proof_hash"], another["id"], canonical["issuer"], NOW)
    duplicate_source = identity(store, "admin", "different-google-cognito-sub")
    duplicate = challenge(store, duplicate_source, label="duplicate-uid")
    with pytest.raises(ValueError, match="reassigned"):
        store.approve_google_link(duplicate["proof_hash"], another["id"], canonical["issuer"], NOW)


def test_enrollment_is_bound_to_exact_approved_proof_and_payload_version(store):
    canonical = owner(store)
    approved = challenge(store)
    store.approve_google_link(approved["proof_hash"], canonical["id"], canonical["issuer"], NOW)
    alias = store.find_identity(canonical["issuer"], "google-cognito-sub")
    fresh = challenge(store, alias, label="not-approved")
    assert not store.complete_google_mfa(fresh["challenge_hash"], fresh["binding_hash"], NOW, NOW // 30,
                                        1, fresh["encrypted_payload"], encrypted_secret="secret")
    assert not store.complete_google_mfa(approved["challenge_hash"], approved["binding_hash"], NOW, NOW // 30,
                                        2, approved["encrypted_payload"], encrypted_secret="secret")
    assert not store.complete_google_mfa(approved["challenge_hash"], approved["binding_hash"], NOW, NOW // 30,
                                        1, "wrong-payload", encrypted_secret="secret")
    assert store.set_google_challenge_payload(approved["challenge_hash"], approved["binding_hash"], approved["encrypted_payload"], "enrollment-ciphertext", NOW)
    assert not store.set_google_challenge_payload(approved["challenge_hash"], approved["binding_hash"], approved["encrypted_payload"], "stale-overwrite", NOW)
    assert store.complete_google_mfa(approved["challenge_hash"], approved["binding_hash"], NOW, NOW // 30,
                                   1, "enrollment-ciphertext", encrypted_secret="secret")
    factor = store.get_google_factor(canonical["id"])
    assert factor["enrollment_challenge_hash"] is None
    assert factor["encrypted_secret"] == "secret"
    assert not store.complete_google_mfa(approved["challenge_hash"], approved["binding_hash"], NOW, NOW // 30,
                                        1, "enrollment-ciphertext", encrypted_secret="secret")


def test_google_login_counter_replay_and_alias_session_metadata(store):
    canonical = owner(store)
    enrollment = challenge(store)
    factor = approve_and_enroll(store, canonical, enrollment)
    alias = store.find_identity(canonical["issuer"], "google-cognito-sub")
    pending = challenge(store, alias, label="login", now=NOW + 30)
    row = google_session(pending, factor, NOW + 30)
    assert store.complete_google_mfa(pending["challenge_hash"], pending["binding_hash"], NOW + 30,
                                   (NOW + 30) // 30, factor["version"], pending["encrypted_payload"], session=row)
    stored = store.get_session(row["token_hash"], "admin")
    assert stored["identity_id"] == alias["id"]
    assert stored["canonical_identity_id"] == canonical["id"]
    assert stored["mfa_version"] == factor["version"]
    assert stored["admin_role"] == "owner"
    assert stored["google_subject"] == pending["google_subject"]
    replay = challenge(store, alias, label="replay", now=NOW + 30)
    assert not store.complete_google_mfa(replay["challenge_hash"], replay["binding_hash"], NOW + 30,
                                        (NOW + 30) // 30, factor["version"], replay["encrypted_payload"], session=google_session(replay, factor, NOW + 30, "replay-session"))


def test_attempt_limit_and_expiry_delete_google_pending_tokens(store):
    pending = challenge(store)
    assert not store.fail_google_challenge(pending["challenge_hash"], digest("other-browser"), NOW)
    for _ in range(5):
        assert store.fail_google_challenge(pending["challenge_hash"], pending["binding_hash"], NOW)
    assert not store.fail_google_challenge(pending["challenge_hash"], pending["binding_hash"], NOW)
    assert store.get_google_challenge(pending["challenge_hash"], pending["binding_hash"], NOW) is None
    fresh = challenge(store, label="expires")
    assert store.get_google_challenge(fresh["challenge_hash"], fresh["binding_hash"], NOW + 300) is None
    assert store.cleanup(NOW + 300)["auth_admin_google_challenges"] == 1


def test_recovery_requires_existing_uid_resets_version_and_revokes_both_methods(store):
    canonical = owner(store)
    enrollment = challenge(store)
    factor = approve_and_enroll(store, canonical, enrollment)
    native = session(store, canonical, "native-session")
    alias = store.find_identity(canonical["issuer"], "google-cognito-sub")
    login = challenge(store, alias, label="login", now=NOW + 30)
    row = google_session(login, factor, NOW + 30)
    assert store.complete_google_mfa(login["challenge_hash"], login["binding_hash"], NOW + 30,
                                   (NOW + 30) // 30, factor["version"], login["encrypted_payload"], session=row)
    obsolete = challenge(store, alias, label="obsolete", now=NOW + 31)
    recovery = challenge(store, alias, label="recovery", now=NOW + 31)
    with pytest.raises(ValueError, match="recovery command"):
        store.approve_google_link(recovery["proof_hash"], canonical["id"], canonical["issuer"], NOW + 31)
    store.recover_google_factor(recovery["proof_hash"], canonical["id"], canonical["issuer"], NOW + 31)
    renewed = store.get_google_factor(canonical["id"])
    assert renewed["version"] == factor["version"] + 1
    assert renewed["encrypted_secret"] is None
    assert renewed["enrollment_challenge_hash"] == recovery["challenge_hash"]
    assert store.get_google_challenge(obsolete["challenge_hash"], obsolete["binding_hash"], NOW + 31) is None
    assert store.get_google_challenge(recovery["challenge_hash"], recovery["binding_hash"], NOW + 31) is not None
    assert store.get_session(native["token_hash"], "admin") is None
    assert store.get_session(row["token_hash"], "admin") is None
    assert not store.complete_google_mfa(recovery["challenge_hash"], recovery["binding_hash"], NOW + 31,
                                        (NOW + 31) // 30, factor["version"], recovery["encrypted_payload"], encrypted_secret="stale-secret")


def test_role_change_and_disable_invalidate_alias_sessions_and_pending(store):
    canonical = owner(store)
    owner(store, "second-owner")
    enrollment = challenge(store)
    factor = approve_and_enroll(store, canonical, enrollment)
    alias = store.find_identity(canonical["issuer"], "google-cognito-sub")
    login = challenge(store, alias, label="login", now=NOW + 30)
    row = google_session(login, factor, NOW + 30)
    assert store.complete_google_mfa(login["challenge_hash"], login["binding_hash"], NOW + 30,
                                   (NOW + 30) // 30, factor["version"], login["encrypted_payload"], session=row)
    waiting = challenge(store, alias, label="waiting", now=NOW + 31)
    store.set_admin_access(canonical["id"], role="staff", now=NOW + 31)
    assert store.get_session(row["token_hash"], "admin") is None
    assert store.get_google_challenge(waiting["challenge_hash"], waiting["binding_hash"], NOW + 31) is None
    assert store.find_identity(canonical["issuer"], alias["subject"])["admin_role"] == "staff"
    store.set_admin_access(canonical["id"], active=False, now=NOW + 32)
    with pytest.raises(AccessDeniedError):
        challenge(store, alias, label="disabled", now=NOW + 32)


def test_google_completion_race_accepts_only_one_same_counter(store):
    canonical = owner(store)
    enrollment = challenge(store)
    factor = approve_and_enroll(store, canonical, enrollment)
    alias = store.find_identity(canonical["issuer"], "google-cognito-sub")
    waiting = [challenge(store, alias, label="race-" + str(i), now=NOW + 30) for i in range(2)]
    barrier = threading.Barrier(2)

    def complete(pending):
        barrier.wait()
        return store.complete_google_mfa(pending["challenge_hash"], pending["binding_hash"], NOW + 30,
                                         (NOW + 30) // 30, factor["version"], pending["encrypted_payload"],
                                         session=google_session(pending, factor, NOW + 30, "session-" + pending["challenge_hash"]))

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(complete, waiting)) == 1


def test_pending_google_logout_cancellation_and_provider_targets(store):
    canonical = owner(store)
    pending = challenge(store)
    store.approve_google_link(pending["proof_hash"], canonical["id"], canonical["issuer"], NOW)
    identities = store.admin_provider_identities(canonical["id"])
    assert {record["provider_username"] for record in identities} == {canonical["subject"], pending["provider_username"]}
    store.cancel_login(pending["binding_hash"], "admin", NOW + 1)
    assert store.get_google_challenge(pending["challenge_hash"], pending["binding_hash"], NOW + 1) is None
    with pytest.raises(LoginCancelledError):
        challenge(store, label="canceled-new", binding=pending["binding_hash"], now=NOW + 2)


def test_google_factor_completion_audit_failure_is_atomic(store, monkeypatch):
    canonical = owner(store)
    enrollment = challenge(store)
    store.approve_google_link(enrollment["proof_hash"], canonical["id"], canonical["issuer"], NOW)

    def fail_audit(*args):
        raise database.pymysql.OperationalError("PRIVATE_DATABASE_DETAIL")

    monkeypatch.setattr(store, "_audit", fail_audit)
    with pytest.raises(StoreUnavailable):
        store.complete_google_mfa(enrollment["challenge_hash"], enrollment["binding_hash"], NOW,
                                  NOW // 30, 1, enrollment["encrypted_payload"], encrypted_secret="encrypted-secret")
    assert store.get_google_factor(canonical["id"])["encrypted_secret"] is None
    assert store.get_google_challenge(enrollment["challenge_hash"], enrollment["binding_hash"], NOW) is not None


def test_0002_migration_preserves_0001_history_and_readiness_checks_both(store, db_settings, tmp_path):
    initial_checksum = checksum(MIGRATIONS / "0001_auth.sql")
    with database.connect(db_settings) as connection, connection.cursor() as cursor:
        cursor.execute("SELECT version,checksum FROM schema_migrations ORDER BY version")
        history = cursor.fetchall()
        assert history[0] == {"version": 1, "checksum": initial_checksum}
        assert history[1]["version"] == 2
        cursor.execute("UPDATE schema_migrations SET applied_at=NULL WHERE version=2")
        connection.commit()
    assert not store.ready()
    assert apply_migrations(db_settings) == ["0002_admin_google_mfa.sql"]
    assert store.ready()


def test_upgrade_from_0001_keeps_native_identity_access_and_session(store, db_settings):
    canonical = owner(store)
    native = session(store, canonical, "native-session-before-upgrade")
    with database.connect(db_settings) as connection, connection.cursor() as cursor:
        for table in ("auth_admin_google_challenges", "auth_admin_totp", "auth_admin_google_links"):
            cursor.execute("DROP TABLE " + table)
        cursor.execute("DELETE FROM schema_migrations WHERE version=2")
        connection.commit()
    assert not store.ready()
    assert apply_migrations(db_settings) == ["0002_admin_google_mfa.sql"]
    assert store.ready()
    assert store.find_identity(canonical["issuer"], canonical["subject"])["id"] == canonical["id"]
    assert store.get_session(native["token_hash"], "admin")["admin_role"] == "owner"


def test_new_proof_reauthorizes_only_unenrolled_factor_and_replaces_old_pending(store):
    canonical = owner(store)
    initial = challenge(store)
    store.approve_google_link(initial["proof_hash"], canonical["id"], canonical["issuer"], NOW)
    alias = store.find_identity(canonical["issuer"], "google-cognito-sub")
    fresh = challenge(store, alias, label="new-approval", now=NOW + 1)
    store.approve_google_link(fresh["proof_hash"], canonical["id"], canonical["issuer"], NOW + 1)
    factor = store.get_google_factor(canonical["id"])
    assert factor["version"] == 1
    assert factor["enrollment_challenge_hash"] == fresh["challenge_hash"]
    assert store.get_google_challenge(initial["challenge_hash"], initial["binding_hash"], NOW + 1) is None
    assert store.complete_google_mfa(fresh["challenge_hash"], fresh["binding_hash"], NOW + 1,
                                   (NOW + 1) // 30, 1, fresh["encrypted_payload"], encrypted_secret="encrypted-secret")
    later = challenge(store, alias, label="already-enrolled", now=NOW + 2)
    with pytest.raises(ValueError, match="recovery command"):
        store.approve_google_link(later["proof_hash"], canonical["id"], canonical["issuer"], NOW + 2)


def test_google_proof_cannot_approve_disabled_target_or_wrong_issuer(store):
    canonical = owner(store)
    owner(store, "second-owner")
    pending = challenge(store)
    with pytest.raises(ValueError, match="exact Google identity proof"):
        store.approve_google_link(pending["proof_hash"], canonical["id"], "https://wrong-issuer", NOW)
    store.set_admin_access(canonical["id"], active=False, now=NOW)
    with pytest.raises(ValueError, match="active canonical"):
        store.approve_google_link(pending["proof_hash"], canonical["id"], canonical["issuer"], NOW)


def test_exact_google_uid_binding_and_case_insensitive_provider_username(store):
    canonical = owner(store)
    pending = challenge(store, uid="MixedCaseUID")
    assert pending["provider_username"] == "google_mixedcaseuid"
    store.approve_google_link(pending["proof_hash"], canonical["id"], canonical["issuer"], NOW)
    alias = store.find_identity(canonical["issuer"], "google-cognito-sub")
    assert alias["google_subject"] == "MixedCaseUID"
    with pytest.raises(AccessDeniedError):
        challenge(store, alias, label="wrong-external-subject", uid="mixedcaseuid")


def test_concurrent_enrollment_consumes_exact_proof_only_once(store):
    canonical = owner(store)
    pending = challenge(store)
    store.approve_google_link(pending["proof_hash"], canonical["id"], canonical["issuer"], NOW)
    barrier = threading.Barrier(2)

    def enroll(_):
        barrier.wait()
        return store.complete_google_mfa(pending["challenge_hash"], pending["binding_hash"], NOW,
                                         NOW // 30, 1, pending["encrypted_payload"], encrypted_secret="encrypted-secret")

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(enroll, range(2))) == 1
    assert store.get_google_factor(canonical["id"])["last_counter"] == NOW // 30


def test_recovery_race_cannot_leave_old_version_google_session_active(store):
    canonical = owner(store)
    factor = approve_and_enroll(store, canonical, challenge(store))
    alias = store.find_identity(canonical["issuer"], "google-cognito-sub")
    pending = challenge(store, alias, label="racing-login", now=NOW + 30)
    recovery = challenge(store, alias, label="racing-recovery", now=NOW + 30)
    row = google_session(pending, factor, NOW + 30)
    barrier = threading.Barrier(2)

    def complete():
        barrier.wait()
        return store.complete_google_mfa(pending["challenge_hash"], pending["binding_hash"], NOW + 30,
                                         (NOW + 30) // 30, factor["version"], pending["encrypted_payload"], session=row)

    def recover():
        barrier.wait()
        store.recover_google_factor(recovery["proof_hash"], canonical["id"], canonical["issuer"], NOW + 30)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(complete), pool.submit(recover)]
        for future in futures:
            future.result(timeout=5)
    assert store.get_session(row["token_hash"], "admin") is None
    assert store.get_google_factor(canonical["id"])["version"] == factor["version"] + 1
    assert store.get_google_challenge(recovery["challenge_hash"], recovery["binding_hash"], NOW + 30) is not None


def test_disable_race_cannot_leave_google_session_active(store):
    canonical = owner(store)
    owner(store, "other-owner")
    factor = approve_and_enroll(store, canonical, challenge(store))
    alias = store.find_identity(canonical["issuer"], "google-cognito-sub")
    pending = challenge(store, alias, label="racing-login", now=NOW + 30)
    row = google_session(pending, factor, NOW + 30)
    barrier = threading.Barrier(2)

    def complete():
        barrier.wait()
        return store.complete_google_mfa(pending["challenge_hash"], pending["binding_hash"], NOW + 30,
                                         (NOW + 30) // 30, factor["version"], pending["encrypted_payload"], session=row)

    def disable():
        barrier.wait()
        store.set_admin_access(canonical["id"], active=False, now=NOW + 30)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(complete), pool.submit(disable)]
        for future in futures:
            future.result(timeout=5)
    assert store.get_session(row["token_hash"], "admin") is None
    assert store.get_google_challenge(pending["challenge_hash"], pending["binding_hash"], NOW + 30) is None
