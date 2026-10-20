import type { DreamItem } from "../../../services/dreams";

export type DreamProcessingState = {
  kind: "upload" | "sorting" | "unreadable" | "failed" | "details" | "deferred";
  label: string;
  detail: string;
};

/** Job state is authoritative; a completed unidentified reel is no longer sorting. */
export function dreamProcessingState(item: DreamItem): DreamProcessingState | undefined {
  if (item.uploadStatus) return {
    kind: "upload",
    label: item.uploadStatus === "sending" ? "Sending reel…" : item.uploadStatus === "failed" ? "Upload needs retry" : "Waiting to send",
    detail: "Kept on this device until it reaches Trotter.",
  };
  if (item.processingRetryAt && Number.isFinite(Date.parse(item.processingRetryAt))) return {
    kind: "deferred", label: "Will retry automatically",
    detail: "Your reel is saved. We’ll try sorting it again automatically.",
  };
  // Source limitations are shown in the location section, not as a failed save.
  if (item.locationState === "source_details") return undefined;
  if (item.sortingState === "sorted") return undefined;
  if (item.sortingState === "queued" || item.sortingState === "running" ||
      (!item.sortingState && (item.status === "created" || item.status === "processing"))) return {
    kind: "sorting", label: "Sorting reel…",
    detail: item.processingMessage || "Saved. Sorting this post in the background—you can leave this screen.",
  };
  if (item.sortingState === "unavailable") return {
    kind: "unreadable", label: "Couldn’t read reel",
    detail: item.processingMessage || "Your reel is saved, but Instagram’s caption could not be read. You can retry or open the original.",
  };
  if (item.sortingState === "failed" || item.status === "failed") return {
    kind: "failed", label: "Couldn’t sort reel",
    detail: item.processingMessage || "Your reel is saved, but sorting could not finish. You can retry or open the original.",
  };
  if (item.sortingState === "needs_details" || (!item.sortingState && (item.needsReview || !item.country?.trim()))) return {
    kind: "details", label: item.placeName ? "Location missing" : "Needs details",
    detail: item.processingMessage || (item.placeName
      ? "Your reel is saved, but there isn’t enough location information to place it yet."
      : "Your reel is saved. Its caption didn’t identify a place."),
  };
  return undefined;
}

export function dreamProcessingSummary(items: DreamItem[]): string {
  const counts = { upload: 0, sorting: 0, unreadable: 0, failed: 0, details: 0, deferred: 0 };
  for (const item of items) {
    const state = dreamProcessingState(item);
    if (state) counts[state.kind]++;
  }
  return [
    counts.upload && `${counts.upload} waiting to send`,
    counts.sorting && `${counts.sorting} sorting`,
    counts.deferred && `${counts.deferred} will retry automatically`,
    counts.details && `${counts.details} ${counts.details === 1 ? "needs" : "need"} details`,
    counts.unreadable && `${counts.unreadable} couldn’t be read`,
    counts.failed && `${counts.failed} couldn’t be sorted`,
  ].filter(Boolean).join(" · ");
}
