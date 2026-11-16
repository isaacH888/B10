# Square Checkout

Square is the selected payment provider. The owner approves availability first. The deposit email includes a Popssibilities payment link for the unpaid part of the required 50% deposit. That page checks the current amount, reservation and approval before sending the customer to Square's hosted checkout. A completed, server-verified Square payment confirms the booking while its approved reservation is valid. The booking workspace can also create and email the remaining balance on a confirmed booking, including after the event.

Partial verified payments reduce the amount requested. The application never adds a processing surcharge. This integration supports USD card payments and eligible Apple Pay/Google Pay card wallets. Tipping, shipping, automatic discounts/taxes, Cash App Pay, Afterpay and bank transfers are disabled in the generated checkout. Card details stay with Square. Square sends its receipt to the email supplied during checkout; the booking workflow sends confirmation to the booking customer. Refunds, disputes and chargebacks are handled in Square, preserving the original payment ledger.

## Private configuration

Start in Square Sandbox. Keep these settings in `backend/.env` for local work or the deployment's private runtime secret for both API and worker. They are never frontend variables, committed credentials, or values to paste into chat.

```dotenv
SQUARE_ENABLED=true
SQUARE_ENVIRONMENT=sandbox
SQUARE_ACCESS_TOKEN=<Sandbox access token>
SQUARE_LOCATION_ID=<Sandbox USD location ID>
SQUARE_MERCHANT_ID=<Sandbox merchant ID>
SQUARE_WEBHOOK_SIGNATURE_KEY=<Webhook subscription signature key>
SQUARE_WEBHOOK_NOTIFICATION_URL=https://your-public-api.example/api/v1/payments/square/webhook
```

Leave `SQUARE_ENABLED=false` until all configuration is ready. `SQUARE_ENVIRONMENT` accepts `sandbox` or `production`; these select the fixed `connect.squareupsandbox.com` and `connect.squareup.com` API hosts. The application pins **Square-Version: 2026-09-16** and uses the existing `requests` dependency directly with Square's REST API. No browser application ID, SDK, publishable key or card tokenization code is needed for this hosted flow.

The Square account/location must belong to the intended merchant. For an OAuth access token, grant `ORDERS_READ`, `ORDERS_WRITE`, `PAYMENTS_READ` and `PAYMENTS_WRITE`. Use the owner's own Square application/account and credentials for the selected environment. An expired, revoked or wrong-environment token fails closed; provider error bodies and credentials are not returned to browsers or jobs.

`AUTH_ORIGIN` is derived from the configured frontend origin and determines payment/return URLs. No caller-supplied price, merchant, location or redirect is accepted. The application supports amounts from $1.00 through its configured upper bound of $999,999.99; Square account limits can be lower. Smaller outstanding amounts require an agreed external payment recorded by the owner.

## Setup and Sandbox verification

1. Install the normal locked backend requirements and apply migrations through the project's migration runner, including **0013_square_checkout.sql**, before enabling Square. This additive migration stores checkout intent, unique Square link/order IDs, expiry indexes and processed event IDs. The previous local Stripe migration was never deployed to shared databases and has been replaced before commit. Do not edit the history of a database where another migration numbered 0013 has already been applied.
2. Enable booking automation and its dispatcher, queue worker and mail delivery adapters. Deploy matching API/worker code and settings. The existing scheduled dispatcher should run every minute: in addition to normal outbox delivery it queues deletion of expired Square links. Local automation captures email using the memory mail adapter. Hosted email supports SES or [Resend](resend-booking-email.md); Resend works without SES access in Learner Lab.
3. In the Square Developer Console, select the Sandbox environment and configure a webhook subscription for **payment.created** and **payment.updated**, API version **2026-09-16**. Its exact public HTTPS notification URL must end with `/api/v1/payments/square/webhook`. Include any actual API Gateway stage prefix. Copy that subscription's signature key into the private configuration. The notification URL is part of Square's signature, so a different hostname, path, query or trailing slash will invalidate authentication. The public endpoint uses Square's signature rather than a Cognito session, API key or browser CSRF token.
4. Restart/redeploy API and worker. Create a synthetic future booking and approve availability. Process the deposit email job, open its Popssibilities payment link, and continue to the generated Sandbox link. Square's Sandbox uses a **testing panel**, which currently produces an `EXTERNAL` payment; it checks navigation but does not exercise this integration's card-only verification. To verify the complete payment flow, use Square's documented Sandbox card token (`cnon:card-nonce-ok`) against the synthetic checkout order, ensure the order is `OPEN` and the payment becomes `COMPLETED`/`CAPTURED`, and wait for the actual Square webhook. Confirm it records one payment and queues booking confirmation/Calendar work. Create a balance link and verify it requests only the remainder. Repeat a notification and confirm the ledger is unchanged. Never relax production payment verification to accept a Sandbox panel redirect or external-payment simulation.
5. Test cancellation, a failed/pending payment, and expiration. The application blocks new handoffs as soon as the saved window or approval becomes invalid. Run the dispatcher and worker and verify the obsolete Square link is deleted. A late payment that settled before deletion must be retained for owner review without reviving cancelled or conditional bookings.

