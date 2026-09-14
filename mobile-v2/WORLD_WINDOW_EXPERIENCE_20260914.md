# World Window experience refinement — 14 September 2026

Rollback checkpoint: `1f385f6a1ec393304e3fd2020379388501c0521e` on `codex/world-window-mobile`.

This implements the accepted experience review in `output/world-window-experience-review-2026-09-14.md`. The existing blue, cream and copper palette, natural country photos, flight data, Google connector, Google Maps integration and passport mechanics remain the foundation.

## Navigation and recovery

- Home flight/country/airport totals carry their selected departure year into the destination list. Lists expose All years; opening an itinerary still shows the original complete trip. Lifetime first-entry stamps and travel start dates remain separate from annual metrics.
- Repeated globe arcs offer individual dates, airport directions and flight numbers, including outbound and return flights on one arc. Selecting a flight opens that exact flight in its original trip. Tap-away still clears selection; Android Back collapses the chooser, dismisses the selected paper, then falls through from the bare Home screen.
- Wallet headers, coupons and footers consistently open the overview. Airport, country and airline journey rows consistently open itineraries. Trip Back stays outside the scrolling flight list; empty and failed details have a working retry.
- Collection detail opens above a retained index, preserving its search and scroll state. Country detail includes journeys directly. Visible return labels explain whether Back returns to Globe, Passport or Profile. Profile's airport heading opens that airport's history directly.
- OAuth retry repeats Google sign-in if no token was received, or account verification if one exists. Gmail scan recovery stores only API/owner-scoped job metadata and last-success time. Restart resumes observing an existing job; it does not start a second import. Transient failures retain the job; terminal outcomes clear it. Account boundaries remain enforced.
- Dreams Edit opens the form directly. Unsaved edit and capture drafts survive tab switches and failed saves; explicit Close/Back offers Keep editing or Discard when needed. Location review distinguishes Confirm pin from Save place details and reports the completed action.

## Presentation and motion

- Home paper enters/exits with the route focus. Selected paper replaces the totals while open, and the totals return on dismissal. Constrained scrolling and measured type sizing keep the chooser, airport codes and controls usable with large text.
- Wallet/ticket navigation carries a noninteractive paper copy from its measured origin to the itinerary, with a reverse on Back. A scoped wallet retains its exact preview in the transition. The real itinerary/map is never scaled. Canceled or superseded transitions cannot complete a late navigation.
- Postcards turn directly into their country collection and reverse into the same postcard on Back. Country heading and paper continuity replace the abrupt screen swap. No backside browsing or shadow rectangle is added.
- Shared press feedback preserves disabled styling and layout, responds quickly and releases smoothly. Reduced-motion settings remove travel/turn motion. Optional tactile feedback is limited to completed page turns, changed chart years and confirmations.
- Classic/NASA preference and the haptic setting survive restarts. The texture switch briefly names the selected mode without adding permanent Home copy.
- Tickets make local calendar dates, overnight/date-line arrivals and connections clearer. All flights stay expanded. Large-text layouts stack airport blocks, count summaries and footer totals when needed.
- Passport identity pages use aligned document fields and rules. The final page is a travel register; interactive activity remains below the book. Stamps retain chronological order and safe, varied placements. Newly earned countries can settle once after an import; existing stamps are not celebrated on initial archive loading.
- Passport gestures wait for horizontal intent before capturing/locking parent scrolling. Archive texture updates wait until a held page settles. The activity chart stores the actual selected year and distinguishes horizontal scrubbing from vertical scrolling.
- Dreams has one compact country heading, focused search beneath it, persistent city/category filters, a stable map height and a selected-place preview with direct Details. Country photography and reel-cover fallback keep one crop/paper treatment.
- Country, airport and airline collections keep their distinct arrival/IATA/small-logo hierarchy. Profile route maps limit labels by importance while retaining every route and airport marker. Shared paper shades and divider colors preserve each object's material without introducing a new palette.

## Verification

The aggregate check is `npm run test:world-window`, including the new Trips, Dreams, preference and motion regressions. `npm run typecheck` checks the complete app. Checks exercise account isolation, scan recovery, original-trip preservation, year scope, reverse routes, nested Back, dirty drafts, exact pin confirmation, canceled motion, preference hydration races, map label placement and generated passport consistency.

Offline visual proof directories under the repository's `artifacts/`:

- `world-window-fidelity`: 241 stamp collection sizes; actual bundled passport runtime at 320/410dp; 98 motion samples including real browser touch intent/cancellation, held-cover updates and one-time stamp settling; collection layouts.
- `dreams-experience-20260914`: 32 production-component layout cases at 320/420dp and 1x/2x text, plus sampled transition frames.
- `home-experience-20260914`: Home selection/chooser/country and dense Profile layouts at 320/420dp and 1x/2x text; explicit checks for sibling overlap.
- `trips-experience-20260914`: compact/scoped wallets, a long itinerary, persistent Back and transition frames at small/large text sizes.

These use synthetic fixtures and bundled assets. No live flight records were edited and no real Dream location was confirmed during QA. There are no backend/schema changes to deploy.

## Android verification boundary

Use the existing WSL pipeline to build the committed source:

```powershell
./scripts/Build-Android-Artifacts.ps1 -Mode apk -Development -ApiBaseUrl https://trotter-api.thehennighs.com
```

The phone was unavailable through ADB during this pass. Browser/source proofs establish layout, logic and WebView-runtime behavior, but do not establish physical Android frame rate, Google Maps native compositing, keyboard behavior, TalkBack ordering or parent-scroll arbitration. Those checks require the installed APK on the connected phone. An update install must preserve app data (`adb install -r`); no uninstall/reset is needed.
