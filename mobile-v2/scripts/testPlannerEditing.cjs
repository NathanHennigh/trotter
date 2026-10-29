const assert = require('node:assert/strict');
const { test } = require('node:test');
const fs = require('node:fs'), path = require('node:path'), ts = require('typescript');
function load(name) {
  const file = path.resolve(__dirname, '../src/components/world-window/planner', name + '.ts'), module = { exports: {} };
  const code = ts.transpileModule(fs.readFileSync(file, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, esModuleInterop: true } }).outputText;
  new Function('module', 'exports', 'require', code)(module, module.exports, value => value.endsWith('.json') ? require(path.resolve(path.dirname(file), value)) : load(path.basename(value)));
  return module.exports;
}
const e = load('plannerEditing'), z = load('plannerTimeZones'), result = load('plannerResultModel');
const trip = { start_date: '2026-10-01', end_date: '2026-10-02' };
const stop = (id, time, extra = {}) => ({ id, idea_id: id, title: id, start_time: time, duration_minutes: 60, kind: 'place', locked: false, travel_minutes: 20, travel_source: 'google', ...extra });
const plan = () => ({ days: [{ date: trip.start_date, stops: [stop('a', '09:00'), stop('b', '11:00')] }, { date: trip.end_date, stops: [] }], warnings: [], unplaced_idea_ids: ['c'] });

test('result summaries separate activity coverage from saved accommodation options', () => {
  const ideas = [{ id: 'a', category: 'sight' }, { id: 'b', category: 'restaurant' }, { id: 'c', category: 'sight' },
    ...Array.from({ length: 14 }, (_, i) => ({ id: `hotel${i}`, category: 'accommodation' }))];
  const value = plan(); value.unplaced_idea_ids.push(...ideas.slice(3).map(idea => idea.id));
  assert.equal(result.savedIdeaSummary(ideas), '3 activities · 14 stay options');
  assert.equal(result.plannedActivitySummary(value, ideas), '2 of 3 activities planned');
  assert.deepEqual(result.unscheduledActivities(value, ideas).map(idea => idea.id), ['c']);
  assert.equal(result.stayOptionsSummary(ideas), '14 saved stay options');
});

test('unknown and stale transport reasons never acquire an invented factual explanation', () => {
  const walking = { code: 'transport_required', transport_mode: 'walk' };
  assert.match(result.exclusionText(walking, ['walk']), /beyond walking/);
  assert.equal(result.transportReasonApplies(walking, ['walk', 'drive']), false);
  for (const reason of [undefined, { code: 'unexpected', message: 'Invented closure' }, walking]) {
    assert.equal(result.exclusionText(reason, ['drive']), 'Not included in this version.');
  }
});

test('new location details and changed votes suppress obsolete explanations', () => {
  assert.equal(result.currentExclusionReason({ title: 'Named place', city: 'Marrakech' }, { code: 'needs_location' }), undefined);
  assert.equal(result.currentExclusionReason({ status: 'ready' }, { code: 'processing' }), undefined);
  assert.equal(result.currentExclusionReason({ score: 1 }, { code: 'low_interest' }), undefined);
  assert.equal(result.currentExclusionReason({ score: -2, must_do: true }, { code: 'low_interest' }), undefined);
});

