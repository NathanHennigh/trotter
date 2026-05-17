# Instagram Share-to-Dreams Implementation Plan

This document outlines how to implement Trotter's Instagram Share-to-Dreams feature.

The feature lets users share an Instagram Reel or post into Trotter, where it becomes an organized Dream item. Trotter saves the source link, extracts travel details, identifies places or destinations, groups them into Dreams, attaches Google Maps results when confident, and marks uncertain items for review.

## Product Goal

Turn passive travel bookmarking into an actionable travel wishlist.

Today, users save travel inspiration in Instagram folders, screenshots, notes, texts, and browser tabs. Those saves are hard to search and rarely become real trips. Trotter should become the place where travel inspiration gets structured.

Core flow:

```text
User sees Instagram Reel/Post
-> taps Share
-> selects Trotter
-> Trotter saves the URL immediately
-> backend fetches caption and metadata
-> parser extracts travel entities
-> validation layer checks confidence
-> Google Places lookup attaches map data when safe
-> item appears in Dreams
```

Example:

```text
Caption:
"Save this for your Madrid trip.

Casa Dani
Best tortilla espanola in the city."

Result:
Dream: Spain / Madrid
Item: Casa Dani
Category: Restaurant
Maps: attached
Status: Confirmed
```

For vague content:

```text
Caption:
"This is your sign to book the trip. Europe in summer is unmatched."

Result:
Dream: Unsorted Travel Ideas
Item: original Instagram link
Category: unknown
Status: Needs Review
```

## MVP Scope

### MVP 1: Share Capture And Parsing

Build:

- iOS and Android share target.
- Save Instagram URL immediately.
- Backend record with `processing` status.
- Caption and metadata fetch.
- Deterministic pre-parser.
- Local model extraction.
- Validation layer.
- Dreams grouping.
- Needs Review state.

Skip at first:

- Video transcription.
- Screenshot OCR.
- Expensive Google metadata.
- Full itinerary generation.
- Social sharing.
- Creator marketplace hooks.

### MVP 2: Google Maps Matching

Add:

- Google Places lookup.
- Google Maps URL attachment.
- Place candidate review.
- Duplicate detection.
- Better confidence scoring.

### MVP 1.5: Transcript Fallback

Add only after URL/caption save and review workflows are working:

- Conditional transcript fallback for Reels where caption/metadata parsing is weak.
- Transcript caching by `source_url`.
- Re-run `qwen3.5:4b` with caption + transcript.
- Persist transcript status and failure reason.
- Keep uncertain transcript-derived results in Needs Review.

Do not transcribe every Reel. Transcription is a recovery path for weak caption parses, not the default parser input.

### MVP 3: Dream-To-Trip

Add:

- Convert Dream into Trip.
- Draft itinerary generation.
- Map view of saved Dream items.
- Seasonal awareness.
- Budget notes.
- Affiliate or booking opportunities.

## Mobile Share Target

The app should register as a share target for URLs.

When the user shares an Instagram URL:

1. Receive the URL.
2. Save it locally if offline.
3. Send it to the backend when possible.
4. Show immediate confirmation.
5. Do not wait for parsing to finish.

User feedback states:

- `Saved to Dreams`
- `Saved to Dreams. Processing...`
- `Saved to Spain Dreams`
- `Saved 4 places to Lisbon Dreams`
- `Saved to Unsorted Dreams. Needs Review.`

The save interaction should feel instant. Parsing can finish later.

## Backend Pipeline

## AI-Assisted, Not AI-Dependent Extraction

The production save flow should not depend on AI being available.

Required behavior:

```text
Instagram Share -> Trotter -> save source URL immediately -> show in Dreams
```

AI or a local model can enrich the item after capture, but it should never be required for the initial save. The backend should always keep the source URL and a reviewable Dream item even if metadata fetch, caption parsing, model extraction, or Google Places lookup fails.

Because Instagram captions vary too much for a fully reliable handwritten parser, the practical parser stack is:

1. Deterministic pre-parser for obvious signals, hashtags, URLs, city/country hints, lists, and no-invention guardrails.
2. Local model extraction for flexible caption interpretation.
3. Deterministic validation before anything becomes confirmed.
4. Needs Review state whenever evidence is weak, ambiguous, or missing.

Production principle:

```text
AI proposes.
Validation checks.
The user confirms.
The app never drops the save.
```

### Step 1: Capture Shared Link

