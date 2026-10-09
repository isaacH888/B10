# Popssibilities - Technical workspace

Digital Modernization & Catering Management System. Lead Developer: Isaac Hernandez.

## Current status

Updated October 9, 2026. Branch `feat/authentication-macha` adds customer and admin
authentication to the approved React/Vite + Flask + MySQL foundation. Customers use
Cognito email/password or Google; invited Owners/Staff use password plus Cognito
TOTP or explicitly approved Google plus application TOTP. Both admin methods share
the canonical role and access status; matching emails never grant or link access.
The backend implements server-side sessions, CSRF, role guards, revocation checks,
audits, migrations, and private provisioning/recovery commands. React has basic
login and protected session pages for testing; frontend design remains undecided.
Cognito templates are prepared; no live cloud resources
or accounts have been created. Business ordering/pricing/payment features remain pending.

Start with [authentication](docs/authentication.md),
[deployment/configuration](docs/authentication-deployment.md), and
[private account operations](docs/authentication-operations.md). Authentication remains
unavailable until MySQL and both Cognito clients are configured; there are no default users.

The supplied dated plan puts Week 4 on October 5-9: form/pricing/DB integration,
first staging build and team demo. Those runtime milestones remain blocked on owner
handoffs and decisions. Calendar is Week 5; reminders/deposit-contract automation
Week 6. Feature freeze October 23, release lock November 6, submission November 9.
The [original charter](docs/project-charter.md) is preserved verbatim.

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
backend/.venv/bin/python -m pytest -c backend/pytest.ini -q
npm run build --prefix frontend
git diff --check
```

Database integration tests skip without `RUN_DATABASE_INTEGRATION=1` and exported disposable
DB settings. Local validation used isolated MariaDB 11.8; MySQL 8.4 remains the CI target.
Compose was not run because Docker daemon access is unavailable.
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
email and Calendar services remain pending. Docs are shared interface/review guidance,
not a substitute for acceptance or an instruction to overwrite teammate designs.

Keep new code free of emojis; use concise comments and standard hyphens. Do not
commit credentials or real customer data. Teammate feature changes require Isaac's
prior approval. Review this foundation on `feature/shared-foundation` through a PR
to main. Branch protections remain unconfigured; external deployment and production
release are separate reviewed and authorized actions. Review authentication changes
on `feat/authentication-macha`; the original foundation branch is preserved.
