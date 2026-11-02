# Controlled flight recovery release — 2026-11-02

Runtime source: `94bd718` on `codex/flight-replay-hardening`.
Image: `trotter-backend:readiness-94bd718`, SHA256
`7192f27e312c74e4b37103a6ec83bd3a2c952b1c6ed2657047b08c2e729da171`.
All six backend services use this image. Parser revision remains 28; no forced
full-history replay or parser-version bump was introduced. Schema head is
`0025_carrier_travel_evidence` (additive table and indexes).

## Scope and verification

- All four optional recovery switches are enabled only for account IDs 1 and 9.
  Empty/malformed cohorts fail closed. The existing Gmail history-discovery
  enrollment and processing limits were preserved.
- The complete backend suite passed 3,216 tests with four existing skips. The
  final scan-health CLI passed another 15 focused tests, including read-only
  transactions and suppression of private values in unexpected failures.
- Paired local PostgreSQL load tests covered 1,400 message applications with
  10 and 25 concurrent accounts and 20/200 pre-existing flights per account.
  All 15,400 original flights and 7,700 trips were preserved; no duplicates or
  cross-account changes appeared. Lock contention, interruption rollback, and
  retry checks passed. See `flight-recovery-load-2026-11-02.md` for measured
  overhead and limits; these are not production-capacity measurements.
- Verified the previous runtime's 113 source files against release `3260146`.
  Built committed source separately, replaced only 20 verified source paths,
  and patched only the five recovery environment mappings in live Compose.
- Restored a fresh production backup to an isolated PostgreSQL/PostGIS database.
  Migration and original-source rehearsal passed their preservation/repeat checks.
  The broad historical sample was diagnostic: its deliberately strict no-removal
  guard stopped after identifying eight removals. Independent original-source
  review classified six as other travelers and two as explicitly canceled,
  with all originals retained; seven personal replacement/missing flights were
  added in that copy. That broad historical sample was not applied live.
- Gracefully drained services, took another verified backup, and compared
  consistent read-only fingerprints before/after the image/schema switch.
  Every pre-existing modeled application table was unchanged. Migration metadata
  and PostGIS system tables were excluded from application fingerprints.
- All 122 final runtime source files match committed `94bd718` after newline
  normalization. API/database/Redis readiness passed locally and publicly.
  All four worker queue canaries passed; no backend restarts or error/traceback
  lines appeared during verification.

## Live canaries and targeted recovery

| Account / operation | Messages checked | Added flights | Recorded span |
| --- | ---: | ---: | ---: |
| 1 — bounded recent scan | 36 | 0 | 6.084 seconds |
| 9 — bounded recent scan | 19 | 0 | 6.063 seconds |
| 9 — 14 reviewed original messages, exact reprocess | 14 | 3 | 13.382 seconds |

All three jobs completed without errors. Recorded spans are persisted job times,
not a controlled end-to-end performance comparison.

Account 9 now has 18 flights across 10 trips, with the three required source-backed
recoveries verified exactly once (AA172, AA163, SY739). All original flight IDs,
immutable observations/cancellations/history/retained-ticket evidence, user rows,
assignments, and shares were preserved. Every other account's complete itinerary
was unchanged. Account 1 remains at its live baseline of 163 flights / 65 trips;
the historical manual repair proposal was not applied in this rollout.

Two partial Philippine arrival/departure notices remain retained evidence rather
than fabricated complete flights. This release does not claim every historical
email contains enough information to create a full flight.

## Operations and rollback

The read-only scan-health CLI is included in the production image. Final reporting
showed three completed canaries, no new failed/running jobs, and one unchanged
historical pending row from May 11. That old SQL row is flagged for investigation;
it is not evidence of current broker backlog and was not silently rewritten.

Pre-release backups were verified by archive listing and checksum and copied
off the VM. The immediate rollout backup is
`trotter-2026-11-02_17-13-46Z.dump`, SHA256
`c6cbbad513512dabbe87c5647a30088423b66726910815087ace11aa1d012a76`.
Rollback image: `trotter-backend:rollback-pre-readiness-20261102`.
Prior configuration and changed source files, manifests, fingerprints, private
rehearsal details, and canary results are retained in the VM's private release
directory. The isolated rehearsal database/network and local QA PostgreSQL
cluster were removed/stopped after testing.

Disable the recovery cohort/switches and restore the prior compatible runtime
and configuration if needed. Retain the additive schema and evidence; never
restore a whole database over subsequent user activity. Application rollback
does not automatically undo already recovered flights. No mobile update is
required for this backend-compatible release.
