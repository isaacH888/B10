# Catering booking and Google Calendar automation

This implementation extends the existing React/Vite, Flask, PyMySQL and Cognito application. The authoritative record is MySQL. The owner opens `/admin/automation` from the authenticated dashboard at `/admin`; private booking links are `/admin/bookings/<id>`. Every automation endpoint requires an active administrator session with the **owner** role; changes also require CSRF and recent authentication. Staff and customer accounts cannot operate this workflow.

The charter's **50% deposit** confirms a booking after the owner approves availability and reserves capacity. Full payment is not needed for a calendar event. The minimum quantity is 50. Booking status, verified-payment status and Calendar integration status are independent. Money is an integer count of minor currency units; the deposit is `(total_minor + 1) // 2`. A verified payment reference is globally unique. Repeated references cannot increase the balance twice. Payment history is preserved when bookings are cancelled; refunds are an external owner decision.

The initial capacity assumption is 1,000 popsicles reserved across overlapping event intervals, configurable with `AUTOMATION_CAPACITY`. Reservations expire after 48 hours by default, capped at the event start. The owner must check real availability, staffing and venue logistics before approval. An expired reservation followed by a deposit retains the payment and enters owner review instead of silently confirming capacity. Reapproval/reopening checks capacity again. This is a focused automation module; it does not introduce public pricing, customer self-service ordering or a payment processor.

## Source and interfaces

| Area | Source |
| --- | --- |
| Owner operations and payment adapter | `backend/app/automation/domain.py`, `routes.py` |
| Transactional MySQL and offline memory adapters | `backend/app/automation/store.py` |
| OAuth, Secrets Manager, Calendar HTTP adapter | `oauth.py`, `google.py`, `calendar.py` |
| Durable jobs, FIFO dispatch, SES, bounded retries | `delivery.py` |
| Time-zone calculation and Scheduler reconciliation | `reminders.py` |
| Existing Flask -> API Gateway WSGI bridge and Lambda handlers | `runtime.py` |
| Additive schema | `backend/migrations/0007_booking_automation.sql` |
| AWS SAM configuration | `infra/automation.yaml` |
| Placeholders for configuration | `backend/.env.automation.example` |

External adapters can be injected through `AUTOMATION_GOOGLE`, `AUTOMATION_SECRETS`, `AUTOMATION_MAIL`, `AUTOMATION_QUEUE`, `AUTOMATION_SCHEDULER`, or the specific service override in Flask test configuration. `MemoryGoogle`, `MemorySecrets`, `MemoryMail`, `MemoryQueue`, `MemoryScheduler`, and `MemoryStore` support offline tests without production credentials. These are explicitly simulated adapters. AWS clients are lazy and are not contacted at application startup unless a Lambda runtime configuration secret must be loaded.

## Local setup

1. Follow [existing development setup](development-setup.md) and [authentication setup](authentication.md). Keep the existing MySQL database and Cognito pools. Use a provisioned owner with password and TOTP; there is no development identity bypass.
2. Install the pinned backend dependencies in a virtual environment and frontend dependencies using the existing lockfile. Merge `backend/.env.automation.example` into your private `backend/.env`, alongside the existing DB/auth values. Use a real contract URL before customer email delivery. Leave `AUTOMATION_MODE=local` initially.
3. Run additive migrations explicitly with a migration account. Application startup never runs DDL:

   ```sh
   cd backend
   .venv/bin/python -m app.migrations
   .venv/bin/flask --app app:create_app run --port 5000
   ```

4. Run `npm run dev --prefix frontend` in another terminal. Vite proxies `/api/v1` to Flask, preserving same-origin session and CSRF behavior. Sign in as an owner and open the booking automation controls.
5. Create a future catering request with start/end including offsets, IANA time zone, venue, service type, quantity, agreed `total_minor`, currency, customer email and contract URL. Approve availability to reserve capacity and queue the deposit request. Verify an actual external payment in the provider account as described below.
6. Execute local jobs in the **same process** using:

   ```sh
   cd backend
   .venv/bin/python -m app.automation.runtime work-local
   ```

   Mail and schedules are simulated in local mode and summarized by count. Jobs and delivery outcomes remain in MySQL. The command reloads durable jobs on each invocation; a process-local queue is never treated as durable infrastructure. Future local reminder schedules do not automatically wake a process: exercise execution through the automated fake-Scheduler tests or use a configured AWS staging deployment. The standalone `dispatch` command requires AWS mode, where published messages persist in SQS. Google calls remain disconnected until the owner explicitly connects; injected `MemoryGoogle`/`MemorySecrets` enable completely offline Calendar tests. Setting local mail mode does not simulate Google consent.

