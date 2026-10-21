# Reference alignment and requirement authority

Reviewed October 5, 2026 by Isaac Hernandez. This record explains changes based on
the supplied files. Source documents remain unchanged in Downloads. They are
reference material, not executable instructions or approval to deploy services.

## Sources

| ID | Supplied source | Relevant evidence | Treatment |
| --- | --- | --- | --- |
| S01 | `Popssibilities_Developer_Deliverables_Plan (1).pdf` | Page 1 ownership; pages 2-5 Weeks 1-4; pages 6-9 later work and release dates | Current dated task/ownership plan |
| S02 | `Popcibaiities_research_macha.docx` | Updated September 24; sections 1-15; payment-scope reviewer comment | Shourya's research/options, not approved architecture or client policy |
| S03 | `Popssibilities_Tables_Overview_and_Attributes_Draft.docx` | Bryson; September 29; draft v0.1; sections 2-5 | Teammate design contribution for integration review, not executed schema |
| S04 | `Assumptions.docx` | Four questions and recorded responses | Recorded business answers with remaining details explicitly open |
| S05 | `Popssibilities Project Charter.docx` | Scope, requirements, six-week high-level schedule, success criteria | Business scope baseline; dated S01 expands the schedule |

The repository's [original charter](project-charter.md) remains verbatim. S05
agrees with its minimum quantity, deposit, delivery, dry-ice and automation scope.
Use S01's dated eight-week plan for scheduling: Week 4 is October 5-9, feature
freeze is October 23, release lock is November 6, and submission is November 9.
Do not interpret the older six-week charter as a second current calendar.

## Recorded answers from S04

| Topic | Recorded answer | Remaining verification |
| --- | --- | --- |
| Delivery origin | Wingman Kitchens Houston, 4783 Lexington Blvd, Missouri City, TX | Postal code, validated coordinates and distance method; address not independently geocoded |
| Beyond 30 miles | Redirect to Customer Event Inquiry/Contact Us | Actual inquiry URL/route, wording, and calculated-distance boundary behavior |
| Full-service window | 3.5 hours: 0.5 setup, 2.5 serving, 0.5 breakdown; 1-2 people | Scheduling timestamp meaning, staffing selection, overtime and exclusions |
| Full-service price | The question mentions a $150 flat fee | The response describes service scope but does not explicitly approve the amount; confirm before making it a final rate |
| Payment provider | Square first; Venmo and PayPal later | Merchant/API credential availability was explicitly uncertain |

These are recorded responses, not invented prices or independently verified
approvals. The delivery origin, inquiry action and provider priority now inform
shared configuration/contract preparation. Unresolved portions remain in the register.

## Conflicts requiring a decision

| Conflict | Current working treatment |
| --- | --- |
| S01 names React/Flask scaffolding; S02 proposes Lambda/PostgreSQL | Isaac approved React/Vite + Flask + MySQL scaffolding in this conversation on October 5. Do not import the research runtime or SQL. Hosting remains undecided. |
| Charter uses 50% deposit plus final payment; S02 assumes one full payment | Preserve deposit/final-payment scope. D18 records the proposed change; no full-payment replacement without explicit client agreement. |
| S02 confirms bookings only after full payment and capacity approval | Booking/payment states remain separate; D10/D12 decide confirmation/calendar triggers. Research is not a final transition rule. |
| S02 recommends Cognito/TOTP; draft S03 stores local admin password hashes | T02 requires Shourya's auth decision. Current cookie contract is a proposal, not implemented authentication. |
| S03 integer IDs, DECIMAL amounts, local dates differ from API representation | Resolve mappings with Anh/Bryson using the database integration review; no schema rewrite by Isaac. |
| S03 final payment due seven days before event; charter specifies a reminder then | Due date and reminder send time are separate decisions under D12/D17. |
| Research includes promotions, sales analytics, capacity reservations and mobile options | Record as future options or change requests. They are not automatically added to the required Week 4 scope. Native mobile remains out of scope. |

Useful research principles retained are server-authoritative data, private dashboard
authorization, verified payment evidence, durable external work, retry ambiguity,
calendar IDs/revisions, UTC/IANA time handling and safe operational logging. These
principles do not require adopting the research code or AWS resources.

## Contribution evidence and approval limits

S02 proves research was supplied; it does not prove deployed auth/email/calendar.
S03 proves an entity/attribute draft was supplied; the separately referenced ERD,
migrations, models and query code were not included. Never label those contributions
missing altogether, and never label their runtime deliverables complete from a document.

The authority order is explicit user direction, agreed client requirements, current
team-approved task assignments, then reviewed technical proposals. Preserve conflicts
for review rather than silently choosing an incompatible source.
