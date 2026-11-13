# Public frontend integration

Prepared November 3, 2026 on `integration/aneena-frontend`, based on `dev`.
Aneena's uploaded sample is on `origin/frontend-aneena`, commit
`fa562e1be8ed2cf7eef487cc893e8516ab5d66aa`. Her source branch is preserved.
The [latest integration review](latest-push-integration.md) records its
combination with Dillion's updated catering and admin pages.

The standalone homepage and sign-in design are adapted into
[`PublicSite.jsx`](../frontend/src/PublicSite.jsx) and scoped
[`public-site.css`](../frontend/src/public-site.css). Uploaded images are copied
unchanged into the existing Vite asset pipeline. The root-level sample HTML,
JavaScript and README are not application entry points; development still uses
`npm run dev --prefix frontend`.

## Connected routes

| Route | Behavior |
| --- | --- |
| `/` | Public homepage, sample flavor menu, story sections and links into catering/sign-in |
| `/login` | Branded customer screen using the existing Cognito password/Google flow |
| `/account` | Existing protected customer session and sample email action |
| `/order` | Existing catering form and quote/order API integration |
| `/order/confirm` | Existing server-backed order confirmation |
| `/admin/login` | Existing administrator password/MFA flow, linked as Team sign-in |
| `/diagnostics` | Previous backend/database/authentication readiness controls |

Customer registration and password reset remain on the provider's secure sign-in
screen. The sample's placeholder username/password handlers are not used.
Existing session cookies, CSRF, provider redirect validation, permission checks,
quote/order calls and booking automation retain their current behavior.

The public header restores an authenticated customer's My account link from the
existing session context. Public content remains available when authentication is
unavailable. On November 12, Isaac removed newsletter signup from scope. The
newsletter section and its navigation links have been removed. Isaac supplied
the Instagram and Facebook profile URLs on November 12. Both public and catering
footers now include "Follow our socials!" with accessible linked icons that open
those profiles in a new tab. See
[client content confirmations](client-content-confirmations.md) for the URLs.

The [November 12 catering UX validation](catering-ux-validation.md) records the
schedule, draft, review, wording and navigation improvements and current checks.

## Fonts and layout

Anton and DM Sans are served locally, including on the existing catering page, so
page navigation no longer depends on Google Fonts requests. The font files come
from Google's [Anton](https://github.com/google/fonts/tree/main/ofl/anton) and
[DM Sans](https://github.com/google/fonts/tree/main/ofl/dmsans) distributions.
Their licenses are included as
[`Anton-OFL.txt`](../frontend/src/assets/fonts/Anton-OFL.txt) and
[`DM-Sans-OFL.txt`](../frontend/src/assets/fonts/DM-Sans-OFL.txt).

Public styles are scoped away from the administrator/diagnostics shell and the
existing catering form. Narrow-screen navigation keeps catering visible; the
branded sign-in buttons wrap within the available width.

## Validation

Validation passed on November 3, 2026:

- Production frontend build and repository frontend formatting checks.
- Shared foundation checks and Git whitespace checks.
- All 93 Chromium browser cases; all 8 public-page cases passed again after the
  final visual cleanup.
- Desktop/mobile screenshot review with no horizontal overflow or JavaScript
  errors at the inspected sizes.
- Homepage-to-catering flow against the running Flask backend: a synthetic
  50-paleta request returned HTTP 200, status `priced` and a $200.00 quote. The
  only POST was `/api/v1/quotes`; no order was submitted.

The browser suite includes homepage assets, public-to-catering navigation,
public-to-provider sign-in, restored customer navigation, authentication outages
and layouts at 320, 375, 768 and 1440 pixels, alongside the existing authentication,
catering, confirmation, email and automation cases. The pinned Chromium binary
was installed temporarily at `/private/tmp/b10-playwright` for local checks;
`PLAYWRIGHT_BROWSERS_PATH=/private/tmp/b10-playwright npm run test:browser --prefix frontend`
uses that installation. Normal team/CI setup can use its usual Playwright browser
installation.

At the November 3 validation, the local readiness probe returned backend reachable,
database `ok` and authentication `disabled`. Provider behavior is covered using controlled browser
API/provider responses; live Cognito sign-in requires the existing private
authentication configuration. No live customer order, email, payment or Calendar
event was created as part of this frontend integration.

On November 11, the owner confirmed successful live Google customer sign-in after
the existing private configuration and local Docker database were supplied. See
[authentication validation](authentication-validation.md) for the current access
limitations. The November 3 results above remain the historical UI validation.
