# Trotter

Trotter is a personal travel memory app. It turns a person's travel data into a beautiful, private record of where they have been, how they moved through the world, what they did there, and what those trips meant.

The first version begins with flights. A user connects Gmail, Trotter finds flight confirmations, reconstructs flight history, groups flights into trips, and turns that history into a globe, map, trip list, and personal travel stats.

The larger dream is much bigger than a flight tracker. Trotter should become the travel identity layer for a person's life: part passport, part trip journal, part private memory system, part social travel graph, and eventually part marketplace for discovering, copying, and selling great trips.

## The Big Idea

Most people have traveled more than they can easily remember. Their trips are scattered across Gmail, calendars, photo libraries, Google Timeline exports, booking apps, camera rolls, notes, and memory.

Trotter brings that together.

It should answer questions like:

- Where have I been?
- When did I first visit each country?
- What flights did I take?
- What cities did I return to again and again?
- Where did I stay?
- What restaurants did I book?
- What did I see, photograph, and experience?
- What were my biggest travel years?
- What trips shaped me?
- What do I want to do next?
- What trips have my friends taken?
- What trips are worth copying?
- What itineraries could I buy from someone who already did the work?

The product should feel like opening a living passport. It should make travel history feel emotional, collectible, accurate, and worth sharing.

## Product Philosophy

Trotter should feel magical without feeling invasive.

The app can infer a lot, but it should always give the user control. It should say:

- We found this.
- Here is why we think it belongs to your trip.
- Here is what confirmed it.
- Edit, remove, or keep it.

The app should not pretend to know everything perfectly. It should reconstruct trips using evidence, confidence, and user review.

The strongest product promise is:

> Trotter reconstructs your travel life from the data you choose to share, then helps you turn it into a beautiful private record.

## Core Product Modes

Trotter should organize around three major modes.

### Passport

Passport is who you are as a traveler.

It turns raw travel history into identity, rewards, milestones, and stats. This is where users see the shape of their travel life: countries visited, airports visited, airlines flown, miles traveled, favorite routes, longest trips, travel streaks, and yearly progress.

Passport should feel premium and collectible. It should feel less like a dashboard and more like a personal artifact.

### Trips

Trips are what happened.

Each trip should have its own home: a focused map, timeline, flights, stays, restaurants, activities, photos, places visited, notes, and source confidence.

Flights explain how someone moved. Trip enrichment explains what they actually did.

Trips also need to become smarter than a simple list of nearby flights. Trotter should eventually understand the difference between a destination, a layover, a same-day connection, a codeshare duplicate, a missing connector leg, and a genuinely separate trip. When the evidence is messy, the product should ask for review rather than confidently claiming the user visited a place they only changed planes in.

### Dreams

Dreams are where the user wants to go next.

This can start simply: wishlist destinations, saved inspiration, public trips worth copying, and dream trip ideas. Later, Dreams can connect to planning, points, creator itineraries, booking links, and trip marketplaces.

Dreams should also become the place where passive travel inspiration turns into organized intent. When a user sees a destination, restaurant, hotel, activity, landmark, or travel idea on Instagram, TikTok, YouTube, a blog, or another app, they should be able to share it into Trotter and have it saved automatically.

The first version of this should focus on Instagram share-to-Dreams:

1. User sees an Instagram Reel or post.
2. User taps Share.
3. User chooses Trotter.
4. Trotter saves the original link immediately.
5. Trotter extracts useful travel details from the caption or metadata.
6. Trotter identifies the destination, place, business, landmark, or activity when possible.
7. Trotter groups the item into Dreams by country, city, or destination.
8. Trotter attaches a Google Maps result when the match is confident.
9. Trotter marks uncertain items as Needs Review.

This turns Trotter into the user's travel inspiration inbox. Instead of losing great ideas in Instagram saves, screenshots, DMs, notes, and browser tabs, Trotter can organize them into actual future trips.

## Final Form

In its final form, Trotter should become a social travel network and itinerary marketplace built on top of real trips people have actually taken.

