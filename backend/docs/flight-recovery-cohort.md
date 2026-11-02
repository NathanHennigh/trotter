# Account-scoped flight recovery

The four optional recovery features require both a master switch and membership
in `FLIGHT_IMPORT_RECOVERY_USER_IDS`:

- `BOOKING_STRICT_ENRICHMENT_ENABLED`
- `CARRIER_TRAVEL_CORROBORATION_ENABLED`
- `BOOKING_LEG_RECONCILIATION_ENABLED`
- `BOOKING_CONTEXTUAL_TRIP_GROUPING_ENABLED`

All default to false. The cohort defaults to empty. Positive account IDs must be
comma-separated; malformed lists disable the entire cohort. A standalone `*`
is an explicit all-account enrollment and must not be used for a limited rollout.
The Gmail history-discovery allowlist is independent and is not widened by these
settings. Account IDs must be resolved and checked in the deployment's database.

Change the shared backend environment and recreate the backend containers to
change production enrollment. All API and worker processes must receive the
same switches. Removing an account or disabling a feature stops new recovery
authority; it does not delete previously recovered flights or their evidence.
The legacy duplicate-hold guard remains active for every account so opt-out
cannot introduce a second interpretation of a known ambiguous connection.

## Release procedure

1. Compare the running source to the last release, retain its image and environment,
   and create a verified PostgreSQL backup with an off-server copy.
2. Run the regression suite, the paired concurrency harness, and the scan-health
   report. Test the additive migration and target-account replay on an isolated
   restore of the fresh production backup.
3. Build an immutable, committed candidate. Enable only the reviewed account IDs.
   Preserve the existing history-discovery cohort and processing limits.
4. Verify identical images and enrollment across every backend process, API
   readiness, and unchanged account records across the image/schema switch.
5. Run bounded canary scans and inspect their recorded outcomes. Historical
   corrections require fresh, source-backed review; never copy obsolete row IDs
   from an old backtest without validating the current data.

The report is an operator command, not a scheduled notification. Run
`trotter-entrypoint python scripts/scan_health_report.py --all-users` inside the
API container, or select accounts with repeated `--user-id` options. Use `--json`
for a machine-readable snapshot and `--fail-on-attention` for an explicit health
gate. Suspected stale jobs are reported without changing them.

## Rollback boundaries

First disable the optional recovery flags or remove the cohort, then recreate
the services. An application rollback can retain the additive carrier-evidence
table and index. Keep the previous display-time compatibility code. Do not
downgrade the schema or restore a whole database over subsequent user activity.
Source observations, repair manifests, and itinerary history retain evidence
for any separately reviewed account correction.

The concurrency harness measures the parser/import/database workload on its
test machine. It does not establish Gmail quota capacity, provider latency, or
maximum production throughput. Those require observation during the cohort
rollout before enrollment expands.
