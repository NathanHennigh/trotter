import React from 'react';
import { ScrollView, StyleSheet, Text, useWindowDimensions, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import {
  BottomNav,
  IconButton,
  IconGlyph,
  PaperSurface,
  ScreenHeader,
  SegmentedFilterTabs,
  Stamp,
} from '../components/trotter/TrotterKit';
import { BottomNavTab, CountryStamp, countryStamps } from '../data/trotterMock';
import { colors, fonts, layout, spacing } from '../theme/trotterTheme';

export function CountryStampCollectionScreen({ active, onChange }: { active: BottomNavTab; onChange: (tab: BottomNavTab) => void }) {
  const insets = useSafeAreaInsets();
  const { width } = useWindowDimensions();
  const [tab, setTab] = React.useState('all');
  const visited = countryStamps.filter((country) => country.visited).length;
  const visibleCountries = countryStamps.filter((country) => tab === 'all' || (tab === 'visited' ? country.visited : !country.visited));
  const screenPadding = width < 390 ? 16 : layout.screenPadding;
  const contentWidth = width - screenPadding * 2;
  const cardWidth = (contentWidth - layout.cardGap) / 2;

  return (
    <View style={[styles.screen, { paddingTop: insets.top + 12 }]}>
      <ScrollView showsVerticalScrollIndicator={false} contentContainerStyle={{ paddingBottom: insets.bottom + layout.bottomNavHeight + 24 }}>
        <ScreenHeader
          title="COUNTRIES"
          subtitle="STAMP COLLECTION"
          leftAction={<IconButton variant="paper" shape="circle" icon={<IconGlyph name="globe" color={colors.ink} size={22} />} />}
          rightActions={[<CountryProgressBadge key="progress" visited={visited} total={195} />]}
        />
        <SegmentedFilterTabs
          activeKey={tab}
          onChange={setTab}
          tabs={[
            { key: 'all', label: 'ALL', count: countryStamps.length },
            { key: 'visited', label: 'VISITED', count: visited },
            { key: 'unvisited', label: 'UNVISITED', count: countryStamps.length - visited },
          ]}
        />
        <CountrySummaryMapCard visited={visited} screenPadding={screenPadding} contentWidth={contentWidth} />
        <View style={[styles.grid, { paddingHorizontal: screenPadding, gap: layout.cardGap }]}>
          {visibleCountries.map((country) => <CountryStampCard key={country.country} country={country} width={cardWidth} />)}
        </View>
        <PaperSurface radius={14} padding={spacing.lg} style={[styles.banner, { marginHorizontal: screenPadding, width: contentWidth }]}>
          <Text allowFontScaling={false} style={styles.bannerTitle}>COLLECT MORE STAMPS</Text>
          <Text maxFontSizeMultiplier={1.1} style={styles.bannerText}>New countries unlock when imported flights include an arrival airport outside your existing travel archive.</Text>
        </PaperSurface>
      </ScrollView>
      <BottomNav active={active} onChange={onChange} />
    </View>
  );
}

function CountryProgressBadge({ visited, total }: { visited: number; total: number }) {
  return (
    <PaperSurface radius={999} padding={8} style={styles.badge}>
      <Text allowFontScaling={false} style={styles.badgeValue}>{visited} / {total}</Text>
      <Text allowFontScaling={false} style={styles.badgeLabel}>VISITED</Text>
    </PaperSurface>
  );
}

function CountrySummaryMapCard({ visited, screenPadding, contentWidth }: { visited: number; screenPadding: number; contentWidth: number }) {
  return (
    <PaperSurface radius={16} padding={spacing.lg} style={[styles.mapCard, { marginHorizontal: screenPadding, width: contentWidth }]}>
      <View style={styles.mapTop}>
        <View>
          <Text allowFontScaling={false} style={styles.mapTitle}>WORLD SUMMARY</Text>
          <Text maxFontSizeMultiplier={1.05} style={styles.mapSub}>{visited} countries stamped</Text>
        </View>
        <IconGlyph name="globe" color={colors.tealDeep} size={34} />
      </View>
      <View style={styles.miniMap}>
        <View style={[styles.landMass, styles.landA]} />
        <View style={[styles.landMass, styles.landB]} />
        <View style={[styles.landMass, styles.landC]} />
        <View style={[styles.routeArc, styles.routeArcA]} />
        <View style={[styles.routeArc, styles.routeArcB]} />
      </View>
      <View style={styles.legend}>
        <LegendDot color={colors.green} label="visited" />
        <LegendDot color={colors.paperBorder} label="not visited" />
        <LegendDot color={colors.mustard} label="in transit" />
      </View>
    </PaperSurface>
  );
}

function LegendDot({ color, label }: { color: string; label: string }) {
  return (
    <View style={styles.legendItem}>
      <View style={[styles.legendDot, { backgroundColor: color }]} />
      <Text maxFontSizeMultiplier={1.05} numberOfLines={1} style={styles.legendText}>{label}</Text>
    </View>
  );
}

function CountryStampCard({ country, width }: { country: CountryStamp; width: number }) {
  return (
    <PaperSurface radius={12} padding={spacing.sm} style={[styles.countryCard, { width }, !country.visited && styles.countryCardMuted]}>
      <Stamp
        type={country.stampType}
        color={country.color}
        title={country.country.toUpperCase()}
        subtitle={`${country.city}${country.airportCode ? ` (${country.airportCode})` : ''}`}
        date={country.firstVisitDate}
        footer={country.visited ? undefined : 'UNSTAMPED'}
        landmark={country.landmark}
        faded={!country.visited}
        size={width < 160 ? 'sm' : 'md'}
      />
      <Text maxFontSizeMultiplier={1.05} numberOfLines={1} style={styles.countryName}>{country.country}</Text>
      <Text maxFontSizeMultiplier={1.05} numberOfLines={1} style={styles.countryMeta}>{country.visited ? country.firstVisitDate : `${country.city} awaits`}</Text>
    </PaperSurface>
  );
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
    backgroundColor: colors.paperSoft,
  },
  badge: {
    minWidth: 68,
    alignItems: 'center',
  },
  badgeValue: {
    color: colors.ink,
    fontFamily: fonts.mono,
    fontSize: 12,
  },
  badgeLabel: {
    color: colors.red,
    fontFamily: fonts.sansBold,
    fontSize: 8,
  },
  mapCard: {
    marginTop: spacing.md,
  },
  mapTop: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  mapTitle: {
    color: colors.ink,
    fontFamily: fonts.sansBold,
    fontSize: 14,
  },
  mapSub: {
    color: colors.mutedInk,
    fontFamily: fonts.sansRegular,
    fontSize: 12,
    marginTop: 2,
  },
  miniMap: {
    height: 132,
    marginTop: spacing.md,
    borderRadius: 10,
    overflow: 'hidden',
    backgroundColor: '#D8C7A6',
    borderWidth: 1,
    borderColor: colors.paperBorder,
  },
  landMass: {
    position: 'absolute',
    backgroundColor: colors.green,
    opacity: 0.72,
  },
  landA: {
    left: 24,
    top: 36,
    width: 94,
    height: 46,
    borderRadius: 28,
  },
  landB: {
    left: 132,
    top: 42,
    width: 72,
    height: 38,
    borderRadius: 20,
  },
  landC: {
    right: 34,
    top: 28,
    width: 98,
    height: 54,
    borderRadius: 30,
  },
  routeArc: {
    position: 'absolute',
    borderTopWidth: 2,
    borderColor: colors.red,
    opacity: 0.75,
  },
  routeArcA: {
    left: 82,
    top: 32,
    width: 164,
    height: 80,
    borderRadius: 100,
    transform: [{ rotate: '-8deg' }],
  },
  routeArcB: {
    left: 44,
    top: 54,
    width: 244,
    height: 94,
    borderRadius: 140,
    transform: [{ rotate: '8deg' }],
  },
  legend: {
    flexDirection: 'row',
    gap: spacing.md,
    marginTop: spacing.md,
    flexWrap: 'wrap',
  },
  legendItem: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 5,
  },
  legendDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
  },
  legendText: {
    color: colors.mutedInk,
    fontFamily: fonts.sansBold,
    fontSize: 10,
  },
  grid: {
    marginTop: spacing.lg,
    flexDirection: 'row',
    flexWrap: 'wrap',
  },
  countryCard: {
    height: 178,
    alignItems: 'center',
    justifyContent: 'flex-start',
    overflow: 'hidden',
  },
  countryCardMuted: {
    backgroundColor: '#E9DCC4',
  },
  countryName: {
    color: colors.ink,
    fontFamily: fonts.sansBold,
    fontSize: 13,
    marginTop: spacing.sm,
  },
  countryMeta: {
    color: colors.mutedInk,
    fontFamily: fonts.sansRegular,
    fontSize: 11,
    marginTop: 2,
  },
  banner: {
    marginTop: spacing.lg,
  },
  bannerTitle: {
    color: colors.red,
    fontFamily: fonts.sansBold,
    fontSize: 13,
  },
  bannerText: {
    color: colors.mutedInk,
    fontFamily: fonts.sansRegular,
    fontSize: 13,
    marginTop: 5,
    lineHeight: 18,
  },
});
