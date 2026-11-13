# ZIP-area service checks

`us-zcta-centers-2026.json` contains 33,791 Census ZIP Code Tabulation Area
representative points, reduced to `GEOID: [INTPTLAT, INTPTLONG]`. It is loaded
only by the backend; it is not part of the browser bundle. No provider calls,
customer addresses or credentials are needed to use it.

- Source: [2026 U.S. Census Gazetteer files](https://www.census.gov/geographies/reference-files/time-series/geo/gazetteer-files.2026.html).
- Download: [National ZCTA ZIP archive](https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2026_Gazetteer/2026_Gaz_zcta_national.zip).
- Member: `2026_Gaz_zcta_national.txt`.
- Downloaded November 13, 2026.
- Archive SHA-256: `f1e9046b91f6e60686a99343cb2752834c02b0764939403b331c78c017e2c54c`.
- JSON SHA-256: `3a849482a11ead5c0fb8326a8cd0b087a5ee95e38c624746c674d964bc6f8f7d`.
- Retain the five-character code, including leading zeroes. Parse coordinates as
  decimals and sort by code. One JSON entry per line keeps updates reviewable.

The fixed service anchor is **77477 (Stafford)** at the published representative
point **29.623924, -95.567088**. Haversine distance between ZIP representative
points is compared with the existing 30-mile limit. ZIP+4 inputs use the first
five digits. The same ZIP is zero miles from itself. No route or street-address
geocoding is performed for eligibility.

ZCTAs approximate ZIP delivery areas; they are not USPS address validation or an
exact street-level measurement. [Some valid ZIPs have no ZCTA](https://www.census.gov/programs-surveys/geography/guidance/geo-areas/zctas.html),
including some PO-box/unique/new ZIPs. Missing/invalid ZIPs never receive a green
approval. The customer can still get a product/extra estimate for owner review.
Before updating the file, verify its provenance, fixed-center record and nearby,
boundary and distant checks; record the new source/hash here.
