# iPhone simulator review — October 29, 2026

## Scope and result

Tested the Release app on the dedicated iPhone 17 Pro simulator (iOS 26.5), using the owner's usual Google account. The main navigation, populated Dreams, Google Maps, trip wallets, Passport, profile and Planner workflows were exercised. One native iOS compatibility error was fixed. This is a simulator review, not approval of every physical-iPhone integration or animation.

Source fix: `8da6eee8eb79d26a26bbcf223335fcf8e4ba5f8e`.

| Before | After | Why |
| --- | --- | --- |
| The globe exposed a fractional maximum in its native accessibility range. iOS logged a Fabric conversion error for `4.8`. | The numeric range uses integer percentages (100–480), while VoiceOver still receives “1.0 times zoom” through “4.8 times zoom.” | Prevents the native conversion error without changing gestures, zoom limits, appearance or spoken units. |
| The simulator kept displaying its first globe frame, before the flight paths had loaded. JavaScript queued drawing faster than Apple's software renderer could finish it. | On Apple Software Renderer only, the next frame waits asynchronously for the native drawing queue. Flight paths, country shading, rotation and year filters now update in the normal Release app. | Bounds queued work without blocking the interface or reducing image quality. Physical-device GPUs retain the existing rendering path. |

## Exercised successfully

- Google login, logout, account switching and session persistence across app reinstalls and simulator restarts.
- Populated Dreams postcards, country opening, Morocco's saved-place list and Google map, clusters and markers. Serenya displayed its resolved Marrakech address and the normal Open in Maps action. The external action launched Google Maps in Safari; destination rendering there was not separately asserted.
- Stable profile-avatar placement across top-level screens, standard tab navigation, Trips list and wallet details, Passport opening and profile route-map rendering at both world-map edges.
- A private, temporary seven-day Morocco trip: dates, all three transport choices selected together, importing saved ideas, generation, accepting the draft, day shortcuts and continuous scrolling.
- Custom “slow morning” entry, moving it to a different day, saved-hotel selection, and votes changing from +1 to −1 and back to neutral. No booking was made.
- Invite settings opened with the available roles. No invitation was created or sent, and another person's acceptance was not tested.
- Sharing an existing Instagram post from Safari into the actual Trotter iOS extension showed “Saved to Dreams.” Returning to Trotter preserved the country's 25-place count. The existing post was reprocessed; this was not a test of the native Instagram app.
- The temporary trip was deleted and the original trip remained. Classic globe preference was restored. The final simulator installation contains the normal app, not the temporary graphics diagnostics.

## Findings and limits

1. **Globe paths are now verified; animation still needs a physical iPhone check.** A follow-up fixed the simulator's severe graphics backlog with an asynchronous native frame barrier. In the fresh Release build, the owner's routes appeared, filtering to 2026 reduced the globe from 163 flights to 16, returning to All years restored the routes, rotation worked, and both Classic and NASA imagery updated. Leaving for Dreams and returning preserved rendering. The software renderer still takes roughly a second per full-resolution frame, so this is not evidence of smooth physical-device animation. The fix is gated to the exact Apple Software Renderer string. Experimental synchronous barriers and reduced-resolution rendering were discarded. Apple's [simulator testing documentation](https://developer.apple.com/library/archive/documentation/IDEs/Conceptual/iOS_Simulator_Guide/TestingontheiOSSimulator/TestingontheiOSSimulator.html) explicitly separates simulator OpenGL performance from device performance.
2. **Software keyboard avoidance remains unverified.** Text fields accepted input and saved changes, but this headless simulator did not display its software keyboard. The dedicated simulator's hardware-keyboard setting and a reboot did not resolve that limitation.
3. **The share receipt needs a compact presentation pass.** Capture succeeded and the typography matched Trotter, but Safari presented the receipt in a near-full-height sheet with excessive empty space despite its preferred content size. No unverified sheet-height workaround was included in this release.
4. Native Instagram sharing when closed/offline/signed out, physical-device haptics and graphics, and invitation acceptance by a second account still need device/integration checks. Apple sign-in remains disabled pending its real-device checks.

## Validation and evidence

- 24 globe interaction/loading regression tests passed, including integer native range values after accessibility actions.
- Mac TypeScript check, iPhone logic suite, generated native project checks and release configuration passed. Expo Doctor passed all 17 checks.
- A fresh Release simulator build installed and launched, and the original native conversion error was absent after the fix.
- Simulator source snapshot: `4154c850ad5f334b246b247415aa786c81b9976700d5fc14ad47e3b72e29cfae`.
- Simulator artifact SHA256: `4dd122be4a171d09f413e68c117f20c01d231035f857dd4e3e4be2d96013baa1`.
- Private screenshots, diagnostic logs and process samples are retained locally under `.ios-remote/artifacts/simulator-review-20261029/`, outside Git. Useful frames: `05-dreams-populated.png`, `07-morocco-map.png`, `13-itinerary-day5.png`, `16-trip-detail.png`, `19-passport-open.png`, `21-profile.png`, `26-trotter-share.png`, `27-clean-planner.png`.

### Flight-path follow-up

- 49 globe-loading, interaction, geometry and native-patch checks passed. They cover a single pending software frame, rapid tab/background returns, stale completion after unmount, recovery from a rejected native frame, and the unchanged hardware-renderer path. The native patch rejects incompatible Expo GL versions and changed upstream implementations; its two checks also run in `test:iphone`.
- Six iOS configuration checks and the Mac TypeScript check passed. A fresh native Release build compiled and was installed over the existing account session.
- Simulator source snapshot: `cceb83d14b9b3ab00975f9c76ab21e5f7f958f39f8dec153786d6c5dc97c402d`. Artifact SHA256: `74379c643e8e38f80f527d8739a68d4769c5ec6b3fc5ed838b1aecfd115bc464`.
- Evidence: `31-frame-barrier.png` (all routes), `32-flight-year.png` (2026), `33-globe-rotated.png`, `35-nasa-loaded.png`. Classic and All years were restored afterward. No diagnostic renderer is installed.
- This simulator-specific follow-up is not included in TestFlight build 4 below; it will be included in the next native build. No additional upload was necessary to verify this preview fix.

## Distribution build

Version **0.1.2 (4)** compiled and passed the exact-IPA checks for both targets, signing, production configuration and the location-purpose string. IPA SHA256: `1639c13af7fc3eaa09dc0209e01fafa966dd7f85b0c55413c478d8c8b9f720b5`.

Apple validation and upload succeeded with no errors. Delivery: `6dbdac36-b319-4118-944a-04327b1d5413`. Apple processing completed with `VALID`, `READY_FOR_BETA_TESTING` for internal testing and `READY_FOR_BETA_SUBMISSION` for external testing. The delivery record reported no errors or warnings. Evidence and the verified IPA are retained under `.ios-remote/artifacts/iphone-beta-build4-20261029/`. No friends have been invited and no public App Store release has been submitted.
