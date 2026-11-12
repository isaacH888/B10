# Admin order API integration and UI handoff

Updated November 11, 2026. The original walkthrough identified sample Dashboard
links, fixed Calendar details, temporary inventory, disabled date/export controls
and unstyled booking/account screens. The sample/API gaps are now addressed in
the same local branch. Use the [completion report](admin-api-completion.md) for
current implementation and validation, and the [Figma brief](dillion-figma-brief.md)
for Dillion's remaining design tasks.

## Walkthrough findings and current disposition

| Original ticket | Current disposition |
| --- | --- |
| UI-01: Dashboard sample metrics and broken order IDs | Resolved: saved metrics, balances, recent orders and upcoming bookings; actual record links and loading/empty/error states. |
| UI-02: Calendar sample drawer, fake connection and one event per day | Resolved: database event feed, actual selected record, multiple events per day and independent Google connection status. |
| UI-03: Booking actions use the authentication test layout | Design still needed: booking detail/intake, payment, scheduling and action dialogs. Amount display now formats currency; payment entry still expects minor units. |
| UI-04: Owner account contains sample bookings; login lands there | Sample dashboard removed; owner login lands on `/admin/dashboard`. Account, invitation and MFA presentation still need branded layouts. Returning to the originating booking after re-verification still needs frontend coordination. |
| UI-05: Disabled date range and export | Resolved: server date filtering, filtered order CSV and per-order summary export with permission/fresh-authentication checks. Date controls need design polish. |
| UI-06: Inventory changes only modify browser arrays | Resolved: persistent inventory, versioned stock changes/history, archive and explicit booking flavor allocations. |

The initial Safari audit used the isolated local API workspace with real
Flask/MySQL, synthetic records and simulated sign-in. It did not verify live
Cognito, email or Google behavior. No external issue tracker tickets were created.

## Owner order read contract

- `GET /api/v1/admin/orders`: optional `q`, `status`, `payment_status`,
  `service_type`, `event_from`, `event_to`, `page` and `page_size`. Returns
  `{data: {items: [{order, booking}], total, page, page_size, storage}, meta}`.
  Page size defaults to 25, maximum 100. Search is a literal case-insensitive
  customer-name/order-ID substring of at most 150 characters; SQL wildcard
  characters are escaped. Unknown or repeated query parameters return 422.
- `GET /api/v1/admin/orders/:orderId`: returns
  `{data: {order, booking}, meta}` or 404 after authorization. `order` preserves
  the original snapshot; the bounded linked `booking` supplies current dates,
  venue, state and verified balances. It is null until intake.
- Both require an active owner session and `bookings:read`, including the
  existing revocation checks. Responses are `Cache-Control: no-store`.
  Staff/customer sessions and authentication-disabled deployments cannot read
  these records.
- Current linked status takes precedence; source `pending_review` and booking
  `requested` map to `pending`. Verified balances determine unpaid/partial/paid.
  Date bounds are explicit-offset timestamps, `[event_from, event_to)`, using
  the linked booking's current event start when present.
- SQL pagination/count share a transaction. Unconfigured development orders
  may use the existing process-memory store and report `storage=memory`.
  Configured DB failures return 503 without sample fallback.
- Manual bookings remain bookings, rather than fabricated customer orders.
  Dashboard and Calendar include them through the booking model.

Intake, approval, payment verification, rescheduling, cancellation, final counts,
reopening and Calendar recovery retain the existing booking APIs. Styled order
details link to that workflow. The obsolete simulated payment/cancellation
controls and product fixture store have been removed.

The [OpenAPI catalog](api/openapi.json) describes the owner endpoints.
`frontend/src/admin/orderApi.js` adapts order reads; `adminApi.js` now calls real
Dashboard, Calendar and Inventory APIs. The earlier general `/orders` edit and
status proposals are separate from the implemented owner workspace interfaces.

## Wider frontend work

Dillion should prioritize the [booking and interaction frames](dillion-figma-brief.md).
Aneena can own the shared account/sign-in components, customer account and branded
confirmation/error screens. Customer order history and newsletter subscriptions
would each need a separate backend contract; neither is supplied by this admin
completion. Existing public homepage, catering form, customer sign-in and server-backed
order confirmation remain available.

Isaac approved committing and publishing this integration from
`feature/admin-order-api-integration` into `dev` on November 11, 2026.
Future commits and pushes still require approval under the repository workflow.
