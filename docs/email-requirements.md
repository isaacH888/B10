# Email requirements extracted from the research document

Status: requirements extraction only, October 15, 2026. No email implementation,
AWS configuration, or messages sent as part of this extraction.

Source: `Popcibaiities_research_macha.docx`, titled *Authentication email calendar
and payment requirements*, updated September 24, 2026. The supplied file is at
`/home/machaman/Documents/Popcibaiities_research_macha.docx`.
Section numbers below refer to that document. Its examples and recommendations
are reference material, not instructions to deploy or replace existing decisions.

## 1. Purpose and delivery events

The document requires notifications to the owner and customer about orders and
payments, plus offers to customers who subscribe. The business database is the
source of truth; emails reflect committed business records.

The complete event table from section 4, paraphrased:

| Event | Owner email | Customer email |
| --- | --- | --- |
| Order or inquiry submitted | New request and a link to the private dashboard | Acknowledgement that states whether approval is still pending |
| Quote approved | Optional copy/record of the quote | Quote, terms, expiry, and payment link |
| Payment succeeds | Payment confirmation and order reference | Receipt showing the full amount paid under the document's proposed full-payment model |
| Catering confirmed | Confirmed booking details | Date, venue, service, and contact information |
| Order changed or cancelled | Updated order/booking status | Revised details or cancellation confirmation |
| Reminder becomes due | Upcoming catering or unpaid-order reminder | Agreed event reminder or a valid payment link |
| Promotion published | Campaign delivery summary | Offer sent only to customers subscribed to that topic |

The research recommends launching transactional email first. Promotions require
a preview and explicit owner approval before sending. It does not supply final
message copy, a visual template, exact reminder timing, or actual addresses.

## 2. Sender identity, replies, and service options

Section 4 recommends Amazon SES and compares three approaches:

| Approach | Benefit described in the source | Responsibility or limitation |
| --- | --- | --- |
| SES with application templates | AWS permissions/monitoring integration and flexible usage-based sending | Build templates, campaign workflow, and delivery operations |
| External email platform | Ready-made campaign editing and richer marketing tools | Additional vendor, subscription, integration, and data-handling review |
| Manual owner email | Simple interim manual process | Does not meet the automatic-notification requirement |

The sending requirements in sections 4–5 are:

- Send from a verified business domain, never from a spoofed customer address.
- Direct customer replies to a monitored business mailbox.
- Owner alerts may use the validated customer's address as `Reply-To`.
- Verify the identity in the selected AWS Region; configure DKIM and SPF/DMARC
  alignment, and obtain SES production access for normal customer sending.
- Configure bounce and complaint events and a suppression policy before launch.
- Apply send-rate limits. Do not expose recipients through shared `To`/`CC` lists.
- Keep credentials and email-service configuration on the server.
- Restrict sending permissions to the intended identity and required configuration
  set. The example names `ses:SendEmail`; the exact policy needs validation when
  the integration is implemented.

SES is the document's recommendation. The repository decision register still
records the email provider and worker execution model as open decisions.

## 3. Templates, trusted data, and configuration

Section 5 illustrates a trusted background worker sending one message to one
recipient. It does not propose a public API accepting arbitrary recipients and
message bodies. The worker obtains the recipient from the stored order.

The example includes:

- UTF-8 subject and plain-text content, with the order reference in the subject.
- An SES message tag named `kind` for the message type.
- An SES configuration set and the returned SES `MessageId`.
- Later addition of escaped HTML templates with equivalent plain-text content.

Server configuration named by the example and section 12:

| Setting/data | Purpose |
| --- | --- |
| `MAIL_FROM` | Approved business sender address |
| `SUPPORT_EMAIL` | Monitored reply mailbox |
| `SES_CONFIG_SET` | SES sending/event configuration set |
| Selected AWS Region and identity | Regional SES setup and sender verification |
| Queue URLs | Durable background delivery |
| Approved public/admin site origins | Correct customer links and private dashboard links |
| Marketing contact list/topics | Subscription and unsubscribe configuration |
| Consent records | Protected database records, including source, timestamp, and preferences |

The JavaScript example uses `@aws-sdk/client-sesv2`, `SESv2Client`, and
`SendEmailCommand`. It illustrates an integration boundary rather than supplying
production-ready application code. The existing Flask implementation will need
an adapter appropriate to its runtime if SES is selected.

