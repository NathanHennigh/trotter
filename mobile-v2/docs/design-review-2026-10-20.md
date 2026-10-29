# Trotter design and UX review · 20 October 2026

Trotter has a distinctive visual foundation, but its screens do not consistently prioritize the user's next action. Travel objects, metadata, filters, status messages, and navigation often receive similar visual weight. The biggest opportunity is to simplify the hierarchy while retaining the paper, blue ink, editorial typography, globe, postcards, and stamps.

This is a design review and proposed direction, not an implemented redesign. Source reviewed at commit `24182b8`. The working tree was clean at the start.

**Evidence and limits**

Reviewed the current Expo app shell; Globe, Trips, trip detail, Passport, country/transport collections, Profile, authentication, Dreams, country/reel collections, saved-place detail/edit, capture form, native maps, and Android share receipt. Current behavior findings below come from source. Visual judgments also use saved September screenshots. Those screenshots are historical evidence, not verification of the installed October app. In particular, the old Trips screenshot contains filters absent from current source, and the old country screenshot has a previous place-row design; neither is reported as a current defect.

No Android device was attached. Automatic approval review blocked the local Expo preview launch with only “blocked by policy,” so this review does not claim a fresh interactive walkthrough, native gesture verification, measured task completion, or a complete accessibility audit. A few files in `mobile-v2/qa-screens` turned out to be captures of an Expo manifest rather than UI; they were excluded. The useful visual evidence is in the root `artifacts` directory.

All Dreams countries use the same `CountryPlaces` component. This review examines that shared page and its different content cases; it does not claim to have opened every country in the user's account.

**Overall judgment**

The app feels most coherent when the travel artifact is the content: the globe, an actual passport page, a country postcard. It feels busiest when every functional container is also styled as an artifact. Repeated borders, inset panels, labels, small text, and multiple ways to navigate turn simple tasks into visual scanning exercises.

My proposed rule is: **one expressive object per screen; quiet controls around it.** Country postcards can carry the imagery. Country detail should prioritize the saved places. A trip can keep its wallet identity while the itinerary becomes easier to scan. A save receipt should be recognizable and brief.

Do not replace the identity with generic rounded cards, gradients, oversized checkmarks, or more ornamental stamps. Do not add a hero photograph to the country detail just to make it feel designed: that would push the places farther down.

**Prioritized findings**

P1 means address in the first redesign pass because it affects orientation, task completion, or save confidence. P2 means a meaningful usability or consistency improvement. P3 means finishing detail. “Source” denotes current implementation evidence; “visual” denotes supporting historical captures; recommendations are design judgments rather than measured user outcomes.

