# Current-code retest — November 2, 2026

The limitation recorded below has since been [fixed and retested](repair-trip-identity-fix-2026-11-02.md).
This report preserves the original finding and its evidence.

Testing is complete. The parser and captured-inbox preservation checks pass,
but an additional PostgreSQL repair-tool case exposed a remaining limitation.
No application source or production data was changed during this retest.

## Passing checks

- The current backend matches all 326 files in the validated V9 manifest.
- The backend suite passed 3,138 tests with four existing skips. Its four
  external standalone integration files remain excluded; the local PostgreSQL
  rehearsal below is separately scoped.
- Both normal captured-history replays directly executed the current worktree:
  Nathan's 12,546 available originals preserve 160 flights and 67 trips;
  Elisha's 11,537 preserve 18 flights and 10 trips. Every captured account table
  is unchanged except the discovery scan timestamp. Two previously unavailable
  Nathan originals remain explicitly accounted for.
- Fresh imports, reviewed repair, repeated imports in both source orders, and
  enabled/disabled feature checks pass. Original snapshots, sources and PDF
  bytes retain their hashes. No live mailbox or Oracle service was accessed.
- A fresh isolated local PostgreSQL 16/PostGIS cluster passed migration
  0024 → 0025 → 0024 → 0025, preserving 37 existing tables and four synthetic
  records. Six repair cases and advisory-lock collision/release also passed.
  A reused SQLite assertion needed UTC-instant comparison for PostgreSQL's
  timezone-aware timestamps; the original failure log and corrected check are
  both retained. No product change was made for that harness difference.

## Confirmed limitation: repairs allocating a new trip

A repair preview that creates a new trip consumes a PostgreSQL sequence value.
Rolling back its savepoint does not rewind the sequence. Applying that preview
allocates a different trip ID, so the exact preview/apply membership comparison
raises `RepairConflict`.

The test confirms the entire account rolls back unchanged and the manifest
remains previewed. This is a blocked repair, not lost data. The reviewed Nathan
repair reuses existing trips and is unaffected, as are ordinary import paths
that do not use this preview/apply comparison. Plans requiring new trips need
this issue fixed and retested before use. Broad repair rollout is not cleared.

The disposable PostgreSQL cluster was stopped and its shutdown verified.
Other WSL services were not stopped. All replay processes completed before the
user-requested computer sleep was scheduled.

## Evidence

Private, Git-ignored reports:

- `artifacts/reconciliation-verification-20261102/fresh-verification-report.json`
- `artifacts/parser-retest-20261102/backend-tests.log`
- `artifacts/parser-retest-20261102/postgres-smoke-final.json`
- `artifacts/parser-retest-20261102/postgres-split-result.json`
- `artifacts/parser-retest-20261102/result.json`

No code, migration, feature flag or account repair was pushed or deployed.
