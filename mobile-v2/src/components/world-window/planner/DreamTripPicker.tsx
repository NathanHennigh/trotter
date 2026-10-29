import React from 'react';
import { ActivityIndicator, Modal, ScrollView, StyleSheet, Text, View } from 'react-native';
import { randomUUID } from 'expo-crypto';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import type { DreamItem } from '../../../services/dreams';
import { plannerApi, type PlannerTripSummary } from '../../../services/planner';
import { colors, fonts } from '../../../theme/trotterTheme';
import { PressFeedback } from '../motion';
import { WWButton, WWIcon } from '../WorldWindowUI';

export type PlannerEntry = { tripId?: string; dreamItemIds?: string[]; destination?: string; sourceUrl?: string };

export function DreamTripPicker({ items, sourceUrl, destination, visible = true, onClose, onOpenPlanner }: {
  items: DreamItem[]; sourceUrl?: string; destination?: string; visible?: boolean; onClose: () => void; onOpenPlanner: (entry: PlannerEntry) => void;
}) {
  const insets = useSafeAreaInsets();
  const [trips, setTrips] = React.useState<PlannerTripSummary[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string>();
  const [tripId, setTripId] = React.useState<string>();
  const [chosen, setChosen] = React.useState<string[]>([]);
  const [attempt, setAttempt] = React.useState(0);
  const requestId = React.useRef(randomUUID());
  const mounted = React.useRef(true);
  React.useEffect(() => {
    const controller = new AbortController(); mounted.current = true;
    setLoading(true); setError(undefined);
    void plannerApi.list(controller.signal).then(value => { if (!controller.signal.aborted) setTrips(value.trips); })
      .catch(caught => { if (!controller.signal.aborted) setError(caught instanceof Error ? caught.message : 'Trips could not load.'); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => { mounted.current = false; controller.abort(); };
  }, [attempt]);
  const trip = trips.find(value => value.id === tripId);
  const add = async () => {
    if (!tripId || busy || (!sourceUrl && !chosen.length)) return;
    setBusy(true); setError(undefined);
    try {
      if (sourceUrl) await plannerApi.addSource(tripId, { source_url: sourceUrl, client_request_id: requestId.current });
      else await plannerApi.importDreams(tripId, chosen);
      if (!mounted.current) return;
      onClose(); onOpenPlanner({ tripId });
    } catch (caught) { if (mounted.current) setError(caught instanceof Error ? caught.message : 'Could not add these places.'); }
    finally { if (mounted.current) setBusy(false); }
  };
  return <Modal visible={visible} transparent animationType="fade" onRequestClose={() => { if (!busy) onClose(); }}>
    <View style={s.overlay}>
      <PressFeedback style={s.scrim} accessibilityRole="button" accessibilityLabel="Close add to trip" onPress={() => { if (!busy) onClose(); }} />
      <View style={[s.sheet, { paddingBottom: Math.max(insets.bottom, 16) }]} accessibilityViewIsModal>
        <View style={s.heading}><Text style={s.title}>{trip ? 'Bring your ideas' : 'Add to a trip'}</Text><PressFeedback accessibilityRole="button" accessibilityLabel="Close" onPress={() => { if (!busy) onClose(); }} style={s.icon}><WWIcon name="close" size={20} /></PressFeedback></View>
        <Text style={s.body}>{trip ? `${trip.title}${sourceUrl ? ' · Share the places from this post.' : ' · Choose which saves to share.'}` : 'Choose who you’re planning with.'}</Text>
        <ScrollView keyboardShouldPersistTaps="handled" style={{ flexGrow: 0 }} contentContainerStyle={{ paddingBottom: 16 }}>
          {loading ? <ActivityIndicator color={colors.blue} style={{ margin: 24 }} /> : !trip ? <>
            {trips.map(value => <PressFeedback key={value.id} onPress={() => { setTripId(value.id); setError(undefined); }} accessibilityRole="button" style={s.row}><View style={s.copy}><Text style={s.name}>{value.title}</Text><Text style={s.meta}>{value.member_count} {value.member_count === 1 ? 'traveller' : 'travellers'} · {value.destination}</Text></View><WWIcon name="chevron" size={17} /></PressFeedback>)}
            {!trips.length && !error ? <Text style={[s.body, { paddingVertical: 18 }]}>Start a trip to turn your saves into a plan.</Text> : null}
            <PressFeedback accessibilityRole="button" onPress={() => { onClose(); onOpenPlanner({ destination, sourceUrl, dreamItemIds: sourceUrl ? undefined : items.map(item => item.id) }); }} style={s.row}><WWIcon name="plus" size={18} /><Text style={s.link}>Create a trip</Text></PressFeedback>
          </> : sourceUrl ? <Text style={[s.body, { paddingVertical: 18 }]}>The post will go into Ideas. Its places will appear as they finish organising.</Text> : items.filter(item => /^\d+$/.test(item.id)).map(item => <PressFeedback key={item.id} accessibilityRole="checkbox" accessibilityState={{ checked: chosen.includes(item.id) }} onPress={() => setChosen(ids => ids.includes(item.id) ? ids.filter(id => id !== item.id) : [...ids, item.id])} style={s.row}><View style={s.copy}><Text style={s.name}>{item.placeName || item.city || 'Saved place'}</Text><Text style={s.meta}>{item.city || item.country}</Text></View><View style={[s.check, chosen.includes(item.id) && s.checked]}>{chosen.includes(item.id) ? <Text style={s.checkText}>✓</Text> : null}</View></PressFeedback>)}
        </ScrollView>
        {error ? <View><Text style={s.error} accessibilityRole="alert">{error}</Text>{!trip && <PressFeedback accessibilityRole="button" style={s.row} onPress={() => setAttempt(value => value + 1)}><Text style={s.link}>Try again</Text></PressFeedback>}</View> : null}
        {trip ? <><WWButton label={busy ? 'Adding…' : sourceUrl ? 'Add post to trip' : `Add ${chosen.length} selected ${chosen.length === 1 ? 'place' : 'places'}`} disabled={busy || (!sourceUrl && !chosen.length)} onPress={() => void add()} /><PressFeedback accessibilityRole="button" style={s.row} onPress={() => { if (!busy) setTripId(undefined); }}><Text style={s.link}>Choose another trip</Text></PressFeedback></> : null}
        <Text style={s.privacy}>Your other Dreams stay private.</Text>
      </View>
    </View>
  </Modal>;
}

const s = StyleSheet.create({
  overlay: { flex: 1, justifyContent: 'flex-end', backgroundColor: '#1E303844' },
  scrim: { position: 'absolute', top: 0, left: 0, right: 0, bottom: 0 },
  sheet: { maxHeight: '86%', backgroundColor: colors.paperSoft, paddingHorizontal: 24, paddingTop: 16, borderTopLeftRadius: 14, borderTopRightRadius: 14 },
  heading: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  title: { flex: 1, fontFamily: fonts.display, color: colors.ink, fontSize: 30 },
  icon: { width: 44, height: 44, alignItems: 'center', justifyContent: 'center' },
  body: { fontFamily: fonts.sansRegular, color: colors.mutedInk, fontSize: 14, lineHeight: 21, marginBottom: 10 },
  row: { minHeight: 52, flexDirection: 'row', alignItems: 'center', gap: 12, paddingVertical: 12, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.paperBorder },
  copy: { flex: 1 }, name: { fontFamily: fonts.display, color: colors.ink, fontSize: 21 },
  meta: { fontFamily: fonts.sansRegular, color: colors.mutedInk, fontSize: 12, marginTop: 4 },
  link: { color: colors.blue, fontFamily: fonts.sans, fontSize: 14 },
  check: { width: 22, height: 22, borderWidth: 1, borderColor: colors.mutedInk, borderRadius: 3, alignItems: 'center', justifyContent: 'center' },
  checked: { backgroundColor: colors.blue, borderColor: colors.blue }, checkText: { color: colors.paper, fontSize: 15 },
  privacy: { fontFamily: fonts.sansRegular, color: colors.mutedInk, fontSize: 12, paddingVertical: 12 },
  error: { fontFamily: fonts.sansRegular, color: '#984B39', fontSize: 13, lineHeight: 19 },
});
