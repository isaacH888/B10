# Authentication validation

Validated locally on October 9, 2026, on `feat/authentication-macha`, starting from
commit `f3f5ef9`. This change removes administrator Google sign-in, retains customer
Google and email/password login, and adds a protected basic sample dashboard.
No AWS resources or user accounts were modified. A subsequent readiness repair restarted the existing local MySQL container without changing application data or migrations. Administrator callback troubleshooting then added private MFA denial reasons and clearer sign-in guidance without relaxing authentication requirements.

| Check | Result |
| --- | --- |
| Backend suite | 198 passed; 41 disposable-database tests skipped |
| Chromium authentication/dashboard/readiness browser suite | 38 passed; both affected callback tests passed again after the final wording change |
| Frontend production build | Passed |
| OpenAPI standards, examples, configuration and foundation checks | Passed: 19 operations, 125 examples |
| Cognito template security assertions | 10 passed, included in backend suite |
| Whitespace checks | Passed |

Backend checks cover password-only administrator initiation, native signed Cognito
ACR/AMR and TOTP requirements, issuer/client/subject/nonce/expiration validation,
active approval, staff/owner permissions, CSRF and exact Origin, refresh, logout,
provider failures, customer password/Google regression, and session expiration.
Retirement tests reject administrator Google at the route, service and provider;
consume old Google OAuth state without exchanging codes; revoke historical
Google/app-TOTP sessions before provider I/O; and prove retired MFA endpoints and
operator approval commands grant no access. Historical aliases cannot obtain a
native password session by inheriting a canonical role.
Diagnostic tests distinguish missing/insufficient signed MFA claims, stale native
authentication and missing TOTP registration; they verify denial audit records
contain only safe codes/request IDs and that audit-storage failure cannot grant
a session.

Browser checks use controlled API/provider responses. They cover both customer
methods and authenticated returns, password-only administrator login, a successful
admin sign-in return opening the protected dashboard, clearly synthetic booking
counts/table, permission-based previews, reload, role/disable changes, expiry,
reauthentication, logout/retry, malformed sessions and a 320px viewport. Readiness tests distinguish unreachable Flask, stopped MySQL, missing authentication storage, disabled sign-in and malformed status data. Only validated `/health` responses can expose degraded data on HTTP 503; failed authentication APIs still deny access. No browser
token storage or sample login bypass is introduced. This run used installed Chrome
for Testing 149.0.7827.55 via a temporary executable-path override; CI installs
Playwright's matching Chromium revision.

The Store and both existing migrations are unchanged. Database integration tests
require a separately configured disposable database and were not run against the
existing development data. Denial auditing uses the existing audit schema and
was observed in the running local MySQL database during the user's retry. Static template checks
verify customers retain COGNITO/Google, administrators use COGNITO only, mandatory
native MFA remains ON, and customer mapping/redirect configuration stays intact.
Successful live Cognito/Google/SES login, stack deployment and production
TLS/proxy behavior remain unverified. The template linter was not rerun for this change.

Repeat checks after installing the pinned dependencies:

```bash
backend/.venv/bin/python scripts/check_foundation.py
backend/.venv/bin/python -m pytest -c backend/pytest.ini -q
npm run build --prefix frontend
npm run test:browser --prefix frontend
git diff --check
```

For database coverage, export `RUN_DATABASE_INTEGRATION=1` and disposable
`DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`; apply migrations from
`backend/` with `python -m app.migrations` first. These tests mutate the configured
authentication tables. CI targets MySQL 8.4; no remote CI result is claimed.

Before release, follow [deployment](authentication-deployment.md) and
[private operator procedures](authentication-operations.md). Verify real customer
Google/password login, required native admin TOTP and dashboard landing, refresh,
logout and revocation against the development pools. Updating the local template
does not remove a provider or redirect in AWS/Google Cloud. Preserve the customer's
Google redirect and review any retired administrator-provider cleanup separately.

An unmocked Chromium check against the running localhost site confirmed HTTP 200
readiness with `database: ok` and `authentication: ready`, the password-only admin
button, HTTP 422 for admin Google requests, both customer login buttons, and no
browser runtime errors. The local MySQL container was previously stopped and is
now healthy; its existing data volume was preserved. This check did not complete
a live Cognito sign-in or create any accounts.

During a subsequent user-initiated native administrator sign-in, the callback
recorded `mfa_required` with the private reason `mfa_assurance_missing`; no admin
session was created. The user reported entering an existing authenticator code.
The live public Cognito authorization redirect retained both the requested
`urn:cognito:loa:4` level and `max_age=0`, and the local initiation pinned the native
provider and exact callback. This establishes the missing signed-claim gate,
not the underlying pool configuration. Read-only configuration inspection could
not complete because the private AWS operator session had expired. Follow the
[MFA troubleshooting procedure](authentication-operations.md#diagnosing-an-administrator-mfa-callback-failure)
to verify feature plan, native ACR settings and managed-login configuration before
making a separately authorized cloud change.
