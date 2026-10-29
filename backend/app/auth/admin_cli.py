"""Private operator commands. These are never exposed as HTTP endpoints."""

import logging
import re
import time
from contextlib import contextmanager
from dataclasses import dataclass
from urllib.parse import urlsplit

import click
from botocore.exceptions import ClientError
from flask import current_app
from flask.cli import with_appcontext


@dataclass
class Operator:
    store: object
    provider: object
    issuer: str
    pool_id: str
    arn: str

    def audit(self, event, identity=None, **detail):
        self.store.audit(
            event,
            identity_id=identity and identity["id"],
            detail={"operator_arn": self.arn, **detail},
            now=int(time.time()),
        )


def _pool_from_issuer(issuer):
    message = "Configure a valid COGNITO_ADMIN_ISSUER before using operator commands."
    try:
        parsed = urlsplit(issuer)
        port = parsed.port
    except (TypeError, ValueError):
        raise click.ClickException(message) from None
    match = re.fullmatch(
        r"cognito-idp\.([a-z0-9-]+)\.amazonaws\.com(?:\.cn)?", parsed.hostname or ""
    )
    pool = parsed.path.removeprefix("/")
    if (
        parsed.scheme != "https"
        or not match
        or parsed.username
        or parsed.password
        or port
        or parsed.query
        or parsed.fragment
        or not re.fullmatch(r"[a-z0-9-]+_[A-Za-z0-9]+", pool)
        or pool.split("_", 1)[0] != match.group(1)
    ):
        raise click.ClickException(message)
    return match.group(1), pool


@contextmanager
def _operator(command):
    """Identify the IAM caller before touching provider or local account state."""
    store = current_app.extensions.get("auth_store")
    if store is None:
        raise click.ClickException("Authentication storage is not configured.")
    issuer = current_app.config.get("COGNITO_ADMIN_ISSUER", "")
    region, pool_id = _pool_from_issuer(issuer)
    operator = None
    # boto3/botocore debug records can contain request bodies, including the
    # temporary password. This command runs in a dedicated operator process;
    # silence logging during its sensitive operations and restore it afterward.
    previous_logging_disable = logging.root.manager.disable
    logging.disable(max(previous_logging_disable, logging.CRITICAL))
    try:
        factory = current_app.extensions.get("auth_admin_client_factory")
        if factory is None:
            import boto3

            def factory(service, region):
                return boto3.client(service, region_name=region)

        provider = factory("cognito-idp", region)
        arn = factory("sts", region).get_caller_identity()["Arn"]
        if not re.fullmatch(r"arn:aws(?:-us-gov|-cn)?:[a-z0-9-]+::[0-9]{12}:.+", arn):
            raise click.ClickException("AWS did not return a valid operator identity.")
        operator = Operator(store, provider, issuer, pool_id, arn)
        operator.audit("admin_operator_started", command=command)
        yield operator
    except click.ClickException:
        raise
    except ValueError:
        raise click.ClickException(
            "Account policy rejected the operation. Preserve an active owner and check the target account."
        ) from None
    except Exception:
        # Provider exceptions can contain email addresses and supplied credentials.
        # Never echo or log their text, or whole SDK responses.
        if operator is not None:
            try:
                operator.audit("admin_operator_failed", command=command)
            except Exception:
                pass
        raise click.ClickException(
            "Operation failed. Inspect protected audit records; credentials and provider details are withheld. Access is not restored automatically."
        ) from None
    finally:
        logging.disable(previous_logging_disable)


def _email(value):
    value = value.strip().lower()
    if len(value) > 254 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
        raise click.ClickException("Supply a valid email address.")
    return value


def _target(operator, email):
    records = operator.store.find_identity_by_email(_email(email), area="admin")
    records = [
        record
        for record in records
        if record["issuer"] == operator.issuer
        and record.get("area") == "admin"
        and record.get("admin_role") in {"owner", "staff"}
        and record.get("canonical_identity_id", record["id"]) == record["id"]
        and not record.get("is_google_alias")
    ]
    if len(records) != 1:
        raise click.ClickException(
            "The configured admin pool must have exactly one matching local account."
        )
    return records[0]


def _provider_identities(operator, identity):
    profiles = operator.store.admin_provider_identities(identity["id"])
    if not profiles or not any(
        profile.get("subject") == identity["subject"] for profile in profiles
    ):
        raise click.ClickException("The canonical admin provider identity is unavailable.")
    for profile in profiles:
        if (
            profile.get("issuer") != operator.issuer
            or profile.get("area") != "admin"
            or not isinstance(profile.get("subject"), str)
            or not profile["subject"]
        ):
            raise click.ClickException(
                "Linked identities must belong to the configured admin pool."
            )
        username = profile.get("provider_username") or profile["subject"]
        google_subject = profile.get("google_subject")
        if google_subject is not None:
            if (
                not isinstance(google_subject, str)
                or not google_subject
                or username not in {"Google_" + google_subject, "google_" + google_subject.lower()}
            ):
                raise click.ClickException("A linked Google provider identity is invalid.")
        elif username != profile["subject"]:
            raise click.ClickException("The native admin provider identity is invalid.")
    return profiles