Run the meaningful automation tests without external credentials:

```sh
backend/.venv/bin/python -m pytest -c backend/pytest.ini -q backend/tests/test_automation_*.py
```

The tests mock Google, SES, Scheduler and SQS; they are not live integration verification. Database integration tests require a separately provisioned, disposable MySQL database and the existing `RUN_DATABASE_INTEGRATION=1` opt-in. Never point destructive test fixtures at a real environment.

## Payment verification

The repository has no existing verified Square/PayPal/Venmo webhook integration. The `ManualPaymentAdapter` implements the charter's external payment approach. An owner independently signs into the provider account, checks that the money was actually received, then records provider/reference, amount in minor units, currency and verification details in the dashboard. Notes should identify the independent provider-account check. A receipt screenshot, redirect success URL, customer claim or browser-supplied payment status is never accepted as verification. Do not put card data or unnecessary banking information in verification notes.

Each payment and its verifying owner/time are recorded atomically with booking changes and uniquely keyed outbox jobs. A 10,001-minor-unit order requires a 5,001-minor-unit deposit and can confirm with 5,000 still outstanding. If capacity was lost or the reservation expired before verification, payment is retained for owner review. Manual verification is the remaining human step and limits full automation. A future signed provider webhook must implement the payment adapter and preserve reference uniqueness; it must verify provider signatures and server-side receipt status before calling the domain service.

## Owner API reference

All paths below begin with `/api/v1/admin/automation`. Browser calls include the existing owner session cookie; every POST also includes `X-CSRF-Token` from the existing authentication session endpoint. POSTs require recent authentication. Responses use the existing `{data, meta}` envelope. Send JSON objects for booking actions, including `{}` when no fields are needed.

| Method and path | Body or result |
| --- | --- |
| `GET /google` | Connection status, persisted calendar ID and useful connection error. |
| `POST /google/connect` | Returns `authorization_url`; the owner's browser follows it to Google. |
| `POST /google/disconnect` | Revokes/erases credentials and returns connection status. |
| `GET /google/callback?state=...&code=...` | Google redirect callback; requires the initiating owner session and consumes state once. |
| `GET /bookings` | Current bookings, balances and Calendar status. |
| `POST /bookings` | Create an owner-entered catering request; example below. |
| `GET /bookings/<id>` | Booking, immutable payment history and job/delivery outcomes. |
| `POST /bookings/<id>/approve` | Optional `reservation_seconds`; reserves capacity and requests deposit. |
| `POST /bookings/<id>/payments` | `reference`, positive integer `amount_minor`, `currency`, `verification_details`, optional `provider`. |
| `POST /bookings/<id>/reschedule` | Required `start`, `end`, `timezone`; optional `venue` and `reservation_seconds`. |
| `POST /bookings/<id>/cancel` | Cancels booking, releases capacity and removes owned calendar projection. |
| `POST /bookings/<id>/reopen` | Required `reason`; rechecks availability and preserved verified payments. |
| `POST /bookings/<id>/final-count` | Optional integer `quantity` (minimum 50); checks capacity for changes and finalizes the current count. |
| `POST /bookings/<id>/retry` | Reconciles current Calendar and reminder state. |
| `POST /bookings/<id>/repair` | Explicit Calendar repair after owner investigation. |
| `POST /jobs/<job-key>/retry` | Audited replay of a failed/dead-letter job; successful/skipped jobs are rejected. |

For booking mutations that accept a JSON body, send `expected_revision` from the latest booking response to detect concurrent dashboard edits; a mismatch returns HTTP 409. Money fields are integers in minor currency units, never decimal floats. Event timestamps require explicit offsets and a valid IANA time zone. Example create body (substitute future dates and owner-approved details):

```json
{
  "start": "2030-02-20T14:00:00-06:00",
  "end": "2030-02-20T16:00:00-06:00",
  "timezone": "America/Chicago",
  "venue": "Example event hall",
  "quantity": 100,
  "service_type": "delivery",
  "total_minor": 10001,
  "currency": "USD",
  "customer_email": "customer@example.test",
  "contract_url": "https://example.test/contracts/catering"
}
```

## Google Cloud and OAuth setup

