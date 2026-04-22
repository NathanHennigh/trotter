# Phase 0 Implementation Plan and Task Tracker

This document enumerates the concrete tasks to deliver Phase 0. Android-first with iOS in mind; backend runs locally. Background import with progress API; progress UI may land later.

## Milestone 1: Repo scaffolding and CI (dev-local)

- [x] Initialize backend (FastAPI) project structure
- [x] Add Celery worker and Redis integration
- [x] Add Postgres and PostGIS via docker-compose
- [x] Configure Alembic migrations
 - [x] Set up Python tooling: black, isort, mypy, pytest
 - [x] Seed script scaffolding (`make migrate`, `make seed`)
 - [x] Environment templates `.env.example`

Tests

- [x] Docker services start and are healthy (DB PostGIS available via compose)
- [x] Alembic migrations apply cleanly on fresh DB; downgrade/upgrade cycle works
- [x] Linters and mypy run locally without errors
- [x] Unit test for `GET /health` added (FastAPI TestClient)

Progress details

- Backend skeleton added under `backend/` with FastAPI app and CORS
- Health router at `backend/app/routers/health.py` responding `{ "status": "ok" }`
- Poetry project configured in `backend/pyproject.toml`
- Test added at `backend/tests/test_health.py`
- Quickstart in `backend/README.md` with run and test commands
 - Celery app configured in `backend/app/celery_app.py`; example task at `backend/app/tasks/example.py`
 - Celery eager-mode integration test added at `backend/tests/test_celery_example.py` (skips if `REDIS_URL` unset)
 - Docs updated with Redis/Celery run instructions
 - Postgres+PostGIS service added (`docker-compose.yml`) with init SQL to enable extensions
 - SQLAlchemy connection helper and PostGIS verification `backend/app/db.py`
 - Test `backend/tests/test_db_postgis.py` (skips if `DATABASE_URL` unset)
 - Backend README updated with compose/run instructions and PostGIS verification snippet
 - Alembic configured (`backend/alembic.ini`, `backend/alembic/env.py`), base migration `0001_create_base_tables.py`
 - Makefile targets: `migrate`, `migrate-down`, `seed` (seeds dev user)
 - Migration smoke test `backend/tests/test_migrations_apply.py` (skips if `DATABASE_URL` unset)
 - Dev tooling configured: black/isort/mypy in `pyproject.toml`; Makefile targets `lint` and `fmt`
 - Lint presence tests `backend/tests/test_lint_config_present.py`
 - Seed script at `backend/app/seed.py` and Make target `make seed`; idempotent
 - Seed test `backend/tests/test_seed_script.py` (skips if `DATABASE_URL` unset)
 - Environment template documented in `README.md` (create `backend/.env` with DB/Redis/Google/Secrets)

## Milestone 2: Auth and accounts

- [x] Endpoint: `POST /auth/google` (exchange server auth code with PKCE, offline access)
- [x] Store `users` and `accounts` rows
- [x] Encrypt refresh token with AES-256-GCM using `ENCRYPTION_KEY`
- [x] Issue app JWT (short-lived) + refresh strategy for app sessions
- [x] Tests: auth flow happy path and token encryption/decryption

Tests

- [x] Exchange uses PKCE and requests offline access; stores refresh token
- [x] Refresh token is encrypted at rest and decrypts correctly with `ENCRYPTION_KEY`
- [x] App JWT verifies signature, expiry, and contains expected claims
- [x] Failure cases: invalid code, missing PKCE, insufficient scopes → 4xx

Progress details

- Google OAuth endpoint implemented at `backend/app/routers/auth.py`
- AES-256-GCM encryption utilities in `backend/app/crypto.py` with base64/hex key support
- JWT utilities in `backend/app/auth.py` with 24-hour default expiry for Phase 0
- SQLAlchemy models in `backend/app/models.py` for users, accounts, messages, trips, segments
- Comprehensive test coverage: 18 tests for crypto + JWT functionality
- Auth endpoint supports server auth code exchange with PKCE verification
- Refresh tokens encrypted at rest, JWT tokens for app sessions
- `/auth/me` endpoint for current user info retrieval
- Environment variables documented: GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, SECRET_KEY, ENCRYPTION_KEY

