# Submitted requests: inbox and Google Calendar

An authenticated owner can route future submitted catering requests to a chosen
inbox and their connected Google Calendar. Price-only quote previews do not send
notifications or create events. The public order payload cannot select a mail
recipient, Google account or calendar.

## Workflow

1. A customer submits a priced request. The saved order stays `pending_review`.
2. The dispatcher discovers the committed order and atomically saves its request
   projection and independent email/Calendar outbox jobs. A crash before that
   transaction commits is recovered by the next sweep of saved orders.
3. The selected inbox receives the event schedule/timezone, location, customer
   contact details, quantity, quoted total and private order link.
4. Google Calendar receives a private **Pending request** event, with tentative
   status and transparent availability. It does not reserve capacity. If the
   customer omitted the end, `endTimeUnspecified` marks the display window as
   unspecified; the owner supplies the actual end during booking intake.
5. Intake reuses the projection's ID and Google mapping. Approval and a verified
   deposit update that same event to confirmed/busy. Rescheduling updates it;
   cancellation removes it. Delayed request jobs cannot demote a linked booking.

## Setup

Use the [live setup handoff](calendar-live-setup.md) for the account configuration,
deployment commands and owner activation steps.

Apply additive migration `0012_request_notifications.sql` through the existing
migration runner using the database owner's reviewed migration account. The
runtime identity needs `SELECT`, `INSERT` and `UPDATE` on `automation_requests`,
alongside its existing automation grants. Existing applied migrations are unchanged.

Deploy the updated API **and automation dispatcher/worker code**. The website's
code-only Lambda deployment does not provision the automation stack or update
separate workers. Follow the [automation deployment runbook](calendar-automation.md).
Automatic delivery requires the scheduled dispatcher and FIFO queue consumer;
Flask does not start a background thread.

In `/admin/automation`, as an owner with recent authentication:

1. Select **Connect Google Calendar** and consent using the intended company's
   Google account. See [Google troubleshooting](google-calendar-reference.md).
2. Enter the temporary or business inbox under **Incoming request notifications**
   and select **Use this calendar for incoming requests**.
3. Submit a new synthetic request and verify its inbox message, one tentative
   event and owner-dashboard delivery states.
4. Test intake with a valid contract URL and event end. Confirm that a separately
   verified deposit updates the same event. Only record real payments after the
   owner has independently checked the provider transaction.

The initial inbox value comes from server-only `AUTOMATION_OWNER_EMAIL`; the
owner's selection persists in MySQL. Enabling excludes existing saved requests.
Stopping and re-enabling starts a fresh submission boundary. Already captured
requests retain their original recipient/calendar when future routing changes.

## Local operation and recovery

`AUTOMATION_MODE=local` simulates email and queues. The owner panel explicitly
labels simulated delivery; those messages do not reach an inbox. Real Calendar
calls still need the configured AWS profile to read the Google OAuth client and
store tokens. An expired AWS login blocks connection before Google consent.
Renew it with `aws login --profile YOUR_CONFIGURED_PROFILE`.

Use the runbook's `work-local` command to sweep and consume local jobs. In AWS
mode, SES needs a verified sender and sending permissions; sandbox recipients
must be verified. The app writes Google events directly. Gmail's ordinary-email
event detection is not a reliable catering integration, and customers are not
added as Calendar attendees.

Provider failures do not delete orders or prevent the other provider's job.
Normal queue redelivery does not duplicate completed jobs. SES still has the
documented acceptance/crash window where a retry can duplicate an email; this is
not an exactly-once mail guarantee. Google IDs and ownership metadata converge
retries to one owned event. The owner panel exposes delivery errors, failed-email
retry, Calendar retry and a separate explicit repair action for removed events.
Reconnecting resumes pending request projections without replaying sent email.

Owner/session/CSRF-protected API endpoints:

- `GET /api/v1/admin/automation/requests`: configuration and recent delivery states.
- `POST /api/v1/admin/automation/requests`: `{recipient, enabled}`; recent authentication required.
- `POST /api/v1/admin/automation/requests/<order_id>/retry`: `{}` or explicit `{repair: true}`.
- Failed email replay uses the existing `/jobs/<job_key>/retry` route.

Automated acceptance uses fake Google/mail adapters and a disposable MySQL
database. It does not establish real consent, inbox delivery or active cloud
workers. Complete the live checks above with the account owner.

Local validation includes backend tests with database integration against
disposable MySQL, covering the new migration and request-to-booking lifecycle.
Browser checks cover owner activation, delivery recovery and request controls at
320, 375, 768 and 1440 pixels. Validation also includes the production frontend
build, formatting/lint and shared foundation/link checks. Live Google consent and
email delivery remain pending account activation.
