# Private administrator operations

Run the `auth` Flask command group in a dedicated trusted operator process with the backend configuration, access to the authentication database, and separately authenticated AWS operator credentials. These commands are not HTTP endpoints. The web runtime must not receive the IAM managed policy produced by the authentication stack. The AWS caller ARN from `GetCallerIdentity` is recorded in protected local audit events before any lifecycle mutation; raw provider errors, passwords, tokens, and client secrets are withheld from terminal output. Standard logging is temporarily silenced while privileged provider/database operations run so verbose SDK request logging cannot record credentials. Audit records are written directly to the database; logging configuration is restored when the command completes or fails.

The configured `COGNITO_ADMIN_ISSUER` fixes the region and user pool for every command. The CLI accepts neither a pool override nor a subject supplied by the caller. Existing-account commands resolve exactly one approved canonical native admin in that issuer by email; an unapproved Google profile or approved alias with the same email cannot shadow it. Native profiles use their recorded subject, and approved Google profiles use their recorded provider username. The local canonical grant and active status remain authoritative for dashboard access. Changing the target's email directly in Cognito requires reconciling the local identity through a successful login or a separately reviewed maintenance procedure.

Before inviting or recovering anyone, verify the approved person's identity and ownership of the intended email address through a known private contact method. Follow the organization's independent approval procedure; a request from a newly supplied email address alone is insufficient. The mandatory `--verified-out-of-band` flag records the operator's assertion that this check happened. Invitation explicitly marks the approved email verified, so omitting this verification would grant trust incorrectly.

From `backend/`, with the private operator environment loaded:

```bash
.venv/bin/flask --app app:create_app auth bootstrap-owner \
  --email approved-owner@example.invalid --name "Approved Owner" --verified-out-of-band

.venv/bin/flask --app app:create_app auth invite-admin \
  --email approved-staff@example.invalid --name "Approved Staff" --role staff --verified-out-of-band
```

Bootstrap refuses an existing active owner, including simultaneous bootstrap grants through the database's serialized lifecycle policy. Concurrent bootstrap commands can create an unused provider invitation before one local grant is rejected; only one bootstrap grant succeeds. Run bootstrap once from the approved operator process. The invitation asks Cognito to generate and email a one-day temporary password; the CLI never accepts or prints that secret. The recipient must replace it and enroll TOTP through managed login before gaining dashboard access. Re-invitation of an existing local identity is rejected. [AWS AdminCreateUser](https://docs.aws.amazon.com/cognito-user-identity-pools/latest/APIReference/API_AdminCreateUser.html).

