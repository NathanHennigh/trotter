import type { TripSummary } from '../../../data/trotterMock';
import type { CountryArrival } from '../../../utils/countryArrivals';
import { SOMALILAND_TRAVEL_KEY, travelCountry } from '../../../utils/travelCountry';

const nameKey = (value: string) => value.trim().toLocaleLowerCase().replace(/\s+/g, ' ');

/** Share the passport's country identity, including ISO aliases and Somaliland. */
function countryMatcher(arrival: CountryArrival) {
  const target = (arrival.travelCountryKey ?? travelCountry(arrival.country, undefined, arrival.airportCode).travelCountryKey).toUpperCase();
  return (country: string, countryCode?: string, airport?: string, savedKey?: string) => {
    const identity = travelCountry(country, countryCode, airport);
    const key = (identity.travelCountryKey === SOMALILAND_TRAVEL_KEY ? identity.travelCountryKey : savedKey ?? identity.travelCountryKey).toUpperCase();
    if (key === SOMALILAND_TRAVEL_KEY || target === SOMALILAND_TRAVEL_KEY) return key === target;
    return key === target || Boolean(country && nameKey(country) === nameKey(arrival.country));
  };
}

export function tripsForCountry(trips: readonly TripSummary[], arrival: CountryArrival, segmentOnly = false): TripSummary[] {
  const matches = countryMatcher(arrival);
  return trips.filter(trip => ((!segmentOnly || trip.segments?.some(segment => segment.arrAirport === trip.airportCode)) && matches(trip.country, trip.countryCode, trip.airportCode, trip.travelCountryKey))
    || (trip.segments ?? []).some(segment => matches(segment.arrPoint?.country ?? segment.arrCountry ?? '', segment.arrPoint?.countryCode ?? segment.arrCountryCode, segment.arrAirport)
      || Boolean(arrival.airportCode && segment.arrAirport === arrival.airportCode)));
}

/** Explain a trip filed under a country using its recorded local stops. A trip
 * named for Nairobi can legitimately include Morocco, but the title alone
 * cannot communicate its Casablanca connection. Never guess stops from titles. */
export function countryTripContext(trip: TripSummary, arrival: CountryArrival): string | undefined {
  const matches = countryMatcher(arrival);
  const stops = new Map<string, string>();
  const add = (airport: string | undefined, city?: string) => {
    const code = airport?.trim().toUpperCase();
    if (!code) return;
    const cityName = city?.trim();
    const label = cityName && cityName.toUpperCase() !== code ? `${cityName} (${code})` : code;
    if (!stops.has(code) || label !== code) stops.set(code, label);
  };
  for (const segment of [...(trip.segments ?? [])].sort((a, b) => a.depTime.localeCompare(b.depTime))) {
    for (const side of ['dep', 'arr'] as const) {
      const airport = segment[`${side}Airport`], point = segment[`${side}Point`];
      if (matches(point?.country ?? segment[`${side}Country`] ?? '', point?.countryCode ?? segment[`${side}CountryCode`], airport)
        || Boolean(arrival.airportCode && airport === arrival.airportCode)) add(airport, point?.city);
    }
  }
  if (!stops.size && matches(trip.country, trip.countryCode, trip.airportCode, trip.travelCountryKey)) {
    const airport = trip.firstCountryEntryAirport ?? trip.airportCode;
    add(airport, airport === trip.airportCode ? trip.city : undefined);
  }
  return stops.size ? `Through ${[...stops.values()].join(' · ')}` : undefined;
}

/** Keep endpoint years and choose enough space between the remaining labels. */
export function activityYearLabelIndices(count: number, plotWidth: number, minimumSpacing = 42): number[] {
  if (count <= 0) return [];
  if (count === 1 || plotWidth < minimumSpacing) return [count - 1];
  const step = Math.max(1, Math.ceil((count - 1) * minimumSpacing / plotWidth));
  const indices = [0];
  for (let index = step; index < count - 1; index += step) {
    if ((count - 1 - index) * plotWidth / (count - 1) >= minimumSpacing) indices.push(index);
  }
  indices.push(count - 1);
  return indices;
}
