# Private administrator operations

Run the `auth` Flask command group in a dedicated trusted operator process with the backend configuration, access to the authentication database, and separately authenticated AWS operator credentials. These commands are not HTTP endpoints. The web runtime must not receive the IAM managed policy produced by the authentication stack. The AWS caller ARN from `GetCallerIdentity` is recorded in protected local audit events before any lifecycle mutation; raw provider errors, passwords, tokens, and client secrets are withheld from terminal output. Standard logging is temporarily silenced while privileged provider/database operations run so verbose SDK request logging cannot record credentials. Audit records are written directly to the database; logging configuration is restored when the command completes or fails.

The configured `COGNITO_ADMIN_ISSUER` fixes the region and user pool for every command. The CLI accepts neither a pool override nor a subject supplied by the caller. Existing-account commands resolve exactly one approved canonical native admin in that issuer by email; an unapproved Google profile or approved alias with the same email cannot shadow it. Native profiles use their recorded subject; historical Google profiles retain their recorded provider username for private lifecycle revocation only. The local canonical grant and active status remain authoritative for dashboard access. Changing the target's email directly in Cognito requires reconciling the local identity through a successful login or a separately reviewed maintenance procedure.

Before inviting or recovering anyone, verify the approved person's identity and ownership of the intended email address through a known private contact method. Follow the organization's independent approval procedure; a request from a newly supplied email address alone is insufficient. The mandatory `--verified-out-of-band` flag records the operator's assertion that this check happened. Invitation explicitly marks the approved email verified, so omitting this verification would grant trust incorrectly.

From `backend/`, with the private operator environment loaded:

```bash
.venv/bin/flask --app app:create_app auth bootstrap-owner \
  --email approved-owner@example.invalid --name "Approved Owner" --verified-out-of-band

.venv/bin/flask --app app:create_app auth invite-admin \
  --email approved-staff@example.invalid --name "Approved Staff" --role staff --verified-out-of-band
```

Bootstrap refuses an existing active owner, including simultaneous bootstrap grants through the database's serialized lifecycle policy. Concurrent bootstrap commands can create an unused provider invitation before one local grant is rejected; only one bootstrap grant succeeds. Run bootstrap once from the approved operator process. The invitation asks Cognito to generate and email a one-day temporary password; the CLI never accepts or prints that secret. The recipient enters it at `/admin/login`, replaces it, and enrolls TOTP in the native challenge interface. Enrollment returns to password login; dashboard access requires a subsequent password plus `SOFTWARE_TOKEN_MFA` challenge. See [native setup](authentication-native-admin.md). Re-invitation of an existing local identity is rejected. [AWS AdminCreateUser](https://docs.aws.amazon.com/cognito-user-identity-pools/latest/APIReference/API_AdminCreateUser.html).

