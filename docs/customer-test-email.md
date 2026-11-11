# Customer test confirmation email

After customer sign-in, `/account` offers **Send test order confirmation**. It sends one
fixed sample catering confirmation to that customer's currently verified Cognito
email address. Both customer password and Google sign-in use the same feature.
The message has a `[TEST]` subject and says that no real order, booking, or payment
has been created. The browser cannot choose a recipient, subject, or message body.

This release implements only that customer-requested test. The broader seven-event
email workspace, real order/payment triggers, campaigns, contract delivery, and
scheduled workers described in `email-requirements.md` remain future work.

## Application setup

Email is disabled by default. Authentication and the existing customer login
configuration must already work. Apply the additive migrations using the migration
database account, from `backend`:

```sh
.venv/bin/python -m app.migrations
```

Apply the complete migration sequence, including
`0006_customer_test_email.sql`; do not edit applied migrations. The website database
principal needs `SELECT`, `INSERT`, and `UPDATE` on `email_test_messages` and
`email_test_budgets` in addition to its existing authentication grants. Keep migration and private
administrator-provisioning database credentials outside the website environment.

Set these backend-only values in `backend/.env` after SES setup:

```dotenv
EMAIL_ENABLED=true
EMAIL_PROVIDER=ses
EMAIL_AWS_REGION=us-east-1
EMAIL_FROM_ADDRESS=orders@example.com
EMAIL_REPLY_TO_ADDRESS=support@example.com
# Optional: an existing configuration set in the same SES account/region.
EMAIL_SES_CONFIGURATION_SET=
```

Replace the example addresses with your verified sender and monitored business
mailbox. Use bare addresses, without a display-name wrapper. Restart the backend:

```sh
.venv/bin/python -m flask --app app:create_app run --host 127.0.0.1 --port 5000
```

`EMAIL_ENABLED=false` leaves existing authentication available without the email
migration or SES credentials. No frontend environment variable contains credentials.
`EMAIL_SANDBOX_RECIPIENT` is not supported: this feature always targets the signed-in
customer, with ownership checked against Cognito immediately before sending.

## AWS setup remaining

These are manual setup instructions. Implementation and automated tests do not
deploy AWS resources, modify Cognito users, or send email.

1. Open SES in the region selected by `EMAIL_AWS_REGION`. Create or select the
   business sender domain, publish SES-provided DKIM DNS records, and wait for
   verification. Configure aligned SPF/DMARC and a monitored reply mailbox. An
   individually verified sender address also works for initial testing.
