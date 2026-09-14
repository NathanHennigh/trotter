# Dreams postcards and background locations

The country list uses landscape photographic postcard fronts, cream paper edges, printed destination lettering and a narrow margin for actual saved-place counts. Existing natural country photography and reel-cover fallback are preserved. Tapping still performs a short turn before opening the country; reduced motion opens immediately. No decorative stamp, fictional address or extra flip control was added.

Named saved places can be located asynchronously. Country maps offer **Find locations**, show progress, and plot results as they arrive. **Saved place** shows the actual address, a map and an external Maps link. Ambiguous matches offer the returned addresses for explicit selection; unknown places remain saved and editable. Both Maps and Geoapify/OpenStreetMap attribution links open externally.

The mobile service polls queued/running location work without overlapping requests, batches large country requests, isolates accounts, preserves saves on failures, and blocks duplicate writes. An unchanged automatically generated Maps URL is never submitted as a manual pin. Entering Edit reads the latest item, while active drafts survive later background updates.

## Verification

- TypeScript checks pass.
- Existing World Window aggregate passes; the final editor regression also passes. The aggregate now includes postcard opening/reduced-motion/duplicate-tap tests and location queue, candidate confirmation, batching, failure and account-switch tests.
- Eight postcard and 28 location UI projections cover 320/420-pixel widths and normal/enlarged text. Full candidate names, addresses and actions fit; the real bundled map runtime renders the correct pin, category icon, attribution and selection message.
- Backend: 318 isolated regression tests covering Dreams, durable lookup, provider matching, migration preservation, auth, booking/import and inbox behavior.
- Three bounded public-place provider checks verified real provider responses. The Louvre and Marina Bay Sands resolved; the British Museum exposed a Greater London alias, now covered by a country-scoped normalization regression.

Offline visual evidence is under `artifacts/postcard-fronts-20260914` and `artifacts/dream-location-ui-20260914`. Map tiles were intentionally blocked for offline layout tests; those tests verify saved pins and the error fallback rather than online tile imagery. Native device testing is pending reconnection of the phone.

Backend operations, status semantics and authenticated endpoint contracts are documented in [background locations](../backend/DREAM_LOCATIONS.md). New provider work uses the dedicated `dream_locations` queue, preserving the default flight-import worker.

## Android artifact

Final mobile/backend implementation commit: `430c66c697c4` (with the postcard/UI commit `3e5fc29` preceding it).

WSL built `C:/Users/natha/Documents/builds/trotter-preview-430c66c697c4-dev-2026-09-14_19-06-42Z.apk`. SHA-256: `8799654e2446e71b18a3503e7658905d3483d23509500cc14ec9f7d686b90c26`.

APK ZIP integrity, existing signing certificate, four ABIs, bundled Newsreader italic, production API origin, and new location endpoint strings are verified. Gradle assembly and Expo Doctor passed. Windows and WSL ADB both list no connected phone; this artifact has not been installed or physically tested.

## Oracle rollout

Migration 0010 was rehearsed against a restored PostgreSQL 16.15 backup, then applied to production. All 16 original data tables retained identical row hashes and schemas, including after background processing. The API, existing flight worker, dedicated location worker and single scheduler were verified; web, database, Redis and tunnel container identities stayed unchanged.

The existing provider account was moved into protected server configuration for this worker. No key was added to the app or new source files. The final pre-migration backup is `/home/ubuntu/trotter/deploy/backups/trotter-2026-09-14_19-13-07Z.dump`, SHA-256 `32f0560c541f35edad3c20fae8ed45e0ddaede847ed7baa006907af441a35d89`.

The initial background pass checked four named saves and returned four `not_found` results, with no blocked/failed jobs and no invented pins. The fifth save is unnamed and remains unchanged. Real provider coverage for these particular saves is a limitation: a working job is not evidence that a place has been matched. Search links and manual editing remain available.

Final backend deployment is `ba85e62d0c12702d71ca31a0b5784b58274770fa`. Its read-only response fallback provides an encoded Google Maps text search for a named place without an existing link. Existing and resolved URLs take precedence; search links never become coordinates. All four named saves across the server now expose Maps links, while their location results remain `not_found`. This server-wide count spans two accounts and is not a single user's count.

The fallback's 135 focused backend tests passed. Internal and external readiness, authenticated endpoints, both worker queues, and the single scheduler passed after deployment. A full comparison including the new location table confirmed no data or schema changes during this final rollout. The original and pre-fallback rollback images are retained. This backend-only follow-up does not require rebuilding the Android artifact above.
