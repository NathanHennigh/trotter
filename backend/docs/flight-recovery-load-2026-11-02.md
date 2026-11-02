# Flight recovery concurrency rehearsal — 2026-11-02

All eight local PostgreSQL workloads passed their preservation and isolation checks. Enabling the four account-gated recovery features increased batch processing wall time by approximately **8.5–12.8%** for this workload. This measures importer/database processing, not end-to-end Gmail scan duration or production capacity.

## Method

- Windows Python 3.13 client, existing local WSL PostgreSQL 16.15, a fresh disposable database migrated to the current Alembic head. No production database or mailbox was accessed. The dedicated QA cluster was stopped and its shutdown verified afterward.
- Actual `parse_email` parsed the five anonymized receipts/notices in `tests/fixtures/orlando-bookings.json` once before timing. Individual fixture parsing took 86–340 ms. Timed work used the resulting parsed objects with actual `apply_booking_message`, builder/ledger, `set_message_outcome`, commits, and PostgreSQL account advisory locks. Weather/provider enrichment was disabled.
- Each account began with 20 or 200 historical flights in unrelated journeys. Ten or 25 threads began together, one account per thread. Each applied the five messages twice: initial import followed by repeat processing. Identical booking identifiers across accounts exercised account isolation.
- OFF and ON runs used equivalent fresh synthetic data. ON set all four master switches and an explicit `FLIGHT_IMPORT_RECOVERY_USER_IDS` list containing only that run's synthetic users. The harness asserted that listed users were enabled and an unlisted user was disabled. Pair order alternated OFF/ON and ON/OFF.
- Database seeding, connection-pool prewarming, and fixture parsing were excluded from timing. Per-message time includes import, message outcome, and commit. Batch wall time also includes account-state assertions between passes. SQL counts include importer queries and lock acquisition/release; assertion queries are excluded.

## Measurements

Per-message latency is in milliseconds. Each row is one run; percentiles combine initial and repeat processing. The private result JSON also records those phases separately, process CPU time, client SQL round-trip totals, and sampled PostgreSQL activity.

| Concurrent accounts | Existing flights/account | Features | Message applications | Batch wall, s | p50, ms | p95, ms | Max, ms | SQL queries |
|---:|---:|:---:|---:|---:|---:|---:|---:|---:|
| 10 | 20 | OFF | 100 | 4.281 | 355.639 | 673.063 | 760.441 | 4,320 |
| 10 | 20 | ON | 100 | 4.669 | 381.245 | 798.860 | 909.928 | 4,880 |
| 25 | 20 | OFF | 250 | 10.249 | 855.881 | 1,492.665 | 1,851.858 | 10,800 |
| 25 | 20 | ON | 250 | 11.566 | 931.772 | 1,888.582 | 2,207.260 | 12,200 |
| 10 | 200 | OFF | 100 | 6.018 | 535.445 | 904.215 | 995.889 | 4,320 |
| 10 | 200 | ON | 100 | 6.528 | 529.314 | 1,081.239 | 1,133.406 | 4,880 |
| 25 | 200 | OFF | 250 | 16.259 | 1,345.093 | 2,356.259 | 2,617.892 | 10,800 |
| 25 | 200 | ON | 250 | 17.943 | 1,506.549 | 2,948.541 | 3,125.723 | 12,200 |

Paired batch wall-time changes were +9.1%, +12.8%, +8.5%, and +10.4%, respectively. Per-message p95 increased 18.7–26.5%; SQL query count increased 13.0%. The additional processing cost is measurable and should be monitored during the limited account rollout. Sampled active queries peaked at four; retained pool connections peaked at 51. These samples do not measure queue depth or establish a saturation point.

## Safety results

- **1,400 message applications across 140 synthetic account runs.** All **15,400 pre-existing flight rows** and **7,700 pre-existing trip rows** retained every compared field exactly.
- Every account ended with exactly the expected four new active flights in one journey. Reprocessing did not duplicate flights or change their facts, trip membership, ownership evidence, cancellations, retained bookings, or sharing state. Corresponding ON/OFF runs produced identical normalized flight schedules. No cross-account contamination was detected.
- Per-message mutation counters can change on replay. The old anonymous receipt also correctly changes from an identity hold to a resolved cancellation-blocked outcome after its later cancellation has been processed. The harness explicitly bounds this expected transition; active flights remain unchanged.
- Four overlapping attempts while the same account lock was held were rejected without writes. A separate interruption after real importer SQL changes but before commit rolled back to the exact prior account state. Explicit retry and a second replay produced no duplicate or lost flights. This tests transaction/retry safety, not Celery's retry scheduling.
- All six monitored importer/builder/recovery/rollout source hashes remained unchanged during the measured run.

## Interpretation and evidence

This is a bounded, single paired pass on a developer machine, using one known deterministic receipt/cancellation/passenger mix. Python thread contention, the local Windows-to-WSL database connection, and warm caches affect the results. It is not an exhaustive carrier-corroboration workload, sustained soak test, production hardware benchmark, or statistical capacity estimate. Gmail retrieval, AI calls, external providers, Celery queue waiting, and end-to-end scan time were not measured. Client SQL round-trip totals include driver/network overhead and concurrent waiting; they are not pure PostgreSQL execution time.

Private local evidence is retained under `artifacts/production-readiness-20261102/`: `concurrent-import-result.json`, `concurrent-import.log`, `pg_import_load.py`, and `postgres-cluster.json`. The harness validates the uniquely named disposable local database before truncating its synthetic seed data; it must never be redirected to a live database. This document contains no personal flight identifiers or credentials.
