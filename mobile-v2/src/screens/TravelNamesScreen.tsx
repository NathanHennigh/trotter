import React from 'react';
import { ActivityIndicator, BackHandler, KeyboardAvoidingView, Platform, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { WWHeader, WWIcon } from '../components/world-window/WorldWindowUI';
import { PressFeedback } from '../components/world-window/motion';
import { TravelRecoveryStatus } from '../components/world-window/profile/TravelRecoveryStatus';
import { prepareTravelNames } from '../components/world-window/profile/travelNamePresentation';
import { useTravelIdentity, type TravelIdentity } from '../services/travelIdentity';
import { useTravelTrips } from '../services/travelTrips';
import { colors, fonts } from '../theme/trotterTheme';

type Props = { onboarding?: boolean; onBack?: () => void; onSaved: (identity: TravelIdentity) => void | Promise<void>; onSkip?: () => void | Promise<void> };
export function TravelNamesScreen({ onboarding = false, onBack, onSaved, onSkip }: Props) {
  const insets = useSafeAreaInsets(), { accountName } = useTravelTrips();
  const travel = useTravelIdentity();
  const [rows, setRows] = React.useState<{ id: number; name: string }[]>([]);
  const [error, setError] = React.useState(''), [working, setWorking] = React.useState(false);
  const initialized = React.useRef(false), serial = React.useRef(0), busy = React.useRef(false), alive = React.useRef(true);
  const primary = travel.identity?.primary_name || accountName;
  React.useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  React.useEffect(() => {
    if (!travel.identity || initialized.current) return;
    initialized.current = true;
    const names = travel.identity.aliases.length ? travel.identity.aliases : primary ? [] : [''];
    setRows(names.map(name => ({ id: ++serial.current, name })));
  }, [travel.identity, primary]);
  const leave = React.useCallback(() => { if (!busy.current && !travel.saving) onBack?.(); }, [onBack, travel.saving]);
  React.useEffect(() => {
    if (Platform.OS === 'web') return;
    const sub = BackHandler.addEventListener('hardwareBackPress', () => { leave(); return true; });
    return () => sub.remove();
  }, [leave]);
  const run = async (action: () => Promise<void>) => {
    if (busy.current || travel.saving) return;
    busy.current = true; setWorking(true); setError('');
    try { await action(); } catch (cause) { if (alive.current) setError(cause instanceof Error ? cause.message : 'Please try again.'); }
    finally { busy.current = false; if (alive.current) setWorking(false); }
  };
  const save = () => run(async () => {
    const result = prepareTravelNames(rows.map(row => row.name), primary);
    if (result.error) throw new Error(result.error);
    const next = await travel.saveNames(result.aliases);
    if (alive.current) await onSaved(next);
  });
  const disabled = working || travel.saving;
  return <KeyboardAvoidingView style={[s.screen, { paddingTop: insets.top }]} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
    <WWHeader title="Travel names" onBack={onBack ? leave : undefined} />
    <ScrollView keyboardShouldPersistTaps="handled" keyboardDismissMode="on-drag" showsVerticalScrollIndicator={false} contentContainerStyle={[s.content, { paddingBottom: insets.bottom + 28 }]}>
      <Text style={s.intro}>{onboarding ? 'Which names are on your tickets?' : 'The names you travel under.'}</Text>
      <Text style={s.description}>Include a previous, maiden, or other name used on flight bookings. This helps Trotter find your flights and keep other travelers’ tickets separate.</Text>
      {primary ? <View style={s.account}><Text style={s.label}>Name on your account</Text><Text style={s.name}>{primary}</Text></View> : null}
      {travel.loading ? <View style={s.loading}><ActivityIndicator color={colors.blue} /><Text style={s.description}>Loading your travel names…</Text></View> : null}
      {!travel.identity && travel.error ? <View style={s.loadError}><Text style={s.error} accessibilityRole="alert">{travel.error}</Text><PressFeedback accessibilityRole="button" style={s.add} onPress={() => void travel.refresh().catch(() => undefined)}><Text style={s.link}>Try again</Text></PressFeedback></View> : null}
      {travel.identity ? <View style={s.names}>
        {rows.map((row, index) => <View key={row.id} style={s.field}>
          <Text style={s.label}>{!primary && index === 0 ? 'Name on your tickets' : 'Previous or other name'}</Text>
          <View style={s.inputRow}><TextInput style={s.input} accessibilityLabel={`Travel name ${index + 1}`} value={row.name}
            onChangeText={name => { setRows(current => current.map(item => item.id === row.id ? { ...item, name } : item)); setError(''); }}
            editable={!disabled} autoCapitalize="words" autoCorrect={false} textContentType="name" maxLength={100} returnKeyType="done" placeholder="Full name as shown on tickets" placeholderTextColor={colors.mutedInk} />
            <PressFeedback accessibilityRole="button" accessibilityLabel={`Remove ${row.name || `travel name ${index + 1}`}`} disabled={disabled} onPress={() => { setRows(current => current.filter(item => item.id !== row.id)); setError(''); }} style={s.remove}><WWIcon name="close" color={colors.mutedInk} size={18} /></PressFeedback>
          </View>
        </View>)}
        {rows.length < 20 ? <PressFeedback accessibilityRole="button" disabled={disabled} accessibilityLabel="Add a previous or other name" style={s.add} onPress={() => setRows(current => [...current, { id: ++serial.current, name: '' }])}><WWIcon name="plus" color={colors.blue} size={18} /><Text style={s.link}>Add a previous or other name</Text></PressFeedback> : null}
      </View> : null}
      <Text style={s.note}>Saving names also rechecks bookings already scanned. You don’t need to scan Gmail again.</Text>
      {error ? <Text style={s.error} accessibilityRole="alert">{error}</Text> : null}
      <PressFeedback accessibilityRole="button" accessibilityState={{ disabled: disabled || !travel.identity, busy: working }} disabled={disabled || !travel.identity} onPress={save} style={[s.primary, (disabled || !travel.identity) && s.disabled]}>
        {working ? <ActivityIndicator color={colors.paperSoft} size="small" /> : null}<Text style={s.primaryText}>{working ? 'Saving…' : onboarding ? 'Confirm names' : 'Save names'}</Text>
      </PressFeedback>
      {onSkip ? <PressFeedback accessibilityRole="button" disabled={disabled} style={s.skip} onPress={() => void run(async () => { await onSkip(); })}><Text style={s.link}>Not now</Text></PressFeedback> : null}
      {!onboarding ? <View style={s.recovery}><TravelRecoveryStatus /></View> : null}
    </ScrollView>
  </KeyboardAvoidingView>;
}
const s = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.paperSoft }, content: { width: '100%', maxWidth: 580, alignSelf: 'center', paddingHorizontal: 24 },
  intro: { fontFamily: fonts.display, fontSize: 27, lineHeight: 33, color: colors.ink, marginTop: 14, marginBottom: 10 }, description: { fontFamily: fonts.sansRegular, fontSize: 14, lineHeight: 22, color: colors.mutedInk },
  account: { borderBottomWidth: 1, borderColor: colors.paperBorder, paddingTop: 28, paddingBottom: 23 }, label: { fontFamily: fonts.sans, fontSize: 12, lineHeight: 19, color: colors.mutedInk, marginBottom: 7 }, name: { fontFamily: fonts.display, fontSize: 29, lineHeight: 35, color: colors.ink },
  names: { paddingTop: 19 }, field: { marginBottom: 17 }, inputRow: { flexDirection: 'row', alignItems: 'center', gap: 3 }, input: { flex: 1, minWidth: 0, minHeight: 52, borderWidth: 1, borderColor: colors.paperBorder, borderRadius: 3, backgroundColor: colors.paper, paddingHorizontal: 12, paddingVertical: 12, fontFamily: fonts.sansRegular, fontSize: 16, color: colors.ink }, remove: { width: 48, minHeight: 52, justifyContent: 'center', alignItems: 'center' },
  add: { flexDirection: 'row', alignItems: 'center', gap: 8, minHeight: 48, alignSelf: 'flex-start' }, link: { fontFamily: fonts.sans, fontSize: 13, lineHeight: 20, color: colors.blue, flexShrink: 1 }, note: { fontFamily: fonts.sansRegular, fontSize: 12, lineHeight: 19, color: colors.mutedInk, marginVertical: 21 },
  primary: { minHeight: 52, paddingVertical: 14, paddingHorizontal: 18, backgroundColor: colors.blue, borderRadius: 3, alignItems: 'center', justifyContent: 'center', flexDirection: 'row', gap: 9, marginTop: 5 }, primaryText: { fontFamily: fonts.sans, fontSize: 14, lineHeight: 21, color: colors.paperSoft }, skip: { minHeight: 52, alignItems: 'center', justifyContent: 'center', marginTop: 6 }, disabled: { opacity: .5 },
  error: { fontFamily: fonts.sansRegular, fontSize: 13, lineHeight: 20, color: colors.redDeep, marginBottom: 10 }, loadError: { paddingTop: 20 }, loading: { paddingVertical: 25, flexDirection: 'row', alignItems: 'center', gap: 10 }, recovery: { marginTop: 28 },
});
