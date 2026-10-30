# Controlled flight import repair

Repair uses the same `prepare_flight_message` parser as new mailbox imports. It accepts a fixed list of messages already owned by one account; it does not discover messages, borrow another account’s tickets, insert hand-written flights, edit aliases, or confirm passenger ownership on a user’s behalf.

## Preview

Use a dedicated database session and the current parser. Collect the exact original Gmail messages and, where needed, extracted ticket documents into a local bundle:

```json
{"messages": [{"full_msg": {"id": "original-provider-id"}, "documents": []}]}
```

The actual `full_msg` is the original Gmail API response. Documents use the shared extraction contract (`filename`, `attachment_id`, `part`, `sha256`, and numbered `pages` with text). Keep the source bundle private; the persisted manifest contains parsed flight facts and source digests, not raw email bodies or credentials.

```sh
python scripts/controlled_flight_repair.py --user-id ACCOUNT --preview-bundle private-source-bundle.json --output private-preview.json
```

Preparation runs a dry-run savepoint and rolls all itinerary/evidence changes back. Only the manifest and its exact preview are then committed. The terminal prints redacted counts, held reasons, and the plan hash; `--output` retains the detailed private preview. Review added flights, updated existing IDs, explicit trip-membership changes, held sources, trip counts, and preservation invariants before applying.

A changed departure date must not be merged just because the route and flight number are similar. Optional `--schedule-links links.json` explicitly links two source selectors:

```json
[{"from":{"message_id":101,"flight_number":"AA2787","departure_local_date":"2026-03-23"},"to":{"message_id":102,"flight_number":"AA2787","departure_local_date":"2026-03-24"}}]
```

Both selectors must belong to this manifest, share an explicit booking reference or alias, route and flight number, be within two days, and have demonstrably ordered original source times. The earlier source must affirmatively identify the account owner. Cancellation, manual hold, ambiguous passenger scope, or an active flight share prevents the link. Original evidence remains retained; only the later schedule is projected.

Forwarded receipts keep the original event separate from mailbox receipt time. When the full original date is explicit but its timezone is unknown, a conservative possible UTC interval can establish that a March 8 receipt precedes March 24 operational mail; it never invents an exact instant or a missing year. MIME plain/HTML alternatives count as one forwarded message. Unordered conflicting schedules remain held. Hashes are identities, not chronology.

## Apply

```sh
python scripts/controlled_flight_repair.py --user-id ACCOUNT --apply MANIFEST_ID --expect-plan-hash EXACT_REVIEWED_HASH --output private-result.json
```

Apply rechecks account/source ownership, manifest integrity, and the full relevant account fingerprint. If mail, aliases, cancellations, sharing, or itinerary state changed after preview, prepare a new preview. It runs under the per-user import lock and commits before releasing that lock. A clean dedicated session is required. The result must match the persisted preview exactly; any error rolls back the entire repair.

Existing segment IDs cannot be deleted. Reparsed times update a proven original leg in place, including corrections crossing a UTC calendar boundary. Original booking/cancellation observations and sharing records cannot change. A trip that merges is retained in the complete pre-repair history snapshot. No new duplicate booking legs are allowed. Reapplying an applied manifest returns the stored result without replaying mutations.

First verify on a local account clone and run the backend regression suite. This command does not create backups: take the established database backup before an authorized production apply. Held evidence is a review result, never a reason to bypass ownership or cancellation protection.
