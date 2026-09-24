import React from 'react';
import { AppState } from 'react-native';
import { clearAuthToken, getApiBaseUrl, getStoredToken, hydrateStoredToken, getAuthRevision, subscribeAuthToken, useTravelTrips } from './travelTrips';
import { canonicalDreamShareUrl, dreamShareOutbox, type PendingDreamShare, type DreamShareOutboxOwner } from './dreamShareOutbox';

export type DreamItemCategory =
  | 'restaurant'
  | 'cafe'
  | 'bar'
  | 'hotel'
  | 'attraction'
  | 'activity'
  | 'beach'
  | 'shopping'
  | 'nature'
  | 'museum'
  | 'event'
  | 'unknown';

export type DreamItemStatus = 'created' | 'processing' | 'parsed' | 'needs_review' | 'confirmed' | 'failed';
export type DreamSortingState = 'queued' | 'running' | 'sorted' | 'needs_details' | 'unavailable' | 'failed';
export type DreamLocationStatus = 'queued' | 'running' | 'resolved' | 'needs_review' | 'not_found' | 'failed' | 'blocked' | 'manual';
export type DreamLocationAttribution = { displayName: string; uri?: string };
export type DreamLocationCandidate = {
  id: string;
  name: string;
  address: string;
  latitude: number;
  longitude: number;
  googleMapsUrl?: string;
  attributions?: DreamLocationAttribution[];
};
export type DreamLocationDetails = {
  coordinatePrecision?: 'place' | 'area';
  locationProvider?: string;
  locationAddress?: string;
  locationCandidates: DreamLocationCandidate[];
  locationAttributions: DreamLocationAttribution[];
  locationPlaceId?: string;
  locationExpiresAt?: string;
  locationStatus?: DreamLocationStatus;
  locationMessage?: string;
};
type ApiLocationCandidate = { id: string; name: string; address: string; latitude: number; longitude: number; google_maps_url?: string; attributions?: { display_name: string; uri?: string }[] };

export type Dream = {
  id: string;
  title: string;
  country?: string;
  city?: string;
  region?: string;
  itemCount: number;
  needsReviewCount: number;
  processingCount: number;
  updatedAt: string;
};

type ApiDream = {
  id: number;
  title: string;
  country?: string | null;
  city?: string | null;
  region?: string | null;
  item_count: number;
  needs_review_count: number;
  processing_count: number;
  updated_at?: string | null;
  created_at: string;
};

type ApiDreamItem = {
  id: number;
  dream_id: number;
  source_platform: 'instagram';
  source_url: string;
  source_post_id?: number | null;
  source_place_count?: number;
  source_place_index?: number;
  caption?: string | null;
  category: DreamItemCategory;
  place_name?: string | null;
  city?: string | null;
  country?: string | null;
  region_or_neighborhood?: string | null;
  summary: string;
  tags_json?: string[] | null;
  confidence?: number | null;
  needs_review: boolean;
  google_maps_url?: string | null;
  thumbnail_url?: string | null;
  latitude?: number | null;
  longitude?: number | null;
  coordinate_precision?: 'place' | 'area' | null;
  location_status?: DreamLocationStatus | null;
  location_address?: string | null;
  location_provider?: string | null;
  location_candidates?: ApiLocationCandidate[] | null;
  location_place_id?: string | null;
  location_candidate_ids?: string[] | null;
  location_expires_at?: string | null;
  location_user_confirmed?: boolean;
  location_message?: string | null;
  location_checked_at?: string | null;
  processing_message?: string | null;
  sorting_state?: DreamSortingState | null;
  status: DreamItemStatus;
  created_at: string;
  updated_at?: string | null;
};

export type DreamItem = {
  id: string;
  dreamId: string;
  sourcePlatform: 'instagram';
  sourceUrl: string;
  sourcePostId?: string;
  sourcePlaceCount?: number;
  sourcePlaceIndex?: number;
  caption?: string;
  category: DreamItemCategory;
  placeName?: string;
  city?: string;
  country?: string;
  regionOrNeighborhood?: string;
  summary: string;
  tags: string[];
  confidence?: number;
  needsReview: boolean;
  googleMapsUrl?: string;
  thumbnailUrl?: string;
  latitude?: number;
  longitude?: number;
  coordinatePrecision?: 'place' | 'area';
  locationStatus?: DreamLocationStatus;
  locationAddress?: string;
  locationProvider?: string;
  locationCandidates?: DreamLocationCandidate[];
  locationMessage?: string;
  locationCheckedAt?: string;
  locationPlaceId?: string;
  locationCandidateIds?: string[];
  locationExpiresAt?: string;
  locationUserConfirmed?: boolean;
  status: DreamItemStatus;
  /** Present only while the device still has an upload receipt. */
  uploadStatus?: 'queued' | 'sending' | 'failed';
  processingMessage?: string;
  sortingState?: DreamSortingState;
  createdAt: string;
  updatedAt: string;
};

export type IncomingDreamShare = {
  sourceUrl: string;
  sharedText?: string;
  /** Native receipt already owns upload; this link only opens its saved places. */
  viewOnly?: boolean;
  receiptId?: string;
};

const emptyItems: DreamItem[] = [];

export function useDreams() {
  const context = React.useContext(DreamsContext);
  if (!context) throw new Error('DreamsProvider is required');
  return context;
}

export function DreamsProvider({ children }: { children: React.ReactNode }) {
  const value = useDreamsState();
  return React.createElement(DreamsContext.Provider, { value }, children);
}

