# Popssibilities - Technical workspace

Digital Modernization & Catering Management System. Lead Developer: Isaac Hernandez.

## Current status

Updated October 29, 2026. Local branch `dev` combines
`feature/backend-anh` and `feat/authentication-macha` with the shared foundation.
The pricing, quote, order submission/retrieval/status APIs now register alongside
authentication and customer sample email. Administrative order routes enforce
sessions, CSRF and the existing owner/staff permissions. See the
[integration validation report](docs/integration-validation.md) for checks and gaps.
The [DEV/TST/PROD workflow](docs/release-workflow.md) includes owner handoff tickets
and the proposed release gates.
The [DEV publication review](docs/dev-review.md) summarizes the pending changes
for approval before committing or pushing.

Customers use
Cognito email/password or Google; invited Owners/Staff use password plus required
Cognito TOTP. Administrator Google sign-in is disabled. A protected sample admin
dashboard displays clearly labeled synthetic bookings after successful sign-in.
The backend implements server-side sessions, revocation checks, audits, migrations,
and private provisioning/recovery commands. React has basic login and session pages;
the catering form and real order dashboard are not implemented.

Order persistence is blocked: existing migrations create auth/email tables but no
`customers`, `orders` or `order_items` tables. Database-backed submission returns
503; without DB credentials, orders use temporary process memory. Quote persistence,
expiry matching and verified delivery-distance pricing also remain unfinished.

Signed-in customers can request a sample order confirmation from `/account`.
The backend sends through SES to their current verified Cognito email, with CSRF,
rate limits, and durable duplicate protection. Email remains disabled until the
[customer email setup](docs/customer-test-email.md) is completed. No actual order
or payment is created; the wider email automation remains pending.

Start with [authentication](docs/authentication.md),
[deployment/configuration](docs/authentication-deployment.md), and
[private account operations](docs/authentication-operations.md). Authentication remains
unavailable until MySQL and both Cognito clients are configured; there are no default users.

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
DB settings. October 29 validation passed 786 backend tests with isolated MySQL
8.4.13 and 63 Chromium browser tests. Order SQL tests use mocks; real auth/email
persistence tests use MySQL. Docker is unavailable on this machine, so a temporary
MySQL server was used without changing the development database.
[CI](.github/workflows/foundation-checks.yml) includes MySQL migrations/persistence tests,
frontend build/browser tests and offline Cognito template lint. Review remote results in GitHub Actions; local evidence is in
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

Shourya's research and Bryson's entity/attribute draft inform the implementation;
business email automation and Calendar remain pending; customer sample email has
its own setup guide above. Docs are shared interface/review guidance,
not a substitute for acceptance or an instruction to overwrite teammate designs.

Keep new code free of emojis; use concise comments and standard hyphens. Do not
commit credentials or real customer data. Teammate feature changes require Isaac's
prior approval. Teammates keep their feature branches and review integration changes
through PRs into `dev`. Accepted release candidates proceed from `dev` to `main`.
Branch protections remain unconfigured; external deployment and production release
are separate reviewed and authorized actions. The original feature branches are
preserved. Ask Isaac before every commit or push. Initial DEV publication was
approved October 29, 2026.
