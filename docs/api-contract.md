# API contract - Week 4 proposal

Contract version: `0.3.0-draft`. Coordinator: Isaac Hernandez.
Order/pricing API owner: Anh Hyunh. Auth/automation owner: Shourya Sai Macha. Frontend consumers:
Aneena Paul and Dillion Nguyen. Persistence owner: Bryson Hawthorne.

Status updated November 11, 2026: health, authentication, quote/order submission,
owner order reads, Dashboard, Calendar feed, inventory and owner CSV exports are
implemented locally. Booking/payment/email/Calendar automation uses its separate
[workflow contract](calendar-automation.md). The general `/orders` edit/status/
deposit interfaces below retain their earlier proposal status; implementing an
owner workspace counterpart does not implement those routes. Quote persistence and live provider verification remain open. Server-side address
checks and Geoapify setup are documented in [catering addresses](catering-addresses.md). See the
[current admin completion report](admin-api-completion.md).

The October 5 [reference review](reference-alignment.md) and
[database mapping review](database-integration-review.md) identify conflicts with
the research and Bryson's draft. This revision adds an out-of-area inquiry action
and precise ownership without imposing database changes or a full-payment policy.

## Authoritative examples and fields

[openapi.json](api/openapi.json) provides all request/response fields, required flags,
types, proposed size limits, authentication declarations, validation constraints,
success examples, and error examples for every operation below. Use it alongside
this guide; disagreements must be resolved before implementation. The
[example bundle](api/examples.json) provides reusable quote, order, and deposit data.

All examples are synthetic. `20000` cents and the `10000`-cent deposit demonstrate
field shape and the 50% relationship only. They do not establish a unit price,
quantity tier, delivery charge, tax rule, or approved quote. Example identifiers,
dates, payment references, passwords, and CSRF tokens are not usable operational data.

## Implemented owner workspace additions

All routes below are under `/api/v1`, require an active owner and `bookings:read`,
use existing session/revocation checks, and return private no-store responses.
Exports additionally require `customers:export` and fresh MFA. Inventory writes
require exact Origin, session CSRF, an `Idempotency-Key` and real MySQL storage.

| Method and route | Current behavior |
| --- | --- |
| `GET /admin/orders`, `GET /admin/orders/{order_id}` | Saved order snapshots plus bounded current linked-booking state. Server search/status/payment/service/page filters; date bounds use `[event_from,event_to)` with explicit offsets and current linked event start. |
| `GET /admin/dashboard` | Saved request/deposit/review counts, confirmed balances grouped by currency, next-30-day confirmed bookings, recent orders and inventory counts. |
| `GET /admin/calendar?year=&month=&timezone=` | Timezone-aware month feed, including unlinked requests and manual bookings without duplicates; cancelled records excluded. Independent of Google connection availability. |
| `GET /admin/inventory`, `POST /admin/inventory` | Read the active catalog or create an item and initial stock history. Reserved quantities are calculated from saved allocations. |
| `PATCH /admin/inventory/{item_id}`, `DELETE /admin/inventory/{item_id}` | Versioned metadata edit or archive. Archive preserves history and rejects active reservations. |
| `POST /admin/inventory/{item_id}/adjust` | Versioned add/remove/set stock with actor/reason/note and before/after history. Reject fractional/negative counts and counts below reserved stock. |
| `GET /admin/inventory/{item_id}/history` | Paginated saved stock history, including archived items. |
| `GET /admin/inventory/bookings/{booking_id}/allocations`, `POST /admin/inventory/bookings/{booking_id}/allocations` | Read or explicitly replace confirmed-booking flavor assignments using the current booking revision. Reject insufficient stock and totals above the booking quantity. |
| `GET /admin/orders/export`, `GET /admin/orders/{order_id}/export` | Filtered or single-order CSV using current booking values; formula-safe cells, maximum 10,000 rows, never silently truncated. |

Inventory mutation keys are scoped to owner/method/path and bound to the payload.
A successful replay returns the original result before stale-version validation;
changed payloads under the same key return 409. Stock/assignment/booking changes
share the SQL booking mutex. Cancellation releases reservations atomically;
reopening does not restore them. Flavor text is not inferred into reservations,
and fulfillment does not automatically consume inventory. See migration 0010
and the exact request/response schemas in [OpenAPI](api/openapi.json).