export function parseIncomingDreamShare(url: string): IncomingDreamShare | undefined {
  try {
    const parsed = new URL(url);
    const isDreamDestination = parsed.protocol === 'trotterv2:' && parsed.hostname === 'dreams';
    const isDreamShare = parsed.protocol === 'trotterv2:' && (parsed.hostname === 'share' || parsed.pathname.includes('share'));
    if (!isDreamShare && !isDreamDestination) return undefined;
    const sourceUrl = parsed.searchParams.get('url') || parsed.searchParams.get('source_url');
    const sharedText = parsed.searchParams.get('text') || parsed.searchParams.get('shared_text') || undefined;
    if (!sourceUrl && !sharedText) return undefined;
    if (isDreamDestination && !canonicalDreamShareUrl(sourceUrl ?? '')) return undefined;
    return {
      sourceUrl: sourceUrl || extractInstagramUrl(sharedText) || 'https://www.instagram.com/',
      sharedText,
      ...(isDreamDestination ? { viewOnly: true, receiptId: parsed.searchParams.get('receipt_id') || undefined } : {}),
    };
  } catch {
    return undefined;
  }
}

type DreamsContextValue = ReturnType<typeof useDreamsState>;

const DreamsContext = React.createContext<DreamsContextValue | null>(null);

function useDreamsState() {
  const { accountId, authStatus } = useTravelTrips();
  const owner = React.useMemo<DreamShareOutboxOwner | undefined>(() => authStatus === 'signed-in' && accountId
    ? { apiBaseUrl: getApiBaseUrl(), ownerId: accountId } : undefined, [accountId, authStatus]);
  const [items, setItems] = React.useState<DreamItem[]>(emptyItems);
  const [liveDreams, setLiveDreams] = React.useState<Dream[] | undefined>();
  const [source, setSource] = React.useState<'local' | 'api'>('local');
  const [status, setStatus] = React.useState<'idle' | 'loading' | 'refreshing' | 'error'>('idle');
  const [error, setError] = React.useState<string | undefined>();
  const itemsRef = React.useRef(items);
  const mounted = React.useRef(true);
  const ownerRevision = React.useRef(getAuthRevision());
  const refreshSequence = React.useRef(0);
  const activeRefresh = React.useRef<{ revision: number; promise: Promise<void> } | undefined>(undefined);
  const mutationIds = React.useRef(new Set<string>());
  const pendingSequence = React.useRef(0);
  const pendingReceipts = React.useRef<PendingDreamShare[]>([]);
  const persistingUrls = React.useRef(new Set<string>());
  const recentlyAccepted = React.useRef(new Map<string, DreamItem>());
  const activeUpload = React.useRef<string | undefined>(undefined);
  const uploadRunning = React.useRef(false);
  const uploadRequested = React.useRef(false);
  const forceUploadRetry = React.useRef(false);
  const uploadTimer = React.useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const kickUploads = React.useRef<(retry?: boolean) => void>(() => {});
  const currentOwner = React.useCallback(() => mounted.current && !!owner && ownerRevision.current === getAuthRevision(), [owner]);
  const updateItems = React.useCallback((update: (current: DreamItem[]) => DreamItem[]) => {
    const next = update(itemsRef.current);
    itemsRef.current = next;
    setItems(next);
  }, []);
  const showPending = React.useCallback((entries: PendingDreamShare[]) => {
    pendingReceipts.current = entries;
    updateItems(current => {
      const remote = current.filter(item => /^\d+$/.test(item.id)).map(item => {
        const pending = entries.find(entry => entry.sourceUrl === normalizeSourceUrl(item.sourceUrl));
        return { ...item, uploadStatus: pending ? (activeUpload.current === pending.id ? 'sending' : pending.status) : undefined } as DreamItem;
      });
      const remoteUrls = new Set(remote.map(item => normalizeSourceUrl(item.sourceUrl)));
      const queued = entries.filter(entry => !remoteUrls.has(entry.sourceUrl)).map(entry => pendingDreamItem(entry, activeUpload.current === entry.id));
      const queuedUrls = new Set(entries.map(entry => entry.sourceUrl));
      const preserving = current.filter(item => !/^\d+$/.test(item.id)
        && (persistingUrls.current.has(item.sourceUrl) || (item.id.startsWith('dream-item-preview-') && item.uploadStatus === 'failed'))
        && !queuedUrls.has(item.sourceUrl));
      return [...queued, ...preserving, ...remote];
    });
  }, [updateItems]);
  React.useEffect(() => {
    mounted.current = true;
    const unsubscribe = subscribeAuthToken(() => {
      refreshSequence.current += 1;
      clearTimeout(uploadTimer.current);
      mutationIds.current.clear();
      pendingReceipts.current = [];
      persistingUrls.current.clear();
      recentlyAccepted.current.clear();
      activeRefresh.current = undefined;
      itemsRef.current = [];
      setItems([]); setLiveDreams(undefined); setError(undefined); setStatus('idle');
    });
    return () => { mounted.current = false; refreshSequence.current += 1; clearTimeout(uploadTimer.current); unsubscribe(); };
  }, []);

  const itemDreams = React.useMemo(() => buildDreams(items), [items]);
  const dreams = React.useMemo(() => mergeDreams(liveDreams, itemDreams), [liveDreams, itemDreams]);
  const needsReviewItems = React.useMemo(() => items.filter((item) => item.needsReview), [items]);
  const pendingUploadItems = React.useMemo(() => items.filter(item => item.uploadStatus), [items]);
  const processingItems = React.useMemo(() => items.filter(isSortingDreamItem), [items]);
  const locatingItems = React.useMemo(() => items.filter((item) => item.locationStatus === 'queued' || item.locationStatus === 'running'), [items]);
  const awaitingReceiptDetails = recentlyAccepted.current.size;

  const refresh = React.useCallback((mode: 'loading' | 'refreshing' | 'quiet' = 'refreshing'): Promise<void> => {
    if (!currentOwner()) return Promise.resolve();
    if (mode === 'refreshing') kickUploads.current(true);
    const revision = getAuthRevision();
    if (activeRefresh.current?.revision === revision) return activeRefresh.current.promise;
    const run = async () => {
      const sequence = ++refreshSequence.current;
      if (mode !== 'quiet') setStatus(mode);
      try {
        // A failing endpoint must not leave its sibling running behind the next
        // poll. Both requests are bounded and this refresh owns both until settled.
        const [dreamsResult, itemsResult] = await Promise.allSettled([dreamsApiFetch<ApiDream[]>('/dreams'), dreamsApiFetch<ApiDreamItem[]>('/dream-items')]);
        if (itemsResult.status === 'rejected') throw itemsResult.reason;
        const apiItems = itemsResult.value;
        if (!mounted.current || sequence !== refreshSequence.current || revision !== getAuthRevision()) return;
        const mappedItems = apiItems.map(mapApiDreamItem);
        setLiveDreams(dreamsResult.status === 'fulfilled' ? dreamsResult.value.map(mapApiDream) : undefined);
        for (const remote of mappedItems) recentlyAccepted.current.delete(remote.id);
        updateItems(current => [
          ...current.filter(item => !/^\d+$/.test(item.id) && !mappedItems.some(remote => normalizeSourceUrl(remote.sourceUrl) === item.sourceUrl)),
          ...[...recentlyAccepted.current.values()].filter(item => !mappedItems.some(remote => remote.id === item.id)),
          ...mappedItems,
        ]);
        showPending(pendingReceipts.current);
        setSource('api');
        if (mode !== 'quiet') { setError(undefined); setStatus('idle'); }
      } catch (caught) {
        if (!mounted.current || sequence !== refreshSequence.current || revision !== getAuthRevision()) return;
        setSource((current) => current === 'api' ? 'api' : 'local');
        if (mode !== 'quiet') {
          setError(caught instanceof Error ? caught.message : String(caught));
          setStatus('error');
        }
      }
    };
    const task = { revision, promise: Promise.resolve() };
    task.promise = run().finally(() => {
      if (activeRefresh.current === task) activeRefresh.current = undefined;
    });
    activeRefresh.current = task;
    return task.promise;
  }, [currentOwner, updateItems, showPending]);

  React.useEffect(() => {
    refresh('loading');
  }, [refresh]);

  React.useEffect(() => {
    if (!processingItems.length && !locatingItems.length && !awaitingReceiptDetails) return;
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      if (AppState.currentState === 'active') await refresh('quiet');
      if (!disposed) timer = setTimeout(() => void poll(), 5000);
    };
    timer = setTimeout(() => void poll(), 5000);
    return () => { disposed = true; clearTimeout(timer); };
  }, [processingItems.length, locatingItems.length, awaitingReceiptDetails, refresh]);

  const drainUploads = React.useCallback((retry = false) => {
    if (!owner || !currentOwner()) return;
    if (retry) forceUploadRetry.current = true;
    if (uploadRunning.current) { uploadRequested.current = true; return; }
    uploadRunning.current = true;
    clearTimeout(uploadTimer.current);
    void (async () => {
      let storageFailed = false;
      try {
        let forceIds = new Set<string>();
        // Each network call has a deadline; one uploader owns this account queue.
        for (let count = 0; count < 100 && currentOwner(); count++) {
          uploadRequested.current = false;
          const entries = await dreamShareOutbox.list(owner);
          if (!currentOwner()) return;
          showPending(entries);
          if (forceUploadRetry.current) { forceIds = new Set(entries.map(entry => entry.id)); forceUploadRetry.current = false; }
          const entry = entries.find(value => !mutationIds.current.has(`dream-item-${value.id}`) && !mutationIds.current.has(value.retryItemId ?? '')
            && (value.status === 'queued' || forceIds.has(value.id) || (value.attemptCount < 4 && uploadRetryAt(value) <= Date.now())));
          if (!entry || AppState.currentState !== 'active') break;
          forceIds.delete(entry.id);
          activeUpload.current = entry.id;
          let attempt: PendingDreamShare | undefined;
          try {
            attempt = await dreamShareOutbox.beginAttempt(owner, entry);
            if (!attempt || !currentOwner()) continue;
            showPending(entries.map(value => value.id === attempt!.id ? attempt! : value));
            const saved = await sendPendingDreamShare(attempt, id => itemsRef.current.find(item =>
              id ? item.id === id : normalizeSourceUrl(item.sourceUrl) === attempt!.sourceUrl));
            if (!currentOwner()) return;
            // Capture success directly becomes a server item, even when list GETs fail.
            refreshSequence.current += 1;
            recentlyAccepted.current.set(saved.id, saved);
            // A reel may own several venue rows. Replace its acknowledged row
            // and local upload placeholder, never its already-saved siblings.
            updateItems(current => [saved, ...current.filter(item => item.id !== saved.id
              && (/^\d+$/.test(item.id) || normalizeSourceUrl(item.sourceUrl) !== attempt!.sourceUrl))]);
            setSource('api'); setStatus('idle'); setError(undefined);
            await dreamShareOutbox.acknowledge(owner, attempt);
            if (!currentOwner()) return;
            void refresh('quiet');
          } catch (caught) {
            if (!currentOwner()) return;
            if (attempt) {
              try { await dreamShareOutbox.markFailed(owner, attempt); }
              catch { storageFailed = true; }
            } else storageFailed = true;
            if (currentOwner()) {
              setError(caught instanceof Error ? caught.message : String(caught));
              setStatus('error');
            }
          } finally { activeUpload.current = undefined; }
          if (storageFailed) break;
        }
        if (!currentOwner()) return;
        const entries = await dreamShareOutbox.list(owner);
        if (!currentOwner()) return;
        showPending(entries);
        const retryTimes = entries.filter(entry => entry.status === 'failed' && entry.attemptCount < 4).map(uploadRetryAt);
        if (!storageFailed && AppState.currentState === 'active' && retryTimes.length) {
          uploadTimer.current = setTimeout(() => kickUploads.current(), Math.max(500, Math.min(...retryTimes) - Date.now()));
        }
      } catch (caught) {
        storageFailed = true;
        if (currentOwner()) { setError(caught instanceof Error ? caught.message : String(caught)); setStatus('error'); }
      } finally {
        uploadRunning.current = false;
        if (!storageFailed && currentOwner() && (uploadRequested.current || forceUploadRetry.current)) kickUploads.current();
      }
    })();
  }, [owner, currentOwner, showPending, updateItems, refresh]);
  kickUploads.current = drainUploads;

  React.useEffect(() => {
    drainUploads();
    const subscription = AppState.addEventListener('change', next => {
      if (next === 'active') { drainUploads(true); void refresh('quiet'); }
      else clearTimeout(uploadTimer.current);
    });
    return () => subscription.remove();
  }, [drainUploads, refresh]);

  const shareInstagramLinkDurable = React.useCallback(async (sourceUrl: string, caption?: string): Promise<void> => {
    const normalizedUrl = canonicalDreamShareUrl(sourceUrl);
    if (!normalizedUrl) throw new Error('Paste a valid Instagram post or reel link.');
    if (!owner || !currentOwner()) throw new Error('Sign in to save this place.');
    const existing = itemsRef.current.find(item => normalizeSourceUrl(item.sourceUrl) === normalizedUrl);
    if (existing && mutationIds.current.has(existing.id)) throw new Error('This place is still saving. Wait for it to finish before retrying.');
    if (existing && /^\d+$/.test(existing.id) && !existing.uploadStatus && !['failed', 'needs_review'].includes(existing.status)) return;
    persistingUrls.current.add(normalizedUrl);
    try {
      const entry = await dreamShareOutbox.enqueue(owner, { sourceUrl: normalizedUrl, sharedText: caption,
        retryItemId: existing && /^\d+$/.test(existing.id) && ['failed', 'needs_review'].includes(existing.status) ? existing.id : undefined });
      if (!currentOwner()) throw new Error('Your account changed.');
      showPending([...pendingReceipts.current.filter(value => value.sourceUrl !== normalizedUrl), entry]);
      setError(undefined); setStatus('idle');
      drainUploads();
    } finally { persistingUrls.current.delete(normalizedUrl); }
  }, [owner, currentOwner, showPending, drainUploads]);

  // Inline capture/editor compatibility. Native delivery awaits the durable method.
  const shareInstagramLink = React.useCallback((sourceUrl: string, caption?: string) => {
    const normalizedUrl = canonicalDreamShareUrl(sourceUrl);
    if (!normalizedUrl || !currentOwner()) { setError('Paste a valid Instagram post or reel link while signed in.'); setStatus('error'); return undefined; }
    const existing = itemsRef.current.find(item => normalizeSourceUrl(item.sourceUrl) === normalizedUrl);
    const next = existing ?? pendingDreamItem({ id: `preview-${Date.now()}-${++pendingSequence.current}`, generation: 1, sourceUrl: normalizedUrl,
      sharedText: caption, status: 'queued', attemptCount: 0, queuedAt: Date.now(), updatedAt: Date.now() });
    if (!existing) updateItems(current => [next, ...current]);
    void shareInstagramLinkDurable(normalizedUrl, caption).catch(caught => {
      if (!currentOwner()) return;
      setError(caught instanceof Error ? caught.message : String(caught)); setStatus('error');
      updateItems(current => current.map(item => item.id === next.id ? { ...item, status: /^\d+$/.test(item.id) ? item.status : 'failed',
        uploadStatus: 'failed', summary: 'This link could not be kept on this device. Retry saving it before closing the app.' } : item));
    });
    return next;
  }, [currentOwner, updateItems, shareInstagramLinkDurable]);

  const updateItem = React.useCallback(async (id: string, patch: Partial<DreamItem>) => {
    if (!/^\d+$/.test(id)) throw new Error('Wait for this place to finish saving before editing.');
    const sourceUrl = normalizeSourceUrl(itemsRef.current.find(item => item.id === id)?.sourceUrl ?? '');
    if (pendingReceipts.current.some(entry => entry.retryItemId === id || entry.sourceUrl === sourceUrl)
      || persistingUrls.current.has(sourceUrl)) {
      throw new Error('This post is being queued for reading. Wait for it to finish before editing.');
    }
    if (mutationIds.current.has(id)) throw new Error('This place is still saving. Wait for it to finish before making another change.');
    const revision = getAuthRevision();
    mutationIds.current.add(id);
    refreshSequence.current += 1;
    try {
      const fields: Partial<Record<keyof DreamItem, string>> = { placeName: 'place_name', city: 'city', country: 'country', regionOrNeighborhood: 'region_or_neighborhood', summary: 'summary', category: 'category', tags: 'tags_json', googleMapsUrl: 'google_maps_url' };
      const edits = Object.fromEntries(Object.entries(patch).filter(([key]) => fields[key as keyof DreamItem]).map(([key, value]) => [fields[key as keyof DreamItem], value ?? null]));
      const response = await dreamsAuthenticatedFetch(`/dream-items/${id}/review`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ decision: patch.needsReview ? 'needs_review' : 'confirm', edits }) });
      const data = await readJson(response);
      if (!response.ok) throw new Error(readError(data, 'Your changes could not be saved.'));
      if (!mounted.current || revision !== getAuthRevision()) return;
      refreshSequence.current += 1;
      const updated = mapApiDreamItem(data as ApiDreamItem);
      recentlyAccepted.current.set(updated.id, updated);
      updateItems(current => current.map(item => item.id === id ? updated : item));
      setLiveDreams(undefined);
      setStatus('idle'); setError(undefined);
    } catch (caught) {
      if (mounted.current && revision === getAuthRevision()) {
        setStatus('error'); setError(caught instanceof Error ? caught.message : String(caught));
      }
      throw caught;
    } finally { if (revision === getAuthRevision()) mutationIds.current.delete(id); }
  }, [updateItems]);

  const confirmItem = React.useCallback((id: string) => {
    return updateItem(id, {
      needsReview: false,
      status: 'confirmed',
      confidence: 0.9,
    });
  }, [updateItem]);

  const deleteItem = React.useCallback(async (id: string) => {
    if (mutationIds.current.has(id)) throw new Error('This place is still saving. Wait for it to finish before making another change.');
    const item = itemsRef.current.find(value => value.id === id);
    const receipt = pendingReceipts.current.find(value => value.sourceUrl === normalizeSourceUrl(item?.sourceUrl ?? ''));
    if (receipt && activeUpload.current === receipt.id) throw new Error('This place is being sent. Wait for it to finish before deleting it.');
    if (item && persistingUrls.current.has(item.sourceUrl)) throw new Error('This place is still saving. Wait for it to finish before deleting it.');
    const revision = getAuthRevision();
    mutationIds.current.add(id);
    const receiptItemId = receipt ? `dream-item-${receipt.id}` : undefined;
    if (receiptItemId) mutationIds.current.add(receiptItemId);
    refreshSequence.current += 1;
    try {
      let remoteId = /^\d+$/.test(id) ? id : receipt?.retryItemId;
      if (!remoteId && receipt && receipt.attemptCount > 0) {
        // A timed-out POST may already have committed. Reconcile its idempotent
        // receipt before deletion rather than leaving an orphan on the server.
        const accepted = await shareInstagramLinkRemote(receipt.sourceUrl, receipt.sharedText);
        remoteId = String(accepted.dream_item_id);
      }
      if (remoteId) {
        const response = await dreamsAuthenticatedFetch(`/dream-items/${remoteId}`, { method: 'DELETE' });
        if (!response.ok && response.status !== 404) throw new Error(readError(await readJson(response), 'This place could not be deleted.'));
      }
      if (owner && receipt) {
        const removed = await dreamShareOutbox.acknowledge(owner, receipt);
        if (!removed) throw new Error('This share changed while deleting it. Please try again.');
      }
      if (!mounted.current || revision !== getAuthRevision()) return;
      refreshSequence.current += 1;
      recentlyAccepted.current.delete(remoteId ?? id);
      pendingReceipts.current = pendingReceipts.current.filter(value => value.id !== receipt?.id);
      updateItems((current) => current.filter((item) => item.id !== id && item.id !== remoteId));
      setLiveDreams(undefined);
      setStatus('idle'); setError(undefined);
    } catch (caught) {
      if (mounted.current && revision === getAuthRevision()) {
        setStatus('error'); setError(caught instanceof Error ? caught.message : String(caught));
      }
      throw caught;
    } finally {
      if (revision === getAuthRevision()) {
        mutationIds.current.delete(id);
        if (receiptItemId) mutationIds.current.delete(receiptItemId);
      }
    }
  }, [owner, updateItems]);

  const locationRequest = React.useCallback(async (path: string, ids: string[], body: object = {}) => {
    if (!ids.length) return;
    if (ids.some(id => !/^\d+$/.test(id))) throw new Error('Wait for these places to finish saving first.');
    const sourceUrls = new Set(itemsRef.current.filter(item => ids.includes(item.id)).map(item => normalizeSourceUrl(item.sourceUrl)));
    if (pendingReceipts.current.some(entry => (entry.retryItemId && ids.includes(entry.retryItemId)) || sourceUrls.has(entry.sourceUrl))
      || [...sourceUrls].some(sourceUrl => persistingUrls.current.has(sourceUrl))) {
      throw new Error('This post is being queued for reading. Wait for it to finish before changing its location.');
    }
    if (ids.some(id => mutationIds.current.has(id))) throw new Error('A place is still saving. Please try again shortly.');
    const revision = getAuthRevision();
    ids.forEach(id => mutationIds.current.add(id));
    refreshSequence.current += 1;
    try {
      const response = await dreamsAuthenticatedFetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      const data = await readJson(response);
      if (!response.ok) throw new Error(response.status === 404
        ? 'Location lookup is not available on this server yet. You can still add a map pin in Edit details.'
        : readError(data, 'Location lookup could not start. Your saved places are unchanged.'));
      if (!mounted.current || revision !== getAuthRevision()) return;
      refreshSequence.current += 1;
      const records = (data && typeof data === 'object' && 'items' in data)
        ? (data as { items: ApiDreamItem[] }).items : [data as ApiDreamItem];
      const updates = new Map(records.map(record => { const item = mapApiDreamItem(record); return [item.id, item] as const; }));
      updates.forEach(item => recentlyAccepted.current.set(item.id, item));
      updateItems(current => current.map(item => updates.get(item.id) ?? item));
      setStatus('idle'); setError(undefined);
    } catch (caught) {
      if (mounted.current && revision === getAuthRevision()) {
        setStatus('error'); setError(caught instanceof Error ? caught.message : String(caught));
      }
      throw caught;
    } finally { if (revision === getAuthRevision()) ids.forEach(id => mutationIds.current.delete(id)); }
  }, [updateItems]);
  const locateItem = React.useCallback((id: string) => locationRequest(`/dream-items/${id}/locate`, [id]), [locationRequest]);
  const confirmLocation = React.useCallback((id: string, candidateId: string) => locationRequest(`/dream-items/${id}/location-confirm`, [id], { candidate_id: candidateId }), [locationRequest]);
  const locateMissing = React.useCallback(async (ids: string[]) => {
    const uniqueIds = [...new Set(ids)];
    const revision = getAuthRevision();
    for (let start = 0; start < uniqueIds.length; start += 250) {
      if (revision !== getAuthRevision()) return;
      const batch = uniqueIds.slice(start, start + 250);
      await locationRequest('/dreams/locate-missing', batch, { item_ids: batch.map(Number) });
    }
  }, [locationRequest]);

  return {
    dreams,
    items,
    needsReviewItems,
    pendingUploadItems,
    processingItems,
    locatingItems,
    source,
    status,
    error,
    refresh,
    shareInstagramLink,
    shareInstagramLinkDurable,
    updateItem,
    confirmItem,
    deleteItem,
    locateItem,
    locateMissing,
    confirmLocation,
  };
}