If the person signed in with Google before native provisioning, their unapproved profile can already occupy the intended email. The CLI keeps this collision blocked, and an email-as-username Cognito pool can also reject duplicate-email native creation. Privately verify a different address that the same person controls and can receive invitations at; use that address for `bootstrap-owner` or `invite-admin`. A plus-address is suitable only when that mailbox supports it and delivery has been verified. Complete native password/TOTP setup there, then explicitly approve the existing Google identity with a fresh proof using the new canonical email. Keep both profiles; do not delete the Google profile, change its password to convert it, force an email alias takeover, or grant access because emails match. [AWS email username constraints](https://docs.aws.amazon.com/cognito/latest/developerguide/user-pool-settings-attributes.html).

If Cognito creates the user but persistence fails, that provider identity has no local admin grant. Inspect the protected audit trail and reconcile the orphan explicitly; do not bypass local access checks or repeatedly create identities. Retain issuer and subject as the identity key. A provider response with an unexpected email or missing subject never receives a local grant.

```bash
.venv/bin/flask --app app:create_app auth change-role \
  --email approved-staff@example.invalid --role owner

.venv/bin/flask --app app:create_app auth disable-admin \
  --email departing-staff@example.invalid

.venv/bin/flask --app app:create_app auth revoke-admin-sessions \
  --email approved-staff@example.invalid
```

Role changes revoke local sessions for the canonical admin and approved Google aliases atomically, then sign out all those Cognito profiles globally. Disable removes canonical local access first, then globally signs out and disables the native and every approved Google profile. Neither operation may remove the last active owner. If AWS fails, local revocation remains in effect; the command reports failure and never restores access automatically. `revoke-admin-sessions` repeats canonical/alias local revocation and global provider sign-out, including after a `logout_provider_pending` event. It signs out all associated profiles, not just one browser. A partially failed disable can be retried after the AWS issue is resolved.

Use `disable-admin` for administrator offboarding. Disabling only one profile directly in the AWS console affects that provider profile, not its separate Google/native sibling or the local canonical grant. Each authenticated session checks its own provider profile and the canonical local status; the CLI coordinates all of them.

For a lost authenticator, complete private identity verification first:

```bash
.venv/bin/flask --app app:create_app auth recover-admin \
  --email approved-owner@example.invalid --verified-out-of-band --lost-mfa
```

The native recovery command checks SDK support, revokes local canonical/alias sessions, globally signs out all associated Cognito profiles, then deletes only the native profile's software token with `AdminDeleteSoftwareToken`. With MFA still `ON` and only TOTP enabled, the next native password sign-in must enroll a new authenticator. This does not reset the separate application factor used for Google sign-in. The command never switches the pool to optional MFA. `AdminSetUserMFAPreference` is not a substitute for deleting the old TOTP registration. Disabled administrators cannot be recovered by this command. [AWS AdminDeleteSoftwareToken](https://docs.aws.amazon.com/cognito-user-identity-pools/latest/APIReference/API_AdminDeleteSoftwareToken.html).

To reset the password as well, add `--reset-password`; it also works without `--lost-mfa` for password-only recovery. The CLI prompts twice with hidden input for a 16–256 character temporary password without whitespace. Deliver it through the previously verified private channel. Never put passwords in command arguments, shell history, scripts, tickets, or logs. The password is set temporary with `Permanent=False`, after session revocation and any requested TOTP deletion. The person must choose a new password and complete fresh required TOTP authentication. `AdminResetUserPassword` is not used because this pool has operator-only recovery.

Any intermediate provider failure stops the remaining recovery steps. Sessions stay revoked, and no success is reported. Review the protected audit trail, check the current provider state privately, and repeat the appropriate verified procedure. If TOTP deletion succeeded but password replacement failed, retry password-only recovery; requesting deletion again can fail because no old token remains. The same identity and local role are retained; creating a replacement account or disabling mandatory MFA is unnecessary. Recovery and role changes revoke existing identity sessions, while pre-authentication flows have no established identity to target; current local access and fresh provider authentication checks still govern any later callback.

Protect operator AWS access with a separate role, strong operator authentication, short sessions, and restricted access to its database credentials. Restrict the generated policy to this environment's admin pool and attach it only to approved operator roles. Keep this operational environment separate from ordinary website execution. The current commands create no permanent recovery codes and perform no account activation, customer administration, automatic account linking, or secret export.

## Approve administrator Google sign-in

Bootstrap or invite the native Owner/Staff account first and complete its native password/TOTP setup. That canonical identity owns the application role; Google is an explicitly approved alternate identity. Cognito pool MFA does not challenge federated Google sign-in, so the website requires its own authenticator-app TOTP after Google authentication. A Google credential alone never opens the dashboard. [AWS federation and MFA](https://docs.aws.amazon.com/cognito/latest/developerguide/user-pool-settings-mfa.html).

1. In the user's browser, open `/admin/login`, choose Google, and authenticate to the intended Google account. The website creates a pending browser-bound challenge lasting at most five minutes, displays a one-time approval code, and grants no session yet.
2. Independently verify that this Google identity belongs to the approved native administrator. The email addresses can differ; an email match does not approve the link. Transfer the displayed approval code privately to the operator while keeping that browser open.
3. From `backend/`, run the command below using the canonical native account's email. Paste the code only into its hidden prompt, never a command argument, shell variable, ticket, or log.

```bash
.venv/bin/flask --app app:create_app auth link-admin-google \
  --email approved-owner@example.invalid --verified-out-of-band
```

The CLI hashes the proof code and looks up the pending challenge. It calls `AdminGetUser` for the proof's exact provider username and requires an enabled `EXTERNAL_PROVIDER` profile, the expected Cognito subject, verified email, and exactly one Google identity with the signed stable Google user ID. A native AWS-linked destination profile is rejected. Case-insensitive pools lowercase the generated provider username; the stored, validated username preserves the actual profile form. [AWS profile mapping](https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-user-pools-specifying-attribute-mapping.html), [AWS AdminGetUser](https://docs.aws.amazon.com/cognito-user-identity-pools/latest/APIReference/API_AdminGetUser.html).

Approval consumes the proof atomically, checks the active canonical role and uniqueness of the alias, records the trusted IAM operator, and revokes existing application sessions across the canonical identity and aliases. When no application factor exists, it authorizes enrollment only in this exact pending challenge. In the same browser, continue to enrollment, save the displayed secret in an authenticator, and submit a current code before the challenge expires. Successful enrollment confirms the factor but does not create an admin session. Start a new Google login, wait for the next unused authenticator code, and submit that code to gain access. Future Google logins also require a fresh application TOTP code.

The proof is used once. It cannot approve a different browser challenge, silently relink an identity to a different administrator, or grant access to a disabled admin. If it expires during verification, start a new Google sign-in and repeat the private approval procedure. Approved Google aliases inherit the canonical role and activation status. The application keeps native and Google Cognito profiles separate: it never merges or deletes profiles with `AdminLinkProviderForUser` or matches identities automatically by email. Approval does not globally sign out its own pending Google tokens, because those fresh tokens are required to finish the authorized challenge.

## Recover a Google application authenticator

For a lost application TOTP device, privately verify the approved person and have them start a fresh Google login in the same browser that will enroll the replacement. On the authenticator-code screen, choose **Recover authenticator** to reveal its fresh approval code. Transfer that code privately, then run:

```bash
.venv/bin/flask --app app:create_app auth recover-google-mfa \
  --email approved-owner@example.invalid --verified-out-of-band
```

The hidden proof must identify the already approved Google alias for that exact canonical admin. After live provider verification, persistence consumes the proof, removes the old application factor, increments its version, revokes canonical/alias application sessions, and authorizes enrollment only in the exact fresh challenge. The person continues in that browser, enrolls a replacement authenticator, and proves possession with a TOTP. Enrollment creates no session: they must then start a new Google login and supply the next unused authenticator code before regaining access. Existing sessions cannot use the old factor version. The native Cognito password/TOTP enrollment remains separate and unchanged; recover it with `recover-admin` when needed.

No AWS-native account-linking or deletion permission is needed for these procedures. A fresh proof, independent verification, and active local grant are required for each recovery; knowing an email address or possessing a Google token alone does not authorize a reset. Preserve the pending provider tokens during the operator procedure so its one approved browser can finish; local revocation and factor-version changes invalidate prior application access.
