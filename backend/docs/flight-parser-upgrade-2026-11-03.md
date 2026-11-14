# Parser hardening and all-account validation — 2026-11-03

## November 14 all-user Gmail sync

Ordinary Gmail scans now use the hardened parser for every existing and new account. The production change set `FLIGHT_IMPORT_RECOVERY_USER_IDS` to `*` on all seven backend services. The deployed images still use release `93c1325`. The four parser switches remain independently reversible. Historical mailbox discovery retains its separate cohort of account 9.

The new account's first scan finished on the previous worker before the cutover. It checked 4,050 emails, parsed 13 and added nine flights. A fresh post-import database backup was verified off the VM and restored into an isolated database. On that copy, a new test account imported four expected flights into one trip. Two repeat scans added zero flights. The test preserved all existing accounts. The focused rollout, routing and receipt suite passed 83 tests.

After activation, the live router selected the updated worker for all seven existing accounts and a prospective account ID. Each of the five queues handled a probe and drained. The public readiness endpoint confirmed database and Redis connectivity. The fingerprints of all 15 checked tables matched the pre-switch snapshot, including trips, segments, passenger evidence and Gmail discovery state. Ordinary scans pick up the change automatically. The cutover did not start historical imports.

## November 13 receipt recovery pilot

Expedia purchase receipts can list a separate confirmation for each airline. The parser now scopes each leg to its explicitly labeled carrier reference. A dated purchase cannot overwrite a newer confirmed schedule. StudentUniverse, LifeMiles and Capital One receipt headings now enter bounded historical recovery with provider and subject checks. Only the affected receipt families need a new recovery marker.

On the restored pilot database, Nathan reached 167 flights in 71 trips. Both original Aeroméxico segment IDs survived, the two Royal Air Maroc legs and UA1540 were recovered, and the two misattributed United tickets were retained for their named passenger. Grant reached 13 flights in six trips before the separately reviewed unsupported Southwest entry is retired. Elisha retained the same 18 flights and ten trips. All eight flagged Nathan retirements matched reviewed IDs and retained their original rows in history. Two final ordinary recovery rounds across all three accounts read zero originals and preserved their itineraries and evidence.

The backend suite passed 5,481 tests, with six skipped. The three database-specific checks were exercised on a separate PostGIS database with two migration and seed runs. The pilot uses a dedicated Celery worker. The API and ordinary dispatcher use the previous stable parser image with the routing hook added. Preserve the three-account recovery cohort and the independent historical-discovery cohort. Fresh-account rediscovery can still reread review-held messages when the provider returns the same search results.

Production release `93c1325` routes Nathan, Elisha and Grant to the pilot. A further 63 routing, rollback-switch and receipt tests passed. All seven backend services agreed on the cohort. Each of the five worker queues processed a ping.

The archive correction committed after 42 bounded worker runs and 378 saved-original reads. Both final recovery rounds made zero original reads. The maintenance run preserved the live Gmail discovery watermarks. A separate database connection then verified Nathan at 167 flights and 71 trips, Elisha at 18 and 10, and Grant at 12 and five. Grant’s separately reviewed sparse Southwest record was retired with its history and supporting evidence. Every expected flight and trip membership matched, together with the other-traveler tickets and their passenger evidence. Production readiness passed and all five queues were empty.

The first archive attempt rolled back because a cross-database check compared generated evidence IDs directly. The revised check resolves those IDs to the underlying observations and original carrier records. Elisha’s isolated retry confirmed equivalent evidence. The historical correction took place in a single transaction with per-account import locks and preserved existing evidence across all accounts.

**November 13.** The parser now classifies identical plain-text and HTML parts once. Only four of 24,418 captured messages used this path. All 187 focused MIME, history, recovery and repeat tests passed. Larger performance work is deferred.

Grant’s first import into an empty account recovered 12 confirmed flights grouped into five expected trips. All four passes matched the original ticket expectations, including passenger ownership and partial evidence. The first repeat attached additional existing evidence to two flights and stored their pre-change history. Subsequent repeats preserved those records. The repeated discovery fixture served the same 325 IDs each time. Each repeat reread 218 messages marked for review, so the zero-refetch check failed.

Historical recovery on a separate restore finished for Nathan, Elisha and Grant, with at most 25 originals per account per scan and zero original reads in the last two rounds. The other accounts and pre-existing evidence passed the preservation checks. The six raw protected-flight removal diagnostics for Nathan matched reviewed retirements with original records retained in history. Elisha retained all 18 flight records and ten trips. Grant recovered all ten missing legs and retired the three canceled ones. His unsupported legacy entry remains a separate reviewed correction on existing accounts.

Nathan’s results block rollout. The historical selector skipped the originals for AT262, AT200 and UA1540. Source 5169 produced additional AM651 and AM2682 records alongside the existing legs, with different clocks. Two older United records previously attributed to another traveler remained active. The database copies were removed after both checks. An initial historical test setup failed to open the private SQLite fixture. The completed cold test was reused, and the historical test ran with an identical read-only copy. Results and exact source indices are in `artifacts/production-readiness-20261102/recovery-checks-20261113/report.json` and `account-review.json`.

**November 10 follow-up on Grant’s repeat scan.** The same archived email reproduced the three extra history rows against the saved PostgreSQL state after his first scan. With the history fix, replaying it twice added zero rows on both passes. Full trip and flight rows, evidence, and ownership matched across the repeats. All 562 focused regression tests passed, including exact pre-change history for a schedule update and a cancellation, retries, and transaction rollback.

In a separate rehearsal on that database copy, the reviewed correction for Grant’s unsupported Southwest segment 242 preserved the original record in history and left 12 confirmed flights in five trips. Reapplying the correction returned the same result. Replaying the three original source messages twice kept the corrected totals. The fix and correction are pending production release. The PostgreSQL result is in `artifacts/production-readiness-20261102/grant-history-on-change/result.json`.

**November 10 — Grant's 325-message replay.** A fresh matched run of the baseline and working candidate against separate copies of the same starting database found 2 and 12 source-verified flights respectively. The candidate preserved both Spirit legs, recovered 10 complete legs across five airlines, grouped the 12 confirmed legs into five journeys, and removed three explicitly canceled legs from active trips while retaining their original records in history. The existing unsupported Southwest segment 242 remained byte-for-byte unchanged: the raw database total is 13 flights and six trips, not 13 verified flights. The six unassigned tickets stayed separate; all 58 new observations and six partial evidence sources matched the independent expectations. The other five accounts were unchanged at every boundary.

Two ordinary follow-up scans preserved all trip and flight rows, IDs, evidence links and assignments. Strict repeat verification still failed: the first repeat appended three `before_booking_import` history entries (one trip and two flight segments), each with the same snapshot content already retained with another reason. The final cached scan added no history. Each follow-up parsed one message. Grant's first-scan time was 175.995 seconds on the baseline and 170.884 on the candidate (−2.9%, one matched sample). The replay used archived originals without any external requests, and both temporary databases were removed. It does not test live Gmail discovery or a blank account. No production changes. Compact report: `artifacts/production-readiness-20261102/grant-replay-20261110/report.json`.

**November 10 matched first-scan benchmark.** The deployed parser version from the saved baseline and the current candidate ran sequentially on the same Oracle QA host, with identical starting rows, captured messages, two CPUs and 2 GiB of memory. Nathan's 12,554 messages took 1,027.238 seconds on the old code and 1,119.566 on the candidate (+8.99%). Elisha's 11,539 took 555.832 and 682.552 seconds (+22.80%). Each user has one matched timing sample.

