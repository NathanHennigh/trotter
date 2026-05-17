# Trotter Trip Enrichment Plan

Trotter should evolve from a flight-history app into a private travel memory system that reconstructs trips from multiple user-approved signals: flights, lodging, restaurants, activities, calendar events, photos, location history, and optional live trip tracking.

The purpose of this feature set is to make each trip feel complete. Flights explain how the user got somewhere. Enrichment explains where they stayed, what they did, where they ate, what they saw, and how the trip unfolded day by day.

## Product Goal

When a user taps into a trip, Trotter should show a rich, confidence-aware trip timeline:

- Flights and other transport.
- Hotels, Airbnbs, and other stays.
- Restaurant reservations.
- Experiences, tours, events, and sights.
- Photo clusters from the trip.
- A map of meaningful places visited.
- Optional path reconstruction from imported or live location data.
- Confidence indicators showing what was confirmed, inferred, or needs review.

The product should not claim perfect knowledge. It should feel magical because it finds the likely shape of a trip, validates it across signals, and lets the user approve, edit, or delete anything quickly.

## Privacy Positioning

This feature should be designed as a privacy-forward reconstruction engine:

- Ask explicitly which data sources the user wants to share.
- Keep raw photos on device.
- Prefer on-device parsing and clustering when feasible.
- Upload only derived, approved itinerary data.
- Avoid storing raw email bodies, raw calendar descriptions, raw Timeline files, or raw location streams unless the user has explicitly opted in.
- Make every imported source reviewable and deletable.
- Treat location history as sensitive personal data, not ordinary app telemetry.

The ideal user-facing promise is:

> Trotter can reconstruct your trip privately on your phone, then sync only the places and memories you approve.

## Onboarding Permissions

Onboarding should present separate consent choices instead of one broad permission wall.

Recommended options:

- **Flights from email**: import flights and build the travel map.
- **Reservations from email**: find hotels, Airbnbs, restaurants, tours, and activities.
- **Calendar events**: use calendar events to find reservations and validate trip dates.
- **Photo locations**: scan on-device photo timestamps and GPS metadata to place photos on trips.
- **Timeline import**: import historical Google Timeline / location history exports.
- **Live trip tracking**: allow Trotter to record location while traveling.

Each option should explain what is read, what is stored, and how to delete it.

## Ongoing Location Modes

Trotter should offer three clear modes for future location services.

### No Location Tracking

Trotter does not record native background location.

The app still builds trips from:

- Flight emails.
- Hotel and Airbnb emails.
- Restaurant and experience emails.
- Calendar events.
- User-approved photo location metadata.
- Manual edits.
- Optional Timeline imports.

This is the default privacy-first mode and should be enough for many users.

### Trip Mode

The user turns on tracking for a specific trip or travel window.

Trotter records low-power location signals during that trip to:

- Build a trip path.
- Detect places visited.
- Confirm hotels and restaurants.
- Group photos into stops.
- Create a more complete day-by-day timeline.

This mode is easier to explain and safer from a platform-review perspective because the tracking is clearly tied to a user-facing trip feature.

### Always-On

The user allows Trotter to work in the background continuously.

Trotter can:

- Detect when a trip starts.
- Auto-create trips.
- Notice new cities and overnight stays.
- Build draft trip timelines without manual setup.
- Prompt the user to review newly detected trips.

This is the most magical version, but also the most sensitive. It requires excellent disclosures, battery discipline, obvious controls, and an easy way to pause or delete history. It should not be the default.

## Data Sources

### Email

Email remains the strongest source for confirmed travel intent.

Useful data:

- Flight confirmations.
- Hotel and Airbnb confirmations.
- Restaurant reservations.
- Event tickets.
- Tours and experiences.
- Cancellation and change notices.
- Confirmation numbers.
- Addresses.
- Guest names.
- Dates and times.

Strengths:

- High precision when structured markup or recognizable providers are present.
- Good for confirmation numbers and status.
- Already fits Trotter's current Gmail ingestion direction.

Weaknesses:

- Inconsistent formats.
- Forwarded emails can be messy.
- Marketing emails can create false positives.
- Changes and cancellations require careful handling.

### Calendar

Calendar import is highly valuable because many bookings land there automatically.

Useful data:

- Event title.
- Start and end time.
- Location string.
- Notes or description.
- Attendees.
- Calendar source.

Strengths:

- Good date and time structure.
- Strong complement to email.
- Often contains restaurants, hotels, events, and flights.

Weaknesses:

- Location strings may be vague.
- Notes can contain raw personal content.
- Calendar permissions are sensitive.
- Not every reservation creates a calendar event.

### Photos

Photo enrichment should run primarily on-device.

Useful data:

- Capture timestamp.
- GPS latitude and longitude, when available.
- Photo clusters by date and place.
- Trip photo counts.
- Representative images for trip memories.

Strengths:

- Strong evidence the user was physically near a place.
- Excellent for validating restaurants, sights, and hotels.
- Makes trip pages emotional and visual.

Weaknesses:

- Many photos lack GPS metadata.
- Some users disable location tagging.
- Platform permissions vary.
- Cloud photo APIs may not expose location metadata reliably.

The app should avoid uploading raw photos unless the user explicitly attaches or shares them.

### Google Timeline Import

Timeline should be treated as a historical import source, not a live API dependency.

Useful data:

- Past routes.
- Stops.
- Visits.
- Overnight locations.
- Place names, where available.

Strengths:

