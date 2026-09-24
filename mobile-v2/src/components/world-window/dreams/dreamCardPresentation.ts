import type { DreamItem } from "../../../services/dreams";
import { dreamLocationType, dreamPlaceLabel } from "./dreamPresentation";
import { dreamProcessingState } from "./dreamProcessing";

/** Source words help distinguish unidentified reels without inventing a place. */
export function dreamCardTitle(item: DreamItem): string {
  if (item.placeName?.trim() || item.coordinatePrecision === "area") return dreamPlaceLabel(item);
  const excerpt = (item.caption || item.summary || "")
    .replace(/https?:\/\/\S+/gi, "")
    .replace(/(^|\s)#[\p{L}\p{N}_]+/gu, " ")
    .replace(/\s+/g, " ")
    .trim();
  if (excerpt) return excerpt.length > 92 ? `${excerpt.slice(0, 89).trimEnd()}…` : excerpt;
  return item.city?.trim() || "Saved reel";
}

export function dreamCardMeta(item: DreamItem): string {
  const location = item.city || item.regionOrNeighborhood || item.country;
  const kind = item.category === "unknown" && item.coordinatePrecision !== "area" ? "Saved reel" : dreamLocationType(item);
  return [kind, location].filter(Boolean).join(" · ");
}

export function dreamInboxSummary(items: DreamItem[]): string {
  const counts = { upload: 0, sorting: 0, unreadable: 0, failed: 0, details: 0 };
  for (const item of items) {
    const state = dreamProcessingState(item);
    if (state) counts[state.kind]++;
  }
  return [
    counts.sorting && `${counts.sorting} sorting`,
    counts.details && `${counts.details} ${counts.details === 1 ? "needs" : "need"} details`,
    counts.unreadable && `${counts.unreadable} couldn’t be read`,
    counts.failed && `${counts.failed} couldn’t be sorted`,
    counts.upload && `${counts.upload} saved on this device`,
  ].filter(Boolean).join(" · ") || `${items.length} saved ${items.length === 1 ? "reel" : "reels"}`;
}
