# Automation validation - November 1, 2026

The implementation extends the repository's existing Flask/MySQL/Cognito and
React stack. External Google, SQS, Scheduler, SES and Cognito calls in automated
tests use injected fakes or mocked HTTP. No AWS resources were deployed and no live
customer, payment provider or AWS delivery was tested. Local OAuth setup and
read-only Google diagnostics are described below.

## Checks performed

- Full backend suite: `backend/.venv/bin/python -m pytest -c backend/pytest.ini -q`.
  **476 passed, 63 skipped** in 18.84 seconds after the migration-history,
  connection-status and AWS credential-store fixes. Of these, the new automation
  tests contributed **157 passed and 2 skipped**.
  The remaining skips belong to the
  existing suite's environment-dependent checks.
- Frontend: `npm run build --prefix frontend` passed.
- Browser suite: all **50 tests passed** with Playwright 1.64.0 and the installed
  Chromium **149.0.7827.55**, including the new owner payment/repair, staff denial,
  and protected booking-link cases. The pinned Chromium 156 executable was absent;
  its download was interrupted. A temporary config supplied `launchOptions.executablePath`
  for the installed browser and left the repository's CI configuration unchanged.
  Run `npx playwright install chromium` and the normal browser command in CI to
  verify the pinned browser there; no remote CI result is claimed.
  After the connection-status fix, all **7 Calendar dashboard browser cases**
  passed on the same installed Chromium, including four new cases for independent
  status loading, inline API errors, missing setup, and stale-connection clearing.
- CloudFormation: `cfn-lint 1.57.2` passed for both
  `infra/cognito-authentication.json` and `infra/automation.yaml`.
- `scripts/check_foundation.py` passed (OpenAPI/schema examples, links,
  configuration placeholders and shared foundation checks).
- `git diff --check` passed.
- After the calendar-provisioning follow-up, the Google, Calendar worker and
  owner-route suites passed together: **76 passed**. These include definitive
  creation rejection retries, ambiguous-outcome duplicate prevention, and safe
  messages for both legacy and structured Calendar API-disabled errors.

## Meaningful coverage

Domain and service tests exercise verified half deposits while balances remain,
integer rounding, globally unique payment references, expired reservations,
concurrent capacity approval, cancelled-payment retention, reopening, owner
review, and transaction rollback. Actual session/role/CSRF guards are exercised
using the existing offline Cognito provider fixtures.

Stateful Google fakes exercise stable event IDs, duplicate/conflicting inserts,
ownership checks, rescheduling, pending-create cancellation, stale revisions,
crashes around mapping persistence, explicit deletion repair, revoked consent,
reconnect, refresh-token preservation, and callback state binding/expiry/reuse.
Additional races verify that old Google failures cannot overwrite a newly
reconnected grant or an explicit disconnect, and that old exhausted jobs cannot
mark newer booking revisions failed.

Reminder/delivery tests exercise local calendar-day calculations across DST,
fold/gap policies, bookings inside seven days, stale schedules, payment/count
suppression, FIFO group failure handling, publication crashes, retry exhaustion,
audited replay, and delayed old-generation messages. An assembled service test
runs real domain/outbox/worker code through deposit, emails, calendar create,
reschedule, full-payment count-only reminder and cancellation with external fakes.

The Lambda WSGI bridge preserves multiple cookies and repeated query values.
The packaging test verifies that private environments, tests and caches are
excluded from Lambda source artifacts.
Mocked credential-store tests cover expired console login, denied secret access,
missing credentials or optional dependencies, malformed JSON, bounded retries,
missing-secret creation, and clearing a token secret without deleting its resource.

## Unperformed checks and limits

Disposable MySQL tests remain skipped because no isolated test database was
configured. During initial validation, Docker Desktop's configured daemon was
unavailable and the alternate system socket was inaccessible. The two new
database integration tests cover concurrent approvals/payment identity and
transaction rollback/state consumption/nested advisory locks. They are included
in the existing CI MySQL 8.4 job. The database tests must run successfully there
or in an isolated staging database before release; memory tests do not verify
InnoDB behavior. No existing development database was changed during that initial
validation.

After the owner started the local MySQL server, its history revealed applied
`0005_admin_recovery.sql` and `0006_customer_test_email.sql` from the email branch.
Those original files were restored from commit `cb9c4ba`, with SHA-256 checksums
matching the database exactly. The unapplied automation migration was renumbered
to `0007_booking_automation.sql`. Running the migration command applied only
that new additive migration; a second run returned `Migrations complete: already
current`. Existing migration history was preserved. A regression test protects
the two restored checksums and the automation migration's new filename. This
verifies local migration application and repeatability; it does not replace the
isolated MySQL persistence/concurrency tests or live external-service checks.

The local connection-status follow-up enabled automation in the private backend
environment and verified the database-backed status query. Missing configuration
correctly reports `configured=false`; status checks do not fetch credentials.
The owner subsequently supplied the existing Google OAuth secret ARN. The private
backend environment now references it, its region, the matching local AWS profile,
and the exact localhost callback. The optional CRT login dependency was installed
without changing deployed dependencies. After the owner renewed the console-login
session, a real server-side Secrets Manager read succeeded and the app validated
the required OAuth client fields. No credential values were printed or requested
from the owner. Successful Google consent, refresh and Calendar operations still
require the live owner connection flow. A regression also checks that a successful
callback returns the owner to the automation connection controls.

During the live owner OAuth flow, Google credentials were stored but calendar
creation left an unresolved provisioning marker. A read-only Calendar request
returned HTTP 403 with `accessNotConfigured` / `SERVICE_DISABLED`; the Calendar
API must be enabled in the OAuth client's project. After the owner confirmed
there was no **Popssibilities Catering** calendar in Google Calendar, the stale
marker was cleared under the owner lock and the repair was audited. Tokens and
booking history were preserved. The local server was restarted with the fix
that clears the marker for definitive creation rejections while retaining it
for unknown outcomes. Successful live calendar creation remains unverified.

SAM's full container build and deployment were not performed. TLS CA packaging,
actual IAM grants, secret contents, Google consent/refresh, SQS/Scheduler delivery,
SES deliverability and the same-origin production proxy need the documented
[staging acceptance checks](calendar-automation.md#staging-acceptance-checklist).

External payments require an owner to verify the actual provider record. SES
may duplicate an email if acceptance succeeds before a crash prevents recording
that success. Ambiguous calendar provisioning requires operator recovery instead
of silently creating another calendar. These limits and recovery procedures are
documented in the runbook.
