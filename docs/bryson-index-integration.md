# Bryson index integration review - November 11, 2026

Reviewed source: [PR #5](https://github.com/isaacH888/B10/pull/5),
`origin/bryson/index-migration` at `1b3c9d5`. The branch includes `dev` at
`e8c2f44` and has no merge conflicts. The reviewed integration combines these
commits with the recovery fixes on `integration/bryson-index-migration`.
Isaac approved committing the fixes and publishing the combined history to `dev`
on November 11, 2026. This publication does not include a production release.

## Change and review fixes

Bryson adds `0009_orders_event_start_index.sql`, a nonunique index named
`orders_event_start` on `orders.event_starts_at`, and allows index creation in
the explicit migration runner. Migrations 0001-0008 retain their original
contents/checksums. API contracts, pricing, authentication and frontend behavior
are unchanged by this contribution.

The original commit `bc050ab` failed Python formatting locally and in GitHub CI.
Bryson pushed the formatting correction `1b3c9d5` during review; it was fetched
and included without rewriting his history.
All four jobs in its [latest GitHub CI run](https://github.com/isaacH888/B10/actions/runs/43093483649)
passed. The additional local recovery fixes still need their own published CI run.

Additional regression tests reproduced two recovery problems in the original
runner:

- A duplicate-index-name error inside `CREATE TABLE` was swallowed, allowing
  an unsuccessful table migration to be treated as complete.
- An existing index with the requested name but different columns, uniqueness,
  sort order or visibility was silently accepted.

The review fix limits duplicate-name recovery to supported `CREATE INDEX`
statements and compares MySQL's existing index metadata with the requested
definition. A mismatch raises `MigrationError` and leaves the migration pending.
Other database errors, including duplicate data during unique-index creation,
propagate normally.

Supported index statements name an unqualified table and one or more simple
columns, with optional `UNIQUE`, backtick quoting and `ASC`/`DESC`. Prefix,
expression and explicit visibility options are rejected before running a
migration because this recovery checker does not support those definitions.
Existing additive table migrations continue through the same checksum and
database-lock checks.

## Validation

Final local checks passed with Python 3.12.16, Node 25.9.0 and disposable
MySQL 8.4.13:

- **1,037 backend tests passed**, including real database persistence,
  authentication, order intake, concurrency, booking automation and 15 migration
  index tests. No backend tests skipped.
- **112 Chromium browser tests passed**, covering checkout, public pages,
  authentication, email controls, admin previews and booking controls.
- Python formatting/lint, frontend formatting and production build, foundation
  contract/configuration/link checks, all three infrastructure template lint
  checks and Git whitespace checks passed.
- A fresh database applied all nine migrations, then reported no pending work.
- A separate database first applied migrations 0001-0008 and saved a synthetic
  customer order through the real quote/order APIs. Applying 0009 preserved
  every customer/order/item row and the previous migration history. Replaying
  the order after constructing a new Flask app returned the original persisted
  response without additional records.
- Marking 0009 interrupted after its index already existed recovered
  successfully. A conflicting same-name index blocked completion and left
  `applied_at` unset; correcting the index allowed recovery. Existing order data
  remained identical throughout.

The first full-suite attempt mistakenly inherited a review-harness
`CUSTOMER_AUTH_ENABLED=false` override. This disabled customer authentication
inside tests that enable it themselves, causing 62 failures. Removing that
harness override produced the passing 1,037-test run; no application change was
needed for those failures.

Validation used only the task's disposable Docker container
`b10-bryson-review-20261111`, loopback port 33319, with separate `_ci` schemas.
The existing development database, private configuration, live providers and
customer data were not used or migrated. Browser tests use controlled provider
and API responses. Local results do not establish live Cognito, SES, Calendar,
payment-provider or deployed-environment behavior.
The disposable review container and its volume were removed after validation;
the existing development container remains running and healthy.

Logs and the upgrade validation harness are under `/private/tmp`:

- `b10-bryson-backend-suite.log`: final passing backend suite.
- `b10-bryson-backend.log`: upgrade/recovery evidence and the initial harness
  configuration failure.
- `b10-bryson-browser.log`: passing browser suite.
- `b10-bryson-validation.py`: disposable fresh-install and saved-order upgrade
  checks. Its fresh-install assertions require new empty schemas.
- `b10-bryson-reviewed/`: recovery copies of the reviewed Python files and diff
  before fetching Bryson's final formatting commit. The matching review stash
  is retained without altering older stashes.

## Integration and migration handoff

Isaac's November 11 approval covers committing the reviewed fixes and pushing
the combined history into `dev`, as required by the
[development workflow](development-workflow.md). The approved publication uses
a fast-forward into `dev`, preserving Bryson's original branch and commits.
PR #5's commits are included along with the recovery fixes described above.
The published integration needs its own remote CI run; the results above record
local validation and the source branch's earlier remote checks.

After source integration, an existing environment still needs its normal
explicit migration step from the repository root:

```sh
cd backend
.venv/bin/python -m app.migrations
```

Use that environment's existing migration configuration. Do not change old SQL
files, edit recorded checksums or delete migration history to force an upgrade.
For a conflicting existing index, inspect and resolve its definition before
rerunning. No migration was applied to the development database during review.

The existing server-side quote persistence/expiry/payload-binding and trusted
delivery-distance release blockers remain in effect. Main/staging/production
promotion is a separate decision.
