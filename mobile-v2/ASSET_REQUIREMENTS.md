# Trotter V2 Asset Requirements

The current prototype uses Three.js for the globe, routes, atmosphere, lights, and interaction. Three.js does not include real Earth imagery, but it can render equirectangular Earth textures, procedural lights, route curves, labels, and shaders on the GPU.

## Globe

### Already Handled By Three.js
- Globe sphere geometry, camera, lighting, atmosphere/rim shader, drag rotation, and animation.
- Curved flight paths generated from airport coordinates.
- Airport/city light dots generated from data.
- Latitude/longitude grid lines.
- Procedural fallback lights and stylized surface detail.

### Provided Or Publicly Sourceable
- Daylight Earth base texture: `assets/globe/blue-marble-day-4096.jpg`, sourced from NASA Blue Marble.
- Earth-at-night base texture: `assets/globe/black-marble-2016-3600.jpg`, sourced from NASA Black Marble 2016.
- Country/coastline vectors are sourced from Natural Earth and converted into mobile-friendly line geometry.
- Airport hub lights come from our own airport/trip data, not from a custom image.
- Current day/night terminator is calculated locally from the device clock and blended in a Three.js shader.

### Optional Custom/Generated Later
- Higher-resolution day/night textures, if we want closer satellite realism.
- Normal/roughness maps, if we want subtle terrain relief. Not required for the reference look.
- Animated route trail shader. Three.js can generate this; no image asset is required unless we want a custom glow sprite.
- Ocean/continent label typography treatment. These can be React Native overlays, Three.js text, or SDF text; no fixed image asset is required.

## Brand And UI
- Aged paper ticket logo plate with torn edges and fold/crease variants.
- Trotter wordmark and airplane mark as vector assets.
- Flip-counter digit sprite sheet for stats.
- Gmail provider icon, sync green light, and small status badges.
- Metal/brass circular control buttons and icon set.
- Passport stamp button art.

## Trips
- Paper-card background texture with subtle stains, fibers, and edge wear.
- Colored luggage-tag side strips and punched-hole variants.
- Destination stamp generator or stamp asset set by country/city.
- Polaroid/photo card frame, paperclip asset, and image placeholders.
- Flag assets or country-code-to-flag renderer.

## Navigation
- Bottom nav icon set in the passport/ledger style.
- Active tab glow texture.
- Review panel LCD/dot-matrix digit sprites.

## Motion
- Globe intro camera move.
- Arc reveal animation.
- Flip-counter roll animation.
- Stamp press animation.
- Sheet drag affordance animation.
