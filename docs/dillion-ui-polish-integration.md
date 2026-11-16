# UI polish and optional contract links

Prepared November 16, 2026. Integration branch:
`integration/dillion-ui-polish-fixes`. This combines Dillion's
`feature/ui-polish` at `19bb1a5` with committed `dev` at `6a59ce1` and
Isaac's optional-contract-link changes from the primary checkout. The combined
snapshot is prepared for publication and PR review into `dev`.

## Resulting behavior

- Actual admin access-denied and unavailable screens have readable recovery
  buttons, their own theme colors, and a full-height standalone layout.
- Staff can open owner verification from the recovery screen without being
  redirected immediately back to the restricted dashboard. Verification still
  requires an explicit password/MFA flow and does not replay booking actions.
- Catering fieldset/legend resets stay inside the catering page and portal
  dialog. Booking workspace and other admin form section titles remain visible.
- The catering slideshow starts paused for reduced motion, responds to motion
  preference changes, and pauses for mouse hover, keyboard focus, manual
  navigation, offscreen content, and hidden browser tabs. Play explicitly
  restarts a manually paused slideshow.
- Hero shading keeps the copy readable over every slide at phone, tablet and
  desktop sizes. Slide badges use customer-facing labels without placeholders.
- The route conflict preserves `/error-preview`, `/payment/pay`, and
  `/payment/return`. Existing payment components and confirmation layouts remain
  integrated with the public shell.
- Owners can create, approve and reopen bookings without a contract link.
  Missing event end times must still be supplied, and supplied links must use
  absolute HTTPS URLs. Capacity, payment verification and revision checks remain.
- Customer confirmation emails include a booking link or configured fallback
  when available; without either, the confirmation sends without a contract line.
  Idempotent processing still prevents duplicate emails.

## Validation

- Full Chromium suite on the combined snapshot: **261 passed**, including the
  existing Square checks, optional-link workflows and six new
  [UI regression tests](../frontend/tests/ui-polish.spec.js).
- Frontend formatting, production build, foundation validation, and whitespace
  checks pass. The build retains its bundle-size advisory.
- Screenshots cover all four catering photos at 375, 768 and 1440 px, plus the
  actual admin error routes and restored booking workspace section titles.
  Measured minimum paragraph contrast over the rendered photo backgrounds is
  6.60:1; minimum heading contrast is 4.85:1 across those samples.
- An actual mobile quote/order flow uses Flask and disposable MySQL without API
  mocks: quote 200, order 201, matching server pricing, and an idempotent retry
  returning the same order.
- Full backend suite on the combined snapshot: **1,626 passed**, with disposable
  MySQL integration enabled and no skips. This includes missing, blank and null
  contract links, SQL-backed intake, required event ends, and confirmation email
  fallback/omission behavior.

Run the focused and full frontend checks from `frontend/`:

```sh
npm run format:check
npm run build
npx playwright test tests/ui-polish.spec.js
npm run test:browser
```

Live Cognito sign-in, live Square transactions and deployment are separate
provider/environment checks. The local demo uses disposable data and local
service adapters; provider authentication and payments are disabled there.

## Integration boundary

The captured optional-link changes from the primary checkout are included and
tested together with the UI fixes. The original primary working files are
preserved. No schema or dependency changes are introduced by these fixes.
Preserve the original teammate histories and follow the
[development workflow](development-workflow.md) for commit and publication approval.
