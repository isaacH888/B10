"""Private lifecycle commands use mocked AWS and storage, never a live pool."""

import logging

import pytest
from flask import Flask

from app.auth.admin_cli import register_admin_commands


ISSUER = "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_Admin123"
ARN = "arn:aws:sts::123456789012:assumed-role/popsibilities-operator/test-session"
EMAIL = "approved@example.invalid"


class FakeStore:
    def __init__(self, events):
        self.events = events
        self.records = []
        self.owner_count = 0
        self.policy_error = False

    def audit(self, event, **data):
        self.events.append(("audit", event, data))

    def find_identity_by_email(self, email, area="admin"):
        return [record for record in self.records if record["email"] == email and record["area"] == area]

    def count_active_owners(self, issuer):
        return self.owner_count

    def upsert_identity(self, issuer, subject, area, email, name, now):
        record = dict(id=len(self.records) + 1, issuer=issuer, subject=subject, area=area,
                      email=email, name=name, admin_active=True, admin_role=None)
        self.records.append(record)
        self.events.append(("upsert", record.copy()))
        return record

    def grant_admin(self, identity_id, role, now, bootstrap=False):
        self.events.append(("grant", identity_id, role, bootstrap))
        if self.policy_error:
            raise ValueError("protected database diagnostic")
        self.records[identity_id - 1]["admin_role"] = role

    def set_admin_access(self, identity_id, role=None, active=None, now=None):
        if self.policy_error:
            raise ValueError("final active owner")
        self.events.append(("local_access", identity_id, role, active))

    def revoke_identity_sessions(self, identity_id, now):
        self.events.append(("local_revoke", identity_id))
        return 1

    def admin_provider_identities(self, canonical_id):
        return [record for record in self.records
                if record.get("canonical_identity_id", record["id"]) == canonical_id]



class FakeProvider:
    def __init__(self, events):
        self.events = events
        self.failure = None
        self.response_email = EMAIL

    def _call(self, name, arguments):
        self.events.append((name, arguments))
        if name == self.failure:
            raise RuntimeError("SecretFromProviderError protected@example.invalid")

    def admin_create_user(self, **arguments):
        self._call("create", arguments)
        return {"User": {"Attributes": [{"Name": "sub", "Value": "provider-subject"},
                                        {"Name": "email", "Value": self.response_email}]}}

    def admin_user_global_sign_out(self, **arguments):
        self._call("global_signout", arguments)

    def admin_disable_user(self, **arguments):
        self._call("disable", arguments)

    def admin_delete_software_token(self, **arguments):
        self._call("delete_totp", arguments)

    def admin_set_user_password(self, **arguments):
        self._call("password", arguments)



@pytest.fixture
def operator_app():
    app = Flask(__name__)
    app.config.update(TESTING=True, AUTH_ENABLED=False, COGNITO_ADMIN_ISSUER=ISSUER)
    events = []
    store, provider = FakeStore(events), FakeProvider(events)

    class STS:
        def get_caller_identity(self):
            events.append(("caller",))
            return {"Arn": ARN}

    def factory(service, region):
        assert region == "us-east-1"
        return provider if service == "cognito-idp" else STS()

    app.extensions["auth_store"] = store
    app.extensions["auth_admin_client_factory"] = factory
    register_admin_commands(app)
    return app, store, provider, events


def run(fixture, command, *options, input=None):
    return fixture[0].test_cli_runner().invoke(args=["auth", command, *options], input=input)


def existing(fixture, issuer=ISSUER, active=True):
    store = fixture[1]
    record = store.upsert_identity(issuer, "provider-subject", "admin", EMAIL, "Approved Person", 1)
    record.update(admin_role="staff", admin_active=active)
    fixture[3].clear()
    return record


def event_names(fixture):
    return [event[0] for event in fixture[3] if event[0] != "audit"]


