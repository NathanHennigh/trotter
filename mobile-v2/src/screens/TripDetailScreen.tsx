import React from 'react';
import {
  Image,
  ImageBackground,
  ImageSourcePropType,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  useWindowDimensions,
  View,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { BottomNav, DarkPanel, IconGlyph, PaperSurface } from '../components/trotter/TrotterKit';
import { PngStamp } from '../components/trotter/stamps/PngStamp';
import { BottomNavTab, TripSegmentSummary, TripSummary } from '../data/trotterMock';
import { useTravelTrips } from '../services/travelTrips';
import { accentColors, colors, fonts, layout, shadows, spacing } from '../theme/trotterTheme';
import { formatAirlineFlight, formatAirlineNames } from '../utils/airlines';
import { mapboxFlightImageUrl, mapboxFlightImageUrlFromCoordinates } from '../utils/mapboxFlightImage';
import { getMobileVisualWidth } from '../utils/mobileLayout';
import { groupTripItineraries, TripItinerary } from '../utils/tripItineraries';

const paperTexture = require('../../assets/textures/paper_texture_clean.png');

export function TripDetailScreen({
  trip,
  active,
  onBack,
  onChange,
}: {
  trip: TripSummary;
  active: BottomNavTab;
  onBack: () => void;
  onChange: (tab: BottomNavTab) => void;
}) {
  const insets = useSafeAreaInsets();
  const { loadTripDetail } = useTravelTrips();
  const [hydratedTrip, setHydratedTrip] = React.useState<TripSummary | undefined>();
  const { width } = useWindowDimensions();
  const visualWidth = getMobileVisualWidth(width);
  const screenPadding = visualWidth < 390 ? 16 : layout.screenPadding;
  const contentWidth = visualWidth - screenPadding * 2;
  const activeTrip = hydratedTrip?.id === trip.id ? hydratedTrip : trip;
  const accent = accentColors[activeTrip.accent];
  const segments = activeTrip.segments?.length ? activeTrip.segments : [fallbackSegment(activeTrip)];
  const itineraries = groupTripItineraries(segments);
  const airports = activeTrip.airports?.length ? activeTrip.airports : uniqueRouteAirports(segments);
  const firstSegment = segments[0];
  const destinationSegment = findDestinationSegment(activeTrip, segments);
  const mapUrl = firstSegment.depPoint && destinationSegment.arrPoint
    ? mapboxFlightImageUrlFromCoordinates(
        [firstSegment.depPoint.lon, firstSegment.depPoint.lat],
        [destinationSegment.arrPoint.lon, destinationSegment.arrPoint.lat],
        720,
        420,
        accent,
      )
    : mapboxFlightImageUrl(firstSegment.depAirport, destinationSegment.arrAirport, 720, 420, accent);
  const heroSource = activeTrip.destinationImage ?? (mapUrl ? ({ uri: mapUrl } as ImageSourcePropType) : undefined);
  const [heroImageFailed, setHeroImageFailed] = React.useState(false);
  const [heroImageAttempt, setHeroImageAttempt] = React.useState(0);

  React.useEffect(() => {
    setHeroImageFailed(false);
    setHeroImageAttempt(0);
  }, [activeTrip.destinationImage, mapUrl, activeTrip.id]);

  React.useEffect(() => {
    setHydratedTrip(undefined);
    if (!trip.backendId) return;
    loadTripDetail(trip.backendId)
      .then((detail) => {
        if (detail) setHydratedTrip(detail);
      })
      .catch(() => undefined);
  }, [loadTripDetail, trip.backendId, trip.id]);

  return (
    <View style={styles.screen}>
      <ImageBackground source={paperTexture} resizeMode="cover" imageStyle={styles.backgroundTexture} style={styles.background}>
        <ScrollView
          showsVerticalScrollIndicator={false}
          contentContainerStyle={{
            paddingTop: insets.top + 10,
            paddingBottom: insets.bottom + layout.bottomNavHeight + 28,
            width: visualWidth,
          }}
        >
          <View style={[styles.header, { paddingHorizontal: screenPadding }]}>
            <Pressable onPress={onBack} style={styles.backButton}>
              <Text allowFontScaling={false} style={styles.backText}>{'<'}</Text>
            </Pressable>
            <View style={styles.headerCopy}>
              <Text allowFontScaling={false} numberOfLines={1} adjustsFontSizeToFit style={styles.kicker}>TRIP DETAIL</Text>
              <Text allowFontScaling={false} numberOfLines={2} adjustsFontSizeToFit style={styles.title}>{activeTrip.title}</Text>
              <Text maxFontSizeMultiplier={1.05} numberOfLines={1} style={styles.subtitle}>
                {formatDateRange(activeTrip.startDate, activeTrip.endDate)} / {tripDurationLabel(activeTrip)}
              </Text>
              {__DEV__ && activeTrip.backendId ? (
                <Text allowFontScaling={false} numberOfLines={1} style={styles.debugLine}>
                  backendId {activeTrip.backendId} / segments {segments.length}
                </Text>
              ) : null}
            </View>
          </View>

          <PaperSurface radius={14} padding={0} style={[styles.heroCard, { marginHorizontal: screenPadding, width: contentWidth }]}>
            <View style={styles.heroImage}>
              {heroSource && !heroImageFailed ? (
                <Image
                  key={`trip-map-${activeTrip.id}-${heroImageAttempt}`}
                  source={heroSource}
                  resizeMode="cover"
                  style={StyleSheet.absoluteFillObject}
                  onError={() => {
                    if (mapUrl && !activeTrip.destinationImage && heroImageAttempt < 2) {
                      setHeroImageAttempt((attempt) => attempt + 1);
                      return;
                    }
                    setHeroImageFailed(true);
                  }}
                />
              ) : (
                <View style={styles.heroFallback}>
                  <Text allowFontScaling={false} style={styles.heroFallbackLabel}>FLIGHT PATH</Text>
                  <Text allowFontScaling={false} numberOfLines={1} adjustsFontSizeToFit style={styles.heroFallbackRoute}>
                    {firstSegment.depAirport}  /  {destinationSegment.arrAirport}
                  </Text>
                </View>
              )}
              <View style={styles.heroScrim} />
              <View style={styles.heroStats}>
                <HeroMetric label="MILES" value={activeTrip.miles.toLocaleString()} />
                <HeroMetric label="FLIGHTS" value={String(segments.length)} />
                <HeroMetric label="AIRPORTS" value={String(airports.length)} />
              </View>
            </View>
            <View style={styles.passportStamp}>
              <PngStamp {...activeTrip.stamp} size="sm" variant="trip-card" rotate={-8} />
            </View>
          </PaperSurface>

          <View style={[styles.routeBoard, { marginHorizontal: screenPadding, width: contentWidth, borderColor: accent }]}>
            <Text allowFontScaling={false} numberOfLines={1} adjustsFontSizeToFit style={[styles.routeText, { color: accent }]}>
              {activeTrip.routeLabel}
            </Text>
            <IconGlyph name="plane" color={accent} size={24} />
          </View>

          <Section width={contentWidth} screenPadding={screenPadding} title={itineraries.length > 1 ? 'ITINERARIES' : 'FLIGHT TIMELINE'}>
            {itineraries.length > 1 ? (
              <Text maxFontSizeMultiplier={1.05} style={styles.itineraryIntro}>
                {itineraries.length} separately booked itineraries make up this trip.
              </Text>
            ) : null}
            {itineraries.map((itinerary, index) => (
              <ItineraryGroup
                key={itinerary.id}
                itinerary={itinerary}
                index={index}
                count={itineraries.length}
                accent={accent}
              />
            ))}
          </Section>

          <Section width={contentWidth} screenPadding={screenPadding} title="TRIP SNAPSHOT">
            <View style={styles.snapshotGrid}>
              <SnapshotTile label="COUNTRY" value={activeTrip.country} />
              <SnapshotTile label="CITY" value={activeTrip.city ?? activeTrip.airportCode ?? activeTrip.countryCode ?? 'Recorded'} />
              <SnapshotTile label="AIRLINES" value={formatAirlines(activeTrip)} />
              <SnapshotTile label="ITINERARIES" value={String(itineraries.length)} />
            </View>
          </Section>

          <Section width={contentWidth} screenPadding={screenPadding} title="ITINERARY FOUNDATION">
            <MemoryPlaceholder icon="suitcase" title="Stays" value="Ready for hotels and Airbnb" />
            <MemoryPlaceholder icon="tag" title="Places" value="Restaurants, sights, and events next" />
            <MemoryPlaceholder icon="passport" title="Evidence" value="Flight confirmations linked from import" />
          </Section>
        </ScrollView>
        <BottomNav active={active} onChange={onChange} />
      </ImageBackground>
    </View>
  );
}

function Section({ title, width, screenPadding, children }: { title: string; width: number; screenPadding: number; children: React.ReactNode }) {
  return (
    <View style={{ marginHorizontal: screenPadding, width, marginTop: spacing.lg }}>
      <Text allowFontScaling={false} style={styles.sectionTitle}>{title}</Text>
      <PaperSurface radius={12} padding={spacing.md} style={styles.sectionPanel}>
        {children}
      </PaperSurface>
    </View>
  );
}

function HeroMetric({ label, value }: { label: string; value: string }) {
  return (
    <DarkPanel radius={8} padding={spacing.sm} style={styles.heroMetric}>
      <Text allowFontScaling={false} numberOfLines={1} style={styles.metricValue}>{value}</Text>
      <Text allowFontScaling={false} numberOfLines={1} style={styles.metricLabel}>{label}</Text>
    </DarkPanel>
  );
}

function FlightTimelineItem({ segment, index, isLast, accent }: { segment: TripSegmentSummary; index: number; isLast: boolean; accent: string }) {
  return (
    <View style={styles.flightRow}>
      <View style={styles.timelineRail}>
        <View style={[styles.timelineDot, { backgroundColor: accent }]} />
        {!isLast ? <View style={styles.timelineLine} /> : null}
      </View>
      <View style={styles.flightBody}>
        <View style={styles.flightTop}>
          <Text allowFontScaling={false} style={styles.flightNumber}>{index + 1}</Text>
          <Text allowFontScaling={false} numberOfLines={1} adjustsFontSizeToFit style={styles.flightRoute}>
            {segment.depAirport}{' -> '}{segment.arrAirport}
          </Text>
          <Text allowFontScaling={false} numberOfLines={1} style={styles.flightMiles}>
            {segment.distanceMiles ? `${segment.distanceMiles.toLocaleString()} mi` : 'flight'}
          </Text>
        </View>
        <Text maxFontSizeMultiplier={1.05} numberOfLines={1} style={styles.flightMeta}>
          {formatSegmentTime(segment.depTime)} to {formatSegmentTime(segment.arrTime)}
        </Text>
        <Text maxFontSizeMultiplier={1.05} numberOfLines={1} style={styles.flightMeta}>
          {formatAirlineFlight(segment.airline, segment.flightNumber)}
        </Text>
      </View>
    </View>
  );
}

function ItineraryGroup({
  itinerary,
  index,
  count,
  accent,
}: {
  itinerary: TripItinerary;
  index: number;
  count: number;
  accent: string;
}) {
  const label = count === 2 ? (index === 0 ? 'OUTBOUND' : 'RETURN') : `ITINERARY ${index + 1}`;
  return (
    <View style={[styles.itineraryGroup, index > 0 && styles.itineraryGroupDivided]}>
      <View style={styles.itineraryHeader}>
        <View style={styles.itineraryHeaderCopy}>
          <Text allowFontScaling={false} style={[styles.itineraryLabel, { color: accent }]}>{label}</Text>
          <Text allowFontScaling={false} numberOfLines={1} adjustsFontSizeToFit style={styles.itineraryRoute}>
            {itinerary.origin}{' -> '}{itinerary.destination}
          </Text>
        </View>
        <View style={[styles.itineraryBadge, { borderColor: accent }]}>
          <Text allowFontScaling={false} style={[styles.itineraryBadgeText, { color: accent }]}>
            {itinerary.segments.length} {itinerary.segments.length === 1 ? 'FLIGHT' : 'FLIGHTS'}
          </Text>
        </View>
      </View>
      {itinerary.segments.map((segment, segmentIndex) => (
        <FlightTimelineItem
          key={segment.id}
          segment={segment}
          index={segmentIndex}
          isLast={segmentIndex === itinerary.segments.length - 1}
          accent={accent}
        />
      ))}
    </View>
  );
}

function SnapshotTile({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.snapshotTile}>
      <Text allowFontScaling={false} numberOfLines={1} style={styles.snapshotLabel}>{label}</Text>
      <Text maxFontSizeMultiplier={1.05} numberOfLines={2} adjustsFontSizeToFit style={styles.snapshotValue}>{value}</Text>
    </View>
  );
}

