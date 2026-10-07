# Lead Developer backlog and Week 4 check-in

Owner: Isaac Hernandez. Updated October 5, 2026. Source: S01 pages 1-5 in
[reference-alignment.md](reference-alignment.md). This file is a local backlog;
no remote issues or project board have been created. The foundation review branch
is `feature/shared-foundation`.

## Working rules

Use Backlog, Ready, In Progress, Review, Done and Blocked. Keep execution timeboxes
to one or two working days. At each boundary demonstrate evidence or create a
separate continuation. Do not expand a blocked task indefinitely or claim a past
scheduled date as an actual completion date. PR review and owner acceptance are
part of Done; a locally checked draft is Review, not a merged release.

Link each eventual issue, branch and PR to the task ID below. Record acceptance
criteria, primary owner, dependencies, expected demo and checks. Update daily with
what completed, what is next and which blocker needs another owner.

## Current Lead Developer tasks

| ID | Task | Timebox | State | Acceptance evidence / blocker |
| --- | --- | --- | --- | --- |
| LD-01 | Reference/architecture/contract alignment | 2 days | Review | Source conflicts and API 0.2.0-draft recorded; owner review B02/T08 pending |
| LD-02 | Shared React/Flask scaffolding and checks | 2 days | Review | Approved October 5; local build/tests/HTTP/contract checks pass; remote CI and independent review pending |
| LD-03 | Shared development database handoff | 2 days | Blocked | Compose prepared; local Docker/MySQL and Bryson migrations unavailable (B03/B10) |
| LD-04 | Connect live quote request to Anh's pricing API | 2 days | Blocked | Dillion form and Anh API missing (B05); approved pricing decisions needed |
| LD-05 | Integrate form, pricing and persistence | 2 days | Blocked | October 5-6 goal; accepted order/snapshot and retry evidence (B03/B04/B05) |
| LD-06 | First reviewed staging build | 2 days | Blocked | October 7-8 goal; deployable owner components, host and approval absent (B08) |
| LD-07 | Team demo and weekly status | 1 day | Ready | October 9 agenda prepared; execute live scenarios only when dependencies exist |

No task is Done solely because its Markdown checklist exists. LD-02 is Review
with local evidence; remaining DB/component work stays separately blocked.

## Week 4 check-in record

- Completed preparation: reference review, source-aware contract/configuration,
  database mapping review, individual ownership and dated acceptance plan.
- Work available locally: shared React/Vite and Flask shell; no business features.
- Unfinished: live quote/order/persistence integration, first staging deployment,
  team demo and team approval of contract/schema mappings.
- Blockers: missing component handoffs and DB runtime/migrations; unresolved pricing
  details; provider test access; hosting/release approval. Use the named B/T/D register.
- Next goals: review the verified scaffold, obtain the component handoffs,
  then execute LD-03 through LD-07 with sanitized evidence.

## Carryover procedure

At the scheduled boundary, record the demonstrated portion and create a one- or
two-day continuation with the unresolved acceptance criteria and responsible owner.
Do not move teammate feature implementation into Isaac's backlog to make integration
appear complete. Bring blocking decisions to Kelly/Adriana's coordination process;
this document does not send messages or create meetings automatically.
