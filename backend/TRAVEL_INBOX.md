# Retained travel inbox

Trotter keeps other people's flight records privately in the importing user's
travel inbox. The original inbox API remains read-only. The separate explicit
sharing/invitation flow is described in [FLIGHT_SHARING.md](FLIGHT_SHARING.md).
It never matches accounts by name, sends emails automatically, or transfers an
airline ticket: an invited recipient accepts a copy of selected flight facts.

## Import behavior

- Every parsed flight is still saved in the immutable booking-observation ledger
  before personal-history decisions. The inbox now indexes that evidence at the
  same point, in the same transaction.
- An explicit applicable passenger name belonging to somebody else becomes a
  retained record. A shared booking keeps the owner's flight in their itinerary
  and retains separate companion records. Verified owner-only bookings do not
  create speculative companions.
- Unknown ownership, ambiguous scope, incomplete names and conflicting evidence
  remain unassigned and available for later review. The full original extraction
  remains in the ledger; no passenger evidence is discarded.
- Records have stable UUIDs, unique per owner, exact booking reference, dated
  flight leg, and literal passenger name. Name keys normalize Unicode, case and
  whitespace only; they do not merge nicknames or middle-name variants. Weak
  booking identities also include the source message to avoid unrelated merges.
- Every receipt/replay links to the retained record without duplicating it. A
  later named receipt can coexist with the original unassigned record, joined by
  the same flight key. It never deletes the original ID or evidence.
- Cancellation evidence changes the read status, never deletes the ticket.
  Unknown cancellation timing/scope or a later receipt after cancellation needs
  review. A personal itinerary decision does not claim or cancel a companion's
  ticket. An exact approved name can mark a record as belonging to the owner; this
  read projection does not add it to their itinerary.

The inbox service never writes trips, segments, country counts, passport stats,
or the existing ledger. Existing parser and personal-history rules still decide
which flights belong in the user's own travel history.

## Storage and reads

Migration `0009_travel_inbox` adds `travel_inbox_items` and
`travel_inbox_evidence`. Evidence links reference original booking observations;
they do not copy a shared booking's full manifest into each passenger record.
The service enforces same-owner linkage and uses the existing per-user import
lock. It commits only through its caller. The migration intentionally refuses a
destructive downgrade that would lose retained tickets.

- `GET /travel-inbox?limit=50&before_id=<cursor>` returns the current user's items
  and `next_cursor`; limit is 1–100. Pass that cursor as `before_id` for the next
  page. No query parameter can select another owner.
- `GET /travel-inbox/{id}` adds owner-only source observation/message pointers.
  A missing or another user's ID returns the same 404 response.
- Both endpoints require normal authentication and are read-only. They do not
  backfill, search for recipients, or return raw email content, payer fields or
  co-traveler manifests.

The current response includes the retained passenger name, flight facts, intake
reason projected from the newest source, and status (`retained`, `needs_review`,
`canceled`, `belongs_to_you`). A retained record is evidence, not proof of a
currently valid ticket. Names and booking references remain private owner data.

## Existing installations

Back up the database, apply `alembic upgrade head`, and restart backend/import
workers before using the new code. Set `DATABASE_URL` explicitly in the command
environment. From `backend`, preview the already saved observations:

```sh
python scripts/backfill_travel_inbox.py --user-id 1
```

The preview rolls back all new inbox writes. Add `--apply` to commit, or use
`--all-users` for all existing accounts. Each account is locked and processed in
its own transaction; reruns are idempotent. This command does not read Gmail or
reparse historical mail. It indexes evidence already retained in the ledger;
historical messages that predate that ledger require a separate normal reparse
to supply their missing observations.

## Sharing boundary

Stable retained-record IDs are the source of explicit shares. The sharing API
binds each invitation to an exact sign-in email and requires recipient acceptance.
Names never resolve to accounts. Its passenger-specific transfer allowlist is
separate from the owner-only inbox response. Booking references, message pointers,
email content, payment data and co-traveler manifests are excluded. The original
`/travel-inbox` routes still expose no sharing mutations.
