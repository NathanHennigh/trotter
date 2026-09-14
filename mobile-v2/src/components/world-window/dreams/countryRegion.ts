import { globeCountries } from "../globe-geography";
import { countryKey } from "./dreamPresentation";

export type CountryRegion = { bounds: [[number, number], [number, number]]; label: string };
const cache = new Map<string, CountryRegion | undefined>();

/** A camera overview only. These bounds are never used as a saved-place pin. */
export function countryRegion(name: string): CountryRegion | undefined {
  const key = countryKey(name);
  if (cache.has(key)) return cache.get(key);
  const country = globeCountries.find((entry) => countryKey(entry.name) === key || entry.code.toLowerCase() === key);
  if (!country) { cache.set(key, undefined); return undefined; }
  const components = country.polygons.map((polygon) => {
    const ring = polygon[0];
    const lons = ring.map(([lon]) => ((lon % 360) + 360) % 360).sort((a, b) => a - b);
    let gap = -1, west = 0;
    lons.forEach((lon, index) => {
      const next = lons[(index + 1) % lons.length] + (index === lons.length - 1 ? 360 : 0);
      if (next - lon > gap) { gap = next - lon; west = next % 360; }
    });
    const east = west + 360 - gap;
    const south = Math.max(-85, Math.min(...ring.map((point) => point[1])));
    const north = Math.min(85, Math.max(...ring.map((point) => point[1])));
    return { west, east, south, north, area: (east - west) * (north - south) };
  }).sort((a, b) => b.area - a.area);
  const main = components[0];
  if (!main) return undefined;
  const center = (main.west + main.east) / 2;
  const nearby = components.map((part) => {
    const shift = 360 * Math.round((center - (part.west + part.east) / 2) / 360);
    return { ...part, west: part.west + shift, east: part.east + shift };
  }).filter((part) => part.west < main.east + 12 && part.east > main.west - 12 && part.south < main.north + 10 && part.north > main.south - 10);
  // Keep distant overseas territories from turning a useful regional view into a world map.
  const bounds: CountryRegion["bounds"] = [
    [Math.min(...nearby.map((part) => part.south)), Math.min(...nearby.map((part) => part.west))],
    [Math.max(...nearby.map((part) => part.north)), Math.max(...nearby.map((part) => part.east))],
  ];
  const region = { bounds, label: country.name };
  cache.set(key, region);
  return region;
}
