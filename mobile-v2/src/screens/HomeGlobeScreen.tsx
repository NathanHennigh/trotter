import React from 'react';
import { ScrollView, StyleSheet, Text, useWindowDimensions, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { GlobeScene } from '../components/GlobeScene';
import {
  BottomNav,
  DarkPanel,
  IconButton,
  IconGlyph,
  NewFlightsBanner,
  PassportViewButton,
  RecentTripsSheet,
  SplitFlapNumber,
  SplitFlapStatsPanel,
  SyncStatusPill,
  TrotterHeaderTag,
} from '../components/trotter/TrotterKit';
import { BottomNavTab, recentTrips, travelerProfile } from '../data/trotterMock';
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

  return (
    <View style={[styles.screen, { paddingTop: insets.top + 12 }]}>
      <ScrollView
        showsVerticalScrollIndicator={false}
        contentContainerStyle={{ paddingBottom: insets.bottom + layout.bottomNavHeight + 24 }}
      >
        <View style={[styles.topRow, { paddingHorizontal: screenPadding, gap: headerGap }]}>
          <TrotterHeaderTag width={headerTagWidth} />
          <View style={[styles.statsWrap, { width: statsWidth }]}>
            <SplitFlapStatsPanel width={statsWidth} compact flights={travelerProfile.flights} countries={travelerProfile.countries} airports={travelerProfile.airports} />
            <SyncStatusPill lastSyncedLabel="Last synced 2h ago" />
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
          <GlobeScene />
          <DarkPanel padding={spacing.sm} radius={12} style={[styles.milesCard, { left: screenPadding }]}>
            <View style={styles.milesTop}>
              <IconGlyph name="plane" color={colors.creamText} size={20} />
              <Text allowFontScaling={false} style={styles.milesLabel}>YOU'VE FLOWN</Text>
            </View>
            <SplitFlapNumber value={travelerProfile.miles} />
            <Text allowFontScaling={false} style={styles.milesUnit}>MILES</Text>
          </DarkPanel>
          <View style={[styles.passportButtonWrap, { right: screenPadding }]}>
            <PassportViewButton />
          </View>
        </View>

        <View style={[styles.sheetWrap, { width }]}>
          <RecentTripsSheet trips={recentTrips} onViewAll={() => onChange('trips')} />
        </View>
        <View style={[styles.bannerWrap, { width: contentWidth, marginHorizontal: screenPadding }]}>
          <NewFlightsBanner count={12} sourceLabel="Gmail" onReview={() => undefined} />
        </View>
      </ScrollView>
      <BottomNav active={active} onChange={onChange} />
    </View>
  );
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
  sheetWrap: {
    marginTop: -44,
    paddingHorizontal: 0,
  },
  bannerWrap: {
    marginTop: 10,
  },
});