On those same messages the candidate made 8,618 additional flight-evidence classifier calls for Nathan and 8,904 for Elisha. The multipart preparation path evaluates both the plain text and HTML, then selects the HTML only if it supplies stronger operational itinerary evidence. Message preparation increased by 198.670 and 187.754 thread CPU seconds respectively. SQL execution increased by 2.453 and 0.434 aggregate seconds. These stages can overlap and include nested calls. The next performance change should target the second classification and compare its outputs to the existing classifier on HTML-only flight details, structured reservations, changes and cancellations before remeasuring full scans.

Both workers completed. The report reader initially interpreted the baseline worker's count-valued diagnostic exit as a boolean. It recovered the saved baseline output without rerunning it. The baseline raw exit was not retained, and the detailed report preserves this limitation. The baseline and candidate produced 10 and 8 protected-segment removal diagnostics respectively. Original immutable records and unrelated accounts passed the worker's checks. This run measures timing, and the repeat, historical-recovery and fresh-account validations remain outstanding. Results are in `artifacts/production-readiness-20261102/paired-first-scan-20261110/report.json`.

**November 10 follow-up.** The working tree now checks middle-name variants on the same booked leg when listing or sharing retained passenger tickets. The four ambiguous pairs from the frozen replay have eight independently specified outcomes. The two Southwest items backed by a named ticket can be shared, and the six unsupported variants are held. The local test checks each outcome through both the inbox and the invitation service and verifies the original records after rolling back each attempted invitation.

The focused run passed 182 tests in 21.41 seconds, including explicit reissues, distinct ticketed passengers, prior invitations and the eight saved outcomes. To repeat the saved cases from `backend`, set `TROTTER_RECIPIENT_REPLAY_FIXTURE` to the private `recipient-ambiguity-four-legs-private.json.gz` in the parser upgrade artifacts and run `python -m pytest -q --tb=line tests/test_recipient_name_ambiguity.py`. Without that fixture pytest skips the private example and runs the portable cases. The paired timing measurement and outstanding repeat, bounded-recovery and fresh-account checks remain pending. This follow-up ran locally.

**Stopped at the user's request on 2026-11-03 at 20:51 UTC. V16 is not release-approved. Neither V15 nor V16 was deployed; global recovery remains held.**

The isolated V16 worker exited with status 1 after SIGINT. All parallel review
work was interrupted. Production was not modified. The QA database, original
backup, frozen candidate and completed diagnostic boundaries are retained.
The ordinary replay completed passes 1 and 2 for Grant, Nathan and Elisha, plus
pass 3 for Grant and Nathan; Elisha's third pass and subsequent cached/disconnected
phases did not complete. An acceptance file written during shutdown does not
constitute acceptance of this incomplete run. No new tests or deployment are to
start without a subsequent user request.

The reviewed first-pass results preserve existing valid flights and immutable
evidence, but this is not an all-account regression-free release claim. Four
different-name ticket pairs remain simultaneously shareable in Flights for others.
One pair reproduces the old baseline; three additional pairs are exposed by this
candidate (also present in rejected V15). Original sources do not provide shared
ticket numbers or explicit name-change proof sufficient for safe merging. A
conservative ambiguity hold was proposed but has not been implemented. This is a
release blocker. Initial ordinary replay times were +8.87% for Nathan and +22.53%
for Elisha versus the saved baseline; a new matched performance comparison has
not run. The separate bounded-recovery and clean fresh-account worker checks also
remain unexecuted. Known legacy unsupported records remain held for separate
source-backed decisions; no live historical repair was performed.

The stopped-run archive is
`artifacts/production-readiness-20261102/parser-upgrade-20261103/candidate-full-v16-user-stop-diagnostic.tar.gz`,
SHA-256 `2780cc10c663ddd79b6d360948c43e637a168f372d8dcccffb4d6e7371074b08`.
The detailed notes below record checkpoints before the user-requested stop.

V16 is now frozen for combined validation, not deployment. Its 111 application
files, 288 application/test Python files and 38 fixtures are bound to root freeze
`449ba0ecef2a07cc549fc09a5e6d0ad2f47b3597079eed0754a7e5213b327d43`.
The full correctness suite passed 5,442 tests, with five existing skips and three
database-environment checks exercised separately. All source, test and fixture
hashes stayed unchanged. The fresh 29,043-original preparation comparison closed
without execution errors, negative-example violations, recall failures or changes
to partial evidence. Exactly two sources remove destination text (`DENVER` and
`MANAGUA`) from aliases and the top-level false PNR; all their other flight fields
and the other 29,041 complete outputs match the frozen V15 comparison. The V15
reference outputs are explicitly inherited, not a new V15 execution.

V16's isolated PostgreSQL/PostGIS checks passed two migrations and two seed runs
with a single seed account. The separate 2,100-import concurrency workload passed
all 56 integrity scenarios, overlap/rollback/retry controls and strict repeated
state checks. Its 25 prior load accounts were preserved, frozen inputs did not
change, and the disposable local cluster shut down cleanly. An independent review
retains the measured query increase and mixed timing results; these are not a
performance acceptance. The real targeted worker replay completed all 15 calls
and disconnected probes with no worker failure or input drift. Its actual exit
status is 1: the strict comparator retains 386 differences, not a blanket pass.
Independent review classifies six source-backed OTHER retirements, 42 second-pass
message/history updates, zero third-pass differences and 338 cached message-only
updates. Active rows and all nonmessage evidence remain stable on the last two
passes. All original immutable records, decisions and unrelated account boundaries
are preserved. Known unsupported legacy flight 242 and the existing 141/142
overlap remain held; no repair authority is inferred from this result.

The complete 24,418-original ordinary worker replay is now running from the same
fresh database backup. No ordinary full-worker, performance or release acceptance
is claimed yet. Targeted replay is modestly faster than V15, but remains slower
than the old baseline for Nathan and Elisha on the forced path; this does not
settle the separate ordinary-scan performance gate.

Grant's first ordinary V16 boundary has now closed and been independently reviewed:
13 active rows, of which 12 have complete reviewed sources, in six trip rows.
The unchanged unsupported legacy row 242 accounts for the extra row/journey.
The ten new complete legs and three cancellations match originals; all original
rows retired by cancellation remain in exact same-owner history. All 58 new
observations match their independently prepared source evidence, with exactly
six held unassigned Inbox items and zero spurious named recipients. The two old
invalid RAPID header items remain unchanged, canceled and unshareable; no new
links are created for them. Its ordinary scan took 170.826 seconds against the
saved old-worker 177.104 seconds, using the same 325 captured originals. This
is one replay, not a statistical performance guarantee or all-account acceptance.

All three first ordinary scans have now completed. Nathan took 1,109.616 seconds
versus the saved old-worker 1,019.227 (+8.87%); Elisha took 685.243 versus 559.267
(+22.53%). Both improved slightly over rejected V15 but still require a fresh
matched baseline before any performance conclusion. The repeated and cached
phases are still running. A prepared isolated timing-control wrapper will preserve
the completed candidate database and require exact restoration; it has not run.

Frozen V16 archive:
`45239fd8b5aab4834613ee3cc74d2b9f10ec2f8863ea1af6e869e24124b9827a`.
All six accounts are present in the isolated restore. Accounts 1, 9 and 12 have
captured mailbox inputs; accounts 2, 10 and 11 are tested for preservation and
the expected disconnected response, not fabricated mailbox coverage.

