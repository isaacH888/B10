# Database integration review of Bryson's draft

Reviewer: Isaac Hernandez. Date: October 5, 2026. Source: S03 in
[reference-alignment.md](reference-alignment.md). Bryson owns the draft and all ERD,
schema, migration, model, query and integrity changes. Anh owns the order/API mapping.
This is an integration review, not a replacement schema or data dictionary.

## Contribution recognized

The draft identifies seven core tables: customers, admins, orders, order_items,
payments, notifications and calendar_events; pricing_tiers is provisional. It
includes keys, relationships, historical fee/price snapshots, deposit/final payment
records, optional customer login, and deletion protection for order history.
The referenced companion ERD and executable artifacts are not supplied here.

## Contract mapping decisions

| Topic | Existing API proposal | Bryson's draft | Required handoff |
| --- | --- | --- | --- |
| Identifiers | Opaque API strings | Auto-increment INT primary keys | Anh/Bryson agree public representation; do not require new DB key types just to match example IDs |
| Customer names | One name up to 150 characters | first_name/last_name, each 50 | Agree request fields or lossless storage mapping; do not automatically split a full name |
| Phone | Required, max 30 | Nullable, max 20 | Agree optionality/limits with Dillion; record a contract revision |
| Event location | Structured address | One VARCHAR(255) | Agree serialization or structured storage without silent truncation |
| Event time | Offset timestamp, IANA timezone, optional end | DATE and TIME, no explicit timezone/end | Define timezone and event-window storage, including setup/serving/breakdown meaning |
| Money | Integer cents + currency | DECIMAL snapshots, no explicit currency column | Exact decimal conversion and currency policy; never use binary floating-point for authoritative amounts |
| Order selections | One quantity and shape | Multiple flavor/shape item rows | Confirm mixed-item policy under D02/D03 before adding an item-array contract; total minimum is sum across rows |
| Order lifecycle | pending_review/confirmed/fulfilled/cancelled | pending/deposit_paid/confirmed/completed/cancelled | Agree explicit mapping or revise contract under D10; payment evidence must remain separately authoritative |
| Fulfillment | delivery/full_service | Also provisional pickup | Do not expose pickup until approved and represented in the contract |
| Final payment/count | No accepted update interface yet | Final payment record and final_confirmed_quantity exist in draft | D17 resolves workflow/API; existing draft storage is recognized, not marked absent |
| Quote/version history | quote_id, revision, order version | Not explicit in draft | Agree durable quote expiry, snapshot history and atomic stale-update protection |

These open decisions are tracked as T08. Until resolved, draft-to-draft mapping is
not evidence of a working order transaction. Public identifiers never authorize retrieval.

## Durability and duplicate-action gaps for owner review

- Notifications currently describe only sent/failed and a provisional unique
  order/type pair. Shourya/Bryson must agree how pending work survives commit,
  how recipients and revisions affect identity, and how attempts/ambiguous sends are recorded.
- Calendar rows are described as existing only after event creation. Agree where
  pending/failed first attempts live, and how event revisions and provider IDs are reconciled.
- Payment records distinguish deposit/final but do not yet establish receipt
  uniqueness across concurrent confirmations or durable idempotency replay.
- Order/version/audit updates and required jobs must be coordinated atomically.
  Isaac states the guarantee; Bryson and the backend owners choose its implementation.
- Guest customer email uniqueness needs a defined contact-update policy. Matching an
  email address alone must not expose an existing customer's order history.
- Cross-row quantity validation belongs to Anh's transaction path, with Bryson's
  integrity checks. A single item-row CHECK cannot prove the full order meets 50.

## Week 4 acceptance handoff

- [ ] Bryson supplies ERD, migration revision, models and exact migration command.
- [ ] Anh/Bryson resolve T08 and demonstrate create/list/detail behavior.
- [ ] Shourya/Bryson resolve durable notification and deduplication state.
- [ ] A fresh disposable database migrates successfully with synthetic data.
- [ ] Create-order commits customer/order/items/payment snapshot and required work together.
- [ ] Failure/retry cases preserve one accepted order and historical amounts.
- [ ] No existing draft is overwritten to implement Isaac's review suggestions.