| Priority / surface | Before | After | Why |
| --- | --- | --- | --- |
| P1 · navigation | `changeTab` clears Passport selections; mounted Dreams retains its country and filters. [A] | Preserve each tab's stack, filters, and scroll when switching. A deliberate tap on the already active tab returns to its root. | The same tab action should have the same meaning. Source. |
| P1 · Globe → Trips | Globe passes its selected year when opening Flights, but `openTrips()` ignores the argument and opens all Trips. [A, B] | Carry the year into Trips and show a removable scope label; match the destination's unit to “Flights.” | A filtered total should lead to the records that produced it. Source. |
| P1 · cross-tab detail | Opening trips and collections can change the active tab while recording a separate return origin. [A] | Keep a detail within the originating navigation context. Reserve tab changes for an explicit destination switch. | Reduces the need to infer where Back will return. Source; perceived confusion needs device validation. |
| P1 · Dreams country | Header, two filter rows, map toolbar, 248-point map, map footer, and optional location notices precede place rows. [C] | Start with country identity, one compact control row, and places. Put the full map in a separate view. | The saved collection should be visible before its management tools. Source + visual. |
| P1 · country Map action | A row's pin scrolls the entire list back to the map at the top. [C] | Open Map with that place selected; returning restores the exact list position. | Avoids a large spatial jump and losing the item being browsed. Source. |
| P1 · place detail | Large photo, description, location panel, and another 248-point map appear before “View reel” and “Open in Maps.” [D] | Put primary actions directly below title/location; reveal the larger map on request. | The likely next actions should not require scrolling past supporting material. Source. |
| P1 · save receipt | “Reel saved” is used for locally retained, failed-upload, sign-in, and server-saved states; detail distinguishes them in small text. [E] | Use a clear headline for each meaningful outcome: “Saved to Dreams,” “Saved on this phone,” or “Sign in to finish saving.” | Local retention is valuable, but a successful cloud save must not be inferred from the headline. Source. |
| P1 · save receipt timing | Several lines and an optional action are presented with a 2.2-second automatic dismissal budget. [E] | Reduce the content; validate a longer reading interval if retaining an actionable receipt. Keep failure/sign-in persistent and accessibility/interaction protections. | Reading and choosing an action should not become a race. Source; timing target requires testing. |
| P1 · correction flow | Missing location recovery can sit behind More → Retry location or a map-level bulk action. [C, D] | Put a direct “Add location” or “Retry” next to the relevant problem; keep routine management in More. | A known problem should reveal its repair action. Source. |
| P2 · Dreams library | Only country cards and Unsorted are available at the root; search is inside a selected country. [C] | Add library-wide search across country, city, place, and source caption. Keep browse-by-country. | Users may remember a café or reel without remembering its country. Source. |
| P2 · country filters | Cities and categories are separate horizontal rows, with multiple counts. [C] | One filter control with City and Type inside; show applied values and one result count. | Cuts persistent chrome while preserving power. Source. |
| P2 · category model | The editor offers 12 types; country browsing exposes Cafés, Restaurants, Hotels, and Other. [D, F] | Use useful groups such as Eat & drink, Stay, and Things to do, with specific types inside Filters. | Beaches, museums, shops, and nature deserve a discoverable home beyond “Other.” Source. |
| P2 · count repetition | Total saved count, All count, category counts, map count, missing-pin count, and city counts can coexist. [C] | One collection total; one filtered result count when needed; one map coverage line only in Map. | Repetition creates density without improving decisions. Source. |
| P2 · country grouping | City sections repeat even when filtering to a single city; each row can repeat the city again. [C, F] | Omit the redundant group heading in a single-city result and use neighborhood/type in row metadata. | Spend the second line on differentiating information. Source. |
| P2 · country ordering | Within a country, items are sorted by city and name; there is no explicit recent-first control. [C] | Offer a small Sort menu with Recently saved and By city. Default to recent when returning to new saves. | Retrieval after sharing is a different task from planning by geography. Source. |
| P2 · empty search | “No matching places” suggests changing filters but offers no reset action. [C] | Add “Clear filters,” preserving the country and collection context. | A zero-result state should provide a one-step recovery. Source. |
| P2 · source collection | Country, Unsorted, and “From this reel” reuse the same filter/map-heavy page. [C] | Keep shared primitives but give each its own hierarchy: country collection, review inbox, source receipt. | These are three different user tasks. Source. |
| P2 · source return | Opening a reel group changes the keyed `CountryPlaces` instance; returning reconstructs country-local search and filter state. [C] | Store the source collection as a child route above the country, preserving its state underneath. | Exploring a source should not reset the user's collection context. Source. |
| P2 · Unsorted | Multiple processing categories are concatenated into the root inbox summary and expanded page notices. [C, F] | Show a concise “Needs attention · 3” or “Organizing 2 saves”; detailed reasons and actions belong on affected rows. | Separates normal background work from work the user must do. Source. |
| P2 · place imagery | The detail photo frame remains large even when only a category-symbol fallback is available. [D, F] | Use a compact illustrated placeholder for missing imagery; retain the larger image when a real source preview is available. | Missing content should not consume the space of rich content. Source. |
| P2 · image meaning | Country covers intentionally use country artwork, while individual saves use source previews or symbols. [F] | Retain this distinction; never imply that a generic destination image depicts the specific saved venue. | The current distinction is sound and should survive the redesign. Source. |
| P2 · notes | Extracted `summary` appears as description, then becomes the field labeled “Notes” in editing. [D] | Distinguish “From this post” from the user's own note; separate storage if supporting both. | Users should know which words they wrote. Source. |
| P2 · place editor | Name, city, country, region, 12 category chips, notes, comma-separated tags, Maps link, and pin placement share one form. [D] | Start with name, location, type, and personal note. Put tags and manual map repair in “More details.” | Correcting one place should not feel like completing a database record. Source. |
| P2 · manual capture | “Save a place” asks for an Instagram link plus a visible caption field before any reading failure. [C] | “Save from Instagram,” one link field, one save action; disclose caption assistance only when requested or useful. | Align the promise with what is actually saved and reduce upfront effort. Source. |
| P2 · receipt composition | Handle, uppercase “TROTTER / DREAMS,” close control, thumbnail, serif headline, check, detail, preview line, footer action. [E] | A compact horizontal receipt with a small brand mark, source thumbnail, one status, one supporting line, and optional Open. | The current component has more hierarchy levels than its content needs. Source-based visual assessment. |
| P2 · receipt states | A glyph checkmark appears after local capture even when sign-in or upload failure needs attention. [E] | Match the symbol to the headline; reserve the final success cue for the stated successful outcome. | Prevents visual success from contradicting the text. Source. |
| P2 · receipt errors | The local-storage failure path can render the exception's message directly. [E] | Use stable, actionable copy; keep diagnostic detail out of the receipt. | Unexpected technical messages damage clarity and can break the layout. Source. |
| P2 · Trips list | Wallet cards expose itinerary summaries, dates, flight counts, repeated emblem, and “Full itinerary” on every item. [G] | Keep the wallet silhouette, destination, dates, and one route summary; move deeper itinerary detail inside. | Makes a long travel history easier to scan. Source + visual. |
| P2 · trip detail | Destination, group title, airport labels, departure date, arrival date, and date stub repeat information. [G] | Present one strong route/time hierarchy. Preserve arrival-date changes; make booking information secondary. | Repetition should explain changes, not restate identical facts. Source + visual. |
| P2 · trip map | Route map and explanatory copy occupy the top of the trip document before the itinerary. [G] | Provide a compact route overview and an expandable map; surface the first flight sooner. | Balances the emotional overview with the task of reading a journey. Source + visual. |
| P2 · Passport | A large closed book follows a large “Passport” heading, with useful collections below. [H] | Retain the book as the hero, but test a smaller cover or remembered open state; make collections reachable without prolonged scrolling. | The delightful object should support repeat visits as well as first discovery. Source + visual. |
| P2 · country collections | Completion total, progress line, Visited/All tabs, region selector, and region subtotal stack before the stamps. [H] | One collection summary and one combined scope/filter control; let stamps dominate the page. | The same excessive control hierarchy appears outside Dreams. Source + visual. |
| P2 · stamp metadata | Country, airport, and date appear inside stamp art and again beneath it. [H] | Keep an accessible country label; move secondary airport/date details to selection or detail if the art already carries them. | Retains legibility without repeating every decorative field as body content. Visual; verify current card variant. |
| P2 · Profile | Traveler card, Gmail scan, globe appearance, haptics, and account controls share a top-level tab. [I] | Short term: shrink identity chrome and clarify Connections vs Preferences. Later, test moving Profile to an avatar entry. | Profile is predominantly settings; its frequency may not justify equal space with the travel tasks. Source; tab removal is a product hypothesis. |
| P2 · scan language | Home says “Import flights”; Trips sends users to Profile; Profile says “Scan for flights”; status uses both scan and update times. [B, G, I] | Use one task name and one consistent entry action wherever the task is needed. Distinguish importing mail from refreshing displayed records only when relevant. | Users should not need to understand the sync architecture. Source. |
| P2 · type hierarchy | Useful metadata and controls frequently use 10–12-point text; titles vary by context and fit calculations. [C, D, I, J] | Establish a small semantic type scale, with readable body and supporting text; allow wrapping before aggressive shrinking. | Small text is a poor substitute for choosing what to show. Source; legibility needs actual-device validation. |
| P2 · surface system | Borders, nested borders, paper shades, 3/4/8/12/18-point radii, and different button constructions coexist. [C, D, E, J] | Define separate document, control, and overlay treatments and reuse their tokens in React Native and Kotlin. | Deliberate surface roles will feel more coherent than making everything the same shape. Source. |
| P3 · country motion | Card turns out for 120ms; the country header separately rotates in for 160ms. [C, F] | Navigate immediately, then use one short transition that preserves spatial continuity. | Sequential theatrical motion adds friction without making the destination clearer. Source; native smoothness not tested. |
| P3 · interaction system | Shared press feedback exists, but native receipt buttons and some controls use different treatments. [E, J] | Standardize pressed, selected, disabled, busy, and focus states across control families. | Consistency is experienced through interaction as well as color. Source. |

