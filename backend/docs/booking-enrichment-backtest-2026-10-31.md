# Conservative booking enrichment: offline validation

This records the earlier V3 preservation-only candidate. It did not recover Elisha's three supported missing flights and was not sufficient to complete that task. See [the carrier-recovery follow-up](carrier-recovery-backtest-2026-11-01.md) for the separate positive recovery work and its validation.

Status: candidate built and both full two-pass mailbox replays completed. One beneficial Nathan message-status change was reviewed against its original passenger evidence; no candidate-specific flight/trip loss or ownership regression was found. Not deployed or approved for production enablement. A PostgreSQL staging check is recommended before rollout.

## Scope

This candidate adds a conservative fallback to the existing exact-booking inheritance mechanism. Existing verified imports and corrections bypass the new evaluator entirely. It does not add an AI evidence-joining service, broad mailbox searches, inferred passenger names, or booking-alias expansion. It does not attempt to turn greetings or post-flight surveys into passenger manifests.

`BOOKING_STRICT_ENRICHMENT_ENABLED` defaults to false. `1` or `true` enables the candidate. No parser-version bump, schema change, dependency change, automatic rescan, or historical repair accompanies this patch. The current production parser remains 28.

The fallback runs only when the existing importer would hold an unnamed original flight notice. It requires the same account, primary booking reference, carrier, airport-local departure date, route, and normalized flight number. The authority must be original, explicit, scoped passenger evidence matching the account's current travel names. Proof and target must have consistent, normalized facts and current original-message metadata. This can reconcile representations such as `UA0123` and `UA123`; a bounded supplement supports either email arrival order without requiring another full scan. Supplemental replay cannot use the older wildcard verifier to bypass the new proof requirements.

Queries return at most 128 rows plus an overflow sentinel; overflow remains unresolved. Stale source revisions, contradictory passenger evidence, ambiguous chronology, cancellations, manual holds, and active sharing remain protected. Synthetic repair/recovery observations cannot prove identity, but continue to protect manual decisions and sharing. Original observations and event times remain unchanged. Existing active rows are not deleted merely because an enrichment attempt is rejected.

Bare `pnr_aliases` are deliberately not used as new authority. Current parsing can collect two unrelated booking codes from one email. A number-only passenger scope must belong to a source with one unambiguous primary reference, including any additional labeled references retained in the source facts.

## Reproducible comparison

The baseline is frozen commit `5db89a7` (runtime parser 28). The candidate's application files are frozen separately, with source manifests before and after each replay. Tests run against the frozen candidate, not an actively edited application tree.

`scripts/replay_booking_backtest.py` restores a private account export into a disposable SQLite database, blocks network connections, and runs the actual history worker through normal message gates twice. It supplies only captured source messages and captured ticket documents. It does not force parsing, add aliases, inject schedule links, or apply repair manifests. The explicit on/off mode, effective flag, actual evaluator calls, decisions and evaluation time are recorded.

`scripts/compare_booking_backtests.py` compares identical baseline/candidate inputs and checks original evidence, flight IDs, itinerary content, passenger identity, trip membership/title/privacy, manual decisions, sharing, message statuses, orphan rows, duplicates and second-pass stability. Any material difference requires review; an additional flight is not automatically a passing result. Detailed reports remain private. Recovered or removed flights already produced by parser 28 are separated from candidate-specific changes.

New retained-ticket rows use random UUIDs. Across separate baseline/candidate databases, the comparator maps only new UUIDs by the existing unique `(user_id, record_key)` identity and validates their evidence links. Original account IDs, assignments, shares and repeat-pass IDs remain exact. Raw UUID differences are retained in the private report. Nathan's 412 fresh UUID differences represent identical logical records; all 29 original retained-ticket rows and all 710 evidence links are preserved.

| Account | Indexed records | Original emails captured | Frozen starting itinerary |
| --- | ---: | ---: | --- |
| Nathan | 12,548 | 12,546 | 163 flights / 65 trips |
| Elisha | 11,537 | 11,537 | 15 flights / 8 trips |

Nathan's two unavailable indexed messages are previously classified deleted marketing messages returning 404. This is complete accounting of the indexed corpus, not a claim to have scanned every message in his much larger mailbox. Elisha's fresh export used one PostgreSQL `REPEATABLE READ READ ONLY` transaction, and every captured source ID was checked against that account snapshot. Her normal bounded ticket extraction used original Gmail attachment metadata. Both accounts retain their actual stored travel-name aliases unchanged.

Private captures, source emails, booking references, documents, and account snapshots are ignored artifacts and must not be committed. Capturing originals for this one-time backtest is separate from the runtime cost of the candidate, which performs no new Gmail or AI requests.

## Validation results

