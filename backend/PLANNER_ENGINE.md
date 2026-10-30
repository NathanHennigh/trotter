# Planner engine operations

The planner composes an uncommitted draft. AI may choose supplied idea IDs, group
them by day and order them. Python assigns times and enforces identity, dates,
opening windows, route buffers and locked bookings. Ordinary edits and acceptance
never call AI or Google. The bounded constructive scheduler does not claim a
globally optimal itinerary.

## Configuration

| Setting | Default | Purpose |
| --- | --- | --- |
| `PLANNER_AI_ENABLED` | `true` | Enables one composition request per explicit generation/rework. |
| `PLANNER_AI_MODEL` | `kimi-k2-5` | Independent of the Dreams capture model. |
| `PLANNER_AI_API_KEY` | fallback `VENICE_API_KEY` | Backend-only credential; `_FILE` variants supported. |
| `PLANNER_AI_BASE_URL` | `https://api.venice.ai/api/v1` | HTTPS provider endpoint. |
| `PLANNER_AI_MAX_COMPLETION_TOKENS` | `4096` | Includes all billed completion/reasoning tokens; maximum 8192. |
| `PLANNER_AI_MAX_COST_USD` | `0.08` | Conservative model-call allowance, including input/schema and completion cap. |
| `PLANNER_MAX_JOB_COST_USD` | `0.15` | Additional model-call ceiling and API job reservation; deployment uses 0.08. |
| `PLANNER_AI_TIMEOUT_SECONDS` | `45` | One attempt only; no automatic paid repair or retry. |
| `PLANNER_FACTS_ENABLED` | `true` | Enables bounded Google facts and coordinate cache reads. |
| `PLANNER_PLACE_LOOKUP_LIMIT` | `10` | Maximum unique Place Details requests per generation, configurable 0–60. |
| `PLANNER_ROUTE_LOOKUP_LIMIT` | `12` | Maximum chosen-edge route requests, configurable 0–60. |
| `PLANNER_ROUTE_TIMEOUT_SECONDS` | `20` | Aggregate live routing time allowance, maximum 45. |
| `GOOGLE_PLACES_API_KEY` | unset | Existing protected backend Places key. |
| `GOOGLE_ROUTES_API_KEY` | fallback Places key | Must have Routes API access for verified routing. |
| `GOOGLE_PLACES_CACHE_URL` | unset | Existing isolated, nonpersistent Redis; never the persistent broker. |

Known model rates are configured for Kimi K2.5 and Qwen3.5 35B. Other models require
`PLANNER_AI_INPUT_USD_PER_MILLION` and `PLANNER_AI_OUTPUT_USD_PER_MILLION`. The API
also enforces `PLANNER_DAILY_GENERATION_LIMIT` (default 20) and
`PLANNER_DAILY_BUDGET_USD` (default 1) using reservations for model requests. A lost
worker is failed without automatically repeating its potentially paid request.

## Facts, retention and costs

