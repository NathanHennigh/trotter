# No-loss verification follow-up

Subsequent local work addressing the inherited Philippines/Washington defects
below is documented in [Flight-leg reconciliation](flight-leg-reconciliation-2026-11-01.md).
The results here remain the earlier carrier-recovery baseline.

This follow-up tests the recovery against the current working implementation and audits original-to-baseline changes rather than treating unchanged baseline behavior as proof that every historical itinerary is correct. All account work uses private captured originals and disposable copies. Production remains unchanged.

## Bugs found and fixed

**Partial evidence retention.** A failed extraction after ordinary parsing had replaced `Message.parse_evidence` could erase the only structured partial-flight annotation. Disabling the feature before reprocessing had the same effect. All normal outcome-replacement paths now retain distinct prior partial facts as historical supporting evidence. A successful fresh extraction becomes current and deduplicates identical history. Historical facts cannot resolve a message, establish ownership or create a flight. Worker regressions and both actual eTravel originals cover failed extraction, no result, disabled features, successful retry and repeat.

**Redundant temporary trips.** Replaying an already-linked carrier-recovered single leg could create and immediately remove an empty trip before refreshing its existing segment. This appended six or seven needless history rows in the exact-source fixtures. A narrowly scoped helper now reuses the trip of the existing same-account, same-booking, same-dated-leg original-linked segment. Ledger protections, normal segment updates, metadata merges, audit snapshots and reclustering still run. Generic imports, different sources/observations, ambiguous matches and multi-leg groups keep their existing paths. Genuine later schedule changes still apply; older notices cannot roll them back.

## Frozen V7 focused results

Recovery service SHA-256: `3e0809a79dedc6c197048f72fdfffd89d20a95ff623f0d2c9e34b59533ca0f0b`. The frozen source manifest covers 317 files.

Using Elisha's original account snapshot and actual emails, both chronological and reverse source orders recover exactly the same three supported flights with the latest clocks: **15 → 18 flights and 8 → 10 trips**. All 15 original flights and all eight original trips retain every stored field. All other original table rows survive. The two incomplete registrations remain supporting facts without invented segments. Original database and source hashes remain unchanged, and network access is blocked.

The chronological repeat changes no non-message table. The reverse repeat adds one legitimate complete `before_booking_import` snapshot of the final existing AA163 record, without changing that record. The following pass changes **no table at all**, including messages and history. No temporary-trip history churn remains. Six frozen-V7 actual-worker checks on the two eTravel sources pass across disabled/failed/no-result extraction and retry scenarios.

Independent synthetic tests cover mismatched accounts, booking references, routes, dates, flight numbers, original observations and sources; feature-off and multi-flight cases; real schedule updates; cancellations and manual holds. These are retained in `tests/test_carrier_projection_trip.py`, alongside the extended worker and recovery suites.

## What “no loss” does and does not establish for Nathan

The stronger audit reviewed all eight flight removals proposed by the existing parser, not just the new candidate's differences:

- Six tickets explicitly name other passengers. Their original observations remain linked to retained Flights for others evidence.
- Two flights match an explicit cancellation.
- All 155 surviving original segments remain. The 65 changed surviving rows were inventoried: 57 clock pairs preserve the original local values while correcting UTC conversion; three actual schedule/date changes and two flight-number corrections match saved original notices/receipts. Categories overlap.

No valid Nathan flight was lost among those eight removals. The new recovery feature produces no additional material Nathan flight/trip changes relative to the baseline. This does **not** mean every inherited record is already correct.

### Broad historical replay is not ready to apply

The original-source audit found three existing itinerary problems:

1. A Philippines return is separated from its outbound and grouped with later Chicago flights.
2. A stale BR51 outbound has the wrong date/destination even though the correct parsed observation is retained. The connection date also needs source-aware reconciliation across the overnight arrival.
3. A stale Washington return remains alongside the correctly restored later return.

These defects are present in the baseline, not introduced by the carrier recovery. A separate private repair proposal identifies the exact supporting ticket evidence and limits changes to the affected itinerary. It requires a fresh copied-data preview, explicit source lineage, protection of manual decisions and independent before/after validation. There is no blanket deletion by flight number and no broad production backfill in this work.

## Safe-disable check

On a disposable copy of Elisha's completed 18-flight/10-trip account, all eight affected operational originals were replayed twice through the real worker with both flags disabled. Full flights, trips, immutable evidence, cancellations, retained tickets, assignments and shares remained unchanged. Forced reprocessing returned those email review states to unresolved and removed current carrier markers; retained typed evidence and the active flights remained. Disabling the feature preserves flights, but does not promise that forced-reparse review statuses stay accepted.

## Final whole-history preservation results

The frozen V7 backend suite passed **2,992 tests**, with four existing skips. As in V6, external standalone PostgreSQL/PostGIS, Celery, migration-apply and seed smoke files were excluded from this suite; the earlier V6 PostgreSQL schema/transaction checks remain separately documented. V7 adds no schema changes.

A fresh normal third history pass ran on disposable exports of both completed V6 account copies, using the frozen V7 importer, original captured sources and original attachment handling. Parsing was not forced; no guard injected preservation or skipped an intended correction. Input restoration was verified, both feature flags were explicitly enabled, and all external network access was blocked.

| Account | Available message IDs checked | Flights before → after | Trips before → after | Result |
| --- | ---: | ---: | ---: | --- |
| Elisha | 11,537 | 18 → 18 | 10 → 10 | Pass |
| Nathan | 12,546 | 162 → 162 | 68 → 68 | Pass |

For both accounts, **every captured table remained exactly unchanged except the discovery state's `updated_at` scan timestamp**. This includes full segment rows and metadata, trip rows, messages, original observations, cancellations, itinerary history, typed carrier evidence, retained tickets, assignments, shares and manual decisions. There were no added or removed evidence/history rows and no new duplicate flights. Nathan's two previously unavailable indexed originals remain explicitly accounted for; the test does not claim to reread missing emails.

Normal skip logic fetched 540 emails for Elisha (542 preparations including attachments) and 659 for Nathan (687 preparations). The local runs took 210.887 and 297.953 seconds while tests ran concurrently; those wall times are not a controlled production-speed measurement. No network call was attempted.

All 317 working source/test/configuration files still match the final frozen manifest. Source captures, exported input snapshots, and the original completed V6 databases retain their hashes. The original account databases were not modified.

**Decision:** the new recovery and retention changes pass the no-loss checks. The broader historical replay remains **not cleared for production application**, because of the inherited Philippines/Washington defects above. Neither code nor account-data corrections were pushed or deployed by this follow-up.

Private final artifacts under `artifacts/booking-enrichment-20261031/` include `followup-no-loss/{nathan,elisha}-v7-report.json`, `positive-focused-v7/`, `backend-tests-v7.log`, `actual-partial-retention-v7.log`, `elisha-disable-existing-v6-3/report.json`, and `nathan-original-removals-adjudication-20261031.json`. The private originals, captures and detailed audits remain ignored by Git.
