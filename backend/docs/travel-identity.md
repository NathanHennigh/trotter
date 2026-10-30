# Travel identity and retained-booking recovery

All endpoints require the signed-in user. Names and inbox records are scoped to that user's account; this never changes another passenger's account or sends an invitation.

## API

`GET /ingest/travel-name-aliases` returns:

```json
{
  "primary_name": "Example Traveler",
  "aliases": ["Example Previousname"],
  "confirmed": true,
  "onboarding_completed": false,
  "recovery": {
    "id": "uuid", "state": "queued", "checked": 0,
    "added": 0, "existing": 0, "needs_review": 0, "error": null
  }
}
```

`recovery` is null before a job exists. Its state is queued, running, completed, or failed. The main account name remains read-only here. Poll this endpoint while queued/running; refresh personal trips when a job completes.

- `PUT /ingest/travel-name-aliases` accepts `{ "aliases": [...], "confirmed": true }`. Existing clients omitting confirmed remain compatible. Names are explicitly user-confirmed; confirmation queues recovery without waiting for mailbox access. Saving the same names is idempotent unless new original booking evidence has arrived since the last completed check.
- `POST /ingest/travel-name-recovery` with `{}` retries confirmed names against retained evidence. It does not scan Gmail.
- `POST /ingest/travel-inbox/{item_id}/claim-self` accepts `{ "passenger_name": "name printed on the original item" }`. This adds that observed name as an alias and queues recovery. An edited assignment or a different name cannot claim the original ticket. Active or accepted sharing conflicts return 409.
- `POST /ingest/travel-onboarding/complete` with `{}` dismisses setup. It works when names or Gmail were skipped, and never confirms names or imports flights by itself.

Aliases allow up to 20 names, 100 characters each, with Unicode letters and normal name punctuation including airline slashes. NFKC normalization collapses whitespace and deduplicates case-insensitively. Requests during another itinerary import return 409; retry after that import finishes. Missing/foreign inbox records return 404; weak or mismatched claims return 422.

## Recovery safety and limits

Migration `0023_travel_name_recovery` follows `0022_ios_auth_identities`. It adds nullable user confirmation/setup timestamps and a recovery queue table. No existing account is confirmed automatically.

Celery beat discovers queued work every 15 seconds. Each worker processes at most 75 observations per atomic batch under the same per-user advisory lock as Gmail import. Original observations and timestamps remain immutable; new self-ownership observations link to their original source. Cursor, counts, and itinerary projection commit together. Interrupted batches roll back and retry without duplicate flights. Unexpected failures retry with increasing delays up to five attempts, then expose a generic error and manual retry. Lock contention waits for the next discovery sweep.

Only applicable traveler evidence with a full given/family name can recover a flight. Initials, payer names, ambiguous scopes, conflicting middle names, incomplete flight facts, held facts, explicit other/canceled/hold decisions, and cancellation evidence stay protected. `MAGNO/ELISHAFAITH` matches an explicitly confirmed `Elisha Faith Magno`; it does not guess that `ELISHAFAITH` or `ELISHABETH` is merely `Elisha`.

The newest receipt for an exact booking/dated leg takes precedence. If it lacks the earlier matching passenger evidence, the older record remains for review rather than projecting stale schedule information. A future enhancement could combine validated ownership provenance with newer schedule facts. Name recovery itself performs no mailbox, AI, Google, or other external calls. It does not import accepted shares again or turn synthesized recovery observations into new inbox tickets.

`checked` counts original observations inspected, not flights. `added` counts newly added personal segments; `existing` counts matching flights already present; `needs_review` counts matching evidence that could not safely be projected. Connections and trip grouping continue to use the established itinerary builder.