1. Use an owner-controlled Google Cloud project, enable Calendar API, and configure its OAuth consent screen and publishing/test-user policy for the deployment audience. Create a **Web application** OAuth client.
2. Register the exact callback URL, including scheme, host and path: `https://YOUR_FRONTEND_ORIGIN/api/v1/admin/automation/google/callback`. For loopback development register the exact `http://localhost:5173/...` callback separately. Do not use wildcards or accept a callback URL from browser input.
3. Put `{"client_id":"PLACEHOLDER","client_secret":"PLACEHOLDER"}` in Secrets Manager and configure `GOOGLE_CLIENT_SECRET_ARN`. Grant access only to the API/worker roles. Keep credentials and tokens out of source control, browser bundles and logs.
4. Prefer leaving `GOOGLE_EXISTING_CALENDAR_ID` empty. The app requests `https://www.googleapis.com/auth/calendar.app.created`, creates the dedicated **Popssibilities Catering** calendar and persists its ID. Reconnection reuses this ID. If the owner must use an existing calendar, configure its exact ID, ensure writer/owner access and reconnect with `https://www.googleapis.com/auth/calendar.events`. Switching target calendars requires explicit repair of mapped bookings after reconnection.
5. Sign in as owner, choose Connect Google Calendar and approve offline access. The backend creates cryptographically random, expiring, single-use state bound to both owner and initiating session. The server exchanges the code using the fixed callback and stores tokens in Secrets Manager. When Google omits a new refresh token, the previous one is preserved. Consent expiry/revocation changes integration status to **reconnect required**.

For an OAuth client already stored in Secrets Manager, set its actual
`GOOGLE_CLIENT_SECRET_ARN` in the private `backend/.env`, select the correct
`AWS_PROFILE` if using named local credentials, and set `AWS_DEFAULT_REGION` to
the secret's region. The profile must be authenticated and allowed to read that
client secret and create/update the narrowly scoped token secrets. Do not copy
the secret value into the browser or chat. Restart Flask after environment
changes. `AUTOMATION_MODE=local` simulates mail and scheduling but still needs
real AWS access for real Google credentials. A status response with
`configured=false` explains the missing setup and disables Connect; it only
checks configuration presence and does not fetch or validate the secret.

