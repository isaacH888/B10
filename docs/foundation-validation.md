# Foundation validation record

Updated October 5, 2026. Scope: approved shared scaffold, contract, configuration
and documentation. Evidence below does not prove teammate business features or
Week 4 integration/staging completion. Runtime targets are Node 22/Python 3.12;
local checks used Node 25.9.0, npm 11.12.1 and Python 3.9.6.

## Checks performed

| Check | Actual result / boundary |
| --- | --- |
| Frontend dependency install and `npm run build --prefix frontend` | Passed; Vite 8.3.2 produced the development-shell bundle; customer pages not implemented |
| Locked Python dependency install and `pip check` | Passed; no broken requirements; no domain persistence adapter installed |
| `backend/.venv/bin/python scripts/check_foundation.py` | Passed full OpenAPI 3.1 standards validation; 14 operations and 108 schema-valid examples |
| Contract fixtures | Synthetic line items sum to total, deposit is 50% for the even-cent fixture, CSV has ten columns; no real business rates tested |
| Link/template/style checks | Local Markdown file targets resolve; all 37 root settings documented, no populated credential placeholders, frontend template public-only, no trailing whitespace/emojis in new shared files |
| CI/Compose structure | YAML parses; CI PR trigger/read-only permissions verified; no deployment job; development MySQL port binds loopback only. Docker/remote execution not performed |
| `backend/.venv/bin/python -m pytest -c backend/pytest.ini -q` | 5 passed, 1 skipped; liveness/readiness distinction, CORS/preflight, absent feature route, safe DB failure and hosted secret requirement tested |
| Real MySQL test | Skipped: RUN_DATABASE_INTEGRATION not enabled and no disposable local MySQL; CI is configured to require it, but has not run remotely |
| Temporary local Flask HTTP probes | `/api/v1/live` 200; request ID/no-store headers; configured-origin credentialed CORS header; `/api/v1/health` 503 with safe degraded/unavailable response |
| Temporary local Vite HTTP probe | `http://localhost:5173/` returned 200 and shell HTML; not proof of a rendered browser UI |
| Browser interaction | Unexecuted: no browser available in this session; button behavior, responsive/accessibility, browser cookies/CSRF and end-to-end UI remain unverified |
| `git diff --check` and new-file whitespace scan | Passed before publication; foundation prepared on feature/shared-foundation for review |
| Source preservation | Original charter and logo compare byte-for-byte with HEAD; supplied PDF/DOCX references were read without edits |
| Ignore rules | Private environments, virtual environment, node_modules, dist, backups and exports ignored; templates and lockfiles remain trackable |

Temporary Flask/Vite processes were stopped after HTTP verification. No real
credentials, customer records, live payments or outbound provider actions were used.
The machine's Python/LibreSSL combination emits an urllib3 compatibility warning
while loading the validator; local validation succeeded. Prefer the documented
Python 3.12 baseline; its CI run is still pending.

## Reproducibility

[Setup](development-setup.md) lists the actual install/run/test commands.
The reusable [checker](../scripts/check_foundation.py) and
[CI workflow](../.github/workflows/foundation-checks.yml) replace the earlier
one-time standard-library checker. CI includes disposable MySQL and a real SELECT 1
probe, not migrations or a production database. Owner conformance must be tested
against implemented routes after the API/schema draft is accepted.

## Remaining evidence

- Independent teammate setup and target Node/Python runtime checks.
- Docker Compose execution, real DB connectivity, Bryson migrations/integrity/restore.
- Live catering form, authoritative pricing, order persistence and retry tests.
- Auth/private-route/session/CSRF, emails and provider reconciliation.
- Later Calendar, payment/status/export, reminders and contract automation.
- Actual GitHub PR checks/review, hosting approval, staging/recovery and team demo.

Use the [scenario matrix](integration-tests.md) and [Week 4 gate](staging-readiness.md).
No full business scenario or external deployment is marked passed.

## Earlier baseline

October 3 checks covered documentation only: 13 draft operations, 105 examples
with a targeted custom checker, 30 environment keys and baseline preservation.
Those historical counts do not describe the current 0.2.0-draft contract, and the
custom checker was not full standards validation. Current results above supersede
the earlier setup/validation limitations; API consumer acceptance remains pending.
