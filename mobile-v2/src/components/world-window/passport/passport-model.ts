import type { TravelerProfile, TripSegmentSummary, TripSummary } from '../../../data/trotterMock';
import type { CountryArrival } from '../../../utils/countryArrivals';
import { buildPassportArrivals } from './passport-arrivals';

export type AirportRecord = { code: string; city: string; country?: string; flights: number; trips: TripSummary[] };
export type AirlineRecord = { code: string; flights: number; miles: number; trips: TripSummary[] };
export type ActivityYear = { year: number; flights: number; miles: number };
export type PassportRecord = { label: string; value: string; detail: string; trip?: TripSummary };
export type PassportArchive = {
  name: string; homeAirport: string; homeAirportName: string; firstFlightDate: string;
  arrivals: CountryArrival[]; airports: AirportRecord[]; airlines: AirlineRecord[];
  years: ActivityYear[]; flights: number; miles: number; tripCount: number; records: PassportRecord[];
};
export function passportIdentityAirport(archive: Pick<PassportArchive, 'homeAirport' | 'homeAirportName' | 'airports'>) {
  if (archive.homeAirport.trim()) return { label: 'Home airport', code: archive.homeAirport.trim(), place: archive.homeAirportName.trim() };
  const mostUsed = archive.airports.reduce<AirportRecord | undefined>((best, airport) => airport.flights > (best?.flights ?? 0) ? airport : best, undefined);
  return mostUsed ? { label: 'Most used airport', code: mostUsed.code, place: mostUsed.city || `${mostUsed.flights} recorded flights` } : undefined;
}
export function flightIdentity(segment: TripSegmentSummary) {
  // IDs and flight numbers can differ between a preview and hydrated detail.
  return [segment.depAirport, segment.arrAirport, segment.depTime].join('|');
}
export function buildPassportArchive(trips: TripSummary[], profile: TravelerProfile): PassportArchive {
  const arrivals = buildPassportArrivals(trips);
  const airportMap = new Map<string, AirportRecord>(), airlineMap = new Map<string, AirlineRecord>();
  const yearMap = new Map<number, ActivityYear>(), routeMap = new Map<string, { count: number; trip: TripSummary }>();
  const seen = new Set<string>();
  let flightCount = 0, miles = 0, firstFlightDate = '', longestFlight: { segment: TripSegmentSummary; trip: TripSummary } | undefined;
  let longestTrip: { trip: TripSummary; days: number } | undefined;
  const addYear = (date: string, count: number, distance: number) => {
    const year = Number(date.slice(0, 4));
    if (!Number.isInteger(year) || year < 1900 || year > 2200) return;
    const row = yearMap.get(year) ?? { year, flights: 0, miles: 0 };
    row.flights += count; row.miles += distance; yearMap.set(year, row);
  };
  const addAirport = (code: string, city: string, trip: TripSummary, count = 1, country = '') => {
    if (!code) return;
    const row: AirportRecord = airportMap.get(code) ?? { code, city, flights: 0, trips: [] };
    row.flights += count; if (!row.city && city) row.city = city; if (country) row.country = country;
    if (!row.trips.some(t => t.id === trip.id)) row.trips.push(trip);
    airportMap.set(code, row);
  };
  for (const trip of trips) {
    const duration = Math.max(1, Math.round((Date.parse(trip.endDate) - Date.parse(trip.startDate)) / 86400000) + 1);
    if (Number.isFinite(duration) && (!longestTrip || duration > longestTrip.days)) longestTrip = { trip, days: duration };
    for (const segment of trip.segments ?? []) {
      const key = flightIdentity(segment); if (seen.has(key)) continue; seen.add(key);
      flightCount++; const distance = Math.max(0, segment.distanceMiles ?? 0); miles += distance;
      if (Number.isFinite(Date.parse(segment.depTime)) && (!firstFlightDate || segment.depTime < firstFlightDate)) firstFlightDate = segment.depTime;
      addYear(segment.depTime, 1, distance);
      addAirport(segment.depAirport, segment.depPoint?.city ?? '', trip, 1, segment.depPoint?.country ?? segment.depCountry);
      addAirport(segment.arrAirport, segment.arrPoint?.city ?? '', trip, 1, segment.arrPoint?.country ?? segment.arrCountry);
      if (segment.airline) {
        const code = segment.airline.trim().toUpperCase();
        const row = airlineMap.get(code) ?? { code, flights: 0, miles: 0, trips: [] };
        row.flights++; row.miles += distance;
        if (!row.trips.some(t => t.id === trip.id)) row.trips.push(trip); airlineMap.set(code, row);
      }
      const route = `${segment.depAirport} → ${segment.arrAirport}`, prior = routeMap.get(route);
      routeMap.set(route, { count: (prior?.count ?? 0) + 1, trip: prior?.trip ?? trip });
      if (distance > (longestFlight?.segment.distanceMiles ?? 0)) longestFlight = { segment, trip };
    }
    if (!trip.segments?.length) {
      flightCount += trip.flightCount; miles += trip.miles; addYear(trip.startDate, trip.flightCount, trip.miles);
      if (Number.isFinite(Date.parse(trip.startDate)) && (!firstFlightDate || trip.startDate < firstFlightDate)) firstFlightDate = trip.startDate;
      for (const code of trip.airports ?? []) addAirport(code, '', trip, 0);
      for (const code of trip.airlines ?? []) {
        const row = airlineMap.get(code) ?? { code, flights: 0, miles: 0, trips: [] };
        if (!row.trips.some(t => t.id === trip.id)) row.trips.push(trip); airlineMap.set(code, row);
      }
    }
  }
  const airports = [...airportMap.values()].sort((a, b) => b.flights - a.flights || a.code.localeCompare(b.code));
  const airlines = [...airlineMap.values()].sort((a, b) => b.flights - a.flights || a.code.localeCompare(b.code));
  const recordedYears = [...yearMap.keys()].sort((a, b) => a - b);
  const years = recordedYears.length ? Array.from({ length: recordedYears.at(-1)! - recordedYears[0] + 1 }, (_, i) => {
    const year = recordedYears[0] + i; return yearMap.get(year) ?? { year, flights: 0, miles: 0 };
  }) : [];
  const topRoute = [...routeMap.entries()].sort((a, b) => b[1].count - a[1].count)[0];
  const busiest = [...years].sort((a, b) => b.flights - a.flights || b.year - a.year)[0];
  const records: PassportRecord[] = [];
  if (airports[0]) records.push({ label: 'Most used airport', value: airports[0].code, detail: `${airports[0].flights} departures / arrivals`, trip: airports[0].trips[0] });
  if (topRoute) records.push({ label: 'Most common route', value: topRoute[0], detail: `${topRoute[1].count} flights`, trip: topRoute[1].trip });
  const countries = new Map<string, number>();
  for (const trip of trips) if (trip.country) countries.set(trip.country, (countries.get(trip.country) ?? 0) + 1);
  const topCountry = [...countries].sort((a, b) => b[1] - a[1])[0];
  if (topCountry) records.push({ label: 'Top destination country', value: topCountry[0], detail: `${topCountry[1]} trips` });
  if (busiest) records.push({ label: 'Busiest year', value: String(busiest.year), detail: `${busiest.flights} flights` });
  if (longestFlight) records.push({ label: 'Furthest flight', value: `${longestFlight.segment.depAirport} → ${longestFlight.segment.arrAirport}`, detail: `${Math.round(longestFlight.segment.distanceMiles ?? 0).toLocaleString()} mi`, trip: longestFlight.trip });
  if (longestTrip) records.push({ label: 'Longest trip', value: longestTrip.trip.city || longestTrip.trip.title, detail: `${Math.max(0, longestTrip.days - 1)} nights`, trip: longestTrip.trip });
  return { name: profile.name, homeAirport: profile.homeAirport, homeAirportName: profile.homeAirportName,
    firstFlightDate: (flightCount ? firstFlightDate || profile.firstFlightDate || '' : '').slice(0, 10), arrivals, airports, airlines, years,
    flights: flightCount, miles: Math.round(miles), tripCount: trips.length, records };
}
export function readableDate(value?: string) {
  if (!value) return '—';
  const date = new Date(`${value.slice(0, 10)}T12:00:00`);
  return Number.isFinite(date.getTime()) ? date.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' }) : value;
}
