import type { DreamItem } from "../../../services/dreams";

export type DreamThumbnail = { uri: string; privateImage: boolean };

export function resolveDreamThumbnail(raw: string | undefined, apiBaseUrl: string, options?: {
  width?: 240 | 960;
  /** All extracted places can share their original post's authenticated cover. */
  sourcePostId?: string;
  /** Non-secret session/revision marker. Prevents private image reuse after sign-out. */
  authScope?: string;
}): DreamThumbnail | undefined {
  const value = raw?.trim();
  if (!value || value.startsWith("//")) return undefined;
  try {
    const base = new URL(apiBaseUrl.replace(/\/+$/, ""));
    const uri = new URL(value.startsWith("/") ? `${base.toString().replace(/\/$/, "")}${value}` : value);
    if (!/^https?:$/.test(uri.protocol) || uri.username || uri.password) return undefined;
    const prefix = base.pathname.replace(/\/+$/, "");
    const privateImage = uri.origin === base.origin && uri.pathname.startsWith(`${prefix}/`)
      && /^\/dream-(?:items|source-posts)\/\d+\/thumbnail\/?$/.test(uri.pathname.slice(prefix.length));
    if (privateImage) {
      if (options?.sourcePostId && /^\d+$/.test(options.sourcePostId)) {
        uri.pathname = `${prefix}/dream-source-posts/${options.sourcePostId}/thumbnail`;
      }
      if (options?.width) uri.searchParams.set("width", String(options.width));
      if (options?.authScope) uri.searchParams.set("session", options.authScope);
    }
    return { uri: uri.toString(), privateImage };
  } catch {
    return undefined;
  }
}

/** Skip missing or invalid covers while keeping the user's saved order. */
export function postcardReelCover(items: DreamItem[], apiBaseUrl: string) {
  return items.find(item => resolveDreamThumbnail(item.thumbnailUrl, apiBaseUrl)) ?? items[0];
}
