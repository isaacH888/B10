# Google Calendar implementation reference

This feature reuses Flask, the existing authenticated owner sessions, and MySQL.
Automated Google tests use `MemoryGoogle` or mocked HTTP responses; they do not
verify a live Google project, deployment, consent screen, or AWS account.

## OAuth configuration

Enable Google Calendar API in a Google Cloud project and create a **Web
application** OAuth client. Configure the consent screen/test users and register
the exact `GOOGLE_REDIRECT_URI`, including scheme, hostname, port and path:

```text
https://frontend.example.com/api/v1/admin/automation/google/callback
```

OAuth consent can succeed even when the Calendar API is disabled. If the API
returns `accessNotConfigured` or `SERVICE_DISABLED`, enable **Google Calendar
API** in **APIs & Services → Library** in the project that owns this OAuth client.
Wait for the change to take effect, then start a fresh connection from the
dashboard. Repeating consent alone does not enable the API.

The callback requires the same authenticated owner session that initiated the
flow. Start the connection in the owner's dashboard browser. Configure the
existing session cookie for HTTPS. This project requires the browser's exact
frontend origin with `/api/v1/*` proxied to the API; use that frontend origin
for both the connect action and registered callback. Hosted `__Host-` session
cookies remain bound to that origin.

For local development, register this exact authorized redirect URI on the Web
application client referenced by the Secrets Manager client ID:

```text
http://localhost:5173/api/v1/admin/automation/google/callback
```

