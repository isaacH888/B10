# Client content confirmations

Recorded November 12–13, 2026 from Adriana's answers and pricing information
relayed by Isaac in conversation.
These answers guide the public website and catering copy. The original charter
and supplied documents remain unchanged.

## Flavors and ingredients

Audrey chooses which flavors to make, and availability fluctuates. A fixed list
of current flavors is not a content requirement. Public copy should explain
that flavors rotate and that the team confirms available options for each event.
Customers can share custom preferences and allergy details in the existing notes
field. An example flavor is not a promise of current availability.

Isaac subsequently supplied approval to show these five flavors for demo purposes:

- Mango Lime
- Strawberry Lime
- Mango Dragonfruit
- Strawberries and Cream
- Watermelon Strawberry and Kiwi

The homepage now has a photo-led sample flavor section between The Paleta Life
cards and Audrey's story, with Flavors navigation links and a catering link.
The supplied transparent paleta photo is a general product image; it does not
assign specific recipes to the pictured paletas.

The catering form supports an optional mix of up to five dropdown selections
with custom whole-number quantities. The selected counts must total the order
quantity. "Split evenly across all 5" gives 10 of each for 50; remainders are
distributed one at a time for totals that are not divisible by five. Customers
can remove selections or let Audrey choose, and retain custom/allergy notes.

The requested mix is a structured optional `catering_request.flavor_allocations`
array, validated by both quote and order routes and saved with the order. It
appears in the review, confirmation, owner detail and booking intake/source
views. Old requests and saved drafts without this field remain supported.
Requested flavor quantities are separate from the owner's actual inventory
reservations; sample choices do not automatically reserve stock.

Adriana describes the paletas as organic and made with fresh fruit. The catering
page uses that supplied ingredient description without claiming certification.
The owner-written story remains as supplied by Isaac.

## Allergy information

The supplied examples are nuts, coconut, strawberries, pineapple and other
fruits. Ingredients vary by flavor. The website gives these examples and directs
customers to the team for specific ingredient and allergy questions before
ordering. This is not a complete recipe-by-recipe ingredient list or an
allergen-free guarantee.

Allergy information appears on the catering page and beside the flavor request
field. The field's accessible description includes availability and allergy
information. Customers can include allergy details in the existing request text;
the flavor-mix update adds no dietary-safety automation.

## Catering sources

Adriana identifies the [project charter](project-charter.md) and `Assumptions.docx`
on Teams as the catering sources. The local Downloads copies of `Assumptions.docx`
and `Popssibilities Project Charter.docx` were read again on November 12. Both
copies have October 5 file modification dates. Their contents match the
previously recorded S04/S05 evidence in
[reference alignment](reference-alignment.md).

Isaac subsequently supplied `Assumptions(1).docx` in this conversation on
November 12. File-hash comparison confirms it is byte-for-byte identical to the
previously reviewed `Assumptions.docx`. This supplied copy contains the same four
questions and answers, with no additional pricing or policy details.

The charter establishes minimum 50 paletas, delivery within 30 miles at $25–$75,
dry ice at $15 per block, a 50% deposit and a final-payment reminder seven days
before the event. Assumptions records the kitchen origin, contact/inquiry handling
beyond 30 miles, Square as the first provider and full service with 1–2 staff:
30 minutes setup, 2.5 hours serving and 30 minutes breakdown, totaling 3.5 hours.
The catering page now describes that recorded service scope.

The documents do not supply quantity-tier unit prices, heart-shape/add-on prices,
tax/refund/cancellation terms, or explicit approval of the $150 service fee
mentioned in a question. The subsequent unit-price confirmation below supersedes
the old regular/heart rates. Other policy decisions remain open where details
are absent; see [the decision register](decisions-and-blockers.md).

## Catering unit prices

On November 13, Isaac relayed catering prices of **$4.50 per regular paleta**
and **$3.00 per heart-shaped paleta**. Pricing revision `2.0.0` applies those
rates to new quotes and orders. The previous volume discounts and $0.50 heart
surcharge are superseded; a heart-shaped unit costs $3.00 in total.

The existing minimum of 50 paletas, delivery/full-service charges, dry-ice fees
and deposit calculation are retained. For example, 50 regular paletas cost
$225.00 and 50 hearts cost $150.00 before service or dry-ice charges. Further
quantity discounts, mixed-shape ordering policy and other unconfirmed policies
are not established by this price update. The public form still selects one
shape for the order and shows both unit prices in the shape dropdown and the
pricing facts. Flavors remain independently selectable within that shape.

