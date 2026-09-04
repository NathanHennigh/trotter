import React from 'react';
import { GestureResponderEvent, Image, ImageBackground, Pressable, StyleSheet, Text, View } from 'react-native';
import { TripSummary } from '../../data/trotterMock';
import { accentColors, colors, fonts, shadows } from '../../theme/trotterTheme';
import Svg, { Path } from 'react-native-svg';
import { mapboxFlightImageUrl, mapboxFlightImageUrlFromCoordinates } from '../../utils/mapboxFlightImage';

const paperTexture = require('../../../assets/textures/paper_texture_clean.png');

type TripCardProps = {
  trip: TripSummary;
  width: number;
  favorite?: boolean;
  upcoming?: boolean;
  onFavorite?: () => void;
  onPress?: () => void;
};

export function TripCard({ trip, width, favorite = false, upcoming = false, onFavorite, onPress }: TripCardProps) {
  const compact = width < 360;
  const accent = accentColors[trip.accent];
  const cardHeight = compact ? 164 : 176;
  const imageWidth = compact ? 124 : 138;
  const imageHeight = compact ? 104 : 116;
  const [origin, destination] = splitRoute(trip.routeLabel);
  const routeCoordinates = findRouteCoordinates(trip, origin, destination);
  const mapUrl = routeCoordinates
    ? mapboxFlightImageUrlFromCoordinates(routeCoordinates.origin, routeCoordinates.destination, 400, 320, accent)
    : mapboxFlightImageUrl(origin, destination, 400, 320, accent);
  const imageSource = trip.destinationImage ?? (mapUrl ? { uri: mapUrl } : undefined);
  const [imageFailed, setImageFailed] = React.useState(false);
  const [imageAttempt, setImageAttempt] = React.useState(0);

  React.useEffect(() => {
    setImageFailed(false);
    setImageAttempt(0);
  }, [mapUrl, trip.destinationImage, trip.id]);

  return (
    <Pressable
      onPress={onPress}
      hitSlop={{ top: 4, bottom: 4, left: 4, right: 4 }}
      style={[styles.shadowWrap, { width }]}
    >
      <ImageBackground
        source={paperTexture}
        resizeMode="cover"
        imageStyle={styles.paperTexture}
        style={[styles.card, { height: cardHeight }]}
      >
        <View style={[styles.accentRail, { backgroundColor: accent }]} />

        <View style={[styles.mainContent, { marginRight: imageWidth + 18 }]}>
          {upcoming ? <Text allowFontScaling={false} style={[styles.upcomingLabel, { color: accent }]}>UPCOMING</Text> : null}
          <View style={styles.titleRow}>
            <Text maxFontSizeMultiplier={1.05} numberOfLines={2} adjustsFontSizeToFit style={[styles.title, compact && styles.titleCompact]}>
              {trip.title}
            </Text>
          </View>

          <View style={styles.routeRow}>
            <Text allowFontScaling={false} numberOfLines={1} style={[styles.airportCode, { color: accent }]}>{origin}</Text>
            <View style={styles.flightPathWrap}>
              <Svg width="30" height="14" viewBox="0 0 30 14">
                <Path
                  d="M 2 12 Q 15 3 28 12"
                  fill="none"
                  stroke={accent}
                  strokeWidth="1.5"
                  strokeDasharray="3,3"
                  strokeLinecap="round"
                />
              </Svg>
            </View>
            <Text allowFontScaling={false} numberOfLines={1} style={[styles.airportCode, { color: accent }]}>{destination}</Text>
          </View>

          <Text maxFontSizeMultiplier={1.05} numberOfLines={1} style={styles.dateText}>
            {formatReadableDate(trip.startDate, trip.endDate)}
          </Text>
          <Text maxFontSizeMultiplier={1.05} numberOfLines={1} adjustsFontSizeToFit style={styles.metaText}>
            {trip.flightCount} flights  •  {trip.miles.toLocaleString()} mi
          </Text>
        </View>



        <View style={[styles.photoFrame, { width: imageWidth, height: imageHeight }]}>
          {imageSource && !imageFailed ? (
            <Image
              key={`trip-map-${trip.id}-${imageAttempt}`}
              source={imageSource}
              resizeMode="cover"
              style={StyleSheet.absoluteFillObject}
              onError={() => {
                if (mapUrl && !trip.destinationImage && imageAttempt < 2) {
                  setImageAttempt((attempt) => attempt + 1);
                  return;
                }
                setImageFailed(true);
              }}
            />
          ) : (
            <RouteFallback origin={origin} destination={destination} accent={accent} />
          )}
          <Pressable
            hitSlop={8}
            onPress={(event: GestureResponderEvent) => {
              event.stopPropagation();
              onFavorite?.();
            }}
            style={styles.favoriteBubble}
          >
            <Text allowFontScaling={false} style={[styles.favoriteStar, favorite && styles.favoriteStarFilled]}>
              {favorite ? '★' : '☆'}
            </Text>
          </Pressable>
        </View>
      </ImageBackground>
    </Pressable>
  );
}

function findRouteCoordinates(trip: TripSummary, originCode: string, destinationCode: string) {
  const points = (trip.segments ?? []).flatMap((segment) => [segment.depPoint, segment.arrPoint]).filter(Boolean);
  const origin = points.find((point) => point?.code === originCode);
  const destination = points.find((point) => point?.code === destinationCode);
  if (!origin || !destination) return undefined;
  return {
    origin: [origin.lon, origin.lat] as [number, number],
    destination: [destination.lon, destination.lat] as [number, number],
  };
}

