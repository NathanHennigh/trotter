import world from "../../data/worldCountries.json";
export type GeoCountry = {
  code: string;
  name: string;
  index: number;
  polygons: number[][][][];
};
export const globeCountries: GeoCountry[] = world.features.map((f, i) => ({
  code:
    f.properties.adm0A3 === "SOL"
      ? "X-SOMALILAND"
      : f.properties.adm0A3 === "KAS"
        ? "X-SIACHEN"
        : f.properties.countryCode,
  name: f.properties.name,
  index: i + 1,
  polygons: (f.geometry.type === "Polygon"
    ? [f.geometry.coordinates]
    : f.geometry.coordinates) as number[][][][],
}));
function inRing(lon: number, lat: number, ring: number[][]) {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const a = ring[i],
      b = ring[j];
    if (
      a[1] > lat !== b[1] > lat &&
      lon < ((b[0] - a[0]) * (lat - a[1])) / (b[1] - a[1]) + a[0]
    )
      inside = !inside;
  }
  return inside;
}
export function countryAt(lon: number, lat: number) {
  return globeCountries.find((c) =>
    c.polygons.some(
      (p) =>
        inRing(lon, lat, p[0]) && !p.slice(1).some((h) => inRing(lon, lat, h)),
    ),
  );
}
export function flightCountryKey(
  country?: string,
  code?: string,
  airport?: string,
) {
  if (
    ["HGA", "BBO"].includes(airport?.toUpperCase() ?? "") ||
    country?.toLowerCase() === "somaliland" ||
    code === "X-SOMALILAND"
  )
    return "X-SOMALILAND";
  return globeCountries.find(
    (c) =>
      c.code === code?.toUpperCase() ||
      c.name.toLowerCase() === country?.toLowerCase(),
  )?.code;
}
export function sunPosition(date = new Date()) {
  const rad = Math.PI / 180,
    days = date.getTime() / 86400000 + 2440587.5 - 2451545,
    mean = (357.528 + 0.9856003 * days) * rad;
  const lon =
      (280.46 +
        0.9856474 * days +
        1.915 * Math.sin(mean) +
        0.02 * Math.sin(2 * mean)) *
      rad,
    tilt = (23.439 - 0.0000004 * days) * rad;
  const lat = Math.asin(Math.sin(tilt) * Math.sin(lon)),
    asc = Math.atan2(Math.cos(tilt) * Math.sin(lon), Math.cos(lon)),
    sidereal = (280.46061837 + 360.98564736629 * days) * rad;
  return {
    lat: lat / rad,
    lon: (((((asc - sidereal) / rad) % 360) + 540) % 360) - 180,
  };
}