**Dreams country page: proposed structure**

The page should answer three questions in order: Which collection am I in? What did I save? How can I narrow it or see its geography?

For a populated country, use this order:

1. Compact back control labeled Dreams, country title, and an Add action. Let long country names wrap to two lines. Keep one summary such as “12 places · 3 cities.”
2. A restrained Places / Map control. Places is the initial view; remember the user's view while that country remains open.
3. Search with a separate Filters button. The expanded search field should not introduce a second permanent toolbar. If there are only one or two items, search and filtering can remain in an overflow action.
4. Saved rows immediately. A row contains a source image or compact fallback, a clear place name, and one useful metadata line. Show a status only when it changes what the user can do.
5. Filters as a sheet: City, Type, and sorting. Show an applied-filter summary with Clear when active. Keep the entire set discoverable without two scrolling rails.

On an ordinary 390 × 844 layout, aim to show at least two complete saved rows before scrolling at default text size. This is a proposed acceptance target, not a measured result. At large text sizes, prioritize readable content and predictable scroll over preserving the row quota.

Keep some editorial character in the title and the photography. Remove the outer paper border from ordinary rows, or use one consistent list divider. Use a single quiet container for a true grouped unit. A border around the list row, another around its thumbnail, a boxed map, and boxed filters all compete to define what is important.

