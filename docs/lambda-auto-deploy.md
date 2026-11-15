# Existing Lambda website: deployment and recovery

This setup targets only the DEV website
<https://n2fffdn5h9.execute-api.us-east-1.amazonaws.com/> and Lambda `b10-lab-api`
in `us-east-1`. It leaves the existing React/Vite, Flask/MySQL, Cognito and AWS
configuration in place. It does not provision infrastructure or release to PROD.

## What runs and which commit it deploys

[Shared foundation checks](../.github/workflows/foundation-checks.yml) retains its
push, PR and manual triggers and its four existing check jobs. The package job
depends on all four. The deployment job depends on all checks plus the package
and runs only for `isaacH888/B10`, `refs/heads/dev`, on `push` or `workflow_dispatch`.
A merge into `dev` produces that push. No `workflow_run` default-branch SHA is used.
Checkout, artifact name, frontend release manifest and deployment all use the same
`github.sha`. PRs cannot run the AWS deployment job.

The job builds the frontend with `VITE_API_BASE_URL=/api/v1`, installs all pinned
Python dependencies as CPython 3.12 Linux x86_64 wheels, and creates this ZIP layout:

```text
site_handler.py
app/                   # backend/app Python and JSON, including pricing/postal data
migrations/            # checksum inputs; SQL is never executed by deployment
frontend/              # actual frontend/dist output, served at the site root
  index.html
  release.json         # full commit SHA and SHA256 of every other frontend file
  assets/...
<installed Python dependencies and native wheels>
```

Each deployment downloads the actual current Lambda ZIP and rejects any
handler-byte or layout mismatch before changing code. A changed handler requires
separate reconciliation with the live deployment.

The package is smoke-tested in the official Lambda Python 3.12 image on x86_64,
including native module imports, frontend hashes, SPA routing, missing asset 404s
and a payload `1.0` API request. Source allowlists omit `.env`, tests, caches and
virtual environments. The uploaded Actions artifact is built from repository
source and dependencies; the downloaded live ZIP and configuration are not uploaded.

## Learner Lab credentials and permissions

The current `deploy-dev` job reads repository Actions secrets and passes them only
to its deployment step. All three must come from the same active Learner Lab
session:

| Repository secret | Value from the active session |
| --- | --- |
| `AWS_ACCESS_KEY_ID` | Temporary access key ID |
| `AWS_SECRET_ACCESS_KEY` | Matching secret access key |
| `AWS_SESSION_TOKEN` | Matching session token |

1. Start the lab and obtain a current credential set through its approved access
   process. Do not print the values in logs or place them in source files.
2. In GitHub, open **B10 -> Settings -> Secrets and variables -> Actions ->
   Secrets**. Create each name with **New repository secret**, or update its
   existing value. Save the complete set from one session before starting a run.
3. Have the instructor/account administrator confirm the session identity can read
   the existing function/API configuration and update only this Lambda's code.
   The function stays Python 3.12, `x86_64`, ZIP, `site_handler.handler`, in
   `us-east-1`. Its HTTP API must retain a `$default` stage and route targeting
   this unqualified Lambda with `AWS_PROXY` and payload `1.0`. Alias/version
   targets, alternate route integrations, layers or a changed handler stop
   deployment until reviewed.
4. When credentials expire, restart or renew the lab session, refresh **all three**
   secrets, and rerun failed jobs on the latest `dev` run with passing checks and
   package validation. The workflow cannot refresh a Learner Lab session itself.

Store only each credential's value in its Actions secret, without shell commands,
quotes or an entire credentials-file block. The deployment script trims surrounding
whitespace and rejects embedded whitespace or assignment text before contacting AWS.
It verifies the session with STS before reading Lambda or changing code. An expired
session is reported separately from HTTP transport errors. Stage messages identify
which check failed without printing credentials, signed download URLs or SDK responses.
Updating a local `learner-lab` profile does not update GitHub Actions secrets.