## Milestone 3: Data model and migrations

- [ ] Tables: `users`, `accounts`, `messages`, `trips`, `segments`
- [ ] Add enums and indexes: `messages.status`, unique `(user_id, provider_msg_id)`, unique `(trip_id, airline, flight_number, dep_time)`
- [ ] PostGIS extensions enabled
- [ ] Airports/airlines reference tables (seed from OurAirports/OpenFlights)
- [ ] Tests: migration up/down and constraints

Tests

- [ ] Unique constraints: `(user_id, provider_msg_id)`, `(trip_id, airline, flight_number, dep_time)`
- [ ] `messages.status` enum transitions valid
- [ ] PostGIS functions available; sample geometry insert succeeds
- [ ] Reference data seeded and basic lookups resolve airport tz

## Milestone 4: Gmail client and fetcher

- [ ] Google API client with retry/backoff (exponential + jitter)
- [ ] Broad candidate search (configurable query)
- [ ] Paged full-history listing (resumable via `nextPageToken`)
- [ ] Fetch metadata (From, Subject, internalDate) and transient bodies/attachments
- [ ] Respect rate limits; handle 429/5xx retries
- [ ] Tests: fixture-driven API stubs

Tests

- [ ] Paged listing traverses full history with `nextPageToken`
- [ ] Retry/backoff on 429/5xx with jitter (bounded attempts)
- [ ] Extract metadata (From, Subject, internalDate) accurately from fixtures
- [ ] Attachment fetch selective (.ics only) and size guardrails respected

## Milestone 5: Parser package

- [ ] JSON-LD extractor (FlightReservation incl. nested `reservationFor.flightNumber`)
- [ ] ICS parser (VEVENT start/end, LOCATION airports, TZID support)
- [ ] Heuristic fallback: airline code+number, 3-letter airports, PNR patterns
- [ ] Forwarded message unwrapping
- [ ] Identity match (RapidFuzz token_set_ratio ≥ 0.85) against profile name + aliases
- [ ] Segment builder: multi-leg → multiple segments; trip grouping (PNR or 48h)
- [ ] Distance calculation via PostGIS `ST_LengthSpheroid`
- [ ] Geometry generation: densified great-circle LINESTRING
- [ ] Tests: unit tests for all extractors and heuristics

Tests

- [ ] JSON-LD: underName, reservationNumber, nested `reservationFor.flightNumber`
- [ ] ICS: VEVENT start/end, LOCATION airports, TZID respected; local airport tz fallback
- [ ] Heuristics: airline code+number, airports, PNR; forwarded message unwrapping
- [ ] Identity: RapidFuzz threshold 0.85; alias handling; ambiguous → review_required
- [ ] Segment builder: multi-leg → multiple segments; trip grouping by PNR or 48h
- [ ] Distance and geometry: `ST_LengthSpheroid` matches expected km within epsilon; densified LINESTRING created

## Milestone 6: Ingestion jobs and idempotency

- [ ] `POST /ingest/gmail/import` → enqueue Celery job, return `job_id`
- [ ] Job runner: scan, parse, upsert with idempotency guards
- [ ] Progress model: scanned_count, parsed_count, segment_count, timestamps
- [ ] `GET /ingest/jobs/{job_id}` returns status
- [ ] Dedupe policy: unique message, unique segment per `(trip_id, airline, flight_number, dep_time)`
- [ ] Tests: property tests for dedupe; integration test from fixture → DB rows

Tests

- [ ] Start job returns `job_id`; status endpoint increments counts then completes
- [ ] Idempotent on re-run: no duplicate messages or segments inserted
- [ ] Resume behavior: job picks up from last page token on retry
- [ ] Property-based tests: duplicates and reordered messages do not duplicate segments

## Milestone 7: Trips API

- [ ] `GET /trips?year=YYYY` with totals and counts
- [ ] `GET /trips/{id}` with segments payload
- [ ] Tests: response shapes and filters

Tests

- [ ] Year filter returns only matching trips; totals match sum of segments
- [ ] Trip detail includes segments with expected fields; order chronological

