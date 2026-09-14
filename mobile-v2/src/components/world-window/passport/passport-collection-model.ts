import type { TripSummary } from '../../../data/trotterMock';
import type { CountryArrival } from '../../../utils/countryArrivals';
import { SOMALILAND_TRAVEL_KEY, travelCountry } from '../../../utils/travelCountry';

const nameKey = (value: string) => value.trim().toLocaleLowerCase().replace(/\s+/g, ' ');

/** Share the passport's country identity, including ISO aliases and Somaliland. */
export function tripsForCountry(trips: readonly TripSummary[], arrival: CountryArrival, segmentOnly = false): TripSummary[] {
  const target = (arrival.travelCountryKey ?? travelCountry(arrival.country, undefined, arrival.airportCode).travelCountryKey).toUpperCase();
  const matches = (country: string, countryCode?: string, airport?: string, savedKey?: string) => {
    const identity = travelCountry(country, countryCode, airport);
    const key = (identity.travelCountryKey === SOMALILAND_TRAVEL_KEY ? identity.travelCountryKey : savedKey ?? identity.travelCountryKey).toUpperCase();
    if (key === SOMALILAND_TRAVEL_KEY || target === SOMALILAND_TRAVEL_KEY) return key === target;
    return key === target || Boolean(country && nameKey(country) === nameKey(arrival.country));
  };
  return trips.filter(trip => ((!segmentOnly || trip.segments?.some(segment => segment.arrAirport === trip.airportCode)) && matches(trip.country, trip.countryCode, trip.airportCode, trip.travelCountryKey))
    || (trip.segments ?? []).some(segment => matches(segment.arrPoint?.country ?? segment.arrCountry ?? '', segment.arrPoint?.countryCode ?? segment.arrCountryCode, segment.arrAirport)
      || Boolean(arrival.airportCode && segment.arrAirport === arrival.airportCode)));
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
