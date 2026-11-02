# Carrier travel corroboration: preproduction validation

This is the V6 validation record. The stronger follow-up in [No-loss verification](no-loss-followup-2026-11-01.md) found and fixed partial-evidence retention and redundant temporary-trip history issues in V7. It also found inherited Nathan itinerary defects, so a broad historical replay is not cleared for production merely because V6 matched the baseline.

This follow-up addresses the missing-flight outcome that the earlier strict-enrichment build did not achieve. The earlier V3 backtest preserved behavior but recovered none of Elisha's three supported missing legs. Its preservation result was not completion of the recovery task.

## Required outcome

Recover these complete original legs from Elisha's own captured emails, with the latest supported schedule:

| Flight | Local departure date | Route | Latest local schedule |
| --- | --- | --- | --- |
| AA172 | August 16, 2025 | MIA → TQO | 10:14 → 11:34 |
| AA163 | August 23, 2025 | TQO → DFW | 16:04 → 19:09 |
| SY739 | June 19, 2026 | DFW → PUJ | 10:00 → 15:30 |

The expected positive result is 15 → 18 flights and 8 → 10 trips, preserving the original flights and their trip memberships. The two additional journeys contain the newly recovered Tulum and Punta Cana legs. No repair manifest or manually injected ownership decision is used.

The two Philippine eTravel registrations are a separate partial-evidence case. They state BR277 arriving at MNL on April 27, 2025, and BR272 departing MNL on May 9, 2025. They do not provide complete opposite airports and flight times. Preserve those explicit facts and the missing-field list without creating flight segments or modifying the existing BR51 IAH → TPE flight.

## Authority and scope

The original parser still supplies the complete operational flight facts. A new, separate immutable store retains narrowly recognized carrier assertions. Gmail-added aligned DKIM/DMARC authentication, exact supported sender/template, account recipient, original content hash and current source revision are required. Surveys alone never create flights or become passenger-manifest evidence.

For Sun Country, a full-name personal notice must match an independent dated post-travel city-route assertion. For American, the policy combines an explicit connecting notice, a dated post-travel journey assertion, and a separately addressed return check-in containing a known complete given-name sequence under the same booking. This is conservative corroboration, not certainty equivalent to a named passenger ticket. Unknown original observations remain unknown; the derived decision records its supporting evidence IDs separately.

Current conflicting travelers, competing bookings, unresolved cancellations, manual decisions, assignments and active shares prevent additional recovery. The existing verified path remains unchanged. Queries are account/date/booking scoped with overflow rejection, and only affected held observations are reconsidered when new support arrives. No AI or schedule provider is called, and no broad Gmail search or parser-version bump is introduced. Previously ignored supported survey templates are reread once; successfully examined support is then skipped on repeat scans.

The eTravel extractor preserves stated fields only. It does not treat a journey country as a specific leg endpoint, complete a missing surname, or retain registration/QR tokens.

## Release boundary

All validation uses disposable local databases and captured originals. Production data and deployed code remain unchanged. Both `BOOKING_STRICT_ENRICHMENT_ENABLED` and `CARRIER_TRAVEL_CORROBORATION_ENABLED` default to false. Migration 0025 is additive. Enabling a flag later is not a historical backfill, and disabling it does not undo already imported flights.

## Frozen validation

Final candidate: V6. Both flags are explicitly enabled in the offline harness. The recovery service hash is `6ef3a54a151b4a1d0581bfd93e451881d00894d5f04a4ddfd17596a5e1abf9c6`; application/dependency manifests and private input fingerprints accompany each run. The real importer, normal evidence gate, original documents, trip builder and local enrichment are exercised. External network calls are blocked.

- Backend suite against the frozen V6 source: **2,960 passed, four existing skips**. External standalone PostgreSQL/PostGIS, Celery, migration-apply and seed smoke files were excluded from that suite; separate PostgreSQL checks below cover the new database work.
- The independent review found and reproduced two ownership gaps before the final freeze: a competing original booking outside the typed-template index, and a contradictory same-journey survey. Both are now regression tests and both fail closed. The earlier V4/V5 interrupted inbox runs are not final acceptance evidence.
- Private exact-source positive tests recover exactly three flights, preserve original flights, use the latest supported schedules, work in both source arrival orders, and remain stable on repeat.

### PostgreSQL staging

An isolated PostgreSQL 16.15/PostGIS cluster used synthetic data only and was stopped after testing. Migration `0024 → 0025 → 0024 → 0025` preserves all 37 original tables and five seeded existing rows. The only additions are the typed-evidence table/indexes and `booking_observations(user_id, travel_date)` index. Downgrade was checked with new evidence present.

Three synthetic flight recoveries pass in both source orders, including hash validation after commit/reload, repeat stability, uniqueness, foreign keys and account isolation. Thirteen competing-booking/conflicting-survey cases and five actual-worker cases pass on PostgreSQL. The worker cases include default-off behavior, partial-evidence holds, once-only survey examination, rollback/retry and the existing same-account advisory lock. An overlapping ordinary job still reports “already running”; this work does not add automatic retry UX for that pre-existing behavior.

With 5,000 synthetic observations for one account, the new date index reduced a competing-route query from scanning 5,036 rows to a scoped index lookup. Warm local samples were 0.012 ms for the route check, 0.064 ms for survey reconciliation and 0.028 ms for booking reconciliation. These are query-plan checks, not production scan-latency measurements.

