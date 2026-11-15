Pushes and merges to `dev` now run the existing Shared foundation checks, build a
Lambda deployment ZIP from the checked commit, and deploy that exact commit to
the existing DEV website only after all checks pass. Pull requests build/test the
package without AWS. The deployment validates API Gateway payload 1.0, preserves
the existing handler and AWS configuration, verifies frontend file hashes and API
readiness, and attempts verified code rollback on failure.

The current workflow receives `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` and
`AWS_SESSION_TOKEN` from repository Actions secrets for an active Learner Lab
session. The README and operations guide describe refreshing all three secrets,
required session permissions, outage reruns and the lab-off availability test.
The original OIDC role-variable setup is no longer used.
Changed migration inputs require explicit database review for the exact SHA;
the local prior package's migration 0009 conflicts with this checkout. No migrations
are executed by deployment. Dependencies are rebuilt and compared with the live
package. The named workflow ZIP attachment was unavailable and still needs comparison.

Validation: Python 3.12 backend suite 1,304 passed / 150 skipped; final focused
package/deployment suite 25 passed. Foundation, Ruff, frontend formatting/build
and actionlint checks passed. The 33 MB ZIP passed the official Lambda Python 3.12
x86_64 container smoke test, including native imports, frontend hashes and API
Gateway 1.0 handling. Local disposable-MySQL integration and browser tests were not
rerun; existing CI jobs remain required.

Publication follow-up: this implementation was merged through PR #10. The
[run for `63383a9`](https://github.com/isaacH888/B10/actions/runs/43658474172)
passed all checks, packaging, deployment and public verification. The 25 focused
tests passed again during the November 14 review. Applied schema compatibility
and lab-off uptime still require their separate operational checks.
