import type { TripSummary } from '../data/trotterMock';
import { stampIdentity } from '../components/trotter/stamps/stampIdentity';
import { travelCountry, isSomalilandAirport, SOMALILAND_TRAVEL_KEY, SOMALILAND_ICON_KEY } from './travelCountry';

export type CountryArrival = {
  country: string;
  travelCountryKey?: string;
  airportCode?: string;
  firstVisitDate: string;
  tripCount: number;
  airportCount: number;
  stamp: TripSummary['stamp'];
};

type ArrivalSegment = {
  airportCode: string;
  date: string;
  countryCode?: string;
  country?: string;
};

// The entry airport can precede the trip's final destination (e.g. JFK before LAX).
// Match enriched country metadata, never an airport's city or a guessed code.
export function firstCountryEntry(segments: ArrivalSegment[], country: string, countryCode?: string) {
  const target = travelCountry(country, countryCode);
  return segments
    .filter((segment) => {
      const arrival = travelCountry(segment.country ?? '', segment.countryCode, segment.airportCode);
      if (target.travelCountryKey === SOMALILAND_TRAVEL_KEY || arrival.travelCountryKey === SOMALILAND_TRAVEL_KEY) return target.travelCountryKey === arrival.travelCountryKey;
      return countryCode && segment.countryCode ? segment.countryCode.toUpperCase() === countryCode.toUpperCase() : segment.country?.toLowerCase() === country.toLowerCase();
    })
    .filter((segment) => segment.airportCode && Number.isFinite(Date.parse(segment.date)))
    .sort((a, b) => Date.parse(a.date) - Date.parse(b.date))[0];
}

function arrivalDate(trip: TripSummary) {
  const value = trip.firstCountryEntryDate ?? trip.stamp.date ?? trip.startDate;
  const iso = /^\d{4}-\d{2}-\d{2}/.exec(value);
  if (iso) return iso[0];
  // Older bundled snapshots stored stamp dates already formatted for display.
  const parsed = new Date(value);
  if (!Number.isFinite(parsed.getTime())) return trip.startDate.slice(0, 10);
  return `${parsed.getFullYear()}-${String(parsed.getMonth() + 1).padStart(2, '0')}-${String(parsed.getDate()).padStart(2, '0')}`;
}

function arrivalOrder(trip: TripSummary) {
  const airport = trip.firstCountryEntryAirport ?? trip.stamp.airportCode ?? trip.airportCode;
  const times = (trip.segments ?? []).filter((segment) => segment.arrAirport === airport)
    .map((segment) => Date.parse(segment.arrTime)).filter(Number.isFinite);
  return times.length ? Math.min(...times) : Date.parse(arrivalDate(trip));
}

function countryVisits(trips: TripSummary[]): TripSummary[] {
  return trips.flatMap((trip) => {
    const identity = travelCountry(trip.country, trip.countryCode, trip.airportCode);
    const normalized = { ...trip, ...identity, stamp: { ...trip.stamp, country: identity.country } };
    if (identity.travelCountryKey === SOMALILAND_TRAVEL_KEY) {
      const entry = (trip.segments ?? []).filter((segment) => isSomalilandAirport(segment.arrAirport) && Number.isFinite(Date.parse(segment.arrTime)))
        .sort((a, b) => Date.parse(a.arrTime) - Date.parse(b.arrTime))[0];
      if (entry) {
        normalized.firstCountryEntryAirport = entry.arrAirport;
        normalized.firstCountryEntryDate = entry.arrTime.slice(0, 10);
      }
      normalized.stamp = { ...normalized.stamp, ...stampIdentity('Somaliland', SOMALILAND_TRAVEL_KEY), icon: SOMALILAND_ICON_KEY,
        airportCode: normalized.firstCountryEntryAirport ?? normalized.airportCode, date: normalized.firstCountryEntryDate ?? normalized.stamp.date };
      return [normalized];
    }
    // HGA/BBO are explicitly tracked as Somaliland travel. A multi-country trip
    // can retain its primary destination and still earn this distinct entry stamp.
    const entry = (trip.segments ?? []).filter((segment) => isSomalilandAirport(segment.arrAirport) && Number.isFinite(Date.parse(segment.arrTime)))
      .sort((a, b) => Date.parse(a.arrTime) - Date.parse(b.arrTime))[0];
    if (!entry) return [normalized];
    const date = entry.arrTime.slice(0, 10);
    const visit: TripSummary = { ...trip, id: `${trip.id}:somaliland`, country: 'Somaliland', countryCode: undefined,
      travelCountryKey: SOMALILAND_TRAVEL_KEY, airportCode: entry.arrAirport,
      firstCountryEntryAirport: entry.arrAirport, firstCountryEntryDate: date,
      stamp: { ...trip.stamp, ...stampIdentity('Somaliland', SOMALILAND_TRAVEL_KEY), country: 'Somaliland',
        icon: SOMALILAND_ICON_KEY, city: undefined, airportCode: entry.arrAirport, date } };
    return [normalized, visit];
  });
}

export function buildCountryArrivals(rawTrips: TripSummary[]): CountryArrival[] {
  const trips = countryVisits(rawTrips);
  const arrivals = new Map<string, CountryArrival & { airports: Set<string> }>();
  const normalizedName = (country: string) => country.trim().toLowerCase().replace(/\s+/g, ' ');
  const codesByName = new Map(trips.filter((trip) => trip.countryCode).map((trip) => [normalizedName(trip.country), trip.countryCode!.toUpperCase()]));
  const visitDate = arrivalDate;
  const chronological = [...trips].sort((a, b) => arrivalOrder(a) - arrivalOrder(b) || a.id.localeCompare(b.id));
  for (const trip of chronological) {
    if (!trip.country.trim()) continue;
    const key = trip.travelCountryKey === SOMALILAND_TRAVEL_KEY ? SOMALILAND_TRAVEL_KEY : trip.countryCode?.toUpperCase() ?? codesByName.get(normalizedName(trip.country)) ?? normalizedName(trip.country);
    const airportCode = trip.firstCountryEntryAirport ?? trip.stamp.airportCode ?? trip.airportCode;
    const airportCodes = [trip.airportCode, airportCode].filter((code): code is string => Boolean(code));
    const known = arrivals.get(key);
    if (known) {
      known.tripCount += 1;
      airportCodes.forEach((code) => known.airports.add(code));
      known.airportCount = known.airports.size;
      continue;
    }
    const airports = new Set(airportCodes);
    arrivals.set(key, {
      country: trip.country,
      travelCountryKey: key,
      airportCode,
      firstVisitDate: visitDate(trip),
      tripCount: 1,
      airportCount: airports.size,
      // City remains part of trip metadata but is not part of an arrival stamp.
      stamp: { ...trip.stamp, city: undefined, airportCode, date: visitDate(trip) },
      airports,
    });
  }
  return Array.from(arrivals.values())
    .sort((a, b) => b.firstVisitDate.localeCompare(a.firstVisitDate) || a.country.localeCompare(b.country))
    .map(({ airports: _airports, ...arrival }) => arrival);
}