- Best source for reconstructing the full path of old trips.
- Can fill gaps where photos or emails are missing.
- Great validator for lodging and restaurant reservations.

Weaknesses:

- Import flow may be manual.
- Export formats may change.
- Data can be noisy.
- Highly sensitive from a privacy standpoint.

### Native Live Location

Native location tracking can cover future trips.

Useful data:

- Significant location changes.
- Visit detection.
- Overnight clusters.
- Trip start/end detection.
- Place dwell time.

Strengths:

- Enables automatic trip creation.
- Fills the gap left by Google Timeline's import-based model.
- Can make Trotter feel alive without user bookkeeping.

Weaknesses:

- Battery cost.
- Platform-review scrutiny.
- Requires very clear consent.
- Always-on mode may make some users uncomfortable.

## Evidence And Confidence Engine

The core product idea is not just importing data. It is cross-validating evidence.

Example:

```text
Candidate: Hotel stay at Hilton Tokyo
Dates: Apr 4-Apr 7

Evidence:
- Lodging confirmation email found.
- Calendar event overlaps the stay.
- Photo clusters appear near the hotel.
- Timeline import shows overnight stops nearby.

Result:
High-confidence confirmed stay.
```

Confidence should be computed from independent signals:

- Email reservation match.
- Calendar match.
- Photo GPS match.
- Timeline or live location match.
- Time overlap with trip dates.
- Distance from known trip route.
- Provider reliability.
- Cancellation or modification status.
- User confirmation.

Suggested confidence states:

- **Confirmed**: strong multi-source match or user-approved.
- **Likely**: good evidence from one strong source or multiple weaker sources.
- **Needs review**: plausible but ambiguous.
- **Ignored**: user rejected it.

## Place Detection

Trotter should infer places from clusters, not individual pings.

For photos and location data:

- Group nearby points by time window.
- Detect overnight clusters as lodging candidates.
- Detect shorter dwell clusters as restaurants, sights, shops, museums, parks, or neighborhoods.
- Match clusters to known reservations.
- Use place lookup only after local clustering reduces the data surface.

This lets the app minimize what it sends to the server. For example, instead of uploading every location point, the app can produce local candidate clusters and only sync approved places.

## Proposed Data Model Direction

Flights should remain movement segments. Lodging, restaurants, events, and sights should become itinerary items.

Potential tables:

- `trips`: existing trip entity.
- `segments`: flights and future movement.
- `itinerary_items`: stays, restaurants, events, experiences, sights, notes.
- `places`: normalized hotels, restaurants, venues, landmarks, airports.
- `evidence`: links between itinerary items and supporting sources.
- `user_data_sources`: permission/source state per user.
- `location_clusters`: derived stops, optionally local-only or approved-sync only.

Potential `itinerary_items` types:

- `lodging`
- `restaurant`
- `experience`
- `event`
- `sight`
- `transport_ground`
- `note`

Potential evidence types:

- `email`
- `calendar`
- `photo_location`
- `timeline_import`
- `live_location`
- `manual_user_confirmation`

## Recommended Build Order

### Phase 1: Trip Detail Foundation

Create the trip detail surface that can display more than flights:

- Timeline.
- Map focused on the trip.
- Segments and itinerary items.
- Source/confidence badges.
- Manual add/edit/delete.

Purpose: give all enrichment work a home.

### Phase 2: Lodging From Email

Parse hotels and Airbnb-style stays from Gmail.

Purpose: lodging is the highest-value non-flight object and easiest to validate.

### Phase 3: Calendar Import

Add calendar event import and matching.

Purpose: calendar provides structured times and fills in restaurants, tours, and reminders.

### Phase 4: Photo Location Matching

Scan photo metadata on-device and attach photos or photo clusters to trips.

Purpose: make trips visual, validate places, and infer sights visited without uploading raw images.

### Phase 5: Timeline Import

Allow users to import past Google Timeline data.

Purpose: reconstruct historical trip paths and enrich older trips.

### Phase 6: Trip Mode

Add explicit per-trip location tracking.

Purpose: support future trips without requiring Timeline and with a clear user-facing privacy story.

### Phase 7: Always-On Autocreation

Add optional always-on trip detection.

Purpose: make Trotter automatic for power users who want the most complete experience.

## Accuracy Expectations

Expected accuracy depends heavily on the user's permissions and data quality.

Email and calendar only:

- Flights: very high when already supported.
- Lodging: high precision, medium-high recall.
- Restaurants: medium precision, medium-low recall.
- Experiences: medium-high precision, medium recall.
- Sights visited: low unless present in calendar.

Photos added:

- Trip photo grouping improves significantly.
- Sights and restaurants become more inferable.
- Reservation validation improves.
- Recall depends on whether photos are geotagged.

Timeline or live location added:

- Full path reconstruction becomes realistic.
- Overnight stay detection improves.
- Restaurant and sight inference improves.
- False positives must be managed through review and confidence states.

Best-case experience with email, calendar, photos, and location:

- Lodging can feel near-confirmed.
- Restaurants can feel reliable when reservation and location agree.
- Sights can feel plausible and useful, but should remain editable.
- Trip paths can become highly complete for users with dense location data.

## Key Product Principle

Trotter should never make users feel surveilled by surprise.

The magic should come from consent, transparency, and control:

- "We found this."
- "Here is why we think it belongs to your trip."
- "Here is what confirmed it."
- "Edit, remove, or keep it."

That design makes the product feel intelligent without feeling invasive.
