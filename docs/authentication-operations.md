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

Bootstrap refuses an existing active owner, including simultaneous bootstrap grants through the database's serialized lifecycle policy. Concurrent bootstrap commands can create an unused provider invitation before one local grant is rejected; only one bootstrap grant succeeds. Run bootstrap once from the approved operator process. The invitation asks Cognito to generate and email a one-day temporary password; the CLI never accepts or prints that secret. The recipient must replace it and enroll TOTP through managed login before gaining dashboard access. Re-invitation of an existing local identity is rejected. [AWS AdminCreateUser](https://docs.aws.amazon.com/cognito-user-identity-pools/latest/APIReference/API_AdminCreateUser.html).

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

`/admin/login?error=mfa_required` means the backend denied access after the Cognito callback. It does not identify the failed MFA check. Start a new login after restarting the updated backend, then inspect the private `login_denied` audit entry or the backend's `Authentication callback denied` log line for its static `reason` and request ID. Never copy tokens, callback codes, flow cookies, authenticator secrets, client secrets, or complete Cognito responses into logs or support messages. The browser receives only the existing public error code.

Run this read-only query through the private database connection to inspect recent administrator failures without selecting account or token records:

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

| Private reason | Meaning and next check |
| --- | --- |
| `mfa_assurance_missing` | A signed ACR or AMR claim is absent. Check the live pool's feature plan, ACR configuration, and managed-login settings. |
| `mfa_assurance_insufficient` | The achieved signed claims do not prove password plus authenticator TOTP. Check which factor completed the login and the live pool's MFA configuration. |
| `mfa_authentication_stale` | The signed authentication time predates the new login transaction beyond the allowed clock skew. Start from `/admin/login` again; check clock synchronization and any managed-login session reuse. |
| `mfa_enrollment_missing` | Cognito `GetUser` does not report a registered `SOFTWARE_TOKEN_MFA` factor for this exact subject. Inspect that native account's factor registration privately. |

The intended admin configuration is Essentials or Plus (the template selects Plus), mandatory MFA `ON`, only `SOFTWARE_TOKEN_MFA`, and managed login version 2. The default level-4 URI must remain `urn:cognito:loa:4`; the signed methods must include `pwd`, `otp`, and `mfa`. Cognito can customize level names, so a renamed level also fails this application's deliberate exact check. On Lite, managed login silently ignores `acr_values`. Cognito does not permit a Lambda trigger to add, replace, or suppress native ACR/AMR claims. Correct the reviewed pool configuration instead of fabricating assurance or relaxing validation. [AWS ACR/AMR and feature-plan requirements](https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-user-pools-step-up-authentication.html).

For a manual configuration repair after the operator has verified drift and the
cloud change is authorized:

1. Open only the administrator pool in Cognito. Under **Settings → Feature plans**,
   check its current plan. If it is Lite, review switching to Plus to match the
   repository template (Essentials also supports the requested ACR level). Review
   the selected plan's price before confirming. [AWS feature-plan setup](https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-sign-in-feature-plans.html).
