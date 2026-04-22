# Enable Gmail Flight Importing for TravelStrava

The backend currently sets up basic DB schemas (`User`, `Account`, `Trip`, `Segment`, `Message`) and authentication. However, it lacks the entire background ingestion side. This plan identifies the missing pieces in the database, application dependencies, background workers, and API routers to achieve the "Phase 0" deliverable of parsing trips from the user's Gmail.

## User Review Required

> [!WARNING]
> This feature introduces significant additions to the backend including the Celery worker queue, the Google API client, and the parsing engine.
> Note that `google-api-python-client`, `rapidfuzz`, and `beautifulsoup4` will be added to the project dependencies.

## Proposed Changes

---

### Database / Schema Enhancements

The current `models.py` matches the Phase 0 structure, EXCEPT it lacks a way to persist the parsing state over time.

#### [MODIFY] [models.py](file:///C:/Projects/Trotter/backend/app/models.py)
- **Add `SyncJob` model**: Create a table to track background import jobs per user with fields: `id` (String/UUID primary key), `user_id` (ForeignKey), `state` (String: pending, running, completed, failed), `scanned_count` (int), `parsed_count` (int), `segment_count` (int), `started_at`, and `updated_at`.
- **Alembic**: Generate and apply a new alembic migration for the `SyncJob` table.

---

### Application Dependencies

The application needs additional libraries to interface natively with the Gmail API and parse data heuristically.

#### [MODIFY] [pyproject.toml](file:///C:/Projects/Trotter/backend/pyproject.toml)
- **Add Packages**: 
  - `google-api-python-client` (Native interactions with the Gmail API).
  - `rapidfuzz` (Specified in the Phase 0 spec to handle identity matching with a token set ratio > 0.85).
  - `beautifulsoup4` (To strip HTML nodes when traversing unstructured email bodies).

---

### Ingestion Logic & Services

#### [NEW] [gmail.py](file:///C:/Projects/Trotter/backend/app/services/gmail.py)
- **Authentication**: Create logic to pull the user's `refresh_token_encrypted`, pipe it through `app/crypto.py` `decrypt_refresh_token()`, and build Google API Credentials.
- **Fetching**: Implement paginated querying using `google-api-python-client` via `service.users().messages().list(...)`. Provide queries to grab common categories containing boarding passes, PNRs, e-tickets, and itineraries. Include functions to retrieve structural payloads and transient bodies.

#### [NEW] [parser.py](file:///C:/Projects/Trotter/backend/app/services/parser.py)
- **JSON-LD Checking**: Traverse HTML text to locate `<script type="application/ld+json">` elements and extract `FlightReservation` properties.
- **ICS Parsing / Heuristics**: Examine properties for `VEVENT` and map airport locations and timestamps.
- **Identity Matching**: Utilize `rapidfuzz` to calculate match scores against the profile's name or saved aliases to flag as `message_status=REVIEW_REQUIRED` versus `ACCEPTED`.

#### [NEW] [builder.py](file:///C:/Projects/Trotter/backend/app/services/builder.py)
- Process accepted payloads into raw `Segment` SQLAlchemy rows. Use distance libraries or fallback to SQL commands during insert to populate the `geom` LINESTRING using `ST_LengthSpheroid`. Group closely spaced segments (48 hours or shared PNR) into `Trip` records.

---

### Workers & Tasks

#### [NEW] [import_tasks.py](file:///C:/Projects/Trotter/backend/app/tasks/import_tasks.py)
- **Celery Task Registration**: Create a `@celery_app.task` named `run_gmail_import(job_id: str, user_id: int)`.
- **Task Lifecycle**: 
  1. Retrieve `SyncJob` and mark it `running`.
  2. Invoke `gmail.py` service to fetch page-by-page.
  3. Dispatch raw messages to the `parser.py` engine.
  4. Frequently commit updates to the `SyncJob` row (incrementing `scanned_count`, `parsed_count`, and `segment_count`).
  5. Mark job as `completed` when done, dropping transient email bodies.

---

### API Routers

#### [NEW] [ingest.py](file:///C:/Projects/Trotter/backend/app/routers/ingest.py)
- `POST /ingest/gmail/import`: Requires Auth token -> Initializes a new `SyncJob` -> triggers `run_gmail_import` Celery background worker -> returns `{"job_id": str}`.
- `GET /ingest/jobs/{job_id}`: Query state by UUID and return `{"state", "scanned_count", "parsed_count", "segment_count", "started_at", "updated_at"}`.

#### [MODIFY] [main.py](file:///C:/Projects/Trotter/backend/app/main.py)
- Incorporate `app.include_router(ingest_router)` to expose these endpoints.

## Open Questions

> [!IMPORTANT]
> 1. Should we add `trips.py` routers (to list/view trips) and `review.py` routers (to handle ambiguous messages) now as well, to fully complete Phase 0 backend?
> 2. How are you currently managing the local Dev server and Redis? (Just `make map` and `docker-compose up`?)

## Verification Plan

### Automated Tests
- The user's `TESTS.md` demands parsing unit tests that can parse a dummy airline JSON-LD fixture correctly.
- Add an API test verifying the `POST /ingest/gmail/import` route correctly starts a celery task and creates the `SyncJob` tracking database row.

### Manual Verification
- We will start the backend (`uvicorn app.main:app`), log an authenticated user token, submit the POST ingest route via cURL or Postman, and inspect the db (`test.db`/Postgres) to ensure rows exist and progress counts reflect iterations.