Create a pending Dream item or source record immediately.

Suggested request:

```json
{
  "source_platform": "instagram",
  "source_url": "https://instagram.com/reel/...",
  "shared_text": null
}
```

Suggested response:

```json
{
  "id": "dream_item_123",
  "status": "processing"
}
```

Initial stored fields:

```text
user_id
source_platform
source_url
status = processing
created_at
updated_at
```

### Step 2: Fetch Caption And Metadata

Attempt to retrieve:

- Caption.
- Post title, when available.
- Username.
- Location tag, when available.
- Hashtags.
- Thumbnail, when available.
- Original source URL.

Start caption-first. Do not begin with video transcription.

If metadata fetch fails, still keep the URL as a Dream item marked Needs Review.

Current Phase 1 behavior:

- URL-only dev parsing is supported.
- `POST /parse-travel-caption` can accept only `source_url`.
- `POST /parse-travel-caption/batch` can accept `source_urls` or pasted `links_text`.
- `POST /dream-items/{id}/parse` can fetch metadata from the saved URL when no caption/shared text exists.
- Metadata fetching is best-effort and reads public Open Graph/meta description fields from the Instagram page.
- If normal page metadata does not include a caption, the backend falls back to Instagram's public oEmbed endpoint.
- If Instagram blocks the request or the page has no caption metadata, the saved item remains Needs Review.

Planned fallback behavior:

- If metadata/caption is missing or generic, keep the URL saved and mark the item Needs Review.
- Later, enqueue transcript fallback only when the cheap caption pass is weak.
- Re-run the parser with caption plus transcript when transcript succeeds.
- If transcript fails or adds no confidence, keep the original URL-only Needs Review item.

### Step 3: Pre-Parse Deterministically

Before calling a model, run lightweight extraction:

- Detect Google Maps links.
- Detect location marker lines.
- Detect numbered lists.
- Detect bullet lists.
- Detect hashtags.
- Detect city and country names.
- Detect likely place-name patterns.
- Detect whether the caption likely contains multiple places.

Examples:

```text
#capetown #tablemountain #southafricatravel
```

Pre-parser output:

```json
{
  "possible_city": "Cape Town",
  "possible_country": "South Africa",
  "possible_place": "Table Mountain",
  "has_multiple_items": false
}
```

This helps the model and gives the validation layer explicit evidence.

### Step 4: Run Local Model

Use a local parser model through Ollama for development and early versions.

Recommended default:

```bash
ollama pull qwen3.5:4b
```

The benchmark handoff found `qwen3.5:4b` practical as the default parser:

- Approximate benchmark score: 83.3%.
- Average speed: about 1.44 seconds per test.
- Strong enough for first-pass extraction.
- Requires deterministic validation after model output.

Use larger models such as `qwen3.5:27b` only for development review, benchmarking, or quality comparison.

Backend defaults:

```text
DREAM_PARSER_MODEL=qwen3.5:4b
OLLAMA_BASE_URL=http://localhost:11434
DREAM_PARSER_TIMEOUT_SECONDS=20
```

Local setup:

```bash
ollama pull qwen3.5:4b
ollama serve
```

The backend should call Ollama only after the Dream item has already been saved. If Ollama is unavailable, the item remains saved and marked Needs Review.

### Model Output Schema

Single item:

```json
{
  "category": "restaurant",
  "place_name": "Casa Dani",
  "city": "Madrid",
  "country": "Spain",
  "region_or_neighborhood": null,
  "summary": "Best tortilla espanola in the city.",
  "tags": ["tortilla", "food", "madrid"],
  "google_maps_search_query": "Casa Dani Madrid Spain",
  "confidence": 0.95,
  "needs_google_places_lookup": true,
  "needs_review": false
}
```

Multiple items:

```json
{
  "items": [
    {
      "category": "restaurant",
      "place_name": "Casa Dani",
      "city": "Madrid",
      "country": "Spain",
      "region_or_neighborhood": null,
      "summary": "Tortilla spot in Madrid.",
      "tags": ["food"],
      "google_maps_search_query": "Casa Dani Madrid Spain",
      "confidence": 0.95,
      "needs_google_places_lookup": true,
      "needs_review": false
    }
  ]
}
```

Allowed categories:

```text
restaurant
cafe
bar
hotel
attraction
activity
beach
shopping
nature
museum
event
unknown
```

## Parser Prompt