async function dreamsApiFetch<T>(path: string): Promise<T> {
  const response = await dreamsAuthenticatedFetch(path);
  const data = await readJson(response);
  if (!response.ok) throw new Error(readError(data, `Dreams API returned ${response.status}`));
  return data as T;
}

/** Transient Google content belongs to the open detail view, never the saved-items store. */
export async function fetchDreamLocationDetails(id: string, signal?: AbortSignal): Promise<DreamLocationDetails> {
  if (!/^\d+$/.test(id)) throw new Error('Wait for this place to finish saving first.');
  const response = await dreamsAuthenticatedFetch(`/dream-items/${id}/location-details`, { signal, cache: 'no-store', headers: { 'Cache-Control': 'no-store' } });
  const data = await readJson(response);
  if (!response.ok) throw new Error(readError(data, 'Location details could not load. Your saved place is unchanged.'));
  const value = data as {
    coordinate_precision?: 'place' | 'area';
    location_provider?: string; location_address?: string; location_candidates?: ApiLocationCandidate[];
    location_attributions?: { display_name: string; uri?: string }[]; location_place_id?: string;
    location_expires_at?: string; location_status?: DreamLocationStatus; location_message?: string;
  };
  return {
    ...(value.coordinate_precision ? { coordinatePrecision: value.coordinate_precision } : {}),
    locationProvider: value.location_provider, locationAddress: value.location_address || undefined,
    locationCandidates: mapLocationCandidates(value.location_candidates),
    locationAttributions: mapLocationAttributions(value.location_attributions),
    locationPlaceId: value.location_place_id, locationExpiresAt: value.location_expires_at,
    locationStatus: value.location_status, locationMessage: value.location_message,
  };
}

