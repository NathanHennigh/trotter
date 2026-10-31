# Flight import shadow audit — October 30, 2026

This is an offline replay and hardening report, not a production repair manifest. The deployed backend remains `5349b74` (parser 26). Candidate parser 27 is based on `de25438` in `codex/flight-replay-hardening`.

## Scope and safeguards

The frozen post-reconnection account contains 163 flights and 65 trips. The replay uses the real history worker against an isolated SQLite copy, with normal evidence gates, no forced parsing, and network calls disabled. It retains original message identities, events, passenger decisions, booking evidence, and cancellations. No new travel-name alias is assumed.

All 12,548 indexed message IDs are accounted for: 12,546 original messages were captured and two deleted marketing messages returned 404. The corpus includes extracted ticket documents; a readable owner-permission-encrypted PDF was recovered as exact original bytes and re-extracted through the bounded production extractor. Password-protected files remain rejected.

This is not complete mailbox-discovery coverage. A separate read-only, ID-only probe returned 10,000 messages over the supported history date range, including 8,922 not in the indexed manifest, with another page remaining. The mailbox profile reported 143,634 messages. These counts are not counts of missed flight emails. Broader discovery remains a separately budgeted background operation.

Raw email bodies, PDFs, passenger details, booking references, account snapshots, and detailed comparison reports remain in private ignored artifacts.

## Changes

- Require explicitly labeled, complete booking-reference tokens, with consistent compound-token boundaries in passenger ownership scoping. Footer prose, compound-ID fragments, and carrier names cannot become extra booking aliases. Preserve legitimate agency and airline references.
- Treat an unconfirmed fused middle-name variant as ambiguous rather than definitely another traveler. This does not establish personal ownership or change the account's aliases.
- Collect repeated traveler sections within the correct booking and flight. An incomplete shared manifest cannot establish exclusive ownership by another passenger. Exclude route and purchase-section labels from passenger names.
- Hold unproven collisions with legacy flights instead of inserting duplicates or merging unrelated references.
- Revisit retained evidence only when a new exact dated leg gains independent personal ownership proof, or when removing an other-passenger row unblocks an explicitly personal receipt. Queries are account-scoped and bounded; original event times, evidence hashes, cancellations, and manual decisions still apply.
- Accept detailed receipts with spelled-out airline names while retaining incomplete summaries for review. Do not create flights from a stop count or another flight's endpoint.
- Resolve arrival dates only from a unique match between the individual flight's printed duration and its airport-local clocks. Total journey time, layovers, and neighboring flight blocks cannot supply that proof. Conflicts remain held.
- Preserve the boundary between completed round trips that return to their own starting airport before a later departure, even when the account's most-used airport is elsewhere.

## Validation

- Focused identity, booking, date-evidence, and trip-boundary checks passed, with independent review; all are included in the final suite below.
- Frozen candidate backend suite: 2,559 passed, four existing skips, 122.24 seconds. PostgreSQL/PostGIS, standalone Celery, migration-apply, and seed smoke files were excluded from this offline run; this is not a new production-deployment certification.
- The final complete two-pass replay records SHA256 manifests of application source and dependency files before and after execution and fails if they change.
- Both complete 12,546-message passes finished with zero failed checkpoints and zero network attempts. Application/dependency source hashes remained unchanged across 89 files: `a48313f67ed95f77f37ae6c4d83d625b60861d067abf9368276333abf049f1c0`.
- All 20 independent verification assertions passed. The second pass made no material flight or trip changes and no changes to booking observations, cancellations, or travel-inbox evidence. Original immutable rows and manual decisions were preserved.

## Offline proposal

The isolated account changes from 163 flights / 65 trip containers to **162 flights / 68 trip containers**. These are proposed historical changes, not live account counts.

- Seven supported additions: five older recovered legs (2016–2021), the missing Houston–Washington leg of the known Orlando journey, and the user's own Washington return booking after an other-passenger projection is removed.
- Eight removals: six entries supported by other-passenger tickets and two explicitly canceled legs. Their source evidence remains retained.
- The protected JetBlue record is unchanged. Compact-middle-name flights and the shared Sun Country booking survive. Only the four confirmed personal Waco Bilt legs enter the personal itinerary. Charlotte and Tulum retain their separate original trip IDs, and the Japan flights match printed dates and durations.
- No orphan flights, duplicate dated-leg keys, or new basis-aware timing/physical-collision failures were introduced. This does not certify that all inherited wrong-date records have been repaired.
- Six old trip containers are regrouped or emptied and nine created. The Waco flights, title, and privacy survive in a new container. Newly recovered outbound legs reconnect an older return journey, and an existing Spain leg joins its surrounding trip. No visibility changes occur. Original trip values remain in immutable history.

Full replay, source classification, temporal diagnostics, and the independent verification are saved privately as `shadow-hardening-release-*` artifacts. The preparation benchmark below is separate from the replay's local cached-history runtime.

The final preparation benchmark uses the same 152 saved messages, full warm-up in persistent processes, and four alternating rounds. Frozen parser 26 took a median 12.957 seconds (12.841–13.058); final parser 27 took 13.887 seconds (13.759–13.989). The 7.2% total increase includes approximately 0.504 seconds spent processing two confirmations previously skipped, adding five extracted rows. Excluding those confirmations, paired overhead was 1.8–4.7%, with a median around 3.2%. The 50-ticket batch increased 3.2%; the 100-marketing-message batch increased 1.3%. This is a small measurable preparation cost, not a claim of zero slowdown. Both source hashes stayed unchanged, but a concurrent shadow replay adds load uncertainty. The benchmark does not measure or guarantee end-to-end production Gmail scan latency.

## Interpretation boundaries

An unchanged stored flight is not necessarily a fully correct historical itinerary. The source audit found an existing fabricated Philippines route/date, an existing wrong-date return record, and existing Philippines/Chicago and Orlando/Denver groupings that predate this upgrade. These must not be silently rewritten from timing assumptions alone. An unmarked legacy timestamp may represent a local clock; inferred timezone audits are diagnostic, not authority to mutate it.

Trip containers and generated titles can change when recovered legs reconnect a journey. Visibility is checked separately. The current trip schema does not record whether a title was manually edited, so retained history alone is not proof that all title changes would match user intent. A historical apply must review these changes explicitly.

Repeated source-link metadata is reported separately from material itinerary changes. Two flight rows gain corroborating source/name links or equivalent provenance representation on the second pass; their dates, route, ownership, trip membership, and verified date proof stay identical. Diagnostic message fields and audit-history snapshots also advance. “Idempotent itinerary and evidence” is therefore not an identical hash of the entire database or every metadata field.

A read-only production export at 00:29:43 UTC on October 31 matched every row in all 13 captured tables from the post-reconnection baseline. The temporary account import lock was then released successfully; normal scans can run again.

Production history has not been replaced by this replay. Any historical correction must use the persisted preview/apply procedure and be checked against the then-current account, with deployment validation completed separately.
