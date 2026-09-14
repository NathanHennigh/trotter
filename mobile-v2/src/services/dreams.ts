import React from 'react';
import { clearAuthToken, getApiBaseUrl, getStoredToken, hydrateStoredToken, getAuthRevision, subscribeAuthToken } from './travelTrips';

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
  status: DreamItemStatus;
  created_at: string;
  updated_at?: string | null;
};

export type DreamItem = {
  id: string;
  dreamId: string;
  sourcePlatform: 'instagram';
  sourceUrl: string;
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
  status: DreamItemStatus;
  createdAt: string;
  updatedAt: string;
};

export type IncomingDreamShare = {
  sourceUrl: string;
  sharedText?: string;
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
    const isDreamShare = parsed.protocol === 'trotterv2:' && (parsed.hostname === 'share' || parsed.pathname.includes('share'));
    if (!isDreamShare) return undefined;
    const sourceUrl = parsed.searchParams.get('url') || parsed.searchParams.get('source_url');
    const sharedText = parsed.searchParams.get('text') || parsed.searchParams.get('shared_text') || undefined;
    if (!sourceUrl && !sharedText) return undefined;
    return {
      sourceUrl: sourceUrl || extractInstagramUrl(sharedText) || 'https://www.instagram.com/',
      sharedText,
    };
  } catch {
    return undefined;
  }
}

type DreamsContextValue = ReturnType<typeof useDreamsState>;

const DreamsContext = React.createContext<DreamsContextValue | null>(null);

