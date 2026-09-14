import type { TripSegmentSummary } from '../../../data/trotterMock';
import type { AirportRecord } from './passport-model';
import { flightIdentity } from './passport-model';
import { validPoint } from '../trips/tripPresentation';

const routeKey = (s: TripSegmentSummary) => [s.depAirport, s.arrAirport].sort().join('|');
export function airportPresentation(airport: AirportRecord, selectedId?: string) {
  const journeys = airport.trips.map(trip => ({ trip, incident: (trip.segments ?? []).filter(s => s.depAirport === airport.code || s.arrAirport === airport.code) })).filter(j => j.incident.length).sort((a, b) => b.trip.startDate.localeCompare(a.trip.startDate));
  const all = new Map(journeys.flatMap(j => j.incident).map(s => [flightIdentity(s), s]));
  const selected = journeys.find(j => j.trip.id === selectedId);
  const selectedRoutes = new Set((selected?.trip.segments ?? []).map(routeKey));
  const routes = new Map<string, TripSegmentSummary>();
  for (const s of [...all.values(), ...(selected?.trip.segments ?? [])]) if (validPoint(s.depPoint) && validPoint(s.arrPoint)) routes.set(routeKey(s), s);
  const segments = [...routes.values()];
  const highlighted = segments.map(s => selectedRoutes.has(routeKey(s)));
  return { journeys, selected, segments, highlighted, routeCount: new Set([...all.values()].map(routeKey)).size };
}
