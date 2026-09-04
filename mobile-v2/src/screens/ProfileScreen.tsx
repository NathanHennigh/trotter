import React from 'react';
import { Pressable, RefreshControl, ScrollView, StyleSheet, Text, useWindowDimensions, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { BottomNav, IconGlyph, PaperSurface, ScreenHeader } from '../components/trotter/TrotterKit';
import { BottomNavTab } from '../data/trotterMock';
import { useTravelTrips } from '../services/travelTrips';
import { colors, fonts, layout, spacing } from '../theme/trotterTheme';
import { getMobileVisualWidth } from '../utils/mobileLayout';

export function ProfileScreen({
  active,
  onChange,
  onOpenStamps,
}: {
  active: BottomNavTab;
  onChange: (tab: BottomNavTab) => void;
  onOpenStamps: () => void;
}) {
  const insets = useSafeAreaInsets();
  const { width } = useWindowDimensions();
  const visualWidth = getMobileVisualWidth(width);
  const screenPadding = visualWidth < 390 ? 16 : layout.screenPadding;
  const contentWidth = visualWidth - screenPadding * 2;
  const archiveCardWidth = (contentWidth - layout.cardGap) / 2;
  const { trips, profile, source, status, error, accountEmail, lastSyncedAt, refresh, syncFromGmail } = useTravelTrips();
  const busy = status === 'loading' || status === 'refreshing' || status === 'syncing';
  const initial = profile.name.trim().charAt(0).toUpperCase() || 'T';
  const connectionLabel = source === 'api' ? 'LIVE ARCHIVE' : 'LOCAL SNAPSHOT';
  const syncTitle = status === 'syncing'
    ? 'Scanning your flight emails'
    : source === 'api'
      ? 'Your archive is connected'
      : 'Connect your travel archive';

  return (
    <View style={[styles.screen, { paddingTop: insets.top + 12 }]}>
      <ScrollView
        showsVerticalScrollIndicator={false}
        refreshControl={<RefreshControl refreshing={status === 'loading' || status === 'refreshing'} onRefresh={refresh} tintColor={colors.red} />}
        contentContainerStyle={{ paddingBottom: insets.bottom + layout.bottomNavHeight + 24, width: visualWidth }}
      >
        <ScreenHeader title="PROFILE" subtitle="ACCOUNT & ARCHIVE" />

        <PaperSurface radius={18} padding={spacing.lg} style={[styles.accountCard, { marginHorizontal: screenPadding, width: contentWidth }]}>
          <View style={styles.accountTop}>
            <View style={styles.avatar}>
              <Text allowFontScaling={false} style={styles.avatarText}>{initial}</Text>
            </View>
            <View style={styles.accountCopy}>
              <Text allowFontScaling={false} numberOfLines={1} adjustsFontSizeToFit style={styles.accountName}>{profile.name}</Text>
              <Text allowFontScaling={false} numberOfLines={1} ellipsizeMode="tail" style={styles.accountEmail}>
                {accountEmail ?? 'Sign in to connect Gmail'}
              </Text>
              <View style={[styles.sourceBadge, source === 'api' && styles.sourceBadgeLive]}>
                <View style={[styles.sourceDot, source === 'api' && styles.sourceDotLive]} />
                <Text allowFontScaling={false} style={styles.sourceBadgeText}>{connectionLabel}</Text>
              </View>
            </View>
          </View>

          <View style={styles.profileDetails}>
            <ProfileDetail label="HOME AIRPORT" value={profile.homeAirport} />
            <ProfileDetail label="TRAVELING SINCE" value={profile.firstFlightDate.slice(0, 4)} />
            <ProfileDetail label="LAST UPDATED" value={formatLastUpdated(lastSyncedAt)} />
          </View>
        </PaperSurface>

        <Text allowFontScaling={false} style={[styles.sectionTitle, { marginHorizontal: screenPadding }]}>YOUR ARCHIVE</Text>
        <View style={[styles.statsGrid, { paddingHorizontal: screenPadding, gap: layout.cardGap, width: visualWidth }]}>
          <ArchiveStat width={archiveCardWidth} icon="plane" label="FLIGHTS" value={profile.flights.toLocaleString()} />
          <ArchiveStat width={archiveCardWidth} icon="suitcase" label="TRIPS" value={trips.length.toLocaleString()} />
          <ArchiveStat width={archiveCardWidth} icon="globe" label="COUNTRIES" value={profile.countries.toLocaleString()} />
          <ArchiveStat width={archiveCardWidth} icon="crosshair" label="AIRPORTS" value={profile.airports.toLocaleString()} />
        </View>

        <PaperSurface radius={16} padding={spacing.lg} style={[styles.syncCard, { marginHorizontal: screenPadding, width: contentWidth }]}>
          <View style={styles.syncHeader}>
            <View style={styles.syncIcon}>
              <IconGlyph name="plane" color={colors.creamText} size={21} />
            </View>
            <View style={styles.syncCopy}>
              <Text allowFontScaling={false} style={styles.syncEyebrow}>GMAIL FLIGHT SYNC</Text>
              <Text allowFontScaling={false} numberOfLines={2} style={styles.syncTitle}>{syncTitle}</Text>
            </View>
          </View>
          <Text style={[styles.syncDescription, error ? styles.syncError : null]}>
            {error ?? (status === 'syncing'
              ? 'The import continues on the server even if you close Trotter.'
              : 'Trotter reads flight confirmations to keep trips, routes, and passport stats current.')}
          </Text>
          <Pressable disabled={busy} onPress={syncFromGmail} style={[styles.syncButton, busy && styles.syncButtonDisabled]}>
            <Text allowFontScaling={false} style={styles.syncButtonText}>{status === 'syncing' ? 'SYNC IN PROGRESS' : source === 'api' ? 'SYNC NEW FLIGHTS' : 'CONNECT GOOGLE'}</Text>
          </Pressable>
        </PaperSurface>

        <Pressable onPress={onOpenStamps} style={[styles.stampsLink, { marginHorizontal: screenPadding, width: contentWidth }]}>
          <View style={styles.stampsIcon}><IconGlyph name="passport" color={colors.red} size={22} /></View>
          <View style={styles.stampsCopy}>
            <Text allowFontScaling={false} style={styles.stampsTitle}>COUNTRY ARRIVAL STAMPS</Text>
            <Text allowFontScaling={false} style={styles.stampsSub}>View the first city, airport, and date for each country</Text>
          </View>
          <Text allowFontScaling={false} style={styles.stampsArrow}>{'>'}</Text>
        </Pressable>
      </ScrollView>
      <BottomNav active={active} onChange={onChange} />
    </View>
  );
}

function ProfileDetail({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.profileDetail}>
      <Text allowFontScaling={false} style={styles.profileDetailLabel}>{label}</Text>
      <Text allowFontScaling={false} numberOfLines={1} adjustsFontSizeToFit style={styles.profileDetailValue}>{value}</Text>
    </View>
  );
}