function useDreamsState() {
  const [items, setItems] = React.useState<DreamItem[]>(emptyItems);
  const [liveDreams, setLiveDreams] = React.useState<Dream[] | undefined>();
  const [source, setSource] = React.useState<'local' | 'api'>('local');
  const [status, setStatus] = React.useState<'idle' | 'loading' | 'refreshing' | 'error'>('idle');
  const [error, setError] = React.useState<string | undefined>();
  const itemsRef = React.useRef(items);
  const inFlightUrlsRef = React.useRef(new Set<string>());
  const mounted = React.useRef(true);
  const refreshSequence = React.useRef(0);
  const pendingSequence = React.useRef(0);
  React.useEffect(() => {
    mounted.current = true;
    const unsubscribe = subscribeAuthToken(() => {
      refreshSequence.current += 1;
      inFlightUrlsRef.current.clear();
      itemsRef.current = [];
      setItems([]); setLiveDreams(undefined); setError(undefined); setStatus('idle');
    });
    return () => { mounted.current = false; refreshSequence.current += 1; unsubscribe(); };
  }, []);

  const itemDreams = React.useMemo(() => buildDreams(items), [items]);
  const dreams = React.useMemo(() => mergeDreams(liveDreams, itemDreams), [liveDreams, itemDreams]);
  const needsReviewItems = React.useMemo(() => items.filter((item) => item.needsReview), [items]);
  const processingItems = React.useMemo(() => items.filter((item) => item.status === 'processing' || item.status === 'created'), [items]);

  React.useEffect(() => {
    itemsRef.current = items;
  }, [items]);

  const refresh = React.useCallback(async (mode: 'loading' | 'refreshing' = 'refreshing') => {
    const sequence = ++refreshSequence.current, revision = getAuthRevision();
    setStatus(mode);
    try {
      const [apiDreams, apiItems] = await Promise.all([dreamsApiFetch<ApiDream[]>('/dreams'), dreamsApiFetch<ApiDreamItem[]>('/dream-items')]);
      if (!mounted.current || sequence !== refreshSequence.current || revision !== getAuthRevision()) return;
      const mappedDreams = apiDreams.map(mapApiDream);
      const mappedItems = apiItems.map(mapApiDreamItem);
      setLiveDreams(mappedDreams);
      setItems(current => [...current.filter(item => item.id.startsWith('dream-item-') && !mappedItems.some(remote => remote.sourceUrl === item.sourceUrl)), ...mappedItems]);
      setSource('api');
      setError(undefined);
      setStatus('idle');
    } catch (caught) {
      if (!mounted.current || sequence !== refreshSequence.current || revision !== getAuthRevision()) return;
      setSource((current) => current === 'api' ? 'api' : 'local');
      setError(caught instanceof Error ? caught.message : String(caught));
      setStatus('error');
    }
  }, []);

  React.useEffect(() => {
    refresh('loading');
  }, [refresh]);

  React.useEffect(() => {
    if (!processingItems.length) return;
    const timer = setInterval(() => { void refresh(); }, 5000);
    return () => clearInterval(timer);
  }, [processingItems.length, refresh]);

  const shareInstagramLink = React.useCallback((sourceUrl: string, caption?: string) => {
    const normalizedUrl = normalizeSourceUrl(sourceUrl);
    if (!isInstagramUrl(normalizedUrl)) {
      setError('Paste a valid Instagram post or reel link.');
      setStatus('error');
      return undefined;
    }
    const existing = itemsRef.current.find((item) => item.sourceUrl === normalizedUrl);
    if (existing && existing.status !== 'failed') return existing;
    if (inFlightUrlsRef.current.has(normalizedUrl)) {
      const inFlight = itemsRef.current.find((item) => item.sourceUrl === normalizedUrl);
      return inFlight;
    }
    inFlightUrlsRef.current.add(normalizedUrl);

    const next: DreamItem = {
      category: 'unknown',
      summary: 'Trotter is reading the Instagram post and looking for place details.',
      tags: [],
      needsReview: false,
      status: 'processing',
      id: `dream-item-${Date.now()}-${++pendingSequence.current}`,
      dreamId: 'dream-processing',
      sourcePlatform: 'instagram',
      sourceUrl: normalizedUrl,
      caption: caption?.trim() || undefined,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    };
    setError(undefined);
    setStatus('refreshing');
    const revision = getAuthRevision();
    setItems((current) => [next, ...current.filter(item => item.id !== existing?.id)]);
    shareInstagramLinkRemote(normalizedUrl, caption)
      .then(() => { if (mounted.current && revision === getAuthRevision()) return refresh('refreshing'); })
      .catch((caught) => {
        if (!mounted.current || revision !== getAuthRevision()) return;
        setError(caught instanceof Error ? caught.message : String(caught));
        setStatus('error');
        setItems((current) => current.map((item) => item.id === next.id ? {
          ...item,
          summary: 'This place could not be saved. Your original link is kept so you can retry.',
          status: 'failed',
          updatedAt: new Date().toISOString(),
        } : item));
      })
      .finally(() => {
        inFlightUrlsRef.current.delete(normalizedUrl);
      });
    return next;
  }, [refresh]);

  const updateItem = React.useCallback(async (id: string, patch: Partial<DreamItem>) => {
    if (!/^\d+$/.test(id)) throw new Error('Wait for this place to finish saving before editing.');
    const revision = getAuthRevision();
    const fields: Partial<Record<keyof DreamItem, string>> = { placeName: 'place_name', city: 'city', country: 'country', regionOrNeighborhood: 'region_or_neighborhood', summary: 'summary', category: 'category', tags: 'tags_json', googleMapsUrl: 'google_maps_url' };
    const edits = Object.fromEntries(Object.entries(patch).filter(([key]) => fields[key as keyof DreamItem]).map(([key, value]) => [fields[key as keyof DreamItem], value ?? null]));
    const response = await dreamsAuthenticatedFetch(`/dream-items/${id}/review`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ decision: patch.needsReview ? 'needs_review' : 'confirm', edits }) });
    const data = await readJson(response);
    if (!response.ok) throw new Error(readError(data, 'Your changes could not be saved.'));
    if (!mounted.current || revision !== getAuthRevision()) return;
    refreshSequence.current += 1;
    const updated = mapApiDreamItem(data as ApiDreamItem);
    setItems(current => current.map(item => item.id === id ? updated : item));
    setLiveDreams(undefined);
    setStatus('idle'); setError(undefined);
  }, []);

  const confirmItem = React.useCallback((id: string) => {
    return updateItem(id, {
      needsReview: false,
      status: 'confirmed',
      confidence: 0.9,
    });
  }, [updateItem]);

  const deleteItem = React.useCallback(async (id: string) => {
    const revision = getAuthRevision();
    if (/^\d+$/.test(id)) {
      const response = await dreamsAuthenticatedFetch(`/dream-items/${id}`, { method: 'DELETE' });
      if (!response.ok) throw new Error(readError(await readJson(response), 'This place could not be deleted.'));
    }
    if (!mounted.current || revision !== getAuthRevision()) return;
    refreshSequence.current += 1;
    setItems((current) => current.filter((item) => item.id !== id));
    setLiveDreams(undefined);
    setStatus('idle'); setError(undefined);
  }, []);

  return {
    dreams,
    items,
    needsReviewItems,
    processingItems,
    source,
    status,
    error,
    refresh,
    shareInstagramLink,
    updateItem,
    confirmItem,
    deleteItem,
  };
}

