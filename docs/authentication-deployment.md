# Authentication deployment

The deployable template is [infra/cognito-authentication.json](../infra/cognito-authentication.json). It provisions separate customer and admin Cognito pools, confidential BFF app clients, managed-login v2 domains and default branding, Google federation in both pools, admin risk settings, a 90-day admin authentication log destination, and an unattached private-operator IAM policy. It creates no AWS operators or approved application users. A Google sign-in can create an unapproved provider profile; administrator access still requires a private local alias grant and application TOTP. Native admin password sign-in retains required Cognito TOTP. Pool resources use deletion protection and retention so stack removal or replacement does not silently remove identities.

Use separate stacks, domain prefixes, credentials, and databases for development and production. The development stack uses `DevelopmentOrigin`, restricted to exact `http://localhost` origins. The production stack requires an exact HTTPS `AuthOrigin`; it cannot select the development origin. Callback and logout URLs have no wildcard or caller-controlled redirect:

| Realm | Callback | Logout landing |
| --- | --- | --- |
| Customer | `<origin>/api/v1/customer/callback` | `<origin>/login` |
| Admin | `<origin>/api/v1/admin/callback` | `<origin>/admin/login` |

Before deployment, establish the following configuration:

- A supported AWS region, uniquely available managed-login domain prefixes, and reviewed CloudFormation execution permissions for Cognito, IAM, log delivery, and Secrets Manager reads.
- A Google OAuth web client dedicated to website authentication, shared by this template's customer and admin providers. Register both `https://<customer-prefix>.auth.<region>.amazoncognito.com/oauth2/idpresponse` and `https://<admin-prefix>.auth.<region>.amazoncognito.com/oauth2/idpresponse` as authorized redirect URIs, with the two corresponding Cognito origins as authorized JavaScript origins. Complete the Google consent and test-user or production publishing requirements. These credentials are separate from the application's Google Calendar adapter.
- An existing Secrets Manager secret containing JSON keys `client_id` and `client_secret`. Supply its ARN as `GoogleOAuthSecretArn`; CloudFormation resolves the values privately. Do not supply Google secret values as parameters or write them to template outputs.
- For production, a verified SES identity and From address in a Cognito-supported SES region; configure SES sending capacity and permissions. Supply `SesIdentityArn` and `EmailFrom`. Development can use Cognito's limited default email sender.
- A same-origin reverse proxy serving the frontend and `/api/v1` backend paths over HTTPS in hosted environments. Preserve `Origin`, secure cookies, callback query strings, and provider redirects while preventing sensitive query strings and headers from reaching access logs.

CloudFormation supports [managed-login domains](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-cognito-userpooldomain.html), [default client branding](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-cognito-managedloginbranding.html), and [refresh-token rotation](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-properties-cognito-userpoolclient-refreshtokenrotation.html). The default Cognito `urn:cognito:loa:4` claim convention is used; no custom ACR renaming is required. Plus compromised-password blocking and risk observation complement required TOTP without changing MFA to optional.

For the recorded development admin domain, add exactly `https://popssibilities-admin-dev.auth.us-east-1.amazoncognito.com/oauth2/idpresponse` to the Google OAuth client's redirect list. Keep the customer's existing redirect as well. These Google-to-Cognito redirects differ from the Cognito-to-website callbacks in the table above. Updating the CloudFormation template does not update Google Cloud's OAuth client configuration. [AWS Google-provider setup](https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-user-pools-social-idp.html).

Update an existing stack with this template to add `AdminGoogleProvider`, Google support on `AdminClient`, and writable mapped `email`/`name` attributes. Native pool MFA remains `ON`; do not downgrade it to enable federation. The admin client uses Cognito's default readable attributes rather than naming `identities` as a schema permission. The backend requires signed `identities` and `cognito:username` metadata and the CLI independently verifies the live profile before local approval. Verify these claims against the deployed pool. No Google identity receives dashboard access simply because its email matches an invited admin. [AWS ID-token metadata](https://docs.aws.amazon.com/cognito/latest/developerguide/amazon-cognito-user-pools-using-the-id-token.html).

Prepare and review a CloudFormation change set with the environment parameters and `CAPABILITY_IAM`. Executing it incurs the configured Cognito tier, SES, Secrets Manager, and CloudWatch costs. The stack outputs pool IDs, issuers, client IDs, login domains, log-group name, and the operator policy ARN. It deliberately has no client-secret output. Obtain each generated app-client secret through an approved private deployment process and inject it directly into backend secret configuration without printing the `DescribeUserPoolClient` response or placing the value in frontend build variables.

| Backend variable | Source |
| --- | --- |
| `APP_ENV` | `development` locally; `production` for hosted release |
| `AUTH_ENABLED` | `true` after all dependencies are configured |
| `AUTH_TRUSTED_PROXY_HOPS` | Zero for direct local access; one for the supplied private-backend Nginx topology |
| `FRONTEND_ORIGIN`, `CORS_ALLOWED_ORIGINS` | The single effective template origin, identical values |
| `APP_SECRET_KEY` | Private random application secret, at least 32 characters |
| `AUTH_TOKEN_ENCRYPTION_KEY` | Private Fernet key; separate from the application secret |
| `COGNITO_CUSTOMER_ISSUER`, `COGNITO_ADMIN_ISSUER` | Corresponding stack issuer outputs |
| `COGNITO_CUSTOMER_CLIENT_ID`, `COGNITO_ADMIN_CLIENT_ID` | Corresponding client ID outputs |
| `COGNITO_CUSTOMER_CLIENT_SECRET`, `COGNITO_ADMIN_CLIENT_SECRET` | Private generated app-client secrets |
| `COGNITO_CUSTOMER_DOMAIN`, `COGNITO_ADMIN_DOMAIN` | Exact HTTPS managed-login origin outputs, without a trailing slash |
| `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` | Runtime MySQL connection with only required DML grants |
| `DB_TLS_CA_FILE` | Trusted CA file for verified MySQL TLS in hosted environments |
| `DB_MIGRATION_USER`, `DB_MIGRATION_PASSWORD` | Separate deploy-time migration credentials; exclude from the web runtime |

