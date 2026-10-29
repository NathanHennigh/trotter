import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import type { DreamItem } from '../../../services/dreams';
import type { PlannerCreate, PlannerDay, PlannerDreamScope, PlannerIdea, PlannerPace, PlannerStop, PlannerTransport, PlannerTrip } from '../../../services/planner';
import { colors, fonts } from '../../../theme/trotterTheme';
import { PressFeedback } from '../motion';
import { WWIcon } from '../WorldWindowUI';
import { k, PlannerAction, PlannerChoices, PlannerField, PlannerPhoto } from './PlannerKit';
import { dateRange, formatDay, isoDay, minutes, tripDates } from './plannerEditing';
import { matchingTimeZones, suggestedTimeZone, timeZoneCity } from './plannerTimeZones';
import { DreamDestinationField } from './DreamDestinationField';

export const PACES: readonly { value: PlannerPace; label: string }[] = [{ value: 'relaxed', label: 'Relaxed' }, { value: 'balanced', label: 'Balanced' }, { value: 'packed', label: 'Full days' }];
export const TRANSPORTS: readonly { value: PlannerTransport; label: string }[] = [{ value: 'walk', label: 'Walking' }, { value: 'drive', label: 'Driving' }, { value: 'transit', label: 'Transit' }];

function nextDate(offset: number) { const date = new Date(); date.setDate(date.getDate() + offset); return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`; }

export function SetupForm({ trip, destination = '', initialIds = [], busy, active = true, onSubmit }: {
  trip?: PlannerTrip; destination?: string; initialIds?: string[]; busy: boolean; active?: boolean;
  onSubmit: (values: Omit<PlannerCreate, 'client_request_id'>) => void;
}) {
  const [title, setTitle] = React.useState(trip?.title ?? (destination ? `${destination}, together` : ''));
  const [place, setPlace] = React.useState(trip?.destination ?? destination);
  const [scope, setScope] = React.useState<PlannerDreamScope | null>(trip?.match_scope ?? null);
  const [start, setStart] = React.useState(trip?.start_date ?? nextDate(14));
  const [end, setEnd] = React.useState(trip?.end_date ?? nextDate(20));
  const [zone, setZone] = React.useState(trip?.timezone ?? suggestedTimeZone(destination) ?? '');
  const manualZone = React.useRef(Boolean(trip));
  const [pace, setPace] = React.useState<PlannerPace>(trip?.pace ?? 'balanced');
  const [transports, setTransports] = React.useState<PlannerTransport[]>(trip?.transport_modes?.length ? trip.transport_modes : [trip?.transport ?? 'walk']);
  const [include, setInclude] = React.useState(true), [error, setError] = React.useState('');
  const submit = () => {
    if (!title.trim() || !place.trim()) { setError('Give the trip a name and destination.'); return; }
    if (!tripDates(start, end).length) { setError('Choose a trip of 1–31 days.'); return; }
    if (!transports.length) { setError('Choose at least one way to get around.'); return; }
    if (!zone) { setError('Choose the local time for your destination.'); return; }
    try { new Intl.DateTimeFormat('en', { timeZone: zone.trim() }).format(); } catch { setError('Choose a local time zone from the list.'); return; }
    setError(''); onSubmit({ title: title.trim(), destination: place.trim(), match_scope_id: scope?.id ?? null, start_date: start, end_date: end, timezone: zone.trim(), pace, transport: transports[0], transport_modes: transports,
      ...(!trip && include && initialIds.length ? { dream_item_ids: initialIds } : {}) });
  };
  return <>
    <PlannerField label="Trip name" value={title} onChangeText={setTitle} placeholder="Morocco, together" editable={!busy} />
    <DreamDestinationField value={place} scope={scope} selectInitial={!trip} active={active} disabled={busy} onChange={(value, chosen) => { setPlace(value); setScope(chosen); if (!manualZone.current) setZone(suggestedTimeZone(chosen?.city || chosen?.country || value) ?? ''); }} />
    {trip?.match_scope && trip.match_scope.id !== scope?.id ? <Text style={[k.hint, { marginBottom: 16 }]}>Changing the destination pauses everyone’s automatic sharing until they choose to turn it on again.</Text> : null}
    <DateRangePicker start={start} end={end} onChange={(a, b) => { setStart(a); setEnd(b); }} disabled={busy} />
    <PlannerChoices label="Your pace" value={pace} choices={PACES} onChange={setPace} disabled={busy} />
    <TransportChoices values={transports} onChange={setTransports} disabled={busy} />
    <TimeZonePicker zone={zone} destination={place} busy={busy} onChange={value => { manualZone.current = true; setZone(value); }} />
    {!trip && initialIds.length > 0 ? <PressFeedback accessibilityRole="checkbox" accessibilityState={{ checked: include }} onPress={() => setInclude(value => !value)} style={f.checkRow}>
      <Check checked={include} /><View style={{ flex: 1 }}><Text style={f.rowTitle}>Include {initialIds.length} {initialIds.length === 1 ? 'place' : 'places'} from your Dreams</Text><Text style={k.hint}>These places will be visible to trip members.</Text></View>
    </PressFeedback> : null}
    {error ? <Text style={k.error} accessibilityRole="alert">{error}</Text> : null}
    <PlannerAction label={trip ? 'Save trip details' : 'Create trip'} onPress={submit} busy={busy} prominent />
  </>;
}

export function TransportChoices({ values, onChange, disabled }: { values: PlannerTransport[]; onChange: (values: PlannerTransport[]) => void; disabled?: boolean }) {
  return <View style={k.field}><Text style={k.label}>Getting around</Text><Text style={k.hint}>Choose any that work for you.</Text><View style={k.choices}>
    {TRANSPORTS.map(choice => { const checked = values.includes(choice.value); return <PressFeedback key={choice.value} accessibilityRole="checkbox" accessibilityLabel={choice.label} accessibilityState={{ checked, disabled: !!disabled }} disabled={disabled}
      style={[k.choice, checked && k.choiceSelected, { flexDirection: 'row', gap: 5 }]} onPress={() => onChange(checked ? values.filter(value => value !== choice.value) : [...values, choice.value])}>
      {checked ? <WWIcon name="check" size={13} /> : null}<Text style={[k.choiceText, checked && k.choiceTextSelected]}>{choice.label}</Text>
    </PressFeedback>; })}
  </View></View>;
}

function TimeZonePicker({ zone, destination, busy, onChange }: { zone: string; destination: string; busy: boolean; onChange: (zone: string) => void }) {
  const [open, setOpen] = React.useState(false), [query, setQuery] = React.useState(''), [limit, setLimit] = React.useState(12);
  const choices = matchingTimeZones(query);
  return <View style={k.field}><View style={{ flexDirection: 'row', alignItems: 'center', gap: 12 }}>
    <View style={{ flex: 1 }}><Text style={f.rowTitle}>{zone ? `Times in ${timeZoneCity(zone)}` : 'Choose the local time'}</Text><Text style={k.hint}>All itinerary times follow this clock.</Text></View>
    <PlannerAction label={open ? 'Done' : zone ? 'Change' : 'Choose'} quiet disabled={busy} onPress={() => { if (!open) { setQuery(matchingTimeZones(destination).length ? destination : ''); setLimit(12); } setOpen(value => !value); }} />
  </View>{open ? <View style={{ marginTop: 14 }}><PlannerField label="Find a city or country" value={query} onChangeText={value => { setQuery(value); setLimit(12); }} placeholder="Casablanca, Morocco…" />
    {choices.slice(0, limit).map(row => <PressFeedback key={row.zone} accessibilityRole="radio" accessibilityState={{ selected: row.zone === zone }} disabled={busy} style={f.checkRow} onPress={() => { onChange(row.zone); setOpen(false); }}>
      <View style={{ flex: 1 }}><Text style={f.rowTitle}>{timeZoneCity(row.zone)}</Text><Text style={k.hint}>{row.countries.join(' · ')}</Text></View><Check checked={row.zone === zone} /></PressFeedback>)}
    {!choices.length ? <Text style={k.hint}>Try a nearby major city or country.</Text> : choices.length > limit ? <PlannerAction label="Show more cities" quiet onPress={() => setLimit(value => value + 20)} /> : null}
  </View> : null}</View>;
}

export function DateRangePicker({ start, end, onChange, disabled }: { start: string; end: string; onChange: (start: string, end: string) => void; disabled?: boolean }) {
  const [picking, setPicking] = React.useState<'start' | 'end' | undefined>();
  const [month, setMonth] = React.useState(start.slice(0, 7));
  const first = new Date(`${month}-01T12:00:00Z`), firstWeekday = (first.getUTCDay() + 6) % 7;
  const length = new Date(Date.UTC(first.getUTCFullYear(), first.getUTCMonth() + 1, 0)).getUTCDate();
  const adjust = (amount: number) => { const date = new Date(first); date.setUTCMonth(date.getUTCMonth() + amount); setMonth(date.toISOString().slice(0, 7)); };
  const select = (date: string) => {
    if (picking === 'start') { onChange(date, end < date ? date : end); setPicking('end'); }
    else { onChange(date < start ? date : start, date); setPicking(undefined); }
  };
  return <View style={k.field}><Text style={k.label}>Dates</Text><View style={f.twoColumns}>
    {(['start', 'end'] as const).map(side => <PressFeedback key={side} accessibilityRole="button" accessibilityLabel={`Choose ${side} date`} disabled={disabled}
      onPress={() => { setPicking(picking === side ? undefined : side); setMonth((side === 'start' ? start : end).slice(0, 7)); }} style={[f.dateBox, picking === side && { borderColor: colors.ink }]}>
      <Text style={k.hint}>{side === 'start' ? 'From' : 'Until'}</Text><Text style={f.dateText}>{formatDay(side === 'start' ? start : end, { year: 'numeric' })}</Text>
    </PressFeedback>)}
  </View>{picking ? <View style={f.calendar}>
    <View style={f.calendarHeader}><PressFeedback style={k.iconButton} onPress={() => adjust(-1)} accessibilityRole="button" accessibilityLabel="Previous month"><WWIcon name="back" size={18} /></PressFeedback>
      <Text style={f.rowTitle}>{first.toLocaleDateString('en', { month: 'long', year: 'numeric', timeZone: 'UTC' })}</Text>
      <PressFeedback style={k.iconButton} onPress={() => adjust(1)} accessibilityRole="button" accessibilityLabel="Next month"><WWIcon name="arrow" size={18} /></PressFeedback></View>
    <Text style={[k.hint, { textAlign: 'center', marginBottom: 8 }]}>Choose the {picking === 'start' ? 'first' : 'last'} day</Text>
    <View style={f.calendarGrid}>{['M', 'T', 'W', 'T', 'F', 'S', 'S'].map((letter, index) => <Text key={index} style={f.weekday}>{letter}</Text>)}
      {Array.from({ length: firstWeekday }, (_, index) => <View key={`empty-${index}`} style={f.dayCell} />)}
      {Array.from({ length }, (_, index) => { const date = `${month}-${String(index + 1).padStart(2, '0')}`, selected = date === start || date === end, inRange = date > start && date < end;
        return <PressFeedback key={date} accessibilityRole="button" accessibilityLabel={formatDay(date, { year: 'numeric' })} accessibilityState={{ selected }}
          onPress={() => select(date)} style={[f.dayCell, inRange && { backgroundColor: colors.paperDeep }, selected && { backgroundColor: colors.ink, borderRadius: 4 }]}>
          <Text style={[f.dayNumber, selected && { color: colors.paperSoft }]}>{index + 1}</Text></PressFeedback>; })}
    </View></View> : null}</View>;
}

export function Check({ checked }: { checked: boolean }) { return <View style={[f.check, checked && f.checked]}>{checked ? <WWIcon name="check" size={15} color={colors.paperSoft} /> : null}</View>; }

export function ImportDreamsForm({ items, initialIds = [], destination, busy, onSubmit }: {
  items: DreamItem[]; initialIds?: string[]; destination: string; busy: boolean; onSubmit: (ids: string[]) => void;
}) {
  const [selected, setSelected] = React.useState<string[]>(initialIds), [query, setQuery] = React.useState('');
  const candidates = items.filter(item => /^\d+$/.test(item.id)).filter(item => !query || `${item.placeName} ${item.city} ${item.country}`.toLowerCase().includes(query.toLowerCase()));
  const ordered = [...candidates].sort((a, b) => Number((b.country || '').toLowerCase() === destination.toLowerCase()) - Number((a.country || '').toLowerCase() === destination.toLowerCase()));
  return <>
    <Text style={[k.body, { marginBottom: 16 }]}>Choose the places you want to share with this trip.</Text>
    <PlannerField label="Find a saved place" value={query} onChangeText={setQuery} placeholder="Place, city or country" />
    {ordered.length ? ordered.map(item => <PressFeedback key={item.id} style={f.importRow} disabled={busy} accessibilityRole="checkbox" accessibilityState={{ checked: selected.includes(item.id) }}
      onPress={() => setSelected(current => current.includes(item.id) ? current.filter(id => id !== item.id) : [...current, item.id])}>
      <View style={f.smallPhoto}><PlannerPhoto uri={item.thumbnailUrl} category={item.category} title={item.placeName} /></View>
      <View style={{ flex: 1 }}><Text style={f.rowTitle} numberOfLines={2}>{item.placeName || item.summary || 'Saved place'}</Text><Text style={k.hint}>{[item.city, item.country].filter(Boolean).join(' · ')}</Text></View><Check checked={selected.includes(item.id)} />
    </PressFeedback>) : <Text style={k.body}>{items.length ? 'No saves match that search.' : 'Your saved places will appear here. You can also add a place directly to the trip.'}</Text>}
    <Text style={[k.hint, { marginVertical: 18 }]}>Your other Dreams and personal notes stay private.</Text>
    <PlannerAction label={`Add ${selected.length} selected ${selected.length === 1 ? 'place' : 'places'}`} onPress={() => onSubmit(selected)} disabled={!selected.length} busy={busy} />
  </>;
}

export function NewIdeaForm({ country, busy, onSubmit, onSource }: {
  country: string; busy: boolean; onSubmit: (values: { title: string; category: string; city: string; country: string; duration_minutes: number }) => void;
  onSource: (url: string) => void;
}) {
  const [mode, setMode] = React.useState<'place' | 'reel'>('place'), [title, setTitle] = React.useState(''), [city, setCity] = React.useState(''),
    [category, setCategory] = React.useState('attraction'), [duration, setDuration] = React.useState('60'), [url, setUrl] = React.useState(''), [error, setError] = React.useState('');
  const submit = () => {
    if (mode === 'reel') {
      try { const parsed = new URL(url.trim()); if (parsed.protocol !== 'https:' || !/(^|\.)instagram\.com$/.test(parsed.hostname)) throw new Error(); }
      catch { setError('Paste the full Instagram link.'); return; }
      onSource(url.trim()); return;
    }
    if (!title.trim() || !Number.isInteger(Number(duration)) || Number(duration) < 5 || Number(duration) > 720) { setError('Add a place name and a visit duration between 5 and 720 minutes.'); return; }
    onSubmit({ title: title.trim(), city: city.trim(), country, category, duration_minutes: Number(duration) });
  };
  return <>
    <PlannerChoices value={mode} choices={[{ value: 'place', label: 'A place' }, { value: 'reel', label: 'An Instagram link' }]} onChange={setMode} />
    {mode === 'place' ? <><PlannerField label="Place name" value={title} onChangeText={setTitle} placeholder="A place you’d love to go" />
      <PlannerField label="City or area" value={city} onChangeText={setCity} placeholder="Where is it?" />
      <PlannerChoices label="What kind of place?" value={category} choices={[{ value: 'attraction', label: 'Explore' }, { value: 'restaurant', label: 'Eat & drink' }, { value: 'hotel', label: 'Stay' }]} onChange={setCategory} />
      <PlannerField label="Visit duration, in minutes" value={duration} onChangeText={setDuration} keyboardType="numeric" /></>
      : <><PlannerField label="Instagram link" value={url} onChangeText={setUrl} keyboardType="url" placeholder="https://www.instagram.com/reel/…" />
        <Text style={[k.body, { marginBottom: 20 }]}>Places found in this post will be added to the group’s Ideas.</Text></>}
    {error ? <Text style={k.error}>{error}</Text> : null}<PlannerAction label={mode === 'reel' ? 'Add link to trip' : 'Add place'} onPress={submit} busy={busy} />
  </>;
}

export function StopEditor({ stop, date, days, busy, onSave, onRemove, onSwap, onMove }: {
  stop: PlannerStop; date: string; days: PlannerDay[]; busy: boolean;
  onSave: (stop: PlannerStop, date: string) => void; onRemove: () => void; onSwap: () => void; onMove: (offset: number) => void;
}) {
  const [name, setName] = React.useState(stop.title), [time, setTime] = React.useState(stop.start_time), [duration, setDuration] = React.useState(String(stop.duration_minutes)),
    [target, setTarget] = React.useState(date), [locked, setLocked] = React.useState(stop.locked), [notes, setNotes] = React.useState(stop.notes || ''), [error, setError] = React.useState('');
  const save = () => {
    if (!name.trim() || !Number.isFinite(minutes(time)) || !Number.isInteger(Number(duration)) || Number(duration) < 5 || Number(duration) > (stop.kind === 'booking' ? 2880 : 1440) || (stop.kind !== 'booking' && minutes(time) + Number(duration) > 1440)) { setError('Use a valid time, such as 09:30, and a duration of at least five minutes. Only bookings can continue overnight.'); return; }
    onSave({ ...stop, title: name.trim(), start_time: time, duration_minutes: Number(duration), locked, notes: notes.trim(), ...(stop.kind === 'break' ? { user_created: true } : {}) }, target);
  };
  return <>
    <PlannerField label="Stop" value={name} onChangeText={setName} editable={!busy && !stop.idea_id} />
    <View style={f.twoColumns}><View style={{ flex: 1 }}><PlannerField label="Start time" value={time} onChangeText={setTime} placeholder="09:30" keyboardType="numbers-and-punctuation" /></View>
      <View style={{ flex: 1 }}><PlannerField label="Minutes here" value={duration} onChangeText={setDuration} keyboardType="numeric" /></View></View>
    <Text style={k.label}>Day</Text><View style={f.dayOptions}>{days.map((day, index) => <PressFeedback key={day.date} accessibilityRole="radio" accessibilityState={{ selected: target === day.date }}
      onPress={() => setTarget(day.date)} style={[f.dayOption, target === day.date && f.dayOptionSelected]}><Text style={[f.dayOptionText, target === day.date && { color: colors.paperSoft }]}>{index + 1} · {formatDay(day.date)}</Text></PressFeedback>)}</View>
    <PressFeedback style={f.checkRow} accessibilityRole="checkbox" accessibilityState={{ checked: locked }} onPress={() => setLocked(value => !value)}>
      <Check checked={locked} /><View style={{ flex: 1 }}><Text style={f.rowTitle}>Keep this stop</Text><Text style={k.hint}>Reworking a day will keep its place and time.</Text></View></PressFeedback>
    <PlannerField label="Note (optional)" value={notes} onChangeText={setNotes} multiline />
    {error ? <Text style={k.error}>{error}</Text> : null}<PlannerAction label="Save changes" onPress={save} busy={busy} />
    {!stop.locked ? <><View style={[f.twoColumns, { marginTop: 8 }]}><PlannerAction label="Move earlier" quiet onPress={() => onMove(-1)} disabled={busy} style={{ flex: 1 }} />
      <PlannerAction label="Move later" quiet onPress={() => onMove(1)} disabled={busy} style={{ flex: 1 }} /></View>
      {stop.kind === 'place' ? <PlannerAction label="Swap for another idea" quiet onPress={onSwap} disabled={busy} /> : null}
      <PlannerAction label="Remove from this day" quiet onPress={onRemove} disabled={busy} /></> : <Text style={[k.hint, { marginTop: 14 }]}>Unlock and save before moving, swapping or removing this stop.</Text>}
  </>;
}

export function IdeaPicker({ ideas, plan, busy, onChoose }: { ideas: PlannerIdea[]; plan: PlannerTrip['plan']; busy: boolean; onChoose: (idea: PlannerIdea) => void }) {
  const [query, setQuery] = React.useState('');
  const placed = new Set(plan?.days.flatMap(day => day.stops.map(stop => stop.idea_id)));
  const available = ideas.filter(idea => !placed.has(idea.id) && (!query || `${idea.title} ${idea.city}`.toLowerCase().includes(query.toLowerCase())));
  return <><PlannerField label="Find an idea" value={query} onChangeText={setQuery} placeholder="Place or city" />
    {available.length ? available.map(idea => <PressFeedback key={idea.id} style={f.importRow} onPress={() => onChoose(idea)} disabled={busy} accessibilityRole="button">
      <View style={f.smallPhoto}><PlannerPhoto uri={idea.image_url} category={idea.category} title={idea.title} /></View><View style={{ flex: 1 }}><Text style={f.rowTitle}>{idea.title}</Text><Text style={k.hint}>{idea.city || idea.country || 'Location to confirm'}</Text></View><WWIcon name="plus" size={18} />
    </PressFeedback>) : <Text style={k.body}>Every matching idea is already in the plan. Add more places in Ideas.</Text>}</>;
}

const f = StyleSheet.create({
  twoColumns: { flexDirection: 'row', gap: 12 },
  rowTitle: { fontFamily: fonts.sans, fontSize: 15, lineHeight: 21, color: colors.ink },
  checkRow: { flexDirection: 'row', alignItems: 'center', gap: 12, minHeight: 54, marginBottom: 18 },
  check: { width: 23, height: 23, borderWidth: 1, borderColor: colors.paperBorder, borderRadius: 3, alignItems: 'center', justifyContent: 'center' },
  checked: { backgroundColor: colors.ink, borderColor: colors.ink },
  importRow: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingVertical: 12, borderBottomWidth: 1, borderColor: colors.paperBorderSoft },
  smallPhoto: { width: 58, height: 62, overflow: 'hidden', borderRadius: 3 },
  dateBox: { flex: 1, minHeight: 62, padding: 10, gap: 4, borderWidth: 1, borderColor: colors.paperBorder, borderRadius: 4 },
  dateText: { fontFamily: fonts.sans, fontSize: 14, color: colors.ink },
  calendar: { paddingTop: 8 },
  calendarHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  calendarGrid: { flexDirection: 'row', flexWrap: 'wrap' },
  weekday: { width: `${100 / 7}%`, textAlign: 'center', paddingVertical: 9, fontFamily: fonts.sans, fontSize: 12, color: colors.mutedInk },
  dayCell: { width: `${100 / 7}%`, minHeight: 44, alignItems: 'center', justifyContent: 'center' },
  dayNumber: { fontFamily: fonts.sans, fontSize: 15, color: colors.ink },
  dayOptions: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, paddingVertical: 12, marginBottom: 8 },
  dayOption: { minHeight: 44, justifyContent: 'center', paddingHorizontal: 12, borderWidth: 1, borderColor: colors.paperBorder, borderRadius: 4 },
  dayOptionSelected: { backgroundColor: colors.ink, borderColor: colors.ink },
  dayOptionText: { fontFamily: fonts.sansRegular, fontSize: 13, color: colors.ink },
});
