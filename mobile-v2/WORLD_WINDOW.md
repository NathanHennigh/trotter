# World Window native app

The approved World Window direction now runs in the Expo/React Native app in this directory. The comparison Site remains a separate design reference.

## What is connected

- The existing Oracle API and Google/Gmail OAuth flow. Signed-out accounts start empty; tokens are stored in native SecureStore and validated through `/auth/me`. Signing out clears this device's account state and cancels stale responses.
- A native Three/Expo GL globe using live flight legs, NASA and classic surfaces, visited countries, daylight, route focus, slow rotation and pinch zoom. Zoom uses bounded local detail tiles: 12288px-equivalent country masks and the existing 21600px NASA imagery. The home toolbar has only year and texture controls. Flight tickets navigate to their actual trip and selected leg.
- Compact trip wallets and complete boarding-pass details, including all recorded legs, airline logos, local flight times, and a map inside each trip.
- A closed rigid passport cover and a bundled physical page-fold renderer. Country details sit above the same book; stamps use the app's calibrated geometry and first-entry airport codes. Activity is an inline line chart; the three collections sit in one row.
- Country postcards in Dreams, with maps, clustered saved places, category/city filters and authenticated thumbnails. Sixteen bundled country covers are reused across all accounts; unsupported countries and failed artwork fall back to a saved reel cover. Individual saved places keep their own photographs. Instagram capture, review, edit, delete and manual pins use the existing account endpoints.
- A new Profile focused on identity, account connection, import/refresh and sign-out.

## Development and builds

Copy `.env.example` to `.env.local` for the current deployed API, or supply `EXPO_PUBLIC_TROTTER_API_URL` to the build process. Never supply a build-time bearer token. The production URL is `https://trotter-api.thehennighs.com`.

The native client needs rebuilding because this migration adds SecureStore, WebBrowser, Crypto and WebView. It cannot be validated by opening an old development client. The checked-in Android project preserves the Instagram share intent and excludes SecureStore from Android backup.

Use the repository's WSL build system from the repository root:

```powershell
./scripts/Build-Android-Artifacts.ps1 -Mode apk -Development -ApiBaseUrl https://trotter-api.thehennighs.com
```

This syncs the current mobile source into Ubuntu, installs its locked dependencies, runs TypeScript and Expo checks, and performs a clean standalone Android build. `-Development` includes the current uncommitted changes; the resulting APK still runs without Metro. The pipeline saves a timestamped APK and `trotter-latest.apk` in `C:/Users/natha/Documents/builds`.

The WSL APK includes ARM32, ARM64, x86 and x86_64. The project uses its existing signing configuration. The earlier direct Windows ARM64 APK is retained as a separate artifact. iOS source support is included, but an iOS binary requires a macOS/Xcode or EAS build.

Run the app regression checks from `mobile-v2` with `npm run test:world-window`. Play-release builds use the pipeline's separate clean-main, signing, and version-code requirements.

## API compatibility

No trip/parser/database migration is part of this UI replacement. The existing deployment supports sign-in, trip reads, Gmail import, and Dreams mutations. The accompanying Dreams API change only exposes already cached location coordinates and invalidates stale location matches when a place is edited; it needs a backend deployment to take effect. It adds no geocoding calls or database schema changes. Older responses still work: exact map URLs and manual pins can be plotted, while missing locations remain explicitly unpinned and visible in the list.

## Validation and remaining device checks

The automated suite covers account isolation, OAuth callbacks, sign-out races, incoming-share ownership, flight preservation, Dreams mutations, geographic masks, passport turns/bounds, stamp calibration, and synthetic API contracts. The fidelity refinement also checks itinerary coupon grouping, map geometry, collection navigation, long identity names, and organic stamp layouts.

The approved deployed Site was captured and its computed colors, typography, dimensions and component structure compared against the native implementation. Offline renders at 320px and 410px exercise the actual wallet, boarding-pass, postcard, profile and auth components, plus the bundled passport renderer. The globe's actual shader/camera/route code was rendered in Chromium WebGL2 using the bundled NASA textures in both classic and NASA modes, in daylight and at night. Evidence and the Android build record are in `artifacts/world-window-fidelity` at the repository root.

A real Google sign-in and an on-device visual/gesture pass remain necessary. No physical Android device or configured emulator was available in this environment. Offline browser renders verify layout and shader behavior, not Android font rasterization, Expo texture decoding or physical touch response. Automatic approval review blocked starting the local Expo preview server with the reason “blocked by policy”; validation used isolated offline documents and synthetic data without a server, authentication bypass or production requests. The QA mock is not included in the app.

## Assets

The R07 emblem, fonts, passport fold geometry, country artwork and geographic data are bundled locally. Rebuild the generated passport runtime with `node scripts/buildPassportRuntime.js`; `--check` verifies that the bundled copy is current. The country mask can be rebuilt from the checked-in GeoJSON with `node scripts/buildWorldWindowGlobe.cjs`. Launcher assets derive from the same approved vector via `node scripts/renderWorldWindowBrand.cjs`.

Country postcards use 16 curated real travel photographs, chosen for natural light and restrained colors. Photographer credits, individual source pages, license links and hashes are in `assets/world-window/dreams/countries/photo-sources.json`; downloaded masters are preserved under `output/country-photographs` at the repository root. `node scripts/buildCountryPhotographs.cjs` encodes proportional 1600px WebP copies without added filters. The rejected generated set is archived under `output/country-postcards` and is not used by the app. Add a verified country photo and a static entry in `countryArtwork.ts` to expand coverage. Run `node scripts/testDreamCountryArtwork.cjs --assets` to verify the catalog, fallback behavior and account isolation.

Font notices are beside the bundled fonts and in Android's `assets/licenses`. Newsreader, DM Sans and IBM Plex Mono use the SIL Open Font License. The preserved page-fold license is under `src/components/world-window/passport/page-fold`; geographic provenance is in `src/data/worldCountries-source.json`. Leaflet's license is preserved with its bundled source. Trip and airport route maps use bundled vector geography; Dreams place maps fetch OpenStreetMap tiles with attribution. The globe and passport do not require a hosted renderer.
