import type { DreamItem } from "../../../services/dreams";
import { dreamDestination, filterDreams, normalizeName } from "./dreamPresentation";
import { dreamProcessingState } from "./dreamProcessing";

export const browseTypes = ["All types", "Eat & drink", "Stay", "Things to do"] as const;
export type BrowseType = typeof browseTypes[number];
export type BrowseSort = "recent" | "city";
export function browseGroup(category: string): BrowseType {
  return ["cafe", "restaurant", "bar"].includes(category) ? "Eat & drink" : category === "hotel" ? "Stay" : "Things to do";
}
export function browseDreams(items: DreamItem[], query = "", city = "", type: BrowseType = "All types", sort: BrowseSort = "recent") {
  const matched = filterDreams(items, query, city, "All").filter(item => type === "All types" || browseGroup(item.category) === type);
  return matched.sort((a, b) => {
    if (sort === "city") {
      const group = normalizeName(dreamDestination(a)).localeCompare(normalizeName(dreamDestination(b)));
      if (group) return group;
      return (a.placeName || "").localeCompare(b.placeName || "");
    }
    const time = (value?: string) => { const n = Date.parse(value || ""); return Number.isFinite(n) ? n : 0; };
    return time(b.createdAt) - time(a.createdAt) || b.id.localeCompare(a.id, undefined, { numeric: true });
  });
}
export function needsDreamAttention(item: DreamItem) {
  const state = dreamProcessingState(item);
  if (state?.kind === "upload") return item.uploadStatus === "failed";
  // A creator withholding a location is not a broken save, even without a country.
  if (item.locationState === "source_details") return false;
  if (state?.kind === "sorting" || state?.kind === "deferred") return false;
  return Boolean(state || !item.country?.trim());
}
