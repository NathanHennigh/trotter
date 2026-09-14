import React from 'react';
import { Platform } from 'react-native';
import * as SecureStore from 'expo-secure-store';
import AsyncStorage from '@react-native-async-storage/async-storage';
import type { CountryIconKey } from '../components/trotter/stamps/PngStamp';
import { stampIdentity } from '../components/trotter/stamps/stampIdentity';
import type { TravelerProfile, TripSummary } from '../data/trotterMock';
import type { TrotterAccent } from '../theme/trotterTheme';
import { firstCountryEntry } from '../utils/countryArrivals';
import { buildPassportArrivals } from '../components/world-window/passport/passport-arrivals';
import { travelCountry, SOMALILAND_ICON_KEY } from '../utils/travelCountry';
import { groupTripItineraries } from '../utils/tripItineraries';
import { cancelGoogleAuthSession, consumeWebOAuthCallback, GoogleSignInCanceled, requestGoogleAuthToken } from './googleAuth';

type ApiSegment = {
  id: number;
  dep_airport: string;
  arr_airport: string;
  dep_time: string;
  arr_time: string;
  airline?: string | null;
  flight_number?: string | null;
  pnr?: string | null;
  distance_km?: number | null;
  meta_json?: Record<string, unknown> | string | null;
};

type ApiTrip = {
  id: number;
  title?: string | null;
  start_ts?: string | null;
  end_ts?: string | null;
  destination_airport?: string | null;
  route_label?: string | null;
  segments: ApiSegment[];
};

type AirportInfo = {
  name?: string;
  city?: string;
  country_code?: string;
  country_name?: string;
  countryCode?: string;
  countryName?: string;
  latitude?: number;
  longitude?: number;
};

