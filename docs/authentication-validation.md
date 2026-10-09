# Authentication validation

Validated locally on October 9, 2026, on `feat/authentication-macha`, starting from
reviewed commit `88afc1f`, using Node 24.18.0 and Python 3.14.4. No AWS changes,
operator invitations, or live-user mutations were performed.

| Check | Result |
| --- | --- |
| Complete backend suite, including disposable database integration | 270 passed |
| Persistence subset against isolated MariaDB 11.8 | 43 passed, included above |
| Chromium authentication browser suite | 42 passed |
| Frontend production build | Passed |
| OpenAPI standards, examples, configuration and foundation checks | Passed: 23 operations, 146 examples |
| Cognito CloudFormation, cfn-lint 1.57.2 | Passed with no findings |
| Whitespace checks | Passed |

The backend suite covers both login methods, signed RS256 JWT verification,
issuer/client/subject isolation, nonce and PKCE handling, verified email, native
Cognito TOTP assurance, exact stable Google identities, unapproved users,
explicit private proof linking, existing profiles and same-email ambiguity,
application-factor enrollment without a session, enrollment authorization bound
to the exact browser challenge, controlled recovery, principal/peer rate limits,
OTP replay, CSRF/Origin, role/disable changes, fresh authentication, refresh,
expiration, logout, provider failures and customer regression. Audit failures,
concurrent OTP consumption, recovery/disable races, and delayed callbacks are
covered. Secret values are excluded from browser storage and operator SDK logs.

The database subset verifies migration 0001 to 0002 preserves native accounts,
grants and sessions; both migration checksums are required for readiness.
Migration 0001 is unchanged. Tests exercise real row locks, alias/canonical role
joins, enrollment payload compare-and-swap, exact-proof authorization, monotonic
OTP counters, factor versions, cancellation tombstones and atomic auditing.
This local evidence used disposable MariaDB 11.8; CI targets MySQL 8.4. No remote
CI or live production database result is claimed.

The browser suite uses controlled API/provider responses. It covers password
and Google initiation, pending approval with no access, enrollment without a
session, verified-session bootstrap, unused-code errors, throttling, private
recovery receipt display, expiry clearing sensitive content, role/disable
changes, customer isolation, reauthentication, polling and logout. Expiry tests
freeze the browser clock before navigation to avoid wall-clock worker races.
These checks do not establish live Cognito, Google, email delivery, deployed
CloudFormation, or production TLS/proxy behavior.

The local Chromium run used installed Chrome for Testing 149.0.7827.55 through a
temporary Playwright executable-path override. The committed CI configuration
continues to install Playwright's matching Chromium revision. The frontend stays
basic for testing; it introduces no finalized design system.

Repeat checks after installing the pinned dependencies:

```bash
backend/.venv/bin/python scripts/check_foundation.py
backend/.venv/bin/python -m pytest -c backend/pytest.ini -q
npm run build --prefix frontend
npm run test:browser --prefix frontend
cfn-lint infra/cognito-authentication.json
git diff --check
```

Database integration skips unless `RUN_DATABASE_INTEGRATION=1` and disposable
`DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, and `DB_PASSWORD` are exported. Apply
`python -m app.migrations` from `backend/` first. Integration tests mutate and clean
the authentication tables, so use a dedicated test database. Playwright requires
its Chromium installation. Template lint is independent of backend dependencies.

Before release, complete the exact Google redirect, stack, backend configuration,
migration, private native bootstrap, Google proof approval, enrollment and live
provider checks in [deployment](authentication-deployment.md) and
[operator procedures](authentication-operations.md). In particular, verify
Google signed identities metadata, native ACR/AMR, application TOTP recovery,
refresh rotation and all-profile disable against the non-production pools.
Customer password-reset/provider-logout limitations remain documented there.
