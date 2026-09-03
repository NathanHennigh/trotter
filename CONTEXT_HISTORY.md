# Trotter Context History

Last updated: 2026-08-27

## Purpose

This file preserves the useful product, development, setup, troubleshooting, and design context from the Trotter project conversations. It is intended to make moving development to another computer or starting a new coding session less dependent on chat history.

Do not put secret values in this file. Local environment files must be transferred separately and securely.

## Repository Status At Handoff

- Repository root: `C:\Users\natha\projects\trotter`
- Git remote: `https://github.com/NathanHennigh/trotter.git`
- Active branch: `main`
- Current commit: `b385055931976f86c03e42a920e8789982e93cb7`
- Commit summary: `Improve Android dev setup and Dreams sharing`
- `main` is synchronized with `origin/main` after a fresh fetch on 2026-08-14.
- There are no modified or staged tracked files.
- There are 142 local design files totaling about 401.48 MB that were intentionally excluded from migration.
- The user decided not to migrate the old `mobile/` tree, `trotter-photo-curation/`, or the generated `design-directions/` archive.

## Product Summary

Trotter is a private-by-default travel history app. It imports flight information from Gmail, normalizes flights and trips, and presents the user's travel history through a globe, trip timeline, passport-style records, collections, saved dream destinations, and profile data.

The original Phase 0 goal was an Android-first vertical slice:

1. Sign in with Google.
2. Grant read-only Gmail access.
3. Import flight emails in a resumable background job.
4. Parse flight reservations into structured segments and trips.
5. Store structured data without retaining raw email bodies.
6. Display real routes and trip details in the mobile app.

## Current Technical Shape

### Active mobile app

The active client is `mobile-v2/`, not the older `mobile/` directory.

- React Native with TypeScript and Expo native development builds.
- Android is the primary local target.
- `expo-gl`, `three`, and related native code power the globe.
- The project requires a native development client; Expo Go alone is not sufficient for all native dependencies.
- Metro uses port `8083` by default to avoid collisions with other Expo projects.
- Important screens include Globe, Trips, Passport identity, Passport records, Passport collections, Dreams, and Profile.
- Shared visual components currently live under `mobile-v2/src/components/trotter/`.
- Screen implementations live under `mobile-v2/src/screens/`.

### Backend and local services

- FastAPI backend under `backend/`.
- PostgreSQL with PostGIS.
- Redis and Celery for background import work.
- Docker Compose provides local services.
- Gmail import is designed to be resumable and privacy-conscious.
- Parsed travel data is persisted; raw email bodies should not be stored at rest.

### Main development entry point

From the repository root:

```powershell
.\scripts\dev.ps1
```

To build and install the native Android client:

```powershell
.\scripts\dev.ps1 -InstallAndroid
```

The setup script targets `mobile-v2/`, starts the backend and Expo environment, and discovers common Windows locations for Docker, Android SDK tools, and Android Studio's JDK.

To create a standalone Android APK through the local WSL toolchain without installing it:

```powershell
.\scripts\Build-Android-Artifacts.ps1 -Mode apk
```

The artifact workflow verifies a clean synchronized `main`, copies `mobile-v2` into WSL's Linux filesystem, installs locked dependencies, runs Expo and TypeScript checks, builds with Gradle, validates the artifact, and publishes timestamped and `latest` files under the current Windows user's `Documents\builds` folder. Play AAB builds additionally require an ignored upload keystore, `android/signing.properties`, and an explicit version code.

## Development And Android Troubleshooting History

### Git checks and updates

The project has repeatedly been pulled, checked, and pushed through the GitHub remote. Earlier conversation requests included pulling new files, checking whether the branch was current, and pushing local changes. At this handoff, tracked code is current with `origin/main`.

### Docker prerequisite failure

An early `dev.ps1` run failed with:

```text
Docker CLI was not found. Open Docker Desktop and try again.
```

The script now checks common Docker Desktop locations, but Docker Desktop still needs to be installed, opened, and running before the backend services can start.

### Android device selection failure

An Android build initially targeted device serial `000463575000745`, but Expo reported that it could not find a device with that name. On a new laptop:

1. Enable Developer Options and USB debugging on the phone.
2. Connect it by USB.
3. Accept the computer authorization prompt on the phone.
4. Run `adb devices` and confirm the state is `device`, not `unauthorized` or `offline`.
5. Run `.\scripts\dev.ps1 -InstallAndroid`.

