# Dreams AI and Infrastructure Migration

Status: hosted AI client implemented and validated against Venice; deployment pending  
Last reviewed: 2026-09-04

This document records the intended direction and implementation progress for hosted Dreams enrichment and a later move to Supabase. It is deliberately split into separate phases so the AI pipeline can improve without coupling it to a database migration.

## Executive Decision

- Use the Venice API as the model gateway instead of operating Ollama in production.
- Start with Venice model `qwen3-5-9b` as the primary Dreams extractor.
- Evaluate `kimi-k2-5` as the selective fallback for difficult captions and images.
- Keep model and provider selection configurable. Do not encode OpenAI, Venice, or any model ID into domain logic.
- Use strict JSON Schema responses, deterministic validation, and Places resolution. The model extracts candidates; it is not the geographic source of truth.
- Redesign Dreams ingestion around one saved source producing zero, one, or many place records.
- Process enrichment asynchronously with the existing worker infrastructure.
- Treat Supabase as a later managed database and storage migration, not as part of the AI-provider change.
- Keep FastAPI and background workers as the application boundary during the first Supabase migration.

## Implementation Progress

The hosted AI portion was implemented locally on 2026-09-04:

- Venice is the default provider behind a provider-neutral parser entry point.
- `qwen3-5-9b` is the configured primary and `kimi-k2-5` is the selective fallback.
- Requests use strict JSON Schema, disable thinking and web access, and bound output size.
- Transient requests retry with bounded backoff.
- Authentication, billing, and request-configuration failures do not waste a fallback request.
- Stored response metadata is limited to request ID, model, token counts, latency, attempts, finish reason, and operational warnings.
- All Dreams parsing endpoints now use the configured provider path.
- Docker deployment reads the Venice key from `deploy/secrets/venice_api_key`.
- Local Ollama remains available only when `DREAM_AI_PROVIDER=ollama` is selected explicitly.
- Live strict-schema smoke tests passed against both `qwen3-5-9b` and `kimi-k2-5` on 2026-09-04.

Still pending:

- Run the labeled model evaluation before treating Kimi as the permanent fallback.
- Deploy the updated backend.
- Implement asynchronous ingestion and source/place database separation.
- Persist all mobile review mutations and finish the review interface.
- Rehearse and execute the Supabase migration.

## Why The Model Recommendation Changed

The initial OpenAI recommendation over-weighted SDK ergonomics and Structured Outputs. Venice exposes an OpenAI-compatible API and supports the same `response_format` JSON Schema mechanism, so those are not meaningful reasons to select an OpenAI-hosted model.

For Trotter, the useful selection criteria are:

- Exact extraction accuracy on real travel posts.
- Multiple-place recall.
- Low hallucination and false-confirmation rates.
- Reliable schema compliance.
- Image understanding for weak or missing captions.
- Private processing where available.
- Low latency and cost.
- Continued availability through Venice.

Model choice must ultimately be based on a Trotter-specific evaluation set rather than vendor benchmarks or model size.

## Verified Current State

### Dreams AI

- Before the hosted migration, the repository used Ollama model `qwen3.5:4b` with `qwen3.5:27b` as its fallback.
- The provider-neutral parser now defaults to Venice. Ollama is retained for local baselines only.
- No Kimi model or Qwen 2.5 model appears in repository history for Dreams.
- The old project benchmark reported approximately 83.3 percent accuracy for `qwen3.5:4b`, but that test is too small and narrow to make the new hosted-model decision.
- The current production sample is also too small: five Dream items were present at review time, four parsed by Qwen and one by deterministic fallback.

Relevant implementation:

- `backend/app/services/dream_parser.py`
- `backend/app/routers/dreams.py`
- `backend/app/models.py`
- `mobile-v2/src/services/dreams.ts`
- `mobile-v2/src/screens/DreamsScreen.tsx`

### Infrastructure

- FastAPI owns the API and business logic.
- PostgreSQL with PostGIS stores application data.
- Redis and Celery handle background work.
- Oracle hosts the application stack.
- Cloudflare Tunnel exposes the public service.
- Gmail OAuth refresh tokens are encrypted and managed by the trusted backend.
- The database was approximately 23.3 MB at review time, with two users. Capacity is not currently a reason to migrate.

## Venice Model Direction

The Venice model catalog changes frequently. Confirm model availability and capabilities from `GET https://api.venice.ai/api/v1/models` during implementation and deployment.

