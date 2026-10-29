import type { PlannerDay, PlannerIdea, PlannerPlan, PlannerStay, PlannerStop, PlannerTransport, PlannerTripSummary } from '../../../services/planner';

export function minutes(value: string): number {
  const match = /^(\d{2}):(\d{2})$/.exec(value);
  if (!match || Number(match[1]) > 23 || Number(match[2]) > 59) return NaN;
  return Number(match[1]) * 60 + Number(match[2]);
}
export function clock(value: number) { return `${String(Math.floor(value / 60)).padStart(2, '0')}:${String(value % 60).padStart(2, '0')}`; }
export function isoDay(value: string): boolean {
  return /^\d{4}-\d{2}-\d{2}$/.test(value) && Number.isFinite(Date.parse(`${value}T00:00:00Z`))
    && new Date(`${value}T00:00:00Z`).toISOString().slice(0, 10) === value;
}
export function tripDates(start: string, end: string): string[] {
  if (!isoDay(start) || !isoDay(end) || end < start) return [];
  const count = Math.round((Date.parse(`${end}T00:00:00Z`) - Date.parse(`${start}T00:00:00Z`)) / 86400000) + 1;
  if (count < 1 || count > 31) return [];
  return Array.from({ length: count }, (_, index) => new Date(Date.parse(`${start}T00:00:00Z`) + index * 86400000).toISOString().slice(0, 10));
}
export function emptyPlan(trip: Pick<PlannerTripSummary, 'start_date' | 'end_date'>): PlannerPlan {
  const dates = tripDates(trip.start_date, trip.end_date);
  return { days: dates.map((date, index) => ({ date, stops: [], stay: { status: index < dates.length - 1 ? 'needed' : 'not_needed' } })), warnings: [], unplaced_idea_ids: [] };
}
export function copyPlan(plan: PlannerPlan): PlannerPlan {
  return { ...plan, ...(plan.unplaced_reasons ? { unplaced_reasons: Object.fromEntries(Object.entries(plan.unplaced_reasons).map(([id, reason]) => [id, { ...reason }])) } : {}), days: plan.days.map(day => ({ ...day, ...(day.stay ? { stay: { ...day.stay } } : {}), stops: day.stops.map(stop => ({ ...stop })) })), warnings: [...plan.warnings], unplaced_idea_ids: [...plan.unplaced_idea_ids] };
}
export function formatDay(date: string, options?: Intl.DateTimeFormatOptions) {
  if (!isoDay(date)) return date;
  return new Date(`${date}T12:00:00Z`).toLocaleDateString('en', { day: 'numeric', month: 'short', timeZone: 'UTC', ...options });
}
export function dateRange(start: string, end: string) { return start === end ? formatDay(start) : `${formatDay(start)} – ${formatDay(end)}`; }
export function durationLabel(value: number) {
  if (value < 60) return `${value} min`;
  return `${Math.floor(value / 60)}h${value % 60 ? ` ${value % 60}m` : ''}`;
}
export function validatePlan(plan: PlannerPlan, trip: Pick<PlannerTripSummary, 'start_date' | 'end_date'> & { ideas?: PlannerIdea[] }): string | undefined {
  const dates = tripDates(trip.start_date, trip.end_date), ids = new Set<string>(), ideaIds = new Set<string>();
  if (!dates.length || plan.days.length !== dates.length || plan.days.some((day, index) => day.date !== dates[index])) return 'The plan must include each day of your trip.';
  const blocks: { start: number; end: number; date: string }[] = [];
  for (const [index, day] of plan.days.entries()) {
    if (day.stay) {
      if (!['needed', 'suggested', 'selected', 'not_needed'].includes(day.stay.status)) return 'Choose a valid stay for each night.';
      if (['suggested', 'selected'].includes(day.stay.status) && (!day.stay.idea_id || (trip.ideas && !trip.ideas.some(idea => idea.id === day.stay!.idea_id && isStayIdea(idea))))) return 'Choose accommodation from this trip’s saved stays.';
    }
    for (const stop of day.stops) {
      if (ids.has(stop.id)) return 'A stop appears twice. Remove the duplicate before saving.';
      ids.add(stop.id);
      if (stop.idea_id) { if (ideaIds.has(stop.idea_id)) return 'This place is already in the plan. Move its existing stop instead.'; ideaIds.add(stop.idea_id); }
      const start = minutes(stop.start_time);
      if (!Number.isFinite(start) || !Number.isInteger(stop.duration_minutes) || stop.duration_minutes < 5 || stop.duration_minutes > (stop.kind === 'booking' ? 2880 : 1440) || (stop.kind !== 'booking' && start + stop.duration_minutes > 1440)) return `Check the time and duration for ${stop.title}.`;
      if (!stop.title.trim()) return 'Give each stop a name.';
      blocks.push({ start: index * 1440 + start, end: index * 1440 + start + stop.duration_minutes, date: day.date });
    }
  }
  blocks.sort((a, b) => a.start - b.start);
  for (let i = 1; i < blocks.length; i += 1) if (blocks[i - 1].end > blocks[i].start) return `Stops overlap on ${formatDay(blocks[i].date)}. Adjust their times before saving.`;
}
function invalidateTravel(day: PlannerDay) {
  day.stops = day.stops.map(stop => ({ ...stop, travel_minutes: undefined, travel_source: 'unknown', travel_from_stop_id: undefined, travel_mode: undefined, travel_blocked: undefined }));
}