async function dreamsApiFetch<T>(path: string): Promise<T> {
  const response = await dreamsAuthenticatedFetch(path);
  const data = await readJson(response);
  if (!response.ok) throw new Error(readError(data, `Dreams API returned ${response.status}`));
  return data as T;
}

async function shareInstagramLinkRemote(sourceUrl: string, caption?: string) {
  const response = await dreamsAuthenticatedFetch('/dreams/share', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ source_url: sourceUrl, source_platform: 'instagram', shared_text: caption }),
  });
  const data = await readJson(response);
  if (!response.ok) throw new Error(readError(data, `Dream save failed: ${response.status}`));
}

async function dreamsAuthenticatedFetch(path: string, init?: RequestInit) {
  const token = getStoredToken() ?? await hydrateStoredToken();
  if (!token) throw new Error('Sign in to access your saved places.');
  const revision = getAuthRevision();
  const response = await fetch(`${getApiBaseUrl()}${path}`, withAuth(init, token));
  if (revision !== getAuthRevision() || token !== getStoredToken()) throw new Error('Your account changed.');
  if (response.status === 401) {
    await clearAuthToken();
    throw new Error('Your session expired. Sign in again.');
  }
  return response;
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

async function readJson(response: Response) {
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
    latitude: item.latitude ?? undefined,
    longitude: item.longitude ?? undefined,
    coordinatePrecision: item.coordinate_precision ?? undefined,
    status: item.status,
    createdAt: item.created_at,
    updatedAt: item.updated_at ?? item.created_at,
  };
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

function buildDreams(items: DreamItem[]): Dream[] {
  const groups = new Map<string, DreamItem[]>();
  for (const item of items) {
    const dreamId = item.dreamId || dreamIdFor(item.country, item.city);
    groups.set(dreamId, [...(groups.get(dreamId) ?? []), item]);
  }

  return Array.from(groups.entries())
    .map(([id, groupItems]) => {
      const first = groupItems[0];
      const isProcessing = groupItems.some((item) => item.status === 'processing' || item.status === 'created');
      return {
        id,
        title: isProcessing && id === 'dream-processing' ? 'Processing' : dreamTitleFor(first.country, first.city),
        country: first.country,
        city: first.city,
        itemCount: groupItems.length,
        needsReviewCount: groupItems.filter((item) => item.needsReview).length,
        processingCount: groupItems.filter((item) => item.status === 'processing').length,
        updatedAt: groupItems.map((item) => item.updatedAt).sort().reverse()[0],
      };
    })
    .sort((a, b) => Number(b.processingCount > 0) - Number(a.processingCount > 0) || b.updatedAt.localeCompare(a.updatedAt));
}

function normalizeSourceUrl(value: string) {
  const trimmed = value.trim();
  if (!trimmed) return 'https://www.instagram.com/';
  const extracted = extractInstagramUrl(trimmed);
  const source = extracted ?? trimmed;
  return source.startsWith('http') ? source : `https://${source}`;
}

function extractInstagramUrl(value?: string) {
  if (!value) return undefined;
  return value.match(/https?:\/\/(?:www\.)?instagram\.com\/[^\s]+/i)?.[0]?.replace(/[),.;]+$/, '');
}

function isInstagramUrl(value: string) {
  try {
    const parsed = new URL(value);
    return /(^|\.)instagram\.com$/i.test(parsed.hostname) && /^\/(reel|reels|p|tv)\//i.test(parsed.pathname);
  } catch {
    return false;
  }
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