const uploadRetryAt = (entry: PendingDreamShare) => (entry.failedAt ?? entry.lastAttemptAt ?? 0) + Math.min(60000, 5000 * 2 ** Math.min(entry.attemptCount - 1, 4));

function pendingDreamItem(entry: PendingDreamShare, sending = false): DreamItem {
  return {
    id: `dream-item-${entry.id}`, dreamId: 'dream-pending-upload', sourcePlatform: 'instagram',
    sourceUrl: entry.sourceUrl, caption: entry.sharedText, category: 'unknown', tags: [], needsReview: false,
    status: entry.status === 'failed' ? 'failed' : 'created', uploadStatus: sending ? 'sending' : entry.status,
    summary: entry.status === 'failed' ? 'Your link is saved on this device. Trotter will retry sending it when you reconnect.' : 'Your link is saved on this device and is waiting to be sent.',
    createdAt: new Date(entry.queuedAt).toISOString(), updatedAt: new Date(entry.updatedAt).toISOString(),
  };
}

type DreamShareAcknowledgement = { dream_item_id: number; dream_id: number; status: DreamItemStatus; processing_message?: string };

async function sendPendingDreamShare(entry: PendingDreamShare, getExisting: (id?: string) => DreamItem | undefined): Promise<DreamItem> {
  if (entry.retryItemId) {
    const response = await dreamsAuthenticatedFetch(`/dream-items/${entry.retryItemId}/parse`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ caption: entry.sharedText }),
    });
    const data = await readJson(response);
    if (!response.ok) throw new Error(readError(data, 'This post could not be queued for reading.'));
    const parsed = data as ApiDreamItem;
    if (String(parsed.id) !== entry.retryItemId || !['created', 'processing', 'parsed', 'needs_review', 'confirmed', 'failed'].includes(parsed.status)) {
      throw new Error('The server did not confirm this retry. Your link is kept for retry.');
    }
    return mapApiDreamItem(parsed);
  }
  const acknowledged = await shareInstagramLinkRemote(entry.sourceUrl, entry.sharedText);
  // The list may have exposed full details while this capture request was pending.
  const existing = getExisting(String(acknowledged.dream_item_id));
  const needsReview = acknowledged.status === 'needs_review' || acknowledged.status === 'failed';
  const sorting = acknowledged.status === 'created' || acknowledged.status === 'processing';
  const knownSummary = existing && /^\d+$/.test(existing.id) && !['created', 'processing'].includes(existing.status) ? existing.summary.trim() : undefined;
  const summary = sorting ? acknowledged.processing_message || 'Saved. Trotter is sorting this post on the server.'
    : knownSummary || (needsReview ? 'Saved. Add a caption or place details to help sort this post.' : 'Saved to Dreams. Refresh to load details.');
  return { ...(existing ?? pendingDreamItem(entry)), id: String(acknowledged.dream_item_id), dreamId: String(acknowledged.dream_id),
    sourceUrl: entry.sourceUrl, status: acknowledged.status, needsReview, uploadStatus: undefined,
    processingMessage: acknowledged.processing_message,
    summary,
    updatedAt: new Date().toISOString() };
}

