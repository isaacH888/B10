# Authentication

Customers and administrators authenticate through separate Amazon Cognito user pools. Customer accounts support email/password and Google through an Essentials pool. Administrator accounts use a Plus pool with native password login and required Cognito TOTP. Google sign-in is available only to customers. There is no public admin access grant, remembered-device bypass, or dashboard account-management API. The frontend remains a basic testing interface.

The Flask backend uses Cognito managed login version 2 and the OAuth authorization-code flow with S256 PKCE. It binds each short-lived, single-use login transaction to the browser and realm with state, nonce, and a private cookie. The browser receives an opaque session cookie; provider tokens and client secrets stay in the backend. MySQL stores hashes of session credentials and encrypted provider tokens. Existing migrations 0001 and 0002 remain unchanged; legacy alias/factor tables are retained for compatibility and private revocation, without enabling administrator Google sign-in. Hosted cookies use `Secure`, `HttpOnly`, `SameSite=Lax`, the `__Host-` prefix, and `/` scope. Authenticated state-changing requests require the exact configured origin and a session-bound CSRF header; login initiation requires that same exact origin before a session exists.

Admin password login pins `identity_provider=COGNITO` and requests fresh authentication with `prompt=login`, `max_age=0`, and `acr_values=urn:cognito:loa:4`. The backend verifies signed token claims, issuer, audience, nonce, expiry, verified email, authentication time, the achieved ACR, and `pwd`, `otp`, and `mfa` authentication methods. It also requires an active local admin grant for that exact issuer and subject. Requesting a stronger login alone is insufficient; the achieved signed claims are mandatory. [AWS describes managed-login step-up and ACR claims](https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-user-pools-step-up-authentication.html).

Customer and admin subjects belong to their configured pool. An email address is contact information, not the identity key or an admin grant. The implementation does not automatically link Google and password accounts by matching email. Google maps `email`, `email_verified`, and `name`; Cognito's verification-status attribute cannot be made writable by an app client. Ordinary mapped attributes remain writable as required by federation. [AWS attribute mapping](https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-user-pools-specifying-attribute-mapping.html), [AWS app-client permissions](https://docs.aws.amazon.com/cognito/latest/developerguide/user-pool-settings-client-apps.html).

## Administrator login and sample dashboard

`/admin/login` offers password login with the existing Cognito authenticator requirement. The API, service and OAuth provider reject Google for administrators. Old admin Google OAuth flows cannot exchange codes, retired application-MFA endpoints are unavailable, and existing Google-assured admin sessions are denied and revoked on use. The admin Cognito app client supports only `COGNITO`; the customer client continues to support `COGNITO` and `Google`.

A successful native password/TOTP callback redirects to `/admin`, which requires an active approved admin session. The basic sample dashboard displays explicitly synthetic booking examples and an overview. Sample content is not loaded from customer/order databases and performs no real booking, payment or export mutations. Role permissions still come from the authenticated server session; customer login, an unapproved account, an expired session or a provider outage cannot open the dashboard.

Owner/Staff invitations, MFA recovery and disable remain private operator procedures. Keep the separate administrator Cognito pool and mandatory native MFA; do not replace them with sample credentials or a demo login bypass.

| Control | Administrator | Customer |
| --- | --- | --- |
| Account creation | Private operator invitation | Managed self-registration or Google |
| Pool tier | Plus | Essentials |
| Access and ID token validity | 5 minutes | 15 minutes |
| Refresh and application session limit | 8 hours | 7 days |
| Application idle limit | 15 minutes | 24 hours |
| MFA | Required native Cognito TOTP | Not required |
| Recovery | Verified private operator | Verified email for password accounts; Google handles its accounts |

Session reads do not extend idle time. Protected business actions may extend it within the fixed session lifetime. Every authenticated request rechecks local access and calls token-authorized Cognito `GetUser`, including checking current Cognito TOTP enrollment for administrators. This detects provider sign-out, revocation, and disable operations; provider or database failures deny access. The `aws.cognito.signin.user.admin` OAuth scope used for `GetUser` authorizes self-account APIs, not IAM pool administration. The browser never receives the access token. [AWS GetUser](https://docs.aws.amazon.com/cognito-user-identity-pools/latest/APIReference/API_GetUser.html).

| Role | Allowed application permissions |
| --- | --- |
| Staff | View bookings and contacts; manage notes and fulfillment |
| Owner | Staff permissions; booking confirmation/cancellation/pricing; payment management; customer exports |

Role and activation changes invalidate existing sessions. Local persistence serializes owner lifecycle changes and prevents disabling or demoting the final active owner. Account invitation, roles, disable, and recovery remain private CLI operations, including for Owners. Future business routes must apply `require_customer` or `require_admin` with the appropriate permission; UI visibility never authorizes an API call. Sensitive future admin actions can require fresh authentication through the guard's `fresh=True` option.

The Plus pool blocks compromised credentials and records authentication events for 90 days. Risk levels are observed with `NO_ACTION`; this configuration does not promise adaptive risk blocking. AWS adaptive MFA requires an optional-MFA setup, so this implementation keeps mandatory TOTP instead. TOTP supplies the chosen second factor and does not have the phishing resistance of a WebAuthn authenticator. [AWS MFA considerations](https://docs.aws.amazon.com/cognito/latest/developerguide/user-pool-settings-mfa.html), [AWS compromised-credential protection](https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-user-pool-settings-compromised-credentials.html).

Local logout revokes the application session immediately. A failed provider revocation records `logout_provider_pending`; admin operators can reconcile it with `revoke-admin-sessions`. There is no background retry worker or customer sign-out reconciliation command. A completed Cognito password reset is not treated as proof that all older application sessions were revoked; guaranteed customer cross-device invalidation after a reset needs an additional provider trigger or recovery integration.

Overlapping login starts reuse a valid private browser-binding cookie for their realm, while each transaction has independent state, nonce, and PKCE values. Each start refreshes the cookie's ten-minute lifetime; each transaction retains its own original ten-minute deadline. Successful and failed callbacks keep that binding cookie until expiry or logout so an overlapping callback remains associated with the same generation.

Authenticated logout cancels both the pending-cookie binding and the current session's recorded binding, clears the realm's cookies, and revokes sessions associated with those bindings. Database cancellation markers prevent callbacks still waiting on Cognito from establishing usable sessions in a cancelled generation, regardless of which operation finishes first. A late login-start request using a cancelled cookie is rejected and clears that cookie; an explicit retry can obtain a new generation. These checks cover associated overlapping flows, not unrelated generations or flow cookies that a browser has lost or deleted. Admin role and recovery commands revoke existing identity sessions; they cannot identify every login flow before the provider has established its user identity. A callback must still satisfy current local access, signed authentication claims, provider checks, and its original transaction deadline after provider requests finish.

Deployment and provisioning are described in [authentication-deployment.md](authentication-deployment.md). Private account procedures are in [authentication-operations.md](authentication-operations.md). No live pools, invitations, or default accounts are created by application startup or tests. With local `AUTH_ENABLED=false`, authentication endpoints remain unavailable rather than granting demo access.
