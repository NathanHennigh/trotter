# Independent recovery pilot — 2026-11-03

## Deployment state

The designated third tester registered as account **12** and connected Gmail.
Its normal initial import completed at 01:44:13 UTC: 4,948 messages checked,
20 parsed, six flights added across three trips, no job error. The recorded
span was 497.351 seconds. This is an initial discovery workload, not comparable
to the earlier cached recent-scan canaries.

The recovery cohort is now **1,9,12**, verified in API, main worker, history
worker, Dreams worker, location worker, and beat. All four independent master
switches remain enabled. History discovery remains separately limited to **9**.
Runtime image/source and schema are unchanged from the November 2 release.
No parser revision bump, app changes, historical discovery enrollment, or live
replay was performed.

Before enrollment, saved runtime/configuration snapshots and verified a fresh
backup both on and off the VM. Gracefully stopped producers and workers; every
worker exited 0 without OOM. Took another verified backup while drained:

- `trotter-2026-11-03_01-56-58Z.dump`
- SHA256 `199b9c2787944b4dba52ff638ea3bb40520d7d234c6814cc797e24f9d4e7bb6d`

Every modeled application table and all account counts matched exactly before
and after the one-value cohort edit. All six services restarted with matching
settings. All four queue canaries and public readiness passed; no restart loops
or new error/traceback lines appeared. The May 11 pending SQL job remains the
known baseline and is not current broker backlog.

## Global rollout is held

Independent review of 293 frozen originals, including four bounded extracted
documents and ten negative controls, found real correctness/coverage gaps in
the first import. All selected originals were retrieved; this selection is not
a claim of complete mailbox recall. Originals and detailed evidence remain in
ignored private artifacts, not this document.

Source-backed findings on the unchanged live baseline:

- Segment **242** is an unsupported Southwest entry inferred from a trip-level
  July 24–26 banner. No original supplies its July 26 DAL–MCI midnight departure,
  one-hour duration, or flight number.
- Segments **240/241**, WN4631/WN2540, have an explicit named cancellation and
  refunds. A later automated upcoming-trip reminder does not prove rebooking.
- Segment **243**, UA2656, has an explicit full-reservation cancellation before
  departure, with credit evidence and no captured subsequent reinstatement.
- Spirit segments **238/239** have direct named, timed original support.
- Six complete named flight facts were missed: AS3492/AS269, G42057/G42056,
  and DL439/DL487. Alaska literal-period separators defeat its existing shape
  parser; Allegiant passenger scope is lost around “confirmation number is”;
  the Delta itinerary sources produce no flight facts. Simply enabling the
  recovery switches does not fix these extraction/association problems.
- A superseded Alaska itinerary and a canceled 2023 Allegiant booking must not
  be recovered as additional active trips. Two Amex attachment reviews are
  hotel documents, not missing flight tickets. The Sun Country ANC–MSP–DFW
  return evidence lacks intermediate clocks and must remain incomplete.

These issues were present before account 12 was enrolled. Do not label them
as newly introduced by the configuration change. Do not silently remove or
repair them in production; retain originals and require reviewed fixes and
regression/backtest evidence before global enablement or a targeted repair.

## Paired validation completed; rollout acceptance failed

The off/on service replay used identical fresh database restores, the same
293 originals, runtime, runner and processing order. Each policy completed
three passes (879 message applications per policy), with zero external-network
attempts. Only the disposable PostgreSQL database was writable by the runner;
external access and real brokers were blocked.

| Measurement | Recovery off | Recovery on |
| --- | ---: | ---: |
| Recorded total replay seconds | 512.580 | 513.488 |
| Flights / trips after every pass | 6 / 3 | 6 / 3 |
| Sources requiring review / accepted | 264 / 29 | 264 / 29 |
| New history rows, passes 1 / 2 / 3 | 18 / 6 / 6 | 15 / 3 / 3 |
| Strict evidence-repeat acceptance | Failed | Failed |

Independent paired review confirmed:

- Every user's complete segment/trip rows equaled the frozen baseline after
  every pass: IDs, clocks, metadata and memberships were preserved exactly.
  Original immutable evidence, protected tables and unrelated application rows
  were preserved. No new duplicate facts or orphan segments appeared.
- Every source's parsed flights, builder results, message status and processing
  path matched off versus on. Neither policy corrected the canceled/phantom
  entries or recovered the six complete missed flight facts.
- Recovery on retained two stable Sun Country post-travel assertions without
  giving them passenger-ownership authority or constructing flights. Nine
  messages gained strict-enrichment annotations, all denying inheritance; two
  carrier-message annotations also changed. These are the only eleven persisted
  message differences between policies.
- Three sparse Southwest messages allocate then remove an empty candidate trip
  on every pass. New temporary IDs create distinct history snapshots. Off takes
  two snapshots per candidate; contextual rebuilding on takes one. This is
  actual storage non-idempotence, not unconditional logging, source loss, or
  an end-of-pass itinerary change. `third_evidence_stable=false` remains a valid
  acceptance failure in both policies.

The recorded timing difference is about 0.9 seconds across one paired run;
it is not a production capacity or latency claim. This selected-source service
diagnostic omits live Gmail discovery/current-version skips, real job scheduling,
PDF re-extraction and final enrichment. It is not equivalent to a forced
exact-reprocess worker job and does not establish full mailbox recall.

## Remaining gates and retained evidence

Before any global enrollment or historical correction:

1. Reject unsupported timed flights inferred from sparse trip banners or
   placeholder clocks; preserve the incomplete source instead.
2. Apply explicit named cancellations to all supported legs, and distinguish
   a later automated reminder from evidence of actual reinstatement/rebooking.
3. Add regression-backed Alaska/Delta format coverage and correct Allegiant
   passenger/booking association without weakening other-traveler separation.
4. Avoid creating empty candidate trips when an existing segment already
   determines the trip, so repeated processing does not grow history.
5. Backtest these fixes against fresh original evidence for accounts 1, 9 and
   12, reviewing every proposed correction and retaining incomplete evidence.
   Validate the actual worker path before a narrow source-backed live repair.

No live replay or flight repair was run in this audit. The cohort remains
**1,9,12**; global `*` was not enabled. Final public readiness and all four
worker queue canaries passed. All six backend services were verified running
the unchanged image and cohort after cleanup. No new failed scans appeared.

Paired reports, source evidence and backups remain in private ignored artifacts
under `artifacts/production-readiness-20261102/grant-pilot-20261103`, with a
matching remote directory below `/home/ubuntu/trotter-readiness-private-20261102`.
The complete QA report archive was copied off the VM and checksum-verified:
`dfa9ae6bc12906aea1cab145f50195497848bb38b39a9d3004fd7dafa87903f2`.
Only the named disposable `trotter-grantqa-db-20261103` container and internal
`trotter-grantqa-20261103` network were removed; retained evidence was preserved.
The signup/pilot follow-up ends after this report because the next step is
targeted parser work, not another unchanged rollout poll.
