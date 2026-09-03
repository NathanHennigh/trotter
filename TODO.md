# Trotter TODO

Current priorities after the flight parser and Gmail discovery reliability checkpoint.

## Next

- [ ] Build a production-ready new-user flow:
  - signed-out and onboarding screens instead of snapshot data
  - visible Google sign-in, reauthorization, and sign-out controls
  - [x] environment-based API configuration without a hardcoded ngrok fallback
  - initial Gmail scan progress with phases, counters, network retry state, and completion messaging
  - polling that follows the import job to a terminal state instead of timing out after six minutes

- [ ] Add an in-app flight review queue:
  - review plausible flight emails that could not be resolved automatically
  - classify flight, check-in, changed itinerary, cancellation, duplicate, reminder, or non-flight
  - correct route, date, time, airline, flight number, passenger, PNR, and trip assignment
  - persist review decisions and use them to avoid repeat prompts and improve future imports

- [ ] Replace remaining user-specific and snapshot profile data:
  - persist traveler name, aliases, and preferred home airport or airports
  - infer or ask for home airports instead of hardcoding IAH, HOU, DFW, and DAL
  - calculate first flight and all Passport identity fields from live account data
  - remove production fallback to Nathan's travel snapshot

- [ ] Add trip correction tools:
  - rename trips
  - merge and split trips
  - mark airports as destinations or layovers
  - correct, hide, restore, or reassign flight segments
  - display source email, parser evidence, confidence, aliases, and update history

## Product Completion

- [ ] Persist trip favorites.
- [ ] Implement trip search and add-trip controls.
- [ ] Finish Trip Detail stays, places, and evidence sections.
- [ ] Stop merging mock Dreams into authenticated production data.
- [ ] Decide the final Profile/Countries navigation structure.
- [ ] Make currently decorative Passport and globe controls functional or remove them.

## Quality And Release

- [ ] Add mobile unit tests for live trip mapping, Passport statistics, auth state, and sync polling.
- [ ] Add an end-to-end test covering sign-in, Gmail import, globe, Trips, and Passport.
- [ ] Add a fresh-database migration and import smoke test.
- [ ] Keep the private parser corpus, database backups, dumps, and local binaries out of Git.
- [ ] Update or archive outdated implementation documents so they do not conflict with the current roadmap.
- [ ] Separate or retire the legacy `mobile` app after `mobile-v2` becomes the canonical client.

## Later

- [ ] Continue trip enrichment with stays, places, photos, memories, and evidence-backed destination details.
- [ ] Expand Dreams into planning and conversion workflows after the core travel history experience is complete.