## Milestone 8: Reviews workflow

- [ ] `GET /reviews` list with minimal fields
- [ ] `POST /reviews/{message_id}` body: `{ decision: 'mine' | 'not_mine' }`
- [ ] Update `messages.status` accordingly; on `not_mine`, persist stable hash for future skip
- [ ] Tests: review transitions

Tests

- [ ] `GET /reviews` lists review_required messages
- [ ] `POST /reviews/{message_id}` with `mine` → status=accepted; `not_mine` → status=ignored and hash stored
- [ ] Ignored hashes cause future duplicates to be skipped

## Milestone 9: React Native app (Android first)

- [x] Project setup (TypeScript, React Native CLI) with `react-native-config` for envs
- [x] Install and configure `@react-native-google-signin/google-signin` (server auth code)
- [⏸️] Install and configure `react-native-maplibre-gl/maps` (deferred - using placeholder)
- [x] Settings screen: Sign in, Import button, user info display
- [⏸️] Import flow: call start-job, store `job_id`, (later) poll status for progress UI (deferred - Phase 1)
- [x] Map screen: placeholder map with stats, ready for segments
- [x] Offline cache via `react-native-mmkv` for secure token storage
- [⏸️] (Later) Playback controls (1x/2x/4x) (Phase 1)

Tests

- [x] Unit: service layer calls for auth and API client (Jest)
- [x] Component: Settings screen renders actions and user info
- [⏸️] Integration (mocked network): sign-in → start import → poll job → render trips (Phase 1)
- [x] Offline: MMKV storage for JWT tokens and user data

Progress details

- React Native 0.73.9 TypeScript project initialized in `mobile/`
- Google Sign-In integration with server auth code exchange flow
- API client with backend communication (`http://10.0.2.2:8001` for Android emulator)
- Secure offline storage using MMKV with encryption
- Navigation with React Navigation bottom tabs (Map + Settings)
- Settings screen with backend status, Google Sign-In, and user info display
- Map screen with placeholder UI and stats cards (ready for flight data)
- Comprehensive service layer: API client, Google Auth, storage
- Jest tests configured for React Native with proper module transformations
- Android package name: `com.trotterandroid` (matches Google OAuth setup)
- Environment: Backend URL and Google client ID configured

Known Issues

- Android build requires JDK/Gradle configuration fixes (similar to earlier backend issues)
- Google OAuth Android client needs SHA-1 certificate fingerprint update
- MapLibre integration deferred to Phase 1 (placeholder map for now)

## Milestone 10: Dev experience and docs

- [ ] Local `docker-compose` for API, worker, DB, Redis
- [ ] `make import` convenience command (current user)
- [ ] Fixtures: `.eml` redacted samples for unit/integration tests
- [ ] README updates with API and architecture
- [ ] Devlog entry with scope and gaps

Tests

- [ ] `docker-compose up` brings stack healthy; `make import` succeeds on sample user
- [ ] Fixtures load in tests; CI passes full test suite

---

## Definition of Done (applies to every task)

- Code has unit tests and, where applicable, integration or property tests
- Linters, type-checking, and tests pass locally and in CI
- Documentation updated (README and/or inline docs)
- Idempotency and error cases covered; secrets not logged; PII minimized

---

## Idempotency and policy decisions

- Message uniqueness: `(user_id, provider_msg_id)`
- Segment uniqueness: `(trip_id, airline, flight_number, dep_time)`
- Trip grouping rule precedence: prefer PNR; fallback to 48h window
- Time handling: use email-provided times; respect TZID; otherwise local airport TZ
- No raw email bodies persisted; only metadata and normalized records

---

## Environment variables

- `DATABASE_URL`
- `REDIS_URL`
- `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`
- `GMAIL_SCOPES` (readonly)
- `SECRET_KEY` (JWT)
- `ENCRYPTION_KEY` (AES-256-GCM for refresh tokens in dev)

---

## Future (Phase 1+) considerations

- Gmail push notifications (Pub/Sub) for incremental updates
- Real-time progress via SSE/WebSocket
- KMS envelope encryption in prod
- iOS build and entitlement setup
- Custom map style and branding
- Reference data refresh pipeline



