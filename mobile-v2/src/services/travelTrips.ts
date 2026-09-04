import React from 'react';
import { Linking } from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import type { CountryIconKey, StampShapeKey } from '../components/trotter/stamps/PngStamp';
import { realTravelerProfile, realTravelTrips } from '../data/realTravelSnapshot';
import type { TravelerProfile, TripSummary } from '../data/trotterMock';
import type { TrotterAccent } from '../theme/trotterTheme';
import { requestGoogleAuthToken } from './googleAuth';

type ApiSegment = {
  id: number;
  dep_airport: string;
  arr_airport: string;
  dep_time: string;
  arr_time: string;
  airline?: string | null;
  flight_number?: string | null;
  distance_km?: number | null;
  meta_json?: Record<string, unknown> | string | null;
};

type ApiTrip = {
  id: number;
  title?: string | null;
  start_ts?: string | null;
  end_ts?: string | null;
  segments: ApiSegment[];
};

type AirportInfo = {
  city?: string;
  country_code?: string;
  country_name?: string;
  countryCode?: string;
  countryName?: string;
  latitude?: number;
  longitude?: number;
};

const HOME_AIRPORTS = new Set(['IAH', 'DFW', 'HOU', 'DAL']);
const ACCENTS: TrotterAccent[] = ['red', 'teal', 'mustard', 'blue', 'green'];
const STAMP_COLORS = ['#B6543F', '#2F5E9E', '#52745A', '#9A5A32', '#C79A43'];
const SHAPES: StampShapeKey[] = [
  'roundedImmigrationWithBand',
  'circularCityDoubleLine',
  'archedCountryCanonical',
  'shieldBadgeRounded',
  'roundedImmigrationCanonical',
];

const COUNTRY_ICONS: Record<string, CountryIconKey> = {
  'United States': 'united_states_golden_gate_bridge',
  'Dominican Republic': 'dominican_republic_puerta_del_conde',
  Singapore: 'singapore_marina_bay_sands',
  Mexico: 'mexico_chichen_itza',
  Philippines: 'philippines_mayon_volcano',
  Nicaragua: 'costa_rica_arenal_volcano',
  Ethiopia: 'ethiopia_lalibela_church',
  Morocco: 'morocco_hassan_ii_mosque',
  Spain: 'spain_sagrada_familia',
  Germany: 'germany_brandenburg_gate',
  Japan: 'japan_mount_fuji',
  Taiwan: 'taiwan_taipei_101',
};

const TITLE_COUNTRY_HINTS: Record<string, string> = {
  'dominican republic': 'Dominican Republic',
  singapore: 'Singapore',
  tulum: 'Mexico',
  philippines: 'Philippines',
  nicaragua: 'Nicaragua',
  'ethiopia and somalia': 'Ethiopia',
  'morocco and spain': 'Morocco',
  germany: 'Germany',
};

const TITLE_AIRPORT_HINTS: Record<string, string> = {
  'dominican republic': 'PUJ',
  singapore: 'SIN',
  tulum: 'TQO',
  philippines: 'MNL',
  nicaragua: 'MGA',
  'morocco and spain': 'RAK',
  germany: 'FRA',
};

const US_STATES: Record<string, string> = {
  'Nashville': 'TN',
  'Charlotte': 'NC',
  'Denver': 'CO',
  'Houston': 'TX',
  'Dallas-Fort Worth': 'TX',
  'Dallas': 'TX',
  'Los Angeles': 'CA',
  'Miami': 'FL',
  'New York': 'NY',
  'Washington': 'D.C.',
  'District of Columbia': 'D.C.',
  'Newark': 'NJ',
  'Fort Lauderdale': 'FL',
  'Chicago': 'IL',
  'Phoenix': 'AZ',
  'Orlando': 'FL',
  'San Francisco': 'CA',
  'Seattle': 'WA',
  'Boston': 'MA',
  'Las Vegas': 'NV',
  'Austin': 'TX',
  'Atlanta': 'GA',
  'Dulles': 'VA',
  'Kailua-Kona': 'HI',
  'New Orleans': 'LA',
  'Pensacola': 'FL',
  'Philadelphia': 'PA',
  'Wilmington': 'NC',
  'Valparaiso': 'FL',
};

const COUNTRY_ABBREVIATIONS: Record<string, string> = {
  'Dominican Republic': 'D.R.',
  'United Kingdom': 'UK',
  'United Arab Emirates': 'UAE',
};

