import React from 'react';
import { Pressable, RefreshControl, ScrollView, StyleSheet, Text, useWindowDimensions, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { BottomNav, IconGlyph, PaperSurface, ScreenHeader } from '../components/trotter/TrotterKit';
import { PngStamp } from '../components/trotter/stamps/PngStamp';
import { BottomNavTab, TripSummary } from '../data/trotterMock';
import { useTravelTrips } from '../services/travelTrips';
import { colors, fonts, layout, spacing } from '../theme/trotterTheme';
import { getMobileVisualWidth } from '../utils/mobileLayout';

const STAMP_BASE_WIDTH = 204.75;

type CountryArrival = {
  country: string;
  city?: string;
  airportCode?: string;
  firstVisitDate: string;
  tripCount: number;
  airportCount: number;
  stamp: TripSummary['stamp'];
};

export function CountryStampCollectionScreen({
  active,
  onChange,
  onBack,
}: {
  active: BottomNavTab;
  onChange: (tab: BottomNavTab) => void;
  onBack?: () => void;
}) {
  const insets = useSafeAreaInsets();
  const { width } = useWindowDimensions();
  const { trips, profile, status, refresh } = useTravelTrips();
  const visualWidth = getMobileVisualWidth(width);
  const screenPadding = visualWidth < 390 ? 16 : layout.screenPadding;
  const contentWidth = visualWidth - screenPadding * 2;
  const cardWidth = (contentWidth - layout.cardGap) / 2;
  const arrivals = React.useMemo(() => buildCountryArrivals(trips), [trips]);
  const firstYear = arrivals.length ? arrivals[arrivals.length - 1].firstVisitDate.slice(0, 4) : '-';
  const latestYear = arrivals.length ? arrivals[0].firstVisitDate.slice(0, 4) : '-';

  return (
    <View style={[styles.screen, { paddingTop: insets.top + 12 }]}>
      <ScrollView
        showsVerticalScrollIndicator={false}
        refreshControl={<RefreshControl refreshing={status === 'loading' || status === 'refreshing'} onRefresh={refresh} tintColor={colors.red} />}
        contentContainerStyle={{ paddingBottom: insets.bottom + layout.bottomNavHeight + 24, width: visualWidth }}
      >
        <ScreenHeader
          title="STAMPS"
          subtitle="FIRST ARRIVALS"
          leftAction={onBack ? <BackButton onPress={onBack} /> : undefined}
          rightActions={[<CountryProgressBadge key="progress" visited={arrivals.length} />]}
        />

        <PaperSurface radius={16} padding={spacing.lg} style={[styles.summaryCard, { marginHorizontal: screenPadding, width: contentWidth }]}>
          <View style={styles.summaryTop}>
            <View>
              <Text allowFontScaling={false} style={styles.summaryEyebrow}>YOUR TRAVEL ARCHIVE</Text>
              <Text allowFontScaling={false} style={styles.summaryValue}>{arrivals.length} countries stamped</Text>
              <Text allowFontScaling={false} style={styles.summarySub}>{firstYear} to {latestYear}</Text>
            </View>
            <IconGlyph name="globe" color={colors.tealDeep} size={38} />
          </View>
          <View style={styles.summaryMetrics}>
            <SummaryMetric label="FLIGHTS" value={profile.flights.toLocaleString()} />
            <SummaryMetric label="AIRPORTS" value={profile.airports.toLocaleString()} />
            <SummaryMetric label="TRIPS" value={trips.length.toLocaleString()} />
          </View>
        </PaperSurface>

        <View style={[styles.sectionHeader, { marginHorizontal: screenPadding }]}>
          <Text allowFontScaling={false} style={styles.sectionTitle}>ARRIVAL STAMPS</Text>
          <Text allowFontScaling={false} style={styles.sectionHint}>Newest first</Text>
        </View>

        {arrivals.length ? (
          <View style={[styles.grid, { paddingHorizontal: screenPadding, gap: layout.cardGap }]}>
            {arrivals.map((arrival, index) => (
              <CountryStampCard key={arrival.country} arrival={arrival} width={cardWidth} index={index} />
            ))}
          </View>
        ) : (
          <PaperSurface radius={14} padding={spacing.xl} style={[styles.emptyCard, { marginHorizontal: screenPadding, width: contentWidth }]}>
            <Text allowFontScaling={false} style={styles.emptyTitle}>NO ARRIVAL STAMPS YET</Text>
            <Text style={styles.emptyText}>Sync Gmail to build this collection from your recorded flights.</Text>
          </PaperSurface>
        )}
      </ScrollView>
      <BottomNav active={active} onChange={onChange} />
    </View>
  );
}

function BackButton({ onPress }: { onPress: () => void }) {
  return (
    <Pressable onPress={onPress} hitSlop={8} style={styles.backButton}>
      <Text allowFontScaling={false} style={styles.backText}>{'<'}</Text>
    </Pressable>
  );
}

function CountryProgressBadge({ visited }: { visited: number }) {
  return (
    <PaperSurface radius={999} padding={8} style={styles.badge}>
      <Text allowFontScaling={false} style={styles.badgeValue}>{visited} / 195</Text>
      <Text allowFontScaling={false} style={styles.badgeLabel}>VISITED</Text>
    </PaperSurface>
  );
}

function SummaryMetric({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.summaryMetric}>
      <Text allowFontScaling={false} style={styles.summaryMetricValue}>{value}</Text>
      <Text allowFontScaling={false} style={styles.summaryMetricLabel}>{label}</Text>
    </View>
  );
}

