# Flight scan health report

Run from `backend` with the application's `DATABASE_URL` already present in the environment. Do not put credentials in command arguments or reports.

```sh
python scripts/scan_health_report.py --user-id 1 --user-id 9
python scripts/scan_health_report.py --user-id 1 --user-id 9 --json
python scripts/scan_health_report.py --all-users --json --fail-on-attention
```

The report runs only SQL reads, in a read-only transaction. PostgreSQL uses a consistent repeatable-read snapshot and a 60-second statement timeout. SQLite must be an existing file and is opened with `mode=ro` and `query_only`. No inbox, task broker, external API, or migration is invoked. The database role should still have the narrowest practical read access.

Exit status is `0` for a successful report, `2` for a report/configuration failure, and optionally `1` for operational attention when `--fail-on-attention` is set. Failures print a fixed diagnostic, without connection URLs, raw exceptions, or SQL parameters.

## Interpreting jobs and history checkpoints

- `--hours 24` includes terminal jobs updated within that window. Every pending or running job is included even when older; an abandoned old pending row is not hidden.
- `--stale-minutes 30` flags running jobs with no recent recorded update as **suspected stalled**. `--pending-minutes 15` flags pending jobs with no recent update. These are observations requiring investigation, not proof that a worker is dead or permission to restart it.
- History checkpoints include state, pending-message count, attempts, retry time, and expired leases. Message IDs and page tokens are omitted. A paused checkpoint or expired active lease requires attention.
- Failed jobs use fixed error categories, including Gmail reconnection, fetch failure, rate limit, timeout, and other failure. Free-form provider errors are never emitted.
- `--max-jobs 50` bounds detailed job rows; totals still cover the complete selected scope.

`started_at` is initialized on job creation and overwritten at worker start. Consequently, exact queue wait is unavailable. Terminal `updated_at - started_at` is labeled a **recorded span**, not guaranteed execution time: a deferred history job can complete without running the usual worker. Negative or missing durations are reported as unavailable. SQL pending counts are not the Celery broker queue depth. Parser phase timings and tier counters currently exist only in task results/logs, not these SQL records.

## Interpreting message outcomes

Message outcomes cover **all stored messages for the selected accounts**. Messages have neither a last-processed timestamp nor a job foreign key, so these are cumulative counts, not the results of a recent scan.

- `incomplete_evidence`: persisted partial-flight evidence identifies missing itinerary facts.
- `unsupported_or_unrecognized_format`: strong flight evidence yielded no segments. This does not prove the source contains every required itinerary fact.
- `ownership_review`: unresolved or conflicting passenger identity.
- `identity_schedule_or_protection_review`: ambiguous lineage, schedule, cancellation scope, or a protected existing record.
- `attachment_review` and `unconfirmed_candidate`: retained evidence needs a different kind of review.
- `resolved`, `ignored`, `pending`, and `unclassified_review`: remaining stored outcomes. Unknown free-form labels stay unknown; the report does not guess their meaning.

Accepted messages retaining someone else's flights are counted separately under `messages_retaining_other_travelers`; retaining those tickets is not treated as a failure. Review counts alone do not trigger the operational attention flag.

Carrier and template breakdowns use recognized structured labels already stored in parse evidence or booking observations. Carrier counts are distinct carriers per message; a message mentioning two carriers appears in both groups. No inference is made from sender addresses. Missing/unknown labels remain unknown, so these breakdowns are coverage indicators rather than a complete template inventory.

Reports omit raw subjects, bodies, sender addresses, passenger names, booking references, provider message IDs, authentication material, and page tokens. Internal account IDs and valid job UUIDs are retained for operations; unexpected job IDs are replaced with opaque hashes.

## Canary use

Capture a report immediately before a controlled scan and after its terminal state. Compare job counters alongside the change in cumulative message outcomes, and investigate any new failed/stalled rows. Do not interpret cumulative count differences as exact per-job throughput or latency. Check flight/trip preservation separately using the existing reconciliation validation tools.

The report does not enable recovery features. All four recovery master switches still require the shared `FLIGHT_IMPORT_RECOVERY_USER_IDS` cohort; a true master switch alone is not an all-account rollout.