The serial is device-specific and should not be assumed to remain the same across computers or connection modes.

### Native install and QR-code crash

The Android APK built, but one install attempt failed through `adb install`. Separately, opening an app and scanning the QR code caused a crash. The important distinction is:

- This project uses an Expo native development client because it has native dependencies.
- First install the generated native debug APK with `-InstallAndroid`.
- After installation, use the QR code from the window titled `Trotter Expo Dev Client :8083`.
- Do not assume that scanning the project in Expo Go will work.
- Rebuild the native client when native dependencies or native configuration change.
- For ordinary JavaScript or TypeScript changes after a successful native install, the normal development script is usually enough.

The exact cause of the previous `adb install` failure was not visible in the shortened error output. If it recurs, run the underlying `adb install` command directly or inspect Logcat so the device's specific failure reason is visible.

## Design History

### Starting design

The implemented app used a passport-ledger aesthetic:

- Warm cream paper backgrounds.
- Black, gold, and clay-red accents.
- Large uppercase headings.
- Passport stamps and ticket motifs.
- A dark five-item bottom navigation bar.
- Rounded stat and content cards.
- A dark globe with illuminated routes.

The user felt the aesthetic was either wrong or insufficiently refined and requested broad design exploration.

### Exploration sequence

1. Several initial concept sets were generated, including a polished version of the existing direction.
2. Those concepts were rejected as not compelling enough.
3. More unusual, graphic-heavy concepts were explored.
4. The user liked their energy but correctly noted that custom art for every flight would not be practical in production.
5. The direction shifted toward systems that can be built with ordinary photos, maps, typography, SVG paths, gradients, and reusable components.
6. Six real app screenshots were supplied as content references: Globe, Trips, Passport identity, Passport records, Passport collections, and Dream detail.
7. Theme-based recreations were generated, but the first comparison used inconsistent or distorted screenshot proportions.
8. All screens were regenerated or normalized to a standard phone canvas.
9. The user then noted that themes still reused the same layout and object shapes.
10. The latest pass rebuilt the information architecture, navigation pattern, density, geometry, and content-reveal model for each theme rather than merely reskinning cards.

### Production design constraints learned from feedback

- Concepts must be implementable in the real React Native app.
- Avoid dependence on custom illustrations for every flight or destination.
- Photos must be optional; map crops, route codes, typography, and color fields should provide fallbacks.
- A theme should change hierarchy and interaction patterns, not just colors, fonts, and corner radii.
- Do not force every screen into the same card grid.
- Screen geometry may vary across features when the content warrants it.
- Individual screenshots must use a normal phone aspect ratio.
- Latest screen outputs are exactly `1080 x 2400` and were proportionally cropped, not stretched.

## Latest Design Systems

The most recent exploration contains eight themes with six screens each, for 48 individual screens total.

Root folder:

`mobile-v2/docs/design-directions/2026-08-structural-layout-variation/`

Each theme folder includes the six phone screenshots and a `contact-sheet.png`. Contact sheets are `1800 x 2700`.

### 1. Map Room

- Edge-to-edge maps and atlas sheets.
- Legend rails, compass controls, waypoints, and map-led hierarchy.
- Trips combine a numbered route index, map backdrop, and docked atlas sheet.
- Records and collections use map overlays, ledgers, and geographic diagrams rather than card grids.

### 2. Travel Library

- Folios, ledgers, shelves, spines, index strips, and archival tables.
- Trips become an open-book feature plus catalog.
- Passport identity becomes an open folio.
- Collections are represented as shelves and volumes.
- Dreams read like library entries with marginal controls.

### 3. Night And Day

- Dark map or photo environments paired with bright bottom sheets.
- Information is progressively revealed by sheets rather than isolated cards.
- Map-heavy upper regions preserve atmosphere while lower sheets handle dense data and actions.

### 4. Native Calm

- Conventional, restrained Android structure.
- Flat app bars, rows, tabs, lists, dividers, and standard navigation.
- Minimal decorative treatment and almost no card containers.
- Intended as the lowest-risk production direction.

### 5. Soft Topographic

- Contour lines, organic SVG boundaries, survey markers, and terrain-like charts.
- Trips use an alternating route timeline.
- Passport identity follows a path through pebble-shaped information nodes.
- Collections form an unequal topographic tessellation.

### 6. Photo-Optional Editorial

