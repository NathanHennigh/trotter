import { airlineCatalog } from '../../data/collections/catalogs';

const sourceBase = 'https://assets.duffel.com/img/airlines/for-light-background/full-color-logo/';
const catalogCodes = new Set(airlineCatalog.entries.map(entry => entry.key));
type CachedLogo = { xml: string | null; expires: number };
const cache = new Map<string, CachedLogo>();
const pending = new Map<string, Promise<string | null>>();
const queue: (() => void)[] = [];
let active = 0;
const maxEntries = 96;
const maxCharacters = 2 * 1024 * 1024;

export function normalizeAirlineCode(code: string) { return code.trim().toUpperCase(); }
export function airlineSymbolUrl(code: string): string | undefined {
  const key = normalizeAirlineCode(code);
  // ZZ is Duffel's fictional sandbox airline, not a real brand to show users.
  return /^[A-Z0-9]{2}$/.test(key) && key !== 'ZZ' && catalogCodes.has(key) ? `${sourceBase}${key}.svg` : undefined;
}
export function cachedAirlineSymbol(code: string): string | null | undefined {
  const key = normalizeAirlineCode(code), item = cache.get(key);
  if (!item) return undefined;
  if (item.expires <= Date.now()) { cache.delete(key); return undefined; }
  cache.delete(key); cache.set(key, item);
  return item.xml;
}
function remember(key: string, xml: string | null, duration: number) {
  cache.delete(key); cache.set(key, { xml, expires: Date.now() + duration });
  let characters = [...cache.values()].reduce((sum, item) => sum + (item.xml?.length ?? 0), 0);
  while (cache.size > maxEntries || characters > maxCharacters) {
    const oldest = cache.keys().next().value;
    if (oldest === undefined) break;
    characters -= cache.get(oldest)?.xml?.length ?? 0; cache.delete(oldest);
  }
}
function runQueue() {
  while (active < 4 && queue.length) queue.shift()?.();
}
/** Accept only self-contained vector marks. No remote images, scripts, fonts or redirects. */
export function validAirlineSymbol(xml: string) {
  return xml.length <= 128 * 1024 && /<svg\b/i.test(xml) && /<path\b|<polygon\b|<circle\b/i.test(xml)
    && !/<!DOCTYPE|<!ENTITY|<script\b|<foreignObject\b|<image\b|<text\b|\son\w+\s*=|@import|@font-face/i.test(xml)
    && [...xml.matchAll(/\b(?:xlink:)?href\s*=\s*["']([^"']+)["']|url\(\s*["']?([^"')\s]+)["']?\s*\)/gi)]
      .every(match => (match[1] ?? match[2]).trim().startsWith('#'));
}
/** Coalesced, bounded, session cache. A missing/offline symbol never blocks an airline row. */
export function loadAirlineSymbol(code: string): Promise<string | null> {
  const key = normalizeAirlineCode(code), url = airlineSymbolUrl(key);
  if (!url) return Promise.resolve(null);
  const existing = cachedAirlineSymbol(key);
  if (existing !== undefined) return Promise.resolve(existing);
  const underway = pending.get(key);
  if (underway) return underway;
  if (pending.size >= 64) return Promise.resolve(null);
  let complete!: (xml: string | null) => void;
  const promise = new Promise<string | null>(resolve => { complete = resolve; });
  pending.set(key, promise);
  queue.push(() => {
    active++;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 6000);
    void (async () => {
      let xml: string | null = null;
      let lifetime = 60000;
      try {
        const response = await fetch(url, { signal: controller.signal, headers: { Accept: 'image/svg+xml' } });
        if (response.status === 404) lifetime = 60 * 60000;
        const redirected = response.url && !response.url.startsWith(sourceBase);
        if (response.ok && !redirected) {
          const text = await response.text();
          if (validAirlineSymbol(text)) { xml = text; lifetime = 24 * 60 * 60000; }
        }
      } catch { /* Offline, timeout and CDN failures retain the neutral IATA tile. */ }
      finally {
        clearTimeout(timer); remember(key, xml, lifetime); pending.delete(key);
        active--; complete(xml); runQueue();
      }
    })();
  });
  runQueue();
  return promise;
}
