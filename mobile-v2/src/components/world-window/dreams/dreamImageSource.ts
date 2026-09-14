import type { DreamItem } from "../../../services/dreams";

export type DreamThumbnail = { uri: string; privateImage: boolean };

export function resolveDreamThumbnail(raw: string | undefined, apiBaseUrl: string): DreamThumbnail | undefined {
  const value = raw?.trim();
  if (!value || value.startsWith("//")) return undefined;
  try {
    const base = new URL(apiBaseUrl.replace(/\/+$/, ""));
    const uri = new URL(value.startsWith("/") ? `${base.toString().replace(/\/$/, "")}${value}` : value);
    if (!/^https?:$/.test(uri.protocol) || uri.username || uri.password) return undefined;
    const prefix = `${base.pathname.replace(/\/+$/, "")}/dream-items/`;
    return { uri: uri.toString(), privateImage: uri.origin === base.origin && uri.pathname.startsWith(prefix) };
  } catch {
    return undefined;
  }
}

/** Skip missing or invalid covers while keeping the user's saved order. */
export function postcardReelCover(items: DreamItem[], apiBaseUrl: string) {
  return items.find(item => resolveDreamThumbnail(item.thumbnailUrl, apiBaseUrl)) ?? items[0];
}