If Google shows `redirect_uri_mismatch`, open Google Cloud Console, select the
project that owns the configured client, then Google Auth Platform -> Clients ->
that Web application. Add the URL above in **Authorized redirect URIs** and save,
preserving existing callbacks such as Cognito sign-in. The scheme, hostname,
port, path and trailing slash must match exactly. Return to the owner dashboard
and start Connect Google Calendar again so it uses a fresh state. Updating the
Google registration does not require changing the app's already-correct callback
or restarting Flask. Google documents exact matching in the
[web-server OAuth flow](https://developers.google.com/identity/protocols/oauth2/web-server).

If Google returns `403 access_denied` and links to the development/testing brand
verification guidance, check the consent audience in the same project that owns
the configured OAuth client. In Google Auth Platform -> Audience, an External
app with publishing status **Testing** allows only explicitly listed test users.
Under **Test users**, choose **Add users**, enter the exact Google account chosen
on the Calendar consent screen, and save. The website's owner-login email may be
different from that Google account. Start Connect Google Calendar again from
the dashboard after saving. Development/testing does not require publishing the
app publicly; see Google's
[development/testing guidance](https://developers.google.com/identity/protocols/oauth2/production-readiness/brand-verification#projects-used-in-dev-test-stage).
If the account is already listed, use the main error text to distinguish a
Google Workspace administrator policy or another consent restriction before
changing further settings.

Store this JSON in Secrets Manager at `GOOGLE_CLIENT_SECRET_ARN`:

```json
{"client_id":"<google-web-client-id>","client_secret":"<google-web-client-secret>"}
```

The token secret under `GOOGLE_TOKEN_SECRET_PREFIX/<sha256-owner-id>` contains
access/refresh tokens and expiry. Only server roles may access it. Authorization
code exchanges and refreshes use bounded HTTPS calls; public responses and error
messages never return the tokens or Google's raw error bodies. State is random,
hashed in MySQL, expires after the configured TTL, is consumed before token
exchange, and is bound to the existing authenticated session token hash.

With `GOOGLE_EXISTING_CALENDAR_ID` empty, the service requests only
`https://www.googleapis.com/auth/calendar.app.created`, provisions **Popssibilities
Catering**, and persists its calendar ID across reconnects/disconnects. Disconnect
revokes the grant best effort and erases stored tokens, retaining the calendar
ID and booking/payment history. If Google's revoke endpoint was unavailable,
remove the app in Google Account security settings as well.

To use an already existing owner calendar, set `GOOGLE_EXISTING_CALENDAR_ID` to
the calendar ID copied from Google Calendar **Settings → Integrate calendar**,
then reconnect. This explicitly requests
`https://www.googleapis.com/auth/calendar.events`. The configured account must
have write access. This scope also permits shared writable calendars; select a
calendar controlled by the owner. Existing mapped events are marked for owner
repair when their stored calendar differs from the selected target. Authorized
repair removes the owned event from the old accessible calendar before creating
the projection on the selected target. If old-calendar access was removed,
restore it before repair to prevent leaving duplicate events.

## Deliberate repair and ambiguous calendar creation

Booking event IDs are deterministic SHA-256 hexadecimal strings, which use only
Google's allowed base32hex alphabet. Ownership is verified with private
application/booking/owner metadata before updates or deletions. Missing or
manually deleted mapped events require the dashboard's explicit owner repair
action. If Google retains ownership on a deleted event, repair restores it. If
only a tombstone remains, repair persists the next event generation before
inserting, so retries and crashes converge to that generation's stable ID.
Reopening an application-cancelled booking restores its owned event; an
underpaid reopened booking keeps its calendar projection removed until another
verified deposit and valid reservation confirm it.

Google calendar creation has no idempotency key and the narrow scope cannot list
arbitrary calendars. Before provisioning, the service commits
`calendar_provisioning=true`. A definitive HTTP rejection clears the marker and
saves the actionable error, allowing a later connection to try again. A network
failure, uncertain HTTP response, or server failure retains the marker because
the creation outcome is unknown. If the process dies after Google created the
calendar but before its ID was saved, a subsequent connection refuses to create
another calendar. An operator must check Google Calendar and recover its ID.
Use the following procedure with a backed-up database and the correct owner ID:

1. In Google Calendar, find **Popssibilities Catering** and copy its calendar ID
   from **Settings → Integrate calendar**. Verify it belongs to this application
   and account. Check for an already saved `calendar_id` before changing data.
2. With an authorized MySQL client, inspect and recover that owner's connection:

   ```sql
   SELECT owner_id, JSON_EXTRACT(data, '$.calendar_id') AS calendar_id,
          JSON_EXTRACT(data, '$.calendar_provisioning') AS provisioning
   FROM automation_connections WHERE owner_id = '<owner-identity-id>';

   UPDATE automation_connections
   SET data = JSON_SET(data, '$.calendar_id', '<verified-google-calendar-id>',
                       '$.calendar_provisioning', CAST('false' AS JSON))
   WHERE owner_id = '<owner-identity-id>'
     AND JSON_EXTRACT(data, '$.calendar_provisioning') = CAST('true' AS JSON);
   ```

3. Reconnect through the dashboard, verify that its status displays the recovered
   calendar, then retry pending calendar jobs. The callback checks calendar
   access and resumes durable booking work.

If investigation establishes that no calendar was created, an authorized
operator may clear only the provisioning marker and reconnect to create one.
Do not clear the marker solely because the callback failed. If the calendar was
permanently deleted, explicitly configure a replacement existing owner calendar
and reconnect, then repair affected bookings. Do not silently clear event
mappings or remove ownership metadata.

## Explicit local simulation

The default Google adapter stays disconnected until real credentials are
configured. For development/tests that intentionally simulate Google, inject
these adapters into `create_app(test_config)` (keep all production settings out
of that test configuration):

```python
from app import create_app
from app.automation.google import MemoryGoogle, MemorySecrets

app = create_app({
    "AUTOMATION_ENABLED": True,
    "AUTOMATION_MODE": "local",
    "GOOGLE_CLIENT_SECRET_ARN": "local-google-client",
    "GOOGLE_REDIRECT_URI": "http://localhost:5173/api/v1/admin/automation/google/callback",
    "AUTOMATION_GOOGLE": MemoryGoogle(),
    "AUTOMATION_SECRETS": MemorySecrets({
        "local-google-client": {"client_id": "local-client", "client_secret": "local-placeholder"},
    }),
})
```

Call `oauth.start(...)`, parse its state in the test, and call `oauth.finish(...)`
with a fake code and the same owner/session. The fake authorization URL is not a
live consent flow. Tests exercise the same state, token persistence and worker
logic without contacting Google. Memory adapters and their state exist only in
one Python process; the runtime's separate `work-local` command cannot inspect a
running web process's in-memory queue. For an end-to-end local simulation use
`app.extensions['automation_services']['dispatcher'].dispatch()` and process
that same instance's `queue.messages` in the same process/test.

## Official references checked for this implementation

- [Google OAuth web server flow](https://developers.google.com/identity/protocols/oauth2/web-server):
  exact redirect URI matching, state, offline authorization, token exchange and
  refresh. Refresh responses may omit a replacement refresh token; stored
  refresh tokens are preserved.
- [Google Calendar OAuth scopes](https://developers.google.com/workspace/calendar/api/auth):
  the app-created scope permits secondary-calendar creation and managing their
  events; existing calendars use the events scope.
- [Events: insert](https://developers.google.com/workspace/calendar/api/v3/reference/events/insert):
  caller-supplied event ID alphabet/length, `sendUpdates=none`, event date/time
  and IANA time-zone fields, private extended properties and cancellation
  tombstone behavior.

The main automation setup/runbook documents staging verification, AWS delivery,
email and audited external payment verification. A staging run must still
exercise real consent, refresh, calendar creation/reuse, deposit confirmation,
rescheduling, cancellation, deletion/repair and revocation with the deployed
owner session and exact registered callback.
