# DEV publication review

Prepared October 29, 2026. Working branch: `dev`. Isaac approved committing the
reviewed changes and publishing this branch in chat on October 29. The first
publication follows this review; current commit and CI status are recorded in GitHub.

## Proposed publication

- Repository: `https://github.com/isaacH888/B10`
- Branch: `dev`
- Proposed commit subject: `feat(dev): integrate backend and authentication for team review`
- Preserve both feature histories in the integration merge: authentication
  `d56689d` and backend `ee74764`, with shared foundation `079f98d` as their base.
- Publish this branch for team review. Environment hosting/deployment and promotion
  to `main` remain separate actions.
- Initial commit/publication approval was received from Isaac for this scope.
  Future commits and pushes still require his explicit approval.

## What teammates will see

Their authentication, sample email, pricing, quotes and order implementations are
combined in one working tree. Their original feature branches are preserved.

The review compared all 13 changed frontend source/configuration files with the
authentication branch after applying the shared formatter: no differences beyond
formatting were found. The dashboard, styling, login screens and frontend behavior
retain the owners' work.

JSON comparisons also confirmed unchanged content for the API contract/examples
and Cognito/customer-email templates. Their diffs contain formatting changes.

Across 26 Python application modules, AST comparison after excluding imports found
changes beyond formatting in only these four files:

| File | Change |
| --- | --- |
| `backend/app/__init__.py` | Combine feature registration with authentication/email initialization and response headers |
| `backend/app/health.py` | Retain cached auth/database readiness and the connection helpers required by orders |
| `backend/app/orders.py` | Enforce existing admin sessions, CSRF and owner/staff status permissions |
| `backend/app/auth/admin_cli.py` | Replace an assigned lambda with an equivalent named function for lint compliance |

Other application Python changes are formatting/import cleanup. Supporting changes
add 12 order-auth integration cases, update test fixtures and the stale foundation
login assertion, add formatting checks/tools, apply the Vite 8.3.5 patch, and
document DEV review and owner handoffs. Archived backend Node references are kept.

## Validation and remaining issues

The application snapshot matches the one previously validated with **786 backend
tests passing**, including the enabled disposable MySQL tests, and **63 Chromium
browser tests passing**. The frontend production build and infrastructure lint
also passed. This review reran Ruff, Prettier, foundation/contract validation and
whitespace checks; only workflow/review documentation changed afterward.

These results do not establish a complete ordering release. Real order storage
still lacks its tables; quote trust/delivery checks, the real catering/admin UI,
automatic order emails and environment/provider configuration remain owner tasks.
Browser tests use controlled API responses. Read the
[validation evidence](integration-validation.md) and the
[six coordination tickets](release-workflow.md#coordination-tickets).

After approved publication, verify the GitHub Actions run for the published SHA
and have the affected owners review the combined work before further promotion.