test('placing an excluded activity clears its reason without mutating the accepted plan', () => {
  const original = plan(); original.unplaced_reasons = { c: { code: 'no_fit' } };
  const placed = e.replaceStop(original, 'c', trip.end_date, stop('c', '09:00'));
  assert.deepEqual(placed.unplaced_reasons, {});
  assert.deepEqual(original.unplaced_reasons, { c: { code: 'no_fit' } });
});
test('calendar handles leap years, invalid days, reversed ranges and the 31-day limit', () => {
  assert.deepEqual(e.tripDates('2028-02-28', '2028-03-01'), ['2028-02-28', '2028-02-29', '2028-03-01']);
  for (const [start, end] of [['2026-02-29', '2026-03-01'], ['2026-03-02', '2026-03-01'], ['2026-01-01', '2026-02-01']]) assert.deepEqual(e.tripDates(start, end), []);
  assert.equal(e.tripDates('2026-01-01', '2026-01-31').length, 31);
});
test('cross-day move is immutable and clears invalidated route facts on both days', () => {
  const original = plan(), snapshot = JSON.stringify(original), moved = e.replaceStop(original, 'a', trip.end_date, original.days[0].stops[0]);
  assert.equal(JSON.stringify(original), snapshot); assert.deepEqual(moved.days.map(day => day.stops.map(s => s.id)), [['b'], ['a']]);
  assert.equal(moved.days[0].stops[0].travel_minutes, undefined); assert.equal(moved.days[1].stops[0].travel_source, 'unknown');
  assert.equal(e.validatePlan(moved, trip), undefined);
});
test('removing a stop returns its idea, protects locks and leaves original intact', () => {
  const original = plan(), next = e.removeStop(original, 'a');
  assert.deepEqual(next.unplaced_idea_ids, ['c', 'a']); assert.equal(original.days[0].stops.length, 2);
  original.days[0].stops[0].locked = true; assert.throws(() => e.removeStop(original, 'a'), /Unlock/);
});
test('validation catches duplicated ideas and overlaps, including overnight flights', () => {
  const original = plan(); assert.equal(e.validatePlan(original, trip), undefined);
  original.days[1].stops = [stop('other', '08:00', { idea_id: 'a' })]; assert.match(e.validatePlan(original, trip), /already/);
  original.days[0].stops = [stop('flight', '23:00', { kind: 'booking', idea_id: undefined, duration_minutes: 600, locked: true })];
  original.days[1].stops = [stop('c', '08:00')]; assert.match(e.validatePlan(original, trip), /overlap/);
  original.days[1].stops[0].start_time = '09:00'; assert.equal(e.validatePlan(original, trip), undefined);
  original.days[0].stops[0].kind = 'break'; assert.match(e.validatePlan(original, trip), /duration/);
});
test('reordering preserves a locked booking and rejects insufficient space', () => {
  const original = plan(); original.days[0].stops.push(stop('booking', '15:00', { kind: 'booking', locked: true }));
  const reordered = e.reorderStop(original, trip.start_date, 'b', -1);
  assert.deepEqual(reordered.days[0].stops.map(s => s.id), ['b', 'a', 'booking']);
  assert.equal(reordered.days[0].stops[2].start_time, '15:00'); assert.equal(original.days[0].stops[0].id, 'a');
  assert.throws(() => e.reorderStop(original, trip.start_date, 'booking', -1), /Unlock/);
  original.days[0].stops[2].start_time = '10:30'; assert.throws(() => e.reorderStop(original, trip.start_date, 'b', -1), /enough room/);
});
test('a final stop can finish at midnight without reserving a trailing travel gap', () => {
  const original = plan(); original.days[0].stops = [stop('a', '21:45'), stop('b', '23:00')];
  const next = e.reorderStop(original, trip.start_date, 'b', -1);
  assert.equal(next.days[0].stops[1].start_time, '23:00'); assert.equal(e.validatePlan(next, trip), undefined);
});
test('tiny vote buttons toggle to neutral and switch direction directly', () => {
  assert.equal(e.nextVote(1, 1), 0); assert.equal(e.nextVote(-1, -1), 0); assert.equal(e.nextVote(0, 1), 1); assert.equal(e.nextVote(1, -1), -1);
});
test('global timezone selection never guesses one zone for a multi-zone country', () => {
  assert.ok(z.tripTimeZones.length > 300); assert.equal(z.suggestedTimeZone('Morocco'), 'Africa/Casablanca');
  assert.equal(z.suggestedTimeZone('Japan'), 'Asia/Tokyo'); assert.equal(z.suggestedTimeZone('US'), undefined);
  assert.equal(z.suggestedTimeZone('Australia'), undefined); assert.equal(z.suggestedTimeZone('Chicago'), 'America/Chicago');
  assert.equal(z.timeZoneCity('America/New_York'), 'New York'); assert.ok(z.matchingTimeZones('US').length > 10);
  assert.equal(z.suggestedTimeZone('Not a country'), undefined);
});

