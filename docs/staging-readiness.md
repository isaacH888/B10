# Week 4 staging readiness checklist

Owner: Isaac Hernandez. Updated October 5, 2026. Decision: not ready to deploy.
Target October 7-8; no staging URL or reviewed release SHA exists.

## Foundation prepared locally

- [x] Isaac approved React/Vite + Flask + MySQL scaffold.
- [x] Shared manifests, lockfiles, environment templates and local commands exist.
- [x] Frontend build and backend foundation tests pass locally; see [validation](foundation-validation.md).
- [x] CI workflow prepared for contract, backend/MySQL probe and frontend build; remote run pending.

These checks do not prove a live database, migration, business integration or staging release.

## Week 4 release gates

- [ ] Concrete hosting/release/cost approval is recorded.
- [ ] Reviewed SHA, accepted API/schema mapping, runtime/image versions and release scope exist.
- [ ] Remote PR checks and independent review pass; actual artifacts are identified.
- [ ] Dillion form, Anh quote/create/list/detail and Bryson migration/query handoffs exist.
- [ ] Business rules required for the demonstrated flow are approved; unpriced requests remain visibly blocked.
- [ ] Bryson demonstrates fresh migration/transaction integrity and first-build recovery; protect and prove restore for any populated target before changing it.
- [ ] HTTPS, private DB/TLS, separate staging secrets and actual frontend API URL are verified.
- [ ] `/live` succeeds; `/health` probes DB; domain schema readiness is checked separately.
- [ ] Private order access is authenticated/authorized; browser origin controls are verified.
- [ ] Order submission/snapshot/list/detail, minimum quantity, inquiry routing and retry/conflict tests pass.
- [ ] Shourya's customer/business email adapter uses approved test recipients and durable deduplication.
- [ ] Email timeout/failure preserves orders and has visible retry/reconciliation state.
- [ ] No real payment transfer, private credentials or real customer data enter tests/artifacts/logs.
- [ ] First-build safe stop/redeploy or later compatible rollback is rehearsed and recorded.
- [ ] Named monitoring/incident owners and sanitized release/demo evidence are available.

## Later release gates

Week 5 adds full auth/dashboard integration, status/payment/export and Calendar,
including test calendar, provider IDs and reschedule/cancel/reconciliation evidence.
Week 6 adds deposit-contract replay and durable timezone-aware reminders with
approved final-payment/count eligibility. These later features are not prerequisites
for a deliberately scoped Week 4 build; private-route protection always is.
Full backup/restore and upgrade rehearsals follow Bryson's later plan and must be
verified before production or risky changes to retained data.

## Evidence

Record SHA, contract/schema versions, exact build/test results, approved origin,
provider test destinations, demonstrated feature subset, blockers, approver and
recovery target. Use [integration evidence](integration-tests.md) and the
[demo agenda](week-4-demo.md). Unchecked gates are pending, not completed by this document.
