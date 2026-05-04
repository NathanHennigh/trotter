import React from 'react';
import {
  Image,
  ImageBackground,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  useWindowDimensions,
  View,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { BottomNav, IconGlyph } from '../components/trotter/TrotterKit';
import { TripCard } from '../components/trotter/TripCard';
import { BottomNavTab } from '../data/trotterMock';
import { useTravelTrips } from '../services/travelTrips';
import { colors, fonts, layout, shadows, spacing } from '../theme/trotterTheme';

const paperTexture = require('../../assets/textures/paper_texture_clean.png');
const tripsReferenceImage = require('../../docs/references/screens/trips-list-reference.png');
const SHOW_REFERENCE_OVERLAY = false;
const REFERENCE_OVERLAY_OPACITY = 0.32;
const SCREEN_PADDING = 24;
const MAX_CONTENT_WIDTH = 430;
const CARD_GAP = 8;

export function TripsListScreen({ active, onChange }: { active: BottomNavTab; onChange: (tab: BottomNavTab) => void }) {
  const insets = useSafeAreaInsets();
  const { width } = useWindowDimensions();
  const { trips, profile } = useTravelTrips();
  const visualWidth = Platform.OS === 'web'
    ? Math.min(getViewportWidth(width), 393)
    : Math.min(width, MAX_CONTENT_WIDTH);
  const screenPadding = SCREEN_PADDING;
  const contentWidth = visualWidth - screenPadding * 2;
  const currentYear = new Date().getFullYear();
  const currentYearTrips = trips.filter((trip) => trip.startDate.startsWith(String(currentYear))).length;

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
        <ScrollView
          showsVerticalScrollIndicator={false}
          contentContainerStyle={{
            paddingTop: insets.top + 6,
            paddingBottom: insets.bottom + layout.bottomNavHeight + 28,
            width: visualWidth,
          }}
        >
          <TripsHeader screenPadding={screenPadding} contentWidth={contentWidth} />
          <TripTabs screenPadding={screenPadding} totalTrips={trips.length} currentYearTrips={currentYearTrips} />
          <SortRow screenPadding={screenPadding} />

          <View style={[styles.list, { paddingHorizontal: screenPadding }]}>
            {trips.map((trip, index) => (
              <TripCard key={trip.id} trip={trip} width={contentWidth} favorite={index === 0} />
            ))}
          </View>

          <View style={[styles.summaryRow, { marginHorizontal: screenPadding }]}>
            <IconGlyph name="globe" color={colors.mutedInk} size={22} />
            <Text maxFontSizeMultiplier={1.05} style={styles.summaryText}>
              {trips.length} trips  -  {profile.flights} flights  -  {profile.miles.toLocaleString()} mi
            </Text>
          </View>
        </ScrollView>

        <Pressable style={[styles.addButton, { right: screenPadding + 2, bottom: insets.bottom + layout.bottomNavHeight + 14 }]}>
          <IconGlyph name="plus" color={colors.paperSoft} size={36} />
        </Pressable>
        <BottomNav active={active} onChange={onChange} />
      </ImageBackground>
    </View>
  );
}

function getViewportWidth(fallbackWidth: number) {
  const viewportWidth = (globalThis as { innerWidth?: number }).innerWidth;
  return typeof viewportWidth === 'number' && viewportWidth > 0 ? viewportWidth : fallbackWidth;
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
            left: screenPadding + contentWidth - (compact ? 108 : 116),
            width: compact ? 108 : 116,
          },
          compact && styles.headerActionsCompact,
        ]}
      >
        <DarkSquareButton icon="search" />
        <DarkSquareButton icon="sliders" />
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
}: {
  screenPadding: number;
  totalTrips: number;
  currentYearTrips: number;
}) {
  const tabs = [
    ['ALL TRIPS', String(totalTrips), true],
    ['THIS YEAR', String(currentYearTrips), false],
    ['FAVORITES', '0', false],
  ] as const;

  return (
    <View style={[styles.tabsShell, { marginHorizontal: screenPadding }]}>
      {tabs.map(([label, count, active]) => (
        <Pressable key={label} style={[styles.tab, active ? styles.tabActive : styles.tabInactive]}>
          <Text allowFontScaling={false} numberOfLines={1} adjustsFontSizeToFit minimumFontScale={0.74} style={[styles.tabText, active ? styles.tabTextActive : styles.tabTextInactive]}>
            {label}
          </Text>
          <Text allowFontScaling={false} style={[styles.tabCount, active ? styles.tabTextActive : styles.tabTextInactive]}>{count}</Text>
        </Pressable>
      ))}
    </View>
  );
}

function SortRow({ screenPadding }: { screenPadding: number }) {
  return (
    <View style={[styles.sortRow, { paddingHorizontal: screenPadding }]}>
      <Text maxFontSizeMultiplier={1.05} numberOfLines={1} style={styles.sortText}>
        SORT BY: <Text style={styles.sortValue}>Most Recent v</Text>
      </Text>
      <Pressable style={styles.mapView}>
        <IconGlyph name="globe" color={colors.tealDeep} size={20} />
        <Text allowFontScaling={false} numberOfLines={1} style={styles.mapText}>MAP VIEW</Text>
      </Pressable>
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
    width: 32,
    height: 32,
  },
  searchCircle: {
    width: 23,
    height: 23,
    borderRadius: 12,
    borderWidth: 3,
    borderColor: colors.creamText,
  },
  searchHandle: {
    position: 'absolute',
    right: 3,
    bottom: 4,
    width: 13,
    height: 3,
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
  list: {
    gap: CARD_GAP,
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
