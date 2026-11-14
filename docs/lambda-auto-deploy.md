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

The handler source was copied byte for byte from the existing local staging
directory `/tmp/tmp.Yz3ipWh9Hl/site_handler.py`. Its provenance is local evidence,
not a fresh authenticated download. Each deployment downloads the actual current
Lambda ZIP and rejects any handler-byte/layout mismatch before changing code.
The missing `b10-lambda-auto-deploy.zip` attachment was not inspected/extracted;
compare it with this implementation when it is available, including hidden files.

The package is smoke-tested in the official Lambda Python 3.12 image on x86_64,
including native module imports, frontend hashes, SPA routing, missing asset 404s
and a payload `1.0` API request. Source allowlists omit `.env`, tests, caches and
virtual environments. The uploaded Actions artifact is built from repository
source and dependencies; the downloaded live ZIP and configuration are not uploaded.

## Instructor/AWS administrator setup

First confirm that this Learner Lab account permits a GitHub IAM OIDC provider,
a dedicated federated role and STS role assumption, including outside an active
session if unattended deployment is expected. Student IAM restrictions may prevent
this. Do not reuse or change `LabRole` or the Lambda execution role for GitHub.
If guardrails prohibit federation, CI still works but automatic OIDC deployment
cannot work until an administrator provides an allowed account/role arrangement.
No expiring Learner Lab access keys are embedded in this workflow.

1. In **IAM → Identity providers → Add provider**, choose **OpenID Connect**,
   provider URL `https://token.actions.githubusercontent.com`, audience
   `sts.amazonaws.com`. Reuse an existing provider with these settings.
2. Create a separate role, for example `B10GitHubDevDeploy`, with a maximum session
   of at least one hour. Use the trust policy below with the actual account ID.
3. Attach the permission policy below. Keep its resources scoped to this function
   and API. AWS permission boundaries/SCPs/lab guardrails must also allow these calls.
4. Send the role ARN to the repository administrator and confirm the function's
   deployed configuration is Python 3.12, `x86_64`, ZIP, `site_handler.handler`.
   Confirm the HTTP API has a `$default` stage and route targeting this unqualified
   Lambda with `AWS_PROXY` and payload `1.0`. This workflow refuses an alias/version
   target, another route integration, Lambda layers or a changed handler until
   those differences are reviewed; it does not change them automatically.

Trust policy for the standard GitHub branch subject:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {
      "Federated": "arn:aws:iam::ACCOUNT_ID:oidc-provider/token.actions.githubusercontent.com"
    },
    "Action": "sts:AssumeRoleWithWebIdentity",
    "Condition": {
      "StringEquals": {
        "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
        "token.actions.githubusercontent.com:sub": "repo:isaacH888/B10:ref:refs/heads/dev"
      }
    }
  }]
}
```

Match the repository's **actual** OIDC subject settings. GitHub documents immutable
subjects for newer/opted-in repositories; if enabled here, the exact subject is
`repo:isaacH888@179164131/B10@1361851799:ref:refs/heads/dev` instead. Confirm the IDs
and configured subject, rather than broadening trust with wildcards. This job does
not use a GitHub environment; adding one changes the subject to an environment
subject and requires updating trust and protecting that environment's allowed refs.
See [GitHub AWS OIDC](https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-aws)
and the [OIDC subject reference](https://docs.github.com/en/actions/reference/security/oidc).

Permission policy:

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
Manager and API write permissions are not needed. Public verification uses HTTPS.
The job's GitHub token has `id-token: write`, `contents: read` and `actions: read`;
other jobs retain read-only repository permission and no OIDC permission.
See [Lambda permissions](https://docs.aws.amazon.com/service-authorization/latest/reference/list_lambda.html)
and [API Gateway payload formats](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-develop-integrations-lambda.html).

In the GitHub repository, open **Settings → Secrets and variables → Actions →
Variables → New repository variable**. Set `B10_DEPLOY_ROLE_ARN` to
`arn:aws:iam::ACCOUNT_ID:role/B10GitHubDevDeploy`. The ARN is configuration, not a
secret; use the **Variables** tab. The workflow reads `vars.B10_DEPLOY_ROLE_ARN`.
See [GitHub configuration variables](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-variables).

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
deployment job fails visibly when the role variable is absent, OIDC is denied, the
lab is unavailable or a public/database probe fails. It does not mark an AWS failure
as a passed deployment. OIDC has a bounded timeout/retry count.

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

If the instructor confirms OIDC is prohibited, unattended deployment remains
unavailable. An authorized operator can download a passing run's artifact and run
the same script with a current private Learner Lab profile, outside GitHub:

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
permissions. Do not put temporary access keys/session tokens into commits or the
role ARN variable.

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
No AWS credentials or lab session control were available, so actual Lambda/API
configuration, OIDC authorization, live schema and post-session uptime remain
unverified. No AWS mutation or deployment was performed during setup.

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

These local packaging tests used the checkout's base SHA as a synthetic release
marker because changes remain uncommitted. GitHub Actions will use the actual
checked commit SHA after review/publication. No browser suite, live deployment or
AWS account/schema verification was performed during this change.

Changes remain uncommitted on local branch `chore/dev-lambda-auto-deploy`.
The [README](../readme.md#automatic-dev-website-deployment) contains exact staging,
commit, push and `gh pr create --base dev` commands. Review the complete diff first.
The prior connection's branch-creation 403 was not retested with a remote mutation;
repository metadata reports push access, which does not prove workflow/branch write
permission. Use your own account with repository Contents and Actions/Workflows write
access as applicable. `gh auth login`, then the README commands, keeps publication
under your control. No PR exists until the changes are committed and pushed.
