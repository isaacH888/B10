# Shared configuration contract

Updated October 8, 2026. Owner: Isaac Hernandez. React/Vite, Flask and MySQL
scaffolding is approved. The shell and authentication consume the settings below. Other feature adapters remain reserved.

## Templates and loading

- [Root template](../.env.example): shared inventory; private root `.env` is used by local Compose.
- [Backend template](../backend/.env.example): copy to `backend/.env`; Flask loads this file without overriding process settings.
- [Frontend template](../frontend/.env.example): copy to `frontend/.env`; contains only public `VITE_API_BASE_URL`.

Do not copy the full shared template into the frontend. See [setup](development-setup.md)
for exact commands. Keep the application DB credentials consistent between root and
backend private files. The MySQL root password belongs only to Compose.

## Variable ownership and implementation

| Variables | Consumer / owner | Current behavior or required handoff |
| --- | --- | --- |
| `VITE_API_BASE_URL` | React; Isaac foundation, Aneena/Dillion consumers | Same-origin `/api/v1`; Vite proxies to Flask locally; cross-origin bases are rejected |
| `APP_ENV`, `LOG_LEVEL` | Flask; Isaac | Validated and consumed at startup; environment is development/staging/production |
| `APP_TIMEZONE` | Future event/reminder adapters; Anh/Shourya | Reserved America/Chicago display default; not yet used for domain timestamps |
| `APP_SECRET_KEY` | Flask; Isaac foundation, Shourya auth | Required for enabled authentication; at least 32 characters; signs session-bound CSRF values |
| `CORS_ALLOWED_ORIGINS` | Flask; Isaac | Comma-separated exact origins; no wildcard, credentials, paths or query; HTTPS required hosted |
| `FRONTEND_ORIGIN` | Session/CSRF implementation; Shourya | Exact browser origin, consumed as AUTH_ORIGIN; must equal the sole CORS origin when auth is enabled |
| `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_TLS_CA_FILE` | Flask readiness; Isaac; domain persistence Bryson/Anh | MySQL session/audit storage and readiness; hosted connections require certificate/hostname-verified TLS |
| `MYSQL_ROOT_PASSWORD` | Local Compose; Isaac | Required for initialization only; never passed to Flask |
| `AUTH_ENABLED` | Flask authentication; Shourya | Explicit true/false. Local default false; hosted authentication must be enabled. Never permits a fallback identity. |
| `AUTH_TRUSTED_PROXY_HOPS` | Flask proxy middleware; Shourya | Default zero ignores forwarded IPs. Set to the exact trusted proxy count (0–3) only after blocking direct backend access. |
| `AUTH_TOKEN_ENCRYPTION_KEY` | Flask authentication; Shourya | Private Fernet key encrypts provider tokens and OAuth transactions in MySQL; no default. Retain encrypted legacy records and plan ciphertext migration before replacing the key. |
| `COGNITO_CUSTOMER_ISSUER`, `COGNITO_ADMIN_ISSUER` | Flask OIDC; Shourya | Exact distinct Cognito pool issuers; immutable issuer/subject identify accounts. |
| `COGNITO_CUSTOMER_CLIENT_ID`, `COGNITO_ADMIN_CLIENT_ID` | Flask OIDC; Shourya | Confidential client identifiers; must match exact callback and logout URLs. |
| `COGNITO_CUSTOMER_CLIENT_SECRET`, `COGNITO_ADMIN_CLIENT_SECRET` | Flask OIDC; Shourya | Backend-only client secrets, never Vite settings or template outputs. |
| `COGNITO_CUSTOMER_DOMAIN`, `COGNITO_ADMIN_DOMAIN` | Flask OIDC; Shourya | Exact HTTPS Cognito managed-login origins, no path or trailing slash. |
| `DB_MIGRATION_USER`, `DB_MIGRATION_PASSWORD` | Explicit migration command; shared persistence | Separate hosted schema credentials; read only by the migration runner, not runtime Flask settings. |
| `EMAIL_ENABLED`, `EMAIL_PROVIDER` | Customer sample email; Shourya | Explicit true/false, false by default; provider must be ses when enabled |
| `EMAIL_AWS_REGION` | SES adapter | Default us-east-1; sender verification and sending limits are regional |
| `EMAIL_FROM_ADDRESS`, `EMAIL_REPLY_TO_ADDRESS` | SES adapter | Required bare sender and monitored reply addresses when enabled |
| `EMAIL_SES_CONFIGURATION_SET` | SES adapter | Optional preconfigured SES event/suppression configuration set |
| `EMAIL_AWS_ACCESS_KEY_ID`, `EMAIL_AWS_SECRET_ACCESS_KEY`, `EMAIL_AWS_SESSION_TOKEN` | Local SES adapter only | Optional dedicated mailer credentials. Never use the private Cognito operator; hosted environments use a mailer workload role. Generic AWS credentials and shared profiles are ignored. |
| `BUSINESS_NOTIFICATION_EMAIL`, `EMAIL_SANDBOX_RECIPIENT` | Future email integrations | Reserved, unused by the customer test endpoint, which resolves the current verified Cognito customer email |
| `CALENDAR_ENABLED`, `GOOGLE_CALENDAR_ID` | Google adapter; Shourya | Reserved; disabled; Week 5 integration |
| `GOOGLE_APPLICATION_CREDENTIALS` | Google; Shourya | Reserved private file path if service-account design is approved |
| `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`, `GOOGLE_OAUTH_REFRESH_TOKEN` | Google; Shourya | Reserved OAuth alternative; choose account model/scopes rather than requiring both mechanisms |
| `PAYMENT_PROVIDER` | Payment workflow; Anh with Shourya/client | Reserved Square-first priority from S04; not a payment adapter or verification method |
| `SQUARE_PAYMENT_LINK`, `VENMO_PAYMENT_LINK`, `PAYPAL_PAYMENT_LINK` | Payment links; client supplies, Anh consumes | Reserved external destinations; Square first, others later; links do not verify payment |
| `CONTRACT_URL` | Contract delivery; Shourya/client | Reserved approved HTTPS document URL/access policy; Week 6 |
| `REMINDERS_ENABLED` | Scheduler; Shourya | Reserved disabled gate; timing/eligibility still open; Week 6 |
| `DELIVERY_ORIGIN_ADDRESS`, `DELIVERY_ORIGIN_POSTAL_CODE` | Distance/pricing; Anh/client | Reserved recorded Wingman Kitchens address; postal code and geocoding unverified |
| `DISTANCE_PROVIDER`, `DISTANCE_API_KEY` | Distance adapter; Anh | Reserved approved distance method/provider; no guessed distance or fee calculation |
| `CUSTOM_EVENT_INQUIRY_URL` | Quote inquiry action; Anh/Dillion/client | Reserved destination for beyond-30-mile requests; empty until approved route is provided |

