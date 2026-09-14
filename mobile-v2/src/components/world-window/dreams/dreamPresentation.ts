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
export type CountryBoard = {
  key: string;
  title: string;
  items: DreamItem[];
  cities: string[];
};
export function cityNames(items: DreamItem[]) {
  const cities = new Map<string, string>();
  for (const item of items)
    if (item.city?.trim())
      cities.set(
        normalizeName(item.city),
        cities.get(normalizeName(item.city)) ?? item.city.trim(),
      );
  return [...cities.values()].sort((a, b) => a.localeCompare(b));
}
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
      (!city || normalizeName(item.city ?? "") === normalizeName(city)) &&
      (category === "All" || categoryGroup(item.category) === category) &&
      terms.every((term) =>
        normalizeName(
          [
            item.placeName,
            item.city,
            item.summary,
            item.regionOrNeighborhood,
            ...item.tags,
          ].join(" "),
        ).includes(term),
      ),
  );
}
export function exactMapPoint(item: DreamItem): MapPoint | undefined {
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
      label: item.placeName || item.city || "Saved place",
      lat: item.latitude,
      lon: item.longitude,
      category: item.category,
      area: item.coordinatePrecision === "area",
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
    label: item.placeName || item.city || "Saved place",
    lat,
    lon,
    category: item.category,
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
