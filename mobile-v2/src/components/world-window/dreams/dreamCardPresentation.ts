import type { DreamItem } from "../../../services/dreams";
import { dreamDestination, dreamLocationType, dreamPlaceLabel, dreamSourceKey, hasDreamPlaceName, isPromotionalText, normalizeName } from "./dreamPresentation";
import { dreamProcessingState } from "./dreamProcessing";

/** Source words help distinguish unidentified reels without inventing a place. */
export function dreamCardTitle(item: DreamItem): string {
  if (hasDreamPlaceName(item) || item.coordinatePrecision === "area") return dreamPlaceLabel(item);
  const excerpt = (item.caption || item.summary || "")
    .replace(/https?:\/\/\S+/gi, "")
    .replace(/(^|\s)#[\p{L}\p{N}_]+/gu, " ")
    .split(/\n+|(?<=[.!?])\s+/)
    .filter(line => !isPromotionalText(line))
    .join(" ")
    .replace(/\s+/g, " ")
    .trim();
  // Iterate Unicode code points so truncation cannot leave half an emoji's
  // surrogate pair and render a replacement character in the native title.
  const characters = Array.from(excerpt);
  if (/[\p{L}\p{N}]/u.test(excerpt)) return characters.length > 92 ? `${characters.slice(0, 89).join("").trimEnd()}…` : excerpt;
  const destination = dreamDestination(item) || item.country?.trim();
  return destination ? `Inspiration in ${destination}` : item.locationState === "source_details" ? "Saved inspiration" : "Saved reel";
}

export function dreamCardMeta(item: DreamItem): string {
  const location = dreamDestination(item) || item.country;
  const kind = item.locationState === "source_details" ? "Inspiration" : item.category === "unknown" && item.coordinatePrecision !== "area" ? "Saved reel" : dreamLocationType(item);
  return [kind, location].filter(Boolean).join(" · ");
}

/** Existing source descriptions distinguish similarly named saves; never infer
 * that records from different posts are duplicate places to remove or merge. */
export function dreamCardExcerpt(item: DreamItem): string {
  for (const source of [item.summary, item.caption]) {
    const excerpt = (source || "").replace(/https?:\/\/\S+/gi, "")
      .replace(/(^|\s)#[\p{L}\p{N}_]+/gu, " ")
      .split(/\n+|(?<=[.!?])\s+/).filter(line => !isPromotionalText(line))
      .join(" ").replace(/\s+/g, " ").trim();
    if (!/[\p{L}\p{N}]/u.test(excerpt) || /^(?:saved from instagram|saved (?:reel|post|place))\.?$/i.test(excerpt) || normalizeName(excerpt) === normalizeName(dreamCardTitle(item))) continue;
    const characters = Array.from(excerpt);
    return characters.length > 120 ? `${characters.slice(0, 117).join("").trimEnd()}…` : excerpt;
  }
  return "";
}

export function repeatedDreamTitleIds(items: DreamItem[]): Set<string> {
  const titles = new Map<string, { sources: Set<string>; ids: string[] }>();
  for (const item of items) {
    const title = normalizeName(dreamCardTitle(item));
    const group = titles.get(title) || { sources: new Set<string>(), ids: [] };
    group.sources.add(dreamSourceKey(item.sourceUrl)); group.ids.push(item.id); titles.set(title, group);
  }
  return new Set([...titles.values()].filter(group => group.sources.size > 1).flatMap(group => group.ids));
}

export function dreamInboxSummary(items: DreamItem[]): string {
  const counts = { upload: 0, sorting: 0, unreadable: 0, failed: 0, details: 0, deferred: 0 };
  for (const item of items) {
    const state = dreamProcessingState(item);
    if (state) counts[state.kind]++;
  }
  return [
    counts.sorting && `${counts.sorting} sorting`,
    counts.deferred && `${counts.deferred} will retry automatically`,
    counts.details && `${counts.details} ${counts.details === 1 ? "needs" : "need"} details`,
    counts.unreadable && `${counts.unreadable} couldn’t be read`,
    counts.failed && `${counts.failed} couldn’t be sorted`,
    counts.upload && `${counts.upload} saved on this device`,
  ].filter(Boolean).join(" · ") || `${items.length} saved ${items.length === 1 ? "reel" : "reels"}`;
}