function MemoryPlaceholder({ icon, title, value }: { icon: string; title: string; value: string }) {
  return (
    <View style={styles.memoryRow}>
      <View style={styles.memoryIcon}>
        <IconGlyph name={icon} color={colors.red} size={22} />
      </View>
      <View style={styles.memoryCopy}>
        <Text allowFontScaling={false} numberOfLines={1} style={styles.memoryTitle}>{title}</Text>
        <Text maxFontSizeMultiplier={1.05} numberOfLines={1} style={styles.memoryValue}>{value}</Text>
      </View>
      <Text allowFontScaling={false} style={styles.memoryStatus}>NEXT</Text>
    </View>
  );
}

function fallbackSegment(trip: TripSummary): TripSegmentSummary {
  const [origin, destination] = trip.routeLabel.replace('->', '->').split('->').map((part) => part.trim());
  return {
    id: `${trip.id}-route`,
    mode: 'flight',
    depAirport: origin || '---',
    arrAirport: destination || trip.airportCode || '---',
    depTime: trip.startDate,
    arrTime: trip.endDate,
    distanceMiles: trip.miles,
  };
}

function uniqueRouteAirports(segments: TripSegmentSummary[]) {
  const seen = new Set<string>();
  const airports: string[] = [];
  for (const segment of segments) {
    for (const code of [segment.depAirport, segment.arrAirport]) {
      if (!code || seen.has(code)) continue;
      seen.add(code);
      airports.push(code);
    }
  }
  return airports;
}