| Model | Proposed role | Privacy | Input / output per 1M tokens | Schema | Vision | Reason |
| --- | --- | --- | ---: | --- | --- | --- |
| `qwen3-5-9b` | Primary | Private | $0.10 / $0.15 | Yes | Yes | Very inexpensive, fast, multilingual, configurable reasoning, and close to the existing Qwen baseline. |
| `kimi-k2-5` | Difficult-case candidate | Private | $0.56 / $3.50 | Yes | Yes | Larger reasoning and vision model for ambiguous captions, lists, and weak visual evidence. |
| `qwen3-vl-235b-a22b` | Vision challenger | Private | $0.21 / $1.90 | Yes | Yes | Strong OCR and visual extraction candidate if Kimi is not best on image-heavy posts. |
| `mistral-small-2603` | General challenger | Private | $0.1875 / $0.75 | Yes | Yes | Cheap larger instruction model worth including in the benchmark. |

These prices and capabilities are a 2026-09-04 snapshot, not permanent configuration.

### Proposed Runtime Policy

1. Send usable caption, shared text, source platform, and URL context to `qwen3-5-9b`.
2. Use strict JSON Schema with all fields required and nullable fields represented explicitly.
3. Set reasoning effort to `none` for ordinary extraction.
4. Do not enable Venice web search or scraping in the normal parsing request.
5. Validate the result against the source text and deterministic rules.
6. Resolve extracted candidates with Google Places or Geoapify.
7. If text is insufficient and a cached thumbnail is available, retry with image input.
8. Escalate to the selected fallback only when validation identifies a real ambiguity, truncation, conflicting geography, or failed place resolution.
9. Send unresolved results to review instead of repeatedly trying larger models.

`kimi-k2-5` is the initial fallback hypothesis, not a permanent decision. If the labeled evaluation shows that Qwen VL or Mistral has higher accuracy, lower false-confirmation rates, or better structured-output reliability, use that model instead.

### Provider Boundary

Define one provider-neutral operation conceptually equivalent to:

```text
extract_dream_places(input, schema, model_policy) -> extraction_result
```

Provider code should own:

- Base URL and authentication.
- Model IDs.
- JSON Schema request formatting.
- Timeouts, retries, and rate-limit handling.
- Usage, latency, and provider request IDs.
- Normalization of refusal, truncation, and malformed-response errors.

Domain code should own:

- What constitutes a Dream place.
- Evidence and confidence rules.
- Place resolution and deduplication.
- Grouping into destinations.
- Review decisions.

Suggested server-side configuration:

```text
DREAM_AI_PROVIDER=venice
DREAM_AI_BASE_URL=https://api.venice.ai/api/v1
DREAM_AI_PRIMARY_MODEL=qwen3-5-9b
DREAM_AI_FALLBACK_MODEL=kimi-k2-5
DREAM_AI_TIMEOUT_SECONDS=30
DREAM_AI_MAX_ATTEMPTS=2
```

The API key must exist only in server-side secret storage. It must never be included in the mobile bundle, logs, parser metadata, or API responses.

## Problems To Fix In The Current Dreams Flow

### Multiple Places Are Lost

The parser schema permits multiple `items`, but current enrichment applies only `parsed.items[0]`. A source describing ten restaurants can therefore produce only one saved item.

The existing unique constraint on `(user_id, source_url)` also prevents representing several extracted places as independent rows tied directly to the same URL.

### Enrichment Is Synchronous

`POST /dreams/share` currently performs metadata retrieval, model parsing, place resolution, grouping, and database work before returning. User-visible saving is therefore coupled to every external dependency.

### Mobile Mutations Are Not Persisted

The current mobile `updateItem`, `confirmItem`, and `deleteItem` operations alter local state but do not consistently call the existing backend endpoints. Changes can disappear after refresh.

### Review Is Not A Complete Product Flow

The mobile review view exists, but the normal Dreams interface does not provide a complete, obvious path into it. Processing and failure states also need to remain visible after the initial share action.

### Source Acquisition Is A Separate Failure Domain

A stronger model cannot extract a place if Instagram metadata contains no useful caption or image. Source capture, metadata retrieval, AI extraction, and place resolution must have separate states and diagnostics.

## Target Dreams Data Model

Use source records and extracted place records as separate concepts.

### `dream_sources`

One record per user-shared source:

- `id`
- `user_id`
- `canonical_url`
- `original_url`
- `source_platform`
- `shared_text`
- `caption`
- `thumbnail_storage_key`
- `status`
- `failure_stage`
- `failure_code`
- `created_at`
- `updated_at`

