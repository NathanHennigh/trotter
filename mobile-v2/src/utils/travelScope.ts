import type { TripSegmentSummary, TripSummary } from "../data/trotterMock";

export function normalizeTravelYear(year?: string): string | undefined {
  return year && /^\d{4}$/.test(year) ? year : undefined;
}

/** A flight belongs to its recorded departure year, including overnight flights. */
export function segmentInTravelYear(segment: TripSegmentSummary, year?: string): boolean {
  const scope = normalizeTravelYear(year);
  return !scope || segment.depTime.slice(0, 4) === scope;
}

/** Presentation copies only. Open the original trip by id for its full itinerary.
 * Country first-entry metadata remains lifetime metadata, never a scoped stamp.
 */
export function scopeTripsToYear(trips: readonly TripSummary[], year?: string): TripSummary[] {
  if (!normalizeTravelYear(year)) return [...trips];
  return trips.flatMap(trip => {
    const segments = (trip.segments ?? []).filter(segment => segmentInTravelYear(segment, year));
    if (!segments.length) return [];
    const airlines = [...new Set(segments.map(segment => segment.airline).filter((code): code is string => Boolean(code)))];
    const airports = [...new Set(segments.flatMap(segment => [segment.depAirport || segment.depPoint?.code, segment.arrAirport || segment.arrPoint?.code])
      .filter((code): code is string => Boolean(code)))];
    return [{ ...trip, segments, flightCount: segments.length,
      miles: segments.reduce((sum, segment) => sum + (segment.distanceMiles ?? 0), 0),
      airlines, airlineCount: airlines.length, airports }];
  });
}