function findDestinationSegment(trip: TripSummary, segments: TripSegmentSummary[]) {
  if (trip.airportCode) {
    const matchingArrival = segments.find((segment) => segment.arrAirport === trip.airportCode);
    if (matchingArrival) return matchingArrival;
  }
  return segments[segments.length - 1];
}

function formatAirlines(trip: TripSummary) {
  if (trip.airlines?.length) return formatAirlineNames(trip.airlines);
  return `${trip.airlineCount} carrier${trip.airlineCount === 1 ? '' : 's'}`;
}

function tripDurationLabel(trip: TripSummary) {
  const start = new Date(`${trip.startDate}T00:00:00`);
  const end = new Date(`${trip.endDate}T00:00:00`);
  const days = Math.max(1, Math.round((end.getTime() - start.getTime()) / 86400000) + 1);
  return `${days} day${days === 1 ? '' : 's'}`;
}

function formatDateRange(start: string, end: string) {
  const startDate = new Date(`${start}T00:00:00`);
  const endDate = new Date(`${end}T00:00:00`);
  const startMonth = startDate.toLocaleString('en-US', { month: 'short' });
  const endMonth = endDate.toLocaleString('en-US', { month: 'short' });
  return `${startMonth} ${startDate.getDate()} - ${endMonth} ${endDate.getDate()}, ${endDate.getFullYear()}`;
}