Workflow fixes take effect in a new commit's run. Rerunning an older run continues
to use that run's original deployment script.

GitHub documents [repository secrets](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets);
Boto3 documents the [credential environment variables](https://docs.aws.amazon.com/boto3/latest/guide/credentials.html#environment-variables).
`B10_DEPLOY_ROLE_ARN` is not read by this workflow. It has no OIDC authentication
step or `id-token: write` permission; configuring a role ARN alone will not supply
its required session secrets. Any future move to federation requires a separate
workflow/account change and review.

Required permission policy for the existing session identity, subject to the
account's boundaries and lab guardrails:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "lambda:GetFunction",
        "lambda:GetFunctionConfiguration",
        "lambda:UpdateFunctionCode"
      ],
      "Resource": "arn:aws:lambda:us-east-1:ACCOUNT_ID:function:b10-lab-api"
    },
    {
      "Effect": "Allow",
      "Action": "apigateway:GET",
      "Resource": [
        "arn:aws:apigateway:us-east-1::/apis/n2fffdn5h9/integrations",
        "arn:aws:apigateway:us-east-1::/apis/n2fffdn5h9/routes",
        "arn:aws:apigateway:us-east-1::/apis/n2fffdn5h9/stages/$default"
      ]
    }
  ]
}
```

`UpdateFunctionConfiguration`, `iam:PassRole`, CloudFormation, database, Secrets
Manager and API write permissions are not needed by this deployment. The job's
GitHub token has `contents: read` and `actions: read`; the other jobs retain
read-only repository access and receive no AWS credentials. Public verification
uses HTTPS. See [Lambda permissions](https://docs.aws.amazon.com/service-authorization/latest/reference/list_lambda.html)
and [API Gateway payload formats](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-develop-integrations-lambda.html).

### Access denied after successful AWS session verification

If the log says `AWS session credentials verified` and then access is denied at
`inspect existing Lambda configuration`, the rejected operation is
`lambda:GetFunction` on `b10-lab-api` in `us-east-1`. The script has not uploaded
code or reached the migration review. Check that the Actions credentials belong
to the account containing this function and that their deployment identity has
the policy above. This is the identity represented by the Actions secrets, not
the Lambda function's runtime execution role. A lab administrator must resolve
any restricting lab policy or permission boundary.

Using the same deployment identity, verify read access without printing the
function's environment or signed code-download URL:

```sh
aws lambda get-function --function-name b10-lab-api --region us-east-1 \
  --query 'Configuration.FunctionName' --output text