People should be able to browse trips from:

- Friends.
- Creators.
- Travel influencers.
- Local experts.
- Ordinary travelers with great taste.
- Public profiles.
- Curated collections.

Users should be able to choose which trips become public. A trip can remain completely private, be shared only with friends, or become a public trip page. Public trip pages can include the itinerary, map, timeline, flights, hotels, restaurants, experiences, notes, budget context, tips, and selected photos.

The long-term marketplace idea is that great trips become reusable products. Someone who planned a perfect honeymoon, food weekend, national parks route, ski trip, bachelor party, family vacation, or two-week Japan itinerary should be able to package that trip and sell it. A traveler looking for inspiration should be able to browse real trips, trust that someone actually took them, and buy or copy the itinerary.

This creates two sides of the product:

- **For travelers**: discover proven trips worth taking.
- **For creators**: turn travel knowledge and taste into income.

Influencers can use Trotter as another way to monetize their travel. Instead of only posting content, they can sell the actual trip: where they stayed, what they booked, what they skipped, what they would do again, and what they would change. Laypeople can also participate. A great trip does not need to come from a professional creator to be useful.

The social side should still preserve user control. Trotter should make it easy to decide:

- Which trips are private.
- Which trips are shared with friends.
- Which trips are public.
- Which photos are attached.
- Which photo locations are shown.
- Which hotels, restaurants, or exact addresses are hidden.
- Whether a public trip is free, paid, or just inspirational.

The final product should feel like Strava for travel, but with richer memories and more utility. Friends can show off trips, compare stats, compete on travel milestones, and browse each other's adventures. Creators can publish beautiful trip pages. Travelers can find trips that are not generic blog posts, but real itineraries with maps, photos, timing, and practical details.

## Current Foundation

The current product foundation is flight history.

Trotter can connect to Google, read Gmail with user consent, find flight-related emails, parse flight segments, group them into trips, and display those trips in the app. The current direction includes a FastAPI backend, Gmail OAuth, encrypted refresh tokens, background import jobs, trip and segment storage, and a React Native mobile app.

The important product foundation is not the specific stack. It is the pipeline:

1. User gives consent.
2. Trotter imports travel evidence.
3. Trotter parses structured trip data.
4. Trotter groups the data into trips.
5. Trotter enriches the data with useful context.
6. Trotter shows the user a beautiful, reviewable travel record.

That pipeline can expand from flights into the rest of the travel experience.

## What Makes Trotter Different

Trotter is not just an itinerary app. It is not just a map. It is not just a photo album. It is not just a travel planning tool.

Trotter is a personal travel graph.

It connects:

- Flights.
- Airports.
- Airlines.
- Countries.
- Cities.
- Hotels and Airbnbs.
- Restaurants.
- Tours and experiences.
- Calendar events.
- Photos.
- Location history.
- Friends.
- Public trips.
- Creator itineraries.
- Marketplace listings.
- Future dreams.

Over time, Trotter should become the place where a user's travel life becomes visible.

## Flight History

Flight history is the entry point.

The app starts by finding flight confirmations in Gmail and turning them into structured flight segments. Each segment can include airline, flight number, departure airport, arrival airport, departure time, arrival time, trip grouping, distance, and map geometry.

This creates the first magical moment:

> I connected my email and my travel history appeared.

Flight history powers:

- The globe.
- Flight arcs.
- Trip grouping.
- Travel stats.
- Passport milestones.
- Yearly cards.
- Country and airport counts.
- Future trip detail pages.

Flights are the skeleton. Everything else adds flesh, memory, and emotion.

## Passport And Stats

Passport should be one of the first major product investments after the flight import foundation feels reliable.

Core stats should include:

- Total countries visited.
- Country breakdown.
- Total airports visited.
- Total airlines flown.
- Total miles flown.
- Total time in the air.
- Flights by year.
- Furthest flight.
- Longest trip.
- Furthest destination from home.
- Most visited airport.
- Most common route.
- First discovered flight.
- Travel streaks.
- Years flying timeline.