const DEFAULT_API_BASE_URL = 'http://localhost:8000';
const CONFIGURED_API_BASE_URL = process.env.EXPO_PUBLIC_TROTTER_API_URL;
const CONFIGURED_AUTH_TOKEN = process.env.EXPO_PUBLIC_TROTTER_AUTH_TOKEN;
let memoryAuthToken: string | undefined;
const AUTH_TOKEN_STORAGE_KEY = 'trotterAuthToken';

export type TravelTripsSource = 'snapshot' | 'api';
export type TravelTripsStatus = 'idle' | 'loading' | 'refreshing' | 'syncing' | 'error';

type TravelTripsContextValue = {
  trips: TripSummary[];
  profile: TravelerProfile;
  source: TravelTripsSource;
  status: TravelTripsStatus;
  error?: string;
  accountEmail?: string;
  lastSyncedAt?: string;
  refresh: () => Promise<void>;
  loadTripDetail: (backendId: number) => Promise<TripSummary | undefined>;
  syncFromGmail: () => Promise<void>;
};

type ImportJobStatus = {
  state?: string;
  scanned_count?: number;
  parsed_count?: number;
  segment_count?: number;
  error_message?: string | null;
  detail?: unknown;
};

const snapshotTrips = realTravelTrips.map(trip => ({
  ...trip,
  title: displayTitle(trip.title, trip.country, trip.countryCode, trip.city)
}));

const TravelTripsContext = React.createContext<TravelTripsContextValue | null>(null);

export function TravelTripsProvider({ children }: { children: React.ReactNode }) {
  const value = useTravelTripsState();
  return React.createElement(TravelTripsContext.Provider, { value }, children);
}

export function useTravelTrips() {
  return React.useContext(TravelTripsContext) ?? useTravelTripsState();
}