@pytest.mark.parametrize("command", ["bootstrap-owner", "invite-admin"])
def test_invitation_requires_private_email_verification(operator_app, command):
    result = run(operator_app, command, "--email", EMAIL, "--name", "Approved Person")
    assert result.exit_code != 0
    assert "--verified-out-of-band" in result.output
    assert not operator_app[3]


@pytest.mark.parametrize("command,role,bootstrap", [("bootstrap-owner", "owner", True),
                                                     ("invite-admin", "staff", False)])
def test_invitation_uses_trusted_caller_and_fixed_pool(operator_app, command, role, bootstrap):
    result = run(operator_app, command, "--email", EMAIL.upper(), "--name", "Approved Person",
                 "--verified-out-of-band")
    assert result.exit_code == 0, result.output
    assert event_names(operator_app) == ["caller", "create", "upsert", "grant"]
    arguments = next(event[1] for event in operator_app[3] if event[0] == "create")
    assert arguments["UserPoolId"] == "us-east-1_Admin123"
    assert arguments["Username"] == EMAIL
    assert arguments["ForceAliasCreation"] is False
    assert arguments["DesiredDeliveryMediums"] == ["EMAIL"]
    assert "TemporaryPassword" not in arguments
    assert {item["Name"]: item["Value"] for item in arguments["UserAttributes"]}["email_verified"] == "true"
    assert ("grant", 1, role, bootstrap) in operator_app[3]
    assert all(event[2]["detail"]["operator_arn"] == ARN for event in operator_app[3] if event[0] == "audit")


def test_existing_owner_prevents_bootstrap_before_invitation(operator_app):
    operator_app[1].owner_count = 1
    result = run(operator_app, "bootstrap-owner", "--email", EMAIL, "--name", "Approved Person", "--verified-out-of-band")
    assert result.exit_code != 0
    assert event_names(operator_app) == ["caller"]


@pytest.mark.parametrize("command", ["bootstrap-owner", "invite-admin"])
def test_historical_google_email_collision_requires_private_operator_review(operator_app, command):
    source = operator_app[1].upsert_identity(ISSUER, "google-cognito-subject", "admin", EMAIL,
                                           "Unapproved Google", 1)
    source.update(canonical_identity_id=source["id"], is_google_alias=False,
                  admin_active=False, admin_role=None)
    operator_app[3].clear()
    result = run(operator_app, command, "--email", EMAIL, "--name", "Approved Person",
                 "--verified-out-of-band")
    assert result.exit_code != 0
    assert "private operator review" in result.output
    assert "do not delete or merge" in result.output
    assert event_names(operator_app) == ["caller"]
    assert source["admin_role"] is None and source["admin_active"] is False


def test_provider_identity_mismatch_never_grants_permission(operator_app):
    operator_app[2].response_email = "unapproved@example.invalid"
    result = run(operator_app, "invite-admin", "--email", EMAIL, "--name", "Approved Person", "--verified-out-of-band")
    assert result.exit_code != 0
    assert event_names(operator_app) == ["caller", "create"]
    assert not operator_app[1].records


@pytest.mark.parametrize("issuer", ["", "https://issuer.invalid/pool", "https://cognito-idp.us-east-1.amazonaws.com:bad/us-east-1_Admin123",
                                    "https://cognito-idp.us-east-1.amazonaws.com/us-west-2_Wrong", "http://cognito-idp.us-east-1.amazonaws.com/us-east-1_Admin123"])
def test_malformed_admin_issuer_fails_before_aws(operator_app, issuer):
    operator_app[0].config["COGNITO_ADMIN_ISSUER"] = issuer
    result = run(operator_app, "revoke-admin-sessions", "--email", EMAIL)
    assert result.exit_code != 0
    assert "valid COGNITO_ADMIN_ISSUER" in result.output
    assert not operator_app[3]


def test_target_cannot_cross_user_pools(operator_app):
    existing(operator_app, issuer="https://cognito-idp.us-east-1.amazonaws.com/us-east-1_Other")
    result = run(operator_app, "disable-admin", "--email", EMAIL)
    assert result.exit_code != 0
    assert event_names(operator_app) == ["caller"]