Uniqueness should apply to `(user_id, canonical_url)` here.

### `dream_places`

Zero or more records produced from one source:

- `id`
- `source_id`
- `dream_id`
- `ordinal`
- `place_name`
- `category`
- `city`
- `region`
- `country`
- `evidence_text`
- `google_place_id` or provider-neutral place ID
- `maps_url`
- `latitude`
- `longitude`
- `confidence`
- `needs_review`
- `status`
- `created_at`
- `updated_at`

Deduplicate resolved places using the canonical place-provider ID within the destination. Do not deduplicate solely by generated name text.

### `dream_processing_attempts`

Record compact operational metadata for each processing stage:

- `source_id`
- `stage`
- `provider`
- `model`
- `prompt_version`
- `schema_version`
- `provider_request_id`
- `input_tokens`
- `output_tokens`
- `latency_ms`
- `outcome`
- `error_code`
- `created_at`

Do not retain entire raw model responses indefinitely. Keep only the normalized result and concise audit data by default, with short-lived debug payloads when explicitly enabled.

## Target Processing Pipeline

```text
Mobile share
  -> canonicalize and persist dream_source
  -> return 202 Accepted with source ID
  -> enqueue enrich_dream_source
  -> fetch metadata and cache permitted thumbnail
  -> extract zero, one, or many candidates
  -> validate evidence
  -> resolve each candidate through Places
  -> deduplicate and group
  -> publish ready or review state
  -> mobile refreshes or receives the final state
```

Suggested source states:

- `queued`
- `fetching`
- `extracting`
- `resolving`
- `ready`
- `needs_review`
- `failed`

The source URL must remain saved even when every later stage fails.

## Validation And Confidence

Model-provided confidence is only a signal. Trotter should calculate application confidence from observable evidence.

Positive evidence includes:

- Exact or alias place name appears in source text.
- City or country appears in source text.
- Resolved Places result agrees with the extracted geography.
- A unique high-quality place match exists.
- Image text independently supports the caption result.

Review triggers include:

- No named venue, landmark, activity, or destination.
- Multiple plausible Places matches.
- Extracted geography conflicts with the resolved place.
- The candidate is inferred without direct source evidence.
- A list appears truncated.
- The source contains more apparent places than the parser returned.
- Metadata and image retrieval both failed.

Auto-confirmation should optimize for a very low false-positive rate. Missing a place and asking for review is preferable to confidently filing the wrong place.

## Model Evaluation Plan

Create a versioned labeled dataset of at least 50 real or representative sources before selecting the permanent fallback. Include:

- One explicit place.
- Multiple named places in one post.
- City-only and country-only inspiration.
- Ambiguous businesses with duplicate names.
- Captions with hashtags, emoji, and unrelated promotional text.
- Missing captions and image-only evidence.
- Non-English captions and diacritics.
- Informal aliases and abbreviated locations.
- Posts that contain no travel place.
- Deleted, private, or inaccessible sources.

Run the same prompt and schema against:

- Existing local `qwen3.5:4b` as the baseline.
- Venice `qwen3-5-9b`.
- Venice `kimi-k2-5`.
- Venice `qwen3-vl-235b-a22b` for visual cases.
- Venice `mistral-small-2603`.

Measure:

- Place-level precision and recall.
- Multi-place recall.
- City, region, and country accuracy.
- Hallucinated-place rate.
- False auto-confirmation rate.
- Schema-valid response rate.
- Places resolution rate.
- Review precision and review rate.
- p50 and p95 latency.
- Tokens and cost per source.

Proposed release gates:

- No source is lost when enrichment fails.
- No parser result is silently discarded because it is not the first item.
- Structured responses are valid after bounded retry in effectively all test cases.
- Explicit named-place recall is at least 95 percent on the labeled set.
- False auto-confirmation remains below 1 percent on the labeled set.
- A fallback must produce a meaningful measured improvement before it is enabled in production.

## Supabase Direction

Supabase is a reasonable future destination for managed PostgreSQL, PostGIS, backups, and object storage. It should not initially replace the FastAPI application or worker processes.

### Keep On Oracle Initially

- FastAPI API service.
- Celery workers.
- Redis.
- Gmail synchronization and token refresh.
- Instagram metadata collection.
- Venice API requests.
- Place-provider calls.
- Cloudflare Tunnel, unless the API is later moved to another compute host.

### Move To Supabase Incrementally

