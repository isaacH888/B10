# Popssibilities - Technical workspace

Digital Modernization & Catering Management System. Lead Developer: Isaac Hernandez.

## Booking and Google Calendar automation

The catering automation extends the existing React/Vite, Flask, MySQL and Cognito
foundation. Owners can approve availability, reserve capacity, verify external
payments, and operate calendar synchronization at `/admin/automation`. A verified
50% deposit confirms a booking and queues its calendar event, confirmation emails,
and reminders while the remaining balance stays visible. Full payment is not a
prerequisite for the calendar event.

See [setup, deployment, operations and staging checks](docs/calendar-automation.md),
[Google OAuth details and recovery](docs/google-calendar-reference.md), and
[the AWS SAM configuration](infra/automation.yaml). Automation is opt-in through
`AUTOMATION_ENABLED`; external payment verification requires an authenticated owner
to check the actual provider account. No live deployment or Google/SES verification
is implied by the automated mock tests. `/admin` is the team account page;
owners land on the saved-data dashboard at `/admin/dashboard`.

## Current status

Updated November 11, 2026. This DEV integration combines the
latest pushed admin/catering frontend with the shared foundation, backend,
authentication/automation and public homepage work. See the
[latest push integration review](docs/latest-push-integration.md)
for the earlier integration sources and checks. The catering form
calls the real quote/order APIs, invalidates edited quotes and validates
whole-number quantities.
Migration 0008 supplies customer/order/item storage and an atomic handoff into the
existing owner booking workflow. See the
[customer-order intake guide](docs/customer-order-intake.md) for the mapping,
session/CSRF protections, migration and operational limits. The previous
[integration validation report](docs/integration-validation.md) records the October baseline.
The [DEV/TST/PROD workflow](docs/release-workflow.md) includes owner handoff tickets
and the proposed release gates.
The [Bryson index integration review](docs/bryson-index-integration.md) covers
migration 0009, recovery fixes and validation of the latest database branch.
The [reporting query integration](docs/reporting-query-fixes.md) records the
current-booking and CSV fixes for Bryson's reporting helpers and validation with
Anh's owner-order list changes.
The [admin order API integration and UI handoff](docs/ui-handoff-and-admin-api.md)
records the initial owner order integration. The
[admin API completion report](docs/admin-api-completion.md) covers saved Dashboard
and Calendar data, persistent Inventory, flavor allocations, event-date filtering
and protected CSV exports. The [Figma brief for Dillion](docs/dillion-figma-brief.md)
defines the remaining booking and account design work.
The [October DEV publication review](docs/dev-review.md) records that earlier integration.

Customers use
Cognito email/password or Google; invited Owners/Staff use password plus required
Cognito TOTP. Administrator Google sign-in is disabled. Protected admin pages
read saved records and display loading, empty or error states when appropriate.
The backend implements server-side sessions, revocation checks, audits, migrations,
and private provisioning/recovery commands. The public homepage and customer sign-in
use Aneena's uploaded design, integrated with the existing React routes. See the
[public frontend integration](docs/public-site-integration.md) for its source, route
mapping and remaining newsletter work. The customer catering form is at `/order`,
and the owner booking workspace is at `/admin/automation` after authentication and
automation setup.

Order persistence uses `customers`, `orders` and `order_items` after applying all
ten migrations. Migration 0009 adds the `orders.event_starts_at` index; 0010 adds
inventory, stock history and explicit booking allocations. Apply 0010 before
running this version's SQL-backed booking actions. Without DB credentials,
orders use temporary development process memory; inventory requires MySQL.
Quote persistence, server-side expiry/payload matching and trusted delivery-distance
pricing remain release blockers. Browser quote checks do not replace server enforcement.

Signed-in customers can request a sample order confirmation from `/account`.
The backend sends through SES to their current verified Cognito email, with CSRF,
rate limits, and durable duplicate protection. Email remains disabled until the
[customer email setup](docs/customer-test-email.md) is completed. No actual order
or payment is created by that sample action. Booking email automation has its own
[setup and validation guide](docs/calendar-automation.md).

Start with [authentication](docs/authentication.md),
[deployment/configuration](docs/authentication-deployment.md), and
[private account operations](docs/authentication-operations.md). Authentication
requires MySQL, shared application keys and the enabled realm's Cognito configuration;
there are no default users. Development can enable customer sign-in independently
with `AUTH_ENABLED=false` and `CUSTOMER_AUTH_ENABLED=true`. Both authentication
areas are required in hosted environments. See
[customer-only development setup](docs/authentication-deployment.md).

The [original charter](docs/project-charter.md) and dated planning documents are
preserved; the integration report records the current implementation evidence.