function formatSegmentTime(value: string) {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
    backgroundColor: colors.paperSoft,
  },
  background: {
    flex: 1,
    backgroundColor: colors.paperSoft,
    alignItems: 'center',
  },
  backgroundTexture: {
    opacity: 0.18,
  },
  header: {
    minHeight: 104,
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
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
    ...shadows.darkPanel,
  },
  backText: {
    color: colors.creamText,
    fontFamily: fonts.sansBold,
    fontSize: 35,
    lineHeight: 38,
    marginTop: -3,
  },
  headerCopy: {
    flex: 1,
    minWidth: 0,
  },
  kicker: {
    color: colors.red,
    fontFamily: fonts.sansBold,
    fontSize: 11,
    letterSpacing: 1.2,
  },
  title: {
    color: colors.ink,
    fontFamily: fonts.display,
    fontSize: 42,
    lineHeight: 43,
    marginTop: 2,
  },
  subtitle: {
    color: colors.mutedInk,
    fontFamily: fonts.sansSemi,
    fontSize: 13,
    marginTop: 4,
  },
  debugLine: {
    color: colors.mutedInk,
    fontFamily: fonts.mono,
    fontSize: 10,
    marginTop: 4,
  },
  heroCard: {
    overflow: 'hidden',
  },
  heroImage: {
    height: 222,
    backgroundColor: colors.dashboard,
  },
  heroFallback: {
    ...StyleSheet.absoluteFillObject,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#17262A',
  },
  heroFallbackLabel: {
    color: colors.subtleText,
    fontFamily: fonts.sansBold,
    fontSize: 10,
    letterSpacing: 1.4,
  },
  heroFallbackRoute: {
    maxWidth: '82%',
    color: colors.creamText,
    fontFamily: fonts.mono,
    fontSize: 27,
    letterSpacing: 2,
    marginTop: 8,
  },
  heroScrim: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: 'rgba(12, 16, 13, 0.18)',
  },
  heroStats: {
    position: 'absolute',
    left: spacing.sm,
    right: spacing.sm,
    bottom: spacing.sm,
    flexDirection: 'row',
    gap: spacing.sm,
  },
  heroMetric: {
    flex: 1,
    minWidth: 0,
    alignItems: 'center',
  },
  metricValue: {
    color: colors.brassSoft,
    fontFamily: fonts.mono,
    fontSize: 18,
  },
  metricLabel: {
    color: colors.creamText,
    fontFamily: fonts.sansBold,
    fontSize: 9,
    marginTop: 3,
  },
  passportStamp: {
    position: 'absolute',
    right: 12,
    top: 12,
    transform: [{ rotate: '-8deg' }],
  },
  routeBoard: {
    minHeight: 56,
    marginTop: spacing.md,
    borderWidth: 2,
    borderRadius: 9,
    backgroundColor: colors.paper,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.sm,
  },
  routeText: {
    fontFamily: fonts.sansBold,
    fontSize: 22,
    letterSpacing: 1,
  },
  sectionTitle: {
    color: colors.ink,
    fontFamily: fonts.sansBold,
    fontSize: 12,
    letterSpacing: 1.1,
    marginBottom: spacing.sm,
  },
  sectionPanel: {
    gap: spacing.sm,
  },
  itineraryIntro: {
    color: colors.mutedInk,
    fontFamily: fonts.sansRegular,
    fontSize: 12,
    lineHeight: 17,
    paddingBottom: spacing.xs,
  },
  itineraryGroup: {
    gap: spacing.xs,
  },
  itineraryGroupDivided: {
    borderTopWidth: 1,
    borderTopColor: colors.paperBorder,
    marginTop: spacing.sm,
    paddingTop: spacing.md,
  },
  itineraryHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    marginBottom: spacing.xs,
  },
  itineraryHeaderCopy: {
    flex: 1,
    minWidth: 0,
  },
  itineraryLabel: {
    fontFamily: fonts.sansBold,
    fontSize: 9,
    letterSpacing: 1.1,
  },
  itineraryRoute: {
    color: colors.ink,
    fontFamily: fonts.mono,
    fontSize: 17,
    marginTop: 3,
  },
  itineraryBadge: {
    borderWidth: 1,
    borderRadius: 12,
    paddingHorizontal: 8,
    paddingVertical: 5,
  },
  itineraryBadgeText: {
    fontFamily: fonts.sansBold,
    fontSize: 8,
    letterSpacing: 0.7,
  },
  flightRow: {
    flexDirection: 'row',
    minHeight: 76,
  },
  timelineRail: {
    width: 22,
    alignItems: 'center',
  },
  timelineDot: {
    width: 12,
    height: 12,
    borderRadius: 6,
    marginTop: 5,
  },
  timelineLine: {
    flex: 1,
    width: 1,
    backgroundColor: colors.paperBorder,
    marginTop: 4,
  },
  flightBody: {
    flex: 1,
    minWidth: 0,
    paddingBottom: spacing.sm,
  },
  flightTop: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
  },
  flightNumber: {
    width: 22,
    height: 22,
    borderRadius: 11,
    overflow: 'hidden',
    backgroundColor: colors.dashboard,
    color: colors.creamText,
    fontFamily: fonts.mono,
    fontSize: 12,
    lineHeight: 22,
    textAlign: 'center',
  },
  flightRoute: {
    flex: 1,
    minWidth: 0,
    color: colors.ink,
    fontFamily: fonts.sansBold,
    fontSize: 17,
  },
  flightMiles: {
    color: colors.mutedInk,
    fontFamily: fonts.mono,
    fontSize: 11,
  },
  flightMeta: {
    color: colors.mutedInk,
    fontFamily: fonts.sansRegular,
    fontSize: 12,
    marginTop: 4,
  },
  snapshotGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.sm,
  },
  snapshotTile: {
    width: '48%',
    minHeight: 68,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: colors.paperBorder,
    backgroundColor: colors.paperSoft,
    padding: spacing.sm,
  },
  snapshotLabel: {
    color: colors.red,
    fontFamily: fonts.sansBold,
    fontSize: 9,
    letterSpacing: 0.8,
  },
  snapshotValue: {
    color: colors.ink,
    fontFamily: fonts.sansSemi,
    fontSize: 14,
    marginTop: 5,
  },
  memoryRow: {
    minHeight: 56,
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: colors.paperBorderSoft,
  },
  memoryIcon: {
    width: 38,
    height: 38,
    borderRadius: 19,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.paperSoft,
    borderWidth: 1,
    borderColor: colors.paperBorder,
  },
  memoryCopy: {
    flex: 1,
    minWidth: 0,
  },
  memoryTitle: {
    color: colors.ink,
    fontFamily: fonts.sansBold,
    fontSize: 14,
  },
  memoryValue: {
    color: colors.mutedInk,
    fontFamily: fonts.sansRegular,
    fontSize: 12,
    marginTop: 2,
  },
  memoryStatus: {
    color: colors.red,
    fontFamily: fonts.mono,
    fontSize: 10,
  },
});
