# Admin API completion and validation

Updated November 11, 2026. Validated on
`feature/admin-order-api-integration`. Isaac authorized publication into `dev`
after the passing local checks. This completes
the sample-data and API gaps found in the admin walkthrough. Dillion's remaining
visual work is defined in the [Figma brief](dillion-figma-brief.md).

## Result

- Dashboard reads saved request/deposit/review counts, confirmed balances by
  currency, upcoming bookings, recent orders and stock. Its record links use
  actual IDs.
- Calendar reads a timezone-aware month feed with multiple events per day,
  current linked-booking dates and manual bookings without duplicates. Cancelled
  bookings are excluded. Google connection status is read separately; a provider
  outage does not remove saved events or produce a fake connected state.
- Inventory list/create/edit/archive, stock adjustments and paginated history
  persist in MySQL. Version checks prevent stale overwrites. Retry keys prevent
  duplicate accepted stock changes. History retains actor, time, reason, note
  and before/after counts. Archiving preserves history.
- Owners can explicitly assign catalog flavors to confirmed bookings. Allocations
  share the booking transaction mutex, reject insufficient stock and totals above
  the booking quantity, and update inventory versions and booking revisions.
  Cancellation releases reservations atomically. Reopening does not restore them.
- Orders support event-date filtering, filtered CSV export and individual order
  summary export. Exports require the export permission and fresh MFA, neutralize
  spreadsheet formula cells, and reject more than 10,000 records rather than
  silently truncate.
- The old sample-only account dashboard and obsolete simulated order actions
  are removed. Owner password login lands on `/admin/dashboard`; `/admin` shows
  the actual team session/permissions. API failures use visible retry/error states,
  without fictional fallback records.

## Integration and storage

Apply the shared migrations through **0010_admin_inventory.sql before running
this version's SQL-backed booking actions**. The additive migration creates
catalog, replay, stock history and booking-reservation tables. Existing migrations
0001-0009 are unchanged. The migration command is in
[development setup](development-setup.md); existing installations apply pending
migrations without resetting their database.

The implementation adds owner Dashboard/Calendar endpoints, inventory operations,
booking allocations and two admin export endpoints. See the exact schemas in
[OpenAPI](api/openapi.json), the [API guide](api-contract.md), and the
[order-read handoff](ui-handoff-and-admin-api.md). Owner/permission, CSRF, revocation
and fresh-authentication controls remain enforced by the existing guards.
Inventory requires MySQL; configured storage failures return 503.

Flavor requests remain free text until an owner assigns actual items. There is
no automatic flavor inference or fulfillment stock consumption. Stock consumption
requires explicit allocation release/adjustment under the current workflow.
The booking screen's payment input still uses minor units and scheduling uses
basic timestamp inputs; Dillion's friendly dollar/date controls need frontend
integration. Currency display has already been corrected.

Quote persistence/expiry/payload enforcement and trusted delivery distance remain
release blockers. Customer order history, newsletter storage, live provider setup,
deployment and automatic inventory fulfillment are outside this completion.

## Validation

- **1,085 backend tests passed**, including the complete suite against isolated
  disposable MySQL 8.4.13. New cases cover persisted data, timezone boundaries,
  current booking state, CSV safety/freshness, stock replay/version conflicts,
  concurrent changes, cross-booking stock conflicts, cancellation release, CSRF,
  owner-only access and actual response conformance to OpenAPI schemas.
- **125 Chromium browser tests passed**, including real-ID navigation, multiple
  same-day events, stock creation/adjustment, CSV downloads, date filters,
  API errors and responsive checks at 375/768/1440 pixels. Browser regressions use
  controlled API/provider responses; database behavior is covered separately.
- Python formatting/lint, frontend formatting/build, foundation contract/link
  validation and Git whitespace checks passed. The contract
  catalog contains 37 operations and 164 schema-valid examples.

Full-suite logs: `/private/tmp/b10-admin-complete-backend-final.log` and
`/private/tmp/b10-admin-complete-browser-final.log`. These local logs are not
committed artifacts and do not establish live Cognito/Google/SES behavior.

## Local walkthrough

The isolated workspace is available at
`http://127.0.0.1:5193/api/v1/__local_api_test/start`. It uses real Flask/MySQL APIs,
four saved synthetic orders and three labeled synthetic inventory items. The
launcher refreshes simulated owner sign-in and opens the live dashboard. Stock
and booking changes persist in its separate demo database across reloads.

The updated demo was checked through protected dashboard, Calendar, inventory and
CSV endpoints, and the saved dashboard was visible in Safari. The actual normal
development database was not reset or migrated. Email and live Google delivery
remain disabled in the isolated walkthrough. The harness and its credentials
are outside the repository and are not part of the application authentication
implementation.
