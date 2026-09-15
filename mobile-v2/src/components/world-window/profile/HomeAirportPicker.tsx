import React from 'react';
import { ActivityIndicator, FlatList, Modal, StyleSheet, Text, TextInput, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import airports from '../../../data/collections/airports.json';
import { colors, fonts } from '../../../theme/trotterTheme';
import { WWIcon } from '../WorldWindowUI';
import { PressFeedback } from '../motion';

export function HomeAirportPicker({ selected, onSave, onClose }: { selected?: string; onSave: (code?: string) => Promise<void>; onClose: () => void }) {
  const insets = useSafeAreaInsets();
  const [query, setQuery] = React.useState('');
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState<string>();
  const running = React.useRef(false), alive = React.useRef(true);
  React.useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  const normalized = (value: string) => value.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().trim();
  const needle = normalized(query);
  const rows = React.useMemo(() => airports.entries.filter(row => !needle || normalized(`${row.key} ${row.city} ${row.name}`).includes(needle))
    .sort((a, b) => Number(b.key === selected || b.key.toLowerCase() === needle) - Number(a.key === selected || a.key.toLowerCase() === needle) || (a.city || a.name).localeCompare(b.city || b.name)), [needle, selected]);
  const save = async (code?: string) => {
    if (running.current) return;
    running.current = true; setSaving(true); setError(undefined);
    try { await onSave(code); if (alive.current) onClose(); }
    catch { if (alive.current) setError('Could not save your home airport. Please try again.'); }
    finally { running.current = false; if (alive.current) setSaving(false); }
  };
  return <Modal animationType="slide" onRequestClose={onClose} presentationStyle="pageSheet">
    <View style={[s.screen, { paddingTop: insets.top + 12, paddingBottom: insets.bottom }]}>
      <View style={s.heading}><Text accessibilityRole="header" style={s.title}>Home airport</Text><PressFeedback accessibilityLabel="Close home airport" onPress={onClose} style={s.close}><WWIcon name="close" size={20} /></PressFeedback></View>
      <Text style={s.note}>Saved for your account on this device.</Text>
      <View style={s.search}><WWIcon name="search" size={18} /><TextInput accessibilityLabel="Find home airport" value={query} onChangeText={setQuery} autoCorrect={false} placeholder="City or airport code" placeholderTextColor={colors.mutedInk} style={s.input} /></View>
      {error ? <Text accessibilityRole="alert" style={s.error}>{error}</Text> : null}
      {saving ? <ActivityIndicator accessibilityLabel="Saving home airport" color={colors.blue} style={s.loading} /> : null}
      <FlatList data={rows} keyExtractor={row => row.key} keyboardShouldPersistTaps="handled" keyboardDismissMode="on-drag" initialNumToRender={12} windowSize={5}
        ListHeaderComponent={selected ? <PressFeedback disabled={saving} onPress={() => void save()} style={s.row}><Text style={s.city}>Remove home airport</Text></PressFeedback> : null}
        renderItem={({ item }) => <PressFeedback disabled={saving} accessibilityRole="button" accessibilityLabel={`${item.city || item.name}, ${item.key}`} accessibilityState={{ selected: selected === item.key, disabled: saving }} onPress={() => void save(item.key)} style={s.row}>
          <Text style={s.code}>{item.key}</Text><View style={s.copy}><Text style={s.city}>{item.city || item.name}</Text><Text style={s.name}>{item.name}</Text></View>{selected === item.key ? <Text style={s.check}>✓</Text> : null}
        </PressFeedback>}
        ListEmptyComponent={<Text style={s.note}>No airports match that search.</Text>} />
    </View>
  </Modal>;
}
const s = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.paperSoft }, heading: { paddingHorizontal: 24, flexDirection: 'row', alignItems: 'center', gap: 12 },
  title: { fontFamily: fonts.display, color: colors.ink, fontSize: 30, flex: 1 }, close: { width: 44, height: 44, alignItems: 'center', justifyContent: 'center' },
  note: { marginHorizontal: 24, marginVertical: 10, fontFamily: fonts.sansRegular, fontSize: 12, lineHeight: 18, color: colors.mutedInk },
  search: { margin: 24, marginTop: 8, flexDirection: 'row', alignItems: 'center', gap: 12, borderBottomWidth: 1, borderBottomColor: colors.paperBorder }, input: { flex: 1, minHeight: 48, fontFamily: fonts.sansRegular, fontSize: 15, color: colors.ink },
  row: { marginHorizontal: 24, paddingVertical: 15, minHeight: 64, flexDirection: 'row', alignItems: 'center', gap: 15, borderBottomWidth: 1, borderBottomColor: colors.paperBorderSoft },
  code: { fontFamily: fonts.mono, fontSize: 19, color: colors.blue }, copy: { flex: 1, minWidth: 0, gap: 4 }, city: { fontFamily: fonts.sans, fontSize: 15, color: colors.ink }, name: { fontFamily: fonts.sansRegular, fontSize: 11, color: colors.mutedInk, lineHeight: 17 },
  check: { fontSize: 18, color: colors.blue }, error: { marginHorizontal: 24, fontFamily: fonts.sansRegular, color: colors.redDeep, fontSize: 13 }, loading: { padding: 8 },
});
