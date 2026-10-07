# Staging and deployment plan

Owner: Isaac Hernandez. Updated October 5, 2026. First staging build target:
October 7-8; team demo October 9. No external hosting/deployment has been performed.
Approved React/Vite + Flask + MySQL shells are infrastructure preparation; business
components and a reviewed release are still missing.

## Hosting and release scope

| Area | Required handoff | Owner |
| --- | --- | --- |
| React/Vite | HTTPS static hosting, actual API build URL, optional SPA fallback | Aneena/Dillion; Isaac release |
| Flask | HTTPS application hosting, production WSGI server/process, limits/restarts, secrets | Isaac with Anh/Shourya |
| MySQL | Private/TLS connection, app/migration users, persistent storage, reviewed engine/image, backups | Bryson with Isaac |
| Durable work | Week 4 email work persistence/retries and a supported worker; scheduler needed for later reminders | Shourya/Bryson |
| Providers | Approved sender and dedicated email test destinations; Square first, no real funds in tests | Client/Shourya/Anh |

Host/cost and production domain remain D16/T04. Research AWS resources are options,
not selected infrastructure. Local Compose is not a staging architecture or deployment.
Flask's development server is for local work; select a production server with the
host. See [Flask deployment guidance](https://flask.palletsprojects.com/en/stable/deploying/).

Week 4 staging acceptance covers form, approved quote/order persistence, safe private
list/detail access, order-created emails, validation and retry behavior. Full auth/dashboard
integration is Week 5, but private data cannot be exposed while auth is unfinished.
Calendar is Week 5; reminders/deposit-contract automation Week 6. Disable unavailable
work deliberately and document the demonstrated subset in the release evidence.

## Release procedure

1. Record reviewed commit SHA, accepted contract, lock versions, migration revision,
   feature scope and build/test evidence. Remote foundation CI must actually run.
2. Obtain approval for the concrete external staging release and any costs; choose resources.
3. Inject separate staging secrets and exact HTTPS origins; validate TLS DB access.
4. Bryson supplies the single migration command, disposable fresh-migration evidence
   and first-build recovery plan; record schema version. For a populated target,
   prove backup/restore before changing retained data. Full recovery rehearsal follows
   his later deliverables and is required before production.
5. Deploy a production Flask process and the required email worker with compatible schema.
   Verify `/api/v1/live`, `/api/v1/health` and domain migration/version separately.
6. Build/deploy React with the actual staging API URL or approved same-origin proxy.
   Verify HTTPS, assets, browser CORS and private API controls.
7. Execute the Week 4 scenario subset and provider failures with synthetic orders and
   approved test recipients. Capture sanitized results and retry/reconciliation evidence.
8. Review blockers, observe failures and decide whether the build is acceptable for the
   team demo. Production release requires a separate explicit release decision.

Local commands are in [setup](development-setup.md). Production entry point/process,
migration runner and host commands remain owner-supplied; do not invent them.
CI checks do not deploy; merging to main does not authorize production release.

## Rollback and recovery

For a first staging build there may be no prior release: record the safe stop/disable,
schema preservation and redeploy procedure. For later releases, record the last
known compatible frontend/backend artifacts. Do not claim a proven rollback without
executing its rehearsal. Pause outbound work when incompatible versions could resend
completed actions; preserve accepted orders and action identities.

Favor compatible additive schema changes. Bryson documents recovery for each migration.
MySQL DDL can implicitly commit; a transaction is not universal schema rollback.
See [MySQL implicit commits](https://dev.mysql.com/doc/refman/8.4/en/implicit-commit.html).
Choose a reviewed forward repair, proven down migration or approved backup restore.
Confirm data loss before destructive restoration and reconcile post-backup orders/provider
work before resuming service.

## Operational ownership

Isaac coordinates releases; component owners validate their services; Bryson owns
migrations, backup/restore and DB privileges. Client owns production provider accounts.
Hosted secrets, backup cadence/retention/recovery targets, credential custodians,
incident contacts and alert destinations remain explicit pre-release handoffs.

Log request IDs and safe outcomes; omit customer bodies, credentials and receipt
secrets. Monitor HTTP/DB failures and email backlog for Week 4. Add Calendar and
scheduler monitoring when those later workflows are enabled. See the
[readiness gate](staging-readiness.md) and [demo evidence](week-4-demo.md).