Fun stats can make the app feel alive:

- Aircraft models flown on, when available.
- Most-flown aircraft model.
- Longest aircraft type flown.
- Newest or oldest aircraft flown, if reliable.
- Worst weather flown through.
- Hottest arrival.
- Coldest arrival.
- Rainiest arrival.
- Earliest departure.
- Latest arrival.
- Longest layover.
- Most chaotic travel day.
- Most repeated airport pair.
- Airport personality stats like "most loyal airport" or "gateway city."

These extra stats should be treated as delightful bonuses. If confidence is low, Trotter should hide them or label them clearly.

## Year Travel Cards

Trotter should create annual travel recap cards.

These should feel like "Your 2025 in travel":

- Flights.
- Miles.
- Countries.
- Airports.
- Airlines.
- Longest flight.
- Top destination.
- Map snapshot.
- Route collage.
- Fun stat of the year.

The goal is the same emotional behavior as Spotify Wrapped: users should want to share them because they feel personal, premium, and accurate.

## Digital Passport

The digital passport should feel collectible.

Possible features:

- Country-by-country visited list.
- Animated passport opening.
- Page-turn moments.
- Custom country stamps.
- Stamp dates based on first visit.
- Regional collections.
- Milestone animations.
- Every-continent moments.
- 10-country, 25-country, 50-country achievements.

The stamps should be generated from country metadata and visual templates, not manually designed one by one. This can make the system scalable while still feeling custom.

## Trip Detail

Every trip should have a full-screen home.

Trip Detail is where Trotter becomes more than a flight map. A trip page should include:

- Trip title.
- Dates and duration.
- A globe or map focused only on that trip.
- Full flight and travel timeline.
- Distance.
- Airports visited.
- Countries and cities visited.
- Airlines and flight numbers.
- Hotels and Airbnbs.
- Restaurants.
- Experiences.
- Events.
- Sights and neighborhoods.
- Photos.
- Notes.
- Attachments.
- Source and confidence status.

Trip Detail is the foundation for almost every long-term feature: photo memories, location enrichment, sharing, creator itineraries, and monetization.

## Itinerary Enrichment

Trotter should expand from flights into the rest of the itinerary.

The app should be able to find:

- Hotels.
- Airbnbs.
- Restaurants.
- Tours.
- Activities.
- Events.
- Museums.
- Shows.
- Ground transport.
- Day-by-day stops.

The most practical first source is email. Many bookings send confirmation emails with structured or semi-structured information. Calendar is also extremely valuable because reservations often appear there automatically.

The product should not just import everything blindly. It should score each candidate by confidence and let users review anything uncertain.

Examples:

- A hotel confirmation email creates a likely lodging item.
- A matching calendar event increases confidence.
- Photos taken near the hotel increase confidence.
- Timeline or live location showing overnight presence confirms it.

The result is not just a list of reservations. It is an evidence-backed trip memory.

## Dreams And Inspiration Capture

Dreams should be both a wishlist and a capture system.

Users already discover travel ideas everywhere: Instagram Reels, influencer posts, travel blogs, restaurant lists, hotel recommendations, Google Maps links, friend texts, TikToks, and screenshots. Most of those ideas disappear into messy save folders that are hard to search and almost impossible to turn into a trip.

Trotter should solve that by letting users save inspiration directly into Dreams.

The first major capture flow should be:

```text
Instagram post or Reel
-> Share to Trotter
-> Save original link
-> Extract caption and metadata
-> Parse travel entities
-> Add to Dreams
-> Group by destination
-> Attach map result when confident
-> Ask for review when uncertain
```

Dream items can include:

- Restaurants.
- Cafes.
- Bars.
- Hotels.
- Attractions.
- Activities.
- Beaches.
- Shopping.
- Nature.
- Museums.
- Events.
- Broad destination ideas.
- Unsorted travel inspiration.

Examples:

