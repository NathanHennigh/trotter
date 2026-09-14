import type {
  TripSegmentSummary,
  TripSummary,
} from "../../../data/trotterMock";

export function calendarDate(value?: string) {
  const match = value?.match(/^(\d{4}-\d{2}-\d{2})(?:T|\s|$)/);
  if (
    !match ||
    Number.isNaN(Date.parse(`${match[1]}T12:00:00Z`)) ||
    new Date(`${match[1]}T12:00:00Z`).toISOString().slice(0, 10) !== match[1]
  )
    return undefined;
  return match[1];
}

export function flightDate(value?: string, year = true) {
  const date = calendarDate(value);
  return date
    ? new Date(`${date}T12:00:00Z`).toLocaleDateString("en-GB", {
        day: "numeric",
        month: "short",
        ...(year ? { year: "numeric" as const } : {}),
        timeZone: "UTC",
      })
    : "Date unavailable";
}

/** Preserve airport-local clock values rather than converting to the device timezone. */
export function flightTime(value?: string) {
  const match = value?.match(/(?:T|\s)(\d{2}):(\d{2})/);
  return match && Number(match[1]) < 24 && Number(match[2]) < 60
    ? `${match[1]}:${match[2]}`
    : "—";
}

/** Calendar change between the airport dates, not elapsed flight duration. */
export function arrivalDayChange(departure?: string, arrival?: string) {
  const start = calendarDate(departure), end = calendarDate(arrival);
  if (!start || !end) return undefined;
  const days = Math.round((Date.parse(`${end}T12:00:00Z`) - Date.parse(`${start}T12:00:00Z`)) / 86400000);
  if (!Number.isFinite(days) || days === 0) return undefined;
  if (days === 1) return "Next day";
  if (days === -1) return "Previous day";
  return `${Math.abs(days)} days ${days > 0 ? "later" : "earlier"}`;
}

export function tripDates(trip: Pick<TripSummary, "startDate" | "endDate">) {
  if (trip.startDate === trip.endDate) return flightDate(trip.startDate);
  return `${flightDate(trip.startDate, trip.startDate.slice(0, 4) !== trip.endDate.slice(0, 4))} – ${flightDate(trip.endDate)}`;
}

export function orderedSegments(segments: TripSegmentSummary[] = []) {
  return segments
    .map((segment, index) => ({ segment, index }))
    .sort((a, b) => {
      const left = Date.parse(a.segment.depTime),
        right = Date.parse(b.segment.depTime);
      return (
        (Number.isFinite(left) ? left : Infinity) -
          (Number.isFinite(right) ? right : Infinity) || a.index - b.index
      );
    })
    .map((entry) => entry.segment);
}

/** Display continuous flight days as coupons without changing the stored trip. */
export function tripItineraries(trip: TripSummary) {
  const ordered = orderedSegments(trip.segments);
  const groups: TripSegmentSummary[][] = [];
  for (const flight of ordered) {
    const current = groups[groups.length - 1];
    const previous = current?.[current.length - 1];
    const dwell = previous
      ? (Date.parse(flight.depTime) - Date.parse(previous.arrTime)) / 60000
      : NaN;
    if (
      !current ||
      !previous ||
      previous.arrAirport !== flight.depAirport ||
      previous.arrAirport === trip.airportCode ||
      previous.arrAirport === ordered[0].depAirport ||
      (Number.isFinite(dwell) && (dwell > 1440 || dwell < 0))
    ) {
      groups.push([flight]);
    } else current.push(flight);
  }
  return groups.map((legs) => {
    const first = legs[0],
      last = legs[legs.length - 1];
    const sameDay = calendarDate(first.depTime) === calendarDate(last.arrTime);
    return {
      id: first.id,
      legs,
      first,
      last,
      title: `To ${last.arrPoint?.city || last.arrAirport}`,
      via: legs.slice(1).map((leg) => leg.depAirport),
      dates: `${flightDate(first.depTime, false)}${!sameDay && calendarDate(last.arrTime) ? ` – ${flightDate(last.arrTime, false)}` : ""}`,
    };
  });
}