Use this prompt as the baseline. Keep it strict because the model must return parseable JSON.

```text
/no_think
You extract travel data from Instagram captions for a travel app.

Return exactly one valid JSON object only. No markdown. No explanations. No reasoning.

Schema for one place:
{
  "category": "restaurant | cafe | bar | hotel | attraction | activity | beach | shopping | nature | museum | event | unknown",
  "place_name": string | null,
  "city": string | null,
  "country": string | null,
  "region_or_neighborhood": string | null,
  "summary": string,
  "tags": string[],
  "google_maps_search_query": string | null,
  "confidence": number,
  "needs_google_places_lookup": boolean,
  "needs_review": boolean
}

Schema for multiple places:
{"items": [same object schema as above]}

Critical rules:
- Never invent an exact place name.
- A city, country, region, neighborhood, or broad destination is NOT a place_name.
- Disable thinking. Do not spend tokens on reasoning. Output the JSON directly.
- If the caption only gives a city, country, region, neighborhood, or general travel vibe, set place_name to null.
- If the caption describes a whole city, country, region, neighborhood, or general travel vibe without naming a specific venue, landmark, event, business, beach, activity, hotel, cafe, bar, or restaurant, set category to "unknown", needs_review to true, and confidence to 0.65 or lower.
- If place_name is null, google_maps_search_query should usually be null.
- If the exact place is unclear or ambiguous, needs_review must be true.
- If an exact place is present, google_maps_search_query should include place + city + country when available.
- confidence must be 0 to 1. Use lower confidence for vague captions.
```

Recommended Ollama payload:

```json
{
  "model": "qwen3.5:4b",
  "messages": [
    {
      "role": "system",
      "content": "SYSTEM_PROMPT"
    },
    {
      "role": "user",
      "content": "/no_think\nCAPTION_AND_PREPARSED_CONTEXT\n\nReturn the JSON object now."
    }
  ],
  "stream": false,
  "options": {
    "temperature": 0,
    "num_ctx": 2048,
    "num_predict": 400,
    "repeat_penalty": 1.05
  },
  "format": "json",
  "think": false
}
```

Use `num_predict = 300-400` for a single-place caption.

Use `num_predict = 900-1200` when the caption contains:

- Numbered lists.
- Bullet lists.
- Multiple location markers.
- "Starter pack".
- "Perfect day in".
- "Save these".
- Multiple obvious place names.

## Validation Guardrails

The model is a first-pass extractor, not the source of truth. Apply deterministic validation before creating confirmed Dream items or calling Google Places.

### Do Not Invent Exact Places

If the model produces a place name that is not supported by caption text, hashtags, location tag, URL text, or deterministic extraction, mark Needs Review.

### Do Not Trust Inferred City Or Country Blindly

If city or country was not explicit:

```text
needs_review = true
confidence = min(confidence, 0.75)
```

Preserve the suggested city or country, but do not treat it as confirmed.

### No Place Name Means No Google Places

If `place_name` is null:

```text
google_maps_search_query = null
needs_google_places_lookup = false
needs_review = true
```

### Generic Names Require Review

Generic names are risky:

```text
The Rock
The View
Old Town
The Beach
Sunset Point
Secret Spot
Hidden Rooftop
The Market
```

If the place name is generic and city/country is missing or uncertain:

```text
needs_review = true
confidence = max 0.70
do not auto-confirm Google Places result
```

### Provider Versus Location

Some posts mention both a tour provider and an activity location.

Example:

```text
We booked our Iceland glacier hike with Arctic Adventures.
Solheimajokull Glacier
```

This can create:

- Provider: Arctic Adventures.
- Location: Solheimajokull Glacier.

For these cases, either create two candidate entities or mark one item Needs Review with related candidates.

### Multi-Place Captions

If the caption is a list, expect multiple Dream items. Increase output length and validate the JSON for truncation.

If the JSON is invalid, retry once with a JSON repair prompt. If repair fails, save the source URL as Needs Review.

## Google Places Lookup

Only call Google Places when:

- `place_name` exists.
- Confidence is high enough.
- There is enough city/country/region context.

Recommended policy:

```text
High confidence:
  place_name + city/country present
  confidence >= 0.80
  call Google Places

Medium confidence:
  place_name present but city/country uncertain
  confidence 0.55-0.80
  optionally call Google Places
  mark Needs Review

Low confidence:
  no place_name
  no Google Places call
```