async function shareInstagramLinkRemote(sourceUrl: string, caption?: string): Promise<DreamShareAcknowledgement> {
  const response = await dreamsAuthenticatedFetch('/dreams/share', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ source_url: sourceUrl, source_platform: 'instagram', shared_text: caption }),
  });
  const data = await readJson(response);
  if (!response.ok) throw new Error(readError(data, `Dream save failed: ${response.status}`));
  const receipt = data as DreamShareAcknowledgement & { item_id?: number };
  const itemId = receipt.dream_item_id ?? receipt.item_id;
  if (!Number.isSafeInteger(itemId) || itemId! <= 0 || !Number.isSafeInteger(receipt.dream_id)
    || !['created', 'processing', 'parsed', 'needs_review', 'confirmed', 'failed'].includes(receipt.status)) {
    throw new Error('The server did not confirm this share. Your link is kept for retry.');
  }
  return { ...receipt, dream_item_id: itemId! };
}

type DreamsResponse = Pick<Response, 'status' | 'ok' | 'text'>;
async function dreamsAuthenticatedFetch(path: string, init?: RequestInit): Promise<DreamsResponse> {
  if (init?.signal?.aborted) throw new Error('The request was cancelled.');
  const initialRevision = getAuthRevision();
  const token = getStoredToken() ?? await hydrateStoredToken();
  if (!token) throw new Error('Sign in to access your saved places.');
  if (initialRevision !== getAuthRevision()) throw new Error('Your account changed.');
  const revision = getAuthRevision();
  const controller = new AbortController();
  let timer: ReturnType<typeof setTimeout> | undefined;
  let unsubscribe = () => {};
  let cancel = () => {};
  const deadline = new Promise<never>((_resolve, reject) => {
    cancel = () => { reject(new Error('The request was cancelled.')); controller.abort(); };
    init?.signal?.addEventListener('abort', cancel, { once: true });
    if (init?.signal?.aborted) cancel();
    timer = setTimeout(() => {
      reject(new Error(init?.method && init.method !== 'GET'
        ? 'The request timed out. The change may still finish on the server. Refresh saved places before retrying.'
        : 'Saved places took too long to load. Check your connection and retry.'));
      controller.abort();
    }, 30000);
    unsubscribe = subscribeAuthToken(() => {
      reject(new Error('Your account changed.'));
      controller.abort();
    });
  });
  try {
    const request = (async () => {
      const response = await fetch(`${getApiBaseUrl()}${path}`, withAuth({ ...init,
        headers: { ...init?.headers, 'X-Trotter-Maps': 'google' }, signal: controller.signal }, token));
      if (revision !== getAuthRevision() || token !== getStoredToken()) throw new Error('Your account changed.');
      if (response.status === 401) {
        // Remove our listener before invalidating the account so the useful
        // expiry message wins over this request's generic account-change error.
        unsubscribe();
        await clearAuthToken();
        throw new Error('Your session expired. Sign in again.');
      }
      const body = await response.text();
      if (revision !== getAuthRevision() || token !== getStoredToken()) throw new Error('Your account changed.');
      return { status: response.status, ok: response.ok, text: async () => body };
    })();
    return await Promise.race([request, deadline]);
  } finally {
    clearTimeout(timer);
    unsubscribe();
    init?.signal?.removeEventListener('abort', cancel);
  }
}

