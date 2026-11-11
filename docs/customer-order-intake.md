# Customer order to owner booking handoff

Updated November 3, 2026. This describes the customer-order integration approved
for DEV publication. Hosted deployment and production approval are separate steps.

## Record ownership

Keep the existing customer order and automation booking implementations. A customer
submits the existing `SubmitOrderRequest`; its saved selections and integer-cent
prices are the source for the owner's booking. The owner supplies the contract
link and any missing event end time, because the public order contract does not
require those fields. Do not invent an owner identity, end time or contract URL.

After intake, the linked automation booking controls operational status, capacity,
verified payments, Calendar state and reminder jobs. The original customer order
remains the intake record; its legacy status is not a live booking-status view.
Legacy status PATCH requests return `409 booking_managed` after linking, preventing
competing administrative workflows. Use the linked booking in the owner workspace.
The booking retains the complete source-order snapshot, including contact details,
flavors, add-ons, address, event notes, quote reference and pricing.

## New owner API

Both routes use the existing `/api/v1/admin/automation` owner-session guard.
Mutation also requires fresh owner verification, the configured exact Origin and
`X-CSRF-Token`. Staff and signed-out requests are denied.

| Method and path | Behavior |
| --- | --- |
| `GET /api/v1/admin/automation/orders` | `200` data array of up to 100 newest pending, unlinked customer orders. Owner workspace refreshes it every 30 seconds. |
| `POST /api/v1/admin/automation/orders/{order_id}/booking` | Accept only `contract_url` and optional `end`. Return `201` with the existing booking representation on first import, `200` for an identical retry. |

Example supplement (synthetic only):

```json
{
  "end": "2027-06-12T16:00:00-05:00",
  "contract_url": "https://example.invalid/contracts/synthetic"
}
```

If `end` is omitted, use the saved order's `event.ends_at`; missing or invalid
end times fail validation. The existing booking validator requires a future event,
valid time zone/offsets, an end after the start, and an absolute HTTPS contract
URL. Customer fields, quantity, service, total and deposit come from the saved
order; client overrides are rejected. The full address stays in the source
snapshot; the existing Calendar venue summary is capped at its 500-character limit.

An import creates a `requested` booking owned by the authenticated administrator.
It does not approve capacity, verify a payment, send mail or create a Calendar
event. Continue with the existing approve and independently verified payment
actions. Approval queues the deposit request; a verified deposit queues Calendar,
customer/owner confirmations and reminder scheduling.

Errors use the existing error envelope and request ID:

- `400 invalid_booking`: invalid supplement, extra keys or missing required details.
- `401/403`: session, owner role, CSRF, Origin or fresh-verification failure.
- `404 not_found`: unknown source order.
- `409 order_already_linked`: that source order was imported with different details;
  open its existing booking to make changes.
- `409 invalid_transition`: source order is not pending review.
- `503 automation_unavailable`: storage or automation is unavailable.

The broader automation API remains described in its [runbook](calendar-automation.md).
The shared OpenAPI catalog still needs a coordinated update for automation routes.

## Database and retry behavior

Apply `0008_customer_order_intake.sql` through the existing explicit migration
runner after migrations 0001-0007. It adds `customers`, `orders`, `order_items` and
`automation_order_links`; existing migration contents/checksums are preserved.
Migration `0009_orders_event_start_index.sql` adds the `orders_event_start` index
on `orders.event_starts_at` through the same runner. Apply all pending migrations;
see the [index integration review](bryson-index-integration.md) for upgrade and
interrupted-run checks.
Do not run schema changes automatically during web startup.

Customer, order and line items save in one transaction. A unique idempotency key
and payload hash protect submission. Matching concurrent requests replay the
winning record; conflicting payloads return 409 and roll back the losing customer
insert. `submission_json` preserves the original POST response independently of
the administrative `response_json`, including after a status change.

Intake locks the source and uses the existing automation transaction/mutex. The
booking, audit and unique source-order link commit together. Any failure rolls
them all back while retaining the submitted order. Concurrent identical imports
create one booking. In-memory adapters retain the same retry/rollback behavior,
but are temporary per-process storage.

## Local review

Customer preview: <http://localhost:5173/order>. The local API uses a separate
`popssibilities_dev_local` database on port 33306. Credentials are in ignored
`backend/.env`, with file permissions 600. Public checkout uses real Flask/MySQL.
Authentication, live mail and automation are disabled in this preview until
the corresponding owner configuration is supplied. No fabricated admin login
is exposed. An actual owner must configure Cognito/session access before manually
reviewing `/admin/automation`.

1. Complete all four form-entry steps using synthetic contact details and a future
   event, then get a quote and place the order. The page must show a new server ID.
2. Return to the form, get a quote, select Back and change quantity. A fresh quote
   is required. Fractions and out-of-range counts must stay on the entry step.
3. With a configured owner session and `AUTOMATION_ENABLED=true`, open
   `/admin/automation`, expand Customer order intake, review the order, supply an
   end time and HTTPS contract link, then create its booking.
4. Open that booking. Confirm the original selections and total are visible.
   Approve availability; verify a synthetic payment only in an isolated test
   environment. Observe the queued jobs and remaining balance.

Run database tests only on disposable names ending `_test`/`_ci` or starting
`test_`. Never point them at the local preview database or a shared environment.
The official MySQL runtime used here is temporary and will need restarting after
a reboot; use the repository's Compose setup for a repeatable team DEV service.

## Release limits

Server-side quote persistence/expiry/payload binding and trusted delivery distance
are still open release blockers. The browser expiration/edit checks do not replace
server enforcement. Existing pricing configuration is unchanged and still needs
business acceptance. Live Cognito, Google consent/Calendar, SES and AWS queue/
Scheduler delivery, hosted TLS/cookies and real payment-provider checks were not
validated by these local tests. Obtain affected owners' review before promotion.