The candidate adds three bounded corrections to the rejected V15 diagnostic:

- A recipient name change requires the original named ticket and an explicit
  old-ticket-to-new-ticket transaction for the same dated flight. It retains
  every physical record and protects existing shares and decisions; similar
  names alone cannot merge tickets.
- A complete, named round-trip original can establish a negative grouping
  boundary before an independently booked later journey. This does not infer
  ownership of the old June return or change the general long-trip threshold.
- Destination text in a typed flight-purchase email title is excluded from
  booking-reference aliases. The source's actual confirmation remains intact.
  Ordinary all-letter confirmation codes are still accepted.

Only two exact-output reference-extraction fast-negative guards are integrated.
Other proposed HTML optimizations with mixed timing results were left out. Their
microbenchmarks do not resolve the ordinary-worker performance gate below.

The separate 68-record read-projection check on the frozen candidate passes:
four existing weak-date tickets suppress their untrusted date/clocks and remain
unshareable; the other 64 complete views and the underlying records are unchanged.
This is a presentation contract check, not proof of import correctness.

The exact frozen V16 recipient service also passes 18 original-source cases:
all six physical records remain, only the three current tickets are listed,
existing shares/decisions are protected, old direct details remain readable,
three strict repeats are unchanged, and all five unrelated accounts are exact.
The trip-feature proof is inherited on identical feature/dependency bytes:
72 source-order/policy cases, 12 paired cases and three strict repeats. Four
initial manual/note-only normalization limitations reproduce in the old baseline;
they are retained explicitly rather than claimed as fixed. Whole-V16 worker
integration is still required.

Original-source review of the second title case confirms distinct printed Spirit
and Aeromexico references. The receipt parser's older global primary-reference
scoping also reproduces in pre-upgrade source `94bd718`; V16 does not newly solve
or approve that legacy behavior. The active Aeromexico flights retain their own
reference in the initial/baseline/V15 projections; V16 must verify that separately.

This change follows the source-backed account 12 audit in
`flight-recovery-deep-audit-2026-11-03.md`. Production still runs source
`94bd718`, recovery cohort `1,9,12`, and separate historical-discovery cohort
`9`. The four independent authority switches remain unchanged. No live repair,
new mailbox scan job, mobile change, or scheduled follow-up is part of this test.

Rejected V15 validation history: its 110 application files, 283 application/test Python
files and 38 fixture files passed the final correctness suite and fresh
29,043-original comparison. The suite passed 5,274 tests, with five existing
skips and three database-environment checks exercised separately on PostgreSQL/
PostGIS. Repeated migrations and seeding passed without duplicate seed accounts.
The fresh comparison changes exactly six reviewed identity sources relative to
retained V14; the other 29,037 complete outputs and every partial-evidence output
match. All 27,433 independent skip-evidence/miss comparisons also match. Hashes
of code, tests, fixtures and cached inputs stayed unchanged. The final PostgreSQL
load also passed 2,100 imports, 56 integrity scenarios, four overlapping-job
rollback/retry cases and strict repeat-state comparisons. The disposable local
cluster is stopped. Real mailbox-worker replay, repeat scans, recovery,
cold-start and scan-performance gates remain open; no candidate is accepted for
production.

All three connected accounts have now completed the first ordinary full scan.
The remaining V15 repeat phases were deliberately stopped after independent
source review found three duplicate recipient-ticket pairs for a Southwest name
change. The original and reissued tickets have the same dated flights; their
different passenger-name spellings currently produce separate actionable inbox
records. This was not covered by requiring the previously approved recipient
records alone. The next candidate must also prove that no additional duplicate
recipients are exposed, including opposite arrival orders and protected shares.

The audit also found a contextual grouping problem: a source-backed May return
and a separate June booking remain in one generated trip. All flights are
retained, but preservation alone does not make that grouping correct. A bounded
correction is being tested against the complete original May itinerary; it must
not infer ownership of the legacy June return, lower the general long-trip
threshold, or alter manual decisions.

A further source review found `DENVER` newly stored as a booking-reference alias
from a destination-bearing email title. The original prints a separate actual
airline confirmation. V16's typed-title exclusion must remove only that false
alias while preserving both complete legs and all genuine reference fields.

First ordinary-scan wall times on the same captured inputs were Grant 174.937
versus 177.104 seconds, Nathan 1,136.188 versus 1,019.227 seconds, and Elisha
705.564 versus 559.267 seconds. Nathan and Elisha remain 11.48% and 26.16% slower
than the old worker. Private preparation optimizations have exact-output proofs,
were tested independently. Only the two reference guards above are now integrated;
they have not been accepted as full-worker performance results.

The closed first-pass physical audits cover all 40 tables and 55 declared foreign
keys. Each account scan preserves the other five accounts, existing immutable
evidence, inbox records and protected decisions; source-authorized retirements
have exact prior-row history. Elisha retains all 18 flight IDs and all 10 trip
rows, with no new flights, inbox items or duplicate flight groups. These findings
do not waive the recipient, grouping, latency, bounded-recovery or cold-start
gates. Every completed boundary and the stopped worker's actual exit code 1
are retained; the full four-pass replay is explicitly incomplete.

The final V15 targeted worker replay has completed all fifteen calls: three
forced passes, a normal cached scan for each connected account, and disconnected
probes for the other three accounts. Frozen inputs stayed unchanged, with no
worker failures or outbound requests. All 40 tables, 55 declared foreign keys,
protected decisions and account boundaries were independently checked. The third
forced pass leaves all 37 non-operational tables exactly unchanged. The cached
scan changes only message-screening/bookkeeping fields, with no flight, trip,
inbox, observation or history changes. All source-backed active facts match the
reviewed V14 target; the Amex receipt now has two explicit SELF observations
without unresolved inbox entries. This target does not contain the five
Southwest footer sources or four AirAsia sources; their final integration checks
were checked in the ordinary first-pass workload, which exposed the additional
name-change duplication above. Its remaining repeat phases are stopped.

The target process exited 1 with 383 strict diagnostic differences retained:
six source-reviewed retirement flags, 39 finite second-pass changes (34 message
updates and five prior-row history snapshots), zero third-pass differences, and
338 cached message-marker updates. Existing sparse flight 242 and the legacy
141/142 overlap remain separately flagged. This is diagnostic clearance to run
the ordinary workload, not production or blanket no-regression acceptance.

Frozen V15 archive:
`01249058375d6d638374378ee6b8d22f1153552935cdd29e9d4eaf07774d258f`

Its changes relative to V14 affect only Bilt metadata gating, passenger evidence,
the retained-ticket date read projection, and the duplicate skip-scoring call.
The fresh source comparison is separate from the earlier Amex-only comparison.

The frozen V14 ordinary replay completed its first import for all three connected
accounts and was deliberately stopped before completing its repeat phases. Every
closed boundary and the actual exit status are retained. Independent physical
audits preserve unrelated accounts, original immutable evidence and exact history
for source-authorized retirements, but semantic review found ten new Southwest
footer phrases represented as companion inbox records. This is a release blocker,
not a passing result hidden by aggregate counts. V15 now excludes the typed
carrier-liability paragraph and recognizes a separate, structured travel-checklist
section. It does not truncate arbitrary tables or broaden roster completeness.
The exact correction passed 426 source-order/protection cases, twelve initial and
prior-candidate six-account cases, and 238 focused tests. Final combined replay
is still required. Elisha retains the same 18 flight IDs and 10 exact trip rows, with no
new inbox items; her normalized flight facts match the old worker's first pass.