def _revoke_provider(operator, identity, profiles=None):
    for profile in profiles if profiles is not None else _provider_identities(operator, identity):
        operator.provider.admin_user_global_sign_out(
            UserPoolId=operator.pool_id,
            Username=profile.get("provider_username") or profile["subject"],
        )


def _delete_lost_factor(operator, identity):
    try:
        operator.provider.admin_delete_software_token(
            UserPoolId=operator.pool_id, Username=identity["subject"]
        )
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") != "ResourceNotFoundException":
            raise
        # AWS also returns ResourceNotFound when a prior recovery already
        # removed TOTP. Confirm the exact user still exists before resuming.
        user = operator.provider.admin_get_user(
            UserPoolId=operator.pool_id, Username=identity["subject"]
        )
        attributes = {item["Name"]: item["Value"] for item in user.get("UserAttributes", [])}
        if (
            attributes.get("sub") != identity["subject"]
            or not user.get("Enabled")
            or "SOFTWARE_TOKEN_MFA" in user.get("UserMFASettingList", [])
        ):
            raise click.ClickException(
                "Recovery state could not be verified. Access remains blocked."
            ) from None


def _provision(operator, email, name, role, bootstrap=False):
    email = _email(email)
    name = name.strip()
    if not name or len(name) > 150:
        raise click.ClickException("Supply a name of 1-150 characters.")
    if operator.store.find_identity_by_email(email, area="admin"):
        raise click.ClickException(
            "An admin identity already exists locally. Use lifecycle commands for approved accounts; an unapproved historical provider profile requires private operator review; do not delete or merge it automatically."
        )
    if bootstrap and operator.store.count_active_owners(operator.issuer):
        raise click.ClickException("An active owner already exists. Use invite-admin instead.")
    # Cognito generates and delivers the temporary password; no password is
    # returned to the terminal, accepted as an argument, or recorded locally.
    response = operator.provider.admin_create_user(
        UserPoolId=operator.pool_id,
        Username=email,
        DesiredDeliveryMediums=["EMAIL"],
        ForceAliasCreation=False,
        UserAttributes=[
            {"Name": "email", "Value": email},
            {"Name": "email_verified", "Value": "true"},
            {"Name": "name", "Value": name},
        ],
    )
    attributes = {item["Name"]: item["Value"] for item in response["User"]["Attributes"]}
    subject = attributes.get("sub")
    if not subject or attributes.get("email", "").lower() != email:
        raise click.ClickException(
            "The provider response did not match the requested identity. No local permission was granted."
        )
    now = int(time.time())
    identity = operator.store.upsert_identity(operator.issuer, subject, "admin", email, name, now)
    operator.store.grant_admin(identity["id"], role, now, bootstrap=bootstrap)
    operator.audit("admin_invited", identity, role=role, bootstrap=bootstrap)


@click.group("auth")
def auth_commands():
    """Privileged account provisioning and recovery; run in a private operator environment."""


@auth_commands.command("bootstrap-owner")
@click.option("--email", required=True)
@click.option("--name", required=True)
@click.option(
    "--verified-out-of-band",
    is_flag=True,
    help="Confirm identity and ownership of the approved email address.",
)
@with_appcontext
def bootstrap_owner(email, name, verified_out_of_band):
    """Invite the first owner; repeat bootstrap is rejected atomically."""
    if not verified_out_of_band:
        raise click.ClickException(
            "Verify the approved email owner privately and supply --verified-out-of-band."
        )
    with _operator("bootstrap-owner") as operator:
        _provision(operator, email, name, "owner", bootstrap=True)
    click.echo(
        "Owner invitation requested. Complete password setup and TOTP authentication before dashboard access."
    )


@auth_commands.command("invite-admin")
@click.option("--email", required=True)
@click.option("--name", required=True)
@click.option("--role", type=click.Choice(["owner", "staff"]), default="staff", show_default=True)
@click.option(
    "--verified-out-of-band",
    is_flag=True,
    help="Confirm identity and ownership of the approved email address.",
)
@with_appcontext
def invite_admin(email, name, role, verified_out_of_band):
    """Invite an authorized owner or staff member without public registration."""
    if not verified_out_of_band:
        raise click.ClickException(
            "Verify the approved email owner privately and supply --verified-out-of-band."
        )
    with _operator("invite-admin") as operator:
        _provision(operator, email, name, role)
    click.echo(
        "Admin invitation requested. Complete password setup and TOTP authentication before dashboard access."
    )