The reporting query helpers in `backend/app/reports_queries.py` use the linked
booking's current schedule, quantity, service and monetary values, with source
order fallback when unlinked. Their date filters and sorting use the same
effective start as the owner workspace. Upcoming items can include the current
free-text `venue`; `event.location` retains the original structured customer
address. CSV neutralization checks formula prefixes after leading whitespace.
The general reporting routes `/events/upcoming`, `/orders/export`, and
`/admin/dashboard/counts` call these helpers with MySQL configured and use the
same rules in memory. They require an administrator session and `bookings:read`.
See the [reporting integration review](reporting-query-fixes.md).

## Confirmed requirements and decision boundaries

| Requirement | Interface expectation |
| --- | --- |
| At least 50 popsicles | Backend rejects smaller quantities with 422 |
| Regular and heart-shaped pricing | November 13 supplied rates: regular $4.50/unit, heart-shaped $3.00/unit. Accept quantity/shape; further discounts and mixed-shape policy remain D01/D02 |
| Custom flavors and add-ons | Accept request text and add-on requests; pricing/availability depend on D03 |
| Event details | Collect type, address, timestamp with offset, and IANA timezone |
| Delivery or full service | Recorded full-service window is 3.5 hours (0.5 setup/2.5 serving/0.5 breakdown), 1-2 people; the $150 mentioned in the question needs explicit rate confirmation under D05 |
| Delivery $25-$75 within 30 miles | Recorded origin is Wingman Kitchens Houston, 4783 Lexington Blvd, Missouri City, TX; postal code/formula remain open under D04 |
| Beyond 30 miles | Recorded response redirects to a custom event inquiry; return `next_action` and no final normal-delivery price |
| Payment provider | Square first per recorded Q&A; credentials unknown; Venmo/PayPal later. Retain the charter's deposit/final-payment model pending D18 |
| Dry ice $15 per block | Unit price is confirmed; allocation and billable count require D06 |
| 50% deposit | Backend calculates from the accepted total; rounding/tax treatment require D07 |
| Email, calendar, reminders | Durable email work in Week 4, Calendar Week 5, reminders Week 6; adapters not implemented here |
| Final-payment reminder 7 days before event | Charter requirement; final-count timing, timezone and exception handling require D12 |

Do not return fabricated prices for unresolved requests. A quote can return
`requires_review` with `pricing: null` and decision IDs. The proposed submission
policy rejects such quotes until priced. A manual-review order path needs D08 approval.

## Shared protocol

- Browser base URL: `/api/v1` behind the local Vite or hosted HTTPS proxy.
- JSON request bodies use `Content-Type: application/json`; unknown fields are rejected.
- Successful JSON returns `{ "data": ..., "meta": { "request_id": ... } }`.
- Errors return `{ "error": { "code", "message", "fields", "request_id" } }`.
- `fields` is an array of `{ "field", "message" }` with dotted field paths; it may be empty.
- JSON errors contain safe messages, not SQL details, traces, credentials, or provider payloads.
- Return `X-Request-ID` on all responses. Private resources use `Cache-Control: no-store`.
- Export CSV and OAuth callback redirects are exceptions to the JSON success envelope.
- Identifiers are opaque strings. IDs never grant permission to retrieve an order.
- Timestamps include an offset; persist UTC and retain the event's IANA timezone.
- Money uses nonnegative integer cents and explicit currency. The proposed currency is USD.
- Monetary line items sum to the total. Calculate the 50% deposit on the backend using
  the client-approved rounding policy. Never accept a client-supplied authoritative total.
- Trim textual input, validate email/phone formats, reject nonexistent local times and
  timezone/offset mismatches, and require event end after start when provided.
- Reject past event starts on quote/submission; example dates remain static fixtures.

Proposed technical limits are 100000 popsicles per request, 1000 requested dry-ice
blocks, 20 add-on requests, 2000-character notes, 15-minute quote expiry, page size
25/max 100, and export cap 10000 rows. These are reviewable abuse/size limits, not
client business rules. Review them before owner implementation.

## Authentication and duplicate actions

The implemented backend issues separate customer/admin opaque cookies. Hosted names
are `__Host-popssibilities_customer` and `__Host-popssibilities_admin`; development
omits the prefix. Cookies use HttpOnly, SameSite=Lax, Path=/, no Domain, and Secure
outside development. MySQL stores session hashes and encrypted provider tokens.

Login initiation validates exact Origin and returns a browser-bound Cognito URL.
Callbacks consume one state/nonce/PKCE transaction. Admin access requires a provisioned
active account plus fresh signed password-and-TOTP assurance. Customer identity never
confers admin privileges. Role/status is authoritative in MySQL and checked on every
request, alongside Cognito GetUser to detect revoked/disabled provider access.