If the local AWS profile uses console login (`aws login` / `login_session`),
install the optional local credential dependencies with
`backend/.venv/bin/python -m pip install -r backend/requirements-local.txt`.
The pinned SDK requires CRT for this provider; it stays out of the Lambda
dependency list, where execution-role credentials are used. Ensure
`BOTO_DISABLE_CRT` is unset or false. See AWS's [console-login credential
documentation](https://docs.aws.amazon.com/boto3/latest/guide/credentials.html#login-with-console-credentials)
and [optional CRT installation](https://docs.aws.amazon.com/boto3/latest/guide/quickstart.html#using-crt).

The implementation follows Google's [server-side authorization-code flow](https://developers.google.com/identity/protocols/oauth2/web-server) and [Calendar scopes](https://developers.google.com/workspace/calendar/api/auth). See [Google-specific setup and recovery notes](google-calendar-reference.md), including ambiguous calendar-provisioning recovery. The existing-calendar configuration is applied on reconnect; until then the persisted connection calendar is authoritative. Google publishing and testing restrictions depend on the configured consent audience; validate the actual owner's account in staging. Successful mocked OAuth tests do not establish that a real consent screen, account, scope grant or refresh token works.

## AWS deployment

AWS SAM is the single infrastructure tool for this module. It builds the existing Python app and declares Lambda, API Gateway REST proxy, encrypted SQS FIFO plus DLQ, EventBridge Scheduler group/execution role, SES permissions and CloudWatch alarms. It references the **existing** MySQL/VPC, Cognito pools and SES identity; it does not provision replacement authentication or database resources. The existing authentication CloudFormation JSON remains independently managed.

Before deploying:

- Supply existing private subnet/security-group IDs. Allow MySQL TLS connectivity and outbound access through NAT to Google, Cognito and AWS endpoints, or appropriate AWS VPC endpoints plus NAT for Google. Restrict the database application user to the needed tables. Grant `SELECT, INSERT, UPDATE` on `automation_mutex`, `automation_bookings`, `automation_outbox`, `automation_deliveries` and `automation_connections`; `SELECT, INSERT, DELETE` on single-use `automation_oauth_states`; **SELECT/INSERT only** on `automation_payments`; and **INSERT only** on `automation_audit`. Use a separate migration account for DDL. Existing auth grants remain governed by its deployment guide. Do not grant the app payment DELETE or UPDATE privileges.
- Package the current database provider's CA chain under `backend/certs/` and put its deployed path, e.g. `/var/task/certs/mysql-ca.pem`, in the private runtime configuration. Verify the chain/source through your database provider. `DB_TLS_CA_FILE` is required in hosted environments; certificate and hostname verification stay enabled.
- Create an existing runtime Secrets Manager secret containing **string-valued environment settings** for the current app: `APP_SECRET_KEY`, `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_TLS_CA_FILE`, `AUTH_TOKEN_ENCRYPTION_KEY`, and both `COGNITO_CUSTOMER_*` / `COGNITO_ADMIN_*` issuer, client ID, client secret and domain values. Also include `AUTOMATION_CONTRACT_URL` and any nondefault capacity/reservation configuration. Lambda cold-start bootstrap imports this JSON without logging it; explicit Lambda environment settings take precedence. Use the already approved Cognito clients/pools. Update their exact allowed callbacks/logout URLs if deploying a new origin.
- Verify the SES sender/domain in the same region, configure DKIM/SPF/DMARC and bounce/complaint handling, and request SES production access before real customers receive mail. In SES sandbox, verify recipients or use the mailbox simulator. SAM grants SendEmail only on the supplied identity and configured From address. [SES SendEmail prerequisites](https://docs.aws.amazon.com/ses/latest/APIReference/API_SendEmail.html) apply.
- The token-secret prefix must match SAM's scoped IAM resources. Defaults use the AWS-managed Secrets Manager key. If using customer-managed KMS keys, add narrow `kms:Decrypt`/`GenerateDataKey` grants and key policy permissions for the specific role/key before deployment. Set operator notifications on the declared queue-age and Scheduler-DLQ alarms; the template intentionally does not invent an email subscription.

Build and validate with an installed current AWS SAM CLI and Python 3.12:

```sh
sam validate --lint --template-file infra/automation.yaml
sam build --template-file infra/automation.yaml --use-container
sam deploy --guided --template-file .aws-sam/build/template.yaml
```

Supply the declared parameters from your own staging account and review the CloudFormation change set. `RuntimeSecretArn` and `GoogleClientSecretArn` are secret ARNs, not credentials. This repository does not perform deployment or fabricate parameter values. All four functions use the included `backend/Makefile` and `backend/scripts/build_automation_lambda.py`: install pinned dependencies, then copy only `app/` and optional `certs/`, excluding `.env` and caches. Private backend environments, local virtual environments, tests and migration credentials are excluded by this source allowlist. Confirm no credentials enter deployment artifacts.

Route the existing frontend's `/api/v1/*` path to the stack's `ApiOrigin` (`/live` stage), preserving methods, bodies, cookies, query strings, Origin and all Set-Cookie response headers. Disable CDN caching on API/auth paths and OAuth callbacks. Keep the private dashboard under the same exact HTTPS origin configured in `FrontendOrigin`; never use a separate cross-origin browser API base. Use the existing web hosting/proxy instead of replacing it. API Gateway does not supply a second identity system: the existing server-side Cognito sessions, MFA, owner-role checks, CSRF and revocation checks authorize every request. Restrict direct-backend/proxy headers according to your hosting design; Lambda uses API Gateway's trusted source IP and does not trust arbitrary forwarded IP headers.

SAM enables `ReportBatchItemFailures`. Workers block later records in a failed booking's FIFO group while allowing independent booking groups to proceed. The deployed worker batch size is one, timeout 180 seconds, delivery lease 240 seconds and queue visibility 1,080 seconds (six times worker timeout); local class/test defaults can be shorter. Scheduler uses revision-specific one-time UTC `at(...)` schedules with automatic deletion and a bounded target-delivery policy. Its FIFO target requires content-based deduplication, enabled on the queue. These settings follow [SAM SQS configuration](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/sam-property-function-sqs.html), [Lambda SQS failure handling](https://docs.aws.amazon.com/lambda/latest/dg/services-sqs-errorhandling.html), and [Boto3 Scheduler CreateSchedule](https://docs.aws.amazon.com/boto3/latest/reference/services/scheduler/client/create_schedule.html), checked during implementation.

## Reliability and reminder semantics

The deployment build uses SAM's documented [custom Makefile build targets](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/building-custom-runtimes.html) and `ARTIFACTS_DIR` output directory. Local validation results are recorded in [automation validation](calendar-automation-validation.md).

Business updates, verified payment records and uniquely keyed outbox rows commit in one MySQL transaction. The dispatcher reads committed jobs, records expiring publication leases, publishes outside the transaction and marks jobs published afterward. If SQS accepts a message and the process crashes before MySQL persistence, the dispatcher retries with the same deduplication ID. Consumer delivery records protect against duplicates beyond SQS's deduplication window. Each job is grouped by booking ID. Short database transactions use a shared durable mutex for capacity decisions and claims; per-booking advisory locks serialize external work with owner mutations. This conservative MVP favors correctness over high throughput; see the [MySQL 8.4 locking reference](https://dev.mysql.com/doc/refman/8.4/en/innodb-locks-set.html).

Calendar workers always reload authoritative state. Stable base32hex-compatible event IDs and private application/booking/owner metadata recover a successful Google insert followed by a database crash. Conflicts with other ownership metadata require repair instead of overwriting an unrelated event. Rescheduling updates the same event; cancellation converges to absence even if an older creation message arrives afterward. Synced revision updates use a current-revision check. Calendar payloads include booking reference, service type, venue, start/end, IANA time zone and private dashboard link. No customer attendees or unnecessary customer details are added.

Final-payment reminders run **seven local calendar days before the event at the event's local start time**, as a reminder date rather than a new payment deadline. `AUTOMATION_COUNT_REMINDER_DAYS` independently controls the count-request offset; default 7 combines the requests into one email. If the resulting local wall time falls in a DST fold, choose the first occurrence. If it falls in a DST gap, shift forward by the gap (02:30 -> 03:30 for a one-hour transition, including support for non-hour changes). Convert that resolved instant to a UTC one-time schedule so Scheduler's own skipped-time behavior cannot silently omit it.

A durable reminder plan belongs to each `schedule_revision`. Rescheduling replaces schedules, cancellation removes them, and every execution rechecks current status and revision. At send time the service also rechecks remaining verified balance and finalized count. Full payment removes payment wording while retaining an outstanding count request. If a booking is confirmed inside seven days, all overdue requests combine into one immediate outstanding-items message; replaying schedule reconciliation does not create another immediate message. Separately configured future count requests retain their own schedule. If nothing is outstanding, no email is sent.

Exactly-once calendar projection is approached through deterministic IDs and metadata checks; email delivery has a narrower guarantee. SES `SendEmail` has **no idempotency token**. A process crash or ambiguous timeout after SES accepts a message but before MySQL records success can produce a duplicate email when retried. Transactional effect records, leases and stable correlation tags prevent normal duplicate messages, but cannot eliminate this provider boundary. Do not claim exactly-once SES delivery. Investigate SES delivery events and the job's provider ID before manually replaying an ambiguous send. A future provider with idempotency keys or a provider-side deduplication service can close that gap.

## Owner runbook

| Situation | Action and expected result |
| --- | --- |
| Connection unavailable | Read the inline error. Ensure `AUTOMATION_ENABLED=true`, restart Flask after environment edits, and check owner authentication and database readiness. Calendar status loads independently of booking-list failures. |
| AWS login expired when connecting Google | Run `aws login --profile YOUR_AWS_PROFILE` in the local operator terminal and complete browser authentication. Use the profile configured in the private backend environment, then retry. Local console-login profiles also require the optional `requirements-local.txt` dependencies. Never paste AWS credentials or the OAuth secret value into chat. |
| Calendar pending | Allow the one-minute dispatcher tick; inspect booking jobs, worker errors and oldest queue age if it persists. |
| Reconnect required | Owner selects Reconnect, grants the required scope, then Retry on affected bookings. Reconnection preserves calendar ID and available refresh token. |
| Disconnect | Owner disconnects in the dashboard; server revokes/deletes credentials. Existing events and payment records remain. Reconnect before further sync. |
| Temporary Google failure | Bounded exponential delays (30, 60, 120, 240, 480 seconds before the sixth attempt; configurable 900-second cap), at most six attempts; failure becomes visible and enters the FIFO DLQ. |
| Invalid event data | Correct start/end/time zone/venue/service through Reschedule, then Retry; static useful errors contain no provider tokens. |
| Event manually deleted | Inspect the calendar, then owner chooses Repair. The app checks ownership, uses a new event generation when needed and persists the repaired mapping. Ordinary retries do not silently recreate a mapped event whose deletion may have been intentional. |
| Calendar changed | Configure target, reconnect with the correct scope/access, then Repair. The app removes the owned old-calendar event before recreating on the selected calendar; inaccessible old calendars require restoring access before repair. |
| Reopened booking | Owner explicitly reopens and reserves capacity; verified payment history remains. Capacity is checked again. Reopened confirmed bookings reuse/repair mappings deliberately; no automatic refund or capacity bypass occurs. |
| Exhausted/failed job | Inspect booking job/delivery rows in the owner view. Fix the cause, then replay that failed job using its Retry control or owner-only `POST /api/v1/admin/automation/jobs/<job-key>/retry`. Replay is audited and creates a new delivery generation; delayed messages from earlier generations are harmless. Never bulk-redrive unknown jobs blindly. |
| Scheduler delivery DLQ | Alarm on the separate standard `SchedulerDeadLetterQueueUrl`. Inspect original `scheduled_reminder` payload and AWS failure attributes, correct IAM/queue configuration, and replay it through `queue_handler` using an operator-controlled Lambda test event. The worker materializes one durable job and rechecks status/revision. Acknowledge the DLQ message only after successful processing or a confirmed obsolete skip. |
| Native work-queue DLQ | The DLQ consumer persists visible `dead_letter` delivery status before acknowledgment. Investigate database audits and controlled per-job replay. DLQ diagnostics contain job keys rather than customer details. |
| Late deposit / owner review | Review the preserved verified payment and availability. Reapprove only when capacity is available; otherwise coordinate with the customer externally. |
| Database contains migrations unknown to this release | Compare `schema_migrations` with the checkout. Preserve applied history and restore the original migration files with matching checksums from the branch that applied them. This release includes the unchanged `0005_admin_recovery.sql` and `0006_customer_test_email.sql` from the email branch, followed by `0007_booking_automation.sql`. Do not delete history rows or disable migration checks to resolve a branch mismatch. |

Owner Retry for a booking reconciles its current Calendar/reminder state; per-job replay supports failed confirmation/deposit/reminder messages. A successful/skipped email job cannot be replayed accidentally. Audit rows record owner actions and payment verification; avoid direct SQL edits. Do not delete payment rows to undo a booking. Before restoring a database backup, pause dispatch/consumers, reconcile existing Google events using metadata and IDs, and review any mail delivery outcomes that are ambiguous across the restore point.

## Staging acceptance checklist

Use synthetic bookings and owner-controlled email/calendar accounts. These are **live checks to perform**, not claimed results:

1. Apply all migrations on isolated MySQL, verify least-privilege runtime grants, TLS hostname validation and transaction rollback. Confirm schema checksums and repeatable migration execution.
2. Exercise the real owner Cognito password/TOTP session and CSRF. A customer, staff account, logged-out browser and forged owner header must receive denial for every automation action, including callbacks and private links.
3. Complete real Google consent, reject consent once, try expired/reused state and another browser session. Check tokens stay server-side and reconnect reuses the dedicated calendar. Verify offline refresh after access-token expiry.
4. Approve a 100-pop order totalling 10,001 minor units, verify 5,001 independently, and observe one event plus customer summary/contract and owner notice while 5,000 remains outstanding. Replay the payment reference; balance and event count remain unchanged.
5. Deliver duplicate/out-of-order jobs, reschedule, cancel while create is pending, reopen, and simulate a crash after Google insertion. Confirm one owned event, stable mapping, correct current revision and converged cancellation.
6. Revoke consent externally, deny calendar access, manually delete an event and change calendars. Verify reconnect/correction/repair states and owner repair behavior without overwriting unrelated events.
7. Exercise a controlled transient Google 429/5xx, queue publication failure and DLQ exhaustion. Verify bounded backoff, group isolation, visible failures, audited replay and alarm routing.
8. Schedule across spring/fall DST, confirm inside seven days, fully pay before execution and finalize counts independently. Confirm no stale reminder after reschedule/cancellation and no payment wording for paid bookings.
9. Use SES sandbox or simulator recipients to verify actual delivery, sender authentication, contract links, bounce/complaint handling and correlation with delivery rows. Record the known ambiguous-send duplicate boundary.
10. Inspect CloudWatch/API logs and deployment artifacts for secrets/customer details, test protected same-origin dashboard deep links, verify cache bypass/cookie preservation, and record stack outputs/rollback procedures before real customers use it.

Automated tests cover domain, adapters, authorization, race/retry behavior and DST using mocked external services. A staging deployment, live Google/SES/SQS/Scheduler verification, production access approval and business acceptance remain deployment work; they are not established by passing unit tests.