**Map should be a destination with context**

The country Map view should use the available screen area and have a compact selected-place card. A marker selection and a list selection must refer to the same item. A row's map action opens that selected marker; Back returns to the list at the same offset. A “Show all” control restores the map extent.

Display “8 of 12 places on map” once when incomplete. Provide access to the four remaining places without letting pin-management notices dominate normal browsing. Preserve the existing distinction between exact venue pins and approximate areas. A region, hiking area, or neighborhood must not be presented as a precise storefront.

If there are no usable pins, start with the places. Offer “Add locations” as a secondary action. Do not lead with an empty country map plus “No pinned places yet,” another map-empty explanation, and a lookup action. Map availability must not determine whether saved content is useful.

**Country-specific adaptation**

The component should adapt to content rather than maintaining a separate hand-designed page for each country:

| Collection case | Proposed behavior |
| --- | --- |
| One saved place | Compact country heading and the place immediately; no city rail or category-count row. |
| One city, many places | No redundant city section headings. Search, useful types, and recent sorting remain available. |
| Many cities, such as Japan or the United States | Searchable city picker inside Filters; optional By city grouping. Never require swiping through a long city rail. |
| Long country name, such as United Arab Emirates | Two-line title and predictable action placement. Test at 320 and 390 widths and enlarged text. |
| Mostly landscapes, beaches, museums, or activities | Give these recognizable types and groups; do not funnel the majority of the collection into “Other.” |
| Large or fragmented geography | Fit actual saved locations; let people select a city/region. Do not rely on national bounds to produce a useful travel-scale view. |
| No exact locations | Useful place/source list first; one clear recovery entry. Preserve approximate-area labels. |
| Many places from one reel | Show source provenance without repeating a full source card under every result; source detail lists the extracted places in source order. |
| Unidentified saves | Use a review inbox with source identity and row-level actions, not a pseudo-country with irrelevant filters. |
| No filter matches | One empty state with Clear filters; do not show a large empty map above it. |
| No thumbnail | Compact intentional fallback, never invented venue photography or a large empty image panel. |