Independent source review classified all 68 new named inbox records from V14:
58 genuine traveler records and the ten footer errors above. Four genuine
AirAsia records contain subject-only fallback dates and placeholder clocks that
the old parser also retained. They remain held and unshareable. V15 suppresses
those untrusted dates/clocks only in the owner-facing read projection, preserving
the raw immutable evidence and existing string/nullable-field API contract.
All other 64 views are unchanged, and 184 focused API/inbox/sharing tests pass,
including read-only database checks. This does not claim to recover the full
AirAsia schedules or resolve other incomplete sources.

V14 first-import wall times versus the same frozen old-code workload were Grant
178.772 versus 177.104 seconds, Nathan 1,425.946 versus 1,019.227 seconds, and Elisha
862.157 versus 559.267 seconds. The latter two regressions remain open. Profiling
found unnecessary sanitized-HTML serialization before a Bilt adapter that rejects
nonmatching headers. V15 now shares the adapter's exact metadata prerequisite and
skips only that unused serialization. All visibility and MIME checks remain;
56 paired original outputs and 288 controls match, and 125 focused tests pass.
Sample timing improvement is not final worker acceptance.

The other measured serial cost was rescoring skipped messages after preparation
had already made that exact decision. V15 reuses only the unchanged, call-local
skip evidence; missing, malformed or non-skip evidence retains the existing
scorer. All 56 sampled original preparation/miss outputs, 39 MIME/force/document
controls and eleven fallback cases match. Twelve actual worker phases across
disabled, unlisted and enabled recovery policies preserve all non-job table rows,
job counters and report fields except measured parsing duration. Twenty-four new
regression cases are included in the frozen suite. These establish behavioral
equivalence, not final first-import timing acceptance.

Retained V14 was frozen after 5,083 passing backend tests, five
existing skips and three separately exercised PostgreSQL/PostGIS environment
checks. The only application difference from V13 is an early return when ticket
reconciliation has no booking scope. Previously that no-op path read four whole
account tables and then discarded the protection result. Twenty paired branch
cases, twenty-one regression tests and the full suite verify that meaningful
ticket-exchange paths retain their safeguards. All 109 other application files
are identical. The 29,043-original extraction comparison and source reviews are
explicitly inherited from exact V13; they are not presented as a fresh V14 run.
V14 PostgreSQL concurrency checks completed, but its broad worker acceptance
was rejected for the semantic and latency findings above.

The broad source audit has additionally identified an upgrade-exposed Amex
identity defect: leading empty HTML table cells hide an explicit Traveler
Information heading from the name extractor. The original receipt prints the
traveler and the same issued ticket as two later Amex schedule communications.
The later schedules already supply the two correct active flights, but the
older receipt produces two unresolved inbox entries. The name is present in
the evidence; this is not an incomplete-source excuse. A narrowly scoped
normalization is included in the frozen V15 candidate. Its earlier separate
29,043-original comparison changes exactly that one receipt; the other 29,042
outputs are identical. Ninety-six byte-exact actual-source service/order cases
also pass. An earlier copied-source private proof had encoding drift and is
explicitly invalidated rather than reused. Those Amex-only proofs do not cover
later V15 performance or Southwest changes; the final combined 29,043-original
comparison described above covers all six final changes. Real worker acceptance
is still required. The frozen V14 replay and all failures are preserved.

Frozen V14 archive:
`09b3374ca0666b26ea4d8a65891824f4f6b767d6f55e403dee849fb42bb49109`

Retained prior candidate: V13 was frozen after 5,062 passing backend tests, five
existing skips and three separately exercised database-environment checks.
Its extraction and partial-evidence results are unchanged from reviewed V12
across all 29,043 captured originals. It extends exact issued-ticket reuse to
OTHER inbox records without merging by name alone or rewriting old records.
The two complete name formats in the source-backed failing case now retain
one inbox item and three source links in all 18 arrival-order/cohort cases.
The frozen candidate also passed 2,100 PostgreSQL imports and all 56 integrity
scenarios, including concurrency, protected records and repeated imports.
Enabled synthetic timing overhead of 10.8–20.2% is recorded, not waived; actual
worker timings and broad recovery acceptance remained open. Its focused real
worker replay completed all fifteen calls, including disconnected-account
probes, with unchanged frozen inputs and no worker failures or outbound calls.
The third pass has zero strict non-operational changes. The raw 384 strict flags
are retained (six source-reviewed retirements, forty finite second-pass updates,
338 cached message-marker updates). These are not a blanket release approval.
No broad V13 run or deployment was performed.

Frozen V13 archive:
`4c12a63be1631f98f338e0e034397ce97b9cf875992ac5115ef72080cb259713`

Retained prior candidate: V12 was frozen after 5,029 passing backend
tests, five existing skips and three database-environment checks. Its 110
application files exactly match the completed comparison of 29,043 originals;
all 36 changed sources and 78 newly eligible sources have independent source
reviews. The separate PostgreSQL/PostGIS, repeated-migration and repeated-seed
checks also passed. Its focused all-account worker replay and final concurrency
checks completed, but source review reproduced duplicate OTHER inbox items for
two spellings of the same traveler and the same issued ticket. The old worker
also creates these duplicates; this is an inherited import defect, not a V12
regression. V12 is nevertheless not accepted for the requested no-junk outcome.
A narrow OTHER-ticket identity correction is being validated as V13. Broad
worker, bounded recovery and cold-start acceptance remain pending. Earlier
candidate numbers below describe retained diagnostic runs, not released versions.

Frozen V12 archive:
`c91674de64ec76b899410de22c45085218436881e4316abcc0ae01584cb87709`

V12's complete focused replay is retained with its actual exit status 1, 384
raw strict differences, no worker failures, no outbound calls and unchanged code
and source caches. All nine removals have source authority and exact original
history: three canceled flights and six OTHER tickets. The second pass reaches
stable flight/trip/inbox/evidence state; the third has no strict differences.
The finite second-pass and cached marker updates are recorded separately rather
than silently waived. No broad V12 replay or production update was performed.

## Changes under test

- Preserve operational itinerary blocks when an email also contains marketing
  or its plain-text alternative omits the HTML itinerary.
- Extract complete Alaska, Allegiant, Delta/Amex, Expedia and Southwest layouts
  without borrowing dates, names, clocks or booking references from other legs.
- Scope passenger identity and booking references to the relevant reservation;
  retain other travelers separately.
- Preserve incomplete Sun Country connections and United notices as partial
  evidence. Missing clocks or passenger authority do not become timed flights.
- Prevent reminders from reviving canceled bookings. Match cancellation scope,
  chronology and passenger identity; hold ambiguous post-travel dispositions.
- Recognize exact named old-ticket/new-ticket exchanges under the existing
  booking reconciliation switch, with manual and shared-data protections.
- Recover affected stored templates in bounded batches, without a global
  parser-version invalidation or routine full-mailbox rescan. Respect source
  404s, transient backoff, independent feature versions, and attachment outcomes.
- Make repeated import behavior auditable, retaining immutable source evidence
  and useful historical snapshots without repeatedly creating empty trips.
- Provide a separate, source-hashed operator preview/apply mechanism for an
  unsupported legacy sparse projection. Parser failure alone cannot delete it.
