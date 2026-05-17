import React from 'react';
import { getApiBaseUrl, getStoredToken, hydrateStoredToken, storeAuthToken } from './travelTrips';

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
  status: DreamItemStatus;
  createdAt: string;
  updatedAt: string;
};

export type IncomingDreamShare = {
  sourceUrl: string;
  sharedText?: string;
};

const seedItems: DreamItem[] = [];

export function useDreams() {
  return React.useContext(DreamsContext) ?? useDreamsState();
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
  const [items, setItems] = React.useState<DreamItem[]>(seedItems);
  const [liveDreams, setLiveDreams] = React.useState<Dream[] | undefined>();
  const [source, setSource] = React.useState<'mock' | 'api'>('mock');
  const [status, setStatus] = React.useState<'idle' | 'loading' | 'refreshing' | 'error'>('idle');
  const [error, setError] = React.useState<string | undefined>();
  const itemsRef = React.useRef(items);
  const inFlightUrlsRef = React.useRef(new Set<string>());

  const mockDreams = React.useMemo(() => buildDreams(items), [items]);
  const dreams = React.useMemo(() => mergeDreams(liveDreams, mockDreams), [liveDreams, mockDreams]);
  const needsReviewItems = React.useMemo(() => items.filter((item) => item.needsReview), [items]);
  const processingItems = React.useMemo(() => items.filter((item) => item.status === 'processing' || item.status === 'created'), [items]);

  React.useEffect(() => {
    itemsRef.current = items;
  }, [items]);

  const refresh = React.useCallback(async (mode: 'loading' | 'refreshing' = 'refreshing') => {
    setStatus(mode);
    const token = await getDreamsAuthToken();
    if (!token) {
      setSource('mock');
      setStatus('idle');
      return;
    }
    try {
      const apiDreams = await dreamsApiFetch<ApiDream[]>('/dreams', token);
      const apiItemsNested = await Promise.all(apiDreams.map((dream) => dreamsApiFetch<ApiDreamItem[]>(`/dreams/${dream.id}/items`, token)));
      const mappedDreams = apiDreams.map(mapApiDream);
      const mappedItems = apiItemsNested.flat().map(mapApiDreamItem);
      setLiveDreams(mappedDreams);
      setItems(mappedItems);
      setSource('api');
      setError(undefined);
      setStatus('idle');
    } catch (caught) {
      setSource((current) => current === 'api' ? 'api' : 'mock');
      setError(caught instanceof Error ? caught.message : String(caught));
      setStatus('error');
    }
  }, []);

  React.useEffect(() => {
    refresh('loading');
  }, [refresh]);

  const shareInstagramLink = React.useCallback((sourceUrl: string, caption?: string) => {
    const normalizedUrl = normalizeSourceUrl(sourceUrl);
    const existing = itemsRef.current.find((item) => item.sourceUrl === normalizedUrl);
    if (existing) return existing;
    if (inFlightUrlsRef.current.has(normalizedUrl)) {
      const inFlight = itemsRef.current.find((item) => item.sourceUrl === normalizedUrl);
      if (inFlight) return inFlight;
    }
    inFlightUrlsRef.current.add(normalizedUrl);

    const next: DreamItem = {
      category: 'unknown',
      summary: 'Trotter is reading the Instagram post and looking for place details.',
      tags: [],
      needsReview: false,
      status: 'processing',
      id: `dream-item-${Date.now()}`,
      dreamId: 'dream-processing',
      sourcePlatform: 'instagram',
      sourceUrl: normalizedUrl,
      caption: caption?.trim() || undefined,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    };
    setItems((current) => [next, ...current]);
    shareInstagramLinkRemote(normalizedUrl, caption)
      .then(() => refresh('refreshing'))
      .catch((caught) => {
        setError(caught instanceof Error ? caught.message : String(caught));
        setItems((current) => current.map((item) => item.id === next.id ? {
          ...item,
          summary: 'Save failed. Check backend/auth, then try again.',
          status: 'failed',
          updatedAt: new Date().toISOString(),
        } : item));
      })
      .finally(() => {
        inFlightUrlsRef.current.delete(normalizedUrl);
      });
    return next;
  }, [refresh]);

  const updateItem = React.useCallback((id: string, patch: Partial<DreamItem>) => {
    setItems((current) => current.map((item) => {
      if (item.id !== id) return item;
      const merged = {
        ...item,
        ...patch,
        dreamId: patch.country || patch.city ? dreamIdFor(patch.country ?? item.country, patch.city ?? item.city) : item.dreamId,
        updatedAt: new Date().toISOString(),
      };
      return merged;
    }));
  }, []);

  const confirmItem = React.useCallback((id: string) => {
    updateItem(id, {
      needsReview: false,
      status: 'confirmed',
      confidence: 0.9,
    });
  }, [updateItem]);

  const deleteItem = React.useCallback((id: string) => {
    setItems((current) => current.filter((item) => item.id !== id));
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

async function dreamsApiFetch<T>(path: string, token: string): Promise<T> {
  const response = await fetch(`${getApiBaseUrl()}${path}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  const data = await readJson(response);
  if (!response.ok) throw new Error(readError(data, `Dreams API returned ${response.status}`));
  return data as T;
}

async function shareInstagramLinkRemote(sourceUrl: string, caption?: string) {
  const token = await getDreamsAuthToken();
  if (!token) throw new Error('No auth token. Sign in or enable DEV_MODE=true on the backend.');
  const response = await fetch(`${getApiBaseUrl()}/dreams/share`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ source_url: sourceUrl, source_platform: 'instagram', shared_text: caption }),
  });
  const data = await readJson(response);
  if (!response.ok) throw new Error(readError(data, `Dream save failed: ${response.status}`));
}

async function getDreamsAuthToken() {
  const existing = getStoredToken() ?? await hydrateStoredToken();
  if (existing) return existing;

  try {
    const response = await fetch(`${getApiBaseUrl()}/auth/dev-token`);
    const data = await readJson(response);
    if (!response.ok || !data || typeof data !== 'object' || !('access_token' in data)) return undefined;
    const token = String((data as { access_token: unknown }).access_token);
    storeAuthToken(token);
    return token;
  } catch {
    return undefined;
  }
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

function parseDraftDreamItem(sourceUrl: string, caption?: string): Omit<DreamItem, 'id' | 'dreamId' | 'sourcePlatform' | 'sourceUrl' | 'createdAt' | 'updatedAt'> {
  const text = `${caption ?? ''} ${sourceUrl}`.toLowerCase();
  const city = findCity(text);
  const country = city?.country ?? findCountry(text);
  const placeName = findLikelyPlaceName(caption);
  const category = inferCategory(text);
  const hasEnoughLocation = Boolean(city || country);
  const needsReview = !placeName || !hasEnoughLocation;

  return {
    category,
    placeName,
    city: city?.city,
    country: city?.country ?? country,
    summary: caption?.trim() ? summarizeCaption(caption) : 'Instagram inspiration saved for review.',
    tags: extractTags(caption),
    confidence: needsReview ? 0.56 : 0.82,
    needsReview,
    status: needsReview ? 'needs_review' : 'parsed',
  };
}

function normalizeSourceUrl(value: string) {
  const trimmed = value.trim();
  if (!trimmed) return 'https://www.instagram.com/';
  return trimmed.startsWith('http') ? trimmed : `https://${trimmed}`;
}

function extractInstagramUrl(value?: string) {
  if (!value) return undefined;
  return value.match(/https?:\/\/(?:www\.)?instagram\.com\/[^\s]+/i)?.[0];
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

const cities = [
  { city: 'Madrid', country: 'Spain' },
  { city: 'Lisbon', country: 'Portugal' },
  { city: 'Tokyo', country: 'Japan' },
  { city: 'Kyoto', country: 'Japan' },
  { city: 'Mexico City', country: 'Mexico' },
  { city: 'Paris', country: 'France' },
  { city: 'Rome', country: 'Italy' },
  { city: 'Cape Town', country: 'South Africa' },
];

function findCity(text: string) {
  return cities.find((entry) => text.includes(entry.city.toLowerCase()));
}

function findCountry(text: string) {
  const countries = ['Spain', 'Portugal', 'Japan', 'Mexico', 'France', 'Italy', 'South Africa', 'Europe'];
  return countries.find((country) => text.includes(country.toLowerCase()));
}

function inferCategory(text: string): DreamItemCategory {
  if (text.includes('restaurant') || text.includes('dinner') || text.includes('food') || text.includes('tortilla')) return 'restaurant';
  if (text.includes('cafe') || text.includes('coffee')) return 'cafe';
  if (text.includes('bar') || text.includes('rooftop') || text.includes('cocktail')) return 'bar';
  if (text.includes('hotel') || text.includes('resort')) return 'hotel';
  if (text.includes('museum')) return 'museum';
  if (text.includes('beach')) return 'beach';
  if (text.includes('hike') || text.includes('tour')) return 'activity';
  if (text.includes('park') || text.includes('mountain')) return 'nature';
  return 'unknown';
}

function findLikelyPlaceName(caption?: string) {
  if (!caption) return undefined;
  const lines = caption.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  const candidate = lines.find((line) => /^[A-Z][A-Za-z0-9 '&.-]{2,42}$/.test(line));
  if (candidate) return candidate;
  const known = ['Casa Dani', 'Table Mountain', 'Sagrada Familia'];
  return known.find((place) => caption.toLowerCase().includes(place.toLowerCase()));
}

function summarizeCaption(caption: string) {
  const clean = caption.replace(/\s+/g, ' ').trim();
  if (clean.length <= 110) return clean;
  return `${clean.slice(0, 107).trim()}...`;
}

function extractTags(caption?: string) {
  if (!caption) return [];
  return Array.from(caption.matchAll(/#([A-Za-z0-9_]+)/g)).map((match) => match[1].toLowerCase()).slice(0, 5);
}
