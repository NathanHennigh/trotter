# World Window globe textures

Generated offline by `node scripts/buildWorldWindowGlobe.cjs` from existing repository assets. No account data or network calls are involved.

- `country-index.png`: 2048 × 1024 country-ID fallback.
- `country-index-4096.png`: 4096 × 2048 country-ID base.
- `country-detail/country-r{row}-c{col}.png`: 72 country-ID tiles, each 1024 × 1024 plus a one-pixel gutter on every side. Together their interiors represent a 12288 × 6144 map. The IDs follow the exact feature order of `src/data/worldCountries.json` (Natural Earth); the matching country-name/ownership interpretation lives in `globe-geography.ts`.
- `nasa-day-base-{2048,4096}.jpg`: downsampled from the existing `assets/globe/blue-marble-day-21600.jpg`. These match the source generation of the existing 72 day-detail JPEG tiles; they do not switch to a different seasonal image while a tile loads.
- `nasa-night-2048.jpg`: smaller capability fallback derived from the existing 3600 × 1800 Black Marble image.

See `../globe/SOURCES.md` for the original NASA and Natural Earth provenance. NASA imagery is a fixed source image; the globe's current solar lighting does not imply current imagery or current snow cover.

The country maps store categorical IDs and must remain lossless. The shader filters decoded land/visited/selected coverage, never numeric country IDs. Gutters come from the same master raster, wrap at the date line, and clamp at the poles.

At close zoom, the runtime retains at most four day/mask pairs (two on a 2048-pixel texture-limit device), with one decode in progress. It disposes obsolete and late-arriving textures. The base remains present during loading and failure. No individual runtime texture exceeds 4096 pixels; the 21600-pixel master is build input only.