test('every unfilled day has editable periods and only actual nights need accommodation', () => {
  const empty = e.emptyPlan({ start_date: '2026-11-01', end_date: '2026-11-04' });
  assert.equal(empty.days.length, 4);
  for (const day of empty.days) assert.deepEqual(e.openDayPeriods(empty, day.date).map(gap => gap.label), ['Morning', 'Lunch', 'Afternoon', 'Evening']);
  assert.deepEqual(empty.days.map(day => day.stay.status), ['needed', 'needed', 'needed', 'not_needed']);
});

test('period openings exclude overnight bookings, intentional free time and supported travel buffers', () => {
  const value = e.emptyPlan(trip);
  value.days[0].stops = [stop('overnight', '23:00', { kind: 'booking', duration_minutes: 720, locked: true })];
  value.days[1].stops = [stop('slow', '14:00', { idea_id: undefined, kind: 'break', user_created: true, duration_minutes: 240 }), stop('a', '19:00'), stop('b', '21:00', { travel_minutes: 60, travel_from_stop_id: 'a', travel_mode: 'walk' })];
  const gaps = e.openDayPeriods(value, trip.end_date, ['walk']);
  assert.deepEqual(gaps.find(gap => gap.label === 'Morning'), { label: 'Morning', start_time: '11:00', end_time: '12:00', duration_minutes: 60 });
  assert.equal(gaps.find(gap => gap.label === 'Afternoon'), undefined, 'a user-created slow afternoon is already filled');
  assert.deepEqual(gaps.find(gap => gap.label === 'Evening'), { label: 'Evening', start_time: '18:00', end_time: '19:00', duration_minutes: 60 });
  const changedModes = e.openDayPeriods(value, trip.end_date, ['drive']);
  assert.equal(changedModes.find(gap => gap.label === 'Evening').start_time, '18:00');
});

test('small fragmented gaps do not produce repetitive period placeholders', () => {
  const value = e.emptyPlan({ start_date: trip.start_date, end_date: trip.start_date });
  value.days[0].stops = [stop('a', '09:00', { duration_minutes: 80 }), stop('b', '10:30', { duration_minutes: 90 })];
  assert.equal(e.openDayPeriods(value, trip.start_date).some(gap => gap.label === 'Morning'), false);
});

test('planned lunch suppresses a repeated meal prompt without interpreting custom text or activities as lunch', () => {
  const value = e.emptyPlan({ start_date: trip.start_date, end_date: trip.start_date });
  value.days[0].stops = [stop('momo', '12:00', { duration_minutes: 90 })];
  const categories = new Map([['momo', 'restaurant']]);
  const hasLunchGap = () => e.openDayPeriods(value, trip.start_date, ['walk'], new Set(['momo']), categories).some(gap => gap.label === 'Lunch');
  assert.equal(hasLunchGap(), false, '12:00–13:30 restaurant must not create a13:30 Lunch to plan prompt');
  categories.set('momo', 'museum'); assert.equal(hasLunchGap(), true, 'an activity leaves the meal unplanned');
  categories.set('momo', 'restaurant'); value.days[0].stops[0].start_time = '09:00'; assert.equal(hasLunchGap(), true, 'a restaurant earlier in the day is not lunch');
  value.days[0].stops = [stop('break', '12:00', { kind: 'break', idea_id: undefined, duration_minutes: 45, generated: true, title: 'Lunch & a little downtime' })];
  assert.equal(hasLunchGap(), false, 'the engine-generated lunch break already covers the meal');
  value.days[0].stops[0].user_created = true; assert.equal(hasLunchGap(), true, 'custom text is not classified by its title');
});

