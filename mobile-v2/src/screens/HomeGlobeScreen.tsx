import React from 'react';
import { Pressable, ScrollView, StyleSheet, Text, useWindowDimensions, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { GlobeScene } from '../components/GlobeScene';
import {
  BottomNav,
  DarkPanel,
  IconButton,
  IconGlyph,
  NewFlightsBanner,
  PassportViewButton,
  SplitFlapNumber,
  SplitFlapStatsPanel,
  SyncStatusPill,
  TrotterHeaderTag,
} from '../components/trotter/TrotterKit';
import { BottomNavTab } from '../data/trotterMock';
import { FlightRoute, RoutePoint } from '../data/demoTravel';
import { useTravelTrips } from '../services/travelTrips';
import { colors, fonts, layout, spacing } from '../theme/trotterTheme';

export function HomeGlobeScreen({ active, onChange }: { active: BottomNavTab; onChange: (tab: BottomNavTab) => void }) {
  const insets = useSafeAreaInsets();
  const { width, height } = useWindowDimensions();
  const screenPadding = width < 390 ? 16 : layout.screenPadding;
  const contentWidth = width - screenPadding * 2;
  const headerGap = width < 390 ? 8 : 10;
  const headerTagWidth = Math.floor(contentWidth * (width < 390 ? 0.53 : 0.54));
  const statsWidth = contentWidth - headerTagWidth - headerGap;
  const globeHeight = Math.max(540, Math.min(650, height * 0.66));
  const { trips, profile, source, status, lastSyncedAt, syncFromGmail } = useTravelTrips();
  const liveRoutes = React.useMemo(() => trips.flatMap((trip) =>
    (trip.segments ?? []).flatMap((segment) => {
      if (!segment.depPoint || !segment.arrPoint) return [];
      return [{
        id: segment.id,
        from: segment.depPoint,
        to: segment.arrPoint,
        tripTitle: trip.title,
        depTime: segment.depTime,
        arrTime: segment.arrTime,
        airline: segment.airline,
        flightNumber: segment.flightNumber,
        distanceKm: segment.distanceMiles ? segment.distanceMiles / 0.621371 : undefined,
      } satisfies FlightRoute];
    })
  ), [trips]);
  const livePoints = React.useMemo(() => {
    const points = new Map<string, RoutePoint>();
    liveRoutes.forEach((route) => {
      points.set(route.from.code, route.from);
      points.set(route.to.code, route.to);
    });
    return Array.from(points.values());
  }, [liveRoutes]);
  const [selectedRoute, setSelectedRoute] = React.useState<FlightRoute | null>(null);
  const syncLabel = source === 'api'
    ? `Synced ${formatSyncTime(lastSyncedAt)}`
    : status === 'loading' || status === 'syncing'
      ? 'Connecting...'
      : 'Snapshot mode';
  return (
    <View style={[styles.screen, { paddingTop: insets.top + 12 }]}>
      <ScrollView
        showsVerticalScrollIndicator={false}
        contentContainerStyle={{ paddingBottom: insets.bottom + layout.bottomNavHeight + 24 }}
      >
        <View style={[styles.topRow, { paddingHorizontal: screenPadding, gap: headerGap }]}>
          <TrotterHeaderTag width={headerTagWidth} />
          <View style={[styles.statsWrap, { width: statsWidth }]}>
            <SplitFlapStatsPanel width={statsWidth} compact flights={profile.flights} countries={profile.countries} airports={profile.airports} />
            <SyncStatusPill lastSyncedLabel={syncLabel} sourceLabel={source === 'api' ? 'Live DB' : 'Local'} />
          </View>
        </View>

        <View style={[styles.filterRow, { paddingHorizontal: screenPadding }]}>
          <DarkPanel padding={spacing.sm} radius={8} style={styles.yearChip}>
            <Text allowFontScaling={false} style={styles.yearText}>2025</Text>
            <Text allowFontScaling={false} style={styles.chevron}>v</Text>
          </DarkPanel>
          <View style={styles.controlStack}>
            <IconButton variant="dark" shape="circle" icon={<IconGlyph name="crosshair" size={23} />} />
            <IconButton variant="dark" shape="circle" icon={<IconGlyph name="sliders" size={23} />} />
          </View>
        </View>

        <View style={[styles.globeWrap, { height: globeHeight }]}>
          <GlobeScene
            key={`live-globe-${source}-${liveRoutes.length}`}
            routes={liveRoutes}
            mapPoints={livePoints}
            onRoutePress={setSelectedRoute}
          />
          <DarkPanel padding={spacing.sm} radius={12} style={[styles.milesCard, { left: screenPadding }]}>
            <View style={styles.milesTop}>
              <IconGlyph name="plane" color={colors.creamText} size={20} />
              <Text allowFontScaling={false} style={styles.milesLabel}>YOU'VE FLOWN</Text>
            </View>
            <SplitFlapNumber value={profile.miles} />
            <Text allowFontScaling={false} style={styles.milesUnit}>MILES</Text>
          </DarkPanel>
          <View style={[styles.passportButtonWrap, { right: screenPadding }]}>
            <PassportViewButton />
          </View>
          {selectedRoute ? (
            <TripArcModal
              route={selectedRoute}
              onClose={() => setSelectedRoute(null)}
              onViewTrip={() => {
                setSelectedRoute(null);
                onChange('trips');
              }}
            />
          ) : null}
        </View>
        <View style={[styles.bannerWrap, { width: contentWidth, marginHorizontal: screenPadding }]}>
          <NewFlightsBanner
            count={profile.flights}
            eyebrow={source === 'api' ? 'LIVE FLIGHTS' : 'SYNC READY'}
            title={status === 'syncing' ? 'Syncing Gmail trips' : 'Sync Gmail trips'}
            sourceLabel={source === 'api' ? 'live database' : 'Google'}
            actionLabel={status === 'syncing' ? 'SYNCING' : 'SYNC'}
            onReview={syncFromGmail}
          />
        </View>
      </ScrollView>
      <BottomNav active={active} onChange={onChange} />
    </View>
  );
}

function TripArcModal({
  route,
  onClose,
  onViewTrip,
}: {
  route: FlightRoute;
  onClose: () => void;
  onViewTrip: () => void;
}) {
  const miles = typeof route.distanceKm === 'number' ? Math.round(route.distanceKm * 0.621371).toLocaleString() : undefined;
  const title = route.tripTitle || `${route.from.city} to ${route.to.city}`;
  const flightLabel = [route.airline, route.flightNumber].filter(Boolean).join(' ');

  return (
    <View style={styles.arcModal}>
      <View style={styles.arcModalHeader}>
        <Text allowFontScaling={false} numberOfLines={1} adjustsFontSizeToFit style={styles.arcModalKicker}>FLIGHT PATH</Text>
        <Pressable onPress={onClose} style={styles.arcModalClose}>
          <Text allowFontScaling={false} style={styles.arcModalCloseText}>x</Text>
        </Pressable>
      </View>
      <Text maxFontSizeMultiplier={1.05} numberOfLines={1} adjustsFontSizeToFit style={styles.arcModalTitle}>{title}</Text>
      <Text allowFontScaling={false} numberOfLines={1} style={styles.arcModalRoute}>{route.from.code}{' -> '}{route.to.code}</Text>
      <Text maxFontSizeMultiplier={1.05} numberOfLines={1} style={styles.arcModalMeta}>
        {[formatRouteDate(route.depTime), flightLabel || undefined, miles ? `${miles} mi` : undefined].filter(Boolean).join(' / ')}
      </Text>
      <Pressable onPress={onViewTrip} style={styles.arcModalButton}>
        <Text allowFontScaling={false} style={styles.arcModalButtonText}>VIEW TRIP</Text>
      </Pressable>
    </View>
  );
}

function formatRouteDate(value?: string | null) {
  if (!value) return undefined;
  const parsed = new Date(value.replace(' ', 'T'));
  if (Number.isNaN(parsed.getTime())) return value.split(' ')[0];
  return parsed.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

function formatSyncTime(value?: string) {
  if (!value) return 'just now';
  const parsed = new Date(value).getTime();
  if (Number.isNaN(parsed)) return 'just now';
  const minutes = Math.max(0, Math.round((Date.now() - parsed) / 60000));
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  return `${hours}h ago`;
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
    backgroundColor: colors.appBackground,
  },
  topRow: {
    zIndex: 5,
    flexDirection: 'row',
    alignItems: 'flex-start',
  },
  statsWrap: {
    flexShrink: 1,
    minWidth: 0,
  },
  filterRow: {
    zIndex: 5,
    marginTop: 18,
    paddingHorizontal: spacing.lg,
    flexDirection: 'row',
    justifyContent: 'space-between',
  },
  yearChip: {
    minWidth: 84,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  yearText: {
    color: colors.creamText,
    fontFamily: fonts.sansBold,
    fontSize: 20,
  },
  chevron: {
    color: colors.subtleText,
    fontFamily: fonts.sansBold,
    fontSize: 14,
  },
  controlStack: {
    gap: 12,
  },
  globeWrap: {
    marginTop: -140,
    justifyContent: 'center',
    overflow: 'hidden',
  },
  milesCard: {
    position: 'absolute',
    bottom: 82,
    width: 174,
  },
  milesTop: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    marginBottom: 6,
  },
  milesLabel: {
    color: colors.creamText,
    fontFamily: fonts.sansBold,
    fontSize: 11,
  },
  milesUnit: {
    color: colors.subtleText,
    fontFamily: fonts.sansBold,
    fontSize: 12,
    textAlign: 'right',
    marginTop: 5,
  },
  passportButtonWrap: {
    position: 'absolute',
    bottom: 72,
  },
  bannerWrap: {
    marginTop: -28,
  },
  arcModal: {
    position: 'absolute',
    left: 24,
    right: 24,
    bottom: 84,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: colors.paperBorder,
    backgroundColor: colors.paper,
    padding: spacing.md,
  },
  arcModalHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: spacing.sm,
  },
  arcModalKicker: {
    color: colors.red,
    fontFamily: fonts.sansBold,
    fontSize: 10,
    letterSpacing: 1.2,
  },
  arcModalClose: {
    width: 28,
    height: 28,
    borderRadius: 14,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.dashboard,
  },
  arcModalCloseText: {
    color: colors.creamText,
    fontFamily: fonts.sansBold,
    fontSize: 14,
    lineHeight: 16,
  },
  arcModalTitle: {
    color: colors.ink,
    fontFamily: fonts.display,
    fontSize: 25,
    marginTop: 2,
  },
  arcModalRoute: {
    color: colors.tealDeep,
    fontFamily: fonts.sansBold,
    fontSize: 18,
    letterSpacing: 1,
    marginTop: 3,
  },
  arcModalMeta: {
    color: colors.mutedInk,
    fontFamily: fonts.sansRegular,
    fontSize: 12,
    marginTop: 4,
  },
  arcModalButton: {
    alignSelf: 'flex-start',
    marginTop: spacing.sm,
    borderRadius: 8,
    backgroundColor: colors.dashboard,
    paddingHorizontal: 13,
    paddingVertical: 9,
  },
  arcModalButtonText: {
    color: colors.creamText,
    fontFamily: fonts.sansBold,
    fontSize: 11,
  },
});