def test_ambiguous_email_is_rejected(operator_app):
    existing(operator_app)
    other = operator_app[1].upsert_identity(ISSUER, "different-subject", "admin", EMAIL, "Other", 1)
    other.update(admin_role="owner", admin_active=True)
    operator_app[3].clear()
    result = run(operator_app, "change-role", "--email", EMAIL, "--role", "owner")
    assert result.exit_code != 0
    assert event_names(operator_app) == ["caller"]


def test_disable_invalidates_local_access_before_aws(operator_app):
    existing(operator_app)
    result = run(operator_app, "disable-admin", "--email", EMAIL)
    assert result.exit_code == 0, result.output
    assert event_names(operator_app) == ["caller", "local_access", "global_signout", "disable"]
    assert ("local_access", 1, None, False) in operator_app[3]
    for event in operator_app[3]:
        if event[0] in {"global_signout", "disable"}:
            assert event[1] == {"UserPoolId": "us-east-1_Admin123", "Username": "provider-subject"}


def test_final_owner_policy_stops_provider_mutations(operator_app):
    existing(operator_app)
    operator_app[1].policy_error = True
    result = run(operator_app, "disable-admin", "--email", EMAIL)
    assert result.exit_code != 0
    assert "Preserve an active owner" in result.output
    assert event_names(operator_app) == ["caller"]


def test_provider_failure_leaves_local_disable_and_hides_diagnostics(operator_app):
    existing(operator_app)
    operator_app[2].failure = "global_signout"
    result = run(operator_app, "disable-admin", "--email", EMAIL)
    assert result.exit_code != 0
    assert event_names(operator_app) == ["caller", "local_access", "global_signout"]
    assert "SecretFromProviderError" not in result.output
    assert "protected@example.invalid" not in result.output
    assert "admin_operator_failed" in [event[1] for event in operator_app[3] if event[0] == "audit"]


def test_recovery_requires_private_verification(operator_app):
    existing(operator_app)
    result = run(operator_app, "recover-admin", "--email", EMAIL, "--lost-mfa")
    assert result.exit_code != 0
    assert not operator_app[3]


def test_recovery_requires_action(operator_app):
    result = run(operator_app, "recover-admin", "--email", EMAIL, "--verified-out-of-band")
    assert result.exit_code != 0
    assert "Choose --lost-mfa" in result.output
    assert not operator_app[3]


def test_lost_mfa_recovery_keeps_required_pool_policy(operator_app):
    existing(operator_app)
    result = run(operator_app, "recover-admin", "--email", EMAIL, "--verified-out-of-band", "--lost-mfa")
    assert result.exit_code == 0, result.output
    assert event_names(operator_app) == ["caller", "local_revoke", "global_signout", "delete_totp"]


def test_missing_totp_reset_sdk_fails_before_session_mutation(operator_app):
    existing(operator_app)
    operator_app[2].admin_delete_software_token = None
    result = run(operator_app, "recover-admin", "--email", EMAIL, "--verified-out-of-band", "--lost-mfa")
    assert result.exit_code != 0
    assert "Upgrade the AWS SDK" in result.output
    assert event_names(operator_app) == ["caller"]


def test_disabled_identity_cannot_be_recovered(operator_app):
    existing(operator_app, active=False)
    result = run(operator_app, "recover-admin", "--email", EMAIL, "--verified-out-of-band", "--lost-mfa")
    assert result.exit_code != 0
    assert event_names(operator_app) == ["caller"]


def test_password_recovery_is_hidden_temporary_and_after_revocation(operator_app):
    existing(operator_app)
    secret = "only-in-private-prompt-93"
    result = run(operator_app, "recover-admin", "--email", EMAIL, "--verified-out-of-band", "--lost-mfa",
                 "--reset-password", input=secret + "\n" + secret + "\n")
    assert result.exit_code == 0, result.output
    assert secret not in result.output
    assert event_names(operator_app) == ["caller", "local_revoke", "global_signout", "delete_totp", "password"]
    arguments = next(event[1] for event in operator_app[3] if event[0] == "password")
    assert arguments["Password"] == secret and arguments["Permanent"] is False
    assert secret not in str([event for event in operator_app[3] if event[0] == "audit"])