- Separate import health from unresolved evidence quality in read-only reports.

## Isolation and account coverage

A fresh production backup was verified both on and off Oracle:

`e232868540811b5ca1f807e2a08b6236cbb8ff10546f46561082f5b6cb10f03b`

Its restored copy runs on the explicitly named internal-only
`trotter-workerqa-20261103` network and `trotter-workerqa-db-20261103` container.
The replay refuses any other database host/name. No public ports or production
network are attached. Original-message caches and application code are mounted
read-only; outbound provider calls are blocked. The real import worker, ORM,
parser, gates, ownership, ledger, builder, and deterministic enrichment run.
Only Gmail transport/discovery and previously captured PDF extraction are
substituted with frozen evidence.

All six accounts (`1,2,9,10,11,12`) are included in full-table snapshots. Accounts
1,9,12 have captured originals. Account 10 has six existing flights but no
connected Gmail or indexed messages: its data is checked for preservation and
its real worker must return `gmail_connection_required` without fetching mail.
Accounts 2 and 11 are checked for unchanged empty flight records. New per-user
boundaries verify full owned-row hashes for every other account after each call.

The focused corpus contains 385 originals. The broader frozen corpus contains
24,418 originals after ten exact newer-message captures. Account 1 contributes
12,554 originals and account 9 contributes 11,539; two older account 1 sources
were rechecked and still return provider 404. Account 12 contributes the 325
audited originals (323 previously indexed and two newly discovered). Its 4,625
other indexed messages are outside the focused worker corpus. Subsequent
read-only capture covered those originals too: 14 are in the bounded recovery
cache, and the remaining 4,611 were independently prepared and rejected as
non-flight evidence. Together these cover all 4,948 indexed messages and the
two additional sources found by the deep audit's 21 paginated searches. This
does not claim to discover every unindexed message in the entire mailbox.

The full v2 cache is verified both on and off Oracle:

`67f2d6e7b3e8ed9a23f022f018bc5215f6cfa840bb52a93407740557aa9da768`

The retained candidate v2 contains 103 application Python files. It is an
intermediate snapshot, not the final release candidate; source-backed checks
below required further fixes:

`e4d08a8bd1436ae65ce6ae29da952e46f1a1f6e26e61b3fa0825914c53770ed1`

The earlier candidate v3 was frozen and verified on Oracle, without deployment:

`af6bd4a5fe8c87f46afe24a7c5401714d76e9dd8631223a27de005870d2527c8`

Its 103 application hashes matched its 3,517-test suite and the
1,400-message synthetic concurrency run. Later findings superseded this
candidate; these results do not validate the current application files.

## Validation recorded so far

- Earlier stable project-environment backend suite: 3,437 passed, five skipped, three
  database-environment checks excluded and verified separately below. All 240
  application/test Python hashes remained unchanged during the final run.
- Read-only health/report tests: 18 passed.
- Isolated Linux checks: PostGIS available; migrations reach
  `0025_carrier_travel_evidence` twice; seed runs twice and creates one user.
  The first empty test database lacked its required PostGIS extension; the
  configured extension was then initialized and the checks passed. Production
  and the restored replay database were not changed by these checks.
- Frozen source extraction recovers the ten audited complete missing legs with
  their named passenger and schedules. The four incomplete legs remain partial.
- Old-worker focused replay is retained as a baseline, including its existing
  ID replacement, audit-history churn and source-backed correctness problems.
- Live validation health: all six services running with zero restarts and the
  same cohort/switches; all four broker queues empty; no running imports; ready
  endpoint passes database and Redis checks. The unchanged May 11 pending SQL
  row remains a known historical baseline, not current broker backlog.

### Additional findings during all-account validation

- A Southwest numbered connection lost a repeated AM label during text
  deduplication. The structural parser now uses the lossless card, bounds each
  leg independently, and never defaults missing meridiem to PM. The actual
  morning connection is restored; all 325 captured Grant sources retain the
  previously audited schedules and ownership outcomes.
- An explicitly labeled Bilt airline confirmation was dropped by stricter
  reference extraction. Its wrapped heading is now supported without treating
  the booking account name as proof of passenger ownership.
- A Chase legal footer was being treated as a passenger name. A narrow layout
  guard excludes the footer while preserving the real traveler and flight.
- An independent lifecycle review reproduced a cross-scan ordering issue:
  a newly projected receipt in one recovery batch could remain active when a
  conflicting post-departure cancellation arrived in the next. Durable,
  versioned creation provenance and separate-worker tests are required before
  the release candidate can be frozen. Existing historical, manual, shared and
  reviewed rows must retain their protections.
- A subsequent intermediate suite passed 3,477 tests, with five skipped and
  three database-environment tests deselected. Source hashes changed during
  that run, so it is explicitly not final frozen-candidate evidence.
- The cross-scan issue is now covered by persistent evidence on new inserts;
  no existing/adopted row is marked. Actual original-order probes converge both
  inside and outside the optional recovery cohort. Newly supported Alaska card
  projections are held outside reconciliation authority, with observations
  retained. Enabling the feature revisits those completed-but-held sources once.
- Independent source review also found a flattened itinerary header being read
  as a booking-reference alias. The structural header is now rejected while
  legitimate all-letter reference fields remain supported.
- Final v3 project-environment suite: **3,517 passed, five skipped, three
  database-environment checks deselected** (verified separately as above),
  203.00 seconds. All 240 application/test Python hashes stayed unchanged.
  Log SHA256: `524a4f509fdef43d10333e2b85ccc44158ca4f762dccd14c6a49b8ebbdb0bf55`.

The baseline broad replay completed. Its strict repeat differences remain
recorded, including transient trip audit-history churn; those are not waived.
No production parser deployment, global cohort change, or live data repair has
been performed during validation.

The v3 candidate failed its real PostgreSQL service replay: the new
`ticket_supersession` audit entity label exceeded the existing `VARCHAR(16)`
column and stopped Grant's import. SQLite tests did not enforce that boundary.
This failure occurred only on the isolated database copy. The failed candidate
and its first-pass account snapshots are retained; it is not a release candidate.
The correction uses `ticket_exchange` and adds model storage-limit coverage plus
a real PostgreSQL lifecycle check, including the old label as a failing control.
Candidate v4 must pass a fresh frozen suite and repeat all real-data checks.

The v4 stable-point suite passed 3,519 tests (five skipped, three separately
verified database checks deselected); all 241 application/test hashes stayed
unchanged. The frozen archive SHA256 is
`14d9be29ad6336d379c237a84a4191119b8669a85f12af10f5069756e23a6a6b`.
Its real PostgreSQL lifecycle check passed all six old/new/reminder arrival
orders and stable repeats, verified the old oversized label fails, and rolled
back every synthetic table row. It used only the isolated checks database.

The independent first-pass source review also found a release blocker in booking
reference authority: an unnamed email's JetBlue reference was projected onto a
United leg after another email established ownership of that exact United leg.
The original evidence remains retained; inherited ownership must not grant
unrelated reference aliases authority. A separate correction and multi-message
regression are required before the next candidate and all-account replay.

