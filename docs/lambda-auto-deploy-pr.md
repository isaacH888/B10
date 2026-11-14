Pushes and merges to `dev` now run the existing Shared foundation checks, build a
Lambda deployment ZIP from the checked commit, and deploy that exact commit to
the existing DEV website only after all checks pass. Pull requests build/test the
package without AWS. The deployment validates API Gateway payload 1.0, preserves
the existing handler and AWS configuration, verifies frontend file hashes and API
readiness, and attempts verified code rollback on failure.

The README and operations guide include administrator OIDC trust/permissions,
`B10_DEPLOY_ROLE_ARN`, Learner Lab outage reruns and the lab-off availability test.
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

Live deployment, AWS configuration/OIDC, actual schema compatibility and lab-off
uptime require the configured account and have not been verified by this change.