def test_password_secret_cannot_be_supplied_as_argument(operator_app):
    result = run(operator_app, "recover-admin", "--email", EMAIL, "--verified-out-of-band", "--password", "unsafe")
    assert result.exit_code != 0
    assert "No such option" in result.output
    assert not operator_app[3]


def test_totp_deletion_failure_prevents_password_change(operator_app):
    existing(operator_app)
    operator_app[2].failure = "delete_totp"
    secret = "only-in-private-prompt-93"
    result = run(operator_app, "recover-admin", "--email", EMAIL, "--verified-out-of-band", "--lost-mfa",
                 "--reset-password", input=secret + "\n" + secret + "\n")
    assert result.exit_code != 0
    assert event_names(operator_app) == ["caller", "local_revoke", "global_signout", "delete_totp"]
    assert secret not in result.output


def test_manual_signout_reconciliation_revokes_local_first(operator_app):
    existing(operator_app)
    result = run(operator_app, "revoke-admin-sessions", "--email", EMAIL)
    assert result.exit_code == 0, result.output
    assert event_names(operator_app) == ["caller", "local_revoke", "global_signout"]


def test_commands_register_no_http_routes(operator_app):
    assert [rule.rule for rule in operator_app[0].url_map.iter_rules()] == ["/static/<path:filename>"]


def test_unidentified_aws_caller_cannot_mutate_local_access(operator_app):
    existing(operator_app)
    original = operator_app[0].extensions["auth_admin_client_factory"]

    class InvalidSTS:
        def get_caller_identity(self):
            return {"Arn": "untrusted-operator"}

    operator_app[0].extensions["auth_admin_client_factory"] = lambda service, region: (
        InvalidSTS() if service == "sts" else original(service, region))
    result = run(operator_app, "disable-admin", "--email", EMAIL)
    assert result.exit_code != 0
    assert "valid operator identity" in result.output
    assert not operator_app[3]


def test_aws_identity_failure_cannot_mutate_local_access(operator_app):
    existing(operator_app)
    original = operator_app[0].extensions["auth_admin_client_factory"]

    class UnavailableSTS:
        def get_caller_identity(self):
            raise RuntimeError("credential-details-must-stay-private")

    operator_app[0].extensions["auth_admin_client_factory"] = lambda service, region: (
        UnavailableSTS() if service == "sts" else original(service, region))
    result = run(operator_app, "change-role", "--email", EMAIL, "--role", "owner")
    assert result.exit_code != 0
    assert "credential-details-must-stay-private" not in result.output
    assert not operator_app[3]


def test_missing_store_fails_before_provider_call(operator_app):
    del operator_app[0].extensions["auth_store"]
    result = run(operator_app, "revoke-admin-sessions", "--email", EMAIL)
    assert result.exit_code != 0
    assert "storage is not configured" in result.output
    assert not operator_app[3]


def test_sdk_logs_cannot_record_temporary_password_and_logging_is_restored(operator_app, caplog):
    existing(operator_app)
    secret = "private-password-not-in-sdk-logs"
    original = operator_app[2].admin_set_user_password

    def verbose_sdk(**arguments):
        logging.getLogger("botocore.endpoint").debug("request-body=%s", arguments)
        logging.getLogger("operator.custom.transport").critical("password=%s", arguments["Password"])
        original(**arguments)

    operator_app[2].admin_set_user_password = verbose_sdk
    previous = logging.root.manager.disable
    with caplog.at_level(logging.DEBUG):
        result = run(operator_app, "recover-admin", "--email", EMAIL, "--verified-out-of-band",
                     "--reset-password", input=secret + "\n" + secret + "\n")
        assert result.exit_code == 0, result.output
        assert secret not in caplog.text and secret not in result.output
        assert logging.root.manager.disable == previous
        logging.getLogger("operator.custom.transport").warning("logging-restored")
        assert "logging-restored" in caplog.text