function ArchiveStat({ icon, label, value, width }: { icon: string; label: string; value: string; width: number }) {
  return (
    <PaperSurface radius={12} padding={spacing.md} style={[styles.archiveStat, { width }]}>
      <View style={styles.archiveStatTop}>
        <IconGlyph name={icon} color={colors.red} size={18} />
        <Text allowFontScaling={false} style={styles.archiveStatLabel}>{label}</Text>
      </View>
      <Text allowFontScaling={false} numberOfLines={1} adjustsFontSizeToFit style={styles.archiveStatValue}>{value}</Text>
    </PaperSurface>
  );
}

function formatLastUpdated(value?: string) {
  if (!value) return 'Not yet';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return 'Recently';
  return parsed.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
    backgroundColor: colors.paperSoft,
  },
  accountCard: {
    marginTop: spacing.sm,
  },
  accountTop: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
  },
  avatar: {
    width: 54,
    height: 54,
    borderRadius: 27,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.dashboard,
  },
  avatarText: {
    color: colors.brassSoft,
    fontFamily: fonts.display,
    fontSize: 24,
  },
  accountCopy: {
    flex: 1,
    minWidth: 0,
  },
  accountName: {
    color: colors.ink,
    fontFamily: fonts.display,
    fontSize: 22,
  },
  accountEmail: {
    color: colors.mutedInk,
    fontFamily: fonts.sansRegular,
    fontSize: 11,
    marginTop: 2,
  },
  sourceBadge: {
    alignSelf: 'flex-start',
    maxWidth: 76,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: colors.paperBorder,
    paddingHorizontal: 7,
    paddingVertical: 5,
    marginTop: 6,
  },
  sourceBadgeLive: {
    borderColor: colors.green,
  },
  sourceDot: {
    width: 6,
    height: 6,
    borderRadius: 3,
    backgroundColor: colors.mustard,
  },
  sourceDotLive: {
    backgroundColor: colors.green,
  },
  sourceBadgeText: {
    flexShrink: 1,
    color: colors.mutedInk,
    fontFamily: fonts.sansBold,
    fontSize: 6.5,
    letterSpacing: 0.3,
  },
  profileDetails: {
    flexDirection: 'row',
    marginTop: spacing.lg,
    paddingTop: spacing.md,
    borderTopWidth: 1,
    borderTopColor: colors.paperBorder,
  },
  profileDetail: {
    flex: 1,
    minWidth: 0,
    paddingHorizontal: spacing.sm,
  },
  profileDetailLabel: {
    color: colors.mutedInk,
    fontFamily: fonts.sansBold,
    fontSize: 7,
    letterSpacing: 0.5,
  },
  profileDetailValue: {
    color: colors.ink,
    fontFamily: fonts.mono,
    fontSize: 12,
    marginTop: 4,
  },
  sectionTitle: {
    color: colors.ink,
    fontFamily: fonts.sansBold,
    fontSize: 12,
    letterSpacing: 1.1,
    marginTop: spacing.xl,
    marginBottom: spacing.sm,
  },
  statsGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
  },
  archiveStat: {
    minHeight: 92,
  },
  archiveStatTop: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  archiveStatLabel: {
    color: colors.mutedInk,
    fontFamily: fonts.sansBold,
    fontSize: 9,
    letterSpacing: 0.6,
  },
  archiveStatValue: {
    color: colors.ink,
    fontFamily: fonts.display,
    fontSize: 28,
    marginTop: 8,
  },
  syncCard: {
    marginTop: spacing.lg,
  },
  syncHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
  },
  syncIcon: {
    width: 42,
    height: 42,
    borderRadius: 21,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.dashboard,
  },
  syncCopy: {
    flex: 1,
    minWidth: 0,
  },
  syncEyebrow: {
    color: colors.red,
    fontFamily: fonts.sansBold,
    fontSize: 8,
    letterSpacing: 0.9,
  },
  syncTitle: {
    color: colors.ink,
    fontFamily: fonts.sansSemi,
    fontSize: 17,
    lineHeight: 20,
    marginTop: 2,
  },
  syncDescription: {
    color: colors.mutedInk,
    fontFamily: fonts.sansRegular,
    fontSize: 12,
    lineHeight: 18,
    marginTop: spacing.md,
  },
  syncError: {
    color: colors.redDeep,
  },
  syncButton: {
    minHeight: 44,
    marginTop: spacing.md,
    borderRadius: 9,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.dashboard,
  },
  syncButtonDisabled: {
    opacity: 0.5,
  },
  syncButtonText: {
    color: colors.creamText,
    fontFamily: fonts.sansBold,
    fontSize: 11,
    letterSpacing: 0.7,
  },
  stampsLink: {
    minHeight: 72,
    marginTop: spacing.md,
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: colors.paperBorder,
    backgroundColor: colors.paper,
    padding: spacing.md,
  },
  stampsIcon: {
    width: 38,
    height: 38,
    borderRadius: 19,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.paperSoft,
  },
  stampsCopy: {
    flex: 1,
    minWidth: 0,
  },
  stampsTitle: {
    color: colors.ink,
    fontFamily: fonts.sansBold,
    fontSize: 11,
    letterSpacing: 0.6,
  },
  stampsSub: {
    color: colors.mutedInk,
    fontFamily: fonts.sansRegular,
    fontSize: 10,
    marginTop: 3,
  },
  stampsArrow: {
    color: colors.mutedInk,
    fontFamily: fonts.sansBold,
    fontSize: 17,
  },
});
