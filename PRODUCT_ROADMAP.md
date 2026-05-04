# Trotter Product Roadmap

Trotter should grow from a beautiful flight history app into a personal travel identity product: part passport, part trip journal, part social travel graph. The near-term goal is to make the existing synced flight data feel valuable, emotional, and complete before expanding into planning, collaboration, and monetization.

## Product Spine

Trotter should organize around three major user modes:

- **Passport**: who you are as a traveler.
- **Trips**: what you did, where you went, and what happened there.
- **Dreams**: where you want to go next.

The current globe remains the emotional home screen, but Passport and Trip Details are the product surfaces that make the data feel real.

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

1. Passport / Stats screen.
2. Year Travel Cards.
3. Digital Passport with animated country stamps.
4. Trip Detail screen.
5. Manual trip photos and notes.
6. Trip album view.
7. Google Photos / iCloud / device photo import.
8. Location and place enrichment.
9. Free shareable trip pages.
10. Public profiles and public trips.
11. Planning / wishlist.
12. Points and deal alerts, possibly as a separate app.
13. Creator itinerary marketplace.

## Near-Term Product Principle

Make the synced travel history feel magical before adding too many new jobs for the user.

The next two features should be:

1. **Passport / Stats**
2. **Trip Detail**

Those make the current data dramatically more valuable and create the foundation for every later feature.
