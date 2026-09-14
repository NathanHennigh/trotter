# Background Dreams locations

Migration `0010_dream_locations` adds one durable, owner-scoped location record per saved item. It does not update existing tables or saved content. Captions, names, categories, notes, board membership, and original provider evidence remain unchanged by lookup and backfill. Downgrade deliberately refuses to delete location evidence.

New saves, parse completion, and review edits queue work in the same database transaction. GET item responses only read saved state. A scheduler discovers up to 25 previously unprocessed named saves each minute, including older saves whose `needs_google_places_lookup` is false. This does not reparse captions. Missing names remain saved for ordinary review.

The dedicated `dream_locations` queue uses one worker process. Flight imports keep their existing default queue and worker. Jobs use a 120-second lease and compare the current identity and pin fingerprints before applying a result. Duplicate notifications are harmless; abandoned leases and lost broker notifications recover on subsequent scheduler ticks. Temporary failures retry with exponential delays, at most five attempts. Missing or rejected provider credentials report `blocked` and retry after six hours; an explicit retry can run sooner. Confident unique places resolve automatically; ambiguous choices require confirmation. Provider failures never delete saves or invent city-centre pins.

An exact saved coordinate URL or existing verified pin remains authoritative. A confirmed candidate survives retries, note/tag edits, and ordinary review decisions. Changes to place name, city, country, region, category, or an explicit pin invalidate the previous resolution, which is retained in its history. Coordinates and addresses from new Geoapify results live only on the additive resolution row. Existing latitude, longitude, and map-link API fields are populated from that evidence for compatibility.

## Configuration and deployment

Set `GEOAPIFY_API_KEY` explicitly in the server's protected `deploy/home-server.env`. Obtain it from the authorized provider account; do not copy legacy source-code defaults or put it in mobile/public environment variables. The new provider uses no default key and no Google Places fallback. Avoid commands that print the environment or expanded Compose configuration. Keep OpenStreetMap and Geoapify attribution visible where new location data is displayed, consistent with the provider plan.

Optional limits: `DREAM_LOCATION_ENABLED=true`, `DREAM_LOCATION_BATCH_SIZE=25` (maximum 100), and `DREAM_LOCATION_MAX_ATTEMPTS=5` (maximum 10). Disabling the feature pauses provider work without deleting queued records or saves.

Before rollout, take a verified PostgreSQL backup and rehearse `alembic upgrade head` on a restored copy. Compare every original table's row contents and schemas, then run synthetic worker/backfill checks on that copy. Apply migration 0010 before starting the updated API and workers. The normal `deploy/scripts/deploy.sh` builds and starts all Compose services, including the new `worker-locations` and `beat` services; it does not itself take a backup. Run exactly one beat instance. The separate service commands are:

```sh
celery -A app.celery_app.celery_app worker --queues=dream_locations --concurrency=1 --prefetch-multiplier=1 --hostname=locations@%h
celery -A app.celery_app.celery_app beat
```

Keep the existing default worker running for Gmail imports. After rollout, check `api`, `worker`, `worker-locations`, `beat`, and `redis` service health/status. Authenticated item reads should progress from `queued` through `running` to `resolved`, `needs_review`, `not_found`, or `blocked`; credentials are not proved valid by API readiness alone. Historical saves are picked up automatically in bounded batches, so no caption reimport or destructive repair command is needed.

## Authenticated API

- `POST /dream-items/{id}/locate`: queue/retry an unresolved item; returns `DreamItemOut`. Existing confirmed or resolved pins are preserved.
- `POST /dream-items/{id}/location-confirm` with `{ "candidate_id": "..." }`: confirm one current candidate belonging to this item; returns `DreamItemOut`. Foreign-owner IDs return 404; stale or unrelated candidates return 422.
- `POST /dreams/locate-missing` with optional `{ "item_ids": [1, 2] }`: queue named missing pins for those owned items; omitted IDs cover all of the user's saves. Returns `{ "queued": 2, "items": [...] }`. A request containing any inaccessible ID fails atomically with 404.

Item responses add `location_status`, `location_address`, `location_provider`, `location_candidates`, `location_message`, and `location_checked_at`. Status is null until a durable row exists (or `manual` when an exact saved pin already exists). Candidate responses contain only ID, name, address, coordinates, and a coordinate-based Google Maps link; internal scores, job leases, and resolution history are not exposed.

When a named save has no existing or resolved Maps URL, responses provide an encoded Google Maps text search for its name, city, and country. This read-only fallback never writes a saved URL or coordinates; numeric-looking names are explicitly treated as place searches. Unnamed saves receive no city-only fallback, and existing saved or resolved links take precedence.

## Offline verification

Run with `DATABASE_URL=sqlite:///:memory:` and an empty `GEOAPIFY_API_KEY`, from the repository root:

```sh
backend/.venv/Scripts/python.exe -m pytest backend/tests/test_dream_locations.py backend/tests/test_dream_location_schema.py backend/tests/test_dream_coordinates.py backend/tests/test_dreams.py backend/tests/test_dream_place_search.py -q
```

These tests use synthetic data and mock providers, including stale results, ownership, manual edits, lease recovery, retry bounds, lost broker messages, and full preservation of prior rows. PostgreSQL DDL compilation is covered locally; an actual PostgreSQL restored-copy rehearsal remains a separate rollout check.
