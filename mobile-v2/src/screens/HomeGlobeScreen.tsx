import React from 'react';
import { Pressable, ScrollView, StyleSheet, Text, useWindowDimensions, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { GlobeScene } from '../components/GlobeScene';
import {
  BottomNav,
  IconGlyph,
  NewFlightsBanner,
  SplitFlapStatsPanel,
  SyncStatusPill,
  TrotterHeaderTag,
} from '../components/trotter/TrotterKit';
import { BottomNavTab } from '../data/trotterMock';
import { FlightRoute, RoutePoint } from '../data/demoTravel';
import { useTravelTrips } from '../services/travelTrips';
import { colors, fonts, layout, spacing } from '../theme/trotterTheme';
import { getMobileVisualWidth } from '../utils/mobileLayout';

export function HomeGlobeScreen({ active, onChange }: { active: BottomNavTab; onChange: (tab: BottomNavTab) => void }) {
  const insets = useSafeAreaInsets();
  const { width, height } = useWindowDimensions();
  const visualWidth = getMobileVisualWidth(width);
  const screenPadding = visualWidth < 390 ? 16 : layout.screenPadding;
  const contentWidth = visualWidth - screenPadding * 2;
  const globeHeight = Math.max(470, Math.min(540, height * 0.55));
  const { trips, profile, source, status, lastSyncedAt, syncFromGmail } = useTravelTrips();
  const isInitialLiveLoading = status === 'loading' && source !== 'api';
  const displayedTrips = isInitialLiveLoading ? [] : trips;
  const displayedProfile = isInitialLiveLoading
    ? { ...profile, flights: 0, countries: 0, airports: 0, airlines: 0, miles: 0, hoursInAir: 0 }
    : profile;
  const liveRoutes = React.useMemo(() => displayedTrips.flatMap((trip) =>
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
  ), [displayedTrips]);
  const livePoints = React.useMemo(() => {
    const points = new Map<string, RoutePoint>();
    liveRoutes.forEach((route) => {
      points.set(route.from.code, route.from);
      points.set(route.to.code, route.to);
    });
    return Array.from(points.values());
  }, [liveRoutes]);
  const travelYears = React.useMemo(() => {
    const years = displayedTrips
      .map((trip) => Number(trip.startDate.slice(0, 4)))
      .filter((year) => Number.isFinite(year) && year > 1900)
      .sort((a, b) => b - a);
    return {
      latest: years[0] ?? new Date().getFullYear(),
      count: new Set(years).size,
    };
  }, [displayedTrips]);
  const [selectedRoute, setSelectedRoute] = React.useState<FlightRoute | null>(null);
  const syncLabel = source === 'api'
    ? `Updated ${formatSyncTime(lastSyncedAt)}`
    : status === 'loading' || status === 'syncing'
      ? 'Connecting...'
      : 'Snapshot mode';
  return (
    <View style={[styles.screen, { paddingTop: insets.top + 12 }]}>
      <ScrollView
        showsVerticalScrollIndicator={false}
        contentContainerStyle={{ paddingBottom: insets.bottom + layout.bottomNavHeight + 24, width: visualWidth }}
      >
        <View style={[styles.topRow, { paddingHorizontal: screenPadding }]}>
          <TrotterHeaderTag width={contentWidth} year={travelYears.latest} />
          <View style={[styles.statsWrap, { width: contentWidth }]}>
            <SplitFlapStatsPanel width={contentWidth} compact flights={displayedProfile.flights} countries={displayedProfile.countries} airports={displayedProfile.airports} />
          </View>
        </View>

        <View style={[styles.syncRow, { marginHorizontal: screenPadding }]}>
          <SyncStatusPill lastSyncedLabel={syncLabel} sourceLabel={source === 'api' ? 'LIVE DATABASE' : 'LOCAL ARCHIVE'} />
        </View>

        <View style={[styles.globeWrap, { height: globeHeight }]}>
          <View pointerEvents="none" style={[styles.mapEyebrow, { left: screenPadding }]}>
            <Text allowFontScaling={false} style={styles.mapEyebrowLabel}>FLIGHT MAP</Text>
            <Text allowFontScaling={false} style={styles.mapEyebrowValue}>{travelYears.latest} / {liveRoutes.length} ROUTES</Text>
          </View>
          <GlobeScene
            key={`live-globe-${source}-${liveRoutes.length}`}
            routes={liveRoutes}
            mapPoints={livePoints}
            onRoutePress={setSelectedRoute}
          />
          <View pointerEvents="none" style={[styles.mapMetric, { left: screenPadding }]}>
            <IconGlyph name="plane" color={colors.brassSoft} size={17} />
            <View>
              <Text allowFontScaling={false} style={styles.mapMetricValue}>{displayedProfile.miles.toLocaleString()} mi</Text>
              <Text allowFontScaling={false} style={styles.mapMetricLabel}>LIFETIME DISTANCE</Text>
            </View>
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
            count={displayedProfile.flights}
            eyebrow={isInitialLiveLoading ? 'LOADING LIVE FLIGHTS' : source === 'api' ? 'LIVE FLIGHTS' : `${travelYears.count} YEARS LOGGED`}
            title={isInitialLiveLoading ? 'Loading live trips' : status === 'syncing' ? 'Syncing Gmail trips' : 'Sync Gmail trips'}
            sourceLabel={source === 'api' ? 'live database' : 'Google'}
            actionLabel={status === 'syncing' ? 'SYNCING' : 'SYNC'}
            onReview={syncFromGmail}
            disabled={status === 'syncing'}
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
    gap: 10,
  },
  statsWrap: {
    flexShrink: 1,
    minWidth: 0,
  },
  syncRow: {
    zIndex: 6,
    marginTop: 10,
  },
  globeWrap: {
    marginTop: 4,
    justifyContent: 'center',
    overflow: 'hidden',
  },
  mapEyebrow: {
    position: 'absolute',
    top: 14,
    zIndex: 5,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: colors.darkBorder,
    backgroundColor: 'rgba(21, 20, 18, 0.9)',
    paddingHorizontal: 9,
    paddingVertical: 7,
  },
  mapEyebrowLabel: {
    color: colors.subtleText,
    fontFamily: fonts.sansBold,
    fontSize: 9,
    letterSpacing: 1.4,
  },
  mapEyebrowValue: {
    color: colors.creamText,
    fontFamily: fonts.mono,
    fontSize: 12,
    marginTop: 3,
  },
  mapMetric: {
    position: 'absolute',
    bottom: 16,
    zIndex: 5,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 9,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: colors.darkBorder,
    backgroundColor: 'rgba(21, 20, 18, 0.92)',
    paddingHorizontal: 12,
    paddingVertical: 9,
  },
  mapMetricValue: {
    color: colors.creamText,
    fontFamily: fonts.mono,
    fontSize: 14,
  },
  mapMetricLabel: {
    color: colors.subtleText,
    fontFamily: fonts.sansBold,
    fontSize: 7,
    letterSpacing: 0.8,
    marginTop: 1,
  },
  bannerWrap: {
    marginTop: 12,
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
