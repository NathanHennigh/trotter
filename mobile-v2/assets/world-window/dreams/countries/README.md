# Country postcard photographs

Sixteen real travel photographs for World Window Dreams. One reusable cover serves each country regardless of how many people, cities or places are saved. They represent a country; they do not claim to depict a user's saved venue.

Every photograph was selected from an individual free Unsplash photo page and visually checked for natural light, believable colors and a usable postcard crop. Photographer credits, source pages, exact download URLs, license links, dimensions and file hashes are recorded in `photo-sources.json`. The standard [Unsplash License](https://unsplash.com/license) permits this bundled use and does not require visible attribution. No Unsplash+ images are included.

Downloaded JPEG masters and curation manifests are preserved in `output/country-photographs` at the repository root. Run `node scripts/buildCountryPhotographs.cjs` from `mobile-v2` to produce the bundled WebP copies: proportional downsize to 1600px wide, quality 88, with no added color grading, AI edits, retouching or compositing. Responsive cropping is handled by the existing postcard image frame.

The earlier generated images and prompts remain archived under `output/country-postcards`; they are not used by the app. Its old encoder now writes only to that archive so it cannot replace these photographs accidentally.

`src/components/world-window/dreams/countryArtwork.ts` maps explicit country names and ISO aliases to these bundled files. Add another file and one catalog entry to grow coverage. Only country overview postcards opt in; individual saved places always use their own source thumbnail. Missing or failed country artwork falls back to the saved reel cover, then the existing neutral placeholder if no usable image exists.

No external stock-photo license UI, image service, API key, or per-user generation is needed.
