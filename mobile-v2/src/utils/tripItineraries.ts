import type { TripSegmentSummary } from '../data/trotterMock';

export type TripItinerary = {
  id: string;
  segments: TripSegmentSummary[];
  origin: string;
  destination: string;
};

const MAX_UNKEYED_CONNECTION_MS = 36 * 60 * 60 * 1000;

export function groupTripItineraries(segments: TripSegmentSummary[]): TripItinerary[] {
  const sorted = [...segments].sort(
    (left, right) => dateMs(left.depTime) - dateMs(right.depTime) || left.id.localeCompare(right.id),
  );
  const groups: Array<TripItinerary & { bookingReference?: string }> = [];
  const keyedGroups = new Map<string, TripItinerary & { bookingReference?: string }>();

  for (const segment of sorted) {
    const bookingReference = normalizeBookingReference(segment.bookingReference);
    let group = bookingReference ? keyedGroups.get(bookingReference) : undefined;

    if (!group) {
      const previous = groups[groups.length - 1];
      if (previous && canJoinUnkeyedSegment(previous, segment, bookingReference)) {
        group = previous;
      }
    }

    if (!group) {
      group = {
        id: bookingReference ? `booking-${bookingReference}` : `itinerary-${groups.length + 1}`,
        bookingReference,
        segments: [],
        origin: segment.depAirport,
        destination: segment.arrAirport,
      };
      groups.push(group);
      if (bookingReference) keyedGroups.set(bookingReference, group);
    }

    group.segments.push(segment);
    group.destination = segment.arrAirport;
  }

  return groups.map(({ id, segments: itinerarySegments, origin, destination }) => ({
    id,
    segments: itinerarySegments,
    origin,
    destination,
  }));
}

function canJoinUnkeyedSegment(
  group: TripItinerary & { bookingReference?: string },
  segment: TripSegmentSummary,
  bookingReference?: string,
) {
  if (bookingReference && group.bookingReference) return bookingReference === group.bookingReference;
  if (bookingReference && !group.bookingReference) return false;

  const previous = group.segments[group.segments.length - 1];
  if (!previous || previous.arrAirport !== segment.depAirport) return false;

  const layoverMs = dateMs(segment.depTime) - dateMs(previous.arrTime);
  return layoverMs >= 0 && layoverMs <= MAX_UNKEYED_CONNECTION_MS;
}

function normalizeBookingReference(value?: string) {
  const normalized = value?.trim().toUpperCase();
  return normalized || undefined;
}

function dateMs(value: string) {
  const parsed = new Date(value).getTime();
  return Number.isNaN(parsed) ? 0 : parsed;
}