Google costs are separate from model usage and the model's daily dollar budget.
Opening-hours fields trigger Place Details Enterprise. At the first paid tier,
the default 10 unique detail requests can cost up to $0.20, and 12 basic route
requests up to $0.06, before free monthly usage, volume discounts or account
agreements. These are request bounds, not a promise of exact billing. Both AI and
rules generation can request facts. Direct editing requests neither.
See [current pricing](https://developers.google.com/maps/billing-and-pricing/pricing)
and [Place Details field billing](https://developers.google.com/maps/documentation/places/web-service/place-details).

Unchosen accommodation options are excluded from automatic sightseeing and hours
lookups. Up to three slots within the existing place lookup cap (one third of
that cap, rounded down) may check coordinates for saved hotel options without
manual/cached coordinates, prioritizing the activity cities. At the default cap,
this leaves at least seven slots for visit details. Hotel requests use only
`id,location`; there is no external hotel search. Duplicate Google IDs use one
lookup. Coordinates alone are cached
for six hours, keyed by Place ID, with a strict allowlist and independent expiry.
Redis must have persistence and backups disabled. No provider names, addresses,
hours, business status, raw responses or route durations enter this cache, SQL,
history or logs. This follows the existing Dreams retention design and
[Places caching exception](https://cloud.google.com/maps-platform/terms/maps-service-terms)
for coordinates; a volatile cache is not permission to cache other content.
Opening hours remain transient and are checked again on explicit rework. Cached
coordinates may still support estimated buffers if live facts are unavailable.

User-supplied coordinates and scheduling windows remain authoritative. Missing
facts stay unknown. Walking/driving haversine buffers are explicitly estimates.
Public transport transfers remain unverified until routing can use each final
departure date/time and the provider's supported timetable window. Exact Google
route durations are removed before plan persistence; only the user's chosen
schedule remains. `refresh_plan_travel` uses manual/cached coordinates without
paid calls to provide independent app estimates after generation, direct edits,
and reads. Each displayed leg names its preceding physical stop and chosen
allowed mode. Text breaks are skipped; an unlocated booking resets the chain.
Legs are day-local, and no first-stop estimate is invented from the previous day.
A known unavailable route remains unknown through storage/read refresh until
the itinerary changes. Sparse saves produce a sparse draft, with all unscheduled
ideas visible for manual planning.

Both AI selections and rules fallback distribute saves over the available dates
and prioritize
venues whose supplied hours leave only the current day available. Unknown local
transfers use an explicitly unverified buffer; unknown city-to-city journeys are
left unscheduled. Fixed breaks do not erase the physical destination that must
be reached next, and single-day rework checks the next fixed commitment.
An empty day carries a short explanation rather than invented activities.
AI selections influence day/order preferences; other eligible saves remain
available to complete the trip. Daily pacing counts distinct venue identities
with usable remaining dates, excludes known infeasible transfers, and reserves
flexible ideas for later uncovered days. A provider-free fit calendar checks at
most 200 ideas × 31 dates once per scheduling pass; it never spends route calls.
Actual placements retain the existing route request and elapsed-time caps.
After each placement or rejected connection, the remaining allowance can shrink
using cached facts and the newly known location, preserving later-day coverage
when an initially plausible outlier turns out not to fit.
When the first pin is unknown, known candidate bases are compared by the future
saved venues they can still reach. A candidate's effect on the reservation is
checked before adding it. Same-city missing pins retain earlier geographic
evidence for feasibility only; they never inherit coordinates or verified travel
times. An unlocated journey or city change resets that geographic context.
Meal venues use lunch/dinner windows and normally have a two-meal daily limit;
explicit cafe/coffee/bakery labels remain separate from meals.

Trips can allow several `transport_modes`; the legacy `transport` is the first
mode. Nearby coordinate-known legs prefer walking when allowed, then driving
or transit for longer legs. Transit durations stay unknown without a verified
timetable. Neither mode choice nor straight-line estimates imply a usable road,
footpath, border crossing or public transport service; confirm routes before
travelling.

Each day may carry `stay: {status, idea_id?, city?, reason?}`. Status is `needed`,
`suggested`, `selected` or `not_needed`. Only saved accommodation is suggested;
there is no external hotel search. Suggestions require coordinates within 5 km
walking / 20 km driving or transit of that day's final location, with consistent
canonical country evidence. A shared city label alone leaves accommodation
needed; those saved options remain available for the user to choose manually.
User-selected stays remain selected and
get a clear warning when far away or the transfer is unknown; selection does
not confirm a booking or availability. Stays are excluded from unused-idea
counts, and the final departure day defaults to `not_needed`.

Rework preserves user-entered visit durations and notes. A manually selected
accommodation remains selected, while other hotel options stay in Ideas. Locked
stops and days outside a one-day rework retain their saved timing and identity.
Editable custom text uses `kind: break, user_created: true` and survives rework
without requiring a lock. Legacy text breaks are preserved too. Engine-created
lunch breaks use `generated: true` so future rework can replace them.
Draft generation never alters the accepted plan automatically.

## Result explanations

Plans may include an optional `unplaced_reasons` map keyed by unscheduled activity
idea IDs. Each entry has an allowlisted `code` and, only for a transport limit,
`transport_mode`. The codes are `needs_location`, `processing`, `closed`,
`opening_hours`, `transport_required`, `travel_unverified`, `low_interest`,
`duplicate`, and `no_fit`. Accommodation options never receive failed-activity
reasons. Existing `unplaced_idea_ids` remain compatible with older clients.

Explanations come from the scheduler's observed decisions. A walking-limit
reason requires the saved point to be beyond the limit from every known planned
activity point; unknown geography does not establish this. Uncertain cases use
neutral `no_fit` copy. Opening-window decisions persist no opening times, and
the `closed` code is reserved for manually supplied flags; Google business status
and response text are not retained. Validation discards unknown IDs/codes/fields,
scheduled references, hotel references, and obsolete transport modes or corrected
location details. Ordinary edits and these explanations make no new provider call.

Mobile shows activities and saved stay options separately before generation and
in the result. A compact unscheduled activity section exposes explanations and
offers Getting around only for an applicable transport limit. Saving transport
options does not regenerate a plan. Older plans without reasons show neutral
copy, and their obsolete all-ideas-unused warning is hidden.

All displayed times use the trip's selected IANA timezone; the engine does not
guess a new timezone when cities change. Elapsed booking durations account for
clock changes, and nonexistent spring-forward times are rejected. The current
clock-only editor cannot distinguish the two occurrences of a repeated fall-back
hour; such times remain explicitly flagged for confirmation. Multi-zone trips
still need the traveller to check booking times in the selected trip timezone.

The model receives only allowlisted supplied IDs, original saved labels, votes,
categories and relevant scheduling facts. Raw captions, private notes, provider
response bodies and reasoning content are excluded. Failure diagnostics contain
only safe counts and finish status. Invalid output produces a truthful rules
fallback with billed or conservatively estimated usage retained.

## Verification

Run `python -m pytest tests/test_planner_engine.py -q` from `backend`. Tests are
offline and block unexpected network requests. They cover identity and locks,
dates/overlaps, one-day rework, opening windows, routing failure, hotel selection,
uncertain geography, sparse-day pacing, voting, DST transitions, preservation of
manual choices, AI budgets/usage/output validation, and coordinate-cache
retention, reuse, expiry and failure. Live provider quality and billing checks
are separate, explicit integration exercises.