Session reads return identity, absolute/idle expiry and a CSRF token; tokens/cookie
values never appear in JSON. Authenticated mutations require X-CSRF-Token and exact
Origin. GET session polling does not renew idle expiry. Owners/staff have distinct
permissions; financial changes and exports additionally require MFA within five minutes.
The frontend starts fresh verification at `/admin/login?reauth=1` without replaying a
business action. See [authentication](authentication.md) for implemented boundaries.

`Idempotency-Key` is mandatory for order creation and deposit updates. Generate a
high-entropy key (for example, a UUID) per logical action and reuse the exact payload
on retries. Proposed retention is at least 24 hours. The backend scopes keys by route
and authenticated principal/order where applicable, and binds them to the request hash.
The public order route must not allow keys to act as order lookup credentials.

Authenticate and validate CSRF before returning a replay. For a valid replay, return
the original response before checking an old version. Same key with different payload
returns 409 `idempotency_conflict`. Concurrency must not create duplicate orders or jobs.
Deposit references and action identities also require durable deduplication beyond
the key retention window. Do not automatically retry a validation/auth/conflict error.

## Endpoint summary

Anh owns quote/order/list/detail/update/status/deposit/event-query/export APIs.
Shourya owns login/session/auth and external automation. Isaac owns contract
coordination and shared health routes; Bryson owns persistence. OpenAPI `x-owner`
and `x-target-week` record each operation's owner and planned implementation week.
Planning an interface now does not implement the Week 5/6 features early.

| Method and route | Purpose | Auth | Success | Request and response schemas |
| --- | --- | --- | --- | --- |
| `POST /quotes` | Calculate a quote or flag unresolved pricing | Public | 200 | `QuoteRequest` / `QuoteResponse` |
| `POST /orders` | Submit one order against a server quote | Public, idempotency | 201 | `SubmitOrderRequest` / `OrderResponse` |
| `GET /orders/{order_id}` | Retrieve an administrative order | Admin | 200 | Path ID / `AdminOrderResponse` |
| `GET /orders` | List and filter orders | Admin | 200 | Query filters / `ListOrdersResponse` |
| `PATCH /orders/{order_id}` | Update order information | Admin, CSRF | 200 | `UpdateOrderRequest` / `AdminOrderResponse` |
| `PATCH /orders/{order_id}/status` | Update fulfillment/business status | Admin, CSRF | 200 | `UpdateStatusRequest` / `AdminOrderResponse` |
| `PATCH /orders/{order_id}/deposit` | Record verified deposit status | Admin, CSRF, idempotency | 200 | `UpdateDepositRequest` / `AdminOrderResponse` |
| `GET /events/upcoming` | Retrieve persisted upcoming events | Admin | 200 | Window/pagination / `UpcomingEventsResponse` |
| `GET /orders/export` | Export filtered order summaries | Admin | 200 CSV | Query filters / CSV string |
| `GET /admin/orders` | Implemented owner workspace: saved customer orders plus current linked booking summary | Owner, bookings:read | 200 | Filters/pagination / `AdminWorkspaceOrdersResponse` |
| `GET /admin/orders/{order_id}` | Implemented owner workspace: saved customer order and current linked booking summary | Owner, bookings:read | 200 | Path ID / `AdminWorkspaceOrderResponse` |
| `POST /admin/login` | Retained strict administrator OAuth flow | Exact Origin, shared rate limit | 200 | `AdminLoginRequest` / `AuthLoginResponse` |
| `GET /admin/password/transaction` | Start/resume native admin sign-in | Browser-bound HttpOnly cookie | 200 | `AdminNativeTransactionResponse` |
| `POST /admin/password/transaction` | Native password, new password or TOTP response | Exact Origin, transaction CSRF, single use, rate limit | 200 | `AdminNativeChallengeRequest` / `AdminNativeTransactionResponse` |
| `DELETE /admin/password/transaction` | Cancel native admin sign-in | Exact Origin, transaction CSRF | 200 | `AdminNativeCancellationResponse` |
| `POST /customer/login` | Start password or Google login | Exact Origin, shared rate limit | 200 | `CustomerLoginRequest` / `AuthLoginResponse` |
| `GET /admin/callback`, `GET /customer/callback` | Complete provider login | Browser-bound OAuth transaction | 303 | Validated success sets the matching opaque session cookie |
| `GET /admin/session`, `GET /customer/session` | Bootstrap session | Matching session | 200 | `AdminSessionResponse` / `CustomerSessionResponse` |
| `DELETE /admin/session`, `DELETE /customer/session` | Revoke and log out | Matching session, Origin, CSRF | 200 | `AuthLogoutResponse` |