def test_sdk_logging_suppression_is_restored_on_failure(operator_app):
    existing(operator_app)
    operator_app[2].failure = "global_signout"
    previous = logging.root.manager.disable
    result = run(operator_app, "revoke-admin-sessions", "--email", EMAIL)
    assert result.exit_code != 0
    assert logging.root.manager.disable == previous


GOOGLE_UID = "108012345678901234567"


def linked_alias(fixture, issuer=ISSUER, username=None):
    record = fixture[1].upsert_identity(issuer, "google-cognito-subject", "admin", EMAIL, "Same Person", 1)
    record.update(canonical_identity_id=1, is_google_alias=True, google_subject=GOOGLE_UID,
                  provider_username=username or "google_" + GOOGLE_UID, admin_role="staff")
    fixture[3].clear()
    return record


@pytest.mark.parametrize("command", ["link-admin-google", "recover-google-mfa"])
def test_removed_google_operator_commands_cannot_approve_access(operator_app, command):
    existing(operator_app)
    result = run(operator_app, command, "--email", EMAIL, "--verified-out-of-band")
    assert result.exit_code != 0
    assert "No such command" in result.output
    assert not operator_app[3]


@pytest.mark.parametrize("command,options,expected", [
    ("disable-admin", [], ["caller", "local_access", "global_signout", "global_signout", "disable", "disable"]),
    ("change-role", ["--role", "owner"], ["caller", "local_access", "global_signout", "global_signout"]),
    ("revoke-admin-sessions", [], ["caller", "local_revoke", "global_signout", "global_signout"]),
])
def test_lifecycle_targets_canonical_and_every_linked_google_profile(operator_app, command, options, expected):
    existing(operator_app)
    linked_alias(operator_app)
    result = run(operator_app, command, "--email", EMAIL, *options)
    assert result.exit_code == 0, result.output
    assert event_names(operator_app) == expected
    calls = [event[1] for event in operator_app[3] if event[0] == "global_signout"]
    assert calls == [{"UserPoolId": "us-east-1_Admin123", "Username": "provider-subject"},
                     {"UserPoolId": "us-east-1_Admin123", "Username": "google_" + GOOGLE_UID}]


def test_native_recovery_also_revokes_linked_google_provider_sessions(operator_app):
    existing(operator_app)
    linked_alias(operator_app)
    result = run(operator_app, "recover-admin", "--email", EMAIL, "--verified-out-of-band", "--lost-mfa")
    assert result.exit_code == 0, result.output
    assert event_names(operator_app) == ["caller", "local_revoke", "global_signout", "global_signout", "delete_totp"]
    assert next(event[1] for event in operator_app[3] if event[0] == "delete_totp")["Username"] == "provider-subject"


def test_linked_profile_cannot_cross_pools_on_lifecycle(operator_app):
    existing(operator_app)
    linked_alias(operator_app, issuer="https://cognito-idp.us-east-1.amazonaws.com/us-east-1_Other")
    result = run(operator_app, "revoke-admin-sessions", "--email", EMAIL)
    assert result.exit_code != 0
    assert event_names(operator_app) == ["caller", "local_revoke"]


def test_historical_unapproved_google_profile_does_not_shadow_canonical_admin(operator_app):
    existing(operator_app)
    source = operator_app[1].upsert_identity(ISSUER, "google-cognito-subject", "admin", EMAIL, "Historical Google", 1)
    source.update(canonical_identity_id=source["id"], is_google_alias=False, admin_active=False, admin_role=None)
    operator_app[3].clear()
    result = run(operator_app, "change-role", "--email", EMAIL, "--role", "owner")
    assert result.exit_code == 0, result.output
    assert next(event for event in operator_app[3] if event[0] == "local_access")[1] == 1
