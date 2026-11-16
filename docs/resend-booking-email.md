# Booking payment emails through Resend

Approving availability saves the booking as `awaiting_deposit` and queues a
`deposit_request`. The dispatcher publishes it to the queue. The worker creates
an idempotent Square checkout and emails the customer's website payment link.
The website checks the amount and reservation before redirecting to Square.
The return page waits for the signed webhook to verify the captured payment;
the redirect itself never marks a deposit paid. A verified deposit confirms the
booking and queues confirmation emails. The owner can request the remaining
balance with **Create and email balance link**, using the same payment flow.

## Private settings

Configure these in the deployment's runtime secret, never in frontend variables
or source control:

```dotenv
EMAIL_PROVIDER=resend
RESEND_API_KEY=<private Resend sending key>
AUTOMATION_FROM_EMAIL=notifications@mail.popssibilities.com
EMAIL_FROM_ADDRESS=notifications@mail.popssibilities.com
EMAIL_REPLY_TO_ADDRESS=notifications@mail.popssibilities.com
```

The sender domain must be verified in Resend. `EMAIL_ENABLED=true` additionally
enables the existing signed-in customer sample-email endpoint. Booking mail is
controlled by `AUTOMATION_ENABLED` and `AUTOMATION_MODE=aws`. Resend uses HTTPS
and does not need SES permissions or dedicated AWS email credentials.

Deploy matching API, dispatcher, worker and DLQ code before selecting Resend.
Reload their runtime configuration after changing the private settings. Verify
the sender and key before enabling the queue worker and the once-a-minute
dispatcher rule. Review existing pending jobs before resuming an environment
that was paused. Cancelled, expired and obsolete payment messages are skipped
using current booking state. Keep Sandbox credentials for tests; real payments
require a separate production Square configuration.

## Retry behavior

Emails retain the same Resend idempotency key throughout an automatic retry.
The key is derived from the durable job key and replay generation. Duplicate
queue deliveries are also suppressed by the delivery record. Permanent provider
rejections need owner review; provider response bodies and credentials are not
exposed to customers or written to job diagnostics.

Resend remembers idempotency keys for 24 hours. Automatic retries stop after
23 hours from the first send attempt, including after a Learner Lab restart.
Check delivery in Resend before using **Retry** on an uncertain failed job.
An explicit owner replay creates a fresh generation and provider key. SES
remains supported through `EMAIL_PROVIDER=ses` for environments with SES access.

See [Resend's send-email API](https://resend.com/docs/api-reference/emails/send-email)
and [idempotency documentation](https://resend.com/docs/dashboard/emails/idempotency-keys).
