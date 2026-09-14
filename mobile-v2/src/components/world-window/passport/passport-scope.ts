import type { TravelerProfile, TripSummary } from "../../../data/trotterMock";
import {
  normalizeTravelYear,
  scopeTripsToYear,
} from "../../../utils/travelScope";
import { buildGlobeHistory } from "../globe-history";
import { flightCountryKey } from "../globe-geography";
import { buildPassportArchive } from "./passport-model";
import { buildPassportArrivals } from "./passport-arrivals";
import { tripsForCountry } from "./passport-collection-model";

/** A year narrows the record, never rewrites a country's lifetime first entry. */
export function passportScope(trips: TripSummary[], year?: string) {
  const scope = normalizeTravelYear(year);
  const scopedTrips = scopeTripsToYear(trips, scope);
  const lifetimeArrivals = buildPassportArrivals(trips);
  const visited = scope
    ? new Set(buildGlobeHistory(trips, scope).visited)
    : null;
  const arrivals = visited
    ? lifetimeArrivals.filter((arrival) => {
        const key = flightCountryKey(
          arrival.country,
          arrival.travelCountryKey,
          arrival.airportCode,
        );
        return key && visited.has(key);
      })
    : lifetimeArrivals;
  return { year: scope, trips: scopedTrips, arrivals, lifetimeArrivals };
}
export function scopedPassportArchive(
  trips: TripSummary[],
  profile: TravelerProfile,
  year?: string,
) {
  const scope = passportScope(trips, year);
  const archive = buildPassportArchive(scope.trips, profile);
  if (scope.year) {
    const top = scope.arrivals
      .map((arrival) => ({
        arrival,
        count: tripsForCountry(scope.trips, arrival, true).length,
      }))
      .sort(
        (a, b) =>
          b.count - a.count ||
          a.arrival.country.localeCompare(b.arrival.country),
      )[0];
    archive.records = archive.records.filter(
      (record) => record.label !== "Top destination country",
    );
    if (top?.count)
      archive.records.push({
        label: "Most visited country",
        value: top.arrival.country,
        detail: `${top.count} ${top.count === 1 ? "trip" : "trips"}`,
      });
  }
  return {
    ...archive,
    recordStartDate: archive.firstFlightDate,
    arrivals: scope.arrivals,
    scopeYear: scope.year,
    firstFlightDate: scope.year
      ? buildPassportArchive(trips, profile).firstFlightDate
      : archive.firstFlightDate,
  };
}