- A Reel about Casa Dani in Madrid becomes a restaurant item inside a Spain or Madrid Dream.
- A vague post about "Europe in the summer" becomes an Unsorted Travel Idea marked Needs Review.
- A list of "5 places to save in Lisbon" becomes multiple Dream items grouped under Portugal and Lisbon.
- A hotel recommendation becomes a stay idea with the original Instagram link attached.

This feature is strategically important because it makes Dreams useful before Trotter has a full planning engine. It gives users a reason to open Trotter before, during, and after trips.

It also connects directly to the future marketplace. Public trips and creator itineraries begin as saved inspiration. The more Trotter understands what users dream about, the better it can recommend real trips, creators, and paid itineraries later.

Dream capture should follow the same confidence philosophy as trip enrichment:

- Never invent exact place names.
- Save vague ideas without overclaiming.
- Attach Google Maps only when there is enough evidence.
- Use Needs Review for ambiguous or inferred items.
- Keep the original source link for context.
- Let users edit, merge, delete, or convert Dream items into real trip plans.

## Photos

Photos are one of the most important emotional layers.

Trotter should start with manual photo attachment, then move toward smarter import and matching.

Possible photo sources:

- Local device photo library.
- Apple Photos on device.
- iCloud-accessible local assets where available.
- Google Photos where useful, though cloud APIs may not expose location metadata reliably.

The ideal approach is on-device:

- Scan photo timestamps.
- Read GPS metadata when the user allows it.
- Match photos to trip date ranges.
- Cluster photos by location.
- Suggest places, sights, and restaurants.
- Let users approve what is attached or synced.

Raw images should not be uploaded unless the user explicitly attaches, shares, or backs them up through Trotter.

Photos make the app feel personal. They also help validate the itinerary. If Trotter thinks a user had dinner at a restaurant and there are photos from that location at that time, the reservation becomes much more trustworthy.

## Location And Timeline

Location data explains what happened between flights.

Trotter should support multiple levels of location sharing so users can choose their comfort level.

### No Location Tracking

The user chooses not to allow native background tracking.

Trotter still builds trips from:

- Flight emails.
- Hotel and Airbnb emails.
- Restaurant and experience emails.
- Calendar events.
- Photo location metadata.
- Manual edits.
- Optional historical Timeline imports.

This should be the default privacy-first mode.

### Trip Mode

The user turns on tracking for a specific trip.

Trotter can record low-power location signals during that trip to:

- Build a trip path.
- Detect places visited.
- Confirm hotels and restaurants.
- Group photos into stops.
- Create a complete day-by-day timeline.

This is the clearest and safest live tracking mode because it is tied to a specific user-facing trip.

### Always-On

The user allows Trotter to work in the background continuously.

This can unlock the most magical experience:

- Auto-detect when a trip starts.
- Auto-create trips.
- Notice new cities and overnight stays.
- Build draft trip timelines.
- Prompt the user to review newly detected trips.

Always-on should be optional, clearly explained, battery-conscious, pauseable, and deletable. It should never be required.

### Google Timeline Import

For historical location, Google Timeline should be treated as an import source rather than a live API dependency.

Timeline imports can help reconstruct:

- Past routes.
- Stops.
- Visits.
- Overnight locations.
- Place names.
- Day-by-day movement.

This is powerful but sensitive. Users should explicitly import, review, and delete this data.

## Calendar

Calendar is a high-value enrichment source.

It can contain:

- Flights.
- Hotel stays.
- Restaurant reservations.
- Tours.
- Events.
- Shows.
- Meetings.
- Locations.
- Start and end times.
- Confirmation notes.

Calendar is especially useful because it provides structured dates and times. It may validate email parsing, fill in missing reservations, and help distinguish real travel events from marketing emails.

Calendar data can also be private, so Trotter should avoid storing raw descriptions unless necessary and should prefer derived itinerary data.

## Evidence And Confidence

The enrichment engine should be based on evidence.

Potential evidence sources:

- Email.
- Calendar.
- Photo location.
- Timeline import.
- Live location.
- User confirmation.

Confidence states should be simple:

- Confirmed.
- Likely.
- Needs review.
- Ignored.

This helps Trotter remain useful even when data is imperfect.

A good experience might look like:

```text
Hilton Tokyo
Apr 4-Apr 7

Confirmed by:
- Hotel confirmation email.
- Calendar event.
- 14 photos nearby.
- Overnight location cluster.
```

That is the heart of the product: not just importing data, but explaining why Trotter believes something belongs to a trip.

## Human Review And Parser Feedback

Trotter should never silently throw away useful travel evidence just because the parser is not fully certain.

If an email, calendar event, photo cluster, or location signal looks travel-related but has missing or uncertain details, Trotter should create a review item. The user can confirm it, correct it, attach it to a trip, mark it as not theirs, or dismiss it as a duplicate, reminder, change, cancellation, or irrelevant message.

For flights, this matters especially when:

- The email appears to be a flight but one or more details are missing.
- The booking is in another person's name but the user appears as a passenger.
- The message is a forwarded itinerary.
- The email is a change notice, cancellation, receipt, boarding pass, or reminder.
- The parser found a route but has weak confidence in date, time, or identity.

This review flow makes Trotter feel honest. It also creates a durable feedback loop. User decisions can improve future imports, strengthen identity matching, and help prioritize new deterministic parser patterns without relying on AI in production.

Onboarding should collect the user's current name and optional travel identity aliases: legal name, previous names, married names, nicknames, initials, and common passenger-name formats. The user should be able to update these later from profile settings.

These names should be part of the evidence model. If an email is addressed to someone else but the user's name or previous name appears in the passenger list, Trotter should treat it as a plausible match and send it to review when needed instead of ignoring it.

Change and cancellation emails should become update evidence. If a later message with the same confirmation number changes or cancels a flight, Trotter should be able to connect it to the existing trip and decide whether the old segment is superseded, canceled, or needs review. The app should not silently rewrite travel history when the evidence is ambiguous.

## Privacy And Trust

Privacy should be a product feature, not just a policy page.

Trotter should ask explicitly what the user wants to share:

- Flights from email.
- Reservations from email.
- Calendar events.
- Photo locations.
- Timeline import.
- Live trip tracking.
- Always-on location.

Each permission should explain:

- What Trotter reads.
- What Trotter stores.
- What stays on device.
- What gets synced.
- How to delete it.

Important principles:

- Do not persist raw email bodies.
- Keep raw photos on device unless the user explicitly uploads them.
- Prefer local clustering of photo and location points.
- Sync only approved derived data where possible.
- Make review and deletion easy.
- Never surprise users with background location behavior.

The trust posture should be central to the brand.

## Sharing

Sharing should come after private memories feel valuable, but it is central to the final form of Trotter.

Private sharing should include:

- Share a trip page with friends.
- Share a trip album.
- Invite friends to contribute photos.
- Export a beautiful trip recap.
- Share selected stats and milestones.
- Compare trips with friends in a Strava-like way.

Public sharing can come later:

- Public profile.
- Public trip pages.
- Creator-style trip pages.
- Save or copy trip inspiration.
- Browse public trips from friends, creators, and other travelers.
- Follow people whose travel taste you trust.
- Discover trips by destination, theme, budget, length, season, or travel style.

This is where Trotter starts to become the "Strava of travel." Users should be able to turn private travel memories into shareable stories when they choose.

Public sharing should be flexible. A user might share:

- A whole trip.
- A single day.
- A route.
- A restaurant list.
- A hotel review.
- A map without exact lodging.
- A photo album.
- A polished recap.
- A copyable itinerary.

Because photos are already associated with trips, Trotter can make sharing easy. Users should be able to select which photos become public. They can attach photos broadly to the trip, or place them on the map at specific destinations and stops. Geotagged public photos should always be opt-in, especially near lodging or sensitive locations.

## Planning And Dreams

Trip planning is powerful, but it should not bloat the core product too early.

Possible Trotter features:

