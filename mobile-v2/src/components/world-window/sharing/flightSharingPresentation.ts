import type { FlightShare, RetainedFlight, SharedFlight } from '../../../services/flightSharing';

export type RetainedBooking = { key: string; passenger: string; reference: string | null; items: RetainedFlight[] };
export function passengerName(item: RetainedFlight): string {
  return (item.assigned_passenger_name || item.passenger_name || '').trim();
}
export function groupRetainedBookings(items: RetainedFlight[]): RetainedBooking[] {
  const groups = new Map<string, RetainedBooking>();
  for (const item of items) {
    if (item.status === 'belongs_to_you') continue;
    const name = passengerName(item);
    const reference = item.flight?.pnr?.trim() || null;
    // An absent booking reference is not evidence that two flights are related.
    const key = `${reference || item.id}\u0000${name.toLocaleLowerCase()}`;
    const group = groups.get(key) || { key, passenger: name, reference, items: [] };
    group.items.push(item);
    groups.set(key, group);
  }
  const bounded: RetainedBooking[] = [];
  for (const group of groups.values()) {
    const ordered = [...group.items].sort((a, b) => (a.flight?.travel_date || '').localeCompare(b.flight?.travel_date || '')
      || (a.flight?.dep_time || '').localeCompare(b.flight?.dep_time || ''));
    let current: RetainedBooking | undefined;
    let start = NaN;
    for (const item of ordered) {
      const date = Date.parse(item.flight?.travel_date || '');
      // Airlines reuse booking codes. A distant booking is a separate selection.
      if (!current || !Number.isFinite(date) || !Number.isFinite(start) || date - start > 90 * 86400000) {
        current = { ...group, key: `${group.key}\u0000${item.id}`, items: [] };
        start = date;
        bounded.push(current);
      }
      current.items.push(item);
    }
  }
  return bounded.sort((a, b) => (b.items[0]?.flight?.travel_date || '').localeCompare(a.items[0]?.flight?.travel_date || ''));
}
export function flightDate(value?: string | null): string {
  if (!value) return 'Date unavailable';
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
  if (!match) return 'Date unavailable';
  const date = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]), 12);
  if (date.getFullYear() !== Number(match[1]) || date.getMonth() !== Number(match[2]) - 1 || date.getDate() !== Number(match[3])) return 'Date unavailable';
  return date.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' });
}
export function flightTime(value?: string | null): string | undefined {
  if (!value || !/^\d{4}-\d{2}-\d{2}T/.test(value)) return undefined;
  // The import ledger uses UTC for timestamps without an explicit offset.
  const date = new Date(/[zZ]$|[+-]\d{2}:?\d{2}$/.test(value) ? value : `${value}Z`);
  return Number.isFinite(date.getTime()) ? `${date.toISOString().slice(11, 16)} UTC` : undefined;
}
export function arrivalDayOffset(flight: SharedFlight | null): number {
  const utcDay = (value?: string | null) => {
    if (!value || !/^\d{4}-\d{2}-\d{2}T/.test(value)) return NaN;
    const stamp = Date.parse(/[zZ]$|[+-]\d{2}:?\d{2}$/.test(value) ? value : `${value}Z`);
    return Math.floor(stamp / 86400000);
  };
  const difference = utcDay(flight?.arr_time) - utcDay(flight?.dep_time);
  return Number.isFinite(difference) && difference > 0 ? difference : 0;
}
export function flightRoute(flights: SharedFlight[]): string {
  const route: string[] = [];
  for (const flight of flights) {
    if (route.at(-1) !== flight.dep_airport) route.push(flight.dep_airport);
    route.push(flight.arr_airport);
  }
  return route.join(' · ');
}
export function shareStatus(share: FlightShare, now = Date.now()): FlightShare['status'] {
  return share.status === 'pending' && Date.parse(share.expires_at) <= now ? 'expired' : share.status;
}
export function validateFlightShare(passenger: string, recipient: string, count: number, ownEmail?: string): string | undefined {
  if (!count) return 'Choose at least one flight.';
  if (count > 40) return 'Choose up to 40 flights per share.';
  if (passenger.trim().length < 2 || passenger.trim().length > 100) return 'Enter the traveler’s name (up to 100 characters).';
  const email = recipient.trim();
  if (email.length > 254 || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) return 'Enter a valid email address.';
  if (ownEmail && email.toLocaleLowerCase() === ownEmail.trim().toLocaleLowerCase()) return 'Choose the traveler’s email, rather than your own.';
}
export function acceptanceMessage(added: number, existing: number): string {
  if (added === 0) return 'These flights are already in your travel history. No duplicates were added.';
  const addedCopy = `${added} ${added === 1 ? 'flight added' : 'flights added'} to your travel history.`;
  return existing ? `${addedCopy} ${existing} ${existing === 1 ? 'flight was' : 'flights were'} already there; no duplicates were added.` : addedCopy;
}