2. Check the SES account's sandbox status in that same region. While in the
   sandbox, verify the exact email address of every customer participating in this
   test using SES's verification process. Cognito email verification does not
   substitute for SES recipient verification. To reach arbitrary signed-in
   customers, request SES production access; the sender still must be verified.
   [AWS sandbox and production-access instructions](https://docs.aws.amazon.com/ses/latest/dg/request-production-access.html)
3. Retain SES account suppression and bounce/complaint feedback forwarding to a
   monitored mailbox. Optionally create a configuration set and event destinations
   for delivery/bounce/complaint monitoring and set `EMAIL_SES_CONFIGURATION_SET`.
   This customer test does not consume feedback events or claim inbox delivery.
4. Grant a dedicated mailer workload role only `ses:SendEmail` on the chosen sender
   identity and, when used, the exact configuration-set ARN. Restrict
   `ses:FromAddress` to `EMAIL_FROM_ADDRESS`. The optional
   [CloudFormation policy template](../infra/customer-test-email.json) prepares that
   policy without attaching it or creating sender identities. Review the policy
   before deploying; do not attach Cognito account-management permissions to the
   website. [SES action/resource reference](https://docs.aws.amazon.com/service-authorization/latest/reference/list_sesv2.html)
5. Use an ECS task role, EC2 instance role, or environment-configured web-identity
   workload role for hosting. The mailer deliberately ignores `AWS_PROFILE`, shared
   credentials/config files, and generic `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`
   values so that the developer's private AWS operator session is not reused.
   For local testing only, inject credentials for a separate, narrowly scoped
   mailer principal through `EMAIL_AWS_ACCESS_KEY_ID`,
   `EMAIL_AWS_SECRET_ACCESS_KEY`, and `EMAIL_AWS_SESSION_TOKEN` when temporary.
   Prefer temporary credentials; never paste them into chat, frontend code, shell
   history, or committed files. Refresh them through the same private local method
   used to obtain them. Do not enable SDK HTTP/debug logging of request bodies.

The application sends through the SES HTTPS API; SMTP credentials and passwords are
not used. Generic SDK endpoint overrides are ignored by this adapter.

## Request and failure behavior

`POST /api/v1/customer/test-email` requires an active customer session, exact trusted
origin, valid CSRF token, empty JSON object, and a UUIDv4 `Idempotency-Key`. Admin
sessions do not authorize the endpoint. The backend reloads the verified customer
profile from Cognito, ignoring a browser-provided or stale cached email address.

The durable attempt ledger limits sends to one per second globally, 60 per UTC
calendar day, three per customer per UTC hour, and three per recipient per UTC hour.
Reusing the same key after acceptance returns the recorded result without sending
again. Concurrent calls with the same key cannot submit duplicate emails. Limits
also apply to rejected/uncertain provider attempts to prevent repeated abuse.
Retain attempt records for at least 30 days; there is no automatic purge in this
release. Deleting a record removes its duplicate protection, so replaying an old
key after manual deletion can cause another send. Restrict database cleanup to
private operators following the project's retention policy.

An SES `MessageId` means **accepted by SES**, not inbox delivery. The adapter makes
one bounded send attempt with no SDK automatic retry. If a timeout, malformed
success response, or process/request failure leaves the outcome unknown, the record
remains uncertain and the same key never resends it automatically. Check SES
monitoring and the inbox before starting another attempt.

Public errors are safe summaries: `email_verification_required` (403),
`email_delivery_uncertain` (409), `email_rate_limited` (429), and
`email_unavailable` / `email_rejected` (503). An unconfigured sender, sandbox
restriction, expired mailer credentials, or paused SES account requires configuration
repair before retry. Existing session-expiration/CSRF errors retain their normal
authentication behavior.

## Verification

Offline provider tests use Botocore stubs, and browser tests mock the API. They
validate the single-recipient request, escaped HTML/plain text, disabled mode,
credential isolation, rate limits, duplicate requests, authorization, and ambiguous
outcomes. They do not verify live Cognito/SES integration or inbox delivery.

Local checks on October 15, 2026: 428 backend tests passed, 77 skipped; all 61
browser tests passed with mocked APIs, including 14 customer-email scenarios.
Frontend build, foundation/OpenAPI checks, and both CloudFormation template lints
passed. The skips include all 16 new MySQL integration scenarios; Docker Desktop
was stopped and the default daemon was inaccessible, so no disposable MySQL run
was possible. CI is configured to run those tests against its MySQL 8.4 service.
No live AWS deployment, Cognito mutation, or real email send was performed.

After completing setup, test using your own customer account:

1. Sign in as a customer with email/password and open `/account`. Click **Send test
   order confirmation** once. Confirm acceptance in the page and receipt of one `[TEST]`
   message at that customer's verified email address; check spam as well.
2. Repeat with a Google customer account whose SES recipient is verified if the
   account is still in the sandbox. Confirm the message goes to that signed-in
   customer rather than the previous account.
3. Sign out, sign in as an admin, and verify neither session can send through the
   customer endpoint. An expired customer session must require login again.
4. If acceptance is reported without inbox receipt, inspect the SES event
   destination or feedback mailbox. Record separately whether the request was
   accepted, delivered by SES, and observed in the inbox.

No real order or payment should appear as a result of any of these tests.
