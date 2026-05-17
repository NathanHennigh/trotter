# Trotter Product Roadmap

Trotter should grow from a beautiful flight history app into a personal travel identity product: part passport, part trip journal, part social travel graph. The near-term goal is to make the existing synced flight data feel valuable, emotional, and complete before expanding into planning, collaboration, and monetization.

## Product Spine

Trotter should organize around three major user modes:

- **Passport**: who you are as a traveler.
- **Trips**: what you did, where you went, and what happened there.
- **Dreams**: where you want to go next.

The current globe remains the emotional home screen, but Passport and Trip Details are the product surfaces that make the data feel real.

## Phase 0.5: Import Reliability And Human Review

Before layering too much product on top of flight history, Trotter should make the import pipeline increasingly reliable without pretending the parser is perfect.

The parser should improve in two ways at once:

- **General extraction patterns**: structured email schemas, calendar attachments, route/date/time tables, airline-code flight rows, airport-pair patterns, and generic itinerary language.
- **Provider-specific refinements**: targeted support for repeated formats from airlines and booking platforms when the general parser cannot safely infer the details.

Provider-specific parsing should be treated as training wheels for recurring formats, not the long-term model. Every new provider rule should ideally reveal a reusable pattern that can be folded into a broader parser later.

### Review Queue

When Trotter sees plausible flight evidence but cannot confidently produce a complete segment, it should create a review item instead of silently dropping the email.

Examples that should enter review:

- likely flight email but missing arrival time, departure time, airport, or passenger match
- flight confirmation in another passenger's name where the user may still appear elsewhere on the ticket
- change, cancellation, boarding pass, receipt, or reminder that references a real trip but may not be the canonical itinerary
- parsed route with weak identity confidence
- duplicate-looking itinerary where Trotter is not sure whether it is a new flight or a copy/reminder

The review UI should let users:

- confirm this is their flight
- mark it as not theirs
- correct airports, dates, times, airline, flight number, passenger name, or trip assignment
- mark it as duplicate, change, cancellation, or reminder
- attach the item to an existing trip or create a new trip

### Feedback Loop

Human review should improve Trotter over time.

User feedback should be stored as structured decisions, not raw email bodies. The system can use those decisions to:

- avoid re-asking about rejected messages
- strengthen identity matching for current, legal, and previous names
- identify missed parser patterns for development
- prioritize which airlines, booking platforms, and email formats need better deterministic support
- improve confidence scoring for future imports

Onboarding should ask for the user's current name plus optional legal names, previous names, married names, nicknames, initials, and common travel document names. Users should be able to edit these later in profile settings.

These names should feed identity matching, parser confidence, and review prompts. If a booking is in someone else's name but one of the user's names appears in the passenger section, Trotter should treat it as a plausible user flight and ask for review when confidence is not strong enough to auto-accept.

### Trip Discovery And Organization Deep Dive

Flight extraction and trip reconstruction are related but separate problems. Once the parser finds the individual legs reliably, Trotter still needs a more deliberate trip model that can distinguish:

- true destinations from layovers and same-day connections
- one trip from several nearby trips
- repeated emails from repeated flights
- codeshares from duplicate segments
- open-jaw itineraries from bad parser output
- impossible or conflicting itineraries that need review
- historical changes in a user's home airport or travel pattern

The current deterministic builder is a useful foundation, but trip organization needs its own focused design pass. That work should likely include:

- layover detection using stop duration, route continuity, and return-path evidence
- stronger itinerary graph logic across PNRs, airlines, and nearby airports
- trip confidence scores and review states, separate from segment confidence
- explicit handling for impossible chronology, missing connector legs, and suspicious country claims
- user tools to merge, split, rename, or correct trips
- regression fixtures from real edge cases such as layover-only Taiwan/Narita labels, repeated Orlando codeshares, and phantom destinations that the user says they never visited

The product should not treat a parsed flight leg as proof that a user visited the connection city or country. A trip's title, visited-country count, and Passport stats should be based on the best-supported destination model, with user review when the graph is ambiguous.

### Changes And Cancellations

Change and cancellation emails should be tracked as update evidence, not treated like ordinary new flight confirmations.

The likely matching key is confirmation number / PNR, with flight number, route, passenger name, and message date as supporting evidence. Trotter should keep the latest trusted itinerary for a booking, but it should also preserve enough evidence to explain what changed.

Open policy decisions:

- If a cancellation email references an entire PNR, should Trotter hide/remove all future segments from that booking automatically, or mark them canceled and show them in trip history?
- If a change email gives a new time or route for the same PNR, should Trotter automatically supersede the old segment when confidence is high, or require review first?
- Should past canceled/changed flights remain visible in Passport stats, or only flown/likely-flown segments should count?
- Should boarding passes and reminders be allowed to fill missing details, or only confirmation/eTicket emails should be allowed to override existing itinerary data?

## Phase 1: Passport And Stats

This is the most important next product feature. It turns raw flight history into identity, reward, and shareable moments.

### Core Stats

- Total countries visited, with a country breakdown.
- Total airports visited.
- Total airlines flown.
- Total miles flown.
- Flights by year.
- Furthest flight.
- Longest trip.
- Furthest destination from home.
- Most visited airport.
- Most common route.
- First discovered flight.
- Travel streak / years flying timeline.

### Fun And Niche Stats

These are the details that make the app feel alive:

