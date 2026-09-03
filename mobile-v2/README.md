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
