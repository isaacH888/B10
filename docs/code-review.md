# Shared code-review checklists

Owner: Isaac Hernandez. Check only applicable items and record evidence or the blocker.
An unchecked feature item is not completed by the existence of this checklist.

Updated October 5, 2026. Apply Week 4 form/quote/order/DB/email checks now;
Calendar/status/payment/export are Week 5, reminders/deposit-contract Week 6.
Private API protection applies whenever a private route is exposed. Follow the
individual [ownership map](integration-dependencies.md), [source decisions](reference-alignment.md)
and [database draft review](database-integration-review.md).

## Frontend - Aneena Paul and Dillion Nguyen

- [ ] Layout works on representative mobile, tablet, and desktop viewports.
- [ ] Requests, enums, cents, timestamps, and responses match the agreed contract.
- [ ] Required fields, minimum quantity feedback, and time/location entry are clear.
- [ ] Loading, validation, network failure, manual-review, and retry states are usable.
- [ ] Labels, keyboard navigation, focus handling, contrast, and error association are checked.
- [ ] API base URL comes from public environment configuration, without hardcoded backend URLs.
- [ ] Displayed prices come from the backend; client totals are never authoritative.
- [ ] Pending quotes are not displayed as zero-cost or final offers.
- [ ] Beyond-30-mile requests use the approved inquiry action and cannot silently become normal delivery orders.
- [ ] Submission retries reuse the same idempotency key and payload.
- [ ] Admin data is not exposed by hidden UI controls or persisted in browser storage.
- [ ] Session and CSRF handling follow the agreed auth design; credentials are absent from code.

## Backend - Anh Hyunh and Shourya Sai Macha

- [ ] Routes, response envelopes, validation, and documented status codes match the contract.
- [ ] Server validation covers quantities, dates/timezones, lengths, enum values, and unknown fields.
- [ ] Authentication and authorization protect every administrative route and export.
- [ ] Session expiry, logout, CSRF protection, and login rate limiting are covered.
- [ ] Secrets and provider access use validated environment configuration.
- [ ] No card data is accepted, stored, logged, or transmitted by this application.
- [ ] Quote revision, expiry, repricing, historical amounts, and stale updates are handled.
- [ ] Idempotency keys and payment references prevent duplicate orders and actions.
- [ ] A committed order survives mail/calendar outages and has durable retry state.
- [ ] CSV exports neutralize spreadsheet formula input and enforce authorization.
- [ ] Relevant tests cover failure paths, replay behavior, and authorization boundaries.
- [ ] Logs and client errors omit internal traces, tokens, passwords, and customer payloads.

## Database - Bryson Hawthorne

- [ ] Primary and foreign keys, relationships, and delete behavior match agreed domain needs.
- [ ] Constraints support quantity, money, state consistency, and required fields.
- [ ] T08 mappings preserve names/phones/addresses, exact money, timezone/end time and item totals without data loss.
- [ ] Migrations reproduce the schema on a fresh disposable database.
- [ ] Indexes support expected list, event-window, and deduplication queries.
- [ ] Models and migration ownership are coordinated with backend developers.
- [ ] Historical quote/pricing data remains intact after pricing rule changes.
- [ ] Duplicate payment references and action identities have appropriate integrity protection.
- [ ] Tests and seed data contain no real customers or production credentials.
- [ ] Backups, encrypted storage, retention, restore validation, and migration recovery are documented.
- [ ] Application DB privileges exclude schema administration where practical.

## Integration - Isaac with affected owners

- [ ] Order submission works end to end under approved rules.
- [ ] Frontend amounts match the backend response exactly, including cents and deposit.
- [ ] Orders persist and are retrievable by an authorized administrator.
- [ ] Failed email/calendar actions do not delete accepted orders.
- [ ] Repeated deposit confirmation does not send duplicate contract emails.
- [ ] Private credentials and customer data are absent from repository changes.
- [ ] Another teammate can start components using the documented setup commands.
- [ ] CORS, cookies, CSRF, readiness, migrations, and deployment environment settings are verified.
- [ ] Review evidence distinguishes passed, failed, blocked, and unexecuted checks.
