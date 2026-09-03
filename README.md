# TravelStrava Phase 0 Spec

## One-paragraph summary

TravelStrava is the Strava of travel: a private-by-default app that reconstructs your lifetime travel from flight emails, then turns it into a beautiful map, timeline, and achievements. In Phase 0 we ship a thin vertical slice that connects Google, imports Gmail flight emails in the background (full-history, resumable), parses them into structured segments, stores only structured fields and select metadata (no raw bodies at rest), and renders a working map view on Android. We keep iOS in mind for next phase without blocking Android delivery.

---

## Goal of Phase 0

From a fresh install on Android, a user signs in with Google, grants Gmail read-only access, and sees at least one real flight route from their inbox drawn on a map with basic trip details. Import runs in the background on the backend with a job status endpoint; the app can poll for progress (UI progress display may land after the core slice). The pipeline runs end to end with tests and docs.

## Home-server deployment

The production-style stack lives in `deploy/`. It runs FastAPI, Celery, Postgres/PostGIS, Redis, and an Expo web build behind an outbound-only Cloudflare Tunnel. See [deploy/README.md](deploy/README.md) for domain setup, SQLite migration, secrets, deployment, mobile builds, backups, and recovery. Oracle Cloud Always Free provisioning is covered in [deploy/OCI.md](deploy/OCI.md).

## Non-goals for Phase 0

No leaderboards, no badges, no tours, no publishing, no push webhooks, no Outlook, no location history. We will not persist raw email bodies.

---

## Tech stack for Phase 0

* Mobile: React Native (TypeScript), Android target first. iOS-compatible architecture (libs and auth flow iOS-ready) but no iOS build in Phase 0.
* Backend: FastAPI on local Docker for dev (Cloud Run later).
* Queue: Celery with Redis for local dev. Cloud task runner later.
* Database: Postgres with PostGIS.
* Storage: none required for Phase 0. Photos and assets arrive in later phases.
* Maps: MapLibre GL via `react-native-maplibre-gl`. PostGIS for geometry and distance.
* Auth: Google Sign-In on device → backend OAuth exchange (access_type=offline, PKCE). Scopes: gmail.readonly, openid, email, profile.
* Secrets: Refresh tokens encrypted with AES-256-GCM (libsodium/cryptography). Key via env var in dev; KMS-managed envelope encryption in prod (future).

---

## Data model for Phase 0

Minimal tables and fields to support the slice. We store only message metadata and parsed, normalized trip/segment data. Raw email bodies are processed in-memory and never stored at rest.

**users**

* id, email, name, home\_tz, created\_at

**accounts**

* user\_id, provider, refresh\_token\_encrypted, scopes, expires\_at

**messages**

* id, user\_id, provider\_msg\_id, internal\_ts, from\_domain\_hash, from\_email, subject, snippet\_sha256, status, ignored, created\_at
* status enum: pending | review_required | accepted | ignored
* unique(user\_id, provider\_msg\_id)
* raw bodies are never stored (fetched transiently for parsing, then discarded)

**trips**

* id, user\_id, title, start\_ts, end\_ts, visibility

**segments**

* id, trip\_id, mode, dep\_airport, arr\_airport, dep\_time, arr\_time, airline, flight\_number, pnr, distance\_km, geom, meta\_json
* unique(trip\_id, airline, flight\_number, dep\_time)
* geom is a LINESTRING in EPSG:4326

Example segment JSON returned by API

```json
{
  "id": "seg_123",
  "trip_id": "trip_001",
  "mode": "flight",
  "airline": "DL",
  "flight_number": "1203",
  "dep_airport": "JFK",
  "arr_airport": "LAX",
  "dep_time": "2024-05-01T14:30:00Z",
  "arr_time": "2024-05-01T18:00:00Z",
  "pnr": "AB12CD",
  "distance_km": 3974.7
}
```

---

## Identity match policy used in Phase 0

Accept a parsed flight if any of these are true. The user can change name and aliases in Settings.

1. JSON-LD underName matches profile name with fuzzy score at least 0.85 (RapidFuzz token_set_ratio).
2. Passenger list contains the profile name or a saved alias.
3. Message To or Delivered-To contains the user email and the traveler contact block shows that email or name.
   If ambiguous, mark the message as review\_required and allow the user to confirm or ignore. Ignored messages are hashed and skipped later.

---

## Ingestion and parsing pipeline for Phase 0

1. Auth and consent

   * Mobile uses Google Sign-In to obtain a server auth code (Android for now; iOS next).
   * Backend exchanges the code with PKCE, requests offline access, stores a user row and an accounts row with an encrypted refresh token.
2. Import job (background)

   * Client calls POST /ingest/gmail/import to start a job; receives a job_id.
   * Backend enqueues a Celery task to scan Gmail full history, page by page, resumable via nextPageToken.
   * Progress tracked as scanned_count, parsed_count, segment_count. Client may poll GET /ingest/jobs/{job_id}.
3. Fetch

   * Backend lists candidate messages using a broad query to maximize recall (tuned over time), e.g.:
     * category:updates OR category:purchases
     * keywords itinerary, "boarding pass", "e-ticket", "record locator", PNR, "confirmation number"
     * no strict date bound for initial full import; subsequent runs can be incremental.
   * For each candidate message id, fetch metadata (From, Subject, internalDate) and raw/HTML body transiently.
   * If attachments exist, fetch selectively (.ics, .pdf if parsable).
