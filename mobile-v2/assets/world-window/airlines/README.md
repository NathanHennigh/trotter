# Airline symbols

These are authentic carrier identifiers displayed in small square slots. Existing approved PNGs (AA, AM, AT, B6, BR, DL, EK, ET, F9, G4, IB, NH, NK, SY, UA, WN, Z2) remain unchanged, including historical Spirit branding. Their earlier acquisition source was not recorded in the repository; no new provenance is invented for them.

The additional 78 symbols were retrieved from Duffel's airline symbol CDN on 2026-09-15. `sources.json` records every source URL, source SHA-256, output SHA-256 and dimensions. The source SVG is rendered without cropping or recoloring into a transparent 128×128 PNG using `sharp` (contain, preserve aspect ratio). A few carriers' actual identifying marks are typographic; the full-width lockup endpoint is never used.

Primary provider documentation: https://duffel.com/docs/api/airlines (`logo_symbol_url`, distinct from `logo_lockup_url`). Source assets remain the trademarks of their respective airlines; neither the provider nor this project grants ownership or implies airline endorsement.

`node scripts/updateAirlineLogos.cjs` refreshes only its explicit reviewed set, regenerating the local require map and provenance manifest. It does not scrape all 867 catalogue entries or read personal flight data. The bundled set is 95 codes; it covers all 17 named codes observed in the current local flight archive.

Other catalogue codes are looked up lazily from the same documented symbol CDN. This is best-effort coverage, not a claim that every catalogue carrier has an available mark. The app shares in-flight requests, allows four concurrent requests, retains at most 96 cached results / 2 MiB of XML, applies a six-second timeout and caches missing results to avoid repeated network requests. Only a normalized catalogue IATA code is sent. Invalid, unavailable, offline, oversized, unsafe or unparseable assets leave a neutral IATA tile at the same size; no invented airline logo is substituted. Duffel's fictional ZZ sandbox mark is explicitly excluded.

An IATA code alone cannot distinguish every historical reassignment or shared brand. Existing bundled identities take precedence. No logo lookup changes the airline name, collection denominator, travel history or parser results.
