# Reporting query integration

Reviewed November 11, 2026. Isaac authorized fixing Bryson's reporting PR #6 and
merging it together with Anh's approved backend PR #3 into `dev`. The original
teammate commits are preserved; this integration does not promote `main`.

## Corrected behavior

`backend/app/reports_queries.py` provides tuple-cursor helpers for dashboard
counts, upcoming customer-order events and order CSV data. It introduces no
routes, migrations or live provider calls. Existing admin pages continue using
their connected owner APIs; Anh can consume the helpers in the reporting routes.

For linked orders, reporting now uses the current booking's schedule, timezone,
quantity, service and monetary values. Filters and upcoming ordering use the
same effective-start SQL expression as the owner workspace. A booking moved
from January to July disappears from the January window, appears in July and
uses its finalized quantity. Unlinked orders retain their own values. Cancelled
bookings remain excluded from upcoming results.

Upcoming items expose optional `venue` for the current free-text booking venue.
The original structured customer address remains in `event.location`; it is not
guessed from a free-text venue. The compatible optional field is documented in
OpenAPI. Existing CSV columns and helper arguments remain unchanged.

CSV formula neutralization checks `=`, `+`, `-` and `@` after leading whitespace,
including spaces, tabs, newlines and Unicode whitespace. Leading tab/carriage
return/newline cells also remain neutralized. CSV quoting preserves embedded
commas, quotes and newlines. Safe cells are unchanged.

Reporting reads leave the source response and original submission snapshot
intact. Replaying the original order submission still returns the original data
after payment, final-count and rescheduling changes.

## Validation and handoff

The targeted query and regression suite passed **63 tests** against isolated
MySQL. New cases exercise real submission, intake, availability approval, deposit
verification, final counts, a timezone/date/venue change and cancellation. They
check month windows, bounds, sorting, pagination, current exported values,
OpenAPI conformance, original snapshots/replays and formula handling.

The full backend suite passed **1,185 tests** in an isolated checkout of current
`dev` with Anh's exact PR #3 and the fixed reporting files together. Python
lint/format, frontend format/build, contract/example/link checks and whitespace
checks also passed. Remote CI evidence is recorded in PR #6 before merge.

Local logs: `/private/tmp/b10-report-fix-targeted.log` and
`/private/tmp/b10-report-fix-combined-full.log`. Tests use synthetic records and
a disposable database, without modifying the normal development or walkthrough
databases. Live provider behavior and deployment are outside this validation.

Quote persistence/expiry/payload enforcement and trusted delivery distance remain
separate release blockers. PR #6 supplied query helpers without registering HTTP
routes or changing existing booking actions. The HTTP integration follow-up is
recorded below.

## HTTP route fixes in PR #8

Reviewed November 12, 2026. Anh's reporting branch registers upcoming events,
order CSV export and dashboard counts using the existing query helpers. The
follow-up fixes address two reproduced review findings on that branch.

`GET /events/upcoming` now returns the existing OpenAPI response shape:
`data` contains `items`, `page`, `page_size` and `total`; `meta` contains only
`request_id`. Successful route tests validate the full HTTP response against
`UpcomingEventsResponse`, including empty pages.

`GET /orders` includes verified booking payments in its live deposit summary.
Partial payments remain visible while the deposit is pending. Confirmed deposit
amounts are capped at the deposit due so final payments and overpayments stay
separate. Cancellation retains verified money. Both storage adapters use the
same read-only projection; source order details, historical pricing and original
POST replay remain intact.

The full backend suite passed **1,284 tests** against fresh disposable MySQL,
including 16 new regression cases across memory and MySQL. The original two
review reproductions also passed after the fixes. Python lint/format, foundation
contract/example/link checks and whitespace checks passed. Local backend log:
`/private/tmp/b10-pr8-fix-backend-full.log`. The disposable container and volume
were removed after validation.
