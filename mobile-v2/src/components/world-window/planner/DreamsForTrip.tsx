import React from 'react';
import { ActivityIndicator, StyleSheet, Text, View } from 'react-native';
import { plannerApi, type PlannerDreamSuggestion, type PlannerDreamSuggestions, type PlannerTrip } from '../../../services/planner';
import { getAuthRevision } from '../../../services/travelTrips';
import { colors, fonts } from '../../../theme/trotterTheme';
import { PressFeedback } from '../motion';
import { WWIcon } from '../WorldWindowUI';
import { k, PlannerAction, PlannerPhoto, PlannerSheet } from './PlannerKit';

export function DreamsForTrip({ trip, visible, dreamsRevision, onChanged, onChooseDestination, onBrowseDreams, compact = false }: {
  trip: PlannerTrip; visible: boolean; dreamsRevision: unknown; compact?: boolean;
  onChanged: () => void; onChooseDestination?: () => void; onBrowseDreams: () => void;
}) {
  const [data, setData] = React.useState<PlannerDreamSuggestions>(), [error, setError] = React.useState('');
  const [loading, setLoading] = React.useState(false), [busy, setBusy] = React.useState('');
  const [open, setOpen] = React.useState(false), [selected, setSelected] = React.useState<string[]>([]), [notice, setNotice] = React.useState('');
  const generation = React.useRef(0), request = React.useRef<AbortController | undefined>(undefined), locked = React.useRef(false);
  const mounted = React.useRef(true), active = React.useRef(visible), scopeId = trip.match_scope?.id;
  active.current = visible;
  React.useEffect(() => { mounted.current = true; return () => { mounted.current = false; generation.current++; request.current?.abort(); }; }, []);
  const fetchPage = React.useCallback(async (cursor?: string) => {
    request.current?.abort();
    const controller = new AbortController(), sequence = ++generation.current, revision = getAuthRevision(); request.current = controller;
    setLoading(true);
    try {
      const result = await plannerApi.dreamSuggestions(trip.id, cursor, controller.signal);
      if (!mounted.current || !active.current || controller.signal.aborted || sequence !== generation.current || revision !== getAuthRevision()) return;
      setData(current => cursor && current && current.scope?.id === result.scope?.id ? { ...result, suggestions: [...current.suggestions, ...result.suggestions.filter(row => !current.suggestions.some(existing => existing.dream_item_id === row.dream_item_id))] } : result);
      setError('');
    } catch (cause) {
      if (mounted.current && active.current && !controller.signal.aborted && sequence === generation.current && revision === getAuthRevision()) setError(cause instanceof Error ? cause.message : 'Your saved places could not be loaded.');
    } finally { if (mounted.current && sequence === generation.current) setLoading(false); }
  }, [trip.id]);
  React.useEffect(() => {
    if (!visible || !scopeId) { request.current?.abort(); generation.current++; setLoading(false); return; }
    if (!locked.current) void fetchPage();
    return () => { request.current?.abort(); generation.current++; };
  }, [visible, scopeId, dreamsRevision, trip.updated_at, fetchPage]);

  const change = async (label: string, operation: (scope: string) => Promise<PlannerTrip>, message?: string) => {
    const scope = data?.scope?.id;
    if (locked.current || !scope || scope !== scopeId) return;
    locked.current = true; setBusy(label); setError(''); setNotice('');
    const revision = getAuthRevision(); request.current?.abort(); generation.current++;
    try {
      const result = await operation(scope);
      if (!mounted.current || revision !== getAuthRevision()) return;
      // Only merge this member's preference. A delayed response must not replace a newer itinerary.
      setData(current => current ? { ...current, sharing: result.dream_sharing ?? current.sharing } : current);
      if (message) { setSelected([]); setNotice(message); }
      if (active.current) await fetchPage();
      onChanged();
    } catch (cause) {
      if (mounted.current && revision === getAuthRevision()) setError(cause instanceof Error ? cause.message : 'That change could not be saved. Try again.');
    } finally { locked.current = false; if (mounted.current) setBusy(''); }
  };
  const share = () => void change('Sharing places…', scope => plannerApi.importMatchingDreams(trip.id,
    selected.length ? { scope_id: scope, dream_item_ids: selected } : { scope_id: scope, all: true }), 'Shared with this trip.');
  const sharing = data?.sharing ?? trip.dream_sharing, rows = data?.suggestions ?? [], total = data?.total ?? 0;
  const shareLabel = selected.length ? `Share ${selected.length} selected` : `Share all ${total}`;
  const preference = <PressFeedback accessibilityRole="switch" accessibilityLabel={`Automatically share future saves in ${data?.scope?.label || trip.match_scope?.label || 'this destination'}`}
    accessibilityState={{ checked: !!sharing?.enabled, disabled: !!busy }} disabled={!!busy || !data?.scope}
    onPress={() => void change('Saving preference…', scope => plannerApi.setDreamSharing(trip.id, scope, !sharing?.enabled))} style={s.preference}>
    <View style={{ flex: 1 }}><Text style={s.rowTitle}>Share future saves automatically</Text><Text style={k.hint}>Places you save in {data?.scope?.label || trip.match_scope?.label} will go to this trip until it ends. Your other Dreams stay private.</Text>
      {sharing?.enabled && !sharing.active ? <Text style={k.hint}>Automatic sharing is paused{trip.end_date < new Date().toISOString().slice(0, 10) ? ' because this trip has ended' : ''}.</Text> : null}</View>
    <View style={[s.check, sharing?.enabled && { backgroundColor: colors.ink, borderColor: colors.ink }]}>{sharing?.enabled ? <WWIcon name="check" size={14} color={colors.paperSoft} /> : null}</View>
  </PressFeedback>;
  return <View style={[s.section, compact && s.compactSection]}>
    {compact ? <PressFeedback style={s.shortcut} accessibilityRole="button" accessibilityLabel={scopeId ? `From your Dreams, ${total} new places` : 'Connect your Dreams'}
      onPress={() => { if (scopeId) { setOpen(true); setNotice(''); } else if (onChooseDestination) onChooseDestination(); else onBrowseDreams(); }}>
      <Text style={s.rowTitle}>From your Dreams</Text><View style={{ flex: 1 }} />
      {loading && !data ? <ActivityIndicator size="small" color={colors.mutedInk} /> : <Text style={k.hint}>{!scopeId ? onChooseDestination ? 'Connect' : 'Browse' : total ? `${total} new` : sharing?.active ? 'Auto-sharing on' : 'Review'}</Text>}<WWIcon name="chevron" size={14} />
    </PressFeedback> : <>
    <View style={s.heading}><Text style={s.title}>From your Dreams</Text>{scopeId ? <PlannerAction label="Review" quiet onPress={() => { setOpen(true); setNotice(''); }} /> : null}</View>
    {!scopeId ? <><Text style={k.hint}>{onChooseDestination ? 'Choose a destination from your Dreams to find your saved places here.' : 'Your organiser can choose a destination to find matching saves here.'}</Text>
      {onChooseDestination ? <PlannerAction label="Choose destination" quiet onPress={onChooseDestination} /> : null}<PlannerAction label="Browse your Dreams" quiet onPress={onBrowseDreams} /></>
      : <>
        {loading && !data ? <View style={s.loading}><ActivityIndicator color={colors.ink} size="small" /><Text style={k.hint}>Finding your saved places…</Text></View> : null}
        {rows.length ? <><Text style={k.hint}>Only you can see these until you share them.</Text>{rows.slice(0, 3).map(row => <DreamRow key={row.dream_item_id} row={row} />)}
          <PlannerAction label={busy || `Share all ${total} with this trip`} secondary busy={!!busy} disabled={loading} onPress={() => { setSelected([]); void change('Sharing places…', scope => plannerApi.importMatchingDreams(trip.id, { scope_id: scope, all: true }), 'Shared with this trip.'); }} />
        </> : data ? <Text style={k.hint}>Your unshared saves in {data.scope?.label} will appear here.</Text> : null}
        {!open && error ? <><Text style={k.error} accessibilityRole="alert">{error}</Text><PlannerAction label="Retry saved places" quiet onPress={() => void fetchPage()} /></> : null}
        {!open && notice ? <Text style={k.hint} accessibilityLiveRegion="polite">{notice}</Text> : null}
        <PlannerAction label={`Future saves · ${sharing?.enabled ? sharing.active ? 'sharing on' : 'paused' : 'sharing off'}`} quiet onPress={() => { setOpen(true); setNotice(''); }} />
      </>}
    </>}
    {open ? <PlannerSheet title="From your Dreams" subtitle={data?.scope?.label || trip.match_scope?.label} visible={visible} busy={!!busy} error={error} onClose={() => setOpen(false)}>
      {preference}
      <Text style={[k.hint, { marginBottom: 12 }]}>Choose places to share with this trip. Your personal notes stay private.</Text>
      {rows.map(row => <DreamRow key={row.dream_item_id} row={row} selected={selected.includes(row.dream_item_id)} disabled={!!busy} onPress={() => setSelected(current => current.includes(row.dream_item_id) ? current.filter(id => id !== row.dream_item_id) : [...current, row.dream_item_id])} />)}
      {data?.next_cursor ? <PlannerAction label="Show more saved places" quiet busy={loading} disabled={!!busy} onPress={() => void fetchPage(data.next_cursor!)} /> : null}
      {total > 0 ? <PlannerAction label={shareLabel} onPress={share} busy={!!busy && busy === 'Sharing places…'} disabled={!!busy || loading} style={{ marginTop: 12 }} /> : null}
      {notice ? <Text style={[k.hint, { marginTop: 12 }]} accessibilityLiveRegion="polite">{notice}</Text> : null}
      <PlannerAction label="Browse all your Dreams" quiet onPress={() => { setOpen(false); onBrowseDreams(); }} disabled={!!busy} />
      {error ? <PlannerAction label="Reload saved places" quiet onPress={() => void fetchPage()} disabled={!!busy} /> : null}
    </PlannerSheet> : null}
  </View>;
}