test('travel labels require the correct consecutive place, source and selected mode', () => {
  const day = { date: trip.start_date, stops: [stop('a', '09:00'), stop('slow', '10:00', { kind: 'break', idea_id: undefined }), stop('b', '12:00', { travel_minutes: 17, travel_source: 'estimate', travel_from_stop_id: 'a', travel_mode: 'walk' })] };
  assert.equal(e.travelLegLabel(day, day.stops[0], ['walk']), undefined);
  assert.equal(e.travelLegLabel(day, day.stops[1], ['walk']), undefined);
  assert.equal(e.travelLegLabel(day, day.stops[2], ['walk', 'transit']), 'About 17 min walk · estimate');
  assert.equal(e.travelLegLabel(day, day.stops[2], ['drive']), 'Travel time to check');
  day.stops[2].travel_from_stop_id = 'old-stop'; assert.equal(e.travelLegLabel(day, day.stops[2], ['walk']), 'Travel time to check');
  day.stops[2].travel_from_stop_id = 'a'; day.stops[2].travel_source = 'unknown'; assert.equal(e.travelLegLabel(day, day.stops[2], ['walk']), 'Travel time to check');
});

test('editing a stop clears the predecessor and mode evidence along with both leg estimates', () => {
  const original = plan(); original.days[0].stops[1] = { ...original.days[0].stops[1], travel_mode: 'drive', travel_from_stop_id: 'a', travel_blocked: true };
  const next = e.replaceStop(original, 'a', trip.start_date, { ...original.days[0].stops[0], duration_minutes: 90 });
  assert.equal(original.days[0].stops[1].travel_from_stop_id, 'a');
  for (const item of next.days[0].stops) assert.deepEqual([item.travel_minutes, item.travel_from_stop_id, item.travel_mode, item.travel_source, item.travel_blocked], [undefined, undefined, undefined, 'unknown', undefined]);
});

test('unlocated bookings break the physical route chain while located bookings can have verified legs', () => {
  const day = { date: trip.start_date, stops: [stop('a', '09:00'), stop('flight', '11:00', { kind: 'booking', idea_id: undefined }), stop('b', '15:00', { travel_mode: 'drive', travel_from_stop_id: 'a', travel_minutes: 45 })] };
  const ids = new Set(['a', 'b', 'restaurant']);
  assert.equal(e.travelLegLabel(day, day.stops[1], ['drive'], ids), undefined);
  assert.equal(e.travelLegLabel(day, day.stops[2], ['drive'], ids), undefined, 'a pre-flight location cannot become the post-flight origin');
  day.stops[1].idea_id = 'restaurant'; day.stops[2].travel_from_stop_id = 'flight';
  assert.equal(e.travelLegLabel(day, day.stops[2], ['drive'], ids), '45 min drive');
  day.stops[2].travel_blocked = true; assert.equal(e.travelLegLabel(day, day.stops[2], ['drive'], ids), 'Travel time to check');
  day.stops[1].idea_id = 'deleted-place'; assert.equal(e.travelLegLabel(day, day.stops[2], ['drive'], ids), undefined);
});

test('custom text remains directly editable and stay selection persists separately from timed stops', () => {
  const original = plan(), custom = stop('slow', '14:00', { idea_id: undefined, kind: 'break', title: 'Slow morning', user_created: true });
  const next = e.replaceStop(original, custom.id, trip.end_date, custom);
  assert.equal(next.days[1].stops[0].user_created, true); assert.equal(next.days[1].stops[0].locked, false);
  const withStay = e.replaceStay(next, trip.start_date, { status: 'selected', idea_id: 'hotel' });
  assert.equal(next.days[0].stay, undefined); assert.equal(withStay.days[0].stops.length, 2);
  assert.deepEqual(e.changedDays(next, withStay), [trip.start_date]);
  assert.match(e.validatePlan(withStay, { ...trip, ideas: [{ id: 'hotel', category: 'restaurant' }] }), /saved stays/);
  assert.equal(e.validatePlan(withStay, { ...trip, ideas: [{ id: 'hotel', category: 'hotel' }] }), undefined);
  assert.equal(e.removeStop(withStay, 'slow').days[1].stops.length, 0, 'custom text does not require an unlock step');
});
