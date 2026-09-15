import React from 'react';
import { ActivityIndicator, Image, RefreshControl, ScrollView, StyleSheet, Switch, Text, useWindowDimensions, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { BottomNav } from '../components/trotter/TrotterKit';
import { WWHeader, WWIcon } from '../components/world-window/WorldWindowUI';
import { PressFeedback } from '../components/world-window/motion';
import { TravelerCard } from '../components/world-window/profile/TravelerCard';
import { HomeAirportPicker } from '../components/world-window/profile/HomeAirportPicker';
import type { BottomNavTab } from '../data/trotterMock';
import airports from '../data/collections/airports.json';
import { getApiBaseUrl, useTravelTrips } from '../services/travelTrips';
import { useExperiencePreferences, selectionHaptic } from '../utils/experiencePreferences';
import { useTravelerIdentity } from '../utils/travelerIdentity';
import { getMobileVisualWidth } from '../utils/mobileLayout';
import { colors, fonts, layout } from '../theme/trotterTheme';

export function ProfileScreen({ active, onChange, onOpenAirport }: {
  active: BottomNavTab; onChange: (tab: BottomNavTab) => void; onOpenStamps?: () => void; onOpenAirport?: (code: string) => void;
}) {
  const insets = useSafeAreaInsets();
  const { width, fontScale } = useWindowDimensions();
  const visualWidth = getMobileVisualWidth(width);
  const large = fontScale >= 1.35 || visualWidth < 350;
  const preferences = useExperiencePreferences();
  const { profile, trips, status, error, accountId, accountEmail, lastSyncedAt, gmailSyncStatus, gmailSyncError, lastGmailSyncedAt, refresh, syncFromGmail, signOut } = useTravelTrips();
  const identity = useTravelerIdentity(accountId ? `${getApiBaseUrl()}/${accountId}` : undefined);
  const [choosingHome, setChoosingHome] = React.useState(false);
  const busy = ['loading', 'refreshing', 'syncing'].includes(status);
  const scanning = gmailSyncStatus === 'syncing' || status === 'syncing';
  const home = airports.entries.find(entry => entry.key === identity.homeAirport);
  const segments = React.useMemo(() => [...new Map(trips.flatMap(trip => trip.segments ?? [])
    .filter(segment => Number.isFinite(Date.parse(segment.depTime)) && Date.parse(segment.depTime) <= Date.now())
    .map(segment => [segment.id, segment])).values()], [trips]);
  const firstYear = profile.firstFlightDate?.match(/^\d{4}/)?.[0];
  const syncCopy = scanning ? 'Finding flight confirmations…' : gmailSyncStatus === 'error' ? 'Scan needs attention' : lastGmailSyncedAt ? `Last scan · ${formatUpdated(lastGmailSyncedAt)}` : 'Ready to scan for flights';
  return <View style={[s.screen, { paddingTop: insets.top }]}>
    <ScrollView showsVerticalScrollIndicator={false} contentContainerStyle={{ paddingBottom: insets.bottom + layout.bottomNavHeight + 22 }}
      refreshControl={<RefreshControl refreshing={status === 'refreshing'} onRefresh={() => void refresh()} tintColor={colors.blue} />}>
      <WWHeader title="Profile" />
      <View style={[s.content, { width: Math.min(visualWidth - 48, 592) }]}>
        <TravelerCard name={profile.name} firstYear={firstYear} homeAirport={identity.homeAirport} homeCity={home?.city || home?.name} segments={segments} ready={identity.ready}
          onChooseHome={() => setChoosingHome(true)} onOpenAirport={onOpenAirport} />
        {identity.error ? <Text style={s.error} accessibilityRole="alert">{identity.error}</Text> : null}
        <View style={s.connection}>
          <View style={s.sectionHeading}><Text style={s.overline}>FLIGHT CONFIRMATIONS</Text>
            {gmailSyncStatus === 'synced' && !scanning ? <Text style={s.success} accessibilityLabel="Scan complete">✓</Text> : null}
          </View>
          <View style={[s.provider, large && s.providerLarge]}>
            <View style={s.providerCopy}><Text style={s.providerName}>Gmail</Text><Text style={s.secondary} accessibilityLiveRegion="polite">{syncCopy}</Text></View>
            <PressFeedback accessibilityRole="button" accessibilityLabel="Scan Gmail for flights" accessibilityState={{ disabled: busy, busy: scanning }} disabled={busy} onPress={() => void syncFromGmail()} style={[s.scan, large && s.scanLarge, busy && s.disabled]}>
              {scanning ? <ActivityIndicator color={colors.blue} size="small" /> : <WWIcon name="sync" size={17} color={colors.blue} />}
              <Text style={s.scanText}>{scanning ? 'Scanning…' : 'Scan for flights'}</Text>
            </PressFeedback>
          </View>
          {scanning ? <Text style={s.note}>Your scan continues if you leave the app.</Text> : null}
          {gmailSyncError ? <Text style={s.error} accessibilityRole="alert">{gmailSyncError}</Text> : null}
        </View>
        <View style={s.preferences}>
          <Text style={s.overline}>PREFERENCES</Text>
          <Text style={s.preferenceTitle}>Globe appearance</Text>
          <View style={[s.textures, large && s.texturesLarge]}>
            {(['classic', 'nasa'] as const).map(texture => <PressFeedback key={texture} accessibilityRole="radio" accessibilityLabel={texture === 'classic' ? 'Classic globe' : 'NASA globe'} accessibilityState={{ selected: preferences.texture === texture }}
              onPress={() => { preferences.setTexture(texture); selectionHaptic(); }} style={[s.texture, preferences.texture === texture && s.textureSelected]}>
              <View accessible={false} style={[s.swatch, texture === 'classic' ? s.classic : s.nasa]}>
                {texture === 'classic' ? <WWIcon name="globe" size={22} color={colors.ink} /> : <Image source={require('../../assets/world-window/nasa-day-base-2048.jpg')} style={s.nasaImage} />}
              </View>
              <Text style={s.textureLabel}>{texture === 'classic' ? 'Classic' : 'NASA'}</Text>
              <Text accessible={false} style={[s.textureCheck, preferences.texture !== texture && { opacity: 0 }]}>✓</Text>
            </PressFeedback>)}
          </View>
          <View style={s.haptics}><View style={s.hapticCopy}><Text style={s.preferenceTitle}>Tactile feedback</Text><Text style={s.secondary}>Page turns and confirmations</Text></View>
            <Switch accessibilityLabel="Tactile feedback" value={preferences.haptics} onValueChange={preferences.setHaptics} trackColor={{ false: colors.paperBorder, true: colors.blue }} thumbColor={colors.paperSoft} hitSlop={10} />
          </View>
        </View>
        <View style={s.account}>
          <Text style={s.overline}>GOOGLE ACCOUNT</Text><Text selectable style={s.email}>{accountEmail}</Text>
          <View style={s.accountBottom}><Text style={s.note}>{lastSyncedAt ? `Updated ${formatUpdated(lastSyncedAt)}` : 'Connected with Google'}</Text>
            <PressFeedback accessibilityRole="button" onPress={() => void signOut()} style={s.signOut}><Text style={s.signOutText}>Sign out</Text><WWIcon name="logout" size={16} color={colors.mutedInk} /></PressFeedback>
          </View>
          {error && error !== gmailSyncError ? <Text style={s.error} accessibilityRole="alert">{error}</Text> : null}
        </View>
      </View>
    </ScrollView>
    <BottomNav active={active} onChange={onChange} />
    {choosingHome ? <HomeAirportPicker selected={identity.homeAirport} onClose={() => setChoosingHome(false)} onSave={async code => { await identity.setHomeAirport(code); selectionHaptic('confirmation'); }} /> : null}
  </View>;
}
function formatUpdated(value: string) {
  const date = new Date(value);
  return Number.isFinite(date.getTime()) ? date.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }) : 'recently';
}
const s = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.paperSoft }, content: { alignSelf: 'center' },
  connection: { marginTop: 25, paddingBottom: 22, borderBottomWidth: 1, borderBottomColor: colors.paperBorder },
  sectionHeading: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' }, overline: { fontFamily: fonts.mono, fontSize: 10, lineHeight: 16, letterSpacing: .7, color: colors.mutedInk },
  success: { fontFamily: fonts.sans, fontSize: 16, color: colors.green }, provider: { flexDirection: 'row', alignItems: 'center', gap: 16, marginTop: 10 }, providerLarge: { flexWrap: 'wrap' },
  providerCopy: { flex: 1, gap: 4, minWidth: 130 }, providerName: { fontFamily: fonts.display, fontSize: 25, lineHeight: 30, color: colors.ink },
  secondary: { fontFamily: fonts.sansRegular, fontSize: 11, lineHeight: 17, color: colors.mutedInk }, scan: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 7, minHeight: 44, paddingHorizontal: 10, borderWidth: 1, borderColor: colors.paperBorder, borderRadius: 3 }, scanLarge: { width: '100%' }, scanText: { fontFamily: fonts.sans, fontSize: 11, lineHeight: 17, color: colors.blue }, disabled: { opacity: .5 },
  preferences: { paddingTop: 21 }, preferenceTitle: { fontFamily: fonts.sans, fontSize: 14, lineHeight: 21, color: colors.ink, marginTop: 8 }, textures: { flexDirection: 'row', gap: 10, paddingVertical: 11 }, texturesLarge: { flexDirection: 'column' },
  texture: { flex: 1, minHeight: 55, padding: 10, gap: 9, flexDirection: 'row', alignItems: 'center', borderWidth: 1, borderColor: colors.paperBorder, borderRadius: 3 }, textureSelected: { borderColor: colors.blue, backgroundColor: '#EFF1E8' }, textureLabel: { fontFamily: fonts.sans, fontSize: 12, lineHeight: 18, color: colors.ink, flex: 1 }, textureCheck: { fontSize: 13, color: colors.blue },
  swatch: { width: 28, height: 28, borderRadius: 14, alignItems: 'center', justifyContent: 'center', overflow: 'hidden' }, classic: { backgroundColor: '#B3CDD0' }, nasa: { backgroundColor: '#133047' }, nasaImage: { width: 56, height: 28 },
  haptics: { flexDirection: 'row', alignItems: 'center', gap: 14, paddingTop: 8, paddingBottom: 21 }, hapticCopy: { flex: 1, gap: 4 },
  account: { borderTopWidth: 1, borderTopColor: colors.paperBorder, paddingTop: 21 }, email: { fontFamily: fonts.sansRegular, fontSize: 13, lineHeight: 21, color: colors.ink, marginTop: 9 }, accountBottom: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between', gap: 10 },
  note: { fontFamily: fonts.sansRegular, fontSize: 10, lineHeight: 17, color: colors.mutedInk, marginTop: 7 }, signOut: { minHeight: 44, flexDirection: 'row', alignItems: 'center', gap: 7 }, signOutText: { fontFamily: fonts.sansRegular, fontSize: 11, color: colors.mutedInk },
  error: { fontFamily: fonts.sansRegular, fontSize: 12, lineHeight: 18, color: colors.redDeep, marginTop: 10 },
});
