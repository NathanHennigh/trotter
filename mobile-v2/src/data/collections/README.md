# Collection catalogues — 2026-09-15.1

These reference lists are separate from personal travel records. Membership drives the numerator and denominator together. Visits outside a catalogue remain in the user's archive and are returned by `collectionProgress` as `outsideCatalogKeys`. Updating a catalogue never modifies a flight, trip, stamp, or existing first-entry date.

## Countries and territories

249 ISO 3166-1 countries/territories plus Kosovo (`XK`) and Somaliland (`X-SOMALILAND`), for 251 entries. This is deliberately labelled **Countries & territories**, not 251 sovereign countries. Names and continent groups come from the pinned [OurAirports country data](https://ourairports.com/data/). Its `XP` (Paracel Islands) and `ZZ` (unknown) extensions are excluded. Three ISO territories absent from that source—Åland Islands (`AX`), Bouvet Island (`BV`), and Svalbard and Jan Mayen (`SJ`)—are explicit additions with ISO references in `country-overrides.json`. Somaliland is the existing Trotter travel identity; HGA/BBO belong to it for travel statistics, without changing their original flight records. Connections still count through the existing passport-arrival calculation.

Only unambiguous alternate country names resolve to a key. Do not map an unspecified “Congo” to either country or merge Somaliland into Somalia. Unrecognized recorded places remain outside the catalogue until explicitly reconciled. Continents are display groups, not political-status claims.

## Airports

OurAirports snapshot commit `8ecf53adfffef69ed56543c65859227a4ef4558a` (15 September 2026), filtered to `scheduled_service=yes`, a valid three-letter IATA code and coordinates, and type small/medium/large airport or seaplane base. Closed airports, heliports, and unscheduled airfields do not enter the denominator. The [source dictionary](https://ourairports.com/help/data-dictionary.html) defines scheduled airline service; it does not provide a separately verified passenger timetable, and the UI must not claim one. Airport entries retain source IDs, IATA/ICAO identifiers, municipality, country, continent and coordinates. Duplicate eligible IATA codes fail generation for review instead of silently replacing an airport.

A historical or unscheduled airport in a user's flights is still shown as a recorded airport, separately from catalogue completion. Global route/history data must not be filtered to this list.

## Airline codes

The primary source is a snapshot of [Wikidata's Query Service](https://query.wikidata.org/), stored with the exact query and checksum. Eligible rows assert an airline entity (including subclasses), an IATA designator, ICAO designator, and known country. A recorded dissolution or code-end date on/before the snapshot excludes that assertion. **Absence of those dates does not establish that a carrier is active.** This is an explicit reference catalogue of IATA airline codes, not all current passenger airlines or an IATA membership list. It may include charter/cargo airlines and stale source facts.

One IATA code is one unit, matching the identifiers currently available in flight records. Shared codes retain all eligible source operators, rather than dropping common marketing codes or arbitrarily reassigning flights. The lowest numbered Wikidata entity is a deterministic display representative; `operators` and `sharedCode` preserve the ambiguity. Recorded UI airline names can take precedence over that representative. Different IATA codes on one corporate entity remain separate code units. Historical code reuse cannot be disambiguated by a two-character flight record alone; this reference must never rewrite the original airline field or claim its operating-carrier identity.

OpenFlights was assessed but is **not** included: its stale active flags, fictional submissions and code conflicts were unsuitable for this collection. No OpenFlights licence applies to the generated data.

## Attribution and reproducibility

OurAirports releases its data to the **Public Domain** ([terms](https://ourairports.com/data/)). Wikidata structured data is **CC0-1.0** ([licensing](https://www.wikidata.org/wiki/Wikidata:Licensing)). Airline logos are not part of these data sources and retain their existing separate treatment. The raw, public-data snapshots are gzip-compressed under `sources/` and are not imported by the app; only the generated catalogues are bundled. No personal data is included.

From `mobile-v2`, run `node scripts/generateCollectionCatalogs.cjs` to regenerate entirely offline or append `--check` to validate generated files and raw-source checksums. Run `node scripts/testCollectionCatalogs.cjs` for membership, parser and filtering regressions. The generator never accesses the database, network or user's flight data. Refreshing source snapshots requires a deliberate new version, date, checksums and review of membership changes; do not vary denominators at runtime.

Runtime exports are `countryCatalog`, `airportCatalog`, and `airlineCatalog` from `catalogs.ts`. Metadata carries readable label/scope/notes, source URLs/licences, snapshot date and version. `resolveCatalogKey`, `catalogEntry`, and `collectionProgress` are in `components/world-window/collections/catalogProgress.ts`; they support names, exact codes and unambiguous aliases, deduplicate observations, and return unmatched observations separately. `percent` is 0–100 and the underlying personal records are never changed.