function withAuth(init: RequestInit | undefined, token: string): RequestInit {
  return {
    ...init,
    headers: {
      ...(init?.headers ?? {}),
      Authorization: `Bearer ${token}`,
      'ngrok-skip-browser-warning': 'true',
    },
  };
}

async function readJson(response: DreamsResponse) {
  const text = await response.text();
  if (!text) return {};
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return { detail: text };
  }
}

function readError(data: unknown, fallback: string) {
  if (data && typeof data === 'object' && 'detail' in data) return String((data as { detail: unknown }).detail);
  return fallback;
}

function mapApiDream(dream: ApiDream): Dream {
  return {
    id: String(dream.id),
    title: dream.title,
    country: dream.country ?? undefined,
    city: dream.city ?? undefined,
    region: dream.region ?? undefined,
    itemCount: dream.item_count,
    needsReviewCount: dream.needs_review_count,
    processingCount: dream.processing_count,
    updatedAt: dream.updated_at ?? dream.created_at,
  };
}

function mapApiDreamItem(item: ApiDreamItem): DreamItem {
  return {
    id: String(item.id),
    dreamId: String(item.dream_id),
    sourcePlatform: item.source_platform,
    sourceUrl: item.source_url,
    sourcePostId: item.source_post_id == null ? undefined : String(item.source_post_id),
    sourcePlaceCount: item.source_place_count,
    sourcePlaceIndex: item.source_place_index,
    caption: item.caption ?? undefined,
    category: item.category,
    placeName: item.place_name ?? undefined,
    city: item.city ?? undefined,
    country: item.country ?? undefined,
    regionOrNeighborhood: item.region_or_neighborhood ?? undefined,
    summary: item.summary,
    tags: item.tags_json ?? [],
    confidence: item.confidence ?? undefined,
    needsReview: item.needs_review,
    googleMapsUrl: item.google_maps_url ?? undefined,
    thumbnailUrl: item.thumbnail_url ?? undefined,
    latitude: item.location_provider === 'google_places' && (!item.location_expires_at || Date.parse(item.location_expires_at) <= Date.now() || !Number.isFinite(Date.parse(item.location_expires_at))) ? undefined : item.latitude ?? undefined,
    longitude: item.location_provider === 'google_places' && (!item.location_expires_at || Date.parse(item.location_expires_at) <= Date.now() || !Number.isFinite(Date.parse(item.location_expires_at))) ? undefined : item.longitude ?? undefined,
    coordinatePrecision: item.coordinate_precision ?? undefined,
    locationStatus: item.location_status ?? undefined,
    locationAddress: item.location_provider === 'google_places' ? undefined : item.location_address ?? undefined,
    locationProvider: item.location_provider ?? undefined,
    locationCandidates: item.location_provider === 'google_places' ? [] : mapLocationCandidates(item.location_candidates),
    locationPlaceId: item.location_place_id ?? undefined,
    locationCandidateIds: item.location_candidate_ids ?? [],
    locationExpiresAt: item.location_expires_at ?? undefined,
    locationUserConfirmed: item.location_user_confirmed,
    locationMessage: item.location_message ?? undefined,
    locationCheckedAt: item.location_checked_at ?? undefined,
    status: item.status,
    processingMessage: item.processing_message ?? undefined,
    sortingState: item.sorting_state ?? undefined,
    createdAt: item.created_at,
    updatedAt: item.updated_at ?? item.created_at,
  };
}

