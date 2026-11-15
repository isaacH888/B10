# Live Calendar setup: handoff for Shourya

The submitted-request feature includes automated backend and browser coverage.
Live Google consent and inbox delivery still require the account setup and
deployment below. Publishing the code to `dev` alone does not activate delivery.

Shourya handles AWS deployment and needs access to the Google Cloud project that
owns the OAuth client, or help from that project's administrator. Isaac can grant
access to his own Google Calendar through the website without having AWS access.

## 1. Prepare the database and release

Use the existing deployment account/lab access. A local `aws login` session on
Isaac's computer is not a prerequisite for hosting this feature.

If deployment verifies the AWS session but is denied access when reading Lambda,
follow the [deployment permissions recovery steps](lambda-auto-deploy.md#access-denied-after-successful-aws-session-verification)
before rerunning it.

Back up the target database and compare its migration history with the release.
Using the separately configured migration account, run the existing runner from
the reviewed checkout:

```sh
cd backend
.venv/bin/python -m app.migrations
cd ..
```

This must include `0012_request_notifications.sql`. Grant the runtime database
user `SELECT`, `INSERT` and `UPDATE` on `automation_requests`, in addition to the
existing automation grants described in [the deployment runbook](calendar-automation.md#aws-deployment).
Resolve any migration-history mismatch before applying changes.

The DEV website pipeline does not run migrations. After reviewing/applying the
schema and confirming compatibility with the previous release, set repository
Actions variable `B10_MIGRATIONS_REVIEWED_SHA` to the full Calendar release commit
SHA, as required by [the existing deployment process](lambda-auto-deploy.md#database-and-dependency-review).
Use the approved active lab credentials for that pipeline when it needs a release.

## 2. Configure Google Cloud

In the project that owns the configured Google OAuth client:

1. Enable **Google Calendar API**.
2. Use a **Web application** OAuth client. Register this authorized redirect URI,
   replacing `SITE_ORIGIN` with the exact HTTPS origin used in the browser:

   ```text
   SITE_ORIGIN/api/v1/admin/automation/google/callback
   ```

   For the DEV address currently documented in this repository, that is:

   ```text
   https://n2fffdn5h9.execute-api.us-east-1.amazonaws.com/api/v1/admin/automation/google/callback
   ```

   If hosting moves to another domain, use that domain and update the app setting
   to match. Preserve other existing sign-in callbacks. Google requires an
   [exact redirect URI match](https://developers.google.com/identity/protocols/oauth2/web-server#httprest_1).
3. While the OAuth audience is **Testing**, add `isaachndz1@gmail.com` as a test
   user. For ongoing service, configure the production consent audience and
   complete any verification Google requires for the selected scopes. External
   Testing grants with Calendar scopes have refresh tokens that expire after
   [seven days](https://developers.google.com/identity/protocols/oauth2#expiration).
4. Verify the Secrets Manager secret referenced by `GOOGLE_CLIENT_SECRET_ARN`
   contains the corresponding Web client credentials in this shape:

   ```json
   {"client_id":"<web-client-id>","client_secret":"<web-client-secret>"}
   ```

Leave `ExistingGoogleCalendarId` empty to create/reuse the dedicated
**Popssibilities Catering** calendar under the Google account that grants consent.
See [Google setup and recovery](google-calendar-reference.md) for an existing
calendar instead.

## 3. Configure real email delivery

Use Amazon SES in `us-east-1`. Verify the sender/domain and use its address for
`FromEmail`; set `OwnerEmail` to `isaachndz1@gmail.com` for the initial test.

If SES is in the sandbox, also verify `isaachndz1@gmail.com` and any other test
recipients. Request production access before mailing arbitrary customers;
[sandbox accounts can send only to verified recipients or the mailbox simulator](https://docs.aws.amazon.com/ses/latest/dg/request-production-access.html).
Complete sender authentication and bounce/complaint handling as described in the
deployment runbook. The recipient address does not need to be the sender address.

## 4. Deploy and connect the automation infrastructure

Deploy the updated website/API and automation functions from the same release.
The existing DEV workflow updates only the website Lambda's code; the background
infrastructure and its functions require a separate deployment.

Use [infra/automation.yaml](../infra/automation.yaml), with AWS SAM and Docker
available, from the repository root:

```sh
sam validate --lint --template-file infra/automation.yaml
sam build --template-file infra/automation.yaml --use-container
sam deploy --guided --template-file .aws-sam/build/template.yaml --region us-east-1
```

Update the existing automation stack if one exists. Supply the actual account
values for `RuntimeSecretArn`, `GoogleClientSecretArn`, `SubnetIds`,
`SecurityGroupIds`, `FrontendOrigin`, `OwnerEmail`, `FromEmail` and `SesIdentityArn`.
Use `Environment=staging` for DEV. Review the generated change set and IAM grants.
If the lab prevents the required resource/role creation, its administrator must
provide the necessary deployment permissions or resources.

The runtime secret must reuse the site's existing MySQL/Cognito configuration,
session secret and token-encryption key, plus the required deployed MySQL CA path
and business configuration. Follow the [complete runtime-secret requirements](calendar-automation.md#aws-deployment).
API and workers must use the same database, Google client and token-secret prefix.

The template enables `AUTOMATION_ENABLED=true` and `AUTOMATION_MODE=aws`, and
configures the queues, Scheduler and Google callback. Confirm:

- The dispatcher runs every minute and the SQS worker trigger is enabled.
- Lambda can reach MySQL, Google and AWS services from its configured network.
- API/worker execution roles have the template's scoped Secrets Manager access;
  the worker can send mail through the selected SES identity.
- The existing site's `/api/v1/*` routes reach the stack's `ApiOrigin`, preserving
  the authenticated session, cookies, request bodies and OAuth query parameters.
  Keep the frontend and browser API on the same origin and bypass API caching.

The deployed application uses its Lambda execution roles for AWS access;
[Lambda assumes those roles automatically](https://docs.aws.amazon.com/lambda/latest/dg/lambda-intro-execution-role.html).
It does not depend on Isaac keeping a terminal login active. The hosting lab and
its required resources still need to be available.

## 5. Isaac connects Calendar and enables routing

After deployment, Isaac signs into the live website as an **owner**:

1. Open `/admin/automation` and select **Connect Google Calendar**.
2. On Google's screen, choose `isaachndz1@gmail.com` and approve Calendar access.
3. Under **Incoming request notifications**, enter `isaachndz1@gmail.com`.
4. Select **Use this calendar for incoming requests**.

Shourya does not need Isaac's Google password. Choosing an inbox and granting
Calendar access are separate actions: changing the inbox does not switch the
connected Google account.

## 6. Verify a real submission

Submit a new synthetic catering request with a future date, time and timezone
after enabling routing. Existing requests are excluded from initial activation.
Confirm an actual inbox message and exactly one **Pending request** entry in the
connected calendar, normally after the next one-minute dispatcher run. Check the
owner panel's separate email and Calendar delivery states if either is missing.

Then test the request-to-booking transition in staging: owner intake/approval and
a separately verified qualifying deposit should update the same event to
confirmed. Use synthetic payment records only in staging; live payment records
must reflect independently verified real payments. Quote previews alone should
create neither mail nor an event.

## Changing or stopping notification emails

In `/admin/automation`, change the **Incoming request notifications** email and
select **Use this calendar for incoming requests** again. Select **Stop new request
notifications** to disable future capture. Re-enabling starts from new submissions.
Already captured requests keep their original recipient and calendar.

The current implementation supports **one notification inbox at a time**. Multiple
recipients would need an additional app change or a shared mailbox/group address.
