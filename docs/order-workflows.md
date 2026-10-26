# Integration workflow expectations

Updated October 5, 2026. Proposed business orchestration, not implemented features.
Isaac coordinates; Anh owns quote/order/payment interfaces; Shourya owns auth and
external automation; Bryson owns persistence. Source conflicts remain in the
[register](decisions-and-blockers.md) and [mapping review](database-integration-review.md).

## Quote and order - Week 3/4

1. Dillion collects validated customer/catering/event input; Aneena supplies shared visuals.
2. Anh validates input and authoritative distance/pricing. Unknown prices return
   requires_review with null pricing; beyond 30 miles includes the approved inquiry action.
3. Dillion displays backend cents or a clear review/inquiry state. Unpriced/out-of-area
   requests cannot become normal delivery orders under proposed D08 policy.
4. Submit complete details, accepted quote ID and one stable idempotency key.
5. Anh/Bryson atomically commit accepted order/items, historical pricing and required
   durable customer/business notification work. Do not create pending Calendar work
   before its later workflow is enabled and triggers accepted.
6. Return a public-safe saved summary; Shourya sends approved test notifications
   independently. External-link returns never prove payment.
7. Provider failure preserves the accepted order and visible retry/reconciliation state.

A DB failure must not acknowledge a saved order. Ambiguous post-commit network
failure is retried with the same key/payload rather than creating a second order.
The draft schema needs agreed pending-job, version and receipt/idempotency support.

## Emails - Week 4

Order-created customer summary and business notification require approved content,
sender and separate recipient identities. The initial contract-link versus later
contract delivery ambiguity remains D13. Do not turn a research comment into a new policy.

Persist job intent and stable action identity before provider work. Record attempts,
provider IDs and safe outcomes. Bounded backoff and authorized recovery must handle
ambiguous timeouts without blindly duplicating accepted sends. Draft notifications
with only sent/failed are not yet proof of durable pending work.

## Calendar - Week 5

Shourya integrates one-way Google Calendar after D12 confirms eligible order states
and event-window/timezone meaning. Retain provider event IDs and revision identity;
handle creation, edits, rescheduling and cancellation without duplicate events.
Upcoming-event data remains available from persisted orders during provider outages.
Use not_scheduled for intentionally unenabled calendar work, not pending as a claim
of an existing job. Review where pending first attempts live before implementing.

## Payment interfaces - Week 5; deposit-contract automation - Week 6

Square is the recorded first provider. Charter deposit/final-payment rules remain
active; research full-payment simplification is open D18, not approved replacement.
The application never receives card data. Approved external links are destinations,
not verification credentials or proof of receipt.

Authorized verification under D11 must validate amount, unique provider/reference,
confirmation time, order version and idempotency key against the accepted snapshot.
Business order state is separate from payment evidence. When Week 6 contract automation
is enabled, commit first verified deposit transition and one required contract action
together. Failed delivery remains retryable without undoing the deposit. Replays,
concurrency and repeated receipts must not send a second contract email.

D09 governs corrections/reversals/refunds and financial changes; status reversal is
not provider refund execution. D14 approves the contract URL/access policy.

## Reminders - Week 6

The charter requires final-payment reminders seven days before the event. That
reminder timing alone does not set a due date. D12/D17 must resolve final-count
send timing, local timezone/DST, short-notice, paid/cancelled/rescheduled behavior
and authoritative final-payment/count interface. Bryson's draft fields are recognized;
their accepted API mapping is still absent.

Persist schedule state and deduplicated send identities, recover from restarts and
cancel/revise eligible jobs after event changes. A confirmed deposit does not mean
final payment is paid. These are later acceptance expectations, not implemented workflows.
