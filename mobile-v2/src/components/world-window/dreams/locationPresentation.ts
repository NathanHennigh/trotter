import type { DreamItem } from "../../../services/dreams";
import { exactMapPoint } from "./dreamPresentation";

const scheduled = (value?: string) => Boolean(value && Number.isFinite(Date.parse(value)));
export const hasAutomaticLocationRetry = (item: DreamItem) =>
  scheduled(item.locationRetryAt) || scheduled(item.processingRetryAt);

/** A completed ambiguous result is not a worker that is still finding a place. */
export const isFindingLocation = (item: DreamItem) =>
  !hasAutomaticLocationRetry(item) && (item.locationState
    ? item.locationState === "processing"
    : item.locationStatus === "queued" || item.locationStatus === "running");

export const isSavedInspiration = (item: DreamItem) => item.locationState === "source_details";

export const canFindLocation = (item: DreamItem) =>
  /^\d+$/.test(item.id) && !isSavedInspiration(item) && !hasAutomaticLocationRetry(item) &&
  !["place", "area"].includes(item.locationState ?? "") &&
  !["resolved", "manual"].includes(item.locationStatus ?? "") &&
  Boolean(item.placeName?.trim() || (item.coordinatePrecision === "area" && (item.city || item.regionOrNeighborhood || item.country))) &&
  item.status !== "created" && item.status !== "processing" &&
  !isFindingLocation(item) && !exactMapPoint(item);

export function locationNote(item: DreamItem) {
  if (exactMapPoint(item) || item.locationState === "place" || item.locationState === "area")
    return item.coordinatePrecision === "area" || item.locationState === "area" ? "Area on map" : undefined;
  if (isSavedInspiration(item)) return item.locationReason === "broad_guide" ? "Saved inspiration" : "Location not shared";
  if (hasAutomaticLocationRetry(item)) return "Will retry automatically";
  if (isFindingLocation(item)) return "Finding location…";
  if (item.locationReason === "processing_failed") return "Not on map yet";
  if (item.locationState === "unavailable" || item.locationStatus === "failed" || item.locationStatus === "blocked") return "Location temporarily unavailable";
  if (item.locationState === "unresolved" || item.locationStatus === "needs_review" || item.locationStatus === "not_found") return "Not on map yet";
  // Old servers do not provide source evidence. Do not infer that the creator
  // omitted details, or promise that a job exists, from a missing coordinate.
  return undefined;
}

export function locationExplanation(item: DreamItem) {
  if ((item.coordinatePrecision === "area" && exactMapPoint(item)) || item.locationState === "area") return "The marker shows the general area.";
  if (isSavedInspiration(item)) {
    if (item.locationHint?.trim()) return item.locationHint;
    if (item.locationReason === "creator_link_required") return "The creator asks for a comment or message to get the location. Open the reel for their instructions.";
    if (item.locationReason === "broad_guide") return "This reel is saved as inspiration; it doesn’t identify one place to pin.";
    if (item.locationReason === "caption_missing") return "The caption doesn’t provide a location. You can still open the reel or add details if you find them.";
    return "Saved as inspiration. The post doesn’t identify the exact place.";
  }
  if (hasAutomaticLocationRetry(item)) return "Your reel is saved. We’ll retry automatically when location lookup is available.";
  if (item.coordinatePrecision === "area" && isFindingLocation(item)) return "Finding this area on the map. You can leave this page while it finishes.";
  if (isFindingLocation(item)) return "Looking for the address. You can leave this page; the pin will appear when it’s ready.";
  if (item.locationHint?.trim()) return item.locationHint;
  if (item.locationReason === "ambiguous_match" || item.locationStatus === "needs_review") return "There are several possible matches. Your save is kept here without choosing an uncertain pin.";
  if (item.locationState === "unresolved" || item.locationStatus === "not_found") return "This place isn’t on the map yet. You can open the reel or add more details if you have them.";
  if (item.locationState === "unavailable" || item.locationStatus === "failed" || item.locationStatus === "blocked") return "Location lookup is unavailable. Your place is saved; you can retry later.";
  return "Your reel is saved. A map pin is only shown when its location can be identified.";
}

/** Describes the collection without presenting inspiration as broken places. */
export function unmappedSummary(items: DreamItem[]) {
  const unpinned = items.filter(item => !exactMapPoint(item));
  const inspiration = unpinned.filter(isSavedInspiration).length;
  const other = unpinned.length - inspiration;
  return [inspiration && `${inspiration} saved as inspiration`, other && `${other} not on map`].filter(Boolean).join(" · ");
}