function useTravelTripsState(): TravelTripsContextValue {
  const [trips, setTrips] = React.useState<TripSummary[]>(snapshotTrips);
  const [profile, setProfile] = React.useState<TravelerProfile>(realTravelerProfile);
  const [source, setSource] = React.useState<TravelTripsSource>('snapshot');
  const [status, setStatus] = React.useState<TravelTripsStatus>('idle');
  const [error, setError] = React.useState<string | undefined>();
  const [accountEmail, setAccountEmail] = React.useState<string | undefined>();
  const [lastSyncedAt, setLastSyncedAt] = React.useState<string | undefined>();

  const loadTrips = React.useCallback(async (mode: 'loading' | 'refreshing' | 'silent' = 'refreshing') => {
    if (mode !== 'silent') setStatus(mode);
    const token = getStoredToken() ?? await hydrateStoredToken();
    if (!token) {
      if (mode !== 'silent') setStatus('idle');
      setSource('snapshot');
      setAccountEmail(undefined);
      return;
    }

    try {
      const headers = { Authorization: `Bearer ${token}` };
      const [meResponse, response] = await Promise.all([
        fetch(`${getApiBaseUrl()}/auth/me`, { headers }),
        fetch(`${getApiBaseUrl()}/trips`, { headers }),
      ]);
      if (response.status === 401) {
        clearAuthToken();
        setSource('snapshot');
        setAccountEmail(undefined);
        throw new Error('Session expired. Sign in with Google again.');
      }
      if (!meResponse.ok) throw new Error(`Profile API returned ${meResponse.status}`);
      if (!response.ok) throw new Error(`Trips API returned ${response.status}`);
      const me = await meResponse.json() as { email?: string };
      const apiTrips = await response.json() as ApiTrip[];
      if (!Array.isArray(apiTrips)) throw new Error('Trips API returned an unexpected payload.');
      const mappedTrips = mapApiTrips(apiTrips);
      setTrips(mappedTrips);
      setProfile(buildProfile(mappedTrips));
      setSource('api');
      setAccountEmail(me.email);
      setLastSyncedAt(new Date().toISOString());
      setError(undefined);
      if (mode !== 'silent') setStatus('idle');
    } catch (caught) {
      setSource((current) => current === 'api' ? 'api' : 'snapshot');
      setError(caught instanceof Error ? caught.message : String(caught));
      if (mode !== 'silent') setStatus('error');
    }
  }, []);

  React.useEffect(() => {
    loadTrips('loading');
  }, [loadTrips]);

  const loadTripDetail = React.useCallback(async (backendId: number) => {
    const token = getStoredToken() ?? await hydrateStoredToken();
    if (!token) return undefined;
    const response = await authFetch(`/trips/${backendId}`, undefined, token);
    if (response.status === 401) {
      clearAuthToken();
      setSource('snapshot');
      throw new Error('Session expired. Sign in with Google again.');
    }
    const data = await readJson(response) as ApiTrip & { detail?: unknown };
    if (!response.ok) throw new Error(readError(data, `Trip detail failed: ${response.status}`));
    if (!Array.isArray(data.segments)) throw new Error('Trip detail returned an unexpected payload.');

    let mapped: TripSummary | undefined;
    setTrips((current) => {
      const existingIndex = Math.max(0, current.findIndex((trip) => trip.backendId === backendId));
      mapped = mapApiTrip(data, existingIndex);
      const next = current.map((trip) => trip.backendId === backendId ? mapped as TripSummary : trip);
      return next.some((trip) => trip.backendId === backendId) ? next : [...next, mapped as TripSummary];
    });
    setSource('api');
    setLastSyncedAt(new Date().toISOString());
    setError(undefined);
    return mapped;
  }, []);

  React.useEffect(() => {
    const handleUrl = ({ url }: { url: string }) => {
      const token = readTokenFromUrl(url);
      if (!token) return;
      storeAuthToken(token);
      removeTokenFromBrowserUrl(url);
      loadTrips('refreshing');
    };

    const subscription = Linking.addEventListener('url', handleUrl);
    Linking.getInitialURL()
      .then((url) => {
        if (url) handleUrl({ url });
      })
      .catch(() => undefined);
    return () => subscription.remove();
  }, [loadTrips]);

  return {
    trips,
    profile,
    source,
    status,
    error,
    accountEmail,
    lastSyncedAt,
    refresh: () => loadTrips('refreshing'),
    loadTripDetail,
    syncFromGmail: async () => {
      setStatus('syncing');
      try {
        let token = getStoredToken() ?? await hydrateStoredToken();
        if (!token) {
          token = await requestGoogleAuthToken(getApiBaseUrl());
          storeAuthToken(token);
        }
        const importResponse = await authFetch('/ingest/gmail/import', { method: 'POST' }, token);
        if (importResponse.status === 401) {
          clearAuthToken();
          throw new Error('Session expired. Sign in with Google again.');
        }
        const importData = await readJson(importResponse) as { job_id?: string; detail?: unknown };
        if (!importResponse.ok || !importData.job_id) {
          throw new Error(readError(importData, `Import failed: ${importResponse.status}`));
        }
        await waitForImport(importData.job_id, token, async () => {
          await loadTrips('silent');
          setStatus('syncing');
        });
        await loadTrips('refreshing');
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : String(caught));
        setStatus('error');
      }
    },
  };
}

export function getApiBaseUrl() {
  const params = getUrlParams();
  const configured = params.get('apiUrl') || CONFIGURED_API_BASE_URL;
  if (configured) return configured.replace(/\/$/, '');
  return DEFAULT_API_BASE_URL;
}