The [Nginx example](../infra/nginx-authentication.conf) supplies HTTPS, SPA routing,
API proxying, CSP and other response headers. Replace its example domain, certificate
paths and frontend root before use. Its access format excludes query strings and
headers; API proxy errors are not retained with raw callback URLs. Configure your
production WSGI server's access format with the path only (Gunicorn `%(U)s`), never
its full request-line or query-string fields. The Flask development access logger
also redacts callback query parameters.

Direct backend access must be blocked before setting `AUTH_TRUSTED_PROXY_HOPS=1`.
The proxy overwrites X-Forwarded-For with its observed client address; it does not
preserve a caller-supplied chain. Different proxy topologies require their exact
trusted-hop count and equivalent origin/backend isolation. The safe default zero
ignores all forwarded IP headers.

Keep application secrets and the encryption key stable across backend instances so sessions, login transactions, and persistent application TOTP factors work across requests. Store all keys privately. Changing the encryption key without migrating ciphertext makes existing sessions and Google-admin factor secrets unreadable. A planned sign-out alone does not migrate a TOTP secret; rotate through an explicit ciphertext migration or a tested, privately verified factor-recovery procedure. The frontend receives no provider token, client secret, AWS key, database password, or encryption key. During authorized TOTP enrollment, the user necessarily receives the enrollment secret to add it to their authenticator; it must not enter access logs or telemetry.

Before starting the web process, run the versioned migration command from `backend/` in the configured deployment environment:

```bash
.venv/bin/python -m app.migrations
```

The migration runner uses a database lock, records checksums and completion, and supports retry after an interrupted additive migration. It runs explicitly, never at web startup. Runtime database access must permit authentication session, flow, rate-limit, identity, grant, and audit operations; DDL permissions belong to the migration process. Bootstrapping the first owner follows [authentication-operations.md](authentication-operations.md), from the private operator environment only.

This release adds migration `0002_admin_google_mfa.sql`; apply it before starting the updated authentication runtime. Do not edit or reapply migration 0001 manually. For the new tables, the web database user needs `SELECT` on `auth_admin_google_links`, `SELECT`/`UPDATE` on `auth_admin_totp`, and `SELECT`/`INSERT`/`UPDATE`/`DELETE` on `auth_admin_google_challenges`. Reserve alias creation and canonical access-grant writes for the private operator database user. Retain the existing identity/session/flow/rate-limit/audit privileges; the web runtime reads canonical grants but does not provision them. Migration credentials remain separate and supply the schema privileges required by the runner.

Create the native approved account before trying its Google method. If a Google-first profile already occupies that email, use a different privately verified native-admin address, complete password/Cognito-TOTP setup there, then approve the existing Google identity through a fresh hidden proof. The CLI deliberately rejects same-email native provisioning collisions. Google application-TOTP enrollment is a separate setup step that creates no session: after enrollment, the person starts another Google login and uses the next unused authenticator code to enter the dashboard.

Attach `AdminOperatorPolicyArn` only to the separately authenticated operator role. It already includes `AdminGetUser` for live Google-proof verification, scoped to this admin pool. Google alias approval is local: no `AdminLinkProviderForUser`, `AdminDeleteUser`, or provider-management permission is granted or needed. The website runtime makes OAuth and token-authorized self-user requests and needs no IAM Cognito administrator permissions. Log delivery targets a same-account CloudWatch log group without a KMS key because Cognito forbids a KMS-encrypted destination for this integration; standard CloudWatch encryption and restricted log-reading permissions still apply. [AWS destination restrictions](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-properties-cognito-logdeliveryconfiguration-cloudwatchlogsconfiguration.html).

Release verification must use real non-production pools and SES delivery: test customer registration and verification, password login and reset, Google first and repeat login, independent same-email accounts, native invitation setup, repeated fresh native admin TOTP challenges, native lost-TOTP re-enrollment, private Google approval, exact-challenge application TOTP enrollment, Google TOTP sign-in/recovery, proof expiry/reuse/wrong-target rejection, staff permission rejection, role changes and disable across linked profiles, logout/provider failure, logout with overlapping login callbacks in multiple tabs, retry after a cancelled login generation, refresh rotation, and TLS/proxy/cookie behavior. Verify signed native admin ACR/AMR and Google identities metadata privately without logging full tokens. Google-admin session assurance is established by the application TOTP step; do not label it as Cognito `loa:4`. Confirm Plus compromised-credential blocking for native passwords and auth-event log delivery in the deployed region. Automated tests use mocks and validate template security invariants; they do not establish that an AWS stack deployed or Google/SES login completed.

Completed customer password resets are not guaranteed by this release to invalidate every existing application session. If immediate cross-device invalidation is a release requirement, add and verify a provider recovery hook before launch. Provider logout failures have an audit event and a private admin reconciliation command, with no automated retry worker. These limits are also recorded in [authentication.md](authentication.md).

Rollback should preserve pools and identity/grant records, restore a compatible application release and private configuration, and reconcile any incomplete invitation or recovery operations from the audit trail. Do not roll back to a hosted build that permits dashboard access without authentication. Pools retained after stack deletion require explicit lifecycle review before any later removal.
