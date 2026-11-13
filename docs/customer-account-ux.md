# Customer account UX

Prepared November 13, 2026. Reference: Crumbl's signed-in account settings,
inline profile editor and order-history empty state. The reference account was
left unchanged; no profile edits, payments or orders were submitted.

The Popssibilities account now uses a white layout with brand typography, a pink
active navigation item, personal details, a catering shortcut and separate
Sign-In & Security and Email Preview sections. Mobile navigation wraps above
the content. Shared public navigation and the footer stay consistent.

The existing customer session provides the name and email. Authentication,
session polling/expiry, CSRF-bound sign-out and explicit sample-email behavior
remain intact. Navigation uses a non-sensitive `view` query parameter, which
survives reload/back navigation. Unknown views fall back to Account Overview.
The email component stays mounted across section switches so a sent or pending
email cannot be repeated by changing sections; changing the authenticated
customer still clears its state. No real email was sent during validation.

Profile editing and customer order history need backend APIs before being
added. Existing order-listing routes are administrator-only. This change adds
no customer-order API, profile mutation, saved payment methods or rewards.
The account overview does not claim that an empty order history was fetched.

Validation uses synthetic sessions and mocked email requests. Browser coverage
checks customer/admin authentication, session restoration, sign-out, expiry,
email retry/deduplication, account-section navigation and widths of 320, 375,
768 and 1440 pixels. This release targets `dev`; staging and production
deployment remain separate work.

Final pre-dev review: all 173 frontend browser checks passed, including the
81 account/authentication/public-navigation cases. Captured desktop, tablet and
phone account layouts were inspected. The production build, frontend formatting,
foundation and whitespace checks also passed. Backend behavior and environment
settings are unchanged.
