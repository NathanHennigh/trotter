# Repair preview identity fix — November 2, 2026

The PostgreSQL new-trip repair failure identified in the earlier retest is fixed.
Only the reviewed legacy-repair utility changes; normal parsing, scanning and
trip grouping code are unchanged. Nothing has been pushed or deployed.

## What changed

New trips in a preview now have stable references derived from their exact
sorted flight-record IDs. Existing trip IDs remain exact. The comparison checks
all trip and flight fields, including titles, dates, visibility, ownership and
metadata. Only the explicit identity of a new trip and its flight-to-trip
references are normalized; unrelated integers in metadata are unchanged.

Apply must match this complete reviewed projection. It returns a separate map
from each new-trip reference to its actual database ID and saves that exact
result for idempotent retries. Empty or ambiguous new-trip identities are
rejected. No database sequence is reset and no ID is reserved or guessed.

New manifests use format 3 in the existing table; no database migration is
needed. Previously applied format-2 manifests retain their cached results.
Pending format-2 plans must be prepared again rather than silently adopting
different comparison rules.

## Verification

- Full backend suite: **3,154 passed, four existing skips**. The four external
  standalone integration files remain excluded; PostgreSQL coverage below is
  recorded separately against the actual database engine.
- Reproduced the original PostgreSQL failure against the frozen prior utility.
- All 13 isolated PostgreSQL cases pass with the fix. A split succeeds with
  zero or 25 unrelated-account ID allocations between preview and apply.
  Interruption after allocation rolls back exactly and a retry succeeds after
  another seven allocations. Actual returned IDs match the saved rows.
- Changes to schedules, titles, visibility, bounds, memberships, existing trip
  identity, flight counts and unrelated metadata still reject and roll back.
  Stale plans still reject. The local QA cluster was stopped and verified.
- Added 16 durable regression cases, including multiple new trips, unrelated
  account allocations, rollback/retry, metadata preservation, real mismatches
  and old-manifest compatibility. The existing 41 repair tests also pass.
- A fresh copied-data repair preserves the established result: Nathan has
  160 flights and 67 trips, consolidating only the two reviewed obsolete records
  with full snapshots and successor links. The complete projection and actual
  ID mapping were reconstructed independently and match the reviewed plan.
- Nine affected Nathan originals and 13 Elisha originals were processed in both
  source orders across three passes. Nathan stays at 160/67 with correction
  flags on and off; Elisha stays at 18/10. Repeated application and settled
  source replays leave all captured tables unchanged. Originals retain their
  hashes; no live inbox or production data was accessed.

The full captured-history checks from the preceding retest remain applicable to
the unchanged parser/scanner; they are not claimed as newly rerun here. This
retest directly exercises the changed repair path on both PostgreSQL and the
captured data.

## Evidence and release boundary

Private reports are under `artifacts/repair-trip-identity-20261102/`:
`postgres-baseline-result.json`, `postgres-candidate-result.json`,
`copied-data-summary.json` and `backend-tests.log`. The reports and captured data
remain ignored by Git.

Verified repair source SHA-256:
`2dc9cf1e740bbecdab45e0bc0bc08ad5ce5515a680a35eadfad69cb9395ca6a3`.

The known blocker is resolved. Production deployment and any real account repair
still require the fresh server backup, current-state preview and controlled
rollout described in the reconciliation report. No production action was
performed for this fix.
