# API contract - Week 4 proposal

Contract version: `0.3.0-draft`. Coordinator: Isaac Hernandez.
Order/pricing API owner: Anh Hyunh. Auth/automation owner: Shourya Sai Macha. Frontend consumers:
Aneena Paul and Dillion Nguyen. Persistence owner: Bryson Hawthorne.

Status: health and customer/admin authentication routes are implemented.
Pricing, orders, payments, email automation and Calendar interfaces remain proposed.
The authentication design was approved by the user on October 8; business contract
acceptance remains with the affected owners.

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

## Confirmed requirements and decision boundaries

| Requirement | Interface expectation |
| --- | --- |
| At least 50 popsicles | Backend rejects smaller quantities with 422 |
| Quantity-based and heart-shaped pricing | Accept quantity/shape; final rates depend on D01/D02 |
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
| `POST /admin/login` | Start native password/TOTP or approved Google login | Exact Origin, shared rate limit | 200 | `AdminLoginRequest` / `AuthLoginResponse` |
| `POST /customer/login` | Start password or Google login | Exact Origin, shared rate limit | 200 | `CustomerLoginRequest` / `AuthLoginResponse` |
| `GET /admin/callback`, `GET /customer/callback` | Complete provider login | Browser-bound OAuth transaction | 303 | Google admin receives pending MFA cookie only; other success sets session |
| `GET /admin/mfa` | Read Google approval/enrollment/challenge | Bound pending MFA and flow cookies | 200 | `AdminMfaResponse` |
| `POST /admin/mfa/enroll` | Create authenticator seed after private approval | Exact approved pending challenge, Origin, CSRF | 200 | Empty JSON / `AdminMfaEnrollmentResponse` |
| `POST /admin/mfa/verify` | Verify unused TOTP; enrollment grants no session | Pending challenge, Origin, CSRF, shared rate limit | 200 | `AdminMfaVerifyRequest` / `AdminMfaVerifyResponse` |
| `DELETE /admin/mfa` | Cancel pending Google sign-in | Pending challenge, Origin, CSRF | 200 | `AuthLogoutResponse` |
| `GET /admin/session`, `GET /customer/session` | Bootstrap session | Matching session | 200 | `AdminSessionResponse` / `CustomerSessionResponse` |
| `DELETE /admin/session`, `DELETE /customer/session` | Revoke and log out | Matching session, Origin, CSRF | 200 | `AuthLogoutResponse` |

The OpenAPI file specifies success schemas and examples for declared errors.
The details below identify additional
semantic validation that JSON schema alone cannot enforce.

Both login requests accept `provider: password|google`, defaulting to password.
Google admin access requires a private exact-identity approval and the separate
application authenticator; email matching never links accounts or authorizes
enrollment. Successful enrollment returns `enrolled`, consumes the pending cookie,
and creates no admin session. A new Google sign-in and unused TOTP return
`authenticated` with an opaque session cookie. See [authentication](authentication.md)
for assurance, rate limiting, replay protection, refresh, revocation and recovery.

## Calculate quote

`POST /quotes` receives `catering_request` and `event` objects. Catering fields are
quantity, `popsicle_shape` (`standard`/`heart`), flavor request text, add-on request
strings, `service_type` (`delivery`/`full_service`), and optional requested dry-ice blocks.
The dry-ice field is a request, not an approved billable count.

Return quote ID, `priced` or `requires_review`, expiry, echoed request/event, nullable
pricing/revision, unresolved decision IDs, and nullable `next_action`. `priced` requires non-null pricing
and a rule revision; `requires_review` requires null pricing and a nonempty decision list.
Validate the minimum quantity, event address/time, request lengths, and service values.

For backend-assessed delivery beyond 30 miles, return `requires_review`, null pricing,
and `next_action` with `type=contact_inquiry`, `reason_code=outside_delivery_radius`,
a safe message and nullable `inquiry_url`. The example URL is synthetic. Dillion
connects the approved real inquiry destination; do not accept a client distance as
authoritative or silently place a standard out-of-area delivery order.

Success examples: OpenAPI `/quotes` POST, `200`, `synthetic`, `priced_fixture`, and `outside_radius`.
Error example: `422` with code `validation_error` and field
`catering_request.quantity` when the requested quantity is below 50.

## Submit order

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

`GET /events/upcoming` requires admin auth and explicit `from`/`to` timestamps,
with optional page/page size. Apply `[from, to)`, require `to > from`, exclude
cancelled orders, and sort by event start then order ID.

Return paginated summaries with order ID/status, event details, quantity, and
service selection. Read from persisted orders so a Calendar outage does not remove
the event from the dashboard. Success example: OpenAPI operation
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