Cognito configuration is implemented for the user-approved authentication design.
Customer sample email configuration is separate from private operator access.
Business email automation, payments, and Calendar remain pending. See
[customer test email](customer-test-email.md) for setup and delivery limitations.
A full-service rate is not encoded here: the $150 question still needs explicit
confirmation. See [source alignment](reference-alignment.md).

## Startup and health

Hosted startup rejects missing core application/TLS DB configuration and invalid
origins or ports. Development permits blank DB credentials so the shell can start;
`/live` returns 200 while `/health` returns 503 until the DB probe succeeds.
When authentication is enabled, readiness also requires all authentication migrations/checksums and tables, including additive `0002_admin_google_mfa.sql`, `0003_admin_native_login.sql` and `0004_admin_login_epochs.sql`. This does not prove domain migrations or live Cognito connectivity.

Reserved flags do not enable a feature by themselves. Feature owners must add
explicit boolean parsing, enabled-feature credential validation and safe adapters.
Production readiness must check required integrations rather than silently accept
disabled adapters. Hosted secrets are injected through the selected hosting secret store.

## Browser origins and sessions

Use `http://localhost:5173` with `VITE_API_BASE_URL=/api/v1` in development.
Vite proxies to `127.0.0.1:5000`; configure Cognito callbacks through the browser origin.
Production requires the same-origin HTTPS proxy documented in
[authentication deployment](authentication-deployment.md). Do not expose the backend
publicly when enabling trusted proxy headers. With the supplied single Nginx proxy,
set `AUTH_TRUSTED_PROXY_HOPS=1`; keep zero for direct development requests.

Customer/admin cookies are separate, HttpOnly, SameSite=Lax, Path=/ and omit Domain.
Hosted names use the __Host- prefix and Secure. A cookie contains only a random
session value; MySQL stores its hash. Tokens/verifiers stay encrypted on the server.
Mutations require the exact Origin and a session-bound X-CSRF-Token. OAuth callbacks
instead require single-use state/nonce/PKCE and the flow-binding cookie.

Admin sessions expire after 15 idle minutes or eight hours; customer sessions after
24 idle hours or seven days. Session polling does not extend inactivity. Business
mutations/reads using the guards do extend inactivity; refresh never extends the
maximum duration or MFA authentication time. See [authentication](authentication.md).

## Secrets

Private `.env` files, keys, provider credentials, backups and customer exports are
ignored, but Git ignore rules cannot identify every secret. Review staged diffs.
Never log credentials or customer payloads. Rotate accidentally committed secrets.
Use separate staging and production accounts/destinations, restricted DB users,
and named credential custodians; these operational controls still require handoff.
