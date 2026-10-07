# Lead Developer plan through Week 4

Owner: Isaac Hernandez. Updated October 5, 2026. The supplied eight-week plan
supersedes the charter's older six-week calendar; see [source alignment](reference-alignment.md).
This record separates completed preparation from scheduled work and actual evidence.

## Dated responsibilities

| Week / dates | Isaac's assigned work | Evidence and remaining work |
| --- | --- | --- |
| Week 1, September 15-18 | Repository/branch standards, architecture, contracts, folders, environment and workflow | Shared documents and PR template prepared; remote branches/protections not configured; owner contract acceptance pending |
| Week 2, September 21-25 | September 21-22 Flask/config; September 23-24 React/API connection; September 25 reproducible setup | Approved shell added October 5; builds/tests and HTTP probes recorded; do not backdate completion or claim independent teammate setup |
| Week 3, September 28-October 2 | September 28-29 shared development DB/env; September 30-October 1 connect quote; October 2 integration review | Compose/env and draft mapping review prepared; live DB/migrations and quote components remain blocked |
| Week 4, October 5-6 | Integrate catering form, pricing and DB | Blocked on owner components, mappings and pricing decisions; shared infrastructure does not implement them |
| Week 4, October 7-8 | First reviewed staging build | Planned; host, owner release, migration/recovery evidence and deployment approval missing |
| Week 4, October 9 | Team demo and weekly check-in | [Demo agenda](week-4-demo.md) and [backlog](agile-backlog.md) prepared; live integrated demo pending |

The dates are planned targets from S01, not evidence that those tasks were completed
on schedule. Record carryover and a new one- or two-day task when dependencies unblock.

## Deliverable status

| Deliverable | Evidence | Current state |
| --- | --- | --- |
| Source/ownership alignment | [References](reference-alignment.md), [dependency map](integration-dependencies.md) | Review; individual owners and conflicts documented |
| Shared architecture/configuration | [Architecture](architecture.md), [configuration](configuration.md), [.env.example](../.env.example) | Scaffold approved; provider/hosting/domain decisions open |
| React/Vite and Flask foundation | [Setup](development-setup.md), [checks](foundation-validation.md) | Local build, backend tests and HTTP checks pass; DB readiness correctly unavailable |
| Contract/examples | [API](api-contract.md), [OpenAPI](api/openapi.json), [examples](api/examples.json) | 0.2.0-draft; standards/example validation separate from consumer acceptance |
| DB coordination | [Database review](database-integration-review.md), [Compose](../compose.yaml) | Draft acknowledged; migrations and live connection blocked |
| Agile/review/CI | [Workflow](development-workflow.md), [backlog](agile-backlog.md), [CI](../.github/workflows/foundation-checks.yml) | Prepared locally; no remote runs, protections, issues or PRs |
| Form/quote/order integration | [Scenarios](integration-tests.md), [workflows](order-workflows.md) | Blocked; business runtime not present |
| Staging/recovery | [Deployment](deployment-plan.md), [readiness](staging-readiness.md) | Planned, not deployed |
| Demo/status | [Week 4 demo](week-4-demo.md), [blockers](decisions-and-blockers.md) | Prepared; owner handoffs and live evidence pending |

## Week 4 boundary and next handoffs

Dillion supplies the form/API connection and confirmation, Anh the pricing and
create/list/detail APIs, Bryson the migrations/queries/transaction tests, Shourya
the order-created email adapter/logging/deduplication, and Aneena shared styling
and loading/error/cross-browser review. Isaac integrates and reviews those handoffs.

Week 5 brings protected dashboard integration, status/payment/export and Calendar.
Week 6 brings reminders and deposit-triggered contracts. Keep private APIs protected
whenever exposed, even before the full dashboard is scheduled. Do not gate Week 4
on completing Week 6 features or present later draft endpoints as implemented.

All Lead Developer tasks and acceptance criteria are in the [local backlog](agile-backlog.md).
Feature freeze is October 23, final release lock November 6 and submission November 9.
Isaac authorized publication on `feature/shared-foundation` for review on October 5.
External staging/production deployment remains pending separate approval.
