# Flight import release — 2026-10-30

Runtime source: `5349b74` on `codex/flight-import-upgrade`.
Pre-change source snapshot: `e58c9f3` (80 application Python files matched the deployed image).
Database migration: `0024_controlled_flight_import`, adding checkpoint and repair-manifest tables only.

## Verification

- Full offline backend suite: 2,281 passed, four existing skips. Four external-service smoke files were excluded from that run. PostgreSQL/PostGIS migration and repair checks and a live Celery/Gmail canary were run separately; the standalone seed and example-task smoke tests were not run.
- Final scheduler eligibility follow-up: 32 focused tests passed.
- Final recent/history contention follow-up: 36 focused tests passed, including the actual account lock, history task, and importer together.
- Same 66-case parser corpus, three rounds each: baseline 38.282 seconds; candidate 36.991 seconds, zero exceptions. No extracted flights disappeared. Three incomplete boarding-link fixtures now hold inconsistent invented arrival times instead of accepting them as reliable facts.
- Local timezone conversion: 3,000 warm calls, median 0.008 ms; no network access.
- Isolated PostgreSQL repair: exact preview/apply agreement, all original segment IDs and evidence preserved, repeat apply unchanged, second preview zero additions/corrections.
- Migration downgrade/upgrade round trip preserved existing account, itinerary, and evidence tables. PostGIS remained available.
- The compatibility rollback image correctly serialized every normalized flight in the PostgreSQL clone with airport-local clocks.
- PostgreSQL advisory-lock contention test verified graceful history deferral with checkpoints and retry counts unchanged.

## Production rollout

The database backup was verified by checksum and archive listing before completing rollout. Application rollback images were retained, including the prior importer with the local-clock API compatibility fix.

Production repair preview exactly matched the isolated PostgreSQL preview. Existing flight IDs, original evidence, cancellations, and shares were preserved. The remaining accounts' flight count and complete segment-record digest were unchanged. Repeated apply and a fresh preview confirmed idempotence. The API clock check and database/Redis readiness checks passed.

One recent-mail canary checked 17 messages in 4.14 seconds, completing without errors. This is a live observation, not a comparison against an equivalent earlier live Gmail scan. Historical catch-up runs separately for the initial account only; two successful batches had checked 100 messages with no current error when rollout verification finished. Full historical coverage remains in progress.

All backend services run `trotter-backend:flight-import-5349b74` (image SHA256 `ca7d9fd8e5110a4dcdc3e6f76c3bb03bd96d3edc6b130ea868e6cf572211c723`). Normal recent scans do not bulk-reparse historical messages after the parser revision change. Widen the history allowlist only after reviewing progress and user-visible scan latency.

Raw source messages, PDFs, repair manifests, and account snapshots remain in private ignored artifacts, not in this repository.