The v5 stable-point suite passed 3,525 tests (five skipped, three separately
verified database checks deselected); all 242 application/test hashes remained
unchanged and matched archive
`3471acfec3034f453ced0701d3afc45a4771cf5e7bafb64ba89a601e4aa312b5`.
Its focused real PostgreSQL replay completed without worker failures. It
recovered all ten source-reviewed missing Grant legs, preserved his two Spirit
legs, applied the three explicit cancellations and Alaska ticket exchange, and
kept the United/JetBlue references separate. Existing immutable rows and every
other-account boundary were preserved.

V5 is still not release-ready. The strict replay reports 416 differences:
four source-reviewed personal-history retirements on the first pass, 51
second-pass metadata/history changes, five third-pass transient trip snapshots,
and 356 changes when switching from forced replay to ordinary sync. Those last
356 are 353 message metadata changes and three transient trip snapshots, with
no active flight or trip changes. The normal-sync metadata changes require
separate convergence evidence; the continuing transient-trip history is a
blocker. Grant's two California one-ways also remain split because their away
airports are 151.93 km apart, just outside the existing 150 km grouping rule.

The next candidate addresses these with deferred trip allocation and a narrowly
bounded, cohort-controlled inferred open-jaw journey rule. The new exception
requires unique adjacent complete self-backed legs, the exact same origin and
return airport, known same-country away airports within 200 km, and a gap from
four hours through seven days. It does not create transport, merge booking
references, or change the general 150 km rule. Its grouping remains an inference,
not source-confirmed ground travel. Both normal clustering and affected-trip
expansion require the same checks.

All 4,611 remaining indexed Grant originals were separately captured with zero
provider errors and verified on/off VM. Together with the earlier captures,
this covers all 4,948 initial indexed originals plus two additional originals.
The capture was read-only. Its full-table hash check is explicitly **false**:
concurrent `dream_google_identities.refresh_after` updates affected 65 of 97
rows, while every other table stayed equal. This is not waived or reported as
an all-database equality check. Captured attachment bytes were not additionally
downloaded; the 25 attachment-bearing messages were reviewed using their visible
context and filenames, with no apparent flight-itinerary attachment found.

Those 4,611 bodies produced no flights under the old or new parser. A newly
introduced MIME-selection path did create 18 unnecessary internal review
outcomes, with no itinerary/inbox evidence writes. The narrower admission guard
eliminates those outcomes while preserving all flight, document, partial and
carrier facts across the 385 focused and 294 earlier positive source cases.
Final combined-candidate validation is still pending.

Candidate v6 passed 3,617 tests (five skipped and three separately verified
database checks deselected) and its focused first pass recovered the ten
source-reviewed Grant schedules with the intended five journeys, plus the
unchanged legacy sparse row. It is nevertheless rejected: an independent
synthetic test found that a receipt containing an existing public-trip flight
and a new return flight could append the return to the public trip. The actual
six-account snapshot has no public trips, shares, or manually/review-created
segments, so the real-data replay alone could not exercise this boundary.
The disposable v6 replay was stopped after its first pass; its incomplete
repeats are not acceptance evidence.

V7 is under review. It keeps protected trips available for existing-flight
matching and negative-decision checks while forbidding insertion of new flights
into those trips. This covers public, manual, reviewed, shared, and explicitly
locked membership. Existing source-origin protection must survive metadata
refreshes. Accepted schedule changes to an existing protected member refresh
that trip's bounds without changing its title, visibility, membership, or
unchanged/held rows. The final relevant 17-file regression suite passed 542
tests. Independent review passed 173 focused tests and nine protected-bounds
probes, each with three stable repeats across enabled, disabled, and unlisted
policies. The frozen v7 archive is
`df864387b3b591d22c2fb96a47fc94c3095574ca0e4bdc270f53cdeae5fc4211`.
Its full exact-interpreter suite passed 3,689 tests (five environment/network
skips and three separately verified database checks deselected) in 232.39 wall
seconds. All 245 application/test file hashes remained unchanged and all 103
application hashes matched the archive. The first focused PostgreSQL pass
matched every active flight and trip row from v6, including the intended
open-jaw membership improvement; all ten complete Grant legs and seven new
Nathan legs were independently source-reviewed. Fresh-copy repeat, broad,
bounded, and first-import checks are still pending. Production remains unchanged.

The focused v7 replay subsequently completed: all worker/probe calls completed
as expected, all three disconnected accounts avoided Gmail access, and every
other-account boundary was preserved. Raw strict differences remain recorded:
four source-reviewed first-pass retirements, 37 message and five history changes
on pass two, zero changes on pass three, and 353 message tier/screen markers on
the first ordinary cached sync. The five history rows do not recur; four are
geometry SRID serialization differences and one an unchanged trip snapshot.
No active flight/trip rows change on these repeats. These observations do not
replace the separate ordinary bounded-scan convergence requirement.

V7 is held before the broad replay. An original-source check of a Capital One
connection found a general city-lookup ambiguity: a printed Miami layover was
rejected even though adjacent flight cards explicitly establish MIA and the
printed 70-minute duration matches both local clocks. Normalizing the first leg
while holding the second leaves a false 53-minute overlap in legacy rows. A
source-constrained airport/place validation and plural reference-heading fix
are being prepared as v8. The separate legacy EVA overlap remains a reviewed
data gap: correct normalization of one leg exposes the earlier wrong-route/
wrong-date row. Overlap alone is not authority to delete or rewrite that row.

V8 is frozen as
`443f9e1b4e4a606545acb07223b88ff673cddc982d7d1994c4670ff6976ff37e`.
Its 3,711-test suite passed with five environment/network skips and three
separately verified database checks deselected; all 246 application/test hashes
remained unchanged. Only the parser and reference-field helper differ from v7.
The 679-source preparation comparison found eight source-supported connection
improvements, no lost/newly held legs, and no gate changes. All 385 focused
originals keep their exact flight facts; nine change only the top-level message
reference after removal of the false plural-heading value. Those references are
worker-consumed, so a fresh v8 worker replay is required rather than treating
the completed v7 replay as final-version proof. Broad body shadow, worker,
bounded recovery, cold import, and specific QA-only legacy repair checks remain
in progress or pending.

The complete v8 ordinary-preparation shadow covered all 24,418 available full
originals and the separate 4,611 Grant negative originals, with zero exceptions,
blocked calls, or input/code hash drift. It found additional release blockers
outside the earlier positive-source sample: two Expedia change notices select
obsolete clocks preceding explicit `(change)` values; four complete named
Southwest itineraries are skipped; three wellness newsletters create empty
review outcomes from merged AM/clock tokens or weekday abbreviations treated as
airport codes. The four Southwest messages contain an explicit body nested in
an unclosed head; removing the head discards both itinerary and passenger
evidence. Body-only diagnostics recover all nine existing legs as self-owned,
so name matching must not be loosened. V8 remains rejected for release while
these general parsing/visible-content errors are corrected. Two unavailable
historical originals remain explicitly unavailable; no contents were invented.

The first v9 shadow also covered all 29,029 captured originals without errors or
network access. It restored the four malformed Southwest messages and removed
the empty newsletter/utility review outcomes. Independent review then found
additional correctness gates: hidden/inert JSON-LD could bypass visible-content
checks; one Alaska card omitted an explicitly named companion; and two forwarded
Priceline receipts produced date cross-products instead of their four printed
legs. The last case also lost visible passenger-label recognition during HTML
cleanup. Restoring ownership over those incorrect candidates is not acceptable.
The candidate must use bounded printed-card dates and passengers, preserve normal
head JSON-LD, and reject hidden/inert metadata. This interim shadow is retained
as diagnostic evidence, not final v9 acceptance. Production remains unchanged.