- Aircraft models flown on, when available from email data or enrichment APIs.
- Most-flown aircraft model.
- Longest aircraft type flown.
- Newest / oldest aircraft flown, if reliable data is available.
- Worst weather flown through, based on historical weather near departure/arrival times.
- Hottest arrival, coldest arrival, rainiest arrival.
- Earliest departure, latest arrival, longest layover.
- Most chaotic travel day.
- Most repeated airport pair.
- Airport personality stats, like "most loyal airport" or "gateway city."

These should be treated as delightful extras, not core correctness requirements. If confidence is low, the app should either hide the stat or label it clearly.

### Year Travel Cards

Create annual "Travel Wrapped" cards designed for sharing:

- "Your 2025 in travel"
- flights, miles, countries, airports, airlines
- longest flight
- top destination
- map snapshot or route collage
- fun stat of the year

These should target the same emotional behavior as Spotify Wrapped: users should want to post them because they feel personal and premium.

### Digital Passport

The Passport should feel collectible and premium:

- country-by-country visited list
- animated passport opening / page turn moments
- custom country stamps
- stamp dates based on first visit
- regional collections
- milestone animations, such as 10 countries, 25 countries, every continent

Custom stamps should be generated from country metadata and visual templates, not manually designed one by one.

## Phase 2: Trip Detail Screen

Every trip needs a dedicated full-screen home. This should come immediately after Passport.

### Trip Detail Contents

- Trip title, dates, and duration.
- Globe or map focused only on that trip.
- Full leg timeline.
- Total distance.
- Airports visited.
- Countries and cities visited.
- Airlines and flight numbers.
- Source/confidence status for parsed data.
- Notes and attachments later.

The trip detail screen becomes the foundation for photos, location enrichment, sharing, and eventual itinerary monetization.

## Phase 3: Personal Trip Memories

Personal trip memories should come before social sharing.

### Photos

Start with manual photo attachment to trips, then add smarter import flows.

Possible integrations:

- Google Photos
- iCloud Photos / Apple Photos on device
- local device photo library

The cross-platform goal is that iOS and Android users can both enrich trips, then later share collaborative albums regardless of device ecosystem.

### Albums

Initial version:

- attach photos to a trip
- organize photos by trip date
- simple trip album view

Later:

- auto-suggest photos by trip date range and location metadata
- shared albums
- friends can join and add photos

## Phase 4: Deeper Location And Trip Enrichment

Flight data explains how a person moved between places. Location data explains what they actually did.

Possible sources:

- Google Maps Timeline / location history export
- on-device location history, where allowed
- photo GPS metadata
- hotel, restaurant, and activity confirmation emails

Trip enrichment should extract:

- hotels
- restaurants
- sights
- neighborhoods
- transit
- day-by-day stops
- places visited

Privacy is critical. Location import should be explicit, reviewable, and deletable. Users should be able to approve what becomes part of a trip.

## Phase 5: Sharing

Sharing should start free and personal before becoming commercial.

### Private Sharing

- share a trip page with friends
- share a trip album
- invite friends to contribute photos
- export a beautiful trip recap

### Public Sharing

- public profile
- public trip pages
- creator-style trip pages
- save/copy trip inspiration

This is where Trotter begins moving toward the "Strava of travel" vision.

## Phase 6: Planning And Points

Trip planning is powerful, but it may be a separate product direction. It should not bloat the core app too early.

Possible Trotter integration:

- wishlist destinations
- dream trips
- basic trip ideas
- save inspiration from public trips

Possible standalone app direction:

- fare tracking
- points wallet
- credit card rewards tracking
- alerts when a trip is bookable with points
- "where can I go with my points?"
- cash vs points recommendations

This could become its own app if the planning and rewards feature set becomes too large or utility-focused for Trotter's travel identity product.

## Phase 7: Creator Monetization

Creator monetization is the long-term distribution and revenue play, but it should wait until users already love creating and sharing trips.

### Future Creator Trip Page

- flights
- hotels
- restaurants
- activities
- photos and videos
- map and timeline
- budget estimates
- booking links
- "copy this trip"
- "save to wishlist"
- paid full itinerary

### Marketplace Path

Start with influencers and high-quality public trips. Let users discover, save, and eventually buy complete itineraries.

This should be introduced only after the private trip product has traction.

## Recommended Build Order

1. Import reliability and human review queue.
2. Passport / Stats screen.
3. Year Travel Cards.
4. Digital Passport with animated country stamps.
5. Trip Detail screen.
6. Manual trip photos and notes.
7. Trip album view.
8. Google Photos / iCloud / device photo import.
9. Location and place enrichment.
10. Free shareable trip pages.
11. Public profiles and public trips.
12. Planning / wishlist.
13. Points and deal alerts, possibly as a separate app.
14. Creator itinerary marketplace.

## Near-Term Product Principle

Make the synced travel history feel magical before adding too many new jobs for the user.

The next two features should be:

1. **Import reliability and human review**
2. **Passport / Stats**
3. **Trip Detail**

Those make the current data dramatically more valuable and create the foundation for every later feature.

## Trip Discovery And Organization Deep Dive

Current parser quality is now ahead of the trip graph. The next serious reliability pass should focus on reconstructing the *actual journey*, not just grouping parsed segments by time.

Known cases to handle deliberately:

- distinguish real destinations from layovers and technical/refuel stops
- preserve richer through-flight itineraries when later emails only expose a partial stopover leg
- reject impossible parser artifacts before they become visible trips
- merge duplicate/codeshare representations without erasing legitimate changed itineraries
- represent open-jaw, nested, and multi-country trips without inventing false destinations
- make title generation depend on the final organized journey, not whichever airport happens to be last in a noisy cluster

This deserves its own design pass with source-message provenance, stopover semantics, and user-correction hooks rather than a long tail of one-off clustering rules.