A historical admin Google profile can already occupy the intended email. The CLI keeps this collision blocked, and an email-as-username Cognito pool can also reject duplicate-email native creation. Privately verify a different address that the same approved person controls and can receive invitations at; use that address for `bootstrap-owner` or `invite-admin`, then complete native password/TOTP setup. A plus-address is suitable only when that mailbox supports it and delivery has been verified. Preserve the historical profile without granting it administrator access. Do not convert its password, force an email alias takeover, or grant access because emails match. [AWS email username constraints](https://docs.aws.amazon.com/cognito/latest/developerguide/user-pool-settings-attributes.html).

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

Use `disable-admin` for administrator offboarding. Removing canonical local access denies native login, and the CLI also coordinates sign-out/disable for historical linked profiles. A Google profile cannot create or use an admin session regardless of its previous alias grant.

For a lost authenticator, complete private identity verification first:

```bash
.venv/bin/flask --app app:create_app auth recover-admin \
  --email approved-owner@example.invalid --verified-out-of-band --lost-mfa
```

The recovery command checks SDK support, revokes local canonical/alias sessions, globally signs out all associated Cognito profiles, then deletes only the native profile's software token with `AdminDeleteSoftwareToken`. With MFA still `ON` and only TOTP enabled, the next native password sign-in must enroll a new authenticator. The command never switches the pool to optional MFA. `AdminSetUserMFAPreference` is not a substitute for deleting the old TOTP registration. Disabled administrators cannot be recovered by this command. [AWS AdminDeleteSoftwareToken](https://docs.aws.amazon.com/cognito-user-identity-pools/latest/APIReference/API_AdminDeleteSoftwareToken.html).

To reset the password as well, add `--reset-password`; it also works without `--lost-mfa` for password-only recovery. The CLI prompts twice with hidden input for a 16–256 character temporary password without whitespace. Deliver it through the previously verified private channel. Never put passwords in command arguments, shell history, scripts, tickets, or logs. The password is set temporary with `Permanent=False`, after session revocation and any requested TOTP deletion. The person must choose a new password and complete fresh required TOTP authentication. `AdminResetUserPassword` is not used because this pool has operator-only recovery.

Any intermediate provider failure stops the remaining recovery steps. Sessions stay revoked, and no success is reported. Review the protected audit trail, check the current provider state privately, and repeat the appropriate verified procedure. If TOTP deletion succeeded but password replacement failed, retry password-only recovery; requesting deletion again can fail because no old token remains. The same identity and local role are retained; creating a replacement account or disabling mandatory MFA is unnecessary. Recovery and role changes revoke existing identity sessions, while pre-authentication flows have no established identity to target; current local access and fresh provider authentication checks still govern any later callback.

Protect operator AWS access with a separate role, strong operator authentication, short sessions, and restricted access to its database credentials. Restrict the generated policy to this environment's admin pool and attach it only to approved operator roles. Keep this operational environment separate from ordinary website execution. The current commands create no permanent recovery codes and perform no account activation, customer administration, automatic account linking, or secret export.

## Diagnosing an administrator MFA callback failure

The retained administrator OAuth callback still rejects missing or insufficient signed ACR/AMR. The approved development owner's request `2407f08818ac45318995a085b6e45417` recorded `mfa_assurance_missing` with all four ID/access claim-presence flags false. Read-only inspection confirmed Plus, required software-token MFA, password-only first factors, COGNITO-only client and a successful password/MFA provider event. These facts show that managed login did not satisfy the implemented signed-claim contract in this environment; they do not justify removing MFA checks or resetting a working account.

The primary `/admin/login` interface now uses a native password/TOTP challenge flow. Follow [native administrator setup and live verification](authentication-native-admin.md). The runtime records static native transition and denial events with request IDs; no passwords, codes, tokens, provider sessions or enrollment secrets belong in audit details or application/access logs.

Inspect protected callback failure records without selecting credentials or account attributes:

```sql
SELECT created_at, request_id,
       JSON_UNQUOTE(JSON_EXTRACT(detail, '$.error_code')) AS error_code,
       JSON_UNQUOTE(JSON_EXTRACT(detail, '$.reason')) AS reason
FROM auth_audit_events
WHERE event = 'login_denied'
  AND JSON_UNQUOTE(JSON_EXTRACT(detail, '$.area')) = 'admin'
ORDER BY created_at DESC
LIMIT 10;
```

| Private reason | Meaning |
| --- | --- |
| `mfa_assurance_missing` | The managed-login token lacks signed ACR or AMR; native challenge login is the supported alternative. |
| `mfa_assurance_insufficient` | Signed managed-login claims do not establish password plus TOTP. |
| `mfa_authentication_stale` | Signed authentication time predates this new transaction beyond allowed clock skew. |
| `mfa_enrollment_missing` | Token-authorized factor queries cannot confirm registered TOTP for the exact native account. |

A required-TOTP pool can challenge a registered authenticator even when `GetUser.UserMFASettingList` is empty. The runtime falls back to `GetUserAuthFactors`, binds its canonical username to `GetUser`, and requires `SOFTWARE_TOKEN`. This is an ongoing registration/revocation check, never proof that this login completed MFA. [AWS GetUserAuthFactors](https://docs.aws.amazon.com/cognito-user-identity-pools/latest/APIReference/API_GetUserAuthFactors.html).

Use separately authenticated operator credentials for configuration or provider-event inspection. If the session expires, renew it through the established operator login; never copy credentials into the website process. Read-only configuration commands, with private backend settings already exported:

```bash
AUTH_ADMIN_POOL_ID="${COGNITO_ADMIN_ISSUER##*/}"
AUTH_ADMIN_REGION="${AUTH_ADMIN_POOL_ID%%_*}"
aws cognito-idp describe-user-pool --profile private-operator \
  --region "$AUTH_ADMIN_REGION" --user-pool-id "$AUTH_ADMIN_POOL_ID" \
  --query 'UserPool.{Tier:UserPoolTier,FirstFactors:Policies.SignInPolicy.AllowedFirstAuthFactors}'
aws cognito-idp get-user-pool-mfa-config --profile private-operator \
  --region "$AUTH_ADMIN_REGION" --user-pool-id "$AUTH_ADMIN_POOL_ID" \
  --query '{Mfa:MfaConfiguration,SoftwareToken:SoftwareTokenMfaConfiguration}'
aws cognito-idp describe-user-pool-client --profile private-operator \
  --region "$AUTH_ADMIN_REGION" --user-pool-id "$AUTH_ADMIN_POOL_ID" \
  --client-id "$COGNITO_ADMIN_CLIENT_ID" \
  --query 'UserPoolClient.{NativeFlows:ExplicitAuthFlows,ChallengeMinutes:AuthSessionValidity,Providers:SupportedIdentityProviders,ReadAttributes:ReadAttributes,Rotation:RefreshTokenRotation,Revocation:EnableTokenRevocation}'
```

Replace `private-operator` with the approved profile. The provisioning policy does not authorize every diagnostic read. Never dump entire client responses because they include its secret. Do not add synthetic ACR/AMR with Lambda, delete/recreate pools, reset a working password/authenticator, grant by matching email, or lower mandatory MFA to diagnose the missing claims.

## Retired administrator Google sign-in

Administrator authentication now uses native Cognito password and mandatory TOTP only. The `link-admin-google` and `recover-google-mfa` commands are no longer available, and the website does not authorize new aliases or application-factor enrollment. Existing Google profiles and historical alias/factor records are retained; do not delete users or applied migrations to change the login policy. Existing native role, revoke, disable and recovery commands continue to revoke any historical linked sessions/profiles as appropriate.

Customers retain their separate Google and email/password authentication. In Google Cloud, retain the customer OAuth redirect; an administrator Google redirect is no longer needed by this application. Review any provider/redirect cleanup in a separate authorized cloud change. No live configuration is changed by editing this repository.