```

After access is restored, finish the database review for the current release and
rerun the latest DEV run's failed jobs. Replacing expired credentials alone does
not grant a session missing permissions to this function.

## Database and dependency review

Before first release, the database owner must reconcile actual `schema_migrations`
history, table/index definitions and checksums with this commit. `/health` only
checks database/auth readiness; it does not prove every business table/index is
ready. The local prior package has `0009_automation_scheduled_reminders.sql` while
this repository has `0009_orders_event_start_index.sql`, `0010_admin_inventory.sql`
and `0011_quotes_persistence.sql`. The migration runner rejects conflicting applied
versions/names/checksums. Do not run it blindly, edit applied migration checksums,
delete history rows, or assume a code rollback can undo database changes.

Deployment compares every SQL file in the actual live and candidate ZIPs. Added,
removed or changed files are listed and block the update unless Actions variable
`B10_MIGRATIONS_REVIEWED_SHA` exactly matches the candidate's full SHA. Set it only
after the owner applies/reconciles separately with a backup and confirms both the
candidate and previous code can use the resulting schema. It is review evidence,
not automated schema validation. Even identical packaged migrations do not prove
they were applied. The pipeline never executes SQL or receives migration credentials.

Every candidate gets a newly installed dependency package from
`backend/requirements.txt`; changes to it require a new build and native runtime
smoke test. The deploy summary lists added/removed/version-changed distributions
against the live ZIP. Current pins match the local prior package's versions;
the authenticated live comparison will decide the actual result. A package over
the direct-upload/expanded Lambda limit, a source shadowing dependency, a Lambda
layer or a mismatched handler stops deployment for review rather than changing AWS
configuration. Existing public `certs/*.pem` CA files are copied from the live ZIP
after rejecting private-key/unexpected material. Secrets and unknown files are not
copied into the new package.

## Verification and rollback

The deployment job serializes updates without cancelling a running deployment.
It rejects an older rerun if a newer DEV run passed the four original checks and
package validation. It downloads the current live ZIP using `GetFunction`'s signed
URL, checks its `CodeSha256`, validates runtime/handler/architecture/integration,
and checks that the previous site and MySQL readiness are healthy before updating.
Signed URLs and environment settings are never printed.

The only AWS mutation is `UpdateFunctionCode` with a `RevisionId` condition and
`Publish=False`. The handler, role, environment, memory, timeout, networking and
other configuration are compared again afterward. For the candidate to pass,
Lambda's code hash must match, `/` and every packaged frontend path must return the
expected bytes, JavaScript/CSS/HTML must have suitable MIME types, `/release.json`
must contain the exact commit/hash manifest, and both API probes must return healthy
JSON. Requests bypass caches and retry propagation. A stale bundle, SPA fallback
for a missing asset, degraded database or wrong commit fails verification.
Each public verification has a three-minute budget plus at most one in-flight
request timeout, leaving time for recovery within the deployment job.

On failure after an accepted code change, the job restores the downloaded previous
ZIP using the current `RevisionId`, verifies its hash/configuration, and repeats
frontend/API verification. The workflow remains failed even after successful
rollback. If AWS is unreachable or the runner is forcibly stopped, automatic
recovery cannot be guaranteed; the summary reports rollback failure/unknown state
when it can. Concurrent external code/config changes cause recovery to stop rather
than overwrite someone else's update. Coordinate manual AWS changes with this job.
Rollback only restores code; it cannot restore SQL or external provider state.

If automatic rollback cannot run, inspect the current function and public probes
when AWS returns. Download the last known good source-built Actions artifact,
review schema compatibility, and rerun the latest passing DEV release. Do not blindly
restore a package whose database assumptions no longer match. The live backup is
kept in runner memory only, not a persistent backup or uploaded artifact. Maintain
your own approved release/backup retention if recovery beyond 30 days is required.

## Lab unavailable: CI, reruns and manual fallback

The four original checks and package build use no AWS credentials. The separate
deployment job fails visibly when a required session secret is missing, the
credentials expire, the lab is unavailable, permissions are denied or a
public/database probe fails. It does not mark an AWS failure as a passed
deployment. Renew the lab session and update all three secrets before retrying an
expired-credential failure.

When the lab is available, choose the latest `dev` run whose original four checks
and package job passed, even if the run is overall failed because of deployment:

```sh
gh run list --repo isaacH888/B10 --workflow foundation-checks.yml --branch dev
gh run view RUN_ID --repo isaacH888/B10
gh run rerun RUN_ID --failed --repo isaacH888/B10
```

Or use **Actions → Shared foundation checks → run → Re-run jobs → Re-run failed
jobs**. This uses the original commit/ref and its same-run package; successful
checks remain successful. Artifacts are retained for 30 days and GitHub reruns are
available up to 30 days. If the artifact is gone, rerun all jobs within that window.
To build/test/deploy the **current** `dev` tip, use:

```sh
gh workflow run foundation-checks.yml --repo isaacH888/B10 --ref dev
```

Manual dispatch reruns all checks; it does not deploy an arbitrary untested SHA.
An expired old release requires a reviewed change restoring its source on `dev`.
See [GitHub rerun semantics](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/re-run-workflows-and-jobs).

An authorized operator can also download a passing run's artifact and run the
same script with a current private Learner Lab profile, outside GitHub:

```sh
gh run download RUN_ID --repo isaacH888/B10 --name b10-lambda-FULL_SHA --dir /tmp/b10-release
# Use the script from that reviewed FULL_SHA; keep temporary credentials private.
AWS_PROFILE=learner-lab aws sts get-caller-identity
AWS_PROFILE=learner-lab python scripts/deploy_site_lambda.py \
  --package /tmp/b10-release/b10-site.zip --commit FULL_SHA
```

Install the pinned tooling first, check out the reviewed script version in an
isolated checkout, and pass `B10_MIGRATIONS_REVIEWED_SHA=FULL_SHA` only after the
same database review if required. This manual path needs the same scoped AWS
permissions. Do not put temporary access keys/session tokens into commits or
Actions variables.

## Verify behavior when the lab session ends

Ending a session, resetting/deleting a lab, account expiration and budget exhaustion
are different events. Current account rules and the database host determine
availability. Ask the instructor whether Lambda/API Gateway remain callable,
whether STS allows deployment outside sessions, and whether MySQL's EC2/RDS host
stops or becomes inaccessible. Resource persistence alone is not an uptime promise.
Public HTTP responses cannot establish whether the user's lab is currently on.

Before ending the session, download a verified run's package and run:

```sh
python scripts/verify_site_lambda.py --package /tmp/b10-release/b10-site.zip --commit FULL_SHA
```

Record the timestamp/result. End the lab session yourself, wait until it is actually
ended, then run that identical command from your own computer outside AWS. It checks
the exact frontend bytes and both API probes. Repeat after 5 and 15 minutes to catch
delayed shutdown. Repeat when the lab restarts. A working homepage with HTTP 503 from
`/api/v1/health` means the frontend is available but database/auth readiness is not.
If nothing is reachable, ask the administrator to inspect the lab/account and
Lambda/API Gateway state; do not infer a permanent deletion from a failed request.

Setup observations, November 14, 2026: live `/`, its referenced JavaScript,
`/api/v1/live` and `/api/v1/health` returned HTTP 200; health reported database `ok`
and authentication `ready`. `/release.json` returned 404 before this implementation.
Those initial setup checks did not exercise AWS credentials, actual Lambda/API
configuration or post-session uptime. Later deployment evidence is recorded below;
actual applied schema details and lab-off uptime still need their own checks.

## Review and publication

Local validation on November 14, 2026:

- Python 3.12 backend suite: 1,304 passed, 150 skipped. Disposable-MySQL integration
  tests were not run locally; the existing CI MySQL job remains required.
- Final package/deployment tests after recovery and rerun fixes: 25 passed.
- Foundation contract checks, Ruff formatting/lint, frontend formatting/build,
  `actionlint` workflow validation and `git diff --check` passed. ShellCheck was
  unavailable; actionlint ran with its ShellCheck integration disabled.
- The actual source-built ZIP was 33,145,772 bytes, below the direct-upload limit.
  Its extracted contents passed native imports, all frontend manifest hashes,
  SPA/404 checks and the API Gateway 1.0 API probe in the pinned official Lambda
  Python 3.12 x86_64 image with networking disabled. Local Docker Desktop does not
  share `/tmp`, so the local test streamed the same package into the container;
  the GitHub runner uses ordinary read-only bind mounts.

The initial local packaging tests used a synthetic release marker. The published
workflow now uses the actual checked commit SHA. The CI/CD implementation was
merged into `dev` through PR #10 and the credential setup was subsequently changed
to the three Learner Lab Actions secrets documented above.

Review on November 14, 2026: all 25 package/deployment tests passed again, together
with Ruff checks. The [run for `63383a9`](https://github.com/isaacH888/B10/actions/runs/43658474172)
completed every check, the package/container smoke test, and the actual deployment
and public verification successfully. This confirms one release through the
pipeline; it does not establish uptime after the lab session ends or separately
prove every applied business migration. The README and this guide describe the
current published workflow rather than the initial uncommitted setup branch.