## Start here

1. Read [reference alignment](docs/reference-alignment.md) and the [Week 4 plan](docs/week-4-plan.md).
2. Follow [development setup](docs/development-setup.md) to install/run the approved shell.
3. Review [architecture](docs/architecture.md), [API contract](docs/api-contract.md),
   [database mappings](docs/database-integration-review.md) and [decisions/blockers](docs/decisions-and-blockers.md).
4. Use the [dependency map](docs/integration-dependencies.md), [backlog](docs/agile-backlog.md)
   and [Git/PR workflow](docs/development-workflow.md) for owner handoffs and review.

## Checks from the repository root

After installing dependencies using the setup guide:

```sh
backend/.venv/bin/python scripts/check_foundation.py
backend/.venv/bin/python -m ruff format --check backend scripts
backend/.venv/bin/python -m ruff check backend scripts
backend/.venv/bin/python -m pytest -c backend/pytest.ini -q
npm run format:check --prefix frontend
npm run build --prefix frontend
npm run test:browser --prefix frontend
git diff --check
```

Database integration tests skip without `RUN_DATABASE_INTEGRATION=1` and exported disposable
DB settings. November 11 index integration validation passed 1,037 backend tests with
isolated MySQL 8.4.13 and 112 Chromium browser tests. Order intake, replay and
concurrency are exercised against real disposable MySQL. Browser tests otherwise use controlled API/provider
responses. Local evidence does not establish live provider behavior or deployment.
[CI](.github/workflows/foundation-checks.yml) includes MySQL migrations/persistence tests,
frontend build/browser tests and offline Cognito template lint. The latest local
checks and browser counts are in the [admin completion report](docs/admin-api-completion.md).
Review remote results in GitHub Actions; earlier local evidence is in
[authentication validation](docs/authentication-validation.md) and
[foundation validation](docs/foundation-validation.md). No external deployment has occurred.

## Shared deliverables

| Purpose | Files |
| --- | --- |
| Sources, schedule and progress | [References](docs/reference-alignment.md), [assessment](docs/repository-assessment.md), [Week 4](docs/week-4-plan.md), [backlog](docs/agile-backlog.md) |
| Architecture and owners | [Architecture](docs/architecture.md), [dependencies](docs/integration-dependencies.md) |
| Interface agreement | [API guide](docs/api-contract.md), [OpenAPI](docs/api/openapi.json), [synthetic examples](docs/api/examples.json), [DB review](docs/database-integration-review.md) |
| Local configuration | [Setup](docs/development-setup.md), [configuration](docs/configuration.md), [.env.example](.env.example), [Compose](compose.yaml) |
| Collaboration/review | [Workflow](docs/development-workflow.md), [review](docs/code-review.md), [PR template](.github/pull_request_template.md) |
| Integration evidence | [Order workflows](docs/order-workflows.md), [scenarios](docs/integration-tests.md), [validation](docs/foundation-validation.md), [demo](docs/week-4-demo.md) |
| Release and open decisions | [Deployment](docs/deployment-plan.md), [readiness](docs/staging-readiness.md), [register](docs/decisions-and-blockers.md) |

## Team boundaries

| Owner | Assigned work |
| --- | --- |
| Isaac Hernandez | Shared scaffolding/configuration, architecture/contracts, code review, integration, deployment coordination, technical blockers |
| Aneena Paul | Public site, shared visual components, dashboard styling, responsive QA |
| Dillion Nguyen | Catering form, price display, confirmation, admin interactions |
| Anh Hyunh | Pricing, order APIs, status/payment interfaces and exports |
| Shourya Sai Macha | Authentication, email, Google Calendar, reminders and automation |
| Bryson Hawthorne | ERD/schema/migrations/models/queries, integrity and recovery |

Shourya's research and Bryson's entity/attribute draft inform the implementation.
Booking email and Calendar automation are implemented but require live provider
configuration and verification; customer sample email has its own setup guide above.
Docs are shared interface/review guidance,
not a substitute for acceptance or an instruction to overwrite teammate designs.

Keep new code free of emojis; use concise comments and standard hyphens. Do not
commit credentials or real customer data. Teammate feature changes require Isaac's
prior approval. Teammates keep their feature branches and review integration changes
through PRs into `dev`. Accepted release candidates proceed from `dev` to `main`.
Branch protections remain unconfigured; external deployment and production release
are separate reviewed and authorized actions. The original feature branches are
preserved. Ask Isaac before every commit or push. Initial DEV publication was
approved October 29, 2026. Isaac approved the November 3 integration and cleanup
commit/push to `dev` and the November 11 admin API completion publication;
future commits and pushes still require approval.