2. Under **Sign-in → Multi-factor authentication → Edit**, retain **Require MFA**
   and **Authenticator apps** as the only supported second factor. Verify the
   domain uses managed login version 2 and the admin app client has branding.
   Retain the existing pool, approved identities, and customer pool settings.
   [AWS MFA setup](https://docs.aws.amazon.com/cognito/latest/developerguide/user-pool-settings-mfa.html).
3. Verify level 4 uses the default `urn:cognito:loa:4` URI. ACR/AMR are native token
   claims, not user attributes to add to client read/write permissions. Use the
   filtered read-only commands below to inspect any remaining differences.
4. Start a fresh password login from `http://localhost:5173/admin/login` in
   development, then enter the existing authenticator code. Verify the callback
   creates a session and lands at `/admin`; verify role and disabled-access
   checks, refresh and logout before declaring the live configuration validated.

No cloud repair is performed by these repository edits or by the diagnostic queries.

Use the existing private operator profile for read-only inspection. If it returns `ExpiredTokenException`, renew that operator session with its established login procedure. Keep those credentials outside the web runtime. With the backend configuration exported into the private operator shell, these commands print selected configuration fields and omit the client secret:

```bash
AUTH_ADMIN_POOL_ID="${COGNITO_ADMIN_ISSUER##*/}"
AUTH_ADMIN_REGION="${AUTH_ADMIN_POOL_ID%%_*}"

aws cognito-idp describe-user-pool --profile private-operator \
  --region "$AUTH_ADMIN_REGION" --user-pool-id "$AUTH_ADMIN_POOL_ID" \
  --query 'UserPool.{Tier:UserPoolTier,ACR:AcrConfiguration,FirstFactors:Policies.SignInPolicy.AllowedFirstAuthFactors}'

aws cognito-idp get-user-pool-mfa-config --profile private-operator \
  --region "$AUTH_ADMIN_REGION" --user-pool-id "$AUTH_ADMIN_POOL_ID" \
  --query '{Mfa:MfaConfiguration,SoftwareToken:SoftwareTokenMfaConfiguration}'

aws cognito-idp describe-user-pool-client --profile private-operator \
  --region "$AUTH_ADMIN_REGION" --user-pool-id "$AUTH_ADMIN_POOL_ID" \
  --client-id "$COGNITO_ADMIN_CLIENT_ID" \
  --query 'UserPoolClient.{Flows:AllowedOAuthFlows,Scopes:AllowedOAuthScopes,Providers:SupportedIdentityProviders,ReadAttributes:ReadAttributes,Callbacks:CallbackURLs}'
```

Replace `private-operator` with the existing approved profile name. These inspection calls require approved Cognito read permissions; the provisioning-only policy does not by itself authorize every diagnostic call. Verify the managed-login domain version in the pool's domain settings. The client must use its own admin pool, the code flow, `COGNITO`, the four configured scopes, and readable `email`/`email_verified`; its callback must exactly match `${FRONTEND_ORIGIN}/api/v1/admin/callback`.

To inspect the approved native account without printing its attributes, privately obtain its subject from the local canonical grant for the configured issuer and set `AUTH_APPROVED_ADMIN_SUBJECT` in that operator shell. Then run:

```bash
aws cognito-idp admin-get-user --profile private-operator \
  --region "$AUTH_ADMIN_REGION" --user-pool-id "$AUTH_ADMIN_POOL_ID" \
  --username "$AUTH_APPROVED_ADMIN_SUBJECT" \
  --query '{Enabled:Enabled,Status:UserStatus,MfaMethods:UserMFASettingList}'
```

Initial managed-login password/TOTP setup can issue a one-time enrollment token. After completing authenticator enrollment, start a fresh password login and complete its authenticator challenge before expecting dashboard access. [AWS TOTP enrollment behavior](https://docs.aws.amazon.com/cognito/latest/developerguide/user-pool-settings-mfa-totp.html).

For someone who already entered a code from an existing authenticator, determine the private reason and live configuration before resetting anything. Do not create a replacement account, reset a working password/factor, change the local role, or disable MFA to diagnose this error. Any necessary cloud configuration change or verified account recovery remains a separately authorized operator action.

## Retired administrator Google sign-in

Administrator authentication now uses native Cognito password and mandatory TOTP only. The `link-admin-google` and `recover-google-mfa` commands are no longer available, and the website does not authorize new aliases or application-factor enrollment. Existing Google profiles and historical alias/factor records are retained; do not delete users or applied migrations to change the login policy. Existing native role, revoke, disable and recovery commands continue to revoke any historical linked sessions/profiles as appropriate.

Customers retain their separate Google and email/password authentication. In Google Cloud, retain the customer OAuth redirect; an administrator Google redirect is no longer needed by this application. Review any provider/redirect cleanup in a separate authorized cloud change. No live configuration is changed by editing this repository.
