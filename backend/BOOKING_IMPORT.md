# Booking reconciliation

Parser version 24 separates extracted flight facts from the active itinerary.

## Import behavior

- `parse_email` keeps all flights, traveler names and supporting evidence. Ownership is `self`, `other` or `unknown`; receiving or paying for an email does not establish passenger ownership. Shared bookings count when the account holder is one of the travelers.
- `apply_booking_message` is the common mailbox policy for ordinary sync, stale-message reparse and the repair script. Every call includes the provider message ID. Unknown ownership is held for review, or linked to verified evidence for the same booking and dated flight. It does not erase an existing legacy flight merely because a new parse is uncertain.
- Explicit cancellation evidence is scoped to booking and dated legs. Negated, conditional, requested, quoted, ambiguously forwarded and unclear partial cancellations cannot remove active travel. Old confirmations cannot resurrect a canceled booking. A truly newer confirmation may establish a rebooking; explicit user corrections take precedence over email replay.
- Booking observations and cancellation events are retained. Complete trip and segment snapshots are saved in the same transaction before changing the active projection. Historical IDs are not foreign keys to the active rows, so reassigning or removing those rows does not erase their history.
- Source-backed imports recluster only affected journeys and connected, verified imported travel. They do not run legacy archive-wide cleanup. Enrichment is limited to the imported segment IDs and snapshots any changes.
- A per-user lock covers import and repair across message commits. PostgreSQL uses a dedicated advisory-lock connection; SQLite uses an OS file lock. Worker failures roll back the current message before recording failure. Previously committed messages remain safe to replay.

Direct builder calls without a source message ID retain legacy behavior for compatibility. New mailbox integrations must use `apply_booking_message`, rather than calling the legacy builder or full rebuild functions directly.

## Review API

All endpoints require the current user's authentication. An observation belonging to another account returns 404.

| Endpoint | Purpose |
| --- | --- |
| `GET /ingest/unparsed-candidates` | Messages awaiting review, including the reason |
| `GET /ingest/booking-observations` | Paginated extracted facts and effective user decisions; optional `source_message_id` filter |
| `POST /ingest/booking-observations/{id}/decision` | Body `{"decision":"self"}`, `"other"` or `"canceled"`; records a durable decision and applies the exact flight correction atomically |
| `GET /ingest/travel-name-aliases` | Approved traveler-name aliases |
| `PUT /ingest/travel-name-aliases` | Body `{"aliases":["Alex J Avery"]}`; validates and replaces approved aliases |

Incomplete observations remain held when an exact correction cannot be applied safely. The API returns 422 with the missing information. A concurrent import returns 409. These backend endpoints do not add a mobile review interface.

## Migration and operation

Apply Alembic migration `0008_booking_ledger` before starting the updated backend. It adds three ledger/history tables and `users.travel_name_aliases`; existing flight, trip and message rows are unchanged. Preserve a database backup before upgrading an existing installation.

The migration deliberately refuses a destructive downgrade. Older application code can run with the additive tables left in place. Do not drop evidence tables as part of a code rollback.

`scripts/rebuild_flight_segments.py --user-email <account> --dry-run` fetches and parses without changing saved travel. Its `--apply` mode backs up the graph and applies the same scoped policy without clearing the archive. A failed fetch or unresolved parse preserves the existing records. Preview repairs against a disposable database copy first; do not use a full resync as a substitute for reviewing a specific correction.

## Regression coverage

Tests cover shared and other-traveler bookings, aliases, payment/forwarding exclusions, cancellation order, newer rebooking, repeated imports, partial and ambiguous notices, exact scope, user decisions, authorization, concurrent workers, scoped enrichment, and injected transaction failures. The anonymized Orlando fixtures retain the original email structures and synthetic ticket-number lengths.

The September 2026 validation ran tests with dotenv disabled, no credentials, a disposable SQLite database and network access blocked. PostgreSQL migration and model DDL were compiled; a live PostgreSQL/PostGIS integration environment was not available. External Gmail and enrichment providers were mocked in worker tests.