- Wishlist destinations.
- Dream trips.
- Basic trip ideas.
- Saved inspiration from public trips.
- Copyable itineraries.
- Share-to-Dreams from Instagram and other apps.
- Destination-based idea boards.
- Needs Review inbox for vague inspiration.
- Dream-to-trip conversion.
- Auto-generated draft itineraries from saved places.

Possible future standalone or adjacent product:

- Fare tracking.
- Points wallet.
- Credit card rewards tracking.
- Alerts when a trip is bookable with points.
- "Where can I go with my points?"
- Cash vs points recommendations.

The main app should first make past travel feel magical. Planning should grow from that foundation.

## Creator And Marketplace Vision

Creator monetization is a long-term opportunity.

A future creator trip page could include:

- Flights.
- Hotels.
- Restaurants.
- Activities.
- Photos and videos.
- Map and timeline.
- Budget estimates.
- Booking links.
- "Copy this trip."
- "Save to wishlist."
- Paid full itinerary.
- Creator notes.
- What I would change.
- Best season to go.
- Who this trip is good for.
- Difficulty, pace, and planning effort.
- Optional exact addresses or hidden private details.

The marketplace path should start with high-quality public trips from influencers, expert travelers, and ordinary users with excellent trips. Users could discover, save, copy, and eventually buy complete itineraries.

This should come only after users already love creating and sharing trips privately.

Marketplace trip pages should feel more trustworthy than generic travel content because they are based on real completed trips. The best pages should combine proof, taste, and practical planning:

- The map shows the actual route.
- The timeline shows the actual order.
- Photos show the real experience.
- Notes explain what mattered.
- Paid itinerary details provide the reusable plan.

Over time, Trotter can support:

- Free public trips.
- Paid itinerary unlocks.
- Creator profiles.
- Affiliate booking links.
- Collections and guides.
- Destination marketplaces.
- Friend recommendations.
- Ratings or saves.
- "People like you took this trip" discovery.

## What The App Should Feel Like

Trotter should feel:

- Beautiful.
- Premium.
- Personal.
- Trustworthy.
- Fast.
- Accurate enough to believe.
- Editable enough to forgive.
- Emotional without being cheesy.
- Social only when the user wants it to be.

The globe is the emotional home. Passport is the identity layer. Trips are the memory layer. Dreams are the future layer.

## Recommended Build Order

The product should build in this order:

1. Make flight import reliable.
2. Make the globe and trip list feel premium.
3. Build Passport and core stats.
4. Build Year Travel Cards.
5. Build Digital Passport stamps and milestones.
6. Build Trip Detail.
7. Add manual photos and notes.
8. Add lodging from email.
9. Add calendar import.
10. Add photo location matching on device.
11. Add Google Timeline import.
12. Add Trip Mode location tracking.
13. Add always-on trip autocreation.
14. Add private sharing.
15. Add public profiles and public trip pages.
16. Add social feeds, friend graphs, and lightweight travel competition.
17. Add public photo controls for trips and destination stops.
18. Add Dreams and wishlist.
19. Add share-to-Dreams for Instagram travel inspiration.
20. Add destination-based Dream boards and review flows.
21. Add Dream-to-trip conversion and draft itineraries.
22. Explore points, planning, and fare tools.
23. Build creator itinerary marketplace.

## Near-Term Focus

The next major focus should be making the existing synced travel history feel magical.

The highest-leverage near-term features are:

1. Passport and stats.
2. Trip Detail.
3. Lodging and itinerary enrichment.
4. Photos and memories.

Those features make the current data more valuable and create the foundation for every later dream.

## The North Star

Trotter should become the place where a person's travel life lives.

At first, it remembers flights.

Then it remembers trips.

Then it remembers places, photos, meals, routes, people, and moments.

Eventually, it helps people share where they have been, dream about where they are going, and discover trips worth taking next.

At its most ambitious, Trotter becomes the place where real travel turns into reusable inspiration. Private trips become memories. Shared trips become stories. Public trips become social proof. Great itineraries become products.

The dream is simple:

> Open Trotter and see your life in motion.