@auth_commands.command("change-role")
@click.option("--email", required=True)
@click.option("--role", type=click.Choice(["owner", "staff"]), required=True)
@with_appcontext
def change_role(email, role):
    """Change local permissions and invalidate all existing sessions."""
    with _operator("change-role") as operator:
        identity = _target(operator, email)
        operator.store.set_admin_access(identity["id"], role=role, now=int(time.time()))
        _revoke_provider(operator, identity)
        operator.audit("admin_role_changed_by_operator", identity, role=role)
    click.echo(
        "Role changed. Existing sessions were invalidated; fresh authentication is required."
    )


@auth_commands.command("disable-admin")
@click.option("--email", required=True)
@with_appcontext
def disable_admin(email):
    """Disable locally before revoking and disabling the provider identity."""
    with _operator("disable-admin") as operator:
        identity = _target(operator, email)
        operator.store.set_admin_access(identity["id"], active=False, now=int(time.time()))
        profiles = _provider_identities(operator, identity)
        _revoke_provider(operator, identity, profiles)
        for profile in profiles:
            operator.provider.admin_disable_user(
                UserPoolId=operator.pool_id,
                Username=profile.get("provider_username") or profile["subject"],
            )
        operator.audit("admin_disabled_by_operator", identity)
    click.echo("Admin disabled. Existing sessions were invalidated.")


@auth_commands.command("revoke-admin-sessions")
@click.option("--email", required=True)
@with_appcontext
def revoke_admin_sessions(email):
    """Reconcile admin sign-out after a provider-revocation failure."""
    with _operator("revoke-admin-sessions") as operator:
        identity = _target(operator, email)
        operator.store.revoke_identity_sessions(identity["id"], int(time.time()))
        _revoke_provider(operator, identity)
        operator.audit("admin_sessions_revoked_by_operator", identity)
    click.echo("All admin sessions were invalidated locally and at the provider.")


@auth_commands.command("recover-admin")
@click.option("--email", required=True)
@click.option(
    "--verified-out-of-band",
    is_flag=True,
    help="Confirm the documented private identity verification was completed.",
)
@click.option(
    "--lost-mfa",
    is_flag=True,
    help="Replace the password and lost TOTP registration through verified private recovery.",
)
@click.option(
    "--reset-password",
    is_flag=True,
    help="Prompt privately for a temporary password; never supply it as an argument.",
)
@with_appcontext
def recover_admin(email, verified_out_of_band, lost_mfa, reset_password):
    """Recover verified users while retaining mandatory pool MFA."""
    if not verified_out_of_band:
        raise click.ClickException(
            "Complete private identity verification and supply --verified-out-of-band."
        )
    if not lost_mfa and not reset_password:
        raise click.ClickException("Choose --lost-mfa, --reset-password, or both.")
    # A stolen old password must never authorize enrollment of the replacement
    # factor. Lost-factor recovery always replaces that credential first.
    reset_password = reset_password or lost_mfa
    temporary_password = None
    if reset_password:
        temporary_password = click.prompt(
            "Temporary password for verified private delivery",
            hide_input=True,
            confirmation_prompt=True,
        )
        if not 16 <= len(temporary_password) <= 256 or any(
            char.isspace() for char in temporary_password
        ):
            raise click.ClickException(
                "Use a temporary password of 16–256 characters without whitespace."
            )
    with _operator("recover-admin") as operator:
        identity = _target(operator, email)
        if not identity.get("admin_active"):
            raise click.ClickException("A disabled admin cannot be recovered by this command.")
        if lost_mfa and not callable(
            getattr(operator.provider, "admin_delete_software_token", None)
        ):
            raise click.ClickException(
                "Upgrade the AWS SDK: AdminDeleteSoftwareToken is required. Pool MFA remains required."
            )
        with operator.store.admin_recovery(identity["id"], int(time.time())):
            _revoke_provider(operator, identity)
            operator.provider.admin_set_user_password(
                UserPoolId=operator.pool_id,
                Username=identity["subject"],
                Password=temporary_password,
                Permanent=False,
            )
            if lost_mfa:
                _delete_lost_factor(operator, identity)
            _revoke_provider(operator, identity)
        operator.audit(
            "admin_recovered_by_operator",
            identity,
            lost_mfa=lost_mfa,
            password_reset=reset_password,
            verification="out_of_band",
        )
    temporary_password = None
    click.echo(
        "Recovery completed. Existing sessions remain invalid; complete fresh password/TOTP authentication."
    )


def register_admin_commands(app):
    app.cli.add_command(auth_commands)
