# Trotter Mobile V2

Experimental Expo native frontend for the passport-ledger visual direction.

## Run

```powershell
cd C:\Users\natha\projects\trotter\mobile-v2
npm install
npx expo run:android
```

This project is set up for native development builds from the start. It uses `expo-gl`, `expo-three`, and `three` for a GPU-backed globe.

## Current Scope

- Passport/ticket-inspired home screen.
- Three.js globe with procedural atmosphere, grid, city lights, and flight arcs.
- Recent trip cards with stamp/photo placeholders.
- Bottom navigation shell.
- Asset requirement list in `ASSET_REQUIREMENTS.md`.

## Placeholder Notes

The prototype intentionally avoids final custom art. Paper textures, map textures, stamps, photos, and icons are represented with styled React Native views or procedural geometry until the asset pipeline is ready.
