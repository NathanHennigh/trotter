import type { FlightRoute } from "../../data/demoTravel";

export function flightPathKey(route: FlightRoute): string {
  return [route.from, route.to].map(point => [point.code, point.lat, point.lon].join(":")).sort().join("|");
}

/** Repeat flights remain individually accessible even when they share one arc. */
export function flightsOnPath(routes: readonly FlightRoute[], selected?: FlightRoute | null): FlightRoute[] {
  if (!selected) return [];
  const key = flightPathKey(selected);
  return routes.filter(route => flightPathKey(route) === key)
    .sort((a, b) => (b.depTime ?? "").localeCompare(a.depTime ?? "") || a.id.localeCompare(b.id));
}