Production `SHOW timezone` was checked read-only and returned `Etc/UTC`. The existing ledger represents source-event timestamps as naive UTC; a non-UTC PostgreSQL session causes evidence hashes to fail closed. Staging explicitly uses UTC. This work does not attempt a broad legacy timestamp migration.

### Elisha: complete account replay

Both passes processed all **11,537 captured original emails**. Independent outcome adjudication passed **33/33 checks**. The result is exactly the three flights above and two new journeys: **18 flights / 10 trips**. All 15 original flight IDs, full provenance, eight original trips and their memberships remain unchanged. There are no duplicate legs, removed records, changes to aliases, manual decisions, shares or assignments, or unexplained review regressions.

Thirteen carrier-evidence rows and every current source/projection reference validate and remain exactly stable on repeat. The two Philippine registrations retain structured partial facts and remain review-only. Eight operational messages resolve their identity hold; three already accepted/ignored surveys change only their explanatory reason to retained carrier support. The strict identical-result comparator correctly flags the intended additions and these eleven status/reason changes; it is not misrepresented as an unchanged-results pass.

Initial per-message audit entries can show the earlier unsuccessful lookup before supporting evidence arrived. Successful deferred resolution is separately recorded in message recovery metadata and the derived segment's carrier-evidence IDs. Instrumentation records 209 carrier evaluations, 106 allowed, taking 2.064 seconds cumulatively; those repeated evaluations produce **three flights**, not 106. Strict enrichment ran 61 times, none allowed, taking 0.411 seconds. No network call was attempted, and frozen source/input hashes remained unchanged.

Offline pass times were 429.266 and 217.477 seconds. The baseline and candidate had identical fetch counts (11,537 then 548) and preparation counts (11,539 then 550, including document re-extraction). Those counts show no added Gmail fetch work in this historical workload; wall times ran under different concurrent loads and do not establish a production speedup.

### Nathan: complete available-history replay

Both passes replayed all **12,546 available original emails**. Two other indexed originals were already unavailable/404 and classified as deleted marketing messages; they were accounted for, not fabricated or claimed as reread. The final **162 flights / 68 trips** exactly match the baseline: no candidate-specific additions, removals, material flight changes, trip changes, or ownership promotions. Orlando, all nine Bilt manual ownership decisions, cancellations, sharing, assignments and retained-ticket evidence remain unchanged.

The independent adjudication passes with two explicit message exceptions. An unnamed AA0163 notice becomes accepted through direct, current named AA163 evidence for an existing flight; only its source provenance/confidence grows. A survey addressed to Elisha in Nathan's inbox remains accepted/ignored but is retained as carrier support, without becoming his travel. The raw unchanged-results comparator deliberately remains false for these two explained message differences. There are nine carrier-evidence rows, valid and stable, and zero carrier promotions or derived carrier links. All 1,903 baseline semantic history snapshots survive, with five additional explained audit snapshots. A partial eTravel extraction remains inert metadata, not a flight.

Material results, original immutable evidence, retained tickets and user decisions are stable on repeat. Strict enrichment ran 854 times (one allowed) in 2.196 cumulative seconds; carrier evaluation ran 880 times (none allowed) in 0.481 seconds. Zero network calls were attempted. Both passes have the same fetch/preparation counts as baseline: 12,546/12,574, then 674/702. Offline durations were 650.222 and 302.015 seconds; concurrency differed from the earlier baseline run, so these durations are not a speedup claim.

The original captured account starts at 163 flights / 65 trips. The current baseline parser already proposes seven additions and eight removals (six other-passenger records and two canceled flights), yielding 162 / 68. V6 matches those inherited corrections exactly. This build does not apply that historical proposal to Nathan's live account; “no new losses” refers to candidate versus baseline, not to ignoring those pre-existing differences from the captured account.

### Isolated lookup cost and limits

After all replays and backend tests finished, eight alternating warmed rounds compared the existing lookup with the combined fallback on read-only copies. Database/source hashes and decisions stayed unchanged; no network was attempted.

| Account workload | Restorable unknown observations | Existing verified bypasses | Median extra time per workload lookup |
| --- | ---: | ---: | ---: |
| Nathan | 234 | 69 | 5.72 ms |
| Elisha | 18 | 2 | 16.17 ms |

These deliberately concentrated local SQLite workloads exclude incomplete/non-restorable observations, parsing, evidence extraction/persistence, source-triggered reconciliation, Gmail latency and production contention. They are not a prediction for every scanned email. The complete real-history replays separately verified unchanged fetch counts, and PostgreSQL query-plan checks verified indexed scope. No claim of zero overhead or universal accuracy is made.

The upgrade is template-specific and conservative. It does not recover incomplete Manila legs, unsupported carrier formats, conflicting travelers, or evidence beyond the bounded policy. It preserves those originals for later evidence rather than inventing a schedule or discarding tickets. The two feature flags are process-wide, not per-account rollout controls; a later production rollout/backfill must use fresh account state and a controlled execution plan.

All 316 frozen source/test/configuration files match the working implementation after validation. Captured emails, account snapshots, booking references and detailed diffs remain ignored private artifacts. Private final references are the V6 replay reports, Elisha's `candidate-v6-independent-adjudication.json`, Nathan's `nathan-v6-adjudication.json`, `postgres-qa/final-v6-summary.json`, and the two V6 lookup reports under `artifacts/booking-enrichment-20261031/`. No production code, schema, flights or trips were changed.
