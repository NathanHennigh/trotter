import type { MapPoint } from "../trips/tripPresentation";
import type { CountryRegion } from "./countryRegion";

export type PlacesRegion = { latitude: number; longitude: number; latitudeDelta: number; longitudeDelta: number };
export type DreamPlacesMapProps = {
  points: MapPoint[];
  fitKey: string;
  selectedId?: string;
  placing?: boolean;
  onSelect?: (id: string | undefined) => void;
  onPlace?: (lat: number, lon: number) => void;
  height?: number;
  overview?: CountryRegion;
};
export const normalizeLongitude = (lon: number) => ((lon + 180) % 360 + 360) % 360 - 180;
export const validMapCoordinate = (lat: unknown, lon: unknown): boolean =>
  typeof lat === "number" && typeof lon === "number" && Number.isFinite(lat) && Number.isFinite(lon) &&
  Math.abs(lat) <= 85.05112878 && Math.abs(lon) <= 180;
export function cleanMapPoints(points: MapPoint[]): MapPoint[] {
  const unique = new Map<string, MapPoint>();
  for (const point of points) if (point.id && validMapCoordinate(point.lat, point.lon)) unique.set(point.id, point);
  return [...unique.values()];
}
const mercator = (lat: number) => Math.log(Math.tan(Math.PI / 4 + Math.max(-85.05112878, Math.min(85.05112878, lat)) * Math.PI / 360));
const latitudeFromMercator = (y: number) => (2 * Math.atan(Math.exp(y)) - Math.PI / 2) * 180 / Math.PI;
function longitudeSpan(longitudes: number[]) {
  const values = longitudes.map(lon => (lon + 360) % 360).sort((a, b) => a - b);
  let start = values[0], gap = -1;
  values.forEach((value, index) => {
    const next = index === values.length - 1 ? values[0] + 360 : values[index + 1];
    if (next - value > gap) { gap = next - value; start = next % 360; }
  });
  return { center: normalizeLongitude(start + (360 - gap) / 2), span: 360 - gap };
}
/** Fit in projected map space, including countries crossing the date line. */
export function placesRegion(points: MapPoint[], overview?: CountryRegion, width = 320, height = 240): PlacesRegion {
  const clean = cleanMapPoints(points);
  let south = -45, north = 65, center = 0, span = 320;
  if (clean.length) {
    // With no provider viewport, an area coordinate is a representative centre,
    // never a building-sized target. This is camera padding, not a claimed boundary.
    south = Math.max(-85.05112878, Math.min(...clean.map(p => p.lat - (p.area ? .09 : 0))));
    north = Math.min(85.05112878, Math.max(...clean.map(p => p.lat + (p.area ? .09 : 0))));
    ({ center, span } = longitudeSpan(clean.flatMap(p => p.area
      ? [normalizeLongitude(p.lon - .09 / Math.max(.09, Math.cos(p.lat * Math.PI / 180))), normalizeLongitude(p.lon + .09 / Math.max(.09, Math.cos(p.lat * Math.PI / 180)))]
      : [p.lon])));
  } else if (overview) {
    const [[s, w], [n, e]] = overview.bounds;
    if ([s, w, n, e].every(Number.isFinite) && n >= s) {
      south = Math.max(-85, s); north = Math.min(85, n);
      span = Math.min(359, ((e - w) % 360 + 360) % 360 || 360);
      center = normalizeLongitude(w + span / 2);
    }
  }
  const aspect = Math.max(0.5, width / Math.max(height, 1));
  const yCenter = (mercator(south) + mercator(north)) / 2;
  const ySpan = Math.max(mercator(north) - mercator(south), 0.0001);
  const xSpan = Math.max(span * Math.PI / 180, 0.0001);
  const fittedY = Math.max(ySpan, xSpan / aspect) * 1.4;
  const fittedX = Math.max(xSpan, ySpan * aspect) * 1.4;
  return {
    latitude: latitudeFromMercator(yCenter), longitude: center,
    latitudeDelta: Math.min(170, latitudeFromMercator(yCenter + fittedY / 2) - latitudeFromMercator(yCenter - fittedY / 2)),
    longitudeDelta: Math.min(359, fittedX * 180 / Math.PI),
  };
}
export function focusPlaceRegion(point: MapPoint, current: PlacesRegion, width = 320, height = 240): PlacesRegion {
  const local = placesRegion([point], undefined, width, height);
  // A list selection should reveal its surroundings, rather than merely move
  // a country-wide camera. Keep a closer view the user has already chosen.
  if (!point.area) return { ...current, latitude: point.lat, longitude: point.lon,
    latitudeDelta: Math.min(current.latitudeDelta, local.latitudeDelta),
    longitudeDelta: Math.min(current.longitudeDelta, local.longitudeDelta) };
  return { ...current, latitude: point.lat, longitude: point.lon,
    latitudeDelta: Math.max(current.latitudeDelta, local.latitudeDelta),
    longitudeDelta: Math.max(current.longitudeDelta, local.longitudeDelta) };
}
export type PlaceCluster = { id: string; points: MapPoint[]; latitude: number; longitude: number; selectedPoint?: MapPoint };
/** Cluster in screen space without changing the saved coordinates or hiding a selected pin. */
export function clusterPlaces(points: MapPoint[], region: PlacesRegion, width: number, height: number, selectedId?: string): PlaceCluster[] {
  const bins = new Map<string, MapPoint[]>();
  const spacing = 44; // The 36px circles need a little room between their borders.
  const yCenter = mercator(region.latitude);
  const ySpan = Math.max(0.000001, mercator(region.latitude + region.latitudeDelta / 2) - mercator(region.latitude - region.latitudeDelta / 2));
  const project = (latitude: number, longitude: number) => ({
    x: normalizeLongitude(longitude - region.longitude) / Math.max(0.000001, region.longitudeDelta) * width,
    y: (mercator(latitude) - yCenter) / ySpan * height,
  });
  for (const point of cleanMapPoints(points).sort((a, b) => a.id < b.id ? -1 : a.id > b.id ? 1 : 0)) {
    const { x, y } = project(point.lat, point.lon);
    const key = point.id === selectedId ? `selected:${point.id}` : `${Math.floor((x + width / 2) / spacing)}:${Math.floor((y + height / 2) / spacing)}`;
    const bucket = bins.get(key) ?? []; bucket.push(point); bins.set(key, bucket);
  }
  const cluster = (members: MapPoint[]): PlaceCluster => {
    const selectedPoint = members.find(point => point.id === selectedId);
    return {
      id: members.map(p => p.id).sort().join("|"), points: members,
      // One highlighted count marker represents nearby places without moving
      // the selected place away from its real coordinate or hiding its neighbors.
      latitude: selectedPoint?.lat ?? members.reduce((total, p) => total + p.lat, 0) / members.length,
      longitude: selectedPoint?.lon ?? normalizeLongitude(members[0].lon + members.reduce((total, p) => total + normalizeLongitude(p.lon - members[0].lon), 0) / members.length),
      ...(selectedPoint ? { selectedPoint } : {}),
    };
  };
  let clusters = [...bins.values()].map(cluster);
  // Neighboring cells can put two count circles almost on top of one another.
  // Merge all connected collisions, then check again: their new center can
  // overlap another cluster that was clear of both original centers.
  while (true) {
    const parents = clusters.map((_, index) => index);
    const root = (index: number): number => {
      while (parents[index] !== index) { parents[index] = parents[parents[index]]; index = parents[index]; }
      return index;
    };
    const centers = clusters.map(group => project(group.latitude, group.longitude));
    const neighbors = new Map<string, number[]>();
    let merged = false;
    for (let i = 0; i < clusters.length; i++) {
      const { x, y } = centers[i], column = Math.floor(x / spacing), row = Math.floor(y / spacing);
      // Only neighboring screen cells can collide. Distant/off-screen saves
      // should not turn a pan into an all-pairs scan of a large collection.
      for (let dx = -1; dx <= 1; dx++) for (let dy = -1; dy <= 1; dy++) {
        for (const j of neighbors.get(`${column + dx}:${row + dy}`) ?? []) {
          if (Math.hypot(x - centers[j].x, y - centers[j].y) >= spacing) continue;
          const a = root(i), b = root(j);
          if (a !== b) { parents[b] = a; merged = true; }
        }
      }
      const key = `${column}:${row}`, members = neighbors.get(key) ?? [];
      members.push(i); neighbors.set(key, members);
    }
    if (!merged) return clusters;
    const joined = new Map<number, MapPoint[]>();
    clusters.forEach((group, index) => {
      const key = root(index), members = joined.get(key) ?? [];
      members.push(...group.points); joined.set(key, members);
    });
    clusters = [...joined.values()].map(cluster);
  }
}
export function googleMapUrl(points: MapPoint[], overview?: CountryRegion) {
  const valid = cleanMapPoints(points);
  if (valid.length === 1 && valid[0].googlePlaceId)
    return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(valid[0].label)}&query_place_id=${encodeURIComponent(valid[0].googlePlaceId)}`;
  const query = valid.length === 1 ? `${valid[0].lat},${valid[0].lon}` : overview?.label || (valid[0] ? `${valid[0].lat},${valid[0].lon}` : undefined);
  return query ? `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(query)}` : undefined;
}

export const placesMapStyle = [
  { elementType: "geometry", stylers: [{ color: "#f0f0e6" }] },
  { elementType: "labels.text.fill", stylers: [{ color: "#526975" }] },
  { elementType: "labels.text.stroke", stylers: [{ color: "#faf8f2" }] },
  { featureType: "water", elementType: "geometry", stylers: [{ color: "#cadbe1" }] },
  { featureType: "landscape.natural", elementType: "geometry", stylers: [{ color: "#e1e7d8" }] },
  { featureType: "road", elementType: "geometry", stylers: [{ color: "#ffffff" }] },
  { featureType: "road.highway", elementType: "geometry", stylers: [{ color: "#e9d8b6" }] },
  { featureType: "poi", elementType: "labels.icon", stylers: [{ visibility: "off" }] },
];
