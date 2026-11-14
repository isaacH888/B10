# Admin order API integration and UI handoff

Updated November 14, 2026. The original walkthrough identified sample Dashboard
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
| UI-03: Booking actions use the authentication test layout | Resolved for workspace layout: booking lists/details now use the shared branded shell and navigation. Existing owner-only action APIs and CSRF/fresh-auth checks remain. Further form polish is still useful; payment entry still expects minor units. |
| UI-04: Owner account contains sample bookings; login lands there | Sample dashboard removed; owner login lands on `/admin/dashboard`. Account, invitation and MFA presentation still need branded layouts. Returning to the originating booking after re-verification still needs frontend coordination. |
| UI-05: Disabled date range and export | Resolved: server date filtering, filtered order CSV and per-order summary export with permission/fresh-authentication checks. Date controls need design polish. |
| UI-06: Inventory changes only modify browser arrays | Resolved: persistent inventory, versioned stock changes/history, archive and explicit booking flavor allocations. |

The initial Safari audit used the isolated local API workspace with real
Flask/MySQL, synthetic records and simulated sign-in. It did not verify live
Cognito, email or Google behavior. No external issue tracker tickets were created.

## November 14 admin usability changes

- One shared navigation/header covers Dashboard, Orders, Calendar, Inventory and
  the booking workspace. Headers, cards and filters are more compact, and phone
  navigation collapses behind an accessible Menu button. Booking management no
  longer includes authentication-test navigation or session debugging content.
- Calendar Upcoming is an explicitly selected-month view of future/ongoing work,
  sorted by actual start time. Upcoming excludes past, fulfilled and cancelled
  records; the month view continues to render its selected-month feed. Today and date
  highlighting follow America/Chicago, including UTC date/month boundaries.
- Inventory and Calendar dialogs contain keyboard focus, isolate background
  controls, close with Escape and return focus to the triggering control.
  Inventory restock shortcuts include out-of-stock items.
- Read views have Refresh data controls and Central-time update timestamps.
  Successful reads refresh while the tab is visible and when returning to it.
  Transient background failures preserve existing views and unsaved drafts;
  explicit access denials remove cached records and close affected drawers.
- Order search, status/payment/service filters, date range and pagination are
  stored in the URL. Details preserve the filtered-list return link. Filter
  changes reset pagination, outdated page numbers are clamped after count
  changes, and old rows/export are unavailable while a new query loads.

For this owner-run small business, keep the current Owner-only workspace policy.
Staff access should be added for an explicit delegated responsibility rather than
granting blanket administrative access. This iteration changes no Cognito users,
roles, credentials, MFA requirements, or backend authorization policies. The local
sample preview remains separate from real data and rejects mutations.

Focused browser coverage is in `admin-calendar-ux.spec.js`,
`admin-drawer-accessibility.spec.js`, `admin-shell-ux.spec.js`,
`admin-data-refresh.spec.js` and `admin-order-state.spec.js`, alongside the existing
admin/authentication/automation regressions. These use synthetic API fixtures;
they do not establish live Calendar, mail, payment-provider or Cognito behavior.

Validation on November 14: production build and formatting checks passed; 64
admin/booking browser scenarios, 49 authentication scenarios (on the expected
5190 test origin), and 5 isolated sample-preview scenarios passed. Desktop and
phone layouts were inspected. A preliminary authentication run on a different
test port failed fixed-origin assertions; rerunning on 5190 passed all 49 without
changing application authentication code.

## Checkout-inspired owner theme

The owner workspace now follows the catering checkout's white surfaces, pale blush
navigation, plum actions, soft borders, typography and field treatments. The same
theme covers Dashboard, Orders, Calendar, Inventory, booking management and their
dialogs. Mobile metrics use two columns, and drawers fit within the phone viewport.
Existing data loading, filters, refresh, exports, permissions and mutation handlers
remain in their current components. The presentation layer is scoped to `.adm-shell`
in `frontend/src/admin/admin-theme.css`, loaded after the existing page styles.

Validation before DEV publication: all 204 frontend browser scenarios passed,
including the 64 admin/booking scenarios, authentication, checkout and public pages.
Production build, formatting and shared foundation/OpenAPI checks passed. Desktop
and phone layouts were visually inspected using the isolated sample preview,
including the inventory form drawer. The mobile Menu uses an SVG icon to satisfy
the shared source validation rules.

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
confirmation/error screens. Customer order history would need a separate backend
contract and is not supplied by this admin completion. Newsletter subscriptions
were removed from scope on November 12; a social media link is planned once the
team supplies the URL. Existing public homepage, catering form, customer sign-in
and server-backed order confirmation remain available.

Isaac approved committing and publishing this integration from
`feature/admin-order-api-integration` into `dev` on November 11, 2026.
Future commits and pushes still require approval under the repository workflow.