- Magazine spreads, oversized typography, ruled lists, sharp color fields, and asymmetric columns.
- Trips use one feature story followed by a compact index.
- Passport identity is a profile cover rather than a central card.
- Records are a data poster.
- The system still works without photography by substituting maps, route codes, or flat fields.

### 7. Monochrome Atlas

- Dense technical instrument styling.
- Sharp rectangles, telemetry rails, manifest tables, coordinate systems, and a safety-orange accent.
- Trips are a flight manifest.
- Passport is an ID console.
- Dreams are structured dossiers.

### 8. Living Route

- A continuous route line and stations organize each screen.
- Trips alternate content around a vertical itinerary path.
- Passport metrics become stops on a personal route.
- Records merge a transit diagram with a year chart.
- Collections branch into unequal destination nodes.

No final theme has been selected, and these concepts have not yet been implemented in the app code.

## Uncommitted And Local-Only Material

### Untracked design archive

These files exist locally but are not in GitHub:

| Folder | Files | Approximate size |
| --- | ---: | ---: |
| `mobile-v2/docs/design-directions/2026-07/` | 16 | 28.23 MB |
| `mobile-v2/docs/design-directions/2026-08-faithful-restyles/` | 4 | 5.80 MB |
| `mobile-v2/docs/design-directions/2026-08-standard-phone-screens/` | 57 | 159.06 MB |
| `mobile-v2/docs/design-directions/2026-08-structural-layout-variation/` | 57 | 195.02 MB |
| `mobile-v2/docs/design-directions/2026-08-theme-system-comparison/` | 8 | 13.38 MB |

The latest archive is `2026-08-structural-layout-variation/`. These generated design files were intentionally left out of Git and will not be migrated to the new laptop; the design decisions they informed remain summarized in this document.

### Local secrets and machine configuration

- `backend/.env` is ignored and contains the local backend configuration. Transfer it securely or recreate it from `backend/.env.example`.
- `mobile-v2/android/local.properties` points to the local Android SDK and should normally be regenerated on the new laptop.
- Never commit real secret values merely to move them between computers.

### Ignored photo-curation tool

The entire `trotter-photo-curation/` directory is ignored by the parent repository and will not exist after cloning from GitHub.

- Total local size is about 4.70 GB.
- About 4.66 GB is under `trotter-photo-curation/assets/`.
- The source, scripts, package files, README, and environment template are small, but they are also ignored.
- The user decided this tool and its assets are no longer needed and will not migrate them.

### Older `mobile/` directory warning

The parent repository records `mobile/` as a Git link at commit `9b8b02f22fb22d1dc3fa52ec7b4864ac8a12b72f`, but:

- There is no `.gitmodules` file.
- The referenced Git object is not available locally.
- The current `mobile/` directory is not itself a functioning Git checkout.
- A fresh clone cannot reconstruct this directory from the current repository configuration.
- The local directory is about 8.08 GB including dependencies and build output, or about 182 MB after excluding common generated dependency/build folders.
- Current development scripts use `mobile-v2/`, so `mobile/` is the obsolete client. The user decided not to migrate it.

## Recommended Laptop Migration Checklist

1. Clone `https://github.com/NathanHennigh/trotter.git` on the new laptop.
2. Confirm `main` is at commit `b385055` or newer.
3. Securely transfer `backend/.env`; do not commit it.
4. Do not migrate `trotter-photo-curation/`, the obsolete `mobile/` tree, or generated `mobile-v2/docs/design-directions/` files.
5. Install Git, Node.js, Docker Desktop, Android Studio, the Android SDK/platform tools, and a compatible JDK.
6. Reinstall project dependencies rather than copying dependency folders.
7. Start Docker Desktop and wait for its Linux engine to be ready.
8. Connect the Android phone, authorize USB debugging, and verify `adb devices` reports `device`.
9. Run `.\scripts\dev.ps1 -InstallAndroid` for the first native installation.
10. After installation, use the Expo development-client QR code on port `8083`.

## Suggested Next Product Step

Before implementing another visual rewrite, choose two or three of the latest structural systems and identify which interaction ideas should survive independently of theme. A likely production shortlist is:

- Native Calm for baseline usability and implementation speed.
- Photo-Optional Editorial for a strong brand system that does not require custom art.
- Living Route or Map Room for a distinctive travel-specific navigation and data model.

The most useful implementation exercise would be one end-to-end vertical slice across Globe, Trips, Passport, and Dream detail using a single selected structural system, tested on the physical Android device.
