# Latest push integration - November 11, 2026

This DEV integration includes `origin/feat/frontend-dillion` at `0521040`,
the adapted Aneena homepage/sign-in work and the customer authentication
configuration fix. The November 11 remote fetch found no additional pushes.
This is a source integration, not a deployment or completion of the live admin
workflow.

## Sources and preservation

- Fetched every remote branch with pruning. Dillion's three November 10 commits
  (`b9f79f4`, `304b126`, `0521040`) were the only newly fetched work.
- Authentication/Calendar, backend, catering-form, shared-foundation, `dev` and
  `main` branch tips are already included in the current history.
- Aneena's standalone upload at `origin/frontend-aneena` (`fa562e1`) is adapted
  into `PublicSite.jsx`, scoped CSS and the Vite asset pipeline. Its root HTML and
  sample sign-in handlers are not additional app entry points.
- The older `origin/macha` is the October 1 charter source, already preserved in
  `docs/project-charter.md`; it has no new application changes to integrate.
- Aneena's `frontend-aneena` source branch is preserved. The redundant remote
  `feature/aneena-frontend-sample`, which matched `dev` and contained no unique
  commits, was deleted with the owner's explicit approval.
- The initial local tracked diff is
  backed up at `/private/tmp/b10-sync-local-before.patch`, and all 17 changed or
  untracked files were archived at
  `/private/tmp/b10-local-before-sync-20261110-135244.tar.gz`. The saved Git stash
  is retained as an additional recovery copy.

## Combined behavior

The homepage and customer sign-in use Aneena's design. Dillion's updated catering
page keeps its own header, hero, form and footer, with working links to the public
homepage sections and customer sign-in/account routes. It still calls the existing
quote and order APIs, preserves idempotent retries, and shows the server response
on confirmation. The page no longer renders a second public header/main/footer.
Shared fonts are served locally. Catering fieldset/legend styling is scoped so it
does not hide authentication or automation controls.

The new dashboard, order list/detail, calendar and inventory screens are available
to authenticated owners with `bookings:read`. They use the existing session polling,
expiry and CSRF-protected logout behavior. Signed-out users, authentication outages,
staff accounts and owners without booking access cannot render these screens.
Account links return to the real session screen.

These new admin screens are explicitly labeled **design previews**. Their fixture
records and mutations remain temporary browser memory. Their proposed
`/api/v1/admin/orders`, `/admin/calendar` and `/admin/inventory` contracts are not
implemented backend endpoints. Changing `USE_MOCK_API` alone will not connect them.
Live booking intake, approval, payment verification and Calendar operations remain
at `/admin/automation`, linked from every preview. Inventory persistence still needs
a backend contract, storage and authorization implementation.

Calendar preview fixes keep date-only events on their intended calendar day,
filter counts by both year and month, derive the upcoming list from the selected
month's records, and exclude cancelled sample orders. Connection controls open the
real booking workspace. Mobile navigation and the Calendar connection panel wrap
within the viewport.

Customer authentication can run independently in development using
`CUSTOMER_AUTH_ENABLED=true` with `AUTH_ENABLED=false`; hosted environments still
require both realms. Only enabled providers are constructed and all disabled admin
routes retain their guards. The owner confirmed live Google customer sign-in after
supplying private settings and starting Docker/MySQL with all eight migrations.
The new local database still needs an approved admin identity/role mapping before
real administrator login can succeed.

The temporary sign-in-free UI preview runs from a file outside the repository,
on a separate loopback port with no real API proxy. That preview fixture and its
simulated session are not part of this DEV integration. Normal admin routes
remain protected.

## Validation

The November 11 publication checks passed:

- All **1,022 backend tests** against a new disposable Docker MySQL 8.4.13
  database after applying all eight migrations. The validation container and its
  volume were removed afterward; the development database was not used.
- All **112 Chromium browser tests**, including protected admin previews,
  customer authentication, checkout, booking controls and responsive public pages.
- Frontend formatting and production build, Python formatting/lint, foundation
  contract/configuration/link checks and Git whitespace checks.
- Changed-file credential-pattern checks; private environment files remain ignored.

GitHub CI runs separately after publication; local results are not a claim that
remote CI or deployment has completed.

The preceding November 10 integration baseline passed:

- All eight migrations applied to a new disposable MySQL 8.4.13 database on
  loopback port 33316. All **985 backend tests passed**, including persistence,
  order intake, replay and concurrency checks. The temporary server was shut down.
- The final full suite passed **112 Chromium tests**, including all **19 admin
  integration tests**, checkout, authentication, sample email and real-workspace
  browser flows. The final Calendar mobile panel adjustment passed an additional
  targeted run at 375, 768 and 1440 pixels.
- Frontend production build and formatting passed. Desktop/mobile screenshot
  review covered the homepage, catering, sign-in, dashboard and Calendar at 375
  and 1440 pixels, with no horizontal document overflow. Review images are in
  `/private/tmp/b10-sync-qa`.
- Python formatting/lint and all three infrastructure template lint checks passed.
  Foundation contract/examples/configuration/link checks and Git whitespace checks
  passed after the final documentation update.

Browser tests use controlled authentication/provider/API responses. Backend
persistence tests use synthetic data and the disposable database. These checks do
not establish live Cognito, SES, Google Calendar or deployed-environment behavior.
No live customer order, payment, message or calendar event was created.

Existing quote-persistence, server-side expiry/payload matching and trusted
delivery-distance pricing release blockers remain documented in the project README.

## Reproduce

Use the normal checks in `readme.md`. This validation's temporary Chromium install is
available with:

```sh
PLAYWRIGHT_BROWSERS_PATH=/private/tmp/b10-sync-playwright npm run test:browser --prefix frontend
```

For persistence checks, configure a fresh disposable MySQL database and export its
DB settings with `RUN_DATABASE_INTEGRATION=1` before running pytest. Tests delete
synthetic records and require a database name ending in `_test`/`_ci` or beginning
with `test_`. The private development database was not modified.