function DreamRow({ row, selected, disabled, onPress }: { row: PlannerDreamSuggestion; selected?: boolean; disabled?: boolean; onPress?: () => void }) {
  const content = <><View style={s.photo}><PlannerPhoto uri={row.image_url} category={row.category} title={row.title} /></View><View style={{ flex: 1 }}><Text style={s.rowTitle} numberOfLines={2}>{row.title}</Text><Text style={k.hint} numberOfLines={1}>{row.city || row.country}</Text></View>
    {onPress ? <View style={[s.check, selected && { backgroundColor: colors.ink, borderColor: colors.ink }]}>{selected ? <WWIcon name="check" size={14} color={colors.paperSoft} /> : null}</View> : null}</>;
  return onPress ? <PressFeedback accessibilityRole="checkbox" accessibilityLabel={row.title} accessibilityState={{ checked: selected, disabled }} disabled={disabled} style={s.row} onPress={onPress}>{content}</PressFeedback> : <View style={s.row}>{content}</View>;
}
const s = StyleSheet.create({
  section: { borderTopWidth: 1, borderTopColor: colors.paperBorder, marginTop: 18, paddingTop: 10 },
  compactSection: { marginTop: 0, paddingTop: 0, borderTopWidth: 0, borderBottomWidth: 1, borderBottomColor: colors.paperBorderSoft, marginBottom: 8 },
  shortcut: { flexDirection: 'row', alignItems: 'center', gap: 8, minHeight: 48 },
  heading: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 12 },
  title: { fontFamily: fonts.serif, fontSize: 23, color: colors.ink },
  row: { flexDirection: 'row', gap: 12, alignItems: 'center', minHeight: 74, paddingVertical: 8 },
  rowTitle: { fontFamily: fonts.sans, fontSize: 15, lineHeight: 21, color: colors.ink },
  photo: { width: 55, height: 58, borderRadius: 3, overflow: 'hidden' },
  check: { width: 21, height: 21, borderWidth: 1, borderColor: colors.paperBorder, borderRadius: 3, alignItems: 'center', justifyContent: 'center' },
  preference: { flexDirection: 'row', alignItems: 'center', gap: 18, borderBottomWidth: 1, borderBottomColor: colors.paperBorder, paddingTop: 2, paddingBottom: 16, marginBottom: 16 },
  loading: { flexDirection: 'row', gap: 10, paddingVertical: 14 },
});