The OpenAPI file specifies success schemas and examples for declared errors.
Isaac owns the two implemented owner workspace reads above. See the
[API integration and UI handoff](ui-handoff-and-admin-api.md) for filters,
authorization, current booking semantics and UI assignments. The original
planned general order-list/edit/export interfaces remain separate.
The details below identify additional
semantic validation that JSON schema alone cannot enforce.

Customer login accepts `provider: password|google`, defaulting to password.
Admin login accepts only `provider: password` (or an empty JSON object for the
password default); Google is rejected with 422. Completed native Cognito TOTP
and an explicitly approved active grant are required before the admin callback
can redirect to the protected sample dashboard. Retired admin Google/MFA
endpoints and old Google-assured sessions grant no access. See
[authentication](authentication.md) for assurance, refresh, revocation and recovery.

## Calculate quote

`POST /quotes` receives `catering_request` and `event` objects. Catering fields are
quantity, `popsicle_shape` (`standard`/`heart`), flavor request text, add-on request
strings, `service_type` (`delivery`/`full_service`), and optional requested dry-ice blocks.
The dry-ice field is a request, not an approved billable count.

Return quote ID, `priced` or `requires_review`, expiry, echoed request/event, nullable
pricing/revision, unresolved decision IDs, and nullable `next_action`. `priced` requires non-null pricing
and a rule revision; `requires_review` requires null pricing and a nonempty decision list.
Validate the minimum quantity, event address/time, request lengths, and service values.

For an outside-area or unverified address, customers may continue to a quote
estimate. Return `requires_review`, null accepted `pricing`, contact guidance and
an optional `estimate` with `currency`, product/extra `line_items` and
`subtotal_cents`. The estimate excludes service/travel fees and any deposit;
the owner confirms availability, final fees and price. Outside-area guidance uses
`reason_code=outside_delivery_radius`; unverified addresses use
`address_verification_unavailable`. The public form shows a green in-area check
or owner-review notice, without mileage, and does not block outside-area estimates.
A quote estimate is not an approved booking: browser distances cannot authorize
service, and normal order creation still requires a server-calculated accepted price.
The November 13 ZIP follow-up fixes the anchor at Stafford 77477 and compares
Census ZIP-area centers within 30 geographic miles. Full event details remain
required for normal pricing; a ZIP-only service check does not validate a street
address. Checks run locally without the suggestion API. Revision 2.1.0 records
the new distance basis for eligibility and the existing delivery-fee formula.

Success examples: OpenAPI `/quotes` POST, `200`, `synthetic`, `priced_fixture`, and `outside_radius`.
Error example: `422` with code `validation_error` and field
`catering_request.quantity` when the requested quantity is below 50.

## Submit order

`CateringRequest` supports an optional `flavor_allocations` array of up to five
objects with `flavor` (1–100 characters) and positive integer `quantity` (at most
100000). A non-empty array must sum exactly to `catering_request.quantity`.
Duplicate names are rejected after trimming and case folding. Both quote and
order routes validate these rules. An empty or omitted array lets the owner
choose the mix; existing clients remain compatible. `flavor_requests` continues
to carry custom requests and allergy notes. Flavor choices do not add charges.
These are requested quantities, not inventory item IDs or stock reservations.

`POST /orders` receives customer name/email/phone, complete catering/event objects,
and `quote_id`. Require `Idempotency-Key`; reject client totals or deposit declarations.
Verify quote expiry, revision, request equality, and final price before persistence.

Return a public-safe order summary: ID/version/status, customer/event/request,
historical pricing/revision, deposit due/status, configured payment links, coarse
workflow states, and created/updated timestamps. Omit admin notes and payment evidence.
The response provides customer confirmation without introducing public order lookup.

Success example: OpenAPI `/orders` POST, `201`, pending-review order with synthetic
pricing, pending email actions and intentionally `not_scheduled` Calendar. Error example: `409`
`quote_not_finalized`. Also distinguish `quote_expired`, `quote_mismatch`, and
`idempotency_conflict`. Database failure returns 503 and must not acknowledge a saved order.

## Retrieve an order

