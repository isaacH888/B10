# Week 4 team demo and evidence checklist

Owner: Isaac Hernandez. Planned demo: Friday, October 9, 2026, per S01 page 5.
Status: prepared agenda only. No demo, staged release or customer-order flow has
been demonstrated in this repository yet.

## Prerequisites and scope

Use the reviewed release SHA, accepted contract version, a disposable migrated DB,
synthetic customer data and approved test email recipients. Confirm staging approval
and an actual staging URL before describing the demo as a staging demonstration.

Week 4 covers form/pricing/persistence integration and order-created emails. Calendar
integration and dashboard work are Week 5; reminders and deposit-triggered contract
email are Week 6. Those later features are not mandatory Week 4 demo evidence.
Admin protection needed for any private list/detail access still applies now.

## Suggested demonstration sequence

1. Isaac shows the release/contract/migration versions and current backlog/blockers.
2. Isaac shows frontend startup, backend liveness and actual DB readiness. A shell
   health check demonstrates connectivity only, not a completed customer workflow.
3. Dillion submits an invalid quantity, then an approved synthetic valid request.
4. Anh shows the returned itemized quote; Dillion's displayed cents match it.
5. Dillion submits using one stable idempotency key and shows the returned summary.
6. Anh/Bryson demonstrate the persisted snapshot and authorized order retrieval.
7. Shourya demonstrates the customer/business test emails and failure tracking.
8. Repeat submission and an email-trigger retry; verify no duplicate order/action.
9. Isaac shows staging evidence, remaining defects and one- or two-day carryover tasks.

If component prerequisites are missing, demonstrate the platform foundation and
document the blocked workflow. Do not substitute synthetic JSON for a live submission
or describe a locally served shell as a deployed staging build.

## Demo result record

| Field | Current entry |
| --- | --- |
| Demonstration date/executor | Not executed |
| Branch / commit SHA | Foundation review branch feature/shared-foundation; no approved demo release SHA |
| Contract | 0.2.0-draft; team acceptance pending |
| Migration revision | Not supplied |
| Environment / staging URL | Local shell only; no staging URL |
| Live quote/order/persistence result | Blocked by owner components and schema |
| Email result | Blocked by Shourya's adapter/test configuration |
| Defects / follow-up | Use the blocker register and Agile backlog |

Replace entries with actual sanitized evidence after the demo. Record passed,
failed and blocked scenarios separately; link tickets and owner continuations.
