# Development, test and production workflow

Owner/coordinator: Isaac Hernandez. Prepared October 29, 2026.
Current evidence and limitations are in [integration validation](integration-validation.md).
This is the proposed release process; automatic deployments are not configured.

## Immediate sequence

1. Review the [pending DEV changes](dev-review.md), then obtain Isaac's explicit
   approval before committing or pushing `dev`. Preserve the original backend and
   authentication commit histories in the integration merge. Ask Anh and Shourya to
   review the shared Flask setup and order authorization; Bryson reviews the
   order/database findings. Require actual GitHub CI results after publication.
2. Create the owner tickets below with a target date and acceptance evidence.
   Keep changes in short feature/fix branches with focused PRs into `dev` and tests.
3. Select the DEV/TST/PROD host, URLs, resource ownership and costs. The earlier
   [deployment plan](deployment-plan.md) lists infrastructure decisions still needed.
4. Make the complete ordering flow pass in DEV, including a real disposable
   database, the actual frontend, configured test identity provider and test email.
5. Promote an identified build to TST for independent testing and business acceptance.
   Promote that same accepted build to PROD after release approval and recovery rehearsal.

## Environment responsibilities

| Environment | Purpose | Entry/exit evidence |
| --- | --- | --- |
| DEV | Developers integrate features using isolated development data and test provider resources | PR review/CI; fresh migrations; real UI-to-API-to-DB order flow; dependency failures and retry tests |
| TST | Team/client test an identified release candidate in a stable environment | All critical tickets closed; independent regression/UAT; configured login and test email; migration, backup/restore and rollback evidence; signed acceptance |
| PROD | Serve the approved release | Accepted TST artifact/SHA, release approval, controlled migrations, smoke checks, monitoring and named incident/rollback owners |

Keep separate databases, application/provider credentials and exact frontend origins
for each environment. Use synthetic data and designated test recipients in DEV/TST.
Each environment needs its own Cognito configuration and session encryption keys.

The code currently accepts `APP_ENV=development`, `staging` or `production`.
Use `development` locally, `staging` for hosted DEV/TST, and `production` for PROD.
`APP_ENV=tst` is invalid. Hosted profiles require authentication and verified TLS
database settings. Keep `VITE_API_BASE_URL=/api/v1` and route API requests through
the website origin. Use a production WSGI process for hosted Flask environments.

## Review, build and promotion

- Each issue records its owner, user-visible acceptance criteria and dependencies.
- Every feature/fix PR runs Python lint/format, contract checks, backend/MySQL
  tests, frontend format/build/browser tests and infrastructure lint.
- Combine reviewed feature PRs in `dev`; review an accepted release candidate
  through a PR from `dev` to `main`. Record the commit SHA, immutable build
  artifacts, dependency locks and migration versions. Keep environment configuration
  separate from the artifacts. A branch push or merge does not itself deploy the app.
- Deploy that release to DEV, then promote it to TST and PROD with a recorded
  environment gate. Any source change creates a new build and restarts testing.
- Record the release scope, test results, unresolved nonblocking issues, approver,
  migration/backup actions, monitoring and previous compatible release.
- Keep new outbound order workflows disabled until their duplicate/failure behavior
  has been demonstrated. Include provider setup and database schema checks in the
  release gate; `/live` and `/health` alone do not establish order readiness.

## Coordination tickets

These are local handoff drafts, not issues already created in GitHub.

| ID / priority | Proposed owner | Issue and evidence | Acceptance criteria |
| --- | --- | --- | --- |
| INT-01 / blocker | Bryson + Anh | Six migrations create auth/email tables only. `customers`, `orders`, `order_items` are absent; a valid database-backed POST returns 503. | Agree lossless contract/schema mappings; fresh additive domain migrations; real create/retrieve/status transaction tests, rollback and restart durability; schema readiness evidence. |
| INT-02 / blocker | Anh + Isaac for business decisions | Quote IDs are generated without durable storage or expiry/revision/payload checks; delivery without measured distance is priced at zero miles. | Persist/validate quotes; enforce expired/mismatched quote responses; approved distance mechanism or explicit manual-review response when distance is unknown; no understated accepted delivery price. |
| INT-03 / high | Anh + Bryson | Database replay reads mutable `response_json`; concurrent same-key submissions have no demonstrated database handling. | Preserve the original submission response; enforce uniqueness atomically; parallel same-key requests create one order; altered payload returns 409; status changes do not alter replay. Depends on INT-01. |
| INT-04 / blocker for full ordering | Dillion + Aneena, with Anh | Current frontend provides login/account pages and synthetic dashboard bookings; the real quote/order APIs are not connected. | Catering form, server-supplied prices, stable retry key, confirmation and authorized real order retrieval/status controls; browser tests against the running API and database. |
| INT-05 / high | Shourya + Bryson, with Anh | Customer email is a manually triggered sample; order submission does not enqueue confirmation jobs. | Atomically persist required order/email work; approved test customer/business recipients; durable duplicate protection; provider failure leaves orders intact and supports visible retry/reconciliation. |
| INT-06 / environment blocker | Isaac + Shourya; Bryson for database | Preview session endpoints return 503 until database and both Cognito clients are configured. Hosted environments, URLs and release pipelines are not established. | Isolated DEV/TST/PROD configuration, working invited owner/staff and customer login in TST, test SES configuration, scoped deployment workflow, monitoring and recovery ownership. |

The order-auth integration gap found during this review is fixed locally and covered
by 12 added cases. Anh and Shourya should review those changes before PR acceptance.
Pricing/payment/export/Calendar functionality outside the existing implementation
must be explicitly included in or excluded from the release scope.

## TST scenarios and release decision

Run the actual browser against the actual backend and isolated MySQL. Capture
results for quote-to-order submission, minimum/invalid inputs, unknown delivery
distance, expired/mismatched quotes, retries/concurrent duplicate submissions,
owner/staff/customer authorization, CSRF, status version conflicts, database/provider
outages, persistence after restart and email duplicate/failure handling.

Isaac coordinates the readiness review with the component owners and the business
acceptance reviewer. Open critical ordering or access defects keep the full ordering
release in DEV. A deliberately limited authentication/demo release may proceed only
with that limited scope documented and accepted. Production requires a separate
release decision after TST evidence is complete.