const ACCENTS: TrotterAccent[] = ['red', 'teal', 'mustard', 'blue', 'green'];
const COUNTRY_ICONS: Record<string, CountryIconKey> = {
  'United States': 'united_states_golden_gate_bridge',
  Somaliland: SOMALILAND_ICON_KEY,
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

const AUTH_TOKEN_STORAGE_KEY = 'trotter.auth.v2';
const LEGACY_TOKEN_STORAGE_KEY = 'trotterAuthToken';
let memoryAuthToken: string | undefined;
let authRevision = 0;
let storageQueue: Promise<unknown> = Promise.resolve();
const authListeners = new Set<() => void>();

export type TravelTripsSource = 'api';
export type TravelTripsStatus = 'idle' | 'loading' | 'refreshing' | 'syncing' | 'error';
export type TravelAuthStatus = 'loading' | 'signed-out' | 'signed-in';
type AccountIdentity = { user_id: number; email: string; name?: string | null };
type TravelTripsContextValue = {
  trips: TripSummary[];
  profile: TravelerProfile;
  source: TravelTripsSource;
  status: TravelTripsStatus;
  authStatus: TravelAuthStatus;
  error?: string;
  accountId?: number;
  accountEmail?: string;
  lastSyncedAt?: string;
  signIn: () => Promise<void>;
  signOut: () => Promise<void>;
  refresh: () => Promise<void>;
  loadTripDetail: (backendId: number) => Promise<TripSummary | undefined>;
  syncFromGmail: () => Promise<void>;
};

type ImportJobStatus = {
  state?: string;
  parsed_count?: number;
  segment_count?: number;
  error_message?: string | null;
  detail?: unknown;
};

const TravelTripsContext = React.createContext<TravelTripsContextValue | null>(null);
export function TravelTripsProvider({ children }: { children: React.ReactNode }) {
  return React.createElement(TravelTripsContext.Provider, { value: useTravelTripsState() }, children);
}
export function useTravelTrips() {
  const context = React.useContext(TravelTripsContext);
  if (!context) throw new Error('useTravelTrips requires TravelTripsProvider');
  return context;
}

function useTravelTripsState(): TravelTripsContextValue {
  const [trips, setTrips] = React.useState<TripSummary[]>([]);
  const [account, setAccount] = React.useState<AccountIdentity>();
  const [authStatus, setAuthStatus] = React.useState<TravelAuthStatus>('loading');
  const [status, setStatus] = React.useState<TravelTripsStatus>('loading');
  const [error, setError] = React.useState<string>();
  const [lastSyncedAt, setLastSyncedAt] = React.useState<string>();
  const tripsRef = React.useRef(trips);
  tripsRef.current = trips;
  const accountRef = React.useRef<AccountIdentity | undefined>(undefined);
  const mounted = React.useRef(true);
  const requestSequence = React.useRef(0);
  const authAttempt = React.useRef(0);
  const syncRunning = React.useRef(false);
  const current = (revision: number) => mounted.current && revision === getAuthRevision();
  const resetAccount = React.useCallback(() => {
    accountRef.current = undefined;
    setAccount(undefined);
    setTrips([]);
    setLastSyncedAt(undefined);
  }, []);

  const loadTrips = React.useCallback(async (mode: 'loading' | 'refreshing' | 'silent' = 'refreshing') => {
    const token = getStoredToken();
    const revision = getAuthRevision();
    const sequence = ++requestSequence.current;
    const relevant = () => current(revision) && sequence === requestSequence.current;
    if (!token) {
      resetAccount();
      setAuthStatus('signed-out');
      setStatus('idle');
      return;
    }
    if (mode !== 'silent') setStatus(mode);
    try {
      const [meResponse, tripsResponse] = await Promise.all([
        authFetch('/auth/me', undefined, token), authFetch('/trips', undefined, token),
      ]);
      if (!relevant()) return;
      if (meResponse.status === 401 || tripsResponse.status === 401) {
        await clearAuthToken();
        if (mounted.current && !getStoredToken()) setError('Your session expired. Sign in with Google again.');
        return;
      }
      const me = await readJson(meResponse) as AccountIdentity;
      if (!relevant()) return;
      if (!meResponse.ok || !Number.isInteger(me.user_id) || !me.email) {
        throw new Error('Your account could not be verified. Please try again.');
      }
      // /auth/me is authoritative; no bundled traveler is ever a fallback.
      if (accountRef.current && accountRef.current.user_id !== me.user_id) setTrips([]);
      accountRef.current = me;
      setAccount(me);
      setAuthStatus('signed-in');
      const payload = await readJson(tripsResponse);
      if (!relevant()) return;
      if (!tripsResponse.ok) throw new Error(`Your trips could not be loaded (${tripsResponse.status}). Pull to retry.`);
      if (!Array.isArray(payload)) throw new Error('Trips returned an unexpected response. Please retry.');
      setTrips(mapApiTrips(payload as ApiTrip[]));
      setLastSyncedAt(new Date().toISOString());
      setError(undefined);
      if (mode !== 'silent') setStatus('idle');
    } catch (caught) {
      if (!relevant()) return;
      setError(friendlyError(caught));
      setStatus('error');
      if (!accountRef.current) setAuthStatus('signed-out');
    }
  }, [resetAccount]);

  React.useEffect(() => {
    mounted.current = true;
    const unsubscribe = subscribeAuthToken(() => {
      if (!mounted.current) return;
      requestSequence.current += 1;
      resetAccount();
      setError(undefined);
      setAuthStatus(getStoredToken() ? 'loading' : 'signed-out');
      setStatus(getStoredToken() ? 'loading' : 'idle');
      if (getStoredToken()) void loadTrips('loading');
    });
    void (async () => {
      const before = getAuthRevision();
      try {
        const callback = consumeWebOAuthCallback();
        if (callback) await storeAuthToken(callback);
        else await hydrateStoredToken();
        if (mounted.current && before === getAuthRevision()) await loadTrips('loading');
      } catch (caught) {
        if (!mounted.current) return;
        resetAccount();
        setAuthStatus('signed-out');
        setStatus('error');
        setError(friendlyError(caught));
      }
    })();
    return () => { mounted.current = false; unsubscribe(); };
  }, [loadTrips, resetAccount]);

  const signIn = React.useCallback(async () => {
    const attempt = ++authAttempt.current;
    setError(undefined);
    setAuthStatus('loading');
    setStatus('loading');
    try {
      const token = await requestGoogleAuthToken(getApiBaseUrl());
      if (!mounted.current || attempt !== authAttempt.current) return;
      await storeAuthToken(token);
      // The token-change listener verifies the account before opening its UI.
    } catch (caught) {
      if (!mounted.current || attempt !== authAttempt.current) return;
      setAuthStatus(accountRef.current ? 'signed-in' : 'signed-out');
      setStatus(caught instanceof GoogleSignInCanceled ? 'idle' : 'error');
      setError(caught instanceof GoogleSignInCanceled ? undefined : friendlyError(caught));
    }
  }, []);

  const signOut = React.useCallback(async () => {
    authAttempt.current += 1;
    cancelGoogleAuthSession();
    resetAccount();
    setAuthStatus('signed-out');
    setStatus('idle');
    setError(undefined);
    try { await clearAuthToken(); }
    catch { if (mounted.current) setError('Could not clear saved sign-in. Please try signing out again.'); }
  }, [resetAccount]);

  const loadTripDetail = React.useCallback(async (backendId: number) => {
    const token = getStoredToken();
    const revision = getAuthRevision();
    if (!token || !accountRef.current) return undefined;
    const response = await authFetch(`/trips/${backendId}`, undefined, token);
    if (!current(revision)) return undefined;
    if (response.status === 401) {
      await clearAuthToken();
      if (mounted.current && !getStoredToken()) setError('Your session expired. Sign in with Google again.');
      return undefined;
    }
    const data = await readJson(response) as ApiTrip;
    if (!current(revision)) return undefined;
    if (!response.ok || !Array.isArray(data.segments) || data.id !== backendId) {
      throw new Error('This trip could not be loaded. Please retry.');
    }
    if (!data.segments.length) return undefined;
    const existingIndex = Math.max(0, tripsRef.current.findIndex(trip => trip.backendId === backendId));
    const mapped = mapApiTrip(data, existingIndex);
    setTrips(existing => existing.some(trip => trip.backendId === backendId)
      ? existing.map(trip => trip.backendId === backendId ? mapped : trip) : [...existing, mapped]);
    setError(undefined);
    setLastSyncedAt(new Date().toISOString());
    return mapped;
  }, []);

  const syncFromGmail = React.useCallback(async () => {
    const token = getStoredToken();
    const revision = getAuthRevision();
    if (syncRunning.current || !token || !accountRef.current) return;
    syncRunning.current = true;
    setStatus('syncing');
    setError(undefined);
    try {
      const response = await authFetch('/ingest/gmail/import', { method: 'POST' }, token);
      if (!current(revision)) return;
      if (response.status === 401) throw new SessionExpired();
      const data = await readJson(response) as { job_id?: string; detail?: unknown };
      if (!current(revision)) return;
      if (!response.ok || !data.job_id) throw new Error(readError(data, 'Gmail sync could not start. Please retry.'));
      await waitForImport(data.job_id, token, () => current(revision), async () => {
        await loadTrips('silent');
        if (current(revision)) setStatus('syncing');
      });
      if (current(revision)) await loadTrips('refreshing');
    } catch (caught) {
      if (!current(revision)) return;
      if (caught instanceof SessionExpired) {
        await clearAuthToken();
        if (mounted.current && !getStoredToken()) setError('Your session expired. Sign in with Google again.');
      } else {
        setError(friendlyError(caught));
        setStatus('error');
      }
    } finally { syncRunning.current = false; }
  }, [loadTrips]);

  return { trips, profile: buildProfile(trips, account), source: 'api', status, authStatus,
    error, accountId: account?.user_id, accountEmail: account?.email, lastSyncedAt,
    signIn, signOut, refresh: () => loadTrips('refreshing'), loadTripDetail, syncFromGmail };
}

export function getApiBaseUrl() {
  const configured = process.env.EXPO_PUBLIC_TROTTER_API_URL?.trim();
  const development = typeof __DEV__ !== 'undefined' && __DEV__;
  if (!configured && !development) throw new Error('This app is missing its server address. Install the latest Trotter build.');
  const value = (configured || 'http://localhost:8000').replace(/\/+$/, '');
  const url = new URL(value);
  if (url.username || url.password || url.search || url.hash || (url.protocol !== 'https:' && !(development && url.protocol === 'http:'))) {
    throw new Error('Trotter requires a secure server address.');
  }
  // URL parameters and embedded build-time bearer tokens cannot switch accounts.
  return value;
}

export function getStoredToken() { return memoryAuthToken; }
export function getAuthRevision() { return authRevision; }
export function subscribeAuthToken(listener: () => void) {
  authListeners.add(listener);
  return () => { authListeners.delete(listener); };
}
function changeMemoryToken(token?: string) {
  memoryAuthToken = token;
  authRevision += 1;
  for (const listener of authListeners) listener();
}
function queueStorage(operation: () => Promise<void>) {
  const pending = storageQueue.then(operation, operation);
  storageQueue = pending.catch(() => undefined);
  return pending;
}
function browserStorage(kind: 'sessionStorage' | 'localStorage') {
  try { return (globalThis as unknown as Record<string, Storage | undefined>)[kind]; }
  catch { return undefined; }
}
async function purgeLegacyToken() {
  browserStorage('localStorage')?.removeItem(LEGACY_TOKEN_STORAGE_KEY);
  await AsyncStorage.removeItem(LEGACY_TOKEN_STORAGE_KEY);
}
export async function storeAuthToken(token: string) {
  if (!token || /\s/.test(token)) throw new Error('Invalid sign-in token.');
  const serialized = JSON.stringify({ token, apiBaseUrl: getApiBaseUrl() });
  changeMemoryToken(token);
  try {
    await queueStorage(async () => {
      if (Platform.OS === 'web') {
        const storage = browserStorage('sessionStorage');
        if (!storage) throw new Error('Session storage is unavailable.');
        storage.setItem(AUTH_TOKEN_STORAGE_KEY, serialized);
      } else {
        await SecureStore.setItemAsync(AUTH_TOKEN_STORAGE_KEY, serialized, { keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY });
      }
      await purgeLegacyToken();
    });
  } catch {
    if (memoryAuthToken === token) changeMemoryToken(undefined);
    throw new Error('Your sign-in could not be saved securely. Please try again.');
  }
}
export function clearAuthToken() {
  // Invalidate outstanding API responses before asynchronous storage work.
  changeMemoryToken(undefined);
  return queueStorage(async () => {
    if (Platform.OS === 'web') browserStorage('sessionStorage')?.removeItem(AUTH_TOKEN_STORAGE_KEY);
    else await SecureStore.deleteItemAsync(AUTH_TOKEN_STORAGE_KEY);
    await purgeLegacyToken();
  });
}
export async function hydrateStoredToken() {
  if (memoryAuthToken) return memoryAuthToken;
  const revision = getAuthRevision();
  await storageQueue;
  const raw = Platform.OS === 'web' ? browserStorage('sessionStorage')?.getItem(AUTH_TOKEN_STORAGE_KEY)
    : await SecureStore.getItemAsync(AUTH_TOKEN_STORAGE_KEY);
  await purgeLegacyToken();
  if (revision !== getAuthRevision()) return memoryAuthToken;
  if (!raw) return undefined;
  try {
    const value = JSON.parse(raw) as { token?: string; apiBaseUrl?: string };
    if (typeof value.token !== 'string' || !value.token || value.apiBaseUrl !== getApiBaseUrl()) {
      await clearAuthToken();
      return undefined;
    }
    changeMemoryToken(value.token);
    return value.token;
  } catch { await clearAuthToken(); return undefined; }
}

class SessionExpired extends Error {}
async function authFetch(path: string, init: RequestInit | undefined, token: string) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 30000);
  try {
    return await fetch(`${getApiBaseUrl()}${path}`, { ...init, signal: controller.signal,
      headers: { ...(init?.headers ?? {}), Authorization: `Bearer ${token}` } });
  } finally { clearTimeout(timeout); }
}
async function waitForImport(jobId: string, token: string, isCurrent: () => boolean, onProgress: () => Promise<void>) {
  let parsed = -1;
  let segments = -1;
  for (let attempt = 0; attempt < 180 && isCurrent(); attempt += 1) {
    const response = await authFetch(`/ingest/jobs/${jobId}`, undefined, token);
    if (!isCurrent()) return;
    if (response.status === 401) throw new SessionExpired();
    const data = await readJson(response) as ImportJobStatus;
    if (!isCurrent()) return;
    if (!response.ok) throw new Error(readError(data, 'Sync progress could not be loaded. Your import continues on the server.'));
    if ((data.parsed_count ?? 0) > parsed || (data.segment_count ?? 0) > segments) {
      parsed = data.parsed_count ?? 0;
      segments = data.segment_count ?? 0;
      if (parsed > 0 || segments > 0) await onProgress();
    }
    if (['done', 'completed', 'success'].includes(data.state ?? '')) return;
    if (['failed', 'error'].includes(data.state ?? '')) throw new Error(data.error_message || 'Gmail sync failed. Please retry.');
    await new Promise(resolve => setTimeout(resolve, 2000));
  }
  if (isCurrent()) throw new Error('Your import is still running on the server. Refresh your trips in a moment.');
}
async function readJson(response: Response) {
  const text = await response.text();
  if (!text) return {};
  try { return JSON.parse(text) as unknown; } catch { return {}; }
}
function readError(data: unknown, fallback: string) {
  if (data && typeof data === 'object' && 'detail' in data && typeof data.detail === 'string') return data.detail;
  return fallback;
}
function friendlyError(caught: unknown) {
  if (caught instanceof Error && caught.name !== 'TypeError' && caught.name !== 'AbortError') return caught.message;
  return 'Trotter could not reach the server. Check your connection and try again.';
}