Request only cheap, useful fields at first:

- `place_id`
- `displayName`
- `formattedAddress`
- `location`
- `googleMapsUri`
- `types`

Do not request reviews, photos, phone numbers, ratings, opening hours, or rich metadata in the MVP.

## Dreams Grouping

Every shared item should be saved, even if uncertain.

Grouping:

```text
If country exists:
  group by country

If city exists:
  subgroup by city

If only region exists:
  group under country/region if available

If no location exists:
  put in Unsorted Travel Ideas

If needs_review is true:
  show review badge but still save it
```

Example structure:

```text
Dreams
├── Spain
│   └── Madrid
│       ├── Casa Dani
│       └── Rooftop tapas bar
├── Japan
│   └── Tokyo
└── Unsorted Travel Ideas
```

## Suggested Data Model

### `dreams`

```text
id
user_id
title
country
city
region
item_count
status
created_at
updated_at
```

### `dream_items`

```text
id
user_id
dream_id
source_platform
source_url
caption
raw_metadata_json
category
place_name
city
country
region_or_neighborhood
summary
tags_json
confidence
needs_review
needs_google_places_lookup
google_place_id
google_maps_url
status
created_at
updated_at
```

### `place_candidates`

```text
id
dream_item_id
source
place_name
city
country
google_place_id
google_maps_url
confidence
selected
created_at
```

### `dream_item_events`

Optional audit/event table:

```text
id
dream_item_id
event_type
event_json
created_at
```

Useful event types:

- `shared`
- `metadata_fetched`
- `parsed`
- `validation_adjusted`
- `places_lookup_started`
- `places_lookup_completed`
- `reviewed`
- `converted_to_trip`

## API Sketch

### Create Shared Dream Item

```text
POST /dreams/share
```

Request:

```json
{
  "source_platform": "instagram",
  "source_url": "https://instagram.com/reel/...",
  "shared_text": null
}
```

Response:

```json
{
  "dream_item_id": "123",
  "status": "processing"
}
```

### Get Dream Item

```text
GET /dream-items/{id}
```

### List Dreams

```text
GET /dreams
```

### List Dream Items

```text
GET /dreams/{id}/items
GET /dream-items?status=needs_review
```

### Review Dream Item

```text
POST /dream-items/{id}/review
```

Request:

```json
{
  "decision": "confirm",
  "edits": {
    "place_name": "Casa Dani",
    "city": "Madrid",
    "country": "Spain"
  },
  "selected_place_candidate_id": "candidate_123"
}
```

### Parse Caption Internal Endpoint

For development and testing:

```text
POST /parse-travel-caption
```

Request:

```json
{
  "source_url": "https://instagram.com/reel/...",
  "caption": "Save this for your Madrid trip..."
}
```

Response:

```json
{
  "items": [
    {
      "category": "restaurant",
      "place_name": "Casa Dani",
      "city": "Madrid",
      "country": "Spain",
      "confidence": 0.95,
      "needs_review": false
    }
  ]
}
```

## Background Processing

Use a background job for metadata fetch, parsing, validation, and Places lookup.

Suggested states:

```text
created
processing
metadata_failed
parsed
needs_review
confirmed
failed
```

Processing should be idempotent. Re-sharing the same URL should not create unlimited duplicates. Reasonable duplicate keys:

- `user_id + source_url`
- `user_id + google_place_id`
- `user_id + normalized place_name + city + country`

Do not dedupe too aggressively in MVP; it is better to merge later than lose a user's save.

## Transcript Fallback

Transcript fallback is an MVP 1.5 enrichment step for Instagram Reels where useful place details are spoken in the video but not exposed in caption metadata.

Core rule:

```text
Save first.
Parse caption/metadata second.
Transcribe only when necessary.
Review when uncertain.
```

### Trigger Conditions

Attempt transcription only when one or more of these are true:

- Caption is empty or unavailable.
- Caption is generic, such as "save this spot" or "details in video".
- Caption has no exact place and no city/country.
- Parser returns `place_name = null`.
- Parser returns `category = unknown`.
- Parser confidence is below `0.55`.
- Metadata fetch only gives a title, username, or generic Instagram wrapper.

Skip transcription when:

- Caption has a clear exact place.
- Caption has place + city/country.
- Caption includes a Google Maps link or clear address.
- Metadata has a reliable location tag.
- Parser returns `place_name` with confidence `>= 0.80`.

