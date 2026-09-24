# Trotter Mobile V2

Experimental Expo native frontend for the passport-ledger visual direction.

## Run

```powershell
cd C:\Users\natha\projects\trotter
.\scripts\dev.ps1
```

This project is set up for native development builds from the start. It uses `expo-gl`, `expo-three`, and `three` for a GPU-backed globe.

## Install On An Android Phone

1. Enable Developer options and USB debugging on the phone.
2. Connect the phone by USB and accept the computer authorization prompt.
3. Verify that `adb devices` shows the phone with the status `device`.
4. From the repository root, run:

```powershell
.\scripts\dev.ps1 -InstallAndroid
```

That command builds a native debug APK, installs it on the connected phone, launches Trotter, and starts the Expo development server. After the native client is installed, normal JavaScript and TypeScript work only needs `.\scripts\dev.ps1`; rebuild with `-InstallAndroid` when native dependencies or native configuration change.

Trotter uses Metro port `8083` by default so it does not collide with other Expo projects using `8081`. Scan only the QR code shown in the window titled `Trotter Expo Dev Client :8083`.

Local iPhone builds require macOS and Xcode. From Windows, use an EAS iOS development build and an Apple Developer account instead.

## Build Android Artifacts In WSL

### Instagram share receipts

The Android share target opens `DreamShareActivity`, a compact native receipt over
the source app. It does not start React or wait for Instagram parsing. **Done**
returns to the source app; **View in Dreams** opens all places from that reel.
The link is saved locally before upload, and WorkManager sends each receipt
independently when connected. Parsing and place lookup run on the server.

Open Trotter and authenticate once after installing this native implementation.
Only a verified account session is copied into the device-only encrypted native
credential store. A share without that session is retained and offers sign-in;
sign-out invalidates credentials and keeps receipts isolated by account and API.
Pending receipts are never removed merely because the app was closed. Receipt
removal follows a successful authoritative Dreams refresh containing its saved ID.

Native changes require a new APK. Validate inbox behavior with
`wsl -d Ubuntu -- bash /mnt/c/Users/natha/projects/trotter/mobile-v2/scripts/testNativeShareState.sh`
and the bridge with `node scripts/testNativeDreamShare.cjs` from `mobile-v2`.

### Maps and build configuration

Dreams uses the native Google Maps SDK. Copy `android/google-maps.properties.example`
to the ignored `android/google-maps.properties` and set `androidApiKey` to a key
restricted to Maps SDK for Android, `com.trotter.mobilev2`, and the installed
build's signing certificate SHA-1. The WSL build copies this local configuration.
For Play builds, add the Play app-signing certificate, not only the upload key.
`GOOGLE_MAPS_ANDROID_API_KEY` overrides the local file in CI. Never put the backend
Places key here. `app.config.js` exposes only readiness booleans in Expo `extra`;
the Android key is installed as SDK metadata. Missing configuration keeps saved
places accessible and shows an explicit map fallback.

For iOS, supply a separate iOS-restricted `GOOGLE_MAPS_IOS_API_KEY` and prebuild on
the iOS build host. This does not configure an iOS key automatically.

The helper mirrors the Etch build-only workflow: it copies `mobile-v2` into WSL's Linux filesystem, installs locked dependencies, runs Expo configuration and TypeScript checks, and builds verified artifacts without installing or uploading them. Release mode also requires a clean `main` branch that exactly matches `origin/main`; development mode builds the current working tree for personal testing.

WSL Ubuntu needs nvm with Node `20.20.2`, Java 17, `rsync`, `unzip`, and the Android SDK at `~/Android/Sdk`.

Build a standalone preview APK:

```powershell
.\scripts\Build-Android-Artifacts.ps1 -Mode apk -ApiBaseUrl https://api.example.com
```

Build a personal test APK from the current working tree, including uncommitted changes:

```powershell
.\scripts\Build-Android-Artifacts.ps1 -Mode apk -Development -ApiBaseUrl https://api.example.com
```

Development artifacts include `-dev` in their timestamped filename. Release builds remain restricted to a clean `main` branch that exactly matches `origin/main`.

Artifacts are written to `$env:USERPROFILE\Documents\builds`, including a timestamped file, `trotter-latest.apk`, and a SHA-256 checksum.

For a Play AAB, first create an Android upload key, copy `mobile-v2/android/signing.properties.example` to the ignored `signing.properties`, and fill in its real values. Then supply a Play version code greater than every version already uploaded:

```powershell
.\scripts\Build-Android-Artifacts.ps1 -Mode both -VersionCode 2 -ApiBaseUrl https://api.example.com
```

The APK falls back to the tracked debug key for convenient local installation. The script refuses to create an AAB unless the private signing configuration and keystore exist.

## Current Scope

- Passport/ticket-inspired home screen.
- Three.js globe with procedural atmosphere, grid, city lights, and flight arcs.
- Recent trip cards with stamp/photo placeholders.
- Bottom navigation shell.
- Asset requirement list in `ASSET_REQUIREMENTS.md`.

## Placeholder Notes

The prototype intentionally avoids final custom art. Paper textures, map textures, stamps, photos, and icons are represented with styled React Native views or procedural geometry until the asset pipeline is ready.