1. Create a Supabase project and enable required extensions, including PostGIS.
2. Rehearse `pg_dump` and restore into a non-production Supabase project.
3. Run Alembic against the restored database and verify extension, role, index, constraint, and sequence behavior.
4. Connect the Oracle-hosted backend through the appropriate Supavisor session-mode endpoint.
5. Run application, migration, background-job, and query-performance tests against the new database.
6. Perform a timed final backup and restore during a short write-maintenance window.
7. Switch the backend database secret and verify health, login, Gmail sync, Dreams, and trip queries.
8. Retain the old Oracle database read-only for a defined rollback window.
9. Move cached thumbnails and future user media to Supabase Storage separately.
10. Consider Supabase Auth only after the database and storage migrations are stable.

### Why Not Rewrite As Edge Functions

Dream enrichment, scraping, Gmail processing, and batch parsing are background workloads. Supabase Edge Functions have execution limits and are not a replacement for the existing Celery worker model. Keeping application logic in FastAPI also avoids a risky backend rewrite during the database move.

### Authentication Caveat

Supabase Auth can provide application login, but it does not eliminate Trotter's Gmail OAuth responsibilities. Gmail background synchronization requires trusted storage and refresh of the Google provider token. That logic must remain server-side even if user authentication later moves to Supabase.

### Free Versus Pro

At the reviewed database size, Supabase Free has ample raw capacity for a rehearsal. It is not ideal for an always-available demonstration environment because free projects can pause after inactivity and do not include automatic backups. Supabase Pro is the sensible production target once the project justifies its current $25 per month base price.

## Recommended Delivery Order

### Phase 0: Measure

- Build and version the labeled Dreams dataset.
- Add a provider-neutral offline evaluation harness.
- Compare Venice candidates and preserve results in the repository.

### Phase 1: Correct The Data Model

- Introduce source and place records.
- Migrate existing Dream items without losing URLs or edits.
- Support multiple extracted places from one source.

### Phase 2: Make Processing Asynchronous

- Save first and return immediately.
- Move metadata, model, and Places work to Celery.
- Add bounded retries and explicit stage failures.

### Phase 3: Add Venice

- Completed: implement the provider boundary.
- Completed: add strict schema extraction with `qwen3-5-9b` as the initial primary.
- Completed: add bounded retry plus configurable `kimi-k2-5` fallback behavior.
- Completed: add token, latency, request, model, and finish-reason telemetry.
- Pending: add image escalation after the source/place migration exposes a safe image input.
- Pending: retain or replace Kimi based on the labeled evaluation.

### Phase 4: Finish The Mobile Workflow

- Display durable processing states.
- Make edit, confirm, and delete operations persist through the API.
- Make the review inbox accessible.
- Render multiple places from one shared post clearly.

### Phase 5: Rehearse Supabase

- Restore a current database snapshot into a temporary Supabase project.
- Verify PostGIS, Alembic, performance, backups, and rollback.
- Document measured results before scheduling a production cutover.

### Phase 6: Supabase Production Cutover

- Move PostgreSQL/PostGIS first.
- Move object storage separately.
- Reconsider authentication and compute only after both are stable.

## Explicit Non-Goals For The First Pass

- Rewriting FastAPI as Edge Functions.
- Replacing Celery with database-triggered work.
- Moving Gmail OAuth token handling into the mobile client.
- Letting a model invent coordinates or bypass Places validation.
- Using Venice web search for normal Dream extraction.
- Sending every image to an expensive fallback model.
- Migrating databases at the same time as changing the parser and data model.

## Reference Documentation

- Venice model catalog: https://docs.venice.ai/models/overview
- Venice live models endpoint: https://api.venice.ai/api/v1/models
- Venice pricing: https://docs.venice.ai/overview/pricing
- Venice Structured Responses: https://docs.venice.ai/guides/features/structured-responses
- Venice privacy: https://docs.venice.ai/overview/privacy
- Supabase pricing: https://supabase.com/pricing
- Supabase PostgreSQL migration: https://supabase.com/docs/guides/platform/migrating-to-supabase/postgres
- Supabase database connections: https://supabase.com/docs/guides/database/connecting-to-postgres
- Supabase PostGIS: https://supabase.com/docs/guides/database/extensions/postgis
- Supabase Edge Function limits: https://supabase.com/docs/guides/functions/limits
- Supabase Queues: https://supabase.com/docs/guides/queues
- Supabase Google Auth: https://supabase.com/docs/guides/auth/social-login/auth-google
