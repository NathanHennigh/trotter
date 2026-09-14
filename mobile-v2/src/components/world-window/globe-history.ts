import type { FlightRoute } from "../../data/demoTravel";
import type { TripSummary } from "../../data/trotterMock";
import { flightCountryKey } from "./globe-geography";
import { buildPassportArrivals } from "./passport/passport-arrivals";

/** Counts describe the archive, even when a flight cannot yet be plotted. */
export function buildGlobeHistory(trips: TripSummary[], year: string) {
  const routes: FlightRoute[] = [];
  const airports = new Set<string>();
  const years = new Set<string>();
  const arrivals = new Set<string>();
  let flightCount = 0;
  for (const trip of trips) {
    for (const segment of trip.segments ?? []) {
      const departureYear = segment.depTime.slice(0, 4);
      if (/^\d{4}$/.test(departureYear)) years.add(departureYear);
      if (year !== "All years" && departureYear !== year) continue;
      flightCount++;
      for (const airport of [
        segment.depAirport || segment.depPoint?.code,
        segment.arrAirport || segment.arrPoint?.code,
      ]) {
        const code = airport?.trim().toUpperCase();
        if (code && /^[A-Z0-9]{3,4}$/.test(code)) airports.add(code);
      }
      // A filtered globe reflects only these flights. A trip's primary country
      // may belong to another year, so use it only for its actual arrival airport.
      const primaryArrival = segment.arrAirport === trip.airportCode;
      const country = flightCountryKey(
        segment.arrPoint?.country ??
          segment.arrCountry ??
          (primaryArrival ? trip.country : undefined),
        segment.arrPoint?.countryCode ??
          segment.arrCountryCode ??
          (primaryArrival ? trip.countryCode : undefined),
        segment.arrAirport,
      );
      if (country) arrivals.add(country);
      const from = segment.depPoint,
        to = segment.arrPoint;
      if (
        !from ||
        !to ||
        ![from.lat, from.lon, to.lat, to.lon].every(Number.isFinite)
      )
        continue;
      routes.push({
        id: segment.id,
        from: {
          ...from,
          country: from.country ?? segment.depCountry,
          countryCode: from.countryCode ?? segment.depCountryCode,
        },
        to: {
          ...to,
          country: to.country ?? segment.arrCountry,
          countryCode: to.countryCode ?? segment.arrCountryCode,
        },
        tripId: trip.backendId,
        tripTitle: trip.title,
        depTime: segment.depTime,
        arrTime: segment.arrTime,
        airline: segment.airline,
        flightNumber: segment.flightNumber,
        distanceKm: segment.distanceMiles
          ? segment.distanceMiles / 0.621371
          : undefined,
      });
    }
  }
  // Preserve manually recorded/corrected country entries in the lifetime view.
  const visited =
    year === "All years"
      ? [
          ...new Set(
            buildPassportArrivals(trips)
              .map((a) =>
                flightCountryKey(a.country, a.travelCountryKey, a.airportCode),
              )
              .filter((code): code is string => Boolean(code)),
          ),
        ]
      : [...arrivals];
  return {
    routes,
    visited,
    flightCount,
    airportCount: airports.size,
    years: [...years].sort().reverse(),
  };
}
