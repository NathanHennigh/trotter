import type { DreamItem } from "../../../services/dreams";
import type { MapPoint } from "../trips/tripPresentation";

export const normalizeName = (value: string) =>
  value
    .normalize("NFKD")
    .replace(/\p{M}/gu, "")
    .trim()
    .replace(/\s+/g, " ")
    .toLowerCase();
const aliases: Record<string, string> = {
  usa: "united states",
  us: "united states",
  "united states of america": "united states",
  uk: "united kingdom",
  uae: "united arab emirates",
};
export const countryKey = (value?: string) =>
  (aliases[normalizeName(value ?? "")] ?? normalizeName(value ?? "")) ||
  "unsorted";
export function dreamSourceKey(value: string): string {
  try {
    const url = new URL(value);
    if (/(^|\.)instagram\.com$/i.test(url.hostname))
      return `instagram.com${url.pathname.replace(/\/+$/, "")}`;
  } catch { /* A local unsent receipt may not have a canonical URL yet. */ }
  return value;
}
export function placesFromSource(items: DreamItem[], sourceUrl: string): DreamItem[] {
  const key = dreamSourceKey(sourceUrl);
  return items.filter(item => dreamSourceKey(item.sourceUrl) === key);
}
export function sourcePlaceCounts(items: DreamItem[]): Map<string, number> {
  const counts = new Map<string, number>();
  for (const item of items) {
    const key = dreamSourceKey(item.sourceUrl);
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  return counts;
}
export type CountryBoard = {
  key: string;
  title: string;
  items: DreamItem[];
  cities: string[];
};
/** Keep browsing labels aligned with the destination shown on a saved place. */
export const dreamDestination = (item: DreamItem) => item.city?.trim() || item.regionOrNeighborhood?.trim() || "";
export function destinationNames(items: DreamItem[]) {
  const cities = new Map<string, string>();
  for (const item of items) {
    const destination = dreamDestination(item);
    if (destination)
      cities.set(
        normalizeName(destination),
        cities.get(normalizeName(destination)) ?? destination,
      );
  }
  return [...cities.values()].sort((a, b) => a.localeCompare(b));
}
// Kept for older callers; destinations also include islands and regions.
export const cityNames = destinationNames;
export function countryBoards(items: DreamItem[]): CountryBoard[] {
  const groups = new Map<string, CountryBoard>();
  for (const item of items) {
    const key = countryKey(item.country);
    const group = groups.get(key) ?? {
      key,
      title: item.country?.trim() || "Unsorted",
      items: [],
      cities: [],
    };
    group.items.push(item);
    groups.set(key, group);
  }
  return [...groups.values()].map((group) => ({
    ...group,
    cities: cityNames(group.items),
  }));
}
export const dreamCategories = [
  "All",
  "Cafés",
  "Restaurants",
  "Hotels",
  "Other",
] as const;
export type DreamFilter = (typeof dreamCategories)[number];
export const categoryLabel = (category: string) =>
  category === "cafe"
    ? "Café"
    : category === "unknown"
      ? "Place"
      : category.charAt(0).toUpperCase() + category.slice(1);
export const isPromotionalText = (value: string) => /\b(?:comment|dm|message|reply)\s+(?:(?:me|us|below|with)\s+)?["'“”‘’]?(?:link|guide|map|details|info|stay|travel|yes|send)\b|\blink\s+in\s+(?:my\s+|our\s+|the\s+)?bio\b|\bfollow\s+(?:@[\p{L}\p{N}_.]+|(?:me|us|for)\b)|\b(?:comment|dm|message|reply)\b.{0,55}\b(?:send|receive|get|location|free|guide|details|link)\b/iu.test(value);
export const hasDreamPlaceName = (item: DreamItem) => Boolean(item.placeName?.trim() && !isPromotionalText(item.placeName));
export const dreamPlaceLabel = (item: DreamItem) => (hasDreamPlaceName(item) ? item.placeName : undefined) || item.city ||
  (item.coordinatePrecision === "area" ? item.regionOrNeighborhood || item.country : undefined) || "Saved place";
export const dreamLocationType = (item: DreamItem) => item.coordinatePrecision === "area" ? "Area" : categoryLabel(item.category);
export const categoryGroup = (category: string): DreamFilter =>
  category === "cafe"
    ? "Cafés"
    : category === "restaurant"
      ? "Restaurants"
      : category === "hotel"
        ? "Hotels"
        : "Other";
export function filterDreams(
  items: DreamItem[],
  query: string,
  city: string,
  category: DreamFilter,
) {
  const terms = normalizeName(query).split(/\s+/).filter(Boolean);
  return items.filter(
    (item) =>
      (!city || normalizeName(dreamDestination(item)) === normalizeName(city)) &&
      (category === "All" || categoryGroup(item.category) === category) &&
      terms.every((term) =>
        normalizeName(
          [
            item.placeName,
            item.city,
            item.country,
            item.caption,
            item.personalNote,
            item.summary,
            item.regionOrNeighborhood,
            ...item.tags,
          ].join(" "),
        ).includes(term),
      ),
  );
}
export function exactMapPoint(item: DreamItem): MapPoint | undefined {
  // Never revive an expired Google coordinate from the Maps URL fallback.
  if (item.locationProvider === "google_places" &&
      (!item.locationExpiresAt || !Number.isFinite(Date.parse(item.locationExpiresAt)) || Date.parse(item.locationExpiresAt) <= Date.now())) return undefined;
  if (
    typeof item.latitude === "number" &&
    typeof item.longitude === "number" &&
    Number.isFinite(item.latitude) &&
    Number.isFinite(item.longitude) &&
    Math.abs(item.latitude) <= 85.05112878 &&
    Math.abs(item.longitude) <= 180
  ) {
    return {
      id: item.id,
      label: dreamPlaceLabel(item),
      lat: item.latitude,
      lon: item.longitude,
      category: item.category,
      area: item.coordinatePrecision === "area",
      ...(item.locationProvider ? { provider: item.locationProvider } : {}),
      ...(item.locationProvider === "google_places" && item.locationPlaceId ? { googlePlaceId: item.locationPlaceId } : {}),
    };
  }
  // Google '@lat,lon' describes the camera, NOT the place. Never geocode by city centre.
  if (!item.googleMapsUrl) return undefined;
  let lat: number | undefined, lon: number | undefined;
  try {
    const url = new URL(item.googleMapsUrl);
    if (!/^https?:$/.test(url.protocol)) return undefined;
    const place = url.href.match(/!3d(-?\d+(?:\.\d+)?)!4d(-?\d+(?:\.\d+)?)/);
    const query = (
      url.searchParams.get("query") ??
      url.searchParams.get("q") ??
      ""
    ).match(/^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$/);
    const match = place ?? query;
    if (match) {
      lat = Number(match[1]);
      lon = Number(match[2]);
    }
  } catch {
    return undefined;
  }
  if (
    lat === undefined ||
    lon === undefined ||
    !Number.isFinite(lat) ||
    !Number.isFinite(lon) ||
    Math.abs(lat) > 85.05112878 ||
    Math.abs(lon) > 180
  )
    return undefined;
  return {
    id: item.id,
    label: dreamPlaceLabel(item),
    lat,
    lon,
    category: item.category,
    area: item.coordinatePrecision === "area",
    ...(item.locationProvider ? { provider: item.locationProvider } : {}),
  };
}
export const safeWebUrl = (value?: string) => {
  try {
    const url = new URL(value ?? "");
    return /^https?:$/.test(url.protocol) ? url.toString() : undefined;
  } catch {
    return undefined;
  }
};
