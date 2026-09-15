import type { CatalogEntry, CollectionCatalog } from '../../../data/collections/catalogs';

const normalized = (value: string) => value.normalize('NFKD').replace(/\p{M}/gu, '').toUpperCase().replace(/[^A-Z0-9]+/g, ' ').trim();
const indexes = new WeakMap<CollectionCatalog, { keys: Map<string, CatalogEntry>; aliases: Map<string, string | null> }>();
function index(catalog: CollectionCatalog) {
  const previous = indexes.get(catalog);
  if (previous) return previous;
  const keys = new Map(catalog.entries.map(entry => [entry.key, entry]));
  const aliases = new Map<string, string | null>();
  for (const entry of catalog.entries) for (const value of [entry.key, entry.name, ...(entry.aliases ?? [])]) {
    const alias = normalized(value);
    if (!alias) continue;
    const existing = aliases.get(alias);
    aliases.set(alias, existing === undefined || existing === entry.key ? entry.key : null);
  }
  const result = {keys,aliases}; indexes.set(catalog,result); return result;
}

/** Exact identifiers win. Ambiguous display names never silently assign an observation. */
export function resolveCatalogKey(catalog: CollectionCatalog, value?: string | null): string | undefined {
  if (!value?.trim()) return undefined;
  const {keys,aliases} = index(catalog), key = value.trim().toUpperCase();
  return keys.has(key) ? key : aliases.get(normalized(value)) ?? undefined;
}
export function catalogEntry(catalog: CollectionCatalog, value?: string | null): CatalogEntry | undefined {
  const key = resolveCatalogKey(catalog,value);
  return key ? index(catalog).keys.get(key) : undefined;
}

/** User records stay untouched; only membership in the versioned catalogue earns its progress. */
export function collectionProgress(catalog: CollectionCatalog, observedKeys: Iterable<string | null | undefined>) {
  const collectedKeys = new Set<string>(), outside = new Map<string,string>();
  for (const observed of observedKeys) {
    if (!observed?.trim()) continue;
    const key = resolveCatalogKey(catalog,observed);
    if (key) collectedKeys.add(key);
    else if (!outside.has(normalized(observed))) outside.set(normalized(observed),observed.trim());
  }
  const collected = collectedKeys.size, total = catalog.entries.length;
  return {collected,total,remaining:Math.max(0,total-collected),percent:total ? collected/total*100 : 0,
    collectedKeys:[...collectedKeys].sort(),outsideCatalogKeys:[...outside.values()].sort()};
}
