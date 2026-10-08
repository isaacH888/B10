# Private administrator operations

Run the `auth` Flask command group in a dedicated trusted operator process with the backend configuration, access to the authentication database, and separately authenticated AWS operator credentials. These commands are not HTTP endpoints. The web runtime must not receive the IAM managed policy produced by the authentication stack. The AWS caller ARN from `GetCallerIdentity` is recorded in protected local audit events before any lifecycle mutation; raw provider errors, passwords, tokens, and client secrets are withheld from terminal output. Standard logging is temporarily silenced while privileged provider/database operations run so verbose SDK request logging cannot record credentials. Audit records are written directly to the database; logging configuration is restored when the command completes or fails.

The configured `COGNITO_ADMIN_ISSUER` fixes the region and user pool for every command. The CLI accepts neither a pool override nor a subject supplied by the caller. Existing-account commands resolve exactly one local admin identity in that issuer by email, then address Cognito using its recorded subject. The local grant and active status remain authoritative for dashboard access. Changing the target's email directly in Cognito requires reconciling the local identity through a successful login or a separately reviewed maintenance procedure.

Before inviting or recovering anyone, verify the approved person's identity and ownership of the intended email address through a known private contact method. Follow the organization's independent approval procedure; a request from a newly supplied email address alone is insufficient. The mandatory `--verified-out-of-band` flag records the operator's assertion that this check happened. Invitation explicitly marks the approved email verified, so omitting this verification would grant trust incorrectly.

From `backend/`, with the private operator environment loaded:

```bash
.venv/bin/flask --app app:create_app auth bootstrap-owner \
  --email approved-owner@example.invalid --name "Approved Owner" --verified-out-of-band

.venv/bin/flask --app app:create_app auth invite-admin \
  --email approved-staff@example.invalid --name "Approved Staff" --role staff --verified-out-of-band
```

Bootstrap refuses an existing active owner, including simultaneous bootstrap grants through the database's serialized lifecycle policy. Concurrent bootstrap commands can create an unused provider invitation before one local grant is rejected; only one bootstrap grant succeeds. Run bootstrap once from the approved operator process. The invitation asks Cognito to generate and email a one-day temporary password; the CLI never accepts or prints that secret. The recipient must replace it and enroll TOTP through managed login before gaining dashboard access. Re-invitation of an existing local identity is rejected. [AWS AdminCreateUser](https://docs.aws.amazon.com/cognito-user-identity-pools/latest/APIReference/API_AdminCreateUser.html).

If Cognito creates the user but persistence fails, that provider identity has no local admin grant. Inspect the protected audit trail and reconcile the orphan explicitly; do not bypass local access checks or repeatedly create identities. Retain issuer and subject as the identity key. A provider response with an unexpected email or missing subject never receives a local grant.

```bash
.venv/bin/flask --app app:create_app auth change-role \
  --email approved-staff@example.invalid --role owner

.venv/bin/flask --app app:create_app auth disable-admin \
  --email departing-staff@example.invalid

.venv/bin/flask --app app:create_app auth revoke-admin-sessions \
  --email approved-staff@example.invalid
```

Role changes revoke local sessions atomically, then sign the user out globally at Cognito. Disable removes local access first, then performs global sign-out and provider disable. Neither operation may remove the last active owner. If AWS fails, local revocation remains in effect; the command reports failure and never restores access automatically. `revoke-admin-sessions` repeats local revocation and global provider sign-out, including after a `logout_provider_pending` event. It signs out all sessions for that admin, not just one browser. A partially failed disable can be retried after the AWS issue is resolved.

For a lost authenticator, complete private identity verification first:

```bash
.venv/bin/flask --app app:create_app auth recover-admin \
  --email approved-owner@example.invalid --verified-out-of-band --lost-mfa
```

The recovery command checks SDK support, revokes every local session, performs Cognito global sign-out, then deletes the registered software token with `AdminDeleteSoftwareToken`. With MFA still `ON` and only TOTP enabled, the next managed sign-in must enroll a new authenticator. The command never switches the pool to optional MFA. `AdminSetUserMFAPreference` is not a substitute for deleting the old TOTP registration. Disabled administrators cannot be recovered by this command. [AWS AdminDeleteSoftwareToken](https://docs.aws.amazon.com/cognito-user-identity-pools/latest/APIReference/API_AdminDeleteSoftwareToken.html).

To reset the password as well, add `--reset-password`; it also works without `--lost-mfa` for password-only recovery. The CLI prompts twice with hidden input for a 16–256 character temporary password without whitespace. Deliver it through the previously verified private channel. Never put passwords in command arguments, shell history, scripts, tickets, or logs. The password is set temporary with `Permanent=False`, after session revocation and any requested TOTP deletion. The person must choose a new password and complete fresh required TOTP authentication. `AdminResetUserPassword` is not used because this pool has operator-only recovery.

Any intermediate provider failure stops the remaining recovery steps. Sessions stay revoked, and no success is reported. Review the protected audit trail, check the current provider state privately, and repeat the appropriate verified procedure. If TOTP deletion succeeded but password replacement failed, retry password-only recovery; requesting deletion again can fail because no old token remains. The same identity and local role are retained; creating a replacement account or disabling mandatory MFA is unnecessary. Recovery and role changes revoke existing identity sessions, while pre-authentication flows have no established identity to target; current local access and fresh provider authentication checks still govern any later callback.

Protect operator AWS access with a separate role, strong operator authentication, short sessions, and restricted access to its database credentials. Restrict the generated policy to this environment's admin pool and attach it only to approved operator roles. Keep this operational environment separate from ordinary website execution. The current commands create no permanent recovery codes and perform no account activation, customer administration, automatic account linking, or secret export.
