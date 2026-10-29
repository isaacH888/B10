# Combined branch validation

Validated locally October 29, 2026, on `integration/combined-validation`.
Use the [release workflow and coordination tickets](release-workflow.md) for the
next DEV/TST/PROD steps.

## Branch coverage

| GitHub branch | Fetched tip | Integration |
| --- | --- | --- |
| `main` | `ca2a1e8` | Ancestor of the shared foundation |
| `feature/shared-foundation` | `079f98d` | Shared baseline |
| `feat/authentication-macha` | `d56689d` | Authentication, frontend, migrations and sample email; includes the merged order-confirmation-email branch |
| `feature/backend-anh` | `ee74764` | Pricing, quotes, order submission/retrieval/status and archived Node references |
| `macha` | `baae6e0` | Older README/charter/image work; its image is already identical in the foundation and it adds no separate application implementation |

The source branches are preserved. Validation and conflict fixes are local; GitHub
publication, PR review and remote CI execution are separate steps.

## Changes made

- Combined both branches in the Flask factory, retaining quote/order registration,
  authentication/email initialization, request headers and cached health checks.
- Retained the shared database connection helpers required by the order API.
- Connected order retrieval/status to real authentication guards. Reads require
  `bookings:read`; confirmation/cancellation require their owner permissions;
  fulfillment accepts the existing staff permission. Mutations enforce Origin/CSRF.
- Added 12 integration cases covering public quotes/submission, anonymous/customer
  denial, CSRF, owner/staff permissions, revocation and disabled authentication.
- Updated the foundation assertion that incorrectly expected admin login to be absent.
- Applied Ruff formatting/import checks to 45 Python files and Prettier to active
  frontend, JSON and YAML code/configuration. Archived Node references are preserved.
  CI now checks formatting on subsequent changes.
- Updated Vite from 8.3.2 to the compatible 8.3.5 patch; the dependency audit reports
  zero vulnerabilities. Added pinned Ruff and Prettier tools.
- Updated the ignored frontend API URL to `/api/v1` and rebuilt the local backend
  environment with Python 3.12. The previous Python 3.9 environment is preserved
  under ignored `.venv/previous-backend-python39`.

## Executed checks

| Check | Result and scope |
| --- | --- |
| Full backend suite | **786 passed**, no skips, with disposable MySQL enabled |
| Backend suite without MySQL | **709 passed, 77 skipped**; skips require a disposable database |
| Chromium browser suite | **63 passed**; browser tests mock API responses and do not prove live AWS login or email delivery |
| Frontend production build | Passed, including normal loading of local frontend settings |
| Ruff lint and format | Passed for backend and validation scripts |
| Prettier check | Passed for active frontend and selected JSON/YAML configuration |
| OpenAPI/foundation validation | Passed: 23 operations and 151 schema-valid examples, plus links, configuration and whitespace checks |
| CloudFormation templates | Both passed `cfn-lint==1.57.2`; resources were not deployed |
| Python dependency compatibility | Passed against installed locked dependencies |
| Frontend dependency audit | Zero reported vulnerabilities after the Vite patch |
| Local HTTP smoke | Frontend HTTP 200; `/api/v1/live` reaches the integrated Flask app through Vite |
| Fresh-database order submission | **Blocked**: required order tables are missing; confirmed HTTP 503 |

Runtime evidence: Python 3.12.16, Node 25.9.0, MySQL Community Server 8.4.13 on
macOS. The disposable server used localhost:33306 and a separate
`popssibilities_integration_test` database. No existing development data was used.
MySQL was obtained from the [official Community Server distribution](https://dev.mysql.com/downloads/mysql/8.4.html).
Docker/Compose execution and the Node 22 GitHub runner were not verified locally.

## Remaining integration blockers

1. **Order schema and transactions:** the six supplied migrations contain only
   authentication/email tables. `customers`, `orders` and `order_items` do not
   exist after migration. A real, valid order POST returns `503 service_unavailable`.
   Existing order SQL tests use fake connections. Anh/Bryson must resolve the
   [database mappings](database-integration-review.md) and supply the domain schema
   before persistent orders can pass an end-to-end check.
2. **Quote trust and delivery pricing:** quote IDs are not persisted or checked for
   expiry/revision/payload equality at submission. The contract adapter substitutes
   zero miles when delivery distance is absent. These limitations prevent treating
   a demo quote as an accepted, verified delivery offer.
3. **Database idempotency:** concurrent submissions rely on a unique-key/schema
   handoff that is absent. Status changes rewrite `response_json`, so database-mode
   POST replay can return a changed order instead of the original response. The
   replay snapshot and concurrent duplicate handling need real database coverage.
4. **Business UI and integrations:** the dashboard contains labeled sample bookings;
   it does not call the new order APIs. A catering/order form, order list, automatic
   order-confirmation email, payment and Calendar flows are not connected. The
   customer email action sends a sample confirmation only.
5. **Live provider configuration:** local authentication remains unavailable until
   MySQL and both Cognito clients are configured. The current preview returns 503
   for session endpoints. SES is opt-in and needs its documented configuration.
   This validation did not log in to AWS-backed accounts or send messages.

## Reproduce

Install dependencies using [development setup](development-setup.md), then run:

```sh
backend/.venv/bin/python -m ruff check backend scripts
backend/.venv/bin/python -m ruff format --check backend scripts
backend/.venv/bin/python scripts/check_foundation.py
backend/.venv/bin/python -m pytest -c backend/pytest.ini -q
npm run format:check --prefix frontend
npm run build --prefix frontend
npx --prefix frontend playwright install chromium
npm run test:browser --prefix frontend
git diff --check
```

For all database tests, export private settings pointing at a **disposable**
database named `*_test`, `*_ci` or `test_*`, set `RUN_DATABASE_INTEGRATION=1`, and run
the same backend test command. Those tests delete their authentication/email fixture
rows. Do not point them at a development database containing data to preserve.

Run Flask and Vite in separate terminals using the development guide. Open
`http://localhost:5173`; Vite proxies `/api/v1` to Flask on `127.0.0.1:5000`.
