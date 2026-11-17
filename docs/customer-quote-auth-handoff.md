# Customer quote sign-in: code and hosting handoff

The code requires customer sign-in before the catering form opens. Google and
email/password use the existing Cognito login flow. Successful sign-in returns
to the quote form, including an existing same-tab draft. Quote and order writes
also enforce customer authentication, same-origin requests and CSRF on the server.

Quotes and submitted orders belong to the verified account identity, independently
of the contact email. My Account → My Orders reads `GET /api/v1/customer/orders`
and shows that account's submitted requests, current booking status and verified
deposit amounts. Once availability is approved, **Pay deposit** opens Square's
secure checkout for the unpaid deposit. It is unavailable before approval, after
cancellation/payment or when the reservation/payment window has expired. The
server checks account ownership and the current approval, revision and amount;
Square's verified webhook updates payment status. Unsubmitted quotes do not appear in this list. Existing guest
orders are not automatically assigned to matching email addresses.

## Hosting work for Shourya

These steps are separate from the code push. This change does not update AWS,
hosted credentials, Google configuration or the hosted database.

1. Review the target database's migration history and preserve existing checksums.
   Apply all pending compatible migrations, including
   `0014_customer_order_accounts.sql`, through the existing migration runner from
   `backend` with the intended environment's private migration credentials:

   ```sh
   .venv/bin/python -m app.migrations
   ```

   The new tables are `customer_quote_accounts` and `customer_order_accounts`.
   The runtime database user needs `SELECT` and `INSERT` on both, in addition to
   its existing application permissions. Do not point test fixtures at this database.

2. Confirm the hosted backend has enabled authentication, persistent MySQL access,
   stable application/encryption keys and the existing customer Cognito settings.
   `FRONTEND_ORIGIN` and `CORS_ALLOWED_ORIGINS` must match the website's exact HTTPS
   origin. Hosted configuration requires both customer and admin authentication.
   Keep credentials in the hosting secret configuration, never source or Vite variables.

3. Confirm customer Cognito supports Google and email/password signup, verification
   and login, with `<website-origin>/api/v1/customer/callback` as the application
   callback and `<website-origin>/login` as the logout landing. Google OAuth must
   retain the customer Cognito `/oauth2/idpresponse` redirect. Existing working
   pools, users and provider settings should be preserved.

4. After the schema review/application, set the deployment's
   `B10_MIGRATIONS_REVIEWED_SHA` to the exact full commit that will deploy from
   `dev` (the merge commit if applicable). The current deployment compares SQL
   files and blocks migration changes without that review marker. It updates code
   only; it does not run migrations or change AWS configuration. A feature-branch
   push runs checks without deploying the DEV website.

5. Verify the hosted flow using an approved test account: request a quote while
   signed out, complete each sign-in method, submit a synthetic order, sign out,
   sign back in and open My Orders. Update its booking through the existing owner
   workflow and confirm the customer sees the new status. A different account must
   not see or submit against the first account's records. Do not collect real payments.

6. For Pay deposit, configure Square and its webhook/worker processing using the
   existing [Square runbook](square-checkout.md), initially in Sandbox. This uses
   the existing `0013_square_checkout.sql` and `0014_customer_order_accounts.sql`;
   it needs no additional migration. Test owner approval → Pay deposit → Square
   Sandbox → verified webhook → updated My Orders. Test cancellation, conditional
   approval, expiry and another customer's account as well. Production credentials
   and real payment activation remain a separate hosting task.

Full configuration and deployment recovery procedures remain in
[authentication deployment](authentication-deployment.md) and
[Lambda deployment](lambda-auto-deploy.md).
