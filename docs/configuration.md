# Shared configuration contract

Updated October 5, 2026. Owner: Isaac Hernandez. React/Vite, Flask and MySQL
scaffolding is approved. The shell consumes only the core settings described below;
feature settings are reserved contracts until the named owner implements them.

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
| `VITE_API_BASE_URL` | React; Isaac foundation, Aneena/Dillion consumers | Used by shell health requests; base includes `/api/v1`, without trailing slash |
| `APP_ENV`, `LOG_LEVEL` | Flask; Isaac | Validated and consumed at startup; environment is development/staging/production |
| `APP_TIMEZONE` | Future event/reminder adapters; Anh/Shourya | Reserved America/Chicago display default; not yet used for domain timestamps |
| `APP_SECRET_KEY` | Flask; Isaac foundation, Shourya auth | Loaded as SECRET_KEY; required hosted; no authentication is implemented by this setting |
| `CORS_ALLOWED_ORIGINS` | Flask; Isaac | Comma-separated exact origins; no wildcard, credentials, paths or query; HTTPS required hosted |
| `FRONTEND_ORIGIN` | Future session/CSRF implementation; Shourya | Reserved expected browser origin; shared CORS currently uses CORS_ALLOWED_ORIGINS |
| `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_TLS_CA_FILE` | Flask readiness; Isaac; domain persistence Bryson/Anh | SELECT 1 connection probe; TLS CA enables certificate/hostname verification; hosted values required |
| `MYSQL_ROOT_PASSWORD` | Local Compose; Isaac | Required for initialization only; never passed to Flask |
| `EMAIL_ENABLED`, `EMAIL_PROVIDER`, `EMAIL_API_KEY` | Email adapter; Shourya | Reserved; disabled template; provider and credentials pending |
| `EMAIL_FROM_ADDRESS`, `BUSINESS_NOTIFICATION_EMAIL`, `EMAIL_SANDBOX_RECIPIENT` | Email; Shourya/client | Reserved verified sender, business recipient and staging override |
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

No provider verification/API secrets are added until the adapter and required
permissions are selected. The research's AWS/Stripe settings are not imported.
A full-service rate is not encoded here: the $150 question still needs explicit
confirmation. See [source alignment](reference-alignment.md).

## Startup and health

Hosted startup rejects missing core application/TLS DB configuration and invalid
origins or ports. Development permits blank DB credentials so the shell can start;
`/live` returns 200 while `/health` returns 503 until the DB probe succeeds.
A successful SELECT 1 proves connectivity, not installed domain migrations.

Reserved flags do not enable a feature by themselves. Feature owners must add
explicit boolean parsing, enabled-feature credential validation and safe adapters.
Production readiness must check required integrations rather than silently accept
disabled adapters. Hosted secrets are injected through the selected hosting secret store.

## Browser origins and sessions

Local URLs are `http://localhost:5173` and `http://localhost:5000`; use consistent
hostnames for browser requests. The shell includes credentials in fetch requests,
but no session or CSRF implementation exists yet. CORS allows exact configured
origins and required methods/headers. Disallowed origins receive no allow-origin
header; CORS is not authorization. Dynamic origin responses must vary by Origin.

The proposed cookie contract still needs T02 approval. Shourya must review HTTPS,
SameSite/Secure, CSRF, expiry and browser restrictions before private routes ship.
Same-origin hosted `/api/v1` proxying is preferred if the approved host supports it.
Vite public values are replaced at build time; rebuild when the API URL changes.
See [Vite environment documentation](https://vite.dev/guide/env-and-mode).

## Secrets

Private `.env` files, keys, provider credentials, backups and customer exports are
ignored, but Git ignore rules cannot identify every secret. Review staged diffs.
Never log credentials or customer payloads. Rotate accidentally committed secrets.
Use separate staging and production accounts/destinations, restricted DB users,
and named credential custodians; these operational controls still require handoff.