Country and city normalization are also worth tightening before visual polish. `countryKey` contains only a small explicit alias set; country grouping uses normalized strings, while the geographic lookup has its own name/code matching. This is a source-level robustness concern, not proof of duplicate countries in the user's account. Prefer stable canonical country identifiers with display names kept separate. Similarly, make grouping and city-filter matching use the same normalization so spelling/case differences do not create repeated section headings.

**Instagram share receipt: proposed design**

Its job is to confirm retention and let the user continue watching Instagram. It should feel like a small, considered part of Trotter. The existing native-first capture and background upload architecture is appropriate; preserve it.

Use a restrained paper surface with the app's blue ink, a small Trotter emblem, a modest source thumbnail when available, and a clear text block. Keep the close target easy to hit. The large serif confirmation, tiny uppercase breadcrumb, separate source line, checkmark, handle, and footer are too many competing elements for this brief interaction.

Prefer a compact composition:

```text
Trotter                                      ×

[reel preview]  Saved to Dreams
                Courtyard cafés in Kyoto

                                      Open →
```

This is a schematic proposal, not a screenshot or an implementation. The second line should be a useful caption excerpt if supplied. If no meaningful excerpt exists, omit it or use the relevant state explanation. A generic “Instagram reel” should not occupy a standalone row just to fill a template. Do not infer a venue or country before parsing has identified it.

The design must work with no supplied thumbnail. Instagram does not need to provide one for capture to succeed. A small source glyph is enough; a large generic picture placeholder makes the receipt feel unfinished. Use the same icon construction as the app rather than relying on text glyphs for the check and close artwork.

| Actual state | Headline | Supporting copy / action |
| --- | --- | --- |
| Local persistence in progress | Saving… | Keep the surface stable; no success check yet. |
| Durably retained, upload pending | Saved on this phone | “We'll send it when connected.” Optional Open. |
| Server save acknowledged | Saved to Dreams | Useful source excerpt if available. Optional Open. Do not imply all places are already identified. |
| Account needed | Sign in to finish saving | “Your link is kept on this phone.” Sign in. Persistent. |
| Upload failed | Saved on this phone | “Couldn't send it to Dreams.” Retry or Open. Persistent. |
| Local persistence failed | Couldn't save this link | “Please share it again.” Explicit close; no success symbol. |

The current policy already pauses automatic dismissal while interacting, suppresses it for touch exploration, and keeps failed/sign-in states open. Preserve those strengths. After simplifying the layout, test the timeout with real sharing speed, larger text, and assistive technology. A starting experiment around four seconds is more defensible for an optional Open action than assuming 2.2 seconds is sufficient; it is not a validated target.

Use one entrance of roughly 150–200ms and a slightly faster exit, with system reduced-motion support. The current subtle slide/fade is already close to this direction. The primary redesign need is composition and state clarity, not additional animation.

**Navigation and information ownership**

Keep the current five tabs during the first repair pass so structural bugs can be fixed without simultaneously changing the entire app. Establish a clear contract:

| Area | Owns | Should link to selectively |
| --- | --- | --- |
| Globe | Geographic exploration and year scope | Relevant flights, a visited-country record |
| Trips | Chronological journeys and itinerary detail | Route overview and flight records |
| Passport | Travel archive, stamps, collections, activity | Relevant trips |
| Dreams | Future places, saved sources, organizing saves | Source reels and external maps |
| Profile | Identity, connections, preferences, account | Home-airport information |