function CountryStampCard({ arrival, width, index }: { arrival: CountryArrival; width: number; index: number }) {
  const stampScale = Math.max(0.55, Math.min(0.76, (width - 18) / STAMP_BASE_WIDTH));
  const airportLabel = arrival.airportCode ?? 'ARRIVAL';
  return (
    <PaperSurface radius={12} padding={spacing.sm} style={[styles.countryCard, { width }]}>
      <View style={styles.stampWrap}>
        <PngStamp
          {...arrival.stamp}
          city={arrival.city}
          airportCode={arrival.airportCode}
          date={arrival.firstVisitDate}
          size="md"
          variant="country-card"
          rotate={index % 2 === 0 ? -2 : 2}
          scale={stampScale}
        />
      </View>
      <Text allowFontScaling={false} numberOfLines={1} adjustsFontSizeToFit style={styles.countryName}>{arrival.country}</Text>
      <View style={styles.arrivalLine}>
        <Text allowFontScaling={false} numberOfLines={1} style={styles.airportCode}>{airportLabel}</Text>
        <Text allowFontScaling={false} numberOfLines={1} style={styles.countryMeta}>{formatStampDate(arrival.firstVisitDate)}</Text>
      </View>
      <Text allowFontScaling={false} numberOfLines={1} style={styles.tripCount}>
        {arrival.tripCount} trip{arrival.tripCount === 1 ? '' : 's'} / {arrival.airportCount} airport{arrival.airportCount === 1 ? '' : 's'}
      </Text>
    </PaperSurface>
  );
}

function buildCountryArrivals(trips: TripSummary[]): CountryArrival[] {
  const arrivals = new Map<string, CountryArrival & { airports: Set<string> }>();
  const chronologicalTrips = [...trips].sort((a, b) => (
    (a.firstCountryEntryDate ?? a.startDate).localeCompare(b.firstCountryEntryDate ?? b.startDate)
  ));

  for (const trip of chronologicalTrips) {
    if (!trip.country) continue;
    const known = arrivals.get(trip.country);
    const airportCodes = (trip.airports ?? []).filter(Boolean);
    if (trip.airportCode) airportCodes.push(trip.airportCode);
    if (known) {
      known.tripCount += 1;
      airportCodes.forEach((code) => known.airports.add(code));
      known.airportCount = known.airports.size;
      continue;
    }

    const airports = new Set(airportCodes);
    arrivals.set(trip.country, {
      country: trip.country,
      city: trip.stamp.city ?? trip.city,
      airportCode: trip.stamp.airportCode ?? trip.airportCode,
      firstVisitDate: trip.firstCountryEntryDate ?? trip.stamp.date ?? trip.startDate,
      tripCount: 1,
      airportCount: airports.size,
      stamp: trip.stamp,
      airports,
    });
  }

  return Array.from(arrivals.values())
    .sort((a, b) => b.firstVisitDate.localeCompare(a.firstVisitDate))
    .map(({ airports: _airports, ...arrival }) => arrival);
}

