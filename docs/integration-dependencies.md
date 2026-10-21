# Integration dependency map and individual assignments

Owner: Isaac Hernandez. Updated October 5, 2026. Assignments follow S01 page 1
and dated weekly cells in [reference-alignment.md](reference-alignment.md).
The shared shells now exist; teammate business implementations are not present.

| Feature | Primary owner | Planned handoff | Dependency / evidence |
| --- | --- | --- | --- |
| Shared application shells and configuration | Isaac | Week 2 carryover | Approved React/Flask/MySQL; real startup/build/health checks |
| Public pages, shared styling and responsive QA | Aneena Paul | Weeks 2-4 | Brand assets, real pages, layout/browser evidence |
| Form, quantity controls and price display | Dillion Nguyen | Weeks 2-4 | Anh's quote API, agreed fields and approved backend prices |
| Confirmation page and submission interaction | Dillion Nguyen | Week 4 | Anh create-order response, idempotency, error states |
| Shared confirmation/loading/error styling | Aneena Paul | Week 4 | Dillion's interaction states |
| Pricing engine and quote API | Anh Hyunh | Weeks 2-3 | D01-D07, recorded origin/inquiry policy, server validation |
| Create/list/detail APIs | Anh Hyunh | Week 4 | Bryson models/queries/transactions, accepted contract, historical prices |
| Create/list/detail data functions | Bryson Hawthorne | Week 4 | ERD/migrations/models, T08 mappings, synthetic transaction checks |
| Admin login and protected-route authentication | Shourya Sai Macha | Week 2 feature; Week 5 lead integration | T02/D15, exact access model; required before private API exposure |
| Customer and business emails | Shourya Sai Macha | Week 3, triggers/logging in Week 4 | Verified sender/test recipients, durable jobs, failure and duplicate protection |
| Database tables/models/integrity | Bryson Hawthorne | Weeks 1-4 | Supplied table draft recognized; ERD/code/migrations still needed |
| Admin dashboard shell/styling | Aneena Paul | Week 5 | Auth and agreed order data |
| Admin lists/details/status interactions | Dillion Nguyen | Week 5 | Anh APIs and Shourya auth |
| Updates, payment status, export APIs | Anh Hyunh | Week 5 | D09/D10/D11/D18, Bryson query/index handoff |
| Google Calendar integration | Shourya Sai Macha | Week 5 | Authorized calendar, agreed booking trigger, stored IDs/revisions |
| Final-payment/count reminders and deposit contract email | Shourya Sai Macha | Week 6 | D12/D13/D14/D17, verified payment/count state |
| Backup, migration deployment and recovery | Bryson Hawthorne | Week 6 and final verification | Tested restore and integrity evidence |
| Staging integration/review/demo | Isaac | Week 4 | Actual owner components, approved host/release and migration evidence |

The plan now specifies individual primary owners; secondary reviewers/backups still
need agreement. Shopify feasibility and the optional chatbot remain outside Isaac's
implementation scope and have no individual owner in the supplied developer plan.

## Week 4 integration sequence

1. Isaac verifies shared shells and approved configuration; Anh/Bryson/Dillion resolve T08.
2. Bryson supplies executable migrations/models and create-order transaction functions.
3. Anh supplies the real quote/create/list/detail APIs; Dillion supplies the form/summary.
4. Isaac connects completed components, with prior approval for teammate-owned edits.
5. Shourya connects order-created emails and demonstrates durable failure/duplicate handling.
6. Isaac executes applicable Week 4 scenarios and reviews the first staging artifact.
7. Deploy only with explicit external approval; record real staging evidence and October 9 demo.

Later Calendar/reminder/contract workflows stay in the forward contract and future
backlog. They are not fabricated as working features to complete this week's checklist.