## 4. Durable jobs, retries, and delivery tracking

Sections 5 and 11 require the following behavior:

1. Save business changes and their notification jobs in one database transaction.
   Publish committed outbox jobs to the worker queue afterwards.
2. Give each email a stable uniqueness key, for example order ID, order revision,
   message type, and recipient. Claim work atomically and tolerate queue redelivery.
3. Store the SES message ID after acceptance. Treat acceptance, delivery, bounce,
   and complaint as separate outcomes; acceptance does not prove inbox delivery.
4. Use bounded retries. If SES accepted a message but the worker failed before
   recording success, another attempt may duplicate the email. Flag uncertain
   sends for owner review; do not promise exactly-once delivery.
5. Validate queued messages and reload current business state before processing.
6. Keep payment recorded even when email or calendar services are unavailable.
   Show integration failures separately in the dashboard and allow investigation
   and controlled retry/replay.

The research proposes SQS with a dead-letter queue and failure alarms. Its Lambda
standard-queue example uses `ReportBatchItemFailures` and an appropriate visibility
timeout; it notes that FIFO queues need ordering-aware handling. These are proposed
deployment details, not a decision to replace the current backend.

## 5. Payment and booking dependencies

The executive recommendation and sections 6, 8–11 use this proposed sequence:

1. Owner approves the catering quote and availability and reserves capacity.
2. Create and persist the order-specific payment link, reference, and expiry,
   then email it. Align the payment deadline with the capacity hold and link expiry.
3. Confirm payment using verified provider evidence, including the correct order,
   amount, currency, and environment. A browser success page is not evidence.
4. Commit payment status plus one customer receipt and one owner-payment-alert job.
   Repeated payment notifications must not generate another receipt.
5. If capacity remains valid, confirm the catering booking, increment its revision,
   and queue confirmation emails and calendar work. Otherwise retain the payment
   and flag the booking for owner review without falsely confirming availability.

Failed, abandoned, or expired checkout does not trigger a successful-payment
receipt. Reuse an existing valid payment link; do not generate another on refresh
or issue another for an already-paid order under the research's model.

These rules depend on the document's **proposed one-full-payment model**. They
must be reconciled with the repository's deposit/final-payment baseline before
implementing payment, contract, or booking-confirmation triggers; see section 9.

## 6. Reminders

Sections 1 and 5 propose EventBridge Scheduler for reminder timing. Before sending,
the worker must reload the booking and payment state so that cancellation,
rescheduling, or recent payment does not produce an obsolete reminder or link.

Store timestamps in UTC and retain the event's IANA time zone. The research does
not specify reminder intervals, local send times, short-notice behavior, or the
number of reminders. Its general phrase "reminder due" does not establish a due
date or authorize a schedule.

## 7. Marketing consent and campaigns

Sections 4–5 require:

- Consent records with source, timestamp, and topic preferences.
- Separate campaign jobs for subscribed recipients.
- An unsubscribe mechanism in every campaign, with SES contact-list/topic
  subscription management suggested as a supporting mechanism.
- A fresh preference check when sending, even if the customer subscribed when
  the job was created.
- Essential transactional content kept separate from promotional content.
- Campaign preview, explicit owner approval, and an owner delivery summary.
- Send-rate limits and protection of other recipients' addresses.

Consent and retention requirements depend on the business location. The document
does not define topics, approved consent wording, retention periods, or who other
than the owner can prepare campaigns. Promotions remain a research option in the
repository's current scope register.

## 8. Security, operations, and acceptance checks

Sections 1, 12, and 15 call for least-privilege IAM, server-side configuration,
separate development/production environments, HTTPS, input validation, rate limits,
protected data, backups, and application audit records. Secrets must not appear
in the frontend or logs. Secret storage/caching and rotation are operational
requirements where secrets are needed; AWS identity permissions are distinct from
user-facing business permissions.

Budget for sending volume, workers, queues, storage, networking, secrets, and logs.
The document supplies no price estimate. Set budget alerts, log-retention limits,
queue-age alarms, and alerts for failed integrations. Assign responsibility for
customer questions, delivery failures, and integration recovery.

