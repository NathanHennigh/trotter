import type { DreamItem } from "../../../services/dreams";
import { exactMapPoint } from "./dreamPresentation";

export const isFindingLocation = (item: DreamItem) =>
  item.locationStatus === "queued" || item.locationStatus === "running";

export const canFindLocation = (item: DreamItem) =>
  /^\d+$/.test(item.id) && Boolean(item.placeName?.trim()) &&
  item.status !== "created" && item.status !== "processing" &&
  !isFindingLocation(item) && !exactMapPoint(item) &&
  item.locationStatus !== "needs_review";

export function locationNote(item: DreamItem) {
  if (isFindingLocation(item)) return "Finding location…";
  if (exactMapPoint(item)) return undefined;
  if (item.locationStatus === "needs_review") return "Check location";
  if (item.locationStatus === "not_found") return "Location not found";
  if (item.locationStatus === "failed" || item.locationStatus === "blocked") return "Location lookup unavailable";
  return "Find location";
}

export function locationExplanation(item: DreamItem) {
  if (isFindingLocation(item)) return "Looking for the address. You can leave this page; the pin will appear when it’s ready.";
  if (item.locationStatus === "needs_review") return item.locationCandidates?.length
    ? "Which location is the one you saved?" : "Add a city or neighborhood in Edit details to narrow down this place.";
  if (item.locationStatus === "not_found") return "No reliable match yet. Check the name and city, or add a map pin in Edit details.";
  if (item.locationStatus === "failed" || item.locationStatus === "blocked") return "The address lookup is unavailable. Your place is saved; you can retry or add a map pin in Edit details.";
  return "Find an address using this place’s name and location.";
}
