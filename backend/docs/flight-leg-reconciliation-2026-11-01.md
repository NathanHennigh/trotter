# Flight-leg reconciliation and contextual journey grouping

The subsequent [November 2 retest](parser-retest-2026-11-02.md) identified a
PostgreSQL preview/apply limitation for repairs that allocate new trips. That
case is now [fixed and retested](repair-trip-identity-fix-2026-11-02.md).

This is a local candidate. No code, feature flag, migration or account repair has
been applied to production by this work. It extends the recovery candidate in
`no-loss-followup-2026-11-01.md`; it does not replace its ownership safeguards.

## Ordinary imports

The OTA confirmation parser resolves a connecting departure from the preceding
verified arrival, explicit printed layover, matching connection airport and
matching departure clock. It retains the evidence of both departure dates.
Unsupported or conflicting dates remain held. This fixes the overnight Taiwan
connection without a country, account, airline flight-number or date exception.

Supported OTA and numbered-flight-card layouts carry a document-local hash of
the original flight block. The hash is independent of parsed airports and dates.
Identical plain/HTML representations are harmless; one block interpreted as
different flights is ambiguous. Formats without a pointer retain their existing
import path and gain no new correction authority.

`BOOKING_LEG_RECONCILIATION_ENABLED` defaults to false. When enabled, a higher
parser revision may correct a leg only through the same account, original
message, unambiguous block, booking and affirmative passenger evidence. Earlier
revisions cannot restore a superseded interpretation. Newer independent schedule
evidence, user decisions (including declared booking aliases), cancellations,
assigned tickets, active shares and accepted-share references remain protected.
An ambiguous older pointer cannot be upgraded into automatic correction authority.

A linked legacy interpretation without a pointer is held when the new parse
conflicts; it is not permission to insert another active copy. A verified
connection also detects the specific old error of copying the outbound heading
date onto that connection. This is a hold, not an automatic legacy correction.
The printed predecessor date remains available even if another representation of
the preceding flight was selected and held during deduplication. This narrowly
scoped duplicate hold also runs when automatic correction is disabled: parsing
an accurate connection must not add it beside an unrepaired legacy copy. It
grants no correction authority and skips extra lookups for other flight types.

`BOOKING_CONTEXTUAL_TRIP_GROUPING_ENABLED` also defaults to false. It computes
journey boundaries using the account's complete timeline, then updates only the
affected connected trips. It retains the existing external connection bound and
clustering rules. Manual, shared and public trips are protected; unrelated trip
fields, flight facts and IDs are unchanged. Stable membership preserves titles
and avoids redundant history snapshots.

## Reviewed legacy repair

`booking_legacy_repair.prepare_legacy_repair` and `apply_legacy_repair` are
operator-only utilities. They are not invoked by ordinary scans or exposed as
an unrestricted user API. Each correction names an existing successor flight,
the exact original observation supporting it, any obsolete legacy flight IDs,
and the source-review reason.

An unnamed later schedule can use up to four explicitly selected original
passenger observations, validated by the existing reconciliation policy against
the same booking and dated leg. This never changes the ownership or contents of
the original unnamed observation. A chosen target must have complete normalized
date evidence and a supported unambiguous source pointer. Both the target and
every selected passenger proof must still be the current, nonconflicting
interpretation of its original. Assigned or actively shared passenger evidence
cannot be borrowed to authorize a correction.

Preparation executes in a savepoint, rolls back, and persists a fingerprinted
preview. Apply requires that exact hash and unchanged account state. An
interruption rolls back and leaves the plan retryable. A repeated application
returns the same result. Flight IDs selected as successors remain; every retired
legacy flight has its full original snapshot and an explicit successor link.
Normalized independent flights cannot be retired through this legacy utility.

The preview checks original observations, cancellations, retained-ticket links,
typed carrier evidence, assignments, sharing, account identity and messages.
Previously stored history cannot change. No unrequested flight may appear or
change its facts/metadata. Regrouping may change affected membership only.
Clock normalization installs its selected evidence immediately even when the
receipt is older than a retained legacy source timestamp.

## Scope and rollout

There are no added Gmail requests, AI calls, dependencies or schema changes in
this reconciliation layer. The separate earlier carrier-recovery candidate still
requires migration 0025. Parser revision remains 28 in this local candidate;
no automatic global historical rescan has been introduced.

New account imports and historical repairs are validated separately. Existing
records without reliable original links cannot be made safe by a broader fuzzy
match. They require a reviewed preview against a fresh account snapshot.
Before production application, recreate each repair against current server data,
verify its precise differences and backup, and apply only that reviewed plan.
A later change to the account invalidates the plan.

When two OTA representations agree exactly on booking, flight number, airports
and departure, the verified complete copy outranks a compact copy explicitly held
for borrowing an endpoint from the next flight. The rule does not change generic
ranking or suppress a different route. Malformed different-route representations
remain held evidence; source captures are unchanged.
This work does not claim every email format is supported or every historical
record has been exhaustively adjudicated.

## Captured-data validation

The final frozen reconciliation V9 suite passes **3,138 tests, with four existing
skips**. All 326 source/test/configuration hashes match the working backend.
The legacy-repair suite has 41 passing tests, including independent checks for
assigned/shared proof, stale and contradictory proof, checksum tampering,
concurrent account changes, rollback and unrequested mutation checks.

