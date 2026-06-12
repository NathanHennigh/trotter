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

## Current Scope

- Passport/ticket-inspired home screen.
- Three.js globe with procedural atmosphere, grid, city lights, and flight arcs.
- Recent trip cards with stamp/photo placeholders.
- Bottom navigation shell.
- Asset requirement list in `ASSET_REQUIREMENTS.md`.

## Placeholder Notes

The prototype intentionally avoids final custom art. Paper textures, map textures, stamps, photos, and icons are represented with styled React Native views or procedural geometry until the asset pipeline is ready.
