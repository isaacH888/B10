# Popssibilities - Technical workspace

Digital Modernization & Catering Management System. Lead Developer: Isaac Hernandez.

## Automatic DEV website deployment

The [Shared foundation checks](.github/workflows/foundation-checks.yml) now build a
real Lambda ZIP from the checked commit. Once all existing checks and the package
smoke test pass, a push or merge to `dev` deploys that exact SHA to
<https://n2fffdn5h9.execute-api.us-east-1.amazonaws.com/>. Pull requests build/test
the package without AWS access. CI continues when Learner Lab is off; a deployment
failure appears as a separate failed job.

Deployment preserves `b10-lab-api` in `us-east-1`, Python 3.12, `x86_64`,
`site_handler.handler`, API Gateway payload `1.0`, environment settings, IAM role,
networking and the existing public database CA certificates. It checks the actual
live handler/layout first, compares every frontend file with the live response,
verifies `/release.json` identifies the commit, and requires healthy
`/api/v1/live` and `/api/v1/health` responses. A failed update/verification restores
and verifies the saved previous ZIP where AWS remains reachable. It never runs
database migrations. See the [full setup and recovery guide](docs/lambda-auto-deploy.md).

Before the first deployment:

1. Ask your instructor/AWS administrator to configure the GitHub OIDC provider,
   dedicated deploy role, exact `dev` trust and scoped permissions from the guide.
   Learner Lab may prohibit students from creating them. The existing Lambda
   execution role is a separate role and must be preserved.
2. In GitHub **B10 → Settings → Secrets and variables → Actions → Variables → New
   repository variable**, enter **Name:** `B10_DEPLOY_ROLE_ARN`; **Value:** the
   administrator's `arn:aws:iam::ACCOUNT_ID:role/ROLE_NAME`.
3. Have the database owner compare the deployed schema/history with this commit.
   The local prior package has `0009_automation_scheduled_reminders.sql`, while
   this checkout has `0009_orders_event_start_index.sql`, `0010_admin_inventory.sql`
   and `0011_quotes_persistence.sql`. Resolve any applied-version conflict and
   confirm rollback compatibility. If the workflow reports changed migration
   files, set Actions variable `B10_MIGRATIONS_REVIEWED_SHA` to the exact reviewed
   40-character commit SHA only after that work. This acknowledges review; it does
   not apply SQL or prove the live schema. Dependencies are rebuilt from pinned
   requirements, and changes from the live package are listed in the job summary.
4. Review the uncommitted changes on `chore/dev-lambda-auto-deploy`. No commit,
   push, PR, AWS mutation or live deployment was performed during setup. The named
   `b10-lambda-auto-deploy.zip` attachment was not available in this workspace;
   these files were implemented from the checkout and local prior package, rather
   than extracted from an inspected attachment.

To commit and open the review PR yourself, after reviewing `git diff`:

```sh
git switch chore/dev-lambda-auto-deploy
git add readme.md docs/lambda-auto-deploy.md docs/lambda-auto-deploy-pr.md \
  .github/workflows/foundation-checks.yml \
  backend/site_handler.py backend/tests/test_site_lambda.py \
  backend/tests/test_site_deployment.py scripts/build_site_lambda.py \
  scripts/check_deploy_candidate.py scripts/deploy_site_lambda.py \
  scripts/smoke_site_lambda.py scripts/verify_site_lambda.py
git diff --cached --check
git diff --cached
git commit -m "ci: deploy checked dev builds to the existing Lambda website"
git push -u origin chore/dev-lambda-auto-deploy
gh pr create --repo isaacH888/B10 --base dev --head chore/dev-lambda-auto-deploy \
  --title "Deploy checked dev builds to the existing Lambda website" \
  --body-file docs/lambda-auto-deploy-pr.md
```

The PR body is provided in [this file](docs/lambda-auto-deploy-pr.md). A remote `403` can
still require your own repository access and workflow write permission. Remote
branch creation was not retried because the requested changes must stay uncommitted.

When the lab is back, open **Actions → Shared foundation checks**, select the
latest `dev` run whose four original check jobs and package job passed, then choose
**Re-run jobs → Re-run failed jobs**. This preserves its original SHA and artifact:

```sh
gh run list --repo isaacH888/B10 --workflow foundation-checks.yml --branch dev
gh run view RUN_ID --repo isaacH888/B10
gh run rerun RUN_ID --failed --repo isaacH888/B10
```

Successful checks can coexist with a failed overall run because deployment failed.
An old rerun is rejected if a newer `dev` commit already passed all release checks.
Artifacts/reruns last 30 days; if unavailable, run the workflow on `dev` to rerun
all checks and rebuild its current commit. For an expired older commit, restore it
through a reviewed `dev` change instead of dispatching an unchecked SHA.

The public homepage, its current JavaScript, liveness and database/auth readiness
returned HTTP 200 during the November 14, 2026 setup check. `/release.json` was
404 because this workflow has not deployed yet. **Lab-off uptime is unverified:**
the session state was not observable and no AWS credentials were available. End
your session yourself and repeat the guide's exact package verification from
outside AWS. Lambda/API Gateway resource persistence does not establish MySQL
availability; your instructor must confirm the account's actual stop/expiry rules.

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
mapping and planned social media link. The customer catering form is at `/order`,
and the owner booking workspace is at `/admin/automation` after authentication and
automation setup.

Order persistence uses `customers`, `orders` and `order_items` after applying all
eleven migrations. Migration 0009 adds the `orders.event_starts_at` index; 0010 adds
inventory, stock history and explicit booking allocations; 0011 adds stored quotes.
Apply all pending migrations before running this version's SQL-backed routes.
Orders enforce the stored quote's 15-minute expiry, matching catering/event details
and one-time use, and retain its trusted price and delivery fee. Quote comparisons
trim text consistently, and concurrent submissions preserve idempotency without
locking missing keys. Without DB credentials, quotes and orders use temporary
development process memory; inventory requires MySQL.

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
[foundation validation](docs/foundation-validation.md). These local checks do not
verify a new live deployment; see the automatic deployment section for observations
of the existing website and outstanding AWS verification.

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
