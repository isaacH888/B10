# Dillion UI follow-up review — November 17, 2026

The seven commits below can be integrated into `dev` with the conflict resolutions
and regression fixes prepared in this checkout. Isaac approved publication and
integration on November 17, 2026. The original project checkout and teammate
branches are preserved.

## Source and candidate

- Reviewed base `dev`: `19d9d613c12b5d2f88c75a52aa44f9d8330221c5`.
- Dillion's `feature/ui-polish`: `41d1309d00150f0fd2e7402a82f8f24bd3230e96`.
- Author recorded by Git: `wistyblu`.
- Candidate branch: `integration/dillion-ui-polish-20261117`.
- Candidate checkout: `/private/tmp/b10-dillion-review-20261117`.
- The integration uses a merge commit to preserve Dillion's commit ancestry.
- Local `dev` in the original checkout is one commit ahead and ten behind remote
  `dev`; the candidate uses remote `dev` and does not reset the local branch.

All source commits were made November 16, 2026, in America/Chicago time:

| Commit | Time | Change |
| --- | --- | --- |
| [c808c2d](https://github.com/isaacH888/B10/commit/c808c2d) | 1:38 PM | Authentic catering photos, new error mascot and session-error styling |
| [1da53d7](https://github.com/isaacH888/B10/commit/1da53d7) | 2:41 PM | Restore three catering slideshow slides |
| [40e7602](https://github.com/isaacH888/B10/commit/40e7602) | 2:49 PM | Catering-page formatting |
| [2baacda](https://github.com/isaacH888/B10/commit/2baacda) | 8:13 PM | Booking detail cards and action tabs, order intake, date-range filters and Calendar connection controls |
| [a6c4307](https://github.com/isaacH888/B10/commit/a6c4307) | 9:28 PM | Regression and booking-action spacing fixes |
| [f9367b1](https://github.com/isaacH888/B10/commit/f9367b1) | 9:42 PM | Handle bookings without a source order |
| [41d1309](https://github.com/isaacH888/B10/commit/41d1309) | 10:09 PM | Distinguish the payment-management region from Square Checkout |

## Conflict resolutions and review corrections

Three files conflict with the current `dev` branch:

- `AdminDashboardPage.jsx`: retain Dillion's improved empty-state presentation.
- `OrderDecisionControls.jsx`: retain `dev`'s explicit decision confirmation,
  duplicate-submit guard and start-based Central-time end selector, applying
  Dillion's layout wrapper. Terminal requests keep `dev`'s decision suppression.
- `AutomationDashboard.jsx`: retain the new booking detail layout and action
  navigation, while preserving Central-time dropdowns for intake/reopening and
  the readable “deposit paid” wording.

Additional corrections in the candidate:

- Restore review/approval controls for ordinary pending and awaiting-deposit
  bookings. The source branch limited them to owner-review/conditional states,
  making normal booking approval unavailable in the redesigned workspace.
- Keep the external-payment form disabled during a mutation, preserving the
  protection supplied by the previous enclosing fieldset.
- Display Google Calendar connection failures, including expired-verification
  instructions, rather than silently refreshing away the error.
- Preserve the sample preview's declared read-only behavior. The source's new
  in-memory booking/notification POST handlers are omitted. Its sample GET data
  and richer intake records remain; the sample recipient is synthetic and the
  dashboard request count matches the three intake records.
- Update the sample-preview test's stale row selector to locate the order by its
  contents rather than assuming the order ID is the first table column.

No backend, API-contract, migration or dependency changes are introduced.
Existing customer account, deposit and receipt changes from `dev` remain included.

## Validation

- Frontend formatting: passed.
- Production frontend build: passed; the existing bundle-size advisory remains.
- Foundation validation: passed, including 50 operations, 187 schema-valid
  examples and 252 local links including this report.
- Backend: **1,562 passed, 183 skipped**. This invocation did not enable disposable
  MySQL integration; no backend files are changed by the candidate.
- Main browser suite: **302 distinct cases verified**. The full run passed 297;
  four cases hit trace-cleanup errors because two test runners initially shared
  the default output folder, and one gallery-rotation assertion timed out. All
  five passed in a targeted rerun using an isolated output folder. No product
  code was changed for those reruns.
- Separate sample-preview suite: **5 passed**, including the expanded read-only
  mutation checks. Its two stale selectors and sample request count were
  corrected before the passing run.
- Added browser cases cover pending/awaiting-deposit review access, Google
  connection errors, CSRF on connection mutations, successful disconnection,
  expired verification and staff access restrictions.
- Added preview assertions reject notification and booking mutations.
- Visual QA at 375, 768 and 1440 pixels: booking list, booking details and orders
  have no document-level horizontal overflow or JavaScript page errors. Desktop
  booking details and mobile review/date controls were visually inspected.
- Whitespace checks: passed.

Local browser JSON reports are in `/private/tmp/b10-dillion-*-tests.json`;
backend output is `/private/tmp/b10-dillion-backend-tests.log`. Screenshots and
layout measurements are in `/private/tmp/b10-dillion-visual-review-20261117/`.
Runtime: Node 25.9.0, npm 11.12.1; backend tests use the original project's virtualenv.

## Remote status and publication

Dillion's latest [branch CI run](https://github.com/isaacH888/B10/actions/runs/44015200609)
passed. The current `dev` [run](https://github.com/isaacH888/B10/actions/runs/44065063884)
passed frontend, Python, backend/contract, infrastructure and Lambda-package jobs;
its DEV deployment job failed. No deployment retry or configuration change is
part of this review. Live Google authorization and Square transactions were not run.

No existing pull request from `feature/ui-polish` was returned by GitHub at review time.
The approved publication sequence is to commit this reviewed merge, push the
integration branch and open a PR into `dev`, then require the candidate's GitHub
checks before merging. A merge into remote `dev` triggers the DEV deployment workflow.

The [repository workflow](development-workflow.md) states: “Isaac requires explicit
approval before each commit or push.” Isaac's November 17 approval authorizes
committing and pushing this reviewed integration and merging it into `dev` after
GitHub checks pass.