4. Parse

   * Prefer JSON-LD FlightReservation if present (including reservationFor/flightNumber nested patterns).
   * If no JSON-LD, parse .ics attachments (VEVENT start/end; LOCATION airports). Respect TZID when present; otherwise treat times as local to the departure/arrival airports.
   * Fallback heuristics in text (including forwarded blocks): airline code + number, 3-letter airports, common PNR formats, dates.
   * Each flight leg becomes a unique segment; multi-leg tickets share the same trip (PNR or 48h grouping).
5. Identity filter

   * Apply the policy above; ambiguous → review_required.
6. Upsert

   * Compute great-circle distance in PostGIS and store segment rows with geom.
   * Group segments into a trip if they share a PNR or fall within a 48 hour window. Title defaults to FirstCity to LastCity.
7. Cleanup

   * Discard any raw email body content after parsing. Keep only structured fields and message metadata (From, Subject, snippet hash).

---

## API for Phase 0

Endpoints are minimal and stable.

Auth

* POST /auth/google: mobile sign in. Returns app JWT.

Ingestion

* POST /ingest/gmail/import: start background import job (full history scan for first run, incremental thereafter). Returns { job_id }.
* GET /ingest/jobs/{job_id}: returns job status { state, scanned_count, parsed_count, segment_count, started_at, updated_at }.

Trips and segments

* GET /trips?year=YYYY: list trips with totals.
* GET /trips/{id}: includes segments with fields shown in the example JSON.

Review

* GET /reviews: list ambiguous items.
* POST /reviews/{message\_id}: body has decision mine or not\_mine. mine → status=accepted; not\_mine → status=ignored and message hash recorded for dedupe.

---

## Android app requirements for Phase 0

* Settings screen

  * Sign in with Google button
  * Import flights button that calls POST /ingest/gmail/import
  * (Optional later) Progress section showing job status (polled from GET /ingest/jobs/{job_id})
  * Profile name and alias list editor
* Map screen

  * World map using MapLibre
  * Polyline routes for all segments
  * Tap a segment to see airline, flight number, airports, and times
  * (Later) Play button reveals segments in chronological order with a simple speed control

---

## Acceptance criteria for Phase 0

* After signing in and starting import, at least one real flight for the user appears as a route on the map within a reasonable time on a dev account with real fixtures.
* Import runs as a background job; job status is queryable via API and reflects progress.
* No raw email bodies are persisted anywhere. Only structured fields and message metadata (From, Subject, snippet hash) exist in Postgres.
* Parser unit tests pass on a fixture set that includes airline direct, OTA, and a forwarded ticket. Each fixture has an expected normalized JSON.
* Integration test seeds a fixture email and results in a segment row and a trip row with a nonzero distance\_km and a LINESTRING geom.
* App can open without network and render the last known map view from cached data.

---

## Test plan for Phase 0

* Parser unit tests

  * JSON-LD extraction with underName and reservationNumber
  * ICS extraction with VEVENT start and end, LOCATION with airport codes (respect TZID)
  * Heuristic fallback with airline code plus number, airports, PNR
  * Forwarded block unwrapping markers like Begin forwarded message
* Property tests for dedupe

  * Duplicate messages for the same segment are not inserted twice
* API integration tests

  * Import route enqueues background job and returns job_id
  * Job status route returns progressing counts, then terminal success
  * GET trips and GET trips id return expected payloads

---

## Dev environment and config

* Environment variables

  * DATABASE\_URL
  * REDIS\_URL
  * GOOGLE\_CLIENT\_ID, GOOGLE\_CLIENT\_SECRET
  * GMAIL\_SCOPES set to readonly
  * SECRET\_KEY for JWT
  * ENCRYPTION\_KEY (32-byte key for token encryption)
  * ENCRYPTION\_KEY for refresh token encryption (dev). KMS config later.
* Local scripts

  * make migrate to run Alembic migrations
  * make seed to insert sample users
  * make import to run the pipeline for the current user

Environment template

Create `backend/.env` with contents like:

```
DATABASE_URL=postgresql+psycopg://trotter:trotter@localhost:5432/trotter
REDIS_URL=redis://localhost:6379/0
GOOGLE_CLIENT_ID=your-google-web-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your-google-web-client-secret
GMAIL_SCOPES=https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/userinfo.email https://www.googleapis.com/auth/userinfo.profile openid
SECRET_KEY=change-me-dev-secret
ENCRYPTION_KEY=change-me-32-byte-key
```

---

## Deliverables for Phase 0

* Backend repo with FastAPI, Celery worker, Postgres migrations, and a parser package
* React Native app with two screens and a working map (Android first; iOS-ready codepaths)
* Parser fixtures and test suite with a red or green report
* Devlog entry that documents scope, demo screenshots, and known gaps

---

## Known gaps left for next phase

* Gmail push notifications via Pub Sub
* Badges and leaderboards
* Tours, photos, publishing
* Outlook and forward-to ingestion
* Location history import
* Job progress UI polish and real-time updates (SSE/WebSocket)
* KMS-managed envelope encryption for secrets at rest
* iOS build and sign-in entitlements
* Airport/airline reference data refresh pipeline

---

## Geometry and distance choices (Phase 0)

* Distance: PostGIS `ST_LengthSpheroid` on geography for accuracy.
* Geometry: store a densified great-circle LINESTRING (segmentized on geography) to avoid straight-line artifacts in Web Mercator.

---

## Offline cache (Phase 0)

* Mobile caches last known `trips` and `segments` in a local store (e.g., MMKV or AsyncStorage; MMKV preferred). App renders from cache when offline.

---

## Testing

See `TESTS.md` for the full Phase 0 test plan, suites, and CI gates. Every task in `TASKS.md` includes corresponding tests and a Definition of Done requiring tests to pass.
