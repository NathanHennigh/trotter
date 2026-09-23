import AsyncStorage from '@react-native-async-storage/async-storage';

/** Supply the verified account ID, never an unverified token's claims. */
export type DreamShareOutboxOwner = { apiBaseUrl: string; ownerId: number };
export type PendingDreamShare = {
  id: string;
  generation: number;
  sourceUrl: string;
  sharedText?: string;
  retryItemId?: string;
  queuedAt: number;
  updatedAt: number;
  status: 'queued' | 'failed';
  attemptCount: number;
  lastAttemptAt?: number;
  failedAt?: number;
};
export type DreamShareReceipt = Pick<PendingDreamShare, 'id' | 'generation'>;
export type DreamShareOutboxStorage = {
  getItem(key: string): Promise<string | null>;
  setItem(key: string, value: string): Promise<void>;
  removeItem(key: string): Promise<void>;
};

const MAX_ENTRIES = 100;
const MAX_TEXT_LENGTH = 10000;
const MAX_STORAGE_LENGTH = 1200000;
// Every instance using the same adapter shares its lock, including test adapters.
const storageQueues = new WeakMap<DreamShareOutboxStorage, Map<string, Promise<unknown>>>();
let nextId = 0;

/** Tracking parameters, fragments, www and trailing slashes do not identify a new post. */
export function canonicalDreamShareUrl(value: string): string | undefined {
  if (typeof value !== 'string' || value.length > 32768) return undefined;
  const trimmed = value.trim();
  const candidate = trimmed.match(/https?:\/\/(?:www\.)?instagram\.com\/[^\s<>"']+/i)?.[0]
    ?.replace(/[),.;!?]+$/, '') ?? trimmed;
  try {
    const url = new URL(/^https?:\/\//i.test(candidate) ? candidate : `https://${candidate}`);
    if (!['https:', 'http:'].includes(url.protocol) || !/^(?:www\.)?instagram\.com$/i.test(url.hostname)
      || url.username || url.password || url.port) return undefined;
    const post = url.pathname.match(/^\/(p|reel|reels|tv)\/([a-zA-Z0-9_-]{1,128})\/?$/i);
    if (!post) return undefined;
    return `https://instagram.com/${post[1].toLowerCase()}/${post[2]}`;
  } catch { return undefined; }
}

function scopeFor(owner: DreamShareOutboxOwner) {
  if (!Number.isSafeInteger(owner.ownerId) || owner.ownerId <= 0) throw new Error('A verified account is required to keep this share.');
  const api = new URL(owner.apiBaseUrl);
  if (!['https:', 'http:'].includes(api.protocol) || api.username || api.password) throw new Error('Invalid API origin.');
  const apiOrigin = api.origin;
  return { apiOrigin, ownerId: owner.ownerId,
    key: `trotter.dream-share-outbox.v1.${encodeURIComponent(apiOrigin)}.${owner.ownerId}` };
}

const validTime = (value: unknown): value is number => typeof value === 'number' && Number.isSafeInteger(value) && value >= 0;
const sharedText = (value: unknown) => typeof value === 'string' ? value.trim().slice(0, MAX_TEXT_LENGTH) || undefined : undefined;

function parseEntries(raw: string | null, scope: ReturnType<typeof scopeFor>): PendingDreamShare[] {
  if (!raw || raw.length > MAX_STORAGE_LENGTH) return [];
  try {
    const envelope = JSON.parse(raw);
    if (!envelope || envelope.version !== 1 || envelope.apiOrigin !== scope.apiOrigin
      || envelope.ownerId !== scope.ownerId || !Array.isArray(envelope.entries)) return [];
    const entries: PendingDreamShare[] = [], urls = new Set<string>(), ids = new Set<string>();
    for (const value of envelope.entries.slice(0, MAX_ENTRIES)) {
      if (!value || typeof value.id !== 'string' || !/^[a-zA-Z0-9_-]{1,128}$/.test(value.id)
        || !Number.isSafeInteger(value.generation) || value.generation < 1
        || !validTime(value.queuedAt) || !validTime(value.updatedAt)
        || !Number.isSafeInteger(value.attemptCount) || value.attemptCount < 0
        || !['queued', 'failed'].includes(value.status)) continue;
      const sourceUrl = canonicalDreamShareUrl(value.sourceUrl);
      if (!sourceUrl || urls.has(sourceUrl) || ids.has(value.id)) continue;
      urls.add(sourceUrl); ids.add(value.id);
      // Explicit fields prevent accidental persistence of credentials or response bodies.
      entries.push({ id: value.id, generation: value.generation, sourceUrl,
        sharedText: sharedText(value.sharedText), queuedAt: value.queuedAt, updatedAt: value.updatedAt,
        retryItemId: typeof value.retryItemId === 'string' && /^[1-9]\d{0,15}$/.test(value.retryItemId) ? value.retryItemId : undefined,
        status: value.status, attemptCount: value.attemptCount,
        lastAttemptAt: validTime(value.lastAttemptAt) ? value.lastAttemptAt : undefined,
        failedAt: validTime(value.failedAt) ? value.failedAt : undefined });
    }
    return entries;
  } catch { return []; }
}

/**
 * Durable receipt store only; authentication, networking and retry policy stay with the caller.
 * Await enqueue before consuming the native/UI receipt. Await beginAttempt before uploading,
 * then acknowledge/markFailed with its returned receipt. A newer generation makes old replies
 * harmless. Pending uploads always remain readable after a cold start (there is no sending lock).
 * Storage failures reject: callers must keep their incoming receipt and show a retry affordance.
 */
export function createDreamShareOutbox(storage: DreamShareOutboxStorage = AsyncStorage) {
  let queues = storageQueues.get(storage);
  if (!queues) { queues = new Map(); storageQueues.set(storage, queues); }

  function serialized<T>(owner: DreamShareOutboxOwner, operation: (scope: ReturnType<typeof scopeFor>) => Promise<T>): Promise<T> {
    // Capture account and origin now; later auth changes cannot redirect a queued write.
    let scope: ReturnType<typeof scopeFor>;
    try { scope = scopeFor(owner); } catch (error) { return Promise.reject(error); }
    const pending = (queues!.get(scope.key) ?? Promise.resolve()).catch(() => undefined).then(() => operation(scope));
    queues!.set(scope.key, pending);
    const cleanup = () => { if (queues!.get(scope.key) === pending) queues!.delete(scope.key); };
    void pending.then(cleanup, cleanup);
    return pending;
  }
  const read = async (scope: ReturnType<typeof scopeFor>) => parseEntries(await storage.getItem(scope.key), scope);
  const write = (scope: ReturnType<typeof scopeFor>, entries: PendingDreamShare[]) => {
    const snapshot = JSON.stringify({ version: 1, apiOrigin: scope.apiOrigin, ownerId: scope.ownerId, entries });
    if (snapshot.length > MAX_STORAGE_LENGTH) return Promise.reject(new Error('Your saved-share queue is full. Connect to upload your pending shares first.'));
    return storage.setItem(scope.key, snapshot);
  };
  const matches = (entry: PendingDreamShare, receipt: DreamShareReceipt) => entry.id === receipt.id && entry.generation === receipt.generation;

  return {
    list(owner: DreamShareOutboxOwner): Promise<PendingDreamShare[]> {
      return serialized(owner, read);
    },
    enqueue(owner: DreamShareOutboxOwner, share: { sourceUrl: string; sharedText?: string; retryItemId?: string }): Promise<PendingDreamShare> {
      const sourceUrl = canonicalDreamShareUrl(share.sourceUrl);
      if (!sourceUrl) return Promise.reject(new Error('Paste a valid Instagram post or reel link.'));
      const text = sharedText(share.sharedText);
      const retryItemId = typeof share.retryItemId === 'string' && /^[1-9]\d{0,15}$/.test(share.retryItemId) ? share.retryItemId : undefined;
      return serialized(owner, async scope => {
        const entries = await read(scope), now = Date.now();
        const existing = entries.find(entry => entry.sourceUrl === sourceUrl);
        if (existing) {
          if (existing.status === 'failed' || (text && existing.sharedText !== text) || (retryItemId && existing.retryItemId !== retryItemId)) {
            if (text) existing.sharedText = text;
            existing.retryItemId ??= retryItemId;
            existing.generation += 1;
            existing.updatedAt = now;
            existing.status = 'queued';
            existing.failedAt = undefined;
            await write(scope, entries);
          }
          return existing;
        }
        if (entries.length >= MAX_ENTRIES) throw new Error('Your saved-share queue is full. Connect to upload your pending shares first.');
        const entry: PendingDreamShare = {
          id: `share-${now.toString(36)}-${(++nextId).toString(36)}-${Math.random().toString(36).slice(2, 12)}`,
          generation: 1, sourceUrl, sharedText: text, retryItemId, queuedAt: now, updatedAt: now, status: 'queued', attemptCount: 0,
          lastAttemptAt: undefined, failedAt: undefined,
        };
        await write(scope, [...entries, entry]);
        return entry;
      });
    },
    beginAttempt(owner: DreamShareOutboxOwner, receipt: DreamShareReceipt): Promise<PendingDreamShare | undefined> {
      const expected = { ...receipt };
      return serialized(owner, async scope => {
        const entries = await read(scope), entry = entries.find(value => matches(value, expected));
        if (!entry) return undefined;
        entry.generation += 1;
        entry.attemptCount += 1;
        entry.updatedAt = entry.lastAttemptAt = Date.now();
        entry.status = 'queued';
        entry.failedAt = undefined;
        await write(scope, entries);
        return entry;
      });
    },
    markFailed(owner: DreamShareOutboxOwner, receipt: DreamShareReceipt): Promise<boolean> {
      const expected = { ...receipt };
      return serialized(owner, async scope => {
        const entries = await read(scope), entry = entries.find(value => matches(value, expected));
        if (!entry) return false;
        entry.generation += 1;
        entry.updatedAt = entry.failedAt = Date.now();
        entry.status = 'failed';
        await write(scope, entries);
        return true;
      });
    },
    acknowledge(owner: DreamShareOutboxOwner, receipt: DreamShareReceipt): Promise<boolean> {
      const expected = { ...receipt };
      return serialized(owner, async scope => {
        const entries = await read(scope), remaining = entries.filter(entry => !matches(entry, expected));
        if (remaining.length === entries.length) return false;
        await write(scope, remaining);
        return true;
      });
    },
    /** Explicit account-only discard; an auth transition itself need not discard unsent links. */
    clear(owner: DreamShareOutboxOwner): Promise<void> {
      return serialized(owner, scope => storage.removeItem(scope.key));
    },
  };
}

export const dreamShareOutbox = createDreamShareOutbox();