export function connectionText(
  previous: TripSegmentSummary,
  next: TripSegmentSummary,
) {
  if (previous.arrAirport !== next.depAirport)
    return `Journey continues from ${next.depAirport}`;
  if (flightTime(previous.arrTime) === "—" || flightTime(next.depTime) === "—")
    return `Via ${next.depAirport} · timing needs review`;
  const minutes = Math.round(
    (Date.parse(next.depTime) - Date.parse(previous.arrTime)) / 60000,
  );
  if (!Number.isFinite(minutes) || minutes < 0)
    return `Via ${next.depAirport} · timing needs review`;
  if (minutes > 24 * 60) {
    const days = Math.floor(minutes / 1440);
    return `${next.depPoint?.city || next.depAirport} · ${days} ${days === 1 ? "day" : "days"} between flights`;
  }
  return `${next.depAirport} connection${minutes ? ` · ${Math.floor(minutes / 60)}h ${minutes % 60}m` : ""}`;
}

export function matchesTrip(
  trip: TripSummary,
  query: string,
  thisYear: boolean,
  year: number,
) {
  if (thisYear && !tripInYear(trip, year)) return false;
  const text = [
    trip.title,
    trip.city,
    trip.country,
    trip.routeLabel,
    ...(trip.airports ?? []),
    ...(trip.airlines ?? []),
  ]
    .join(" ")
    .normalize("NFKD")
    .replace(/\p{M}/gu, "")
    .toLowerCase();
  return query
    .normalize("NFKD")
    .replace(/\p{M}/gu, "")
    .toLowerCase()
    .trim()
    .split(/\s+/)
    .every((term) => text.includes(term));
}

export function tripInYear(trip: TripSummary, year: number) {
  const prefix = String(year) + "-";
  return trip.segments?.length
    ? trip.segments.some((flight) => calendarDate(flight.depTime)?.startsWith(prefix))
    : trip.startDate.startsWith(prefix) || trip.endDate.startsWith(prefix);
}

/** Destination-oriented wallet preview; the full itinerary retains its original visit groups. */
export function walletSummary(trip: TripSummary) {
  const groups = tripItineraries(trip);
  const legs = orderedSegments(trip.segments);
  const destination = trip.airportCode;
  const arrival = legs.findIndex((flight) => flight.arrAirport === destination);
  const departure = legs.reduce((last, flight, index) => index > arrival && flight.depAirport === destination ? index : last, -1);
  const make = (part: TripSegmentSummary[]) => {
    const first = part[0], last = part[part.length - 1];
    return {
      id: first.id, first, last, legs: part,
      via: part.slice(1).map((flight) => flight.depAirport),
      dates: `${flightDate(first.depTime, false)}${calendarDate(first.depTime) !== calendarDate(last.arrTime) && calendarDate(last.arrTime) ? ` – ${flightDate(last.arrTime, false)}` : ""}`,
    };
  };
  // Only combine a continuous airport chain. A surface transfer must remain explicit.
  const continuous = (part: TripSegmentSummary[]) => part.every((leg, i) => i === 0 || part[i - 1].arrAirport === leg.depAirport);
  const outbound = arrival >= 0 ? legs.slice(0, arrival + 1) : [];
  const inbound = departure >= 0 ? legs.slice(departure) : [];
  const shown = outbound.length && continuous(outbound) && (inbound.length === 0 || continuous(inbound))
    ? [make(outbound), ...(inbound.length ? [make(inbound)] : [])]
    : groups.length > 2 ? [groups[0], groups[groups.length - 1]] : groups;
  const represented = new Set(shown.flatMap((group) => group.legs.map((leg) => leg.id)));
  return { shown, hidden: legs.filter((leg) => !represented.has(leg.id)).length };
}

export type MapPoint = {
  id: string;
  label: string;
  lat: number;
  lon: number;
  category?: string;
  area?: boolean;
  provider?: string;
};
export type MapLine = { from: string; to: string; id: string };
export const validPoint = (point?: {
  lat: number;
  lon: number;
}): point is { lat: number; lon: number } =>
  Boolean(
    point &&
      Number.isFinite(point.lat) &&
      Number.isFinite(point.lon) &&
      Math.abs(point.lat) <= 85.05112878 &&
      Math.abs(point.lon) <= 180,
  );

export function tripMapData(segments: TripSegmentSummary[]) {
  const points = new Map<string, MapPoint>(),
    lines: MapLine[] = [];
  for (const segment of segments) {
    for (const point of [segment.depPoint, segment.arrPoint]) {
      if (validPoint(point))
        points.set(point.code, {
          id: point.code,
          label: `${point.code} · ${point.city}`,
          lat: point.lat,
          lon: point.lon,
        });
    }
    if (validPoint(segment.depPoint) && validPoint(segment.arrPoint))
      lines.push({
        id: segment.id,
        from: segment.depPoint.code,
        to: segment.arrPoint.code,
      });
  }
  return { points: [...points.values()], lines, mappedFlights: lines.length };
}