function removeTokenFromBrowserUrl(url: string) {
  const browser = globalThis as typeof globalThis & {
    history?: { replaceState: (data: unknown, unused: string, url?: string | URL | null) => void };
    location?: { origin?: string };
  };
  if (!browser.history || !browser.location?.origin) return;
  try {
    const parsed = new URL(url);
    const fragmentParams = new URLSearchParams(parsed.hash.replace(/^#/, ''));
    const hasToken = parsed.searchParams.has('token') || fragmentParams.has('token');
    if (parsed.origin !== browser.location.origin || !hasToken) return;
    parsed.searchParams.delete('token');
    fragmentParams.delete('token');
    parsed.hash = fragmentParams.toString() ? `#${fragmentParams}` : '';
    browser.history.replaceState({}, '', `${parsed.pathname}${parsed.search}${parsed.hash}`);
  } catch {
    // Native deep links do not need browser history cleanup.
  }
}

export function getStoredToken() {
  const params = getUrlParams();
  const token = params.get('token') || CONFIGURED_AUTH_TOKEN;
  const storage = getLocalStorage();
  if (token) {
    storeAuthToken(token);
    return token;
  }
  return storage?.getItem(AUTH_TOKEN_STORAGE_KEY) ?? memoryAuthToken;
}

export function storeAuthToken(token: string) {
  memoryAuthToken = token;
  getLocalStorage()?.setItem(AUTH_TOKEN_STORAGE_KEY, token);
  AsyncStorage.setItem(AUTH_TOKEN_STORAGE_KEY, token).catch(() => undefined);
}

export function clearAuthToken() {
  memoryAuthToken = undefined;
  getLocalStorage()?.removeItem(AUTH_TOKEN_STORAGE_KEY);
  AsyncStorage.removeItem(AUTH_TOKEN_STORAGE_KEY).catch(() => undefined);
}

export async function hydrateStoredToken() {
  if (memoryAuthToken) return memoryAuthToken;
  const webToken = getLocalStorage()?.getItem(AUTH_TOKEN_STORAGE_KEY);
  if (webToken) return webToken;
  try {
    const token = await AsyncStorage.getItem(AUTH_TOKEN_STORAGE_KEY);
    if (token) memoryAuthToken = token;
    return token ?? undefined;
  } catch {
    return undefined;
  }
}

function getUrlParams() {
  const location = (globalThis as { location?: { search?: string; hash?: string } }).location;
  const params = new URLSearchParams(location?.search ?? '');
  const fragmentParams = new URLSearchParams(location?.hash?.replace(/^#/, '') ?? '');
  fragmentParams.forEach((value, key) => {
    if (!params.has(key)) params.set(key, value);
  });
  return params;
}

function getLocalStorage() {
  return (globalThis as { localStorage?: Storage }).localStorage;
}

function readTokenFromUrl(url: string) {
  try {
    const parsed = new URL(url);
    return parsed.searchParams.get('token')
      ?? new URLSearchParams(parsed.hash.replace(/^#/, '')).get('token')
      ?? undefined;
  } catch {
    const match = /[?&#]token=([^&#]+)/.exec(url);
    return match ? decodeURIComponent(match[1]) : undefined;
  }
}

async function authFetch(path: string, init: RequestInit | undefined, token: string) {
  return fetch(`${getApiBaseUrl()}${path}`, {
    ...init,
    headers: {
      ...(init?.headers ?? {}),
      Authorization: `Bearer ${token}`,
    },
  });
}

async function waitForImport(jobId: string, token: string, onProgress?: (status: ImportJobStatus) => Promise<void>) {
  let lastObservedParsed = -1;
  let lastObservedSegments = -1;
  for (let attempt = 0; attempt < 180; attempt += 1) {
    const response = await authFetch(`/ingest/jobs/${jobId}`, undefined, token);
    if (response.status === 401) {
      clearAuthToken();
      throw new Error('Session expired. Sign in with Google again.');
    }
    const data = await readJson(response) as ImportJobStatus;
    if (!response.ok) throw new Error(readError(data, `Job status failed: ${response.status}`));
    const parsedCount = data.parsed_count ?? 0;
    const segmentCount = data.segment_count ?? 0;
    const discoveredMoreTrips = parsedCount > lastObservedParsed || segmentCount > lastObservedSegments;
    lastObservedParsed = Math.max(lastObservedParsed, parsedCount);
    lastObservedSegments = Math.max(lastObservedSegments, segmentCount);
    if (discoveredMoreTrips && (parsedCount > 0 || segmentCount > 0)) {
      await onProgress?.(data);
    }
    if (data.state === 'done' || data.state === 'completed' || data.state === 'success') return;
    if (data.state === 'failed' || data.state === 'error') throw new Error(data.error_message || 'Gmail import failed.');
    await delay(2000);
  }
  throw new Error('Gmail import did not finish before the sync timeout.');
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

function delay(ms: number) {
  return new Promise<void>((resolve) => setTimeout(resolve, ms));
}

function mapApiTrips(apiTrips: ApiTrip[]): TripSummary[] {
  return apiTrips
    .filter((trip) => Array.isArray(trip.segments) && trip.segments.length > 0)
    .map((trip, index) => mapApiTrip(trip, index));
}

function mapApiTrip(trip: ApiTrip, index: number): TripSummary {
  const segments = [...trip.segments].sort((a, b) => dateMs(a.dep_time) - dateMs(b.dep_time) || a.id - b.id);
  const destination = pickDestination(trip.title, segments);
  const country = destination.info.country_name ?? destination.info.countryName ?? countryHint(trip.title) ?? trip.title ?? 'United States';
  const countryCode = destination.info.country_code ?? destination.info.countryCode ?? (country === 'United States' ? 'US' : undefined);
  const city = cleanCity(destination.info.city) || trip.title || undefined;
  const startDate = toDateOnly(trip.start_ts ?? segments[0].dep_time);
  const endDate = toDateOnly(trip.end_ts ?? segments[segments.length - 1].arr_time);
  const airlines = new Set(segments.map((segment) => segment.airline).filter(Boolean));
  const isDomestic = countryCode === 'US';
  const shape = isDomestic ? 'shieldBadgeRounded' : SHAPES[index % SHAPES.length];
  const color = isDomestic ? '#52745A' : STAMP_COLORS[index % STAMP_COLORS.length];

  return {
    id: `api-trip-${trip.id}`,
    backendId: trip.id,
    title: displayTitle(trip.title, country, countryCode, city),
    country,
    countryCode,
    city,
    airportCode: destination.airport,
    startDate,
    endDate,
    firstCountryEntryDate: toDateOnly(destination.date),
    routeLabel: routeLabelFor(segments, destination.airport),
    miles: Math.round(segments.reduce((sum, segment) => sum + (segment.distance_km ?? 0), 0) * 0.621371),
    flightCount: segments.length,
    airlineCount: airlines.size,
    airlines: Array.from(airlines).sort() as string[],
    airports: uniqueAirports(segments),
    segments: segments.map(mapApiSegment),
    accent: ACCENTS[index % ACCENTS.length],
    stamp: {
      shape,
      icon: COUNTRY_ICONS[country] ?? 'united_states_golden_gate_bridge',
      color,
      country,
      city,
      airportCode: destination.airport,
      date: toDateOnly(destination.date),
      footer: isDomestic ? 'DOMESTIC' : 'FIRST VISIT',
    },
  };
}

function mapApiSegment(segment: ApiSegment) {
  const meta = parseMeta(segment.meta_json);
  const confidence = typeof meta.confidence === 'number' ? meta.confidence : undefined;
  const departure = airportInfo(segment, 'departure');
  const arrival = airportInfo(segment, 'arrival');
  return {
    id: `api-segment-${segment.id}`,
    mode: 'flight' as const,
    depAirport: segment.dep_airport,
    arrAirport: segment.arr_airport,
    depTime: segment.dep_time,
    arrTime: segment.arr_time,
    airline: segment.airline ?? undefined,
    flightNumber: readFlightNumber(segment),
    distanceMiles: typeof segment.distance_km === 'number' ? Math.round(segment.distance_km * 0.621371) : undefined,
    confidence,
    depPoint: routePoint(segment.dep_airport, departure),
    arrPoint: routePoint(segment.arr_airport, arrival),
  };
}

function routePoint(code: string, info: AirportInfo) {
  if (typeof info.latitude !== 'number' || typeof info.longitude !== 'number') return undefined;
  return {
    code,
    city: cleanCity(info.city) || code,
    lat: info.latitude,
    lon: info.longitude,
  };
}

function readFlightNumber(segment: ApiSegment) {
  const value = (segment as ApiSegment & { flight_number?: string | null }).flight_number;
  return value ?? undefined;
}

function uniqueAirports(segments: ApiSegment[]) {
  const seen = new Set<string>();
  const airports: string[] = [];
  for (const segment of segments) {
    for (const code of [segment.dep_airport, segment.arr_airport]) {
      if (!code || seen.has(code)) continue;
      seen.add(code);
      airports.push(code);
    }
  }
  return airports;
}

function pickDestination(title: string | null | undefined, segments: ApiSegment[]) {
  const key = normalizeTitle(title);
  const airportHint = TITLE_AIRPORT_HINTS[key];
  const country = TITLE_COUNTRY_HINTS[key];
  const candidates = segments.flatMap((segment) => [
    {
      segment,
      side: 'arrival' as const,
      airport: segment.arr_airport,
      date: segment.arr_time,
      info: airportInfo(segment, 'arrival'),
    },
    {
      segment,
      side: 'departure' as const,
      airport: segment.dep_airport,
      date: segment.dep_time,
      info: airportInfo(segment, 'departure'),
    },
  ]);
  const first = segments[0];
  const last = segments[segments.length - 1];
  const openEndedFinal = last?.arr_airport
    && last.arr_airport !== first?.dep_airport
    && !HOME_AIRPORTS.has(last.arr_airport)
    ? candidates.find((candidate) => candidate.side === 'arrival' && candidate.airport === last.arr_airport)
    : undefined;

  return (
    candidates.find((candidate) => candidate.airport === airportHint) ??
    candidates.find((candidate) => candidate.info.country_name === country && !HOME_AIRPORTS.has(candidate.airport)) ??
    openEndedFinal ??
    candidates.find((candidate) => !HOME_AIRPORTS.has(candidate.airport)) ??
    candidates[0]
  );
}

function routeLabelFor(segments: ApiSegment[], destinationAirport: string) {
  const first = segments[0];
  const last = segments[segments.length - 1];
  if (first.dep_airport === destinationAirport && HOME_AIRPORTS.has(first.arr_airport)) {
    return `${first.dep_airport} -> ${first.arr_airport}`;
  }
  if (HOME_AIRPORTS.has(first.dep_airport)) {
    return `${first.dep_airport} -> ${destinationAirport}`;
  }
  if (last.arr_airport && last.arr_airport !== destinationAirport) {
    return `${first.dep_airport} -> ${last.arr_airport}`;
  }
  return `${first.dep_airport} -> ${destinationAirport}`;
}

function airportInfo(segment: ApiSegment, side: 'departure' | 'arrival'): AirportInfo {
  const meta = parseMeta(segment.meta_json);
  const airports = readObject(readObject(meta.enrichment).airports);
  return readObject(airports[side]) as AirportInfo;
}

function parseMeta(raw: ApiSegment['meta_json']): Record<string, unknown> {
  if (!raw) return {};
  if (typeof raw === 'object') return raw;
  try {
    return JSON.parse(raw) as Record<string, unknown>;
  } catch {
    return {};
  }
}

function readObject(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' ? (value as Record<string, unknown>) : {};
}

function buildProfile(trips: TripSummary[]): TravelerProfile {
  const flights = trips.reduce((sum, trip) => sum + trip.flightCount, 0);
  const miles = trips.reduce((sum, trip) => sum + trip.miles, 0);
  const countries = new Set(trips.map((trip) => trip.country).filter(Boolean)).size;
  const airports = new Set(
    trips
      .flatMap((trip) => trip.airports ?? trip.routeLabel.split('->').map((part) => part.trim()))
      .concat(trips.map((trip) => trip.airportCode ?? ''))
      .filter(Boolean)
  ).size;
  const airlineCodes = new Set(trips.flatMap((trip) => trip.airlines ?? []));
  const airlines = airlineCodes.size || trips.reduce((max, trip) => Math.max(max, trip.airlineCount), 0);

  return {
    ...realTravelerProfile,
    flights,
    countries,
    airports,
    airlines,
    miles,
  };
}

function normalizeTitle(title?: string | null) {
  return (title ?? '').trim().toLowerCase();
}

function countryHint(title?: string | null) {
  return TITLE_COUNTRY_HINTS[normalizeTitle(title)];
}

function displayTitle(title: string | null | undefined, country: string, countryCode?: string, city?: string) {
  const cleanTitle = title?.trim();
  const primaryName = (city && city.toLowerCase() !== country.toLowerCase()) ? city : (cleanTitle || country);

  if (countryCode === 'US') {
    const state = US_STATES[primaryName] || (primaryName === cleanTitle ? US_STATES[cleanTitle || ''] : undefined);
    if (state) return `${primaryName}, ${state}`;
    return primaryName;
  }

  const displayCountry = COUNTRY_ABBREVIATIONS[country] || country;

  if (primaryName.toLowerCase() === country.toLowerCase()) return displayCountry;
  if (primaryName.toLowerCase().includes(country.toLowerCase())) return primaryName;

  return `${primaryName}, ${displayCountry}`;
}

function cleanCity(value: unknown) {
  return String(value ?? '').replace(/\s*\([^)]*\)/g, '').trim();
}

function toDateOnly(value?: string | null) {
  return String(value ?? '').split('T')[0].split(' ')[0];
}

function dateMs(value?: string | null) {
  const parsed = new Date(value ?? '').getTime();
  return Number.isNaN(parsed) ? 0 : parsed;
}
