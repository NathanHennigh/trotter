# Flight import release — 2026-10-31

Runtime source: `3260146`, parser 28, pushed to `codex/flight-import-upgrade`.
Previous runtime: `5349b74`, parser 26.
Image: `trotter-backend:flight-import-3260146`, SHA256 `908f6d19154a79b51f90cd8ad7217907032c48b878eb67902e3eef5bb8a8ecac`.
The production `trotter-backend:local` tag points to that exact image.

## Release scope

This deploys the controlled replay hardening and consistent middle-name matching described in the shadow-audit report. There are no dependency, API-contract, or schema changes. Migration head remains `0024_controlled_flight_import`. The installed Android build 5 already contains the current client and reconnect fixes, so no new APK was required. Existing iOS clients can use the backend improvements without a new TestFlight release.

Deployment does not apply the offline historical correction proposal or change account travel-name aliases. Historical repairs still require a current, reviewed preview. No full-mailbox replay or live Gmail scan was triggered for this release.

## Safeguards and verification

- Built the exact committed backend in a separate release directory. Verified all 88 application files against the committed manifests; only the 13 changed application files were copied into the existing server checkout after its previous source was verified.
- Preserved the original source and deployment configuration. Retained `trotter-backend:rollback-pre-3260146`, pointing to the previous application image.
- Created PostgreSQL backups before QA and immediately before switching images. Verified archive listings and checksums. The rollout backup is `trotter-2026-10-31_21-31-30Z.dump` in the server's private backup directory.
- Restored the earlier backup into an isolated PostgreSQL/PostGIS container. Candidate schema checks passed. Synthetic checks exercised exact full-middle-name ownership, original flight-ID preservation, normalized clocks, repeated evidence stability, account separation, manual decisions, cancellations, other passengers, PostGIS geometry, and date-proof preservation. All synthetic rows rolled back. The temporary database and its isolated network were removed after verification.
- The prior local backend regression suite passed 2,655 tests with four existing skips; the final retention safeguards passed 169 affected checks and 301 focused identity checks, as recorded in the shadow-audit report.
- Paused workers and the scheduler during the switch, then held the history worker and scheduler until the API and existing records passed verification. All table row counts and content digests were unchanged across the deployment check, including all 11 explicitly protected account, itinerary, booking-evidence, sharing, and recovery tables.
- All six backend containers—API, normal worker, history worker, Dreams worker, location worker, and scheduler—run the identical image and report parser 28. No startup error lines or restarts were observed during final verification.
- Non-importing Celery canaries passed on all four queues. The public `/ready` endpoint returned HTTP 200 with PostgreSQL and Redis ready. All 15 currently normalized flight records retained correct airport-local API clocks.
- Resumed the scheduler and history worker with the existing history allowlist unchanged. No broadening of historical discovery or change to processing limits occurred.

The public readiness probe uses curl. A default Python-urllib user agent received an edge HTTP 403; the same URL returned HTTP 200 with curl. No edge-security settings were changed.

Private deployment manifests, before/after digests, source backups, checks, and logs remain under `/home/ubuntu/trotter-flight-import-private-20261031`. They contain no replacement authority for historical corrections. Application rollback preserves the current additive schema; a whole-database restore must not overwrite subsequent user activity.