### Transcript Flow

```text
process_dream_item
-> fetch metadata
-> parse caption with qwen3.5:4b
-> validate
-> if transcript_needed:
     enqueue transcript_dream_item
-> else:
     finish
```

```text
transcript_dream_item
-> resolve video/audio URL
-> transcribe
-> cache transcript by source_url
-> re-run parser with caption + transcript
-> validate again
-> update Dream item or keep Needs Review
```

### Data Model Direction

Prefer a related table over adding many columns to `dream_items`, because transcript data may later include multiple providers, languages, OCR, retries, and cost records.

Suggested table:

```text
dream_item_transcripts
id
dream_item_id
source_url
transcript_text
transcript_source
language
duration_seconds
cost_cents
status
error
created_at
updated_at
```

Suggested statuses:

```text
not_needed
needed
processing
completed
failed
skipped_cost_control
```

### Cost Controls

- Only transcribe once per unique `source_url` unless manually retried.
- Cache transcript results.
- Do not automatically retry failed transcript jobs more than once.
- Do not auto-transcribe videos over an early duration cap, such as 90 seconds.
- Do not transcribe private/unavailable posts.
- Do not run transcript fallback during instant save.
- Track cost per transcript provider.

### Provider Direction

Short term:

- Deepgram or Rev AI, only as fallback.

Medium term:

- `faster-whisper` or `whisper.cpp` locally.

Avoid as default:

- Direct Instagram transcript APIs priced around `$0.30/reel`; useful for experiments, too expensive as production infrastructure.

## Dreams UI

Build three basic surfaces.

### Dreams Home

Shows destination groups:

- Spain.
- Japan.
- Mexico City.
- Lisbon.
- Unsorted Travel Ideas.
- Needs Review.

### Dream Detail

Shows items for a destination:

- Place name.
- Category.
- Summary.
- Original Instagram link.
- Google Maps link when available.
- Confidence or review badge.
- Edit/delete actions.

### Review Inbox

Shows uncertain items:

- Vague destination ideas.
- Ambiguous place names.
- Multiple candidate places.
- Missing city/country.
- Failed metadata fetches.

Review actions:

- Confirm.
- Edit.
- Move to another Dream.
- Pick a Google Places candidate.
- Delete.

## Testing Strategy

### Parser Unit Tests

Fixture categories:

- Exact restaurant with city/country.
- Landmark with city.
- Cafe with neighborhood.
- Vague city-only caption.
- General region/country vibe.
- Hashtag-only destination clues.
- Multiple places in one caption.
- Generic place name.
- Provider plus activity location.
- Caption with Google Maps link.
- Non-travel post.

Assert:

- Valid JSON.
- Correct category.
- Correct place handling.
- No invented place names.
- Proper Needs Review behavior.
- Google Maps query is null when place is null.

### Validation Tests

Cover:

- Inferred city/country confidence cap.
- Generic names forced to review.
- Place-null blocks Places lookup.
- Multi-item output normalization.
- Duplicate detection.
- Google Places candidate selection.

### API Tests

Cover:

- Share endpoint creates processing item.
- Failed metadata fetch still saves item.
- Parser job updates status.
- High-confidence item groups into correct Dream.
- Low-confidence item goes to Unsorted Travel Ideas.
- Review endpoint applies edits.

### Mobile Tests

Cover:

- Share target receives URL.
- User sees immediate saved state.
- Offline save queues locally.
- Dreams list renders processing and confirmed states.
- Review screen can edit an item.

## Implementation Order

1. Add backend tables for Dreams and Dream items.
2. Add `POST /dreams/share` to save URLs immediately.
3. Add a background processing job.
4. Add caption/metadata fetcher for Instagram URLs.
5. Add deterministic pre-parser.
6. Add local Ollama parser service behind an interface.
7. Add validation and confidence rules.
8. Add Dreams grouping logic.
9. Add internal parser test endpoint for development.
10. Add basic Dreams UI.
11. Add mobile share target.
12. Add Needs Review UI.
13. Add Google Places lookup.
14. Add duplicate detection and candidate review.
15. Add Dream-to-trip conversion.

## Implementation Progress

### 2026-05-11 Mobile Phase 1 UI

Implemented the first mobile UI slice in `mobile-v2`:

- Added `src/services/dreams.ts` with backend-shaped `Dream` and `DreamItem` types.
- Added a mock Dreams store with destination grouping, needs-review filtering, item edit, confirm, delete, and Instagram-link save actions.
- Added `src/screens/DreamsScreen.tsx`.
- Replaced the temporary stamp editor route in `App.tsx` with the new Dreams surface.
- Built three Phase 1 UI surfaces:
  - Dreams Home.
  - Dream Detail.
  - Review Inbox.
- Added a dev-only link tester inside Dreams so parser/review UI can be tested before native share capture and backend persistence are complete.

The dev link tester is not intended as the production flow. The production flow is Instagram Share -> Trotter -> immediate save to Dreams.

### 2026-05-11 Android Share Target

Implemented Android share-sheet capture for the production direction:

- Added an Android `ACTION_SEND` `text/plain` intent filter in `android/app/src/main/AndroidManifest.xml`.
- Added `share_to_dreams` label in `android/app/src/main/res/values/strings.xml`.
- Updated `android/app/src/main/java/com/trotter/mobilev2/MainActivity.kt` so shared text/URLs are transformed into a `trotterv2://share?url=...&text=...` deep link before React Native receives them.
- Updated `src/services/dreams.ts` with `DreamsProvider` and `parseIncomingDreamShare`.
- Wrapped the app with `DreamsProvider`.
- Updated `App.tsx` to listen for incoming share deep links, save the shared Instagram URL into Dreams, and switch to the Dreams tab.

Expected Android test flow:

```text
Instagram post/Reel
-> Share
-> Trotter V2 / Save to Trotter Dreams
-> app opens Dreams
-> shared URL appears as a saved Dream item
```

### 2026-05-11 Backend Persistence Slice

Implemented the first backend persistence slice:

- Added `Dream` and `DreamItem` SQLAlchemy models.
- Added Alembic migration `0007_add_dreams`.
- Added Dreams API routes:
  - `POST /dreams/share`
  - `GET /dreams`
  - `GET /dreams/{dream_id}/items`
  - `GET /dream-items?status=needs_review`
  - `POST /dream-items/{id}/review`
  - `DELETE /dream-items/{id}`
- Added deterministic draft grouping/validation so shared links can be saved immediately before AI parsing exists.
- Added duplicate protection on `user_id + source_url`.
- Added targeted backend tests for auth, share capture, grouping, duplicate handling, review edits, and delete.

This slice intentionally does not fetch Instagram metadata, call AI, or call Google Places yet. It creates the stable save/review API that those later processors can update.

### 2026-05-11 Ollama Parser Slice

Implemented the first local parser integration using Ollama:

- Added `app/services/dream_parser.py`.
- Default model is `qwen3.5:4b`.
- Default Ollama URL is `http://localhost:11434`.
- Added strict JSON prompt/payload based on the benchmarked parser setup.
- Added deterministic validation after model output:
  - unsupported place names are forced to Needs Review
  - unsupported city/country suggestions cap confidence
  - missing place names disable Google Places lookup
- Added `POST /parse-travel-caption` for internal/dev parser testing.
- Added `POST /dream-items/{id}/parse` to enrich an already-saved Dream item.
- Parser failure does not delete or lose the saved Dream item; it remains Needs Review.

### 2026-05-12 URL-Only Parser Test Slice

Implemented URL-only parsing for local testing:

- Added `app/services/instagram_metadata.py`.
- Added best-effort Instagram page metadata fetching using Open Graph/meta description fields.
- Added Instagram oEmbed fallback for reels/posts whose normal HTML does not expose caption metadata.
- Normalized Instagram URLs before metadata lookup so share params such as `igsh` do not break oEmbed.
- oEmbed lookup now uses the canonical `https://www.instagram.com/.../` form expected by Instagram.
- Added one JSON repair retry when the local model returns malformed JSON.
- If JSON repair still fails, the parser now returns a safe Needs Review item instead of failing the whole URL.
- Metadata misses now return a URL-only Needs Review item for dev parsing instead of hard-failing the batch.
- Added a validation guardrail so a city/island name is not treated as an exact `place_name` when `place_name == city`.

### 2026-05-12 End-To-End Dreams Import Slice

Implemented the first app-testable import flow:

- Updated `POST /dreams/share` so native Instagram Share-to-Trotter runs the full enrichment path immediately for a shared Reel/Post URL:
  - normalize URL
  - fetch Instagram metadata/caption when public metadata is available
  - parse with `qwen3.5:4b`
  - selectively retry weak/unknown results with `qwen3.5:27b`
  - validate and group into the right Dream
  - attach a place link when possible
