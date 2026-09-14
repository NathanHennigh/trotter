import type { DreamItem } from "../../../services/dreams";
import { categoryLabel } from "./dreamPresentation";

/** Repair reversible punctuation damage for display; never replace stored source text. */
export function dreamCopy(item: DreamItem): { summary?: string; original?: string } {
  const original = item.summary?.trim();
  if (!original) return {};
  const repaired = original
    .replace(/\u00e2\u20ac\u2122/g, "’")
    .replace(/\u00e2\u20ac\u0153/g, "“")
    .replace(/\u00e2\u20ac\u009d/g, "”")
    .replace(/\u00e2\u20ac\u201c/g, "–")
    .replace(/\u00e2\u20ac\u201d/g, "—")
    .replace(/\u00c2(?=[\u00a0\u00b0])/g, "");
  const damaged = /\uFFFD|\?{2,}|[\p{L}]\?[\p{L}]/u.test(repaired);
  if (!damaged) return { summary: repaired, ...(repaired !== original ? { original } : {}) };
  const location = [item.city, item.country].filter(Boolean).join(", ");
  return {
    summary: location ? `${categoryLabel(item.category)} in ${location}.` : undefined,
    original,
  };
}
