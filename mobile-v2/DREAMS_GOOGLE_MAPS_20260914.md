# Dreams Google Maps rollout — 14 September 2026

Dreams country and place views now use native Google Maps with World Window map
colors, category pins, count clusters, an exact-overlap chooser, manual placement,
and a camera that respects the user's pan. The first located place fits once.
Globe and trip maps keep their existing rendering.

Google Places lookup remains asynchronous on Oracle. Search uses at most two
requests and conservative matching; ambiguous names, local-script geography and
compatible venue categories yield review choices instead of invented pins.
Confirmed choices retain the Google Place ID. Names and addresses are fetched
only for the open detail view; coordinates expire in a dedicated memory-only
Redis cache. Saved captions, notes, board membership and manual pins remain
independent of provider content.

The Google project uses the existing billing account approved by the user. Server
and Android keys have separate API/application restrictions and are excluded from
Git. The server key is absent from every APK entry. Older clients receive safe
Google Maps links without coordinates intended for the new Google map renderer;
the new client advertises `X-Trotter-Maps: google`.

## Verification

- Mobile implementation: `1f03ac2`; backend/cache implementation: `1ad9c80`.
- Mobile regression suite, TypeScript and all 17 Expo Doctor checks passed;
  13 targeted native-map/detail tests plus configuration tests passed.
- Focused backend suite: 342 passed. Broader isolated backend run: 968 passed,
  5 skipped; environment-only PostGIS/Poetry runner files were excluded.
- Independent provider/lifecycle/API review passed, including account isolation,
  stale responses, retryable errors, capability isolation and manual-pin retention.
- Restored PostgreSQL 16.15 migration rehearsal preserved all 18 original tables'
  rows and schema; only the empty Google identity table was added.
- Both requested public businesses returned one valid review candidate in the
  bounded live probes. Neither was automatically marked as user-confirmed.

Standalone Android APK built in WSL and installed with `adb install -r`, preserving
app data. Artifact: `trotter-preview-1f03ac25e711-dev-2026-09-14_21-13-38Z.apk`.
SHA-256: `b780eb2222c654cd2937ed36bcf1efbec6a29257ebac53fd1da1f2eb88dfe624`.
Package/signing certificate match the restricted Google Android key.

Native on-device visual verification remains unverified. USB read/write failures
interrupted the phone inspection after successful installation. An isolated
official ADB 37.0.1 build also failed to establish a stable transport, and Windows
denied an interface-only reset without administrator access. No phone settings or
app data were changed by troubleshooting. Layout projections and native component
tests verify surrounding behavior, not real Google tiles or physical gestures.

## Production outcome

Oracle is running `1ad9c80` with migration `0011_dream_google_identities`.
API readiness, both worker queues and the single scheduler were verified. The
Google cache is healthy with snapshots/AOF disabled, 128 MB maximum memory,
tmpfs storage, and no published ports or persistent volumes. The original
database, task broker, web and tunnel containers were retained.

The owner-scoped retry affected only the two requested saved places. Each now
has one fresh Google review candidate and no automatically confirmed pin. Modern
detail requests returned 200 with no-store; clients without Google map capability
received 409 before any provider call. Authentication remains required.

Final full-row hashes confirmed all original saved-item, flight, trip and other
table rows were unchanged. Only the two intended location-job rows changed, with
their prior histories retained, and two IDs-only Google identity rows were added.
The verified pre-rollout database backup is
`deploy/backups/trotter-2026-09-14_21-27-25Z.dump`, SHA-256
`d97bf5600c77a6d5e97f83195d1c1e9a045efde73c25ca429fa64749492cca46`.
The prior backend image is retained as
`trotter-backend:rollback-before-google-places-20260914`. Code rollback should
retain the additive identity table; do not restore or delete user data to roll
back application code.
