# Authentication validation

Validated locally on October 8, 2026, on `feat/authentication-macha`, using Node
24.18.0 and Python 3.14.4. No AWS resources or application accounts were provisioned.

| Check | Result |
| --- | --- |
| Backend suite, including disposable database integration | 145 passed |
| Persistence subset against isolated MariaDB 11.8 | 25 passed, included above |
| Chromium authentication browser suite | 21 passed |
| Frontend production build | Passed |
| OpenAPI standards, examples, configuration and foundation checks | Passed |
| Cognito CloudFormation, cfn-lint 1.57.2 | Passed with no findings |
| Whitespace checks | Passed |

The backend suite covers signed JWT verification, issuer/client/subject isolation,
required completed TOTP, invitation and permission checks, CSRF and Origin,
session expiry, provider outages/revocation, encrypted token rotation, owner
lifecycle protection, private recovery commands, and concurrent session/flow
operations. Logout races include a consumed callback, overlapping tab starts,
canceled-generation retries, and session revocation during provider requests.
Private operator tests also verify passwords are excluded from SDK debug logs.

The browser suite uses controlled API/provider responses to check protected pages,
customer/Google and admin redirects, fresh authentication, permission displays,
expiry, polling, logout retries, and safe unavailable states. These tests do not
prove live Cognito, Google, email delivery, or production proxy behavior.

After simplifying the frontend to a basic testing interface, the production build
and all 21 browser tests passed again. That run used installed Chrome for Testing
149.0.7827.55 through a temporary Playwright executable-path override; the committed
CI configuration continues to install Playwright's matching Chromium revision.
The simplified pages also passed an unmocked check against the running local site.

An additional unmocked smoke check ran Chromium against Vite on port 5173 and
Flask on port 5000. It verified the same-origin API proxy, customer/admin screens,
liveness, and protected access denial with `AUTH_ENABLED=false`, without browser
exceptions. Readiness returned 503 because the default local database and Cognito
configuration are absent; the disposable test database was configured only for tests.

Repeat checks after installing the pinned dependencies:

```bash
backend/.venv/bin/python scripts/check_foundation.py
backend/.venv/bin/python -m pytest -c backend/pytest.ini -q
npm run build --prefix frontend
npm run test:browser --prefix frontend
git diff --check
```

Database integration skips unless `RUN_DATABASE_INTEGRATION=1` and disposable
`DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, and `DB_PASSWORD` are exported. Apply
`python -m app.migrations` from `backend/` first. Integration tests mutate and clean
the authentication tables, so use a dedicated test database. Playwright requires
its Chromium installation. CloudFormation lint is independent of application
dependencies.

[CI](../.github/workflows/foundation-checks.yml) targets MySQL 8.4 and runs migrations,
backend integration, browser/build checks, and template lint. Local persistence
evidence used MariaDB because Docker daemon access was unavailable; no remote CI
result is claimed. Complete the real-provider release checks in
[deployment](authentication-deployment.md) before launch, including the documented
customer password-reset and provider-logout limitations.