function formatStampDate(value: string) {
  const parsed = new Date(`${value}T00:00:00`);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
    backgroundColor: colors.paperSoft,
  },
  backButton: {
    width: 48,
    height: 48,
    borderRadius: 24,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.dashboard,
    borderWidth: 1,
    borderColor: colors.darkBorder,
  },
  backText: {
    color: colors.creamText,
    fontFamily: fonts.sansBold,
    fontSize: 31,
    lineHeight: 34,
    marginTop: -3,
  },
  badge: {
    minWidth: 70,
    alignItems: 'center',
  },
  badgeValue: {
    color: colors.ink,
    fontFamily: fonts.mono,
    fontSize: 11,
  },
  badgeLabel: {
    color: colors.red,
    fontFamily: fonts.sansBold,
    fontSize: 7,
    letterSpacing: 0.6,
  },
  summaryCard: {
    marginTop: spacing.sm,
  },
  summaryTop: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  summaryEyebrow: {
    color: colors.red,
    fontFamily: fonts.sansBold,
    fontSize: 9,
    letterSpacing: 1,
  },
  summaryValue: {
    color: colors.ink,
    fontFamily: fonts.display,
    fontSize: 21,
    marginTop: 3,
  },
  summarySub: {
    color: colors.mutedInk,
    fontFamily: fonts.sansRegular,
    fontSize: 11,
    marginTop: 2,
  },
  summaryMetrics: {
    flexDirection: 'row',
    marginTop: spacing.lg,
    paddingTop: spacing.md,
    borderTopWidth: 1,
    borderTopColor: colors.paperBorder,
  },
  summaryMetric: {
    flex: 1,
    alignItems: 'center',
    borderRightWidth: 1,
    borderRightColor: colors.paperBorderSoft,
  },
  summaryMetricValue: {
    color: colors.ink,
    fontFamily: fonts.mono,
    fontSize: 16,
  },
  summaryMetricLabel: {
    color: colors.mutedInk,
    fontFamily: fonts.sansBold,
    fontSize: 8,
    letterSpacing: 0.7,
    marginTop: 3,
  },
  sectionHeader: {
    marginTop: spacing.xl,
    marginBottom: spacing.sm,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  sectionTitle: {
    color: colors.ink,
    fontFamily: fonts.sansBold,
    fontSize: 12,
    letterSpacing: 1.1,
  },
  sectionHint: {
    color: colors.mutedInk,
    fontFamily: fonts.sansRegular,
    fontSize: 10,
  },
  grid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
  },
  countryCard: {
    height: 205,
    alignItems: 'center',
  },
  stampWrap: {
    height: 122,
    alignItems: 'center',
    justifyContent: 'center',
  },
  countryName: {
    maxWidth: '100%',
    color: colors.ink,
    fontFamily: fonts.sansBold,
    fontSize: 13,
  },
  arrivalLine: {
    maxWidth: '100%',
    flexDirection: 'row',
    alignItems: 'center',
    gap: 5,
    marginTop: 4,
  },
  airportCode: {
    color: colors.redDeep,
    fontFamily: fonts.mono,
    fontSize: 10,
  },
  countryMeta: {
    flexShrink: 1,
    color: colors.mutedInk,
    fontFamily: fonts.sansRegular,
    fontSize: 9,
  },
  tripCount: {
    color: colors.mutedInk,
    fontFamily: fonts.sansRegular,
    fontSize: 8.5,
    marginTop: 4,
  },
  emptyCard: {
    alignItems: 'center',
  },
  emptyTitle: {
    color: colors.ink,
    fontFamily: fonts.sansBold,
    fontSize: 13,
  },
  emptyText: {
    color: colors.mutedInk,
    fontFamily: fonts.sansRegular,
    fontSize: 12,
    lineHeight: 18,
    textAlign: 'center',
    marginTop: spacing.sm,
  },
});