Heart-shaped units use the `heart_shaped_popsicles` pricing line item, replacing
the old surcharge item. The flat quote breakdown correspondingly uses
`heart_shaped_popsicles_cents`; regular units retain `base_popsicles_cents`.
Line items remain nonnegative integer cents and sum to the total. Existing
saved orders and idempotent submission replays retain their original price and
revision. No database migration is needed.

## Customer reviews

Adriana confirms there are no customer reviews and no Google business page.
Testimonials, ratings and a Google-review integration are not content requirements.
The current public pages contain no customer-review section.

## Social profiles

Isaac supplied the business's social URLs on November 12:

- [Instagram: @popssibilities_llc](https://www.instagram.com/popssibilities_llc/)
- [Facebook: Popssibilities, LLC](https://www.facebook.com/popssibilitiesllc/)

The homepage/public footer and catering footer display "Follow our socials!"
with Instagram and Facebook icon links. The shared links use the supplied URLs,
open in a new tab, and include accessible platform names, keyboard focus styling
and 44-pixel click targets. The icons are inline SVGs with no external icon/font
dependency or embedded social feeds.

## Remaining public content

The owner story and supplied photo slideshow are implemented. Flavor availability,
ingredient wording, the provided allergy examples and the absence of reviews
are now recorded. Social URLs have been supplied and linked in both footers.
The unresolved catering/pricing details above remain public-content follow-up.

## Local validation

The production build, repository frontend formatting checks, foundation checks
and Git whitespace checks passed. All 36 existing catering/public-site browser
tests passed in installed Chrome, including narrow booking dialogs and public
pages at 320, 375, 768 and 1440 pixels. That initial content update changed public
copy, hints and documentation while preserving the quote and order contracts.

After adding the social links, the build, formatting/foundation/whitespace checks
and all 11 public-site browser tests passed again. Direct footer checks passed
on the homepage and catering page at 320, 375 and 1440 pixels: exact URLs, new-tab
opening, keyboard activation/focus, 44-pixel targets and no horizontal overflow.
Desktop/mobile footer screenshots were visually inspected. External profile
navigation was intercepted during QA; these checks verify the supplied link
targets and browser behavior, not the social accounts' content or availability.

The approved flavor-mix follow-up passed **1,232 backend tests** against a fresh
disposable MySQL 8.4.13 container, including 47 new validation and persistence
cases. The container and volume were removed afterwards. Backend log:
`/private/tmp/b10-flavor-mix-backend-full.log`.

The affected browser suite passed 59 cases; the additional owner flavor-display
check initially matched two equivalent text elements. Its locator was scoped to
the Flavor Requests area and passed on rerun, verifying all 60 affected cases.
Coverage includes the five-way split, custom dropdown amounts, remainder handling,
under/over totals, invalid quantities, old/new drafts, quote invalidation, customer
confirmation and owner display. Build, frontend formatting, Python lint/format,
foundation and whitespace checks passed. The menu and picker were visually
inspected on desktop and mobile; picker controls were checked at 320, 375 and
1440 pixels. No schema migration or flavor inventory reservation is introduced.

The November 13 unit-price follow-up passed all **1,241 backend tests** against
a fresh disposable MySQL 8.4.13 container, which was removed afterwards, and all
47 affected public/catering browser cases. Quote/order parity, the old quantity
boundaries, mixed-shape arithmetic, deposits, saved price snapshots and replay
behavior are covered. Backend log:
`/private/tmp/b10-catering-prices-backend-full.log`.

Build, formatting, Ruff, foundation and whitespace checks passed. After widening
the shape selector for full price labels, checkout and all three narrow-dialog
checks passed again. The actual running localhost form also returned $250.00
for 50 regular paletas and $175.00 for 50 hearts, each including the existing
$25.00 base delivery fee, with deposits of $125.00 and $87.50. These were unsaved
quotes; no live order was submitted. The local backend was restarted to load
pricing revision 2.0.0.

## Service-area and quote follow-up (November 13)

Isaac requested a simple green in-area indicator instead of visible driving
mileage, and approved continuing outside-area requests to quote estimates. The
owner decides availability and travel/service fees. Estimates itemize known
paleta/extra prices, omit logistics and any deposit, and provide owner contact
links. The existing 30-mile calculation remains behind the scenes; the user did
not approve a new distance method or radius.

The later November 13 ZIP follow-up supersedes the earlier driving-method note:
Isaac fixed Stafford ZIP 77477 as the center of a 30-mile ZIP-area geographic
radius. Local Census representative points now determine area status without
a street match or API call. Unknown/outside ZIPs retain owner-review estimates.
