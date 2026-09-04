import React from 'react';
import {
  FlatList,
  Image,
  ImageBackground,
  Platform,
  Pressable,
  RefreshControl,
  StyleSheet,
  Text,
  useWindowDimensions,
  View,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { BottomNav, IconGlyph } from '../components/trotter/TrotterKit';
import { TripCard } from '../components/trotter/TripCard';
import { BottomNavTab, TripSummary } from '../data/trotterMock';
import { useTravelTrips } from '../services/travelTrips';
import { colors, fonts, layout, shadows, spacing } from '../theme/trotterTheme';
import { getMobileVisualWidth } from '../utils/mobileLayout';

const paperTexture = require('../../assets/textures/paper_texture_clean.png');
const tripsReferenceImage = require('../../docs/references/screens/trips-list-reference.png');
const SHOW_REFERENCE_OVERLAY = false;
const REFERENCE_OVERLAY_OPACITY = 0.32;
const SCREEN_PADDING = 24;
const MAX_CONTENT_WIDTH = 430;
const CARD_GAP = 8;

export function TripsListScreen({
  active,
  onChange,
  onOpenTrip,
}: {
  active: BottomNavTab;
  onChange: (tab: BottomNavTab) => void;
  onOpenTrip?: (trip: TripSummary) => void;
}) {
  const insets = useSafeAreaInsets();
  const { width } = useWindowDimensions();
  const { trips, profile, source, status, error, accountEmail, refresh } = useTravelTrips();
  const visualWidth = Math.min(getMobileVisualWidth(width), MAX_CONTENT_WIDTH);
  const screenPadding = SCREEN_PADDING;
  const contentWidth = visualWidth - screenPadding * 2;
  const currentYear = new Date().getFullYear();
  const [activeTab, setActiveTab] = React.useState<'all' | 'year' | 'favorites'>('all');
  const [favorites, setFavorites] = React.useState<Set<string>>(new Set());

  const toggleFavorite = (id: string) => setFavorites(prev => {
    const next = new Set(prev);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });

  const currentYearTrips = trips.filter((trip) => trip.startDate.startsWith(String(currentYear))).length;

  const today = new Date().toISOString().split('T')[0];

  const filteredTrips = trips.filter(trip => {
    if (activeTab === 'year') return trip.startDate.startsWith(String(currentYear));
    if (activeTab === 'favorites') return favorites.has(trip.id);
    return true;
  });

  const upcomingTrips = filteredTrips.filter(trip => trip.startDate >= today);
  const pastTrips = filteredTrips.filter(trip => trip.startDate < today);
  const visibleTrips = [...upcomingTrips, ...pastTrips];

  return (
    <View style={styles.screen}>
      <ImageBackground source={paperTexture} resizeMode="cover" imageStyle={styles.backgroundTexture} style={styles.background}>
        {SHOW_REFERENCE_OVERLAY ? (
          <View pointerEvents="none" style={styles.referenceOverlay}>
            <Image
              source={tripsReferenceImage}
              resizeMode="stretch"
              style={[styles.referenceOverlayImage, { opacity: REFERENCE_OVERLAY_OPACITY }]}
            />
          </View>
        ) : null}
        <FlatList
          data={visibleTrips}
          keyExtractor={(trip) => trip.id}
          showsVerticalScrollIndicator={false}
          refreshControl={<RefreshControl refreshing={status === 'loading' || status === 'refreshing' || status === 'syncing'} onRefresh={refresh} tintColor={colors.red} />}
          initialNumToRender={4}
          maxToRenderPerBatch={4}
          updateCellsBatchingPeriod={80}
          windowSize={5}
          removeClippedSubviews={Platform.OS === 'android'}
          contentContainerStyle={{
            paddingTop: insets.top + 6,
            paddingBottom: insets.bottom + layout.bottomNavHeight + 28,
            width: visualWidth,
          }}
          ListHeaderComponent={(
            <>
              <TripsHeader screenPadding={screenPadding} contentWidth={contentWidth} />
              <TripTabs
                screenPadding={screenPadding}
                totalTrips={trips.length}
                currentYearTrips={currentYearTrips}
                favoritesCount={favorites.size}
                activeTab={activeTab}
                onChangeTab={setActiveTab}
              />
              <SyncLine screenPadding={screenPadding} source={source} status={status} error={error} accountEmail={accountEmail} onRefresh={refresh} />
            </>
          )}
          renderItem={({ item: trip, index }) => {
            const upcoming = index < upcomingTrips.length;
            const startsUpcoming = upcoming && index === 0;
            const startsPast = !upcoming && index === upcomingTrips.length;
            return (
              <View style={[styles.listItem, { paddingHorizontal: screenPadding }]}>
                {startsUpcoming ? (
                  <View style={[styles.sectionHeader, styles.firstSectionHeader]}>
                    <Text allowFontScaling={false} style={styles.sectionLabel}>UPCOMING</Text>
                    <View style={styles.sectionLine} />
                    <Text allowFontScaling={false} style={styles.sectionCount}>{upcomingTrips.length}</Text>
                  </View>
                ) : null}
                {startsPast ? (
                  <View style={[styles.sectionHeader, styles.firstSectionHeader, upcomingTrips.length > 0 && styles.followingSectionHeader]}>
                    <Text allowFontScaling={false} style={styles.sectionLabel}>PAST TRIPS</Text>
                    <View style={styles.sectionLine} />
                    <Text allowFontScaling={false} style={styles.sectionCount}>{pastTrips.length}</Text>
                  </View>
                ) : null}
                <TripCard
                  trip={trip}
                  width={contentWidth}
                  favorite={favorites.has(trip.id)}
                  upcoming={upcoming}
                  onFavorite={() => toggleFavorite(trip.id)}
                  onPress={() => onOpenTrip?.(trip)}
                />
              </View>
            );
          }}
          ListEmptyComponent={(
            <View style={[styles.emptyState, { marginHorizontal: screenPadding }]}>
              <Text maxFontSizeMultiplier={1.05} style={styles.emptyStateText}>No trips match this view.</Text>
            </View>
          )}
          ListFooterComponent={(
            <View style={[styles.summaryRow, { marginHorizontal: screenPadding }]}>
              <IconGlyph name="globe" color={colors.mutedInk} size={22} />
              <Text maxFontSizeMultiplier={1.05} style={styles.summaryText}>
                {trips.length} trips  -  {profile.flights} flights  -  {profile.miles.toLocaleString()} mi
              </Text>
            </View>
          )}
        />

        <Pressable style={[styles.addButton, { left: visualWidth - screenPadding - 70, bottom: insets.bottom + layout.bottomNavHeight + 14 }]}>
          <IconGlyph name="plus" color={colors.paperSoft} size={36} />
        </Pressable>
        <BottomNav active={active} onChange={onChange} />
      </ImageBackground>
    </View>
  );
}

function SyncLine({
  screenPadding,
  source,
  status,
  error,
  accountEmail,
  onRefresh,
}: {
  screenPadding: number;
  source: 'snapshot' | 'api';
  status: 'idle' | 'loading' | 'refreshing' | 'syncing' | 'error';
  error?: string;
  accountEmail?: string;
  onRefresh: () => void;
}) {
  const label = status === 'loading'
    ? 'Connecting to live trips'
    : status === 'refreshing'
      ? 'Refreshing live trips'
      : status === 'syncing'
        ? 'Syncing Gmail into live trips'
      : source === 'api'
        ? `Live trips for ${accountEmail ?? 'signed-in account'}`
        : 'Showing local snapshot. Sign in again to load live trips';
  return (
    <Pressable onPress={onRefresh} style={[styles.syncLine, { marginHorizontal: screenPadding }]}>
      <View style={[styles.syncDot, source === 'api' ? styles.syncDotLive : styles.syncDotLocal]} />
      <Text maxFontSizeMultiplier={1.05} numberOfLines={1} style={styles.syncLineText}>
        {error ? `${label} - ${error}` : label}
      </Text>
    </Pressable>
  );
}

function TripsHeader({ screenPadding, contentWidth }: { screenPadding: number; contentWidth: number }) {
  const compact = contentWidth < 360;
  return (
    <View style={[styles.header, { paddingHorizontal: screenPadding, width: contentWidth + screenPadding * 2 }]}>
      <View style={[styles.headerCopy, { width: contentWidth - (compact ? 108 : 124) }]}>
        <View style={styles.titleLine}>
          <Text allowFontScaling={false} numberOfLines={1} style={[styles.title, compact && styles.titleCompact]}>TRIPS</Text>
          <View style={[styles.flightDetail, compact && styles.flightDetailCompact]}>
            <View style={styles.dashLine} />
            <IconGlyph name="plane" color={colors.ink} size={compact ? 22 : 28} />
          </View>
        </View>
        <Text allowFontScaling={false} numberOfLines={1} style={styles.subtitle}>YOUR JOURNEYS, RECORDED.</Text>
      </View>
      <View
        style={[
          styles.headerActions,
          {
            left: screenPadding + contentWidth - (compact ? 48 : 48),
            width: compact ? 48 : 48,
          },
          compact && styles.headerActionsCompact,
        ]}
      >
        <DarkSquareButton icon="search" />
      </View>
    </View>
  );
}

function DarkSquareButton({ icon }: { icon: 'search' | 'sliders' }) {
  return (
    <Pressable style={styles.headerButton}>
      {icon === 'search' ? (
        <View style={styles.searchIcon}>
          <View style={styles.searchCircle} />
          <View style={styles.searchHandle} />
        </View>
      ) : (
        <IconGlyph name="sliders" color={colors.creamText} size={29} />
      )}
    </Pressable>
  );
}

function TripTabs({
  screenPadding,
  totalTrips,
  currentYearTrips,
  favoritesCount,
  activeTab,
  onChangeTab,
}: {
  screenPadding: number;
  totalTrips: number;
  currentYearTrips: number;
  favoritesCount: number;
  activeTab: 'all' | 'year' | 'favorites';
  onChangeTab: (tab: 'all' | 'year' | 'favorites') => void;
}) {
  const tabs = [
    ['ALL TRIPS', String(totalTrips), activeTab === 'all', 'all'],
    ['THIS YEAR', String(currentYearTrips), activeTab === 'year', 'year'],
    ['FAVORITES', String(favoritesCount), activeTab === 'favorites', 'favorites'],
  ] as const;

  return (
    <View style={[styles.tabsShell, { marginHorizontal: screenPadding }]}>
      {tabs.map(([label, count, active, key]) => (
        <Pressable key={label} onPress={() => onChangeTab(key)} style={[styles.tab, active ? styles.tabActive : styles.tabInactive]}>
          <Text allowFontScaling={false} numberOfLines={1} adjustsFontSizeToFit minimumFontScale={0.74} style={[styles.tabText, active ? styles.tabTextActive : styles.tabTextInactive]}>
            {label}
          </Text>
          <Text allowFontScaling={false} style={[styles.tabCount, active ? styles.tabTextActive : styles.tabTextInactive]}>{count}</Text>
        </Pressable>
      ))}
    </View>
  );
}



const styles = StyleSheet.create({
  screen: {
    flex: 1,
    backgroundColor: colors.paperSoft,
  },
  background: {
    flex: 1,
    backgroundColor: colors.paperSoft,
  },
  backgroundTexture: {
    opacity: 0.18,
  },
  referenceOverlay: {
    ...StyleSheet.absoluteFillObject,
    zIndex: 0,
  },
  referenceOverlayImage: {
    width: '100%',
    height: '100%',
  },
  header: {
    minHeight: 96,
    position: 'relative',
    flexDirection: 'row',
    alignItems: 'flex-start',
    justifyContent: 'space-between',
  },
  headerCopy: {
    flex: 1,
    minWidth: 0,
    paddingTop: 3,
  },
  titleLine: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  title: {
    color: colors.ink,
    fontFamily: Platform.select({ web: 'Arial Narrow', default: fonts.display }),
    fontSize: 58,
    fontWeight: '900',
    letterSpacing: 5,
    lineHeight: 60,
  },
  titleCompact: {
    fontSize: 54,
    letterSpacing: 4.5,
    lineHeight: 56,
  },
  flightDetail: {
    flex: 1,
    minWidth: 44,
    marginLeft: 12,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 7,
  },
  flightDetailCompact: {
    minWidth: 32,
    marginLeft: 9,
  },
  dashLine: {
    flex: 1,
    height: 1,
    borderTopWidth: 2,
    borderStyle: 'dashed',
    borderColor: colors.mutedInk,
    opacity: 0.55,
  },
  subtitle: {
    color: colors.redDeep,
    fontFamily: fonts.sansBold,
    fontSize: 12,
    letterSpacing: 1.35,
    marginTop: -4,
  },
  headerActions: {
    position: 'absolute',
    top: 10,
    flexDirection: 'row',
    gap: 10,
    marginLeft: 8,
  },
  headerActionsCompact: {
    gap: 8,
    marginLeft: 6,
  },
  headerButton: {
    width: 48,
    height: 48,
    borderRadius: 9,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.dashboard,
    borderWidth: 1,
    borderColor: colors.darkBorder,
    ...shadows.darkPanel,
  },
  searchIcon: {
    width: 24,
    height: 24,
  },
  searchCircle: {
    width: 17,
    height: 17,
    borderRadius: 8.5,
    borderWidth: 2.5,
    borderColor: colors.creamText,
  },
  searchHandle: {
    position: 'absolute',
    right: 2,
    bottom: 3,
    width: 10,
    height: 2.5,
    borderRadius: 2,
    backgroundColor: colors.creamText,
    transform: [{ rotate: '45deg' }],
  },
  tabsShell: {
    flexDirection: 'row',
    borderRadius: 8,
    overflow: 'hidden',
    borderWidth: 1,
    borderColor: colors.paperBorder,
    backgroundColor: colors.paperDeep,
    marginTop: 10,
  },
  syncLine: {
    minHeight: 32,
    marginTop: 8,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  syncDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
  },
  syncDotLive: {
    backgroundColor: colors.green,
  },
  syncDotLocal: {
    backgroundColor: colors.mustard,
  },
  syncLineText: {
    flex: 1,
    minWidth: 0,
    color: colors.mutedInk,
    fontFamily: fonts.sansSemi,
    fontSize: 11.5,
  },
  tab: {
    flex: 1,
    minHeight: 48,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 8,
    borderRightWidth: 1,
    borderRightColor: colors.paperBorder,
  },
  tabActive: {
    backgroundColor: colors.dashboard,
  },
  tabInactive: {
    backgroundColor: colors.paper,
  },
  tabText: {
    fontFamily: fonts.sansBold,
    fontSize: 10.5,
    letterSpacing: 0.2,
  },
  tabCount: {
    fontFamily: fonts.mono,
    fontSize: 11.5,
  },
  tabTextActive: {
    color: colors.creamText,
  },
  tabTextInactive: {
    color: colors.ink,
  },
  sortRow: {
    minHeight: 38,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginTop: 8,
  },
  sortText: {
    flex: 1,
    minWidth: 0,
    color: colors.mutedInk,
    fontFamily: fonts.sansBold,
    fontSize: 13,
    letterSpacing: 0.2,
  },
  sortValue: {
    color: colors.ink,
    fontFamily: fonts.sansSemi,
    letterSpacing: 0,
  },
  mapView: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 5,
    flexShrink: 0,
    marginLeft: 8,
  },
  mapText: {
    color: colors.tealDeep,
    fontFamily: fonts.sansBold,
    fontSize: 10.5,
    letterSpacing: 0.3,
  },
  listItem: {
    marginBottom: CARD_GAP,
  },
  firstSectionHeader: {
    marginTop: 16,
  },
  followingSectionHeader: {
    marginTop: 8,
  },
  emptyState: {
    minHeight: 140,
    alignItems: 'center',
    justifyContent: 'center',
  },
  emptyStateText: {
    color: colors.mutedInk,
    fontFamily: fonts.sansSemi,
    fontSize: 14,
  },
  sectionHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    marginBottom: 6,
  },
  sectionLabel: {
    color: colors.mutedInk,
    fontFamily: fonts.sansBold,
    fontSize: 10,
    letterSpacing: 1.4,
  },
  sectionLine: {
    flex: 1,
    height: 1,
    backgroundColor: colors.paperBorder,
  },
  sectionCount: {
    color: colors.mutedInk,
    fontFamily: fonts.mono,
    fontSize: 10,
  },
  summaryRow: {
    minHeight: 58,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 10,
  },
  summaryText: {
    color: colors.ink,
    fontFamily: fonts.sansRegular,
    fontSize: 14,
  },
  addButton: {
    position: 'absolute',
    width: 68,
    height: 68,
    borderRadius: 34,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#344B3D',
    borderWidth: 3,
    borderColor: colors.paperDeep,
    ...shadows.darkPanel,
  },
});