export function isStayIdea(idea: Pick<PlannerIdea, 'category'>) { return ['stay', 'hotel', 'accommodation', 'lodging'].includes(idea.category.toLowerCase()); }
export function replaceStay(plan: PlannerPlan, date: string, stay: PlannerStay): PlannerPlan {
  const next = copyPlan(plan), day = next.days.find(value => value.date === date);
  if (!day) throw new Error('Choose a night within this trip.');
  day.stay = { ...stay }; return next;
}

function previousPhysicalStop(day: PlannerDay, stop: PlannerStop, knownIdeaIds?: ReadonlySet<string>): PlannerStop | undefined {
  const unlocatedBooking = (value: PlannerStop) => value.kind === 'booking' && (!value.idea_id || (knownIdeaIds && !knownIdeaIds.has(value.idea_id)));
  if (stop.kind === 'break' || unlocatedBooking(stop)) return;
  let previous: PlannerStop | undefined;
  for (const item of day.stops) {
    if (item.id === stop.id) return previous;
    if (item.kind === 'break') continue;
    previous = unlocatedBooking(item) ? undefined : item;
  }
}

/** Unknown or outdated leg data is never presented as a route estimate. */
export function travelLegLabel(day: PlannerDay, stop: PlannerStop, modes: readonly PlannerTransport[], knownIdeaIds?: ReadonlySet<string>): string | undefined {
  const previous = previousPhysicalStop(day, stop, knownIdeaIds);
  if (!previous) return;
  if (stop.travel_blocked || stop.travel_from_stop_id !== previous.id || !stop.travel_mode || !modes.includes(stop.travel_mode)
    || !['google', 'estimate'].includes(stop.travel_source || '') || !Number.isFinite(stop.travel_minutes) || stop.travel_minutes! < 0) return 'Travel time to check';
  const mode = { walk: 'walk', drive: 'drive', transit: 'by transit' }[stop.travel_mode];
  return `${stop.travel_source === 'estimate' ? 'About ' : ''}${Math.round(stop.travel_minutes!)} min ${mode}${stop.travel_source === 'estimate' ? ' · estimate' : ''}`;
}