Some duplication is useful: a country can be reached from a globe and a stamp collection. The mistake is losing scope or changing context unexpectedly. Every destination must say what it represents and preserve the source's filters when appropriate.

After those fixes, test a four-tab structure with Profile/settings behind a consistent avatar entry. This is a hypothesis about task frequency, not a conclusion that five tabs are inherently wrong. Do not merge Globe and Passport just to reduce the count; their experiences can remain meaningfully distinct.

**Visual system and content rules**

Retain Newsreader for editorial titles, DM Sans for controls/body, and IBM Plex Mono for genuine codes and compact technical data. Define roles rather than choosing a new size for each component: page title, section title, item title, body, supporting text, and overline. Start with 15–16 for ordinary reading text and 13–14 for supporting information, then validate on device. Keep 10–11 for nonessential decorative print only. These are proposed product targets, not a standards-conformance claim.

Use one screen gutter and a consistent spacing rhythm. A postcard frame can be nearly square; a transient overlay can have softer corners. Encode that distinction explicitly. Avoid treating every map, filter, thumbnail, card, and paragraph as a separate bordered panel. Several near-identical paper shades should have named roles or be consolidated.

Give the blue accent a consistent job. If nearly all content is blue, actionability needs additional cues such as position, label, underline, or filled treatment. A primary button, quiet action, destructive action, active tab, and status label should be distinguishable without relying on color alone.

Copy should describe the user's task and result: “Save from Instagram,” “Saved to Dreams,” “Add location,” “View post,” “Scan for flights.” Keep technical reasons and provider failures behind concise explanations. Use “post” when supporting both posts and reels, or derive the correct noun consistently; current code handles the distinction in parts of the native receipt but many other screens always say reel.

Preserve useful accessibility work already present: explicit labels on many icon controls, 44-point control targets in many components, reduced-motion handling, protection of hidden layers from accessibility focus, and retained saves during upload failures. The next pass should verify focus entry/return for modals, hardware Back at each nested level, text scaling, screen-reader announcement timing, contrast, and list alternatives to map/book gestures. Those have not been certified by this review.

**Implementation order and acceptance**

1. **Navigation and save truthfulness.** Preserve scope and tab state, clarify local/server receipt outcomes, and keep context when entering a source collection. Verify the selected-year Flights route, tab round trips, country → place → reel → Back, and every receipt outcome.
2. **Dreams country redesign.** Introduce Places/Map, compact controls, useful category grouping, direct correction actions, and stable list return. Check all collection cases above, including large text and absent imagery.
3. **Receipt and saved-place detail.** Implement the quieter native receipt and move detail actions up. Validate with a real Android share from Instagram, offline capture, account-required state, upload failure, large text, and rapid successive shares.
4. **Whole-app density pass.** Reduce trip and stamp repetition; simplify Passport collection controls and Profile hierarchy. Preserve meaningful date changes and useful accessible labels.
5. **Shared visual tokens and interaction finishing.** Consolidate type, surface, spacing, icon, press, and overlay patterns. Verify on actual device before adjusting small shadow or animation values.

Suggested usability checks: find a recently saved place without knowing its country; find every café in one city; move between a selected map pin and its list position; recover an unidentified reel; open the same year-scoped flights represented by the Globe; leave and return to a collection without losing context. Success means a clear path and preserved context, not merely a prettier screenshot.

**Source and visual evidence index**