function RouteFallback({ origin, destination, accent }: { origin: string; destination: string; accent: string }) {
  return (
    <View style={styles.routeFallback}>
      <Text allowFontScaling={false} style={styles.fallbackKicker}>FLIGHT PATH</Text>
      <View style={styles.fallbackRoute}>
        <Text allowFontScaling={false} style={styles.fallbackCode}>{origin}</Text>
        <View style={styles.fallbackLine}>
          <View style={[styles.fallbackDot, { borderColor: accent }]} />
          <View style={[styles.fallbackTrack, { backgroundColor: accent }]} />
          <View style={[styles.fallbackDot, { borderColor: accent }]} />
        </View>
        <Text allowFontScaling={false} style={styles.fallbackCode}>{destination}</Text>
      </View>
    </View>
  );
}

function splitRoute(routeLabel: string) {
  const normalized = routeLabel.replace('→', '->');
  const [origin, destination] = normalized.split('->').map((part) => part.trim());
  return [origin || 'DFW', destination || '---'];
}

function formatReadableDate(start: string, end: string) {
  const startDate = new Date(`${start}T00:00:00`);
  const endDate = new Date(`${end}T00:00:00`);
  const startMonth = startDate.toLocaleString('en-US', { month: 'short' });
  const endMonth = endDate.toLocaleString('en-US', { month: 'short' });
  return `${startMonth} ${startDate.getDate()} – ${endMonth} ${endDate.getDate()}, ${endDate.getFullYear()}`;
}

const styles = StyleSheet.create({
  shadowWrap: {
    borderRadius: 16,
    ...shadows.paper,
  },
  card: {
    position: 'relative',
    flexDirection: 'row',
    alignItems: 'center',
    overflow: 'hidden',
    borderRadius: 15,
    borderWidth: 1,
    borderColor: colors.paperBorder,
    backgroundColor: colors.paper,
  },
  paperTexture: {
    borderRadius: 15,
    opacity: 0.22,
  },
  accentRail: {
    width: 6,
    alignSelf: 'stretch',
  },

  mainContent: {
    flex: 1,
    minWidth: 0,
    alignSelf: 'stretch',
    justifyContent: 'center',
    paddingLeft: 14,
    paddingRight: 0,
    zIndex: 2,
  },
  upcomingLabel: {
    fontFamily: fonts.sansBold,
    fontSize: 8,
    letterSpacing: 1.1,
    marginBottom: 3,
  },
  titleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 7,
  },
  title: {
    flex: 1,
    minWidth: 0,
    color: colors.ink,
    fontFamily: 'Georgia',
    fontSize: 24,
    lineHeight: 26,
    fontWeight: '500',
  },
  titleCompact: {
    fontSize: 21,
    lineHeight: 23,
  },
  countryCode: {
    color: colors.ink,
    fontFamily: fonts.mono,
    fontSize: 10,
    borderWidth: 1,
    borderColor: colors.paperBorder,
    paddingHorizontal: 5,
    paddingVertical: 1,
    backgroundColor: colors.paperSoft,
  },
  routeRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginTop: 6,
  },
  flightPathWrap: {
    width: 30,
    height: 14,
    marginHorizontal: 5,
    alignItems: 'center',
    justifyContent: 'flex-start',
    marginTop: 2,
  },
  airportCode: {
    fontFamily: fonts.sansBold,
    fontSize: 14,
    letterSpacing: 1,
  },
  dateText: {
    color: colors.ink,
    fontFamily: fonts.sansRegular,
    fontSize: 11.5,
    marginTop: 6,
  },
  metaText: {
    color: colors.mutedInk,
    fontFamily: fonts.sansRegular,
    fontSize: 11.5,
    marginTop: 5,
  },

  photoFrame: {
    position: 'absolute',
    right: 9,
    top: 30,
    borderWidth: 4,
    borderColor: colors.paperSoft,
    backgroundColor: colors.dashboard,
    overflow: 'hidden',
    transform: [{ rotate: '2deg' }],
    zIndex: 3,
    ...shadows.paper,
  },
  routeFallback: {
    flex: 1,
    justifyContent: 'center',
    paddingHorizontal: 10,
    backgroundColor: '#17262A',
  },
  fallbackKicker: {
    color: colors.subtleText,
    fontFamily: fonts.sansBold,
    fontSize: 7,
    letterSpacing: 1,
    textAlign: 'center',
    marginBottom: 10,
  },
  fallbackRoute: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 4,
  },
  fallbackCode: {
    color: colors.creamText,
    fontFamily: fonts.mono,
    fontSize: 11,
  },
  fallbackLine: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
  },
  fallbackDot: {
    width: 6,
    height: 6,
    borderRadius: 3,
    borderWidth: 1.5,
  },
  fallbackTrack: {
    flex: 1,
    height: 1,
    opacity: 0.8,
  },
  favoriteBubble: {
    position: 'absolute',
    top: 5,
    right: 5,
    width: 29,
    height: 29,
    borderRadius: 15,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.dashboard,
    borderWidth: 1,
    borderColor: colors.darkBorder,
    zIndex: 4,
  },
  favoriteStar: {
    color: colors.brassSoft,
    fontSize: 18,
    lineHeight: 20,
  },
  favoriteStarFilled: {
    color: colors.brassSoft,
  },
});