- Final additive candidate backend suite: **2,768 passed, four existing skips**, against the frozen candidate. External PostgreSQL/PostGIS, standalone Celery, migration-apply and seed smoke files were excluded; no production rollout is certified by this offline run.
- Strict policy coverage includes exact positive matches; greetings, surveys and incomplete names; account/carrier/route/date/number boundaries; stale, moved and empty source revisions; contradictory source metadata; ambiguous multi-booking references; malformed saved facts; cancellation/manual/share protection; bounded histories; retained-notice ordering; and idempotence.
- Comparison-tool suite after adding fresh-UUID handling: **35 passed**, including original-ID preservation, missing or duplicate logical identities, dangling evidence and unchanged sharing/assignment references.
- Elisha: both 11,537-message passes completed; **60/60 comparison checks passed**. All 15 flights, eight trips, original IDs, message statuses/reasons, evidence, manual decisions and shares match the baseline. Repeat-pass results are stable. Existing repair and travel-name recovery records are unchanged.
- Nathan: both 12,546-message passes completed; final flight and trip results match the baseline (**162 flights / 68 trips**). One previously unresolved message becomes accepted through direct matching passenger evidence; no new flight is created. Its status/provenance difference is retained for explicit review rather than silently treated as an identical result.
- Both replays had zero network attempts and unchanged frozen application hashes. The candidate evaluator ran 854 times for Nathan (one allowed; 2.008270 seconds total) and 16 times for Elisha (none allowed; 0.126425 seconds total). The rule did run on actual emails, rather than merely being enabled in configuration.
- Isolated lookup benchmark completed using eight alternating warmed rounds, fresh read-only sessions, completed source metadata and no concurrent replays. Database and application hashes remained unchanged, with zero network attempts and stable decisions. Nathan's 234 restorable unknown observations included 69 existing verified bypasses and 165 fallback calls: median workload time was 77.7 ms before versus 1,324.1 ms with the fallback, or **5.34 ms additional time per workload lookup**. Elisha's 18 restorable observations included two bypasses and 16 fallbacks: 4.95 ms versus 107.3 ms, or **5.69 ms additional time per workload lookup**. Incomplete/non-restorable originals were excluded (324 for Nathan; 32 for Elisha). These deliberately concentrated workloads are not whole-inbox scan timings or PostgreSQL latency estimates.

Nathan's single additional acceptance is an unnamed AA0163 notice for the same dated Tulum-to-Dallas leg as an explicitly named AA163 ticket. Both baseline and candidate already contain the flight. The candidate adds source attribution/confidence to that existing row and resolves the held notice; flight identity, route, schedule, passenger ownership, trip membership and evidence are unchanged. The comparator intentionally returns review-required for this status difference. It must not be described as 60/60 identical-result checks passing or as an additional recovered flight.

This acceptance occurs on the second historical pass: the newer notice is processed before older corroborating messages with legacy metadata. The first pass waits for those originals to be reparsed. The legacy importer already recognized a self-owned scope, so refreshing that proof does not trigger the new-scope replay hook. The next ordinary retry can use the now-current direct proof. This is a mixed-version historical-replay limitation; the fallback does not weaken the source-currentness rule to avoid it. A focused third ordinary retry on a separate database copy left flights, trips, the accepted message status, observations, retained tickets, sharing and assignments unchanged; the worker's discovery-state update timestamp advanced as expected.

The real-data backtest rejected a veto-style prototype despite unchanged flight counts. It blocked two corrections already made by parser 28 in Nathan's history and changed four of Elisha's accepted messages to review-required. The final design therefore preserves the existing verified path and applies strict checks only to additional recovery. Regression tests explicitly require established corrections to bypass the new evaluator. Rejected and interrupted prototype runs are retained privately and are not final validation results.

Nathan's frozen starting snapshot has 163 flights / 65 trips. Replaying the current parser already proposes seven additions, eight removals (six other-passenger records and two canceled flights), and 65 changed records. The candidate produces the same flight/trip result. These historical corrections are not new enrichment behavior and have not been applied to his live account by this work. Repeat passes preserve material itinerary and immutable evidence; some existing parser provenance metadata grows on replay, so the full database is not byte-for-byte identical.

## Expected limits

The two Tulum notices and Sun Country notice discussed in the source audit contain flight details but lack qualifying direct passenger proof in the reviewed sources. Personalized survey emails remain supporting context, not sufficient automatic ownership authority. The incomplete Manila registrations remain held without invented airports or times. This candidate does not promise to recover those flights.

An unchanged result relative to parser 28 is not certification that every inherited historical itinerary is correct. Existing historical correction proposals must be reviewed and applied separately against then-current account data. No such proposal is applied by this work.

Before production enablement, run the frozen candidate against a disposable PostgreSQL clone to measure query plans and concurrent imports. SQLite replay does not establish production lock contention, isolation, throughput or Gmail latency. Existing user/booking/source indexes help, but returned-row limits do not guarantee a constant amount of database scanning. Whole-replay timings were measured under different concurrent loads and cannot establish a production speed improvement or slowdown.

The flag is process-wide, not an account allowlist. Turning it off stops additional recovery; it does not undo previously applied changes. There is no automatic historical rescan, so previously held messages require later evidence or a separately controlled replay to be reconsidered.
