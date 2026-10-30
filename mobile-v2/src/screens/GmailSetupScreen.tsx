import React from 'react';
import { ActivityIndicator, BackHandler, Platform, ScrollView, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { WWHeader, WWIcon } from '../components/world-window/WorldWindowUI';
import { PressFeedback } from '../components/world-window/motion';
import { useTravelTrips } from '../services/travelTrips';
import { colors, fonts } from '../theme/trotterTheme';

export function GmailSetupScreen({ onDone, onSkip, onBack }: { onDone: () => void | Promise<void>; onSkip: () => void | Promise<void>; onBack?: () => void }) {
  const insets = useSafeAreaInsets();
  const { gmailConnected, gmailConnecting, gmailConnectionError, gmailSyncStatus, gmailSyncError, connectGmail, cancelGmailConnection } = useTravelTrips();
  const [error, setError] = React.useState(''), [finishing, setFinishing] = React.useState(false);
  const alive = React.useRef(true), busy = React.useRef(false);
  React.useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  const back = React.useCallback(() => { if (!busy.current) { if (gmailConnecting && !gmailConnected) cancelGmailConnection(); onBack?.(); } }, [gmailConnecting, gmailConnected, cancelGmailConnection, onBack]);
  React.useEffect(() => {
    if (Platform.OS === 'web') return;
    const sub = BackHandler.addEventListener('hardwareBackPress', () => { back(); return true; }); return () => sub.remove();
  }, [back]);
  const finish = async (skip: boolean) => {
    if (busy.current) return;
    busy.current = true; setFinishing(true); setError('');
    if (skip && gmailConnecting && !gmailConnected) cancelGmailConnection();
    try { await (skip ? onSkip() : onDone()); }
    catch (cause) { if (alive.current) setError(cause instanceof Error ? cause.message : 'Please try again.'); }
    finally { busy.current = false; if (alive.current) setFinishing(false); }
  };
  const connect = () => {
    if (gmailConnecting || busy.current) return;
    setError('');
    // Connection state unlocks Continue immediately; this promise may include a long background scan.
    void connectGmail().catch(cause => { if (alive.current) setError(cause instanceof Error ? cause.message : 'Could not connect Gmail. Please try again.'); });
  };
  const waiting = gmailConnecting && !gmailConnected;
  return <View style={[s.screen, { paddingTop: insets.top }]}>
    <WWHeader title="Your flights" onBack={onBack ? back : undefined} />
    <ScrollView contentContainerStyle={[s.content, { paddingBottom: insets.bottom + 28 }]} showsVerticalScrollIndicator={false}>
      <View style={s.icon} accessibilityElementsHidden importantForAccessibility="no-hide-descendants"><WWIcon name={gmailConnected ? 'check' : 'mail'} size={34} color={colors.blue} /></View>
      <Text style={s.title}>{gmailConnected ? 'Gmail is connected.' : 'Bring your flights into Trotter.'}</Text>
      <Text style={s.description}>{gmailConnected ? gmailSyncStatus === 'syncing' ? 'Your flight confirmations are being imported in the background. You can start exploring now.' : 'Your flight confirmations can now become trips, routes, and passport stamps.' : 'Connect Gmail to find flight confirmations and build your travel history automatically.'}</Text>
      {!gmailConnected ? <View style={s.permission}><WWIcon name="passport" size={21} color={colors.blue} /><Text style={s.permissionText}>Read-only access to Gmail. Trotter can’t send or change your emails. Connecting is optional.</Text></View> : null}
      {waiting ? <View style={s.waiting}><ActivityIndicator color={colors.blue} /><Text style={s.description}>Waiting for your permission…</Text></View> : null}
      {(error || gmailConnectionError || (gmailConnected && gmailSyncError)) ? <Text style={s.error} accessibilityRole="alert">{error || gmailConnectionError || gmailSyncError}</Text> : null}
      <PressFeedback accessibilityRole="button" disabled={finishing || waiting} accessibilityState={{ disabled: finishing || waiting, busy: finishing || waiting }} onPress={gmailConnected ? () => void finish(false) : connect} style={[s.primary, (finishing || waiting) && s.disabled]}>
        {finishing ? <ActivityIndicator size="small" color={colors.paperSoft} /> : null}<Text style={s.primaryText}>{finishing ? 'Finishing…' : gmailConnected ? 'Continue to Trotter' : waiting ? 'Connecting…' : 'Connect Gmail'}</Text>
      </PressFeedback>
      {!gmailConnected ? <PressFeedback accessibilityRole="button" disabled={finishing} style={s.skip} onPress={() => void finish(true)}><Text style={s.link}>Not now</Text></PressFeedback> : null}
      {!gmailConnected ? <Text style={s.footnote}>You can connect later in Profile.</Text> : null}
    </ScrollView>
  </View>;
}
const s = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.paperSoft }, content: { width: '100%', maxWidth: 580, alignSelf: 'center', paddingHorizontal: 24 }, icon: { alignSelf: 'flex-start', marginTop: 33, marginBottom: 30 },
  title: { fontFamily: fonts.display, fontSize: 35, lineHeight: 41, color: colors.ink, marginBottom: 16, maxWidth: 350 }, description: { fontFamily: fonts.sansRegular, fontSize: 14, lineHeight: 22, color: colors.mutedInk },
  permission: { marginVertical: 30, paddingVertical: 20, borderTopWidth: 1, borderBottomWidth: 1, borderColor: colors.paperBorder, flexDirection: 'row', gap: 13 }, permissionText: { fontFamily: fonts.sansRegular, fontSize: 12, lineHeight: 20, color: colors.mutedInk, flex: 1 },
  waiting: { flexDirection: 'row', alignItems: 'center', gap: 10, marginBottom: 18 }, primary: { minHeight: 52, paddingVertical: 14, paddingHorizontal: 18, backgroundColor: colors.blue, borderRadius: 3, alignItems: 'center', justifyContent: 'center', flexDirection: 'row', gap: 9, marginTop: 18 }, primaryText: { fontFamily: fonts.sans, fontSize: 14, lineHeight: 21, color: colors.paperSoft }, skip: { minHeight: 52, alignItems: 'center', justifyContent: 'center', marginTop: 6 }, link: { fontFamily: fonts.sans, fontSize: 13, lineHeight: 20, color: colors.blue }, disabled: { opacity: .5 },
  footnote: { fontFamily: fonts.sansRegular, fontSize: 12, lineHeight: 19, color: colors.mutedInk, textAlign: 'center', marginTop: 14 }, error: { fontFamily: fonts.sansRegular, fontSize: 13, lineHeight: 20, color: colors.redDeep, marginTop: 15 },
});