The explicit email acceptance scenarios in section 15 are:

- Inquiry/order acknowledgement.
- Customer receipt and owner alert.
- Bounce and complaint processing.
- Marketing unsubscribe.
- An ambiguous send/retry outcome.
- A reminder queued before cancellation.

Additional checks directly implied by sections 4–5 and 8–11 include duplicate
payment/queue events, unsubscribe after queuing, reschedule/payment before a
reminder, exhausted retries, protected recipient selection, and email-service
failure without loss of committed order/payment state. Implementation tests and
real SES delivery verification are separate future work; neither was performed
by this requirements extraction.

## 9. Existing decisions and unresolved conflicts

The repository's [reference alignment](reference-alignment.md),
[architecture](architecture.md), and [decision register](decisions-and-blockers.md)
provide context beyond the uploaded document:

| Topic | Research document | Existing repository record / treatment |
| --- | --- | --- |
| Runtime/database | Lambda/Node.js and PostgreSQL examples | React/Vite, Flask, and MySQL are the approved scaffold; no stack migration is inferred |
| Payment scope | One full payment and Paid/Unpaid | Preserve 50% deposit plus final payment until explicitly changed; D18 records this conflict |
| Payment provider | Stripe example; evaluate Square first if already used | Square first is recorded; do not choose Stripe from sample code |
| Booking confirmation | Full payment plus approved capacity | D10/D12 still need the actual booking/calendar transition rules |
| Contract email | No contract-email trigger specified | Existing scope includes deposit-triggered contract delivery; D13/D14 leave timing, link, ownership, and access open |
| Reminders | Generic upcoming-event/unpaid-order reminder | Charter includes a seven-day final-payment reminder; D12/D17 leave due date, timing, and eligibility open |
| Promotions | Subscribed offers and owner-approved campaigns | Research option; not automatically part of the initial order-email implementation |
| Email infrastructure | SES, SQS, EventBridge Scheduler | Provider and durable execution model remain open in T04/T06 |
| Authentication | Includes managed-login and email-code options | Preserve the current native administrator password/TOTP flow and separate customer authentication |

The DOCX also contains a reviewer comment saying its payment scope was simplified
to one full-payment link and that refunds, disputes, and reconciliation were
removed. This is evidence of the document's scope, not new user approval to
replace the repository's payment requirements.

Before dependent implementation, resolve:

1. Initial email events and whether promotions are deferred.
2. Sender domain/address/display name, monitored reply mailbox, owner-alert recipients, AWS
   Region, DNS access, provider selection, and SES production-access status if used.
3. Deposit/final-payment versus full-payment policy, booking-confirmation trigger,
   contract-delivery trigger/link/access, receipt wording for each payment, and
   the business country, currency, tax treatment, and cancellation terms.
4. Exact reminder timing/time zone, payment due dates/link expiry, and handling of
   short-notice orders, reschedules, cancellations, and final-count changes.
5. Approved templates, language, and business contact details; staff permissions for manual
   resend, recovery, and campaign preparation/approval.
6. Marketing topics, consent collection/wording/storage, unsubscribe policy,
   suppression behavior, retention periods, campaign tools, and the meaning of
   the delivery summary if marketing is included.
7. Order/payment schema and event interfaces, durable job ownership/runner,
   retry limits, reconciliation workflow, monitoring owner, and expected volume.

These are information gaps, not requests to share credentials. Secrets belong in
private deployment configuration.

## 10. Official references included in the source

The uploaded document cites these integration references. They are retained for
implementation research; their current contents were not reverified for this
document-only extraction.

- [SES production access](https://docs.aws.amazon.com/ses/latest/dg/request-production-access.html)
- [SES v2 SendEmail](https://docs.aws.amazon.com/ses/latest/APIReference-V2/API_SendEmail.html)
- [SES DMARC and email authentication](https://docs.aws.amazon.com/ses/latest/dg/send-email-authentication-dmarc.html)
- [SES subscription management](https://docs.aws.amazon.com/ses/latest/dg/sending-email-subscription-management.html)
- [Lambda with SQS](https://docs.aws.amazon.com/lambda/latest/dg/with-sqs.html)
- [Transactional outbox pattern](https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/transactional-outbox.html)
