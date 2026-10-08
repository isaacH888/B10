# Decision and integration-blocker register

Owner: Isaac Hernandez. Updated October 8, 2026. Week 4 is October 5-9 under
[the supplied dated plan](reference-alignment.md). Feature freeze October 23;
release lock November 6; submission November 9. Open items stay open until the
outcome, approver and acceptance evidence are recorded.

## Business decisions

Kelly Vo and Adriana Gonzalez coordinate client answers. Isaac records impact;
feature owners implement agreed outcomes. Recorded answers below come from S04,
not independent verification or approval inferred from research.

| ID | Current evidence and remaining question | Responsible owners |
| --- | --- | --- |
| D01 | Quantity tiers, unit prices, boundaries and effective dates still unknown | Client / Anh; Dillion display; Bryson snapshots |
| D02 | Confirm heart-shaped price and mixed-shape order policy | Client / Anh / Dillion / Bryson |
| D03 | Confirm flavors, add-ons, charges and manual-review requests | Client / Anh / Dillion |
| D04 | Origin recorded: Wingman Kitchens Houston, 4783 Lexington Blvd, Missouri City, TX; beyond 30 miles redirects to inquiry. Confirm postal code/geocoding, distance method, $25-$75 formula and inquiry URL | Client / Anh / Dillion |
| D05 | Recorded full service is 3.5 hours (.5 setup, 2.5 serving, .5 breakdown), 1-2 people. $150 appears in the question, not explicit price approval; confirm fee, staffing, timestamp meaning, overtime and delivery inclusion | Client / Anh / Dillion / Shourya calendar |
| D06 | Confirm dry-ice allocation/count and when $15/block applies | Client / Anh / Dillion |
| D07 | Confirm USD, taxes, total basis, odd-cent deposit rounding and final balance | Client / Anh / Bryson |
| D08 | Approve whether unpriced requests can be submitted; draft API requires a priced accepted quote | Client / Anh / Dillion |
| D09 | Define financial edits, corrections/reversals, cancellation/refunds and adjustments after deposit | Client / Anh / Bryson |
| D10 | Approve order states/transitions, acceptance/capacity policy and draft DB status mapping | Client / Anh / Bryson |
| D11 | Square first is recorded; Venmo/PayPal later. Merchant credentials unknown; approve manual/provider verification and acceptable evidence | Client / Anh / Shourya |
| D12 | Confirm event timezone/calendar inclusion and revision policy; reminder send time, final-count timing and short-notice/reschedule/cancel behavior. Seven-day reminder does not establish payment due date | Client / Shourya / Anh |
| D13 | Approve sender/recipients/content and resolve initial contract link versus contract first sent after verified deposit | Client / Shourya |
| D14 | Approve contract owner, URL and access policy | Client / Shourya |
| D15 | Approve admin users, account provisioning/revocation and access/retention | Client / Shourya / Isaac |
| D16 | Approve hosting/cost/domain, custodians, retention, backups and recovery targets | Client / Isaac / Bryson |
| D17 | Draft has final-payment/count fields; agree the API, verification, due date and reminder eligibility, including later count changes below minimum | Client / Anh / Bryson / Shourya |
| D18 | Research proposes one full payment and Paid/Unpaid; charter and database draft use deposit/final payment. Preserve 50% deposit baseline until client explicitly approves a change | Client / Anh / Shourya / Bryson / Isaac |

Minimum 50, 50% deposit, $25-$75 delivery within 30 miles, $15/block dry ice and
seven-day final-payment reminders remain the charter baseline. Do not invent the
unconfirmed details or adopt research scope changes to close a blocker.

## Technical decisions

| ID | Status / decision | Responsible reviewers |
| --- | --- | --- |
| T01 | Approved by Isaac in conversation October 5: React/Vite + Flask + MySQL scaffold. Locks included; CI targets Node 22/Python 3.12; local checks used Node 25.9/Python 3.9.6. MySQL 8.4 family selected for development/CI; production image/version and styling need release review | Isaac / component owners / Bryson |
| T02 | Resolved for authentication branch by user October 8: separate Cognito customers/admin pools, Google customer login, required admin password/TOTP, Owner/Staff roles, server MySQL sessions/CSRF, private CLI administration, admin Plus tier; live provider configuration pending | Shourya / Dillion / Isaac |
| T03 | Open: ORM/models, single migration runner/history and exact commands | Bryson / Anh |
| T04 | Open: approved host and durable worker/scheduler execution model; no AWS adoption inferred | Isaac / Shourya / Bryson / client |
| T05 | Open: technical limits, 15-minute quote lifetime, >=24-hour idempotency replay and export cap | Anh / Dillion / Bryson / Isaac |
| T06 | Open: email provider, Google credential mechanism, durable jobs, retry/reconciliation | Shourya / Bryson / Isaac |
| T07 | Individual ownership resolved by S01; optional Shopify/chatbot ownership and secondary coverage still need team coordination | Team / project managers |
| T08 | Open: API/database mapping, item aggregation, UTC/end time, money, statuses, quote snapshots, audit/idempotency and job identities | Anh / Bryson / Shourya / Isaac |

See [database integration review](database-integration-review.md) before implementing
mappings. Isaac reviews interfaces; Bryson retains migration/model ownership.

## Integration blockers

| ID | Condition / current status | Resolution owner | Unlocks |
| --- | --- | --- | --- |
| B01 | Resolved for shared scaffold: stack approval, manifests, locks and executable shell commands exist. Owner approval and remote CI still pending | Isaac | Foundation review |
| B02 | API 0.2.0-draft and T08 mappings lack consumer acceptance | Isaac / Anh / Dillion / Shourya / Bryson | Independent business implementation |
| B03 | Bryson entity/attribute draft received; companion ERD, migrations, models/query code and runner not supplied | Bryson / Anh | Domain persistence/migration tests |
| B04 | Pricing/fulfillment/payment-policy details remain open | Client through project managers / Anh | Final financial assertions |
| B05 | Shared shells exist; catering form, pricing/order APIs and owner business components are absent in this checkout | Named owners in dependency map | Quote/order integration |
| B06 | Authentication implementation and guards exist on feat/authentication-macha; live Cognito/Google configuration and named admin provisioning still required | Shourya / client / Isaac | Safe admin access |
| B07 | Research received; provider adapters, test access/recipients and durable job implementation unavailable | Shourya / client / Bryson | Week 4 emails; later calendar/contracts/reminders |
| B08 | No approved host, reviewed deployable business release or migration/restore evidence | Isaac / Bryson / feature owners / client | October 7-8 staging goal |
| B09 | Draft final-payment/count fields exist; API and reminder-state semantics not agreed | Anh / Bryson / Shourya / client | Week 6 automation |
| B10 | Local Docker/MySQL executable unavailable; live DB test skipped. CI service prepared but remote run pending | Isaac / Bryson / team | DB connectivity evidence |

## Decision record

Record ID, date, chosen outcome, approver, contract version, affected owners,
implementation task and acceptance evidence. Link sanitized meeting notes. A draft,
comment or research suggestion is not an approved decision.
