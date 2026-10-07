# Integration test checklist and evidence record

Owner: Isaac Hernandez with relevant feature owners. Updated October 5, 2026.
Shared shell build/start/health/CORS checks have evidence in
[foundation-validation.md](foundation-validation.md); business scenarios remain blocked
by missing owner components/migrations and accepted rules. Use synthetic data and
dedicated test accounts/destinations. Do not infer full scenario completion from a shell check.

Contract data lives in [api/examples.json](api/examples.json). It is not a running
mock server, real price list, or production seed dataset. Numeric totals are arbitrary.

## Scenario matrix

| ID | Scenario | Expected evidence | Primary owners | Target |
| --- | --- | --- | --- | --- |
| INT-01 | Independent startup | Documented frontend/backend commands run; DB migrations succeed in a fresh disposable DB | Isaac / Bryson / component owners | Week 3/4 |
| INT-02 | API base URL and browser access | Correct `/api/v1` prefix; allowed origin succeeds, disallowed origin cannot perform protected actions | Isaac / Dillion / Shourya | Week 2/4 |
| INT-03 | Minimum quantity | 49 rejected by backend with 422; 50 accepted for quote validation | Anh / Dillion | Week 4 |
| INT-04 | Unresolved pricing | `requires_review` with null pricing; frontend shows review state; submit blocked under proposed D08 policy | Anh / Dillion | Week 4 |
| INT-05 | Agreed pricing | Client-approved tier boundaries, heart shape, custom/add-ons, service, delivery and dry ice match expected cents | Anh / client | Week 4 |
| INT-06 | Deposit calculation | 50% of accepted total under approved rounding/tax rules; frontend matches backend | Anh / Dillion / Bryson | Week 4 |
| INT-07 | Quote authority | Forged totals, expired quotes, mismatched event/request, stale price revisions rejected or repriced under agreed policy | Anh / Bryson | Week 4 |
| INT-08 | Successful submission | Browser receives one 201 order; accepted snapshot and durable jobs persist; admin retrieves it | Isaac / Dillion / Anh / Bryson / Shourya | Week 4 |
| INT-09 | Submission retries | Same key/payload replays original result; changed payload conflicts; concurrent duplicate submissions create one order | Anh / Bryson | Week 4 |
| INT-10 | Database failure | Failed commit returns a safe error; no acknowledged phantom order or orphaned external job | Anh / Bryson / Shourya | Week 4 |
| INT-11 | Admin lifecycle | Login, reload bootstrap, expiry, logout and generic failure behavior work; no token leaks | Shourya / Dillion | Week 5 |
| INT-12 | Authorization and CSRF | Anonymous/private-resource requests fail; invalid CSRF/Origin mutations fail; hidden UI is not relied on | Shourya / Anh / Isaac | Before private routes ship |
| INT-13 | List/event windows | Empty results, pagination limits, stable tie sorting, `[from,to)` boundaries and cancelled exclusion match contract | Anh / Bryson | Week 4 list; Week 5 events |
| INT-14 | Order updates | Atomic version protection; fresh quote for financial changes; prior snapshot remains auditable | Anh / Bryson | Week 5 |
| INT-15 | Status transitions | Invalid transitions conflict; confirmed is not treated as paid; cancellation preserves history | Anh / Dillion | Week 5 |
| INT-16 | Deposit evidence | Redirect or customer claim cannot confirm payment; verified matching evidence can | Anh / Shourya / client | Week 5 |
| INT-17 | Repeated deposit actions | Same key, new key/same receipt, concurrent requests and worker retries do not duplicate contract actions | Anh / Shourya / Bryson | Week 6 contract action |
| INT-18 | Email outage | Order remains retrievable; failed job is observable/retryable; approved test recipient receives the eventual email | Shourya / Bryson / Anh | Week 4 |
| INT-19 | Calendar outage | Order and upcoming-event view remain available; retry/reconciliation avoids duplicate provider events | Shourya / Bryson | Week 5 |
| INT-20 | Reminder workflow | Approved timezone/timing, already-paid/cancelled cases, event edits and runner restarts behave correctly | Shourya / Anh / Bryson | Week 6 |
| INT-21 | Export | Authorized CSV has agreed columns and filters; formulas neutralized; capped export errors rather than truncates | Anh / Dillion | Week 5 |
| INT-22 | Health and logs | DB failure returns health 503; provider outage remains privately observable; errors/logs contain no credentials or customer bodies | Isaac / Shourya | Week 2/4 |
| INT-23 | Migration and recovery | Fresh migration and safe first-build recovery; later prior-version upgrade, backup restore and compatible application rollback | Bryson / Isaac | Week 4 fresh setup; Week 6/7 recovery |
| INT-24 | Reproducible setup | Another teammate follows README/setup successfully with no undocumented secrets or commands | Isaac / independent teammate | Week 2/4 |
| INT-25 | Out-of-area inquiry | Backend-assessed >30 miles gives null pricing and inquiry action; exactly 30 follows approved boundary; no normal delivery submission; no fabricated URL | Anh / Dillion / client | Week 4 |
| INT-26 | Draft-to-API transaction mapping | Agreed IDs, names/phones/addresses, cents, item totals and timezone/end map without truncation; failure rolls back transaction | Anh / Bryson / Isaac | Week 4 |

## Week 4 execution subset

Run INT-01 through INT-10, private-access checks in INT-12, list behavior in INT-13,
INT-18, INT-22 through INT-26. INT-02 has HTTP/CORS foundation evidence, but browser
behavior remains unverified. INT-01/22/24 are partial until DB migrations and an
independent teammate setup pass. Do not claim all scenario rows passed from pytest.
Week 5/6 scenarios remain preparation for later work; see [dated plan](week-4-plan.md).
INT-23's full backup/restore and upgrade rehearsal is later work; a first empty
staging DB still needs reproducible migrations and a documented safe recovery path.

## Required boundary and failure cases

For INT-05, wait for confirmed prices before writing expected financial assertions.
Cover 30-mile delivery boundaries, out-of-area requests, 0/1 dry-ice blocks and
the approved allocation rule. Test the recorded 3.5-hour full-service window against
agreed timestamp meaning and staffing selection; do not invent the $150 rate or
overtime rules. Keep the 50% deposit model until D18 is explicitly resolved.

For event handling, cover missing offsets, invalid timezone names, nonexistent
daylight-saving times, ambiguous local times, end-before-start, and past event dates.
Use current synthetic future dates when running tests, rather than copying expired fixtures.

For integration failures, simulate timeouts before and after a provider accepts an
action. Verify reconciliation as well as straightforward retries. No destructive
failure tests run against production or actual customer events.

## Evidence template

For each executed scenario record:

| Field | Required value |
| --- | --- |
| Scenario / contract version | INT ID and agreed contract version |
| Release / environment | Commit SHA and development or staging identity |
| Executor / time | Team member and timestamp |
| Setup / command | Exact command or UI steps; redact secrets |
| Expected / actual | Observable behavior and sanitized evidence |
| Result | Passed, failed, or blocked; never infer pass from an unchecked checklist |
| Defect / owner | Issue reference, owner and recheck conditions |

No full business scenario is marked passed by the foundation checks. Attach actual
owner execution evidence before changing its result.
