# Catering UX and public-site cleanup

Prepared November 12, 2026. Isaac authorized these local UX changes and requested
review, validation, and publication to `dev` after successful checks.

## Resulting behavior

- The schedule fields explicitly collect the event start and optional end date
  and time. Entries use Houston/Central time (`America/Chicago`) regardless of
  the visitor's device timezone. Daylight saving gaps and repeated clock times
  produce field errors instead of silently changing the requested schedule.
- Review and confirmation show the event start, end, timezone and address.
  Review sections have Edit buttons; changed details require a fresh quote.
- Step names, service/address labels, paleta terminology and request buttons
  explain the existing availability-review and verified-deposit workflow.
- Closing the form keeps its progress. A tab-scoped draft lasts up to two hours,
  survives reloads, and clears after submission or a confirmed Start over.
  Quotes and retry keys are not stored in that draft. Browser storage failures
  still allow close/reopen using the current page's in-memory draft.
- Validation identifies and focuses the first invalid field. The dialog keeps
  keyboard focus inside it, restores the opening button on close, and provides
  scrollable fields and visible navigation on narrow screens.
- Quote expiry offers explicit recalculation. Manual-review and request-failure
  states include working email and telephone contact links.
- Page navigation starts at the top while section links retain their anchors.
- The newsletter section, navigation links and unused styling are removed.
  The subsequently supplied Instagram and Facebook URLs are linked from the
  public and catering footers under "Follow our socials!".

## Scope and handoff

The initial UX changes affect the public frontend and documentation. The approved
demo flavor follow-up also adds optional structured flavor quantities with quote
and order validation; see [client content confirmations](client-content-confirmations.md).
Existing request fields, server-supplied prices, authentication and database schema
remain compatible.
Dillion owns catering interactions, Aneena owns shared visuals, and Isaac
coordinates this integration. The subsequent
[client content confirmations](client-content-confirmations.md) record the supplied
story/photos, rotating flavors, ingredient/allergy wording, catering sources and
the absence of customer reviews. Remaining policy details stay with Adriana and
her mom.

The reviewed diff contains synthetic browser fixtures and application source;
local settings, credentials, generated builds and test reports are excluded.
This review did not submit a live order or send a customer email.

## Validation

Local runtime: Node 25.9.0 and Python 3.12.16. The GitHub workflow uses the
repository's Node 22 baseline and an isolated MySQL service.

- Frontend formatting and production build: passed.
- OpenAPI/examples/configuration/local-link foundation checks: passed.
- Python formatting and lint: passed.
- Cognito, email and automation infrastructure template lint: passed.
- Full frontend browser suite: 137 passed.
- Full local backend suite: 1,048 passed and 137 skipped. Optional disposable
  MySQL and unavailable legacy-reference cases were not enabled locally;
  GitHub CI enables database integration against its isolated MySQL service.
- Git whitespace checks: passed.
- Safari visual review: the revised schedule labels, Central time explanation,
  booking wording and story-to-footer layout were inspected.

Browser coverage includes winter/summer offsets with a Tokyo device timezone,
daylight saving gaps/repeated times, end-before-start validation, full schedule
and address confirmation, draft close/reload/reset, editing and quote refresh,
stable submission retries, expiry, errors and navigation. Narrow booking-dialog
checks cover 320, 375 and 768 pixels; public-page checks also cover 1440 pixels.

Publication updates `dev`; staging and production deployment are separate work.

## Catering visual refresh — November 13, 2026

The catering request dialog now uses white form surfaces, a pale progress sidebar,
larger fields and pill buttons, and separate review cards. On smaller screens,
the sidebar becomes a compact progress indicator. Fields scroll independently
while the close button and Back/Next navigation remain visible. Flavor selection,
address suggestions, service-area notices and quote breakdowns use the same
spacing, borders and accents. The public landing-page content is unchanged.

The reference was Crumbl's signed-in catering selection, flavor quantities, bag
and checkout screens. Inspection stopped at payment; no payment details were
entered and no order was placed. This adaptation retains Popssibilities' five
steps, optional flavor allocations, pricing, ZIP-area checks, owner-review path,
draft behavior and availability/deposit workflow. No backend changes were needed.

Event type now offers five common choices (Birthday, Graduation, Wedding, Baby
shower and Corporate event) plus Custom. Custom reveals a required text field.
Existing free-text drafts restore under Custom; the chosen or entered event name
continues to use the existing event type field in review and API requests.

Both native event calendars disable days before today in Houston/Central time.
The limit refreshes when a date field receives focus and every minute while the
schedule step is open. Today remains selectable; the existing validation still
requires the event start to be a future time and the end to follow the start.

Validation: all 168 frontend browser tests passed, including the 51 catering and
address tests, along with the frontend formatting check, production build and
shared foundation check. Six responsive cases were also
captured and reviewed at 320, 375 and 768 pixels. Desktop contact, service,
schedule, flavor and review screens were inspected in the local preview using
synthetic details, which were cleared afterward. Live quote/order submission was
not used for the visual review. This refresh targets `dev`; staging and production
deployment remain separate work.
