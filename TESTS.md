# Phase 0 Test Strategy and Cases

This document defines the test plan for Phase 0. Every task must land with tests. Use pytest for backend, golden fixtures for parser, and Jest + RNTL for mobile.

## Tooling

* Backend: pytest, hypothesis (property tests), httpx TestClient, custom stubs/fixtures for Google/Gmail, FactoryBoy for data
* Lint/type: ruff/flake8 or black+isort, mypy
* DB: Postgres with PostGIS in docker; test DB schema migrated per test session
* Mobile: Jest, react-native-testing-library (RNTL), React Native Jest preset

## Global fixtures

* Redacted `.eml` files for airlines, OTAs, and forwarded tickets
* ICS samples with TZID and without
* JSON-LD samples with `FlightReservation` and nested `reservationFor`

## Backend test suites

### 1) Health and scaffolding
* GET /health returns 200 json
* PostGIS extension is enabled; simple geometry query succeeds

### 2) Auth and accounts
* Exchange code with PKCE and offline access: stores encrypted refresh token
* Decrypt with `ENCRYPTION_KEY` yields original token
* JWT generation: signature valid, exp set, claims include `user_id`
* Error paths: invalid code, wrong verifier, missing scopes → 4xx

### 3) Data model and migrations
* Unique constraints enforced for `(user_id, provider_msg_id)` and `(trip_id, airline, flight_number, dep_time)`
* Enum transitions for `messages.status` allowed and invalid transitions rejected in service layer
* Airports/airlines reference lookups resolve tz and coordinates

### 4) Gmail client
* Paged listing iterates all pages; stops correctly on last page
* Retry/backoff on 429/5xx with jitter and max attempts
* Extracts From, Subject, internalDate, snippet; attachment filtering for .ics

### 5) Parser package
* JSON-LD: extracts airline, flight_number, airports, dep/arr times; underName match
* ICS: parses VEVENT start/end; LOCATION to airports; respects TZID; local airport tz fallback
* Heuristics: airline code+number, airports, PNR; forwarded block unwrap
* Identity: RapidFuzz score >= 0.85 accepted; below → review_required
* Segment build: multi-leg creates multiple segments under one trip (PNR or 48h)
* Distance/geometry: `ST_LengthSpheroid` within epsilon of known route; densified geom created

### 6) Ingestion jobs and idempotency
* `POST /ingest/gmail/import` returns `job_id`
* `GET /ingest/jobs/{job_id}` shows progress counters increasing and final success state
* Re-running import produces no duplicate messages/segments
* Resume starts from saved page token on retry
* Property tests: permutations of duplicate emails produce one set of segments

### 7) Trips API
* `GET /trips?year=` filters correctly; totals and counts match DB
* `GET /trips/{id}` returns segments ordered by time with specified fields

### 8) Reviews workflow
* `GET /reviews` lists pending review items
* `POST /reviews/{message_id}` with `mine` marks accepted; `not_mine` marks ignored and stores hash; future duplicates skipped

## Mobile test suites

### 9) Settings screen
* Renders sign-in, import buttons
* Start import stores `job_id`; (later) status polling updates UI state
* Aliases editor updates profile store

### 10) Map screen
* Renders polylines for segments from mock API
* Tap shows details pane with airline, number, airports, times
* Offline: renders from MMKV/AsyncStorage cache when API unavailable

## CI gates

* Run linters and mypy
* Start docker services; run backend tests against test DB
* Run React Native unit and component tests (Jest + RNTL)
* Artifacts: coverage reports for backend and app

## How to run tests locally (Windows)

Backend (venv + pip):

```
cd backend
python -m venv .venv
".\.venv\Scripts\python" -m pip install -U pip setuptools wheel
".\.venv\Scripts\python" -m pip install fastapi==0.115.0 uvicorn[standard]==0.30.0 pytest==8.2.0 httpx==0.27.0 celery[redis]==5.4.0 redis==5.0.1 sqlalchemy==2.0.31 alembic==1.13.2
".\.venv\Scripts\pytest" -q
```

Enable DB/Celery tests:

```
docker compose up -d db
set DATABASE_URL=postgresql+psycopg2://trotter:trotter@localhost:5432/trotter
".\.venv\Scripts\python" -m pip install psycopg2-binary==2.9.9
set REDIS_URL=redis://localhost:6379/0
".\.venv\Scripts\pytest" -q
```


