import type { DreamItem, DreamItemCategory } from "../../../services/dreams";

export type DreamDraft = {
  name: string; city: string; country: string; region: string;
  personalNote: string; tags: string; maps: string; category: DreamItemCategory;
};
export function draftFromItem(item: DreamItem): DreamDraft {
  return { name: item.placeName || "", city: item.city || "", country: item.country || "",
    region: item.regionOrNeighborhood || "", personalNote: item.personalNote || "",
    tags: item.tags.join(", "), maps: item.googleMapsUrl || "", category: item.category };
}
export function draftFingerprint(draft: DreamDraft): string {
  return JSON.stringify([draft.name.trim(), draft.city.trim(), draft.country.trim(),
    draft.region.trim(), draft.personalNote.trim(), draft.tags.split(",").map(tag => tag.trim()).filter(Boolean),
    draft.maps.trim(), draft.category]);
}
