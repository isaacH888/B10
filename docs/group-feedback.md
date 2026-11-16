# November 15 group feedback

The customer ordering form, pricing API and owner workspace now apply the group's
feedback. Homepage colors and the replacement photo remain with Aneena.

Custom flavor requests, custom add-ons, non-menu flavor allocations and heart
shapes require at least 14 days before the event start. The API checks this when
quoting and again when accepting the order. Short-notice events use available
paletas; sample flavor choices are preferences that the owner must verify against
stock. Allergy notes have a separate field and remain available for every event.
Changing a date does not silently discard an existing custom request: the customer
can clear it or choose a later date.

Every quote includes at least `3 * ceil(quantity / 150)` dry-ice blocks.
Orders of up to 150 paletas pay $15 per block. For orders over 150 paletas,
the first three blocks stay $15 each and additional blocks cost $10 each.
For example, 150 paletas require three blocks ($45), 151 require six ($75), and
301 require nine ($105). Extra blocks remain available at the rate for that
order size. Quotes and saved orders show the actual required count even if an
older client requests fewer blocks or omits them. Existing saved quotes/orders
retain their accepted price; newly calculated quotes use pricing revision 2.3.0.

Full service retains the $150 service fee and adds one employee at $15 per hour
for the event duration only. Setup and teardown add no employee hours. Full-service
requests require an event end, and the API calculates the duration and fee from
the event timestamps. The employee charge appears separately in quote line items.
Owner-entered bookings retain their explicitly agreed total; that total should
include required dry ice and employee service.

`/admin` redirects to `/admin/dashboard`. The separate team account screen and
its navigation links are removed. Existing staff authentication remains valid,
but staff cannot enter owner workspaces; sign-out and reauthentication remain
available. Order tables show the customer name before the order ID. Headings also
lead with the customer name. Owner event creation, intake, review and rescheduling
use native date/time pickers in Houston/Central time, with server timestamps
retaining explicit offsets.

The order-detail page and booking workspace provide Confirm availability,
Conditionally confirm, and Deny request actions. An unlinked order is imported
and reviewed atomically. Every review requires the current source version or
booking revision, preventing an outdated screen from overwriting another action.

Confirmation requires the contract link and a known event end, checks capacity,
and queues the existing deposit-request email. A verified deposit still confirms
the booking. Conditional confirmation requires an owner-written message, queues
an email asking the customer to discuss the conditions, and neither requests a
deposit nor reserves capacity. Recording money does not clear those conditions.
Denial queues a customer email, cancels the request, and retains payment history.
The owner can use the existing reopen workflow when a denied request changes.
Reopening requires the contract link and a real event end before capacity is
reserved. A stale request can still be denied after its event date. Updating the
final quantity raises its required dry-ice count without silently repricing the
accepted total.

Decision emails use the existing transactional outbox, retry and replay workflow.
Older decision and deposit-request emails are suppressed after a newer decision, and duplicate job
deliveries do not create duplicate successful sends. Failed delivery remains
visible in the booking's automation jobs. The UI reports that mail is queued,
without claiming inbox delivery. Live delivery requires the existing automation,
SES sender and queue configuration; offline tests use simulated providers.

Public copy now says Houston while retaining the service-area center ZIP 77477,
coordinates, radius and distance calculations. Navigation text is larger and
responds to phone/tablet widths. The yellow homepage text badge is replaced with
strawberry and lemon emoji. The header measures its height so section links remain
visible below it when navigation wraps.

New decision endpoints are documented in the [OpenAPI contract](api/openapi.json)
and [automation guide](calendar-automation.md). These changes use the existing
JSON booking records and outbox; no migration or historical order repricing is
required. New regression tests cover pricing thresholds, short-notice behavior,
employee duration, conditional payment handling, stale decisions, atomic rollback,
email suppression/deduplication, and responsive owner controls.

Initial group-feedback verification covered 1,535 distinct backend tests with a
disposable MySQL database and 222 Chrome browser tests, including focused reruns after correcting
outdated expectations and four expired/timed-out authentication fixtures. Build,
formatting, Python lint and shared foundation checks passed. Owner pages were
also inspected visually at desktop and phone widths. This does not verify live
SES delivery or deploy the changes.

The additional-block dry-ice discount follow-up passed 412 targeted backend tests
(four optional MySQL cases skipped), with browser checks for discount copy, block
thresholds and responsive quote summaries. The frontend build, formatting, Python
lint and shared foundation checks also passed.

Before the DEV push, local `dev` was fast-forwarded to `fb9a465` to preserve the
new startup intro. The combined application passed all 241 Chrome browser tests.
Backend validation passed all 1,543 tests in the full disposable-MySQL run plus
eight additional edge-case tests in a 57-case focused MySQL run (1,551 distinct
backend tests total). Review also checked stale deposit-email suppression,
reopening requirements, historical-request denial, date-boundary validation and
required dry ice after final quantity changes. Formatting, lint, build, contract
and whitespace checks passed; there are no migration or dependency changes.