Review of all six matching forwarded Priceline receipts also identified a later
source-backed schedule revision, a separate one-way ticket, and one contradictory
date layout that must remain unresolved. The new recovery selector admits only
the exact dated receipt-subject grammar under the existing metadata/original-read
limits; it does not add generic forwarded mail or invalidate the global parser
cache. A synthetic lifecycle test additionally reproduced retirement of two new
flights after their parent trip was published and an ambiguous post-departure
cancellation arrived in a later worker. Parent-trip protection and stable-repeat
coverage are required before freezing the next candidate.

Those focused v9 checks now pass. All 24 arrival orders of the four original
Priceline receipts produce the same four latest flights, keep existing IDs and
old observations, and settle to three identical subsequent states. On the seeded
initial-account copy, the two legacy Emirates rows remain unchanged and no extra
Emirates flight is created. This is a conservative hold, not a repair or proof
that the legacy itinerary is correct. The seeded check covers trip, segment,
observation, cancellation and identity data; the full-table worker replay remains
required. Independent checks also confirm companion retention for both named
travelers in the Alaska and United receipts and prevent ambiguous post-departure
cancellations from retiring flights in protected trips.

The sealed event-time comparison covers 1,634 admitted originals. It preserves
every cancellation/classification decision and every previously exact event
time, adding only 18 source-verified original dates and 68 provenance-only
records. Explicitly quoted original headers must supply a consistent sender,
subject and date; nested replies, incomplete headers and ambiguous timezones
cannot become revision authority. The full 29,029-original shadow and final
candidate suite are running before the next immutable worker replay.

The first complete-return comparison rejected two further roster regressions:
a visible Delta `Passenger Info / NAME` section was consumed as the name
"Info", and an Alaska information-section boundary made a complete named
roster incomplete, suppressing exact previous-ticket authority. Both now have
narrow format fixes and negative tests. The Alaska originals pass both arrival
orders with recovery disabled, unlisted and enabled; opt-in selects only the
current two legs, preserves the four source observations, and reaches three
identical subsequent states. A fresh full-source comparison is still required
on the combined fix. A separate Priceline source contains six printed cards
but conflicting outbound dates and duration; its old 18 generated variants
are not 18 real flights. It remains retained for review, including the three
coherent return cards that the current whole-document policy does not project.

V9 was frozen for diagnostics as
`86bc80e79ca0294dd06f8545af161d3ada8e341e06a1c7fa2e456c2652b77aa9`.
Its 4,208-test suite passed, with five retained skips and three
database checks exercised separately against the exact candidate. All 261
application/test file hashes remained unchanged. The final source comparison
covered 29,029 originals without exceptions, network calls or input drift.
The isolated PostGIS, repeated migration and repeated seed checks passed.

V9 is nevertheless rejected for release. Its eight PostgreSQL concurrency
workloads passed 2,100 imports, but an additional fresh-process protected-trip
test exposed duplicate conflict annotations: the same UTC event serializes
without an offset before persistence and with `+00:00` after PostgreSQL reload.
Two segments receive duplicate annotations and six history rows are appended;
physical flight facts, trip membership and existing immutable evidence stay
unchanged. Independent review confirmed a product idempotence defect, not a
test-harness issue. V9 evidence and its ongoing focused replay are retained.
A separate v10 candidate will canonicalize conflict timestamp comparison while
preserving existing annotations, and must pass the corrected reproduction and
the remaining account-level checks. No production change was made.

V10 now passes the PostgreSQL reproduction across 30 fresh-process cases,
including protected trips, exact ticket revision order and opt-in controls. It
normalizes only valid conflict event timestamps for comparison; other identity
fields and existing stored annotations remain unchanged. Its frozen archive is
`2af6c33a417109517a8dc4fe0dc5fd4e4f7715f36b37932b9abc6a3dbaae29aa`.
The final suite passed 4,289 tests with all 262 application/test hashes stable;
the five retained skips and three database checks are recorded separately.
Repeated migrations, PostGIS availability and repeated seeding also passed on
a separate isolated database using the exact 107 application files. Full account
replays remain required before acceptance; these focused results do not override
the retained source-backed legacy correctness gaps.

The frozen V10 preparation pass covered all 29,029 originals with exact returned
field equality to the final source-reviewed V9 output, zero errors/network
attempts, and unchanged input/application hashes. Its final local PostgreSQL
run also passed 2,100 imports across eight workloads and the 30 additional
cross-process cases. All 25 unrelated synthetic accounts stayed unchanged;
four overlapping jobs were blocked without writes, interruption rolled back,
and retry produced no duplicate or loss. Three settled repeats preserved the
entire state. Measured synthetic overhead was 4.74–14.47%; this is not a Gmail,
Celery, Oracle capacity, or end-to-end scan-speed measurement.

The five suite skips are one eager Celery example without a Redis URL and four
preexisting fixture exclusions: a PDF-only boarding pass, a Spanish gate notice
whose frozen date was redacted, and two check-in messages with no printed route.
These are coverage limitations, not passing parser cases. The three separately
executed database checks are PostGIS, migrations and idempotent seeding.

The focused V10 real-worker replay is complete: 12 connected jobs and three
disconnected-account probes completed as expected, with all six account
boundaries preserved and no worker, input-integrity or network-guard failures.
The three probes made no Gmail calls. All ten complete Grant additions are
source-backed; the four incomplete legs remain held. Existing other-traveler
items, links and observations survive unchanged. The third forced pass changes
no product rows or history; the cached pass changes only message processing
markers. Its raw 384 strict flags remain recorded (four reviewed other-traveler
removals, 40 finite second-pass changes and 340 cached marker changes), not
converted into an all-clear. The legacy sparse row, wrong-date projection and
old overlap still require their separately scoped review. The broad V10 worker
replay has started from the original verified backup.

The broad V10 run exposed a performance regression: Nathan's first ordinary
pass took about 29 minutes versus 17 minutes for the frozen baseline. V10 is
therefore rejected for production despite its focused correctness results.
Read-only profiling found the new airline-partial hook decoding MIME bodies
even for domains whose extraction branches always return no evidence. V11
moves that same domain check before decoding; the government eTravel fallback
still runs independently. Independent comparison of all 29,043 captured
originals found identical complete evidence objects and source fingerprints,
including all 12 positives. MIME calls fell from 29,046 to 475, and isolated
local hook CPU from 274.06 to 9.78 seconds. This is not yet proof of actual
worker latency: V11 still requires its frozen suite and account worker tests.
The V10 run and failed timing remain retained, not relabeled as V11 results.

The broad V10 first pass is now closed for all three captured inboxes and all
six account boundaries. Elisha retained all 18 physical flight IDs and facts,
all ten trip rows, and every preexisting immutable evidence/inbox row. Her scan
also regressed in duration (1,081.725 versus 559.267 seconds), confirming the
performance rejection. After the complete first-pass checkpoints were copied
and verified, the rejected QA worker was interrupted explicitly; its partial
second pass, raw exit, logs and stop receipt are retained. It is not a completed
three-pass or cached acceptance run. Production health and configuration remained
unchanged, with no running imports or broker backlog.

