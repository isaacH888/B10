# Catering addresses and the Stafford ZIP-radius check

Isaac's latest November 13 instruction fixes the service-area center at
**Stafford ZIP 77477** and keeps a **30-mile radius**. This supersedes the earlier
street-address/driving-route calculation from the recorded kitchen address.
The check now compares representative ZIP-area centers using geographic distance.
It is approximate ZIP-to-ZIP eligibility, not street-address validation or driving
mileage. Normal booking availability still requires the owner's review.

## Customer experience

Step 2 automatically checks a valid ZIP after a short pause, including when the
street/city fields are still empty. The status sits below the ZIP fields. It shows
a green **Within our service area** check, **Owner review needed** for outside ZIPs,
or manual-review guidance for a ZIP missing from the data. It labels the basis as
ZIP-area centers within 30 miles of Stafford 77477 and hides numeric mileage.
ZIP+4 uses its first five digits.

Editing the ZIP clears the earlier status and checks the new ZIP. Older responses
cannot approve a newer entry. Editing street/city text without changing the ZIP
does not invalidate its area status. Full event address/contact details remain
required before a normal quote or order, even though the area check itself only
needs the ZIP.

Outside-area and unknown ZIPs can still continue to a paletas/extras quote estimate.
The estimate uses $4.50 regular or $3.00 heart-shaped paletas and the existing
$15 per requested dry-ice block. Service/travel fees are excluded and the owner
confirms availability, fees and final price. No deposit is due for an estimate.
A prefilled email link includes the event and estimate details for owner review.
An estimate cannot authorize a normal accepted booking or bypass the server's
service check. Existing quote-persistence/custom-fee workflow limitations remain.

Geoapify remains optional for US-wide address suggestions and city/state/ZIP
autofill. Selecting a suggestion fills the fields before the separate ZIP check.
Suggestions support keyboard/mobile interaction, source attribution and stale
response cancellation. City/state/ZIP context helps ambiguous street searches.
A missing API key disables suggestions, while manual entry and ZIP checks work.

## Local data and fixed center

The backend bundles 33,791 representative ZIP-area points from the
[2026 Census Gazetteer](https://www.census.gov/geographies/reference-files/time-series/geo/gazetteer-files.2026.html).
See [data provenance and hashes](../backend/app/data/README.md). The published
77477 point is **29.623924, -95.567088**. The fixed anchor is implemented in
`backend/app/postal_areas.py`; legacy kitchen settings cannot move it.

Radius checks are local: no Geoapify geocoding/routing, address-match confidence,
network request or API credit is needed. The coordinate file is cached in server
memory and is not bundled into frontend assets. Customer addresses, routes and
eligibility results are not retained in a provider cache.

Census ZCTAs approximate postal areas and do not cover every valid USPS ZIP,
including some PO-box/unique/new codes. Missing points never produce a guessed
zero distance or green approval. Those requests get an owner-review estimate.
The reference is versioned; updates require source/hash review and boundary tests.

Known checks from this dataset:

| ZIP | Approximate miles from 77477 | Result |
| --- | ---: | --- |
| 77477 | 0.00 | In area |
| 77478 | 2.51 | In area |
| 77479 | 5.76 | In area |
| 77002 | 15.18 | In area |
| 77058 | 28.41 | In area |
| 77550 | 52.73 | Owner review |
| 77380 | 35.94 | Owner review |
| 34698 | 780.82 | Owner review |

These geographic results intentionally differ from the old driving-route results.
For example, ZIP 77058 is within this geographic radius even though the earlier
street-level route check was over 30 driving miles.

## API and pricing

Exact shapes are in [OpenAPI](api/openapi.json).

| Endpoint under `/api/v1/catering/address` | Behavior |
| --- | --- |
| `GET /config` | Suggestion `enabled` flag, independent `service_area_enabled` flag, fixed `origin_postal_code: "77477"`, radius and `distance_method: "zip_centroid_radius"` |
| `POST /suggestions` | Geoapify US address suggestions after four characters and a fresh UUIDv4 session |
| `POST /resolve` | Signed address components; optional `check_service_area: false` for separate autofill/check calls |
| `POST /check` | Accepts a ZIP-only location and optional US country; returns local radius status |

Selections are signed, bound to the search session and valid for 15 minutes.
Keys and raw provider errors stay on the backend. The public form sends the
selected address to `/resolve` without waiting for eligibility. ZIP changes
trigger `/check` after 250 ms; manual checks and Next can also request it.

Quotes/orders independently recompute ZIP eligibility on the server. Browser
coordinates, distances or origin values cannot move the anchor or change fees.
Pricing revision **2.1.0** records the change to ZIP-area distance for eligibility
and the existing delivery-fee formula. Unit prices and fee formulas are unchanged;
stored orders and idempotent replays preserve their accepted snapshots.

Eligible ZIPs with complete event details receive normal accepted pricing.
Unknown/outside ZIPs return `requires_review`, null accepted `pricing` and an
`estimate` of known products/extras with no deposit. There is no new database
migration or automatic approval of outside-area exceptions.

## Setup and validation

No API setup is needed for the radius check. For suggestions, create a free
[Geoapify project](https://myprojects.geoapify.com/) and privately set
`GEOAPIFY_API_KEY` in the backend, then restart. Restrict deployed keys to authorized
backend egress IPs and keep them out of chat, version control, logs and `VITE_`
variables. Their [Free plan](https://www.geoapify.com/pricing/) currently includes
3,000 credits/day; ZIP checks use none of them. Geoapify/required data-source links
appear only with its address suggestions and resolved address data.

`DELIVERY_ORIGIN_ADDRESS` remains a recorded kitchen setting; it does not define
this service area. Hosted deployment still needs approved privacy/terms and
shared request limits. No hosted deployment or paid upgrade was performed.

Validation passed: **1,316 backend tests** using disposable MySQL 8.4.13,
**47 selected catering/address browser cases** (address cases rerun after the
status placement/attribution change), build, formatting, Ruff and foundation
checks. The disposable container and volume were removed; development data was
not used for the regression suite. Backend log:
`/private/tmp/b10-stafford-zip-backend-full.log`.

A live local Chrome run at 375 pixels checked 77477, 77479 and 77058 as inside;
77550 and Florida ZIP 34698 as outside; ZIP+4 correctly; and an absent ZIP as
unavailable. ZIP-only checks completed in roughly 0.3-0.6 seconds in that run.
A complete Galveston request still generated the $225 product/extra estimate for
owner review. No order was submitted and no horizontal overflow was present.

## Pre-dev review (November 13)

The working-tree review fixed two UI regressions before publication:

- Selecting a different suggested street in the same ZIP now preserves its
  existing ZIP-area status. A changed ZIP still clears and rechecks eligibility.
- The owner-review email now includes the entered customer contact details,
  event type/start/end/time zone, all flavor quantities, flavor/allergy requests
  and event notes, alongside the estimate and service-review guidance.

Both issues were reproduced with regression tests before fixing them. The new
provider fixture also received the formatting required by CI. No private values
were found in the changed files or production assets, the sample admin-preview
records were absent from production JavaScript, and the bundled ZIP data hash
matches its source manifest. Remote `dev` still matched the local base commit
when checked. No commit or push was made during this review.

Final local checks passed: **1,316 backend tests** against disposable MySQL,
**165 main browser tests**, **5 separate admin-preview tests**, production build,
full Python/JS formatting and lint, foundation validation (41 operations / 174
schema-valid examples / 220 local links), and whitespace checks. The temporary
MySQL container/volume was removed. Backend review log:
`/private/tmp/b10-pre-dev-review-backend-full.log`.