- [A — app navigation](C:/Users/natha/projects/trotter/mobile-v2/App.tsx:293): tab switching, drill-down origins, year-dropping Trips handler, and retained layers.
- [B — Globe](C:/Users/natha/projects/trotter/mobile-v2/src/screens/HomeGlobeScreen.tsx:200): import entry, selected flight/country panels, and scoped statistics navigation.
- [C — Dreams and country page](C:/Users/natha/projects/trotter/mobile-v2/src/screens/DreamsScreen.tsx:306): country hierarchy, state, map placement, filters, rows, source collections, and capture form.
- [D — saved-place detail/editor](C:/Users/natha/projects/trotter/mobile-v2/src/components/world-window/dreams/DreamEditor.tsx:267): content order, primary actions, editing fields, and recovery menu.
- [E — Android share receipt](C:/Users/natha/projects/trotter/mobile-v2/android/app/src/main/java/com/trotter/mobilev2/DreamShareActivity.kt:152) and [dismissal policy](C:/Users/natha/projects/trotter/mobile-v2/android/app/src/main/java/com/trotter/mobilev2/DreamShareReceiptPolicy.kt:5).
- [F — country/filter model](C:/Users/natha/projects/trotter/mobile-v2/src/components/world-window/dreams/dreamPresentation.ts:47), [processing language](C:/Users/natha/projects/trotter/mobile-v2/src/components/world-window/dreams/dreamProcessing.ts:10), [postcard](C:/Users/natha/projects/trotter/mobile-v2/src/components/world-window/dreams/CountryPostcard.tsx:93), and [image fallback](C:/Users/natha/projects/trotter/mobile-v2/src/components/world-window/dreams/DreamPhoto.tsx:48).
- [G — Trips list](C:/Users/natha/projects/trotter/mobile-v2/src/screens/TripsListScreen.tsx:70), [wallet](C:/Users/natha/projects/trotter/mobile-v2/src/components/world-window/trips/WalletCover.tsx:69), [trip detail](C:/Users/natha/projects/trotter/mobile-v2/src/screens/TripDetailScreen.tsx:143), and [boarding pass](C:/Users/natha/projects/trotter/mobile-v2/src/components/world-window/trips/BoardingPass.tsx:147).
- [H — Passport](C:/Users/natha/projects/trotter/mobile-v2/src/screens/PassportStatsScreen.tsx:173), [collections](C:/Users/natha/projects/trotter/mobile-v2/src/components/world-window/passport/PassportCollections.tsx:197), and [country navigation](C:/Users/natha/projects/trotter/mobile-v2/src/screens/CountryStampCollectionScreen.tsx:110).
- [I — Profile](C:/Users/natha/projects/trotter/mobile-v2/src/screens/ProfileScreen.tsx:31).
- [J — shared components](C:/Users/natha/projects/trotter/mobile-v2/src/components/world-window/WorldWindowUI.tsx:145), [bottom navigation](C:/Users/natha/projects/trotter/mobile-v2/src/components/trotter/TrotterKit.tsx:979), [theme](C:/Users/natha/projects/trotter/mobile-v2/src/theme/trotterTheme.ts:1), and [text fitting](C:/Users/natha/projects/trotter/mobile-v2/src/components/world-window/displayTextFit.ts:11).
- Historical country layout projection: [Portugal, mixed locations](C:/Users/natha/projects/trotter/artifacts/dreams-experience-20260914/location-country-mixed-420-font1-top.png). Map is explicitly a placeholder; old rows differ from current code.
- Historical native captures: [Globe](C:/Users/natha/projects/trotter/artifacts/final-ui-refinement-20260915/globe-retained-final.png), [Profile](C:/Users/natha/projects/trotter/artifacts/final-ui-refinement-20260915/profile-final.png), [trip detail](C:/Users/natha/projects/trotter/artifacts/final-ui-refinement-20260915/ticket-open.png), [countries](C:/Users/natha/projects/trotter/artifacts/final-ui-refinement-20260915/countries-final.png), [Passport](C:/Users/natha/projects/trotter/artifacts/deep-qa-20260914/android-passport-closed.png), and [Trips](C:/Users/natha/projects/trotter/artifacts/deep-qa-20260914/android-trips-top.png). Old Trips filters are not current findings.