`GET /orders/{order_id}` requires an administrator session and an opaque path ID.
Return the order summary plus admin notes. Private payment evidence remains in the
restricted audit record rather than this default API representation.

Success example: OpenAPI operation `retrieveOrder`, `200`. Error example: `404`
`not_found` for a missing order after authorization. Missing/expired sessions return 401.
Any future customer lookup requires a separately approved authorization contract.

## List orders

`GET /orders` accepts optional `status`, `event_from`, `event_to`, `page`, and
`page_size`. Time bounds filter event start using `[from, to)`; when both are given,
the upper bound must be later. Sort by `created_at` descending, then ID ascending.

Return `items`, `page`, `page_size`, and filtered `total`; empty results are 200
with an empty array. Success example: OpenAPI operation `listOrders`, `200`.
Error example: `422` `validation_error` for an out-of-range page size.
Offset pages can shift during concurrent changes; they do not promise a stable export.

For imported orders, list summaries use the linked booking's mapped order/deposit
status and verified deposit amounts. `amount_confirmed_cents` is the verified
payment total applied toward the deposit, capped at `amount_due_cents`; partial
payments remain visible while the deposit status is pending. Final-balance
payments and overpayments do not increase the deposit summary. Unlinked orders
retain their saved deposit fields. These read-only projections preserve source
order snapshots, historical pricing and the original submission replay.

## Update order information

`PATCH /orders/{order_id}` requires admin auth, CSRF, current `version`, and at
least one of `customer`, `event`, `catering_request`, or `admin_notes`. Nested
objects replace the whole object. Omitted objects remain unchanged.

Event or catering changes require a fresh matching priced `quote_id`. Reject
financial changes to confirmed-deposit orders until D09 establishes the adjustment
policy. Preserve historical snapshots, update atomically, and increment version.
This endpoint cannot mutate order status or deposit status.

Success example: OpenAPI operation `updateOrder`, `200`, version 2 with changed
admin notes. Error example: `409` `stale_version`; additional quote conflicts follow
submission rules. Do not overwrite another administrator's changes.

## Update order status

`PATCH /orders/{order_id}/status` requires admin auth, CSRF, version, a status, and
optional reason. Proposed transitions: `pending_review -> confirmed/cancelled` and
`confirmed -> fulfilled/cancelled`. `fulfilled` and `cancelled` are terminal.
After a valid version check, setting the existing state is a no-op. Business
confirmation does not prove payment; D10 must approve these transitions and eligibility.

Return the updated administrative order. Success example: OpenAPI operation
`updateOrderStatus`, `200`, version 2 and `confirmed`. Error example: `409`
`invalid_transition`. Cancellation must not silently refund money or delete history.
Calendar/reminder changes follow the agreed durable workflow, not the browser.

## Update deposit status

`PATCH /orders/{order_id}/deposit` requires admin auth, CSRF, version, status, and
idempotency key. Confirmed deposits require `amount_cents`, provider (`paypal`,
`square`, `venmo`), unique `external_reference`, and `confirmed_at`. The amount must
match the persisted 50% deposit due under the approved rounding policy.

Proposed transitions: `pending -> confirmed` after verified evidence and
`confirmed -> reversed` with a reason. Setting the current state must not replace
evidence or create new work; conflicting evidence returns 409. Reconfirmation after
reversal is blocked until D09 defines corrections/refunds. A reversal records a
status correction; it does not invoke a provider refund.

Only the first verified confirmation schedules the deduplicated contract email.
Record evidence and required durable work atomically. Repeated requests, new keys
for the same receipt, and worker retries cannot create a second contract action.

Success example: OpenAPI operation `updateDepositStatus`, `200`, confirmed deposit
and pending contract email. Error example: `409` `payment_reference_conflict`.
Missing evidence returns 422. Payment-link redirects and customer claims never qualify.

## Retrieve upcoming events

`GET /events/upcoming` requires admin auth. Accept optional `event_from` and
`event_to` timestamps with explicit offsets, and optional `page`/`page_size`.
The lower bound defaults to now. Apply `[event_from, event_to)`, require
`event_to > event_from` when both are supplied, exclude cancelled orders, and
sort by event start then order ID.

Return paginated summaries with order ID/status, event details, quantity, and
service selection. Read from persisted orders so a Calendar outage does not remove
the event from the dashboard. The response is
`{data: {items, page, page_size, total}, meta: {request_id}}`, including empty
pages. Success example: OpenAPI operation
`retrieveUpcomingEvents`, `200`. Error example: `422` for an invalid event window.

