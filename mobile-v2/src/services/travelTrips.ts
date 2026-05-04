import React from 'react';
import { Platform } from 'react-native';
import type { CountryIconKey, StampShapeKey } from '../components/trotter/stamps/PngStamp';
import { realTravelerProfile, realTravelTrips } from '../data/realTravelSnapshot';
import type { TravelerProfile, TripSummary } from '../data/trotterMock';
import type { TrotterAccent } from '../theme/trotterTheme';

type ApiSegment = {
  id: number;
  dep_airport: string;
  arr_airport: string;
  dep_time: string;
  arr_time: string;
  airline?: string | null;
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

export function useTravelTrips() {
  const [trips, setTrips] = React.useState<TripSummary[]>(realTravelTrips);
  const [profile, setProfile] = React.useState<TravelerProfile>(realTravelerProfile);
  const [source, setSource] = React.useState<'snapshot' | 'api'>('snapshot');

  React.useEffect(() => {
    let cancelled = false;
    const token = getStoredToken();
    if (!token) return;

    fetch(`${getApiBaseUrl()}/trips`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((response) => {
        if (!response.ok) throw new Error(`Trips API returned ${response.status}`);
        return response.json() as Promise<ApiTrip[]>;
      })
      .then((apiTrips) => {
        if (cancelled || !Array.isArray(apiTrips) || apiTrips.length === 0) return;
        const mappedTrips = mapApiTrips(apiTrips);
        setTrips(mappedTrips);
        setProfile(buildProfile(mappedTrips));
        setSource('api');
      })
      .catch(() => {
        if (!cancelled) setSource('snapshot');
      });

    return () => {
      cancelled = true;
    };
  }, []);

  return { trips, profile, source };
}

function getApiBaseUrl() {
  const params = getUrlParams();
  const configured = params.get('apiUrl') || getProcessEnv('EXPO_PUBLIC_TROTTER_API_URL');
  if (configured) return configured.replace(/\/$/, '');
  return Platform.OS === 'android' ? 'http://10.0.2.2:8000' : 'http://localhost:8000';
}

function getStoredToken() {
  const params = getUrlParams();
  const token = params.get('token') || getProcessEnv('EXPO_PUBLIC_TROTTER_AUTH_TOKEN');
  const storage = getLocalStorage();
  if (token) {
    storage?.setItem('trotterAuthToken', token);
    return token;
  }
  return storage?.getItem('trotterAuthToken') ?? undefined;
}

function getUrlParams() {
  const location = (globalThis as { location?: { search?: string } }).location;
  return new URLSearchParams(location?.search ?? '');
}

function getLocalStorage() {
  return (globalThis as { localStorage?: Storage }).localStorage;
}

function getProcessEnv(key: string) {
  const processLike = globalThis as { process?: { env?: Record<string, string | undefined> } };
  return processLike.process?.env?.[key];
}

function mapApiTrips(apiTrips: ApiTrip[]): TripSummary[] {
  return apiTrips
    .filter((trip) => Array.isArray(trip.segments) && trip.segments.length > 0)
    .map((trip, index) => mapApiTrip(trip, index));
}

function mapApiTrip(trip: ApiTrip, index: number): TripSummary {
  const segments = [...trip.segments].sort((a, b) => dateMs(a.dep_time) - dateMs(b.dep_time) || a.id - b.id);
  const destination = pickDestination(trip.title, segments);
  const country = destination.info.country_name ?? countryHint(trip.title) ?? trip.title ?? 'United States';
  const countryCode = destination.info.country_code ?? (country === 'United States' ? 'US' : undefined);
  const city = cleanCity(destination.info.city) || trip.title || undefined;
  const startDate = toDateOnly(trip.start_ts ?? segments[0].dep_time);
  const endDate = toDateOnly(trip.end_ts ?? segments[segments.length - 1].arr_time);
  const airlines = new Set(segments.map((segment) => segment.airline).filter(Boolean));
  const isDomestic = countryCode === 'US';
  const shape = isDomestic ? 'shieldBadgeRounded' : SHAPES[index % SHAPES.length];
  const color = isDomestic ? '#52745A' : STAMP_COLORS[index % STAMP_COLORS.length];

  return {
    id: `api-trip-${trip.id}`,
    title: displayTitle(trip.title, country, countryCode),
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

  return (
    candidates.find((candidate) => candidate.airport === airportHint) ??
    candidates.find((candidate) => candidate.info.country_name === country && !HOME_AIRPORTS.has(candidate.airport)) ??
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
  const airports = new Set(trips.flatMap((trip) => trip.routeLabel.split('->').map((part) => part.trim())).concat(trips.map((trip) => trip.airportCode ?? ''))).size;
  const airlines = trips.reduce((max, trip) => Math.max(max, trip.airlineCount), 0);

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

function displayTitle(title: string | null | undefined, country: string, countryCode?: string) {
  const clean = title?.trim();
  if (!clean) return country;
  if (countryCode === 'US' || clean.toLowerCase().includes(country.toLowerCase())) return clean;
  return `${clean}, ${country}`;
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