function mapLocationAttributions(values?: { display_name: string; uri?: string }[] | null): DreamLocationAttribution[] {
  return (values ?? []).filter(value => typeof value.display_name === 'string' && value.display_name.trim()).map(value => ({ displayName: value.display_name, uri: value.uri }));
}
function mapLocationCandidates(values?: ApiLocationCandidate[] | null): DreamLocationCandidate[] {
  return (values ?? []).filter(candidate => typeof candidate.id === 'string' &&
    typeof candidate.latitude === 'number' && typeof candidate.longitude === 'number' &&
    Number.isFinite(candidate.latitude) && Number.isFinite(candidate.longitude) &&
    Math.abs(candidate.latitude) <= 85.05112878 && Math.abs(candidate.longitude) <= 180
  ).map(candidate => ({ id: candidate.id, name: candidate.name, address: candidate.address,
    latitude: candidate.latitude, longitude: candidate.longitude, googleMapsUrl: candidate.google_maps_url,
    attributions: mapLocationAttributions(candidate.attributions) }));
}

function mergeDreams(apiDreams: Dream[] | undefined, itemDreams: Dream[]) {
  if (!apiDreams) return itemDreams;
  const merged = new Map(apiDreams.map((dream) => [dream.id, dream]));
  for (const dream of itemDreams) {
    const existing = merged.get(dream.id);
    if (!existing) {
      merged.set(dream.id, dream);
      continue;
    }
    merged.set(dream.id, {
      ...existing,
      itemCount: Math.max(existing.itemCount, dream.itemCount),
      processingCount: Math.max(existing.processingCount, dream.processingCount),
      updatedAt: existing.updatedAt > dream.updatedAt ? existing.updatedAt : dream.updatedAt,
    });
  }
  return Array.from(merged.values()).sort((a, b) => {
    const processingSort = Number(b.processingCount > 0) - Number(a.processingCount > 0);
    if (processingSort !== 0) return processingSort;
    return b.updatedAt.localeCompare(a.updatedAt);
  });
}