- Added `POST /dreams/import-instagram-batch`.
- Batch import creates real `DreamItem` rows immediately.
- Each imported item then attempts metadata fetch, `qwen3.5:4b` parsing, selective `qwen3.5:27b` fallback, validation, and optional Google Places lookup.
- Google Places is optional and only runs when `GOOGLE_PLACES_API_KEY` or `GOOGLE_MAPS_API_KEY` is configured.
- Added a free Google Maps search URL fallback, so dev builds can store a useful Maps button without paid Google Places.
- Added optional Geoapify place lookup via `GEOAPIFY_API_KEY` as a free/dev candidate matcher before paid Google Places.
- Added the current Geoapify key as a dev default in code so local testing does not require setting terminal environment variables. `GEOAPIFY_API_KEY` still overrides it.
- Geoapify uses cautious name/confidence guardrails; low-confidence name mismatches are rejected and fall back to a Google Maps search URL.
- Geoapify geocoding now disables IP-country bias and checks multiple candidates, choosing the best acceptable name match instead of blindly accepting the first result.
- Place fields are stored on `dream_items` via `google_place_id` and `google_maps_url`, with raw match data in `raw_metadata_json`.
- Foreign Dreams are grouped by country, such as `Mexico` or `Thailand`.
- Domestic United States Dreams are grouped by region/state when Google Places provides it, such as `Texas`.
- Updated `parse_instagram_batch.ps1` so its default mode imports links into real Dreams instead of parse-only testing. Use `-ParseOnly` for the older parser-only loop.
- Updated mobile `DreamsProvider` to load live backend Dreams/items when an auth token is present, with existing mock data as fallback.
- Hid Needs Review surfaces in the mobile app for now; review status remains in backend data.
- Updated `POST /parse-travel-caption` so it can accept only `source_url`.
- Added `POST /parse-travel-caption/batch` for testing many Instagram URLs at once.
- Updated `POST /dream-items/{id}/parse` so saved URL-only Dream items can fetch metadata before calling Ollama.
- Added tests for metadata extraction, URL-only parse routing, and saved-item URL-only parsing.

### Verification

Completed:

- `npm run typecheck -- --pretty false` filtered for `App.tsx`, `DreamsScreen.tsx`, and `dreams.ts`: clean.
- `android/gradlew.bat :app:assembleDebug`: completed successfully.
- `pytest tests/test_dreams.py -q`: 6 passed.
- `pytest tests/test_dreams.py tests/test_dream_parser.py -q`: parser/API tests pass.

Known caveat:

- Full project typecheck may still surface unrelated existing stamp editor issues while `NativeStampEditorScreen.tsx` remains in the tree.

### Next Implementation Items

Completed:

- Add backend persistence:
   - `Dream`
   - `DreamItem`
   - optional `DreamItemEvent`
- Add Dreams API routes:
   - `POST /dreams/share`
   - `GET /dreams`
   - `GET /dreams/{dream_id}/items`
   - `GET /dream-items?status=needs_review`
   - `POST /dream-items/{id}/review`
   - `DELETE /dream-items/{id}`
- Add deterministic backend grouping and validation.

Remaining:

1. Move batch import/enrichment into a background job so mobile save stays instant for large batches.
2. Add structured `review_reason` / `failure_reason` fields instead of storing notes in `raw_metadata_json`.
3. Add mobile review UI later, once the core live Dreams display feels right.
4. Add transcript fallback decision function, but keep actual transcription behind a later job/provider.
5. Add Google Places candidate review for ambiguous matches.
6. Add native iOS Share Extension later.

## Open Questions

- Should local model parsing run on the backend machine, on-device, or both?
- Is Instagram caption fetching reliable enough without a user-provided caption from the share sheet?
- Should the first mobile version require the share sheet's URL only, or also support pasted links?
- How should Trotter handle private Instagram posts where metadata cannot be fetched?
- Should screenshots and OCR be added before or after Google Places?
- Should Dream items be private by default forever until explicitly shared?

## Product Principle

Every shared item should be saved immediately. Trotter can be uncertain later, but it should never drop the user's inspiration.

The correct MVP behavior is:

```text
Save first.
Parse second.
Validate third.
Ask for review when unsure.
```