function mapApiTrips(apiTrips: ApiTrip[]): TripSummary[] {
  return apiTrips
    .filter((trip) => Array.isArray(trip.segments) && trip.segments.length > 0)
    .map((trip, index) => mapApiTrip(trip, index));
}

function mapApiTrip(trip: ApiTrip, index: number): TripSummary {
  const segments = [...trip.segments].sort((a, b) => dateMs(a.dep_time) - dateMs(b.dep_time) || a.id - b.id);
  const mappedSegments = segments.map(mapApiSegment);
  const itineraryCount = groupTripItineraries(mappedSegments).length;
  const destination = pickDestination(trip.title, segments, trip.destination_airport);
  const rawCountry = destination.info.country_name ?? destination.info.countryName ?? countryHint(trip.title) ?? trip.title ?? 'United States';
  const { country, countryCode, travelCountryKey } = travelCountry(rawCountry, destination.info.country_code ?? destination.info.countryCode ?? (rawCountry === 'United States' ? 'US' : undefined), destination.airport);
  const entry = firstCountryEntry(segments.map((segment) => {
    const info = airportInfo(segment, 'arrival');
    return { airportCode: segment.arr_airport, date: segment.arr_time, country: info.country_name ?? info.countryName, countryCode: info.country_code ?? info.countryCode };
  }), country, countryCode);
  const entryAirport = entry?.airportCode ?? destination.airport;
  const entryDate = toDateOnly(entry?.date ?? destination.date);
  const city = cleanCity(destination.info.city) || trip.title || undefined;
  const startDate = toDateOnly(trip.start_ts ?? segments[0].dep_time);
  const endDate = toDateOnly(trip.end_ts ?? segments[segments.length - 1].arr_time);
  const airlines = new Set(segments.map((segment) => segment.airline).filter(Boolean));
  const isDomestic = countryCode === 'US';
  const { shape, color } = stampIdentity(country, countryCode);

  return {
    id: `api-trip-${trip.id}`,
    backendId: trip.id,
    title: displayTitle(trip.title, country, countryCode, city),
    country,
    countryCode,
    travelCountryKey,
    city,
    airportCode: destination.airport,
    startDate,
    endDate,
    firstCountryEntryDate: entryDate,
    firstCountryEntryAirport: entryAirport,
    routeLabel: trip.route_label?.trim() || routeLabelFor(segments, destination.airport),
    miles: Math.round(segments.reduce((sum, segment) => sum + (segment.distance_km ?? 0), 0) * 0.621371),
    flightCount: segments.length,
    itineraryCount,
    airlineCount: airlines.size,
    airlines: Array.from(airlines).sort() as string[],
    airports: uniqueAirports(segments),
    segments: mappedSegments,
    accent: ACCENTS[index % ACCENTS.length],
    stamp: {
      shape,
      icon: COUNTRY_ICONS[country] ?? '',
      color,
      country,
      city,
      airportCode: entryAirport,
      date: entryDate,
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
    depCountry: departure.country_name ?? departure.countryName,
    depCountryCode: departure.country_code ?? departure.countryCode,
    arrCountry: arrival.country_name ?? arrival.countryName,
    arrCountryCode: arrival.country_code ?? arrival.countryCode,
    depTime: segment.dep_time,
    arrTime: segment.arr_time,
    airline: segment.airline ?? undefined,
    flightNumber: readFlightNumber(segment),
    bookingReference: segment.pnr ?? undefined,
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
    country: info.country_name ?? info.countryName,
    countryCode: info.country_code ?? info.countryCode,
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

function pickDestination(
  title: string | null | undefined,
  segments: ApiSegment[],
  preferredAirport?: string | null,
) {
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
  const preferred = preferredAirport
    ? candidates.find((candidate) => candidate.side === 'arrival' && candidate.airport === preferredAirport)
      ?? candidates.find((candidate) => candidate.airport === preferredAirport)
    : undefined;
  const titleMatch = candidates.find((candidate) => (
    candidate.side === 'arrival' && candidateMatchesTitle(candidate, key)
  )) ?? candidates.find((candidate) => candidateMatchesTitle(candidate, key));
  const longestStay = longestStayDestination(segments, candidates);
  const openEndedFinal = last?.arr_airport
    && !airportsShareMetro(first?.dep_airport, last.arr_airport, candidates)
    ? candidates.find((candidate) => candidate.side === 'arrival' && candidate.airport === last.arr_airport)
    : undefined;

  return (
    preferred ??
    candidates.find((candidate) => candidate.airport === airportHint) ??
    titleMatch ??
    candidates.find((candidate) => candidateCountry(candidate) === country && candidate.airport !== first?.dep_airport) ??
    longestStay ??
    openEndedFinal ??
    candidates.find((candidate) => candidate.side === 'arrival' && candidate.airport !== first?.dep_airport) ??
    candidates[0]
  );
}

function routeLabelFor(segments: ApiSegment[], destinationAirport: string) {
  const first = segments[0];
  const last = segments[segments.length - 1];
  if (first.dep_airport === destinationAirport && last.arr_airport !== destinationAirport) {
    return `${first.dep_airport} -> ${last.arr_airport}`;
  }
  return `${first.dep_airport} -> ${destinationAirport}`;
}

type DestinationCandidate = {
  segment: ApiSegment;
  side: 'arrival' | 'departure';
  airport: string;
  date: string;
  info: AirportInfo;
};

function candidateMatchesTitle(candidate: DestinationCandidate, normalizedTitle: string) {
  if (!normalizedTitle) return false;
  return [candidate.info.city, candidate.info.name, candidateCountry(candidate)]
    .map(normalizePlaceName)
    .filter((value) => value.length >= 3)
    .some((value) => value === normalizedTitle || value.includes(normalizedTitle) || normalizedTitle.includes(value));
}

function candidateCountry(candidate: DestinationCandidate) {
  return candidate.info.country_name ?? candidate.info.countryName;
}

function longestStayDestination(segments: ApiSegment[], candidates: DestinationCandidate[]) {
  let best: DestinationCandidate | undefined;
  let longestStayMs = 12 * 60 * 60 * 1000;

  for (let index = 0; index < segments.length - 1; index += 1) {
    const segment = segments[index];
    const nextSegment = segments[index + 1];
    const stayMs = dateMs(nextSegment.dep_time) - dateMs(segment.arr_time);
    if (stayMs < longestStayMs) continue;

    const candidate = candidates.find((item) => (
      item.side === 'arrival' && item.airport === segment.arr_airport && item.segment.id === segment.id
    ));
    if (!candidate) continue;
    best = candidate;
    longestStayMs = stayMs;
  }

  return best;
}

function airportsShareMetro(
  firstAirport: string | undefined,
  secondAirport: string | undefined,
  candidates: DestinationCandidate[],
) {
  if (!firstAirport || !secondAirport) return false;
  if (firstAirport === secondAirport) return true;

  const first = candidates.find((candidate) => candidate.airport === firstAirport)?.info;
  const second = candidates.find((candidate) => candidate.airport === secondAirport)?.info;
  if (
    typeof first?.latitude !== 'number'
    || typeof first.longitude !== 'number'
    || typeof second?.latitude !== 'number'
    || typeof second.longitude !== 'number'
  ) return false;

  return haversineKm(first.latitude, first.longitude, second.latitude, second.longitude) <= 150;
}

function haversineKm(lat1: number, lon1: number, lat2: number, lon2: number) {
  const radians = (degrees: number) => degrees * Math.PI / 180;
  const latDelta = radians(lat2 - lat1);
  const lonDelta = radians(lon2 - lon1);
  const value = Math.sin(latDelta / 2) ** 2
    + Math.cos(radians(lat1)) * Math.cos(radians(lat2)) * Math.sin(lonDelta / 2) ** 2;
  return 6371 * 2 * Math.atan2(Math.sqrt(value), Math.sqrt(1 - value));
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

function buildProfile(trips: TripSummary[], account?: AccountIdentity): TravelerProfile {
  const flights = trips.reduce((sum, trip) => sum + trip.flightCount, 0);
  const miles = trips.reduce((sum, trip) => sum + trip.miles, 0);
  const countries = buildPassportArrivals(trips).length;
  const airports = new Set(
    trips
      .flatMap((trip) => trip.airports ?? trip.routeLabel.split('->').map((part) => part.trim()))
      .concat(trips.map((trip) => trip.airportCode ?? ''))
      .filter(Boolean)
  ).size;
  const airlineCodes = new Set(trips.flatMap((trip) => trip.airlines ?? []));
  const airlines = airlineCodes.size || trips.reduce((max, trip) => Math.max(max, trip.airlineCount), 0);

  return {
    name: account?.name?.trim() || account?.email?.split('@')[0] || 'Traveler',
    homeAirport: '',
    homeAirportName: '',
    firstFlightDate: trips.map(trip => trip.startDate).filter(Boolean).sort()[0] ?? '',
    hoursInAir: Math.round(trips.flatMap(trip => trip.segments ?? []).reduce((total, segment) => {
      const elapsed = Date.parse(segment.arrTime) - Date.parse(segment.depTime);
      return total + (Number.isFinite(elapsed) && elapsed > 0 ? elapsed / 3600000 : 0);
    }, 0)),
    flights,
    countries,
    airports,
    airlines,
    miles,
  };
}

function normalizeTitle(title?: string | null) {
  return normalizePlaceName(title);
}

function normalizePlaceName(value?: string | null) {
  return (value ?? '')
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, ' ')
    .trim();
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