Independent source review also rejected V11 for unresolved correctness gaps:
an incomplete passenger roster could retain someone else's Emirates flights;
a United multi-passenger receipt could misclassify a real traveler; a Frontier
two-flight connection was still represented as one flight; and an explicitly
exchanged Southwest ticket could leave the old itinerary active. Testing the
Emirates case against manually protected/public trips exposed an existing
automatic OTHER-retirement path that lacked those protections. The new fixes
must pass both original and previously normalized projection snapshots, including
all existing evidence, before a new candidate can be frozen. Historical failed
proofs remain retained. A newly added companion item also had a prose fragment
misread as a booking reference; supported passenger identity does not waive that
invalid reference.

The bounded selector has been extended for the newly addressed Frontier,
Emirates and Aeromexico source shapes, including a tightly defined forwarded
Emirates check-in subject. This authorizes a bounded source read only, never
flight creation or passenger ownership. Comparing all 29,043 original indexed
message metadata rows added 78 eligible rows and removed none; limits stay at
25 originals and 100 metadata rows per scan. Every added shape still requires
body-level validation and an actual bounded-worker replay. In particular, an
older-only replay correctly preserves the newer Aeromexico schedule's authority
but cannot normalize the untouched legacy row without rereading that newer
source; the final test must include it rather than waive the mismatch.

The V12 working candidate now has source-backed service proofs for the United
multi-passenger receipt, the Emirates other-traveler classification, Frontier's
two numbered connection cards, and the explicit Southwest ticket exchange.
The updated Aeromexico timetable reads names only from its visible passenger
column and matches the printed date, flight, route and both clocks; its latest
schedule wins in 144 arrival-order/cohort cases. Manual, shared and protected
trip controls remain independent of this positive source authority.

Additional ticket-conflict tests found order-dependent extra flights and empty
trips. Conflicting successors now remain held when only unnamed corroborating
messages follow them, including source-backed clock changes. A separately
verified later named purchase retains its own authority. This applies only to
new projections carrying durable creation evidence, never to an inferred legacy
binding. Independent counterexamples and settled repeats pass; the frozen
whole-account worker validation is still required.

The same United service proof exposed a separate companion-retention failure:
two formats of the same person's name created two new inbox items for one
issued ticket. Preserving the owner's flight did not satisfy companion
acceptance. The rejected two-item output is retained. The correction under
test requires the same source-bound issued-ticket fingerprint, exact account
and dated flight/booking scope, and complete name-format equivalence; names
alone cannot merge recipients. Existing items, decisions, shares and evidence
must not be deleted or reassigned. No final V12 candidate is accepted yet.

The original-body comparison then rejected three United ownership regressions:
return seat routes appear after the frequent-flyer row, and a cancellation
marks the issued ticket as credited. Those exact layouts now preserve both
named legs without treating ancillary seat purchases as issued tickets. The
actual cancellation pairs pass in both arrival orders; old partial cancellation
evidence remains alongside the new complete scope. The companion case now has
one retained item linked to both receipts across all 18 tested orders/cohorts.

The new timetable identity path also exposed an older Ethiopian extraction
ambiguity: through-flight summaries compete with numbered stop rows, and one
source omits two printed stop rows from its parsed result. Promoting selected
rows created overlapping flights on the isolated copy. A coherence guard now
withholds this new authority for those layouts, leaving the previous extraction
and all original evidence intact. All 18 source-order/cohort cases preserve
every existing segment and trip row and reach three identical repeats. The
older aggregate defects remain explicitly unresolved; no broad legacy repair
was introduced to make the test pass. The two coherent Aeromexico sources still
retain their named traveler evidence.

The next whole-source comparison closed all 29,043 originals with unchanged
source/cache hashes and no ownership loss. It identified 35 changed originals,
including twelve additive, per-traveler issued-ticket fingerprints. Independent
inspection of all 78 newly eligible recovery sources caught one further defect:
an older Frontier passenger table continued into its invoice summary. Five
invoice headings entered traveler metadata and caused a new unassigned inbox
item. This was rejected even though the earlier parser already misread the same
body; newly admitting it through bounded recovery makes the consequence relevant
to this upgrade. The narrow correction requires the exact invoice summary and
typed airfare boundary. Its actual service replay preserves the existing flight
ID, correct clocks, all other account rows and three strict repeats, with no new
inbox item. The whole-source comparison and suite must be repeated after this fix.

The full intermediate suite recorded 4,990 passes and fourteen failures, with
all application/test hashes stable. All fourteen convergence fixtures inherited
a default personal note from an unrelated legacy-clock helper while expecting
automatic removal. The intended unprotected cases now explicitly omit that
note; their existing recovery assertions remain. Added both-order cases verify
that real personal notes preserve the entire old flight/trip and both evidence
records across three repeats. No application protection was weakened. The failed
suite remains retained, and the replacement suite has a distinct artifact name.

One newly eligible Frontier promotion already had a false review-required status
in the frozen initial database. Its current preparation is unchanged and actual
worker replays create no flight, trip, inbox or evidence rows. The inherited
review still appears in review/health surfaces; it is an acknowledged existing
quality issue, not a recovered flight, a new projection, or a claimed improvement.

### Additional isolation and load checks

The updated real-importer synthetic concurrency harness passed eight workloads:
10 and 25 concurrent accounts, each with 20 and 200 historical flights, with
recovery flags both off and on (2,100 message imports including repeats in each
final v7/v8 run). It
preserved historical rows and account boundaries, blocked four overlapping
same-account jobs without writes, rolled back an interrupted transaction, and
retried without duplicates. Application hashes remained unchanged. The dedicated
localhost-only PostgreSQL 16 cluster was stopped after the test; its data is
synthetic and retained. This does not measure Gmail, Celery, provider latency or
Oracle production throughput.

Read-only PostgreSQL plans for the bounded selector on the isolated 29,045-row
message snapshot took 73–144 ms across the three connected accounts. The limit
is 100 metadata rows returned/materialized per call; PostgreSQL can examine more
indexed account rows. This is a measured current-size result, not a constant-time
or future capacity guarantee.

## Release gates still open

1. Correct and independently test the recipient name-change and contextual-trip
   findings, then freeze a new candidate and complete its broad ordinary-sync
   replay from the same fresh backup as the old worker. V15 is stopped and
   rejected; its completed focused replay cannot substitute for this gate.
2. Review every removed/replaced flight ID and every new flight against original
   evidence; verify itinerary continuity, ownership, cancellation chronology,
   ticket exchanges, unrelated accounts, and immutable evidence preservation.
3. Require stable repeats or individually explain bounded metadata progress;
   do not waive unexplained itinerary or audit-history churn.
4. Verify incomplete and contradictory evidence cannot produce invented clocks,
   routes or passenger ownership. Preview and test the specific legacy sparse
   correction only on the isolated copy.
5. Compare parser work and scan duration, including fully cached repeats and
   failed/unavailable sources. A cached zero-parse scan alone is not acceptance.
6. Exercise bounded recovery without a global parser-version reset or full
   discovery rescan; verify its queue limits, source outcomes and two quiet
   follow-up passes.
7. Exercise fresh-account imports with recovery disabled, enabled but unlisted,
   and enabled for the account. Audit retained-ticket names and evidence in
   addition to personal flight/trip counts and repeat stability.
8. Preserve the completed final suite/source-comparison/PostgreSQL proofs and
   unchanged frozen application bytes, recheck live health, and record remaining
   evidence limitations before any rollout decision. Repeating passed checks is
   required only if their inputs change or a new finding invalidates them.

Private originals, logs, manifests and database snapshots remain in ignored
`artifacts/production-readiness-20261102`; they must not be committed or published.
