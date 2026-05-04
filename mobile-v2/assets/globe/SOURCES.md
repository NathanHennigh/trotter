# Globe Source Assets

## NASA Black Marble 2016

- File: `black-marble-2016-3600.jpg`
- Source URL: `https://assets.science.nasa.gov/content/dam/science/esd/eo/images/imagerecords/144000/144898/BlackMarble_2016_01deg.jpg`
- Use: equirectangular Earth-at-night diffuse texture for the Three.js globe.
- Notes: NASA imagery is generally usable for app prototypes and products when NASA attribution and endorsement rules are respected.

## NASA Blue Marble Day Texture

- File: `blue-marble-day-4096.jpg`
- Source URL: `https://eoimages.gsfc.nasa.gov/images/imagerecords/57000/57730/land_ocean_ice_2048.jpg`
- Source URL for high-resolution master: `https://eoimages.gsfc.nasa.gov/images/imagerecords/57000/57730/land_ocean_ice_8192.png`
- Use: daylight Earth diffuse texture blended with the night map by the Three.js day/night shader.
- Notes: the app texture is a 4096x2048 JPEG derived from the NASA 8192x4096 PNG to keep mobile GPU memory reasonable.

## Natural Earth Country Borders

- Source URL: `https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_110m_admin_0_countries.geojson`
- Runtime file: `src/data/countryBorders110m.json`
- Use: lightweight country border rings rendered as thin Three.js line geometry.

## Future Source Candidates

- Natural Earth for public-domain coastline, country, and admin boundary vectors.
- Our own backend airport/trip data for lights, route arcs, hubs, and destination labels.
