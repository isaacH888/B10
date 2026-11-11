# Authentication validation

Validated locally on October 9, 2026, on `feat/authentication-macha`, starting from commit `556ab3a`. The fix adds native administrator password/TOTP challenges, temporary-password replacement and authenticator enrollment. Customer Google/email-password flows and the retained strict administrator OAuth contract remain in place. No AWS resources or live users were modified; protected Cognito configuration/events were inspected read-only. Native choice discovery was probed without entering a password or authenticator code.

| Check | Result |
| --- | --- |
| Full backend suite, disposable MySQL 8.4 | 380 passed; no skipped tests |
| Backend suite without disposable DB | 319 passed; 61 database cases skipped |
| Chromium authentication/dashboard/readiness browser suite | 47 passed |
| Frontend production build | Passed |
| OpenAPI standards, examples, configuration and foundation checks | Passed: 22 operations, 149 schema-valid examples |
| CloudFormation lint | CI-pinned cfn-lint 1.57.2 passed offline |
| Template security assertions | 11 passed, included in backend suite |
| Whitespace checks | Passed |

## What the tests establish

Backend tests cover the required password-to-SOFTWARE_TOKEN_MFA sequence, no session before its successful completion, NEW_PASSWORD_REQUIRED, MFA_SETUP, secure association/verification, discarded/revoked setup-issued tokens and an additional password/TOTP login after enrollment. Signed local RSA JWTs exercise signature, issuer, audience/client, subject, scope, expiration, verified email, freshness and rejection of federated native profiles. Strict OAuth missing-ACR/AMR checks remain enforced; native validation never manufactures those claims.

Negative cases include unapproved/inactive identities, historical Google aliases, matching-email profiles, foreign issuers, wrong codes, malformed provider challenges/results, unexpected second factors, malformed user input, bad Origin/CSRF, expired/consumed/different-browser transactions, provider/database outages, safe audit denial and accidental-query log redaction. Session tests retain owner/staff permission checks, fixed/idle expiration, provider disable/revocation checks, rotating refresh, original authentication continuity, fresh-action checks and logout. Native refresh cannot renew the recorded MFA proof. Access changes during provider calls and authenticator association deny access; per-identity versions also fence a transaction consumed before an operator revokes access.

All persistence tests ran against a new loopback-only MySQL 8.4 container with random temporary credentials and a memory-backed data directory. The container and credential file were removed afterward. Tests establish browser binding, fixed five-minute expiry, five-transition budget, six-way single-consumption concurrency, logout/provider-in-flight cancellation, private access-version fences, audit rollback, customer isolation, pruning, additive migration upgrade/interruption and unchanged earlier checksums. They did not run against development data. Two additional Flask API tests drive the complete password/TOTP/session flow through real MySQL, covering both a legacy grant without an epoch row and a current grant with one. They prevent regression of MySQL returning a DECIMAL for the COALESCE projection: the Store explicitly converts the version to an integer before encrypted JSON serialization.

Browser tests use controlled API/provider responses. They establish the local forms, approved-session-only dashboard, new-password/enrollment flow, no dashboard after enrollment alone, rejected verification, duplicate submission prevention, cancellation, expiry/key removal, private form-data clearing and no secret/token storage. They retain customer password/Google, role/disable, refresh/session polling, logout, fresh-verification, readiness and narrow-viewport regressions. Installed Chrome for Testing 149.0.7827.55 was used through a temporary executable-path override; CI installs its pinned Playwright Chromium.

## What was checked against the running environment

The protected callback record for request `2407f08818ac45318995a085b6e45417` showed `mfa_assurance_missing`; ID/access ACR and AMR presence flags were all false. Read-only Cognito inspection confirmed the newly recreated pool is Plus, mandatory TOTP and password-only; its client is COGNITO-only, enables ALLOW_USER_AUTH, rotating refresh and revocation, and reads email/email_verified/name. The approved owner is enabled, confirmed and bound to the exact local native subject, which also equals its canonical Cognito username. Recent provider events included successful password and MFA challenges. These observations establish the managed-login assurance mismatch, not its undocumented service-side cause.

A credential-free public InitiateAuth probe confirmed native choice discovery returns SELECT_CHALLENGE with PASSWORD available and no tokens. The preferred-password request requires PASSWORD in AuthParameters, as documented by AWS; the provider implementation and tests were corrected to submit it in that operation. This discovery probe did not complete password authentication or MFA and does not establish a successful real native login. The first account-holder retry hit a local serialization error before the TOTP step because the unsigned login-version projection arrived as Decimal; the integer conversion was verified against the real approved row, covered by the complete MySQL/API tests, and loaded into the running backend. The subsequent live retry succeeded: the account holder confirmed the dashboard opens after password and authenticator entry. Protected native completion request `5afb7d22596c40189d9b22c839af8a3f` and one active local admin session corroborated that result.

The new additive local `0004_admin_login_epochs.sql` migration was applied with identity count unchanged; migrations 0001-0003 were not edited. The backend was restarted with operator AWS credential variables excluded. Unmocked local API checks verified HTTP 200 readiness, database/authentication ready, native password bootstrap, HttpOnly/SameSite=Strict cookie, no-store responses, CSRF-protected cancellation, protected admin HTTP 401 when signed out and admin Google HTTP 422. An unmocked Chromium check verifies the actual local admin/customer forms and protected redirect; it submits no credentials and captures no trace or secrets.

## Remaining live verification

Native owner password/TOTP login and dashboard access were verified live after the MySQL conversion fix. Complete live onboarding/setup, refresh rotation, logout, account lifecycle and customer regressions still require the approved account holder/operator to follow [native live verification](authentication-native-admin.md#live-verification-still-required). Mocked browser success and cryptographic fixtures alone do not prove completed Cognito authentication; the reported live success is specifically the existing owner's password/TOTP/dashboard flow. No live user was reprovisioned, reset, disabled or deleted during this fix. No CloudFormation update was deployed.

The existing client already supports the implemented USER_AUTH flow. A separately authorized CloudFormation change sets its challenge duration from three to five minutes, matching the application deadline; three minutes remains safe but can expire setup sooner. See the [exact configuration/release steps](authentication-native-admin.md#aws-configuration-and-release). Preserve the customer Google provider/redirect and keep admin Google disabled. Hosted TLS/proxy behavior, SES delivery and remote CI remain unverified.

Repeat checks after installing pinned dependencies:

```bash
backend/.venv/bin/python scripts/check_foundation.py
backend/.venv/bin/python -m pytest -c backend/pytest.ini -q
npm run build --prefix frontend
npm run test:browser --prefix frontend
cfn-lint infra/cognito-authentication.json
git diff --check
```

For all database cases, export `RUN_DATABASE_INTEGRATION=1` and a genuinely disposable `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`. The database name must end in `_ci`/`_test` or start with `test_`; these tests mutate authentication tables. Apply migrations in that isolated environment before running the suite. Never point it at existing development or production users.
