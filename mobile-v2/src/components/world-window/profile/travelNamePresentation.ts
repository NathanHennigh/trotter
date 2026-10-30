import type { RetainedFlight } from '../../../services/flightSharing';
import type { TravelNameRecovery } from '../../../services/travelIdentity';

const tidy = (name: string) => name.normalize('NFKC').trim().replace(/\s+/g, ' ');
export function prepareTravelNames(input: string[], primaryName?: string | null): { aliases: string[]; error?: string } {
  const aliases: string[] = [], seen = new Set<string>();
  if (primaryName?.trim()) seen.add(tidy(primaryName).toLocaleLowerCase());
  for (const value of input) {
    const name = tidy(value);
    if (!name) continue;
    if (name.length > 100) return { aliases, error: 'Keep each name to 100 characters or fewer.' };
    if (!/\p{L}/u.test(name) || !/^[\p{L}\p{M}\s'’\-.,()/]+$/u.test(name)) return { aliases, error: 'Enter the traveler’s name as it appears on a ticket, without an email or numbers.' };
    const key = name.toLocaleLowerCase();
    if (seen.has(key)) continue;
    seen.add(key); aliases.push(name);
  }
  if (aliases.length > 20) return { aliases, error: 'You can save up to 20 previous or other names.' };
  if (!primaryName?.trim() && !aliases.length) return { aliases, error: 'Enter at least one name used on your flight bookings.' };
  return { aliases };
}

/** An owner-assigned name is not evidence that a ticket was issued to this user. */
export function claimableTravelName(items: RetainedFlight[]): { itemId: string; name: string } | undefined {
  const candidates = items.filter(item => item.passenger_name?.trim() && item.flight
    && item.status !== 'canceled' && item.status !== 'belongs_to_you');
  const names = new Set(candidates.map(item => tidy(item.passenger_name!).toLocaleLowerCase()));
  if (names.size !== 1) return undefined;
  const item = candidates[0];
  return item ? { itemId: item.id, name: item.passenger_name! } : undefined;
}

export function recoveryMessage(job: TravelNameRecovery): { title: string; detail: string } {
  if (job.state === 'queued') return { title: 'Names saved', detail: 'Your saved bookings will be checked in the background. You can keep using Trotter.' };
  if (job.state === 'running') return { title: 'Checking saved bookings…', detail: job.checked > 0 ? `${job.checked} checked so far. You can keep using Trotter.` : 'Matching your travel names with previously scanned tickets.' };
  if (job.state === 'failed') return { title: 'Your names are saved', detail: 'The booking check couldn’t finish. Try again; your existing flights are safe.' };
  const title = job.added > 0 ? `${job.added} ${job.added === 1 ? 'flight' : 'flights'} recovered` : 'Saved bookings checked';
  const detail = job.needs_review > 0 ? 'Some bookings still need review in Flights for others.' : job.added > 0 ? 'Your travel history has been updated. Existing flights weren’t added twice.' : 'No additional flights matched these names. Future imports will use them too.';
  return { title, detail };
}
