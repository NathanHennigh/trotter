# Controlled flight import rollout

Parser revision 26 normalizes only proven time bases. Stored times are UTC; the trips API serializes normalized endpoints with their airport-local offset so existing mobile clients retain their displayed dates and clocks. Unverified legacy rows retain their previous representation. Ambiguous DST times, incomplete routes, conflicting schedules, and unproven passenger ownership remain held evidence.

## Performance boundaries

- Normal recent-mail scans do not sweep historical stale parser versions.
- Historical discovery has its own queue, one worker, persisted page checkpoints, and a 20-second cooperative work budget. A pending interactive scan takes priority; each completed message is checkpointed.
- Enable history only for selected account IDs through `TROTTER_GMAIL_HISTORY_USER_IDS`. Empty disables it; `*` enables all eligible connected accounts. Keep the initial rollout scoped until latency and failures have been observed.
- Complete email bodies avoid PDF downloads. PDF fallback is bounded by attachment count, size, pages, process memory, and execution time; no OCR or paid model calls are introduced.
- Airport timezone conversion uses a cached local dataset, not network lookups.

## Release gates

1. Preserve the deployed source/image and take the established PostgreSQL backup.
2. Run the full backend regression suite and compare the same offline parser corpus before/after. Report parser timing separately from end-to-end Gmail scan duration.
3. Build the exact committed source into a tagged image. Test the additive migration and exact account repair against isolated PostgreSQL, including repeated apply, a fresh second preview, original segment IDs, and immutable evidence.
4. Deploy backend services with historical discovery disabled. Verify migrations, health, the installed parser revision, and local-time API serialization.
5. Use the persisted preview/apply procedure in `controlled-flight-repair.md` for any account repair. Do not substitute another account's tickets or discard uncertain evidence.
6. Enable historical discovery for the initial account only. Inspect queue progress, checkpoint advancement, normal scan responsiveness, and error rates before widening rollout.

## Rollback

Disable historical discovery first. Keep the additive tables; downgrading is unnecessary for application rollback and would discard repair history. Preserve the airport-local API serializer when rolling back the importer after any normalized UTC rows have been written. Otherwise old clients that display the ISO clock directly would show UTC as local time. A compatibility rollback image can contain the previous importer plus only the new display serializer and timezone data.

Do not restore a full database backup over newer unrelated user activity. Repair manifests and itinerary history retain the affected account's pre-change facts; any account rollback must be separately previewed against current records. Failed preview/apply operations roll back their own transactions, and repeated successful apply is idempotent.