Use Square's [Quick Pay Checkout guide](https://developer.squareup.com/docs/checkout-api/quick-pay-checkout), [Square Order Checkout](https://developer.squareup.com/docs/checkout-api/square-order-checkout), [CreatePaymentLink reference](https://developer.squareup.com/reference/square/checkout/create-payment-link), [webhook validation](https://developer.squareup.com/docs/webhooks/step3validate), and [checkout management guide](https://developer.squareup.com/docs/checkout-api/manage-checkout).

## Payment and expiration rules

- The fresh-owner/CSRF-protected create action accepts only `purpose` and `expected_revision`. The server prices the outstanding deposit/balance from the agreed booking and immutable verified-payment ledger. Requested, conditional, cancelled and expired deposit approvals cannot start checkout.
- The exact Square request and a random checkout capability are committed before the network call. A timeout retry reuses the same creation intent and Square idempotency key. Concurrent clicks reuse an eligible open link. Ambiguous requests older than 23 hours are quarantined for owner inspection in Square; the application never blindly rotates a possibly-used key. Locate the request using its booking reference, order reference/metadata, and checkout audit before resolving it. Never delete payment rows to clear a retry.
- Square API-generated links are single-use. They do **not** accept Stripe-style native expiration/cancel URL parameters. Emailed URLs therefore point to `/payment/pay?checkout=<opaque-id>`, which validates current eligibility before exposing the Square destination. The payment window is at most 24 hours and a deposit window is capped by reservation expiry and event start. Balance windows can extend beyond the event.
- The scheduled dispatcher scans indexed open/creating checkout rows for expiry and enqueues `square_reconcile` jobs. Booking changes also queue reconciliation. The worker deletes obsolete unpaid links using Square's API, which cancels their Square order. It checks for settled or in-flight tenders before deletion and waits for payment verification instead of cancelling those orders. Keep dispatch/worker processing healthy; a customer who already copied the provider URL can still complete payment until Square deletion takes effect. This race is handled by preserving late money and requiring availability review, not by pretending a redirect or timer prevents every payment.
- Webhooks authenticate the configured notification URL plus untouched raw body using Square's documented Base64 HMAC-SHA256 and a constant-time comparison. Square does not use Stripe's timestamp-signature format. Durable event IDs and globally unique `square:<payment_id>` references prevent replay and duplicate money.
- Notifications from another merchant or unrelated POS/application payments are never credited to a booking. The server retrieves the actual Payment and Order using the private token, verifies their IDs, location, exact USD amounts, order reference/metadata and checkout note, and requires a **COMPLETED** card payment with **CAPTURED** card status. Pending, authorized, failed or cancelled payments never confirm a booking. Money, booking changes, confirmation outbox, checkout status and event deduplication commit together.
- A success/cancel query parameter, customer screenshot or browser claim never verifies money. Public payment status exposes only amount, currency, purpose, environment, paid/pending/expired state and handoff availability; no customer, booking ID, address, provider URL or card details are returned by the read endpoint. The start action requires both the emailed capability and the same browser origin, accepts no payment fields, and returns only the checked Square URL.
- The manual owner adapter remains available for independently verified external payments. The owner can independently verify a Square POS/external payment and record its actual Square Payment ID. Manual and automatic Square records use the same namespaced transaction reference, preventing double counting if a later webhook sees it. Historical manually verified Square records with raw transaction IDs are also recognized without rewriting the original payment history. The audit distinguishes owner verification from webhook verification. Refunds/disputes require owner action in Square and do not erase the historical payment ledger.

## HTTP endpoints

Responses use the existing `{data, meta}` / `{error}` envelopes and `Cache-Control: no-store`.

| Endpoint | Access and behavior |
| --- | --- |
| `GET /api/v1/admin/automation/square` | Owner session; enabled state and Sandbox/production environment only. |
| `POST /api/v1/admin/automation/bookings/<id>/checkout` | Fresh owner session and CSRF; JSON `purpose: deposit|balance`, `expected_revision: integer`. Returns the application's payment URL, amount and deadline, and queues one email. |
| `GET /api/v1/payments/square/<opaque-id>` | Public capability; current amount/status/environment and `can_pay`, without identity or card information. |
| `POST /api/v1/payments/square/<opaque-id>/start` | Same-origin public capability; JSON `{}`. Rechecks booking/amount/window and returns the Square hosted URL. No ledger mutation. |
| `POST /api/v1/payments/square/webhook` | Public, authenticated by `X-Square-HmacSha256-Signature`. Successful/irrelevant/duplicate events return 200. Signature/body errors return 400; payment mismatch 409; provider/storage failure 503 for retry. |

## Production activation

Use the owner's activated Square merchant account, `SQUARE_ENVIRONMENT=production`, its production token/location/merchant IDs and a production webhook subscription/signature key. Sandbox and production bookings cannot be mixed. Square Sandbox renders a testing panel, so a production hosted page's visual appearance must be reviewed using the merchant account's Square branding settings. Keep Square/webhook processing enabled while issued links can settle; disabling it makes handoff and notifications unavailable until restored. Monitor Square's webhook delivery failures and resend after recovery; automatic retry windows are finite.

Automated tests use Square-shaped responses, the documented signature algorithm, disposable MySQL and isolated browser fixtures. They do not prove that an account, real Sandbox transaction, webhook subscription, SES delivery or deployed API is configured. Complete the Sandbox steps before production payment activation. The previously reported DEV deployment was blocked by expired AWS credentials and its API returned 500; restore a healthy deployment before testing the public notification URL.