export type PlannerPeriodGap = { label: 'Morning' | 'Lunch' | 'Afternoon' | 'Evening'; start_time: string; end_time: string; duration_minutes: number };
const PERIODS: readonly [PlannerPeriodGap['label'], number, number][] = [['Morning', 540, 720], ['Lunch', 720, 840], ['Afternoon', 840, 1080], ['Evening', 1080, 1320]];
/** At most one useful opening per period, accounting for bookings that cross midnight. */
export function openDayPeriods(plan: PlannerPlan, date: string, modes: readonly PlannerTransport[] = ['walk', 'drive', 'transit'], knownIdeaIds?: ReadonlySet<string>, ideaCategories?: ReadonlyMap<string, string>): PlannerPeriodGap[] {
  const dayIndex = plan.days.findIndex(day => day.date === date);
  if (dayIndex < 0) return [];
  const lunchPlanned = plan.days[dayIndex].stops.some(stop => {
    const start = minutes(stop.start_time);
    if (start >= 840 || start + stop.duration_minutes <= 720) return false;
    const category = stop.idea_id ? ideaCategories?.get(stop.idea_id)?.toLowerCase() : undefined;
    // These match the engine's meal categories. Custom text is never interpreted as a meal.
    return !!category && ['food', 'restaurant', 'dining'].includes(category)
      || stop.kind === 'break' && 'generated' in stop && stop.generated === true && !stop.user_created;
  });
  const occupied = plan.days.flatMap((day, index) => day.stops.map(stop => {
    const start = (index - dayIndex) * 1440 + minutes(stop.start_time);
    const previous = previousPhysicalStop(day, stop, knownIdeaIds);
    const travel = !stop.travel_blocked && previous && stop.travel_from_stop_id === previous.id && stop.travel_mode && modes.includes(stop.travel_mode) && ['google', 'estimate'].includes(stop.travel_source || '') && Number.isFinite(stop.travel_minutes) ? Math.max(0, stop.travel_minutes!) : 0;
    return { start: start - travel, end: start + stop.duration_minutes };
  })).filter(block => Number.isFinite(block.start) && block.end > 540 && block.start < 1320).sort((a, b) => a.start - b.start);
  return PERIODS.flatMap(([label, start, end]) => {
    if (label === 'Lunch' && lunchPlanned) return [];
    const gaps: { start: number; end: number }[] = []; let cursor = start;
    for (const block of occupied) {
      if (block.end <= cursor || block.start >= end) continue;
      if (block.start > cursor) gaps.push({ start: cursor, end: Math.min(block.start, end) });
      cursor = Math.max(cursor, block.end);
      if (cursor >= end) break;
    }
    if (cursor < end) gaps.push({ start: cursor, end });
    const gap = gaps.sort((a, b) => (b.end - b.start) - (a.end - a.start))[0];
    return gap && gap.end - gap.start >= 30 ? [{ label, start_time: clock(gap.start), end_time: clock(gap.end), duration_minutes: gap.end - gap.start }] : [];
  });
}
export function replaceStop(plan: PlannerPlan, originalId: string, date: string, value: PlannerStop): PlannerPlan {
  const next = copyPlan(plan);
  const destination = next.days.find(day => day.date === date);
  if (!destination) throw new Error('Choose a day within this trip.');
  for (const day of next.days) {
    if (day.stops.some(stop => stop.id === originalId)) { day.stops = day.stops.filter(stop => stop.id !== originalId); invalidateTravel(day); }
  }
  destination.stops.push({ ...value }); destination.stops.sort((a, b) => minutes(a.start_time) - minutes(b.start_time)); invalidateTravel(destination);
  if (value.idea_id) next.unplaced_idea_ids = next.unplaced_idea_ids.filter(id => id !== value.idea_id);
  if (value.idea_id && next.unplaced_reasons) delete next.unplaced_reasons[value.idea_id];
  return next;
}
export function removeStop(plan: PlannerPlan, id: string): PlannerPlan {
  const next = copyPlan(plan);
  for (const day of next.days) {
    const target = day.stops.find(stop => stop.id === id);
    if (!target) continue;
    if (target.locked) throw new Error('Unlock this stop before removing it.');
    if (target.idea_id && !next.unplaced_idea_ids.includes(target.idea_id)) next.unplaced_idea_ids.push(target.idea_id);
    if (target.idea_id && next.unplaced_reasons) delete next.unplaced_reasons[target.idea_id];
    day.stops = day.stops.filter(stop => stop.id !== id); invalidateTravel(day);
  }
  return next;
}
export function reorderStop(plan: PlannerPlan, date: string, id: string, offset: number): PlannerPlan {
  const next = copyPlan(plan), day = next.days.find(value => value.date === date);
  if (!day) return next;
  const index = day.stops.findIndex(value => value.id === id), target = index + offset;
  if (index < 0 || target < 0 || target >= day.stops.length) return next;
  if (day.stops[index].locked) throw new Error('Unlock this stop before moving it.');
  const [stop] = day.stops.splice(index, 1); day.stops.splice(target, 0, stop);
  const original = plan.days.find(value => value.date === date)!;
  let cursor = original.stops.length ? minutes(original.stops[0].start_time) : 540;
  for (const item of day.stops) {
    if (item.locked) {
      if (cursor > minutes(item.start_time)) throw new Error(`There isn’t enough room before ${item.title}. Move this stop to another time or day.`);
      cursor = minutes(item.start_time) + item.duration_minutes;
    } else {
      item.start_time = clock(cursor); cursor += item.duration_minutes;
    }
    if (cursor > 1440 && item.kind !== 'booking') throw new Error('This day is full. Move a stop to another day.');
    cursor += 15;
  }
  invalidateTravel(day); return next;
}
export function stopForIdea(idea: PlannerIdea, id: string, day: PlannerDay): PlannerStop {
  const last = day.stops.at(-1), start = last ? minutes(last.start_time) + last.duration_minutes + 30 : 540;
  return { id, idea_id: idea.id, title: idea.title, kind: 'place', start_time: clock(start), duration_minutes: idea.duration_minutes || 60, locked: false, travel_source: 'unknown' };
}
export function nextVote(current: -1 | 0 | 1, pressed: -1 | 1): -1 | 0 | 1 { return current === pressed ? 0 : pressed; }
export function changedDays(previous: PlannerPlan | null, next: PlannerPlan): string[] {
  return next.days.filter(day => { const before = previous?.days.find(value => value.date === day.date); return JSON.stringify({ stops: before?.stops ?? [], stay: before?.stay }) !== JSON.stringify({ stops: day.stops, stay: day.stay }); }).map(day => day.date);
}
export function canEditPlan(role: string) { return role === 'owner' || role === 'editor'; }