function isSortingDreamItem(item: DreamItem): boolean {
  return !item.uploadStatus && (item.sortingState
    ? item.sortingState === 'queued' || item.sortingState === 'running'
    : item.status === 'processing' || item.status === 'created');
}

function buildDreams(items: DreamItem[]): Dream[] {
  const groups = new Map<string, DreamItem[]>();
  for (const item of items) {
    const dreamId = item.dreamId || dreamIdFor(item.country, item.city);
    groups.set(dreamId, [...(groups.get(dreamId) ?? []), item]);
  }

  return Array.from(groups.entries())
    .map(([id, groupItems]) => {
      const first = groupItems[0];
      const isProcessing = groupItems.some(isSortingDreamItem);
      return {
        id,
        title: isProcessing && id === 'dream-processing' ? 'Processing' : dreamTitleFor(first.country, first.city),
        country: first.country,
        city: first.city,
        itemCount: groupItems.length,
        needsReviewCount: groupItems.filter((item) => item.needsReview).length,
        processingCount: groupItems.filter(isSortingDreamItem).length,
        updatedAt: groupItems.map((item) => item.updatedAt).sort().reverse()[0],
      };
    })
    .sort((a, b) => Number(b.processingCount > 0) - Number(a.processingCount > 0) || b.updatedAt.localeCompare(a.updatedAt));
}

function normalizeSourceUrl(value: string) {
  return canonicalDreamShareUrl(value) ?? value.trim();
}

function extractInstagramUrl(value?: string) {
  if (!value) return undefined;
  return value.match(/https?:\/\/(?:www\.)?instagram\.com\/[^\s]+/i)?.[0]?.replace(/[),.;]+$/, '');
}

function dreamIdFor(country?: string, city?: string) {
  if (!country && !city) return 'dream-unsorted';
  return `dream-${slugify([country, city].filter(Boolean).join('-'))}`;
}

function dreamTitleFor(country?: string, city?: string) {
  if (country && city) return `${city}, ${country}`;
  if (country) return country;
  if (city) return city;
  return 'Unsorted Travel Ideas';
}

function slugify(value: string) {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'unsorted';
}
