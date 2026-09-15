import type { DreamItem } from "../../../services/dreams";
import { exactMapPoint } from "./dreamPresentation";

export const isFindingLocation = (item: DreamItem) =>
  item.locationStatus === "queued" || item.locationStatus === "running" ||
  (item.locationProvider === "google_places" && item.locationStatus === "needs_review");

export const canFindLocation = (item: DreamItem) =>
  /^\d+$/.test(item.id) && Boolean(item.placeName?.trim()) &&
  item.status !== "created" && item.status !== "processing" &&
  !isFindingLocation(item) && !exactMapPoint(item);

export function locationNote(item: DreamItem) {
  if (isFindingLocation(item)) return "Finding location…";
  if (exactMapPoint(item)) return undefined;
  if (item.locationStatus === "needs_review") return "Finding location…";
  if (item.locationStatus === "not_found") return "No reliable match yet";
  if (item.locationStatus === "failed" || item.locationStatus === "blocked") return "Location lookup unavailable";
  return "Location pending";
}

export function locationExplanation(item: DreamItem) {
  if (isFindingLocation(item)) return "Looking for the address. You can leave this page; the pin will appear when it’s ready.";
  if (item.locationStatus === "needs_review") return "Looking for the address. The pin will appear automatically when it’s ready.";
  if (item.locationStatus === "not_found") return "No matching location found. You can retry or adjust the place name in Edit details.";
  if (item.locationStatus === "failed" || item.locationStatus === "blocked") return "The address lookup is unavailable. Your place is saved; you can retry or add a map pin in Edit details.";
  return "The address and map pin will appear automatically when they’re ready.";
}