All account checks use disposable copies and captured original email/attachment
bytes, with external networking blocked. Input hashes are checked. No production
account, live mailbox or original capture is changed. The earlier recovery V7
baseline and this reconciliation V9 candidate are distinct snapshots.

Nine affected Nathan originals are replayed in chronological and reverse order,
with three passes per order. On a fresh itinerary they produce seven valid
flights in three journeys: four EVA legs together, the Washington outbound and
return together, and the later Chicago journey separate. The Taiwan connection
uses April 27 and the latest printed clocks. Both standalone receipt variants
now retain the complete overnight outbound. All eleven route/date/grouping
checks pass, without an account-specific parser rule.

On the existing legacy account, ordinary importing preserves 162 flights and
68 trips and holds the conflicting connection rather than creating a duplicate.
The final V9 source replay also verifies those counts with both new flags
disabled, in both source orders across three passes. This closes a real V8
default-off regression that added a duplicate connection; its failed report is
retained rather than replaced. The hold remains active while correction is off.
The separately reviewed repair keeps the supported successor IDs, consolidates
exactly two obsolete interpretations, corrects the connection date and restores
the Philippines journey. Its result is 160 flights and 67 trips. Full retired
records remain in history with successor links. Preview leaves itinerary data
unchanged; repeat application is idempotent. Subsequent source replays with the
new flags both enabled and disabled preserve the repaired itinerary.

Elisha retains all 18 flights and 10 trips, including the three supported flights
recovered by the earlier carrier-evidence work. The two incomplete registrations
remain supporting evidence; missing endpoints are not invented. Direct V8
reprocessing of her 13 affected originals in both orders across three passes
also preserves that outcome; V9 does not change the enabled import path.

The first whole-history Nathan pass records additional evidence: 32 observations,
26 retained-ticket links, 57 audit snapshots and one unassigned, held malformed
interpretation. Seven flight rows gain metadata only. Every existing flight's
route/date/clock/trip fields, all trip rows, prior immutable evidence and protected
rows remain exact. Its strict byte-for-byte unchanged gate is retained as failed,
with a separate explicit no-loss adjudication. A second normal pass leaves every
captured table exact except the discovery scan timestamp. Elisha's first and
second normal passes meet that exact unchanged gate. These runs cover 12,546
available Nathan message IDs and 11,537 Elisha IDs; Nathan's two unavailable
indexed originals remain accounted for separately.

The final complete-copy parser adjustment subsequently adds one Nathan
observation, one retained-ticket link and two audit snapshots, and accepts its
original receipt. Only the existing outbound's source metadata grows; all
itinerary facts remain exact. A following full normal replay under frozen V8
passes the strict unchanged gate: 160 flights, 67 trips, all captured rows exact
except the discovery timestamp. Elisha's final normal replay is likewise exact.

The whole-history evidence is explicitly versioned. V7 to V8 changes only the
reviewed-repair utility and its tests; the ordinary scanner is byte-identical.
V8 to final V9 changes only the disabled-feature duplicate-hold branch and its
tests; the enabled import behavior is unchanged. Final V9 directly repeats fresh
imports, unrepaired imports with flags off, and repaired imports with flags on
and off. Reviewed-repair API code is unchanged from its exact V8 preview/apply
test. The final aggregate records these limited transfers of validation instead
of claiming every long replay used the final binary.

Whole-history tests use normal worker skip logic, not forced reparsing of every
accepted email. Forced reprocessing of the affected originals is tested
separately. This distinction prevents unchanged skip results from being treated
as proof that every email was parsed again.

## Performance and remaining release checks

The new logic adds database work, not Gmail or AI calls. An early frozen-candidate
measurement on the nine-original fresh-account fixture increased SQL statements
from 794 to 808 in chronological order and 761 to 846 in reverse order. Forced
repeated parsing was approximately 35% more queries and roughly one second
slower over the fixture; it is not the normal accepted-email scan path. These
concurrent local SQLite measurements are diagnostic, not a production latency
guarantee. Measure first-import and rescan latency on the server canary before
expanding rollout.

The feature flags are process-wide. A canary requires an isolated worker or
rehearsal environment restricted to the intended accounts; enabling the flags
on a shared worker is not a per-account rollout control.

Reconciliation adds no migration. The pending carrier-evidence migration 0025
still needs the deployment checks documented for that earlier candidate. The
current broad test suite excludes the standalone external PostgreSQL/PostGIS,
Celery, migration-apply and seed smoke files. A fresh production-engine rehearsal,
backup, current-account repair preview and monitored canary remain deployment
steps. No blanket rescan or automatic repair of unlinked legacy records is
authorized by passing the captured-data tests.

**Status:** implementation and captured-data validation are complete. No code,
migration, feature flag or account correction has been pushed or deployed.
Production rollout remains a separate step with fresh server state.

Private evidence is under `artifacts/booking-enrichment-20261031/`:
`candidate-reconciliation-v9/source-manifest.json`, the adjacent
`backend-tests.log`, `reconciliation-qa/final-validation-v9.json`, and the
`reconciliation-qa/` actual-source, reviewed-repair,
normal-history and adjudication reports. Captures and detailed account data
remain ignored by Git.