## Export orders

`GET /orders/export` requires admin auth. Accept optional status/event bounds and
`format=csv`; unsupported formats or over-cap exports return 422. Register this
static route distinctly from the opaque order-ID route.

Return UTF-8 `text/csv` with `Content-Disposition` and `X-Request-ID`. Columns are
`order_id,status,customer_name,event_starts_at,quantity,service_type,currency,total_cents,deposit_due_cents,deposit_status`.
Escape cells and neutralize leading spreadsheet formula characters, including
formula prefixes after leading whitespace. Use a consistent query snapshot.

Success example: OpenAPI operation `exportOrders`, `200`, a complete synthetic CSV.
Error example: `422` `export_too_large` in the JSON error envelope. Never silently
truncate, expose provider receipts, or write customer exports into source control.

## Login, session and logout

`POST /admin/login` accepts `{}`; `POST /customer/login` accepts the optional
provider `password` or `google`. Credentials are entered only on Cognito/Google
managed pages. Registration, email verification and customer password reset use
Cognito. Admin registration and social authentication are disabled.
Overlapping starts reuse the private realm-specific browser binding; callbacks
retain it until its ten-minute cookie lifetime ends or authenticated logout.
A login start using a canceled binding returns `401 login_expired` and clears that
cookie, allowing an explicit fresh attempt.

Callbacks set the opaque session cookie and redirect to `/admin` or `/account`.
Failure redirects to the fixed matching login page with a safe error code.
Admin first-time enrollment is insufficient: signed `acr=urn:cognito:loa:4` and
`amr` containing pwd, otp and mfa are required before session creation.

GET session returns identity, permissions for admins, expiry and a CSRF token.
Missing/expired sessions return 401, forbidden access 403, and unavailable provider
or database 503. DELETE session invalidates locally, cancels associated pending
login flows across overlapping tabs, clears session/binding cookies and returns
Cognito logout_url for browser navigation. Provider-revocation failure is audited;
local logout still succeeds, with manual provider reconciliation documented in
[operations](authentication-operations.md). No background revocation retry is claimed.

## Customer sample confirmation email

`POST /customer/test-email` is implemented for authenticated customers. It accepts
only `{}`, requires the customer's session-bound CSRF token and exact origin, and
requires a canonical UUIDv4 `Idempotency-Key`. The server resolves the recipient
from the current verified Cognito profile, never browser input. Both customer
password and Google sign-in use the same endpoint; admin sessions alone do not
authorize it.

Success returns `{data: {status: "accepted", reference: "TEST-...", duplicate: false},
meta: {request_id: "..."}}`. Replaying an accepted request returns the same reference
and `duplicate: true` without another send. SES acceptance does not prove inbox
delivery. An uncertain attempt returns `409 email_delivery_uncertain`; do not
automatically send another. Validation is 422, shared limits 429, and disabled or
unavailable email configuration/storage 503. No order/payment is created.

See [customer test email](customer-test-email.md) for migrations, permissions,
SES sandbox restrictions, configured limits, and live verification steps.

## Supporting health interfaces

GET `/live` proves process liveness only. GET `/health` checks MySQL and, when auth
is enabled, its required migration/checksum and tables. Its health envelope includes
status, database and authentication (disabled/ready/unavailable), with 503 on degraded
readiness. Health does not prove live Cognito configuration or business features.

## Contract acceptance

- [ ] Isaac confirms routes, ownership, versioning, and unresolved decisions.
- [ ] Aneena and Dillion confirm fields, UI error states, session handling, and examples.
- [ ] Anh and Shourya confirm validators, auth, durable workflows, and duplicate protection.
- [ ] Bryson confirms snapshot, integrity, versioning, and migration compatibility expectations.
- [ ] Client decisions affecting business behavior are recorded in the decision register.
- [x] Full OpenAPI standards and schema-example validation run locally; see [validation](foundation-validation.md).
- [ ] Owner runtime conformance checks pass for implemented business features.

This checklist is intentionally unsigned. Foundation syntax/example checks do not
establish agreement or implementation conformance.

The primary administrator login uses the [native Cognito challenge contract](authentication-native-admin.md). Enrollment and pool settings do not establish MFA proof. Only completed browser-bound `SOFTWARE_TOKEN_MFA` can establish a native session; operator revocation versions fence pending challenges and fresh-authentication time survives refresh. Customer OAuth and strict legacy admin OAuth validation remain unchanged.
