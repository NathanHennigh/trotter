import React from 'react';
import { Image, ImageBackground, StyleSheet, Text, View } from 'react-native';
import { TripSummary } from '../../data/trotterMock';
import { accentColors, colors, fonts, radii, shadows } from '../../theme/trotterTheme';
import { IconGlyph } from './TrotterKit';
import { PngStamp } from './stamps/PngStamp';

const paperTexture = require('../../../assets/textures/paper_texture_clean.png');

type TripCardProps = {
  trip: TripSummary;
  width: number;
  favorite?: boolean;
};

export function TripCard({ trip, width, favorite = false }: TripCardProps) {
  const compact = width < 370;
  const accent = accentColors[trip.accent];
  const cardHeight = compact ? 140 : 156;
  const stripWidth = compact ? 48 : 54;
  const dateWidth = compact ? 54 : 58;
  const imageWidth = Math.max(compact ? 106 : 116, Math.min(compact ? 114 : 128, width * 0.32));
  const imageHeight = compact ? 72 : 84;
  const stampSize = 'md';
  const [origin, destination] = splitRoute(trip.routeLabel);

  return (
    <View style={[styles.shadowWrap, { width }]}>
      <ImageBackground
        source={paperTexture}
        resizeMode="cover"
        imageStyle={styles.paperTexture}
        style={[styles.card, { height: cardHeight }]}
      >
        <View style={[styles.accentStrip, { width: stripWidth, backgroundColor: accent }]}>
          <View style={styles.stripInset} />
          <View style={styles.punchOuter}>
            <View style={styles.punchInner} />
          </View>
        </View>

        <View style={[styles.dateColumn, { width: dateWidth }]}>
          <Text allowFontScaling={false} numberOfLines={1} adjustsFontSizeToFit style={styles.verticalDate}>
            {formatVerticalDate(trip.startDate, trip.endDate)}
          </Text>
        </View>

        <View style={[styles.mainContent, { marginRight: imageWidth - (compact ? 20 : 16) }]}>
          <View style={styles.titleRow}>
            <Text maxFontSizeMultiplier={1.05} numberOfLines={1} adjustsFontSizeToFit style={[styles.title, compact && styles.titleCompact]}>
              {trip.title}
            </Text>
            {trip.countryCode ? (
              <Text allowFontScaling={false} numberOfLines={1} style={styles.countryCode}>
                {trip.countryCode}
              </Text>
            ) : null}
          </View>

          <View style={styles.routeRow}>
            <Text allowFontScaling={false} numberOfLines={1} style={[styles.airportCode, { color: accent }]}>{origin}</Text>
            <IconGlyph name="plane" color={accent} size={20} />
            <Text allowFontScaling={false} numberOfLines={1} style={[styles.airportCode, { color: accent }]}>{destination}</Text>
          </View>

          <Text maxFontSizeMultiplier={1.05} numberOfLines={1} style={styles.dateText}>
            {formatReadableDate(trip.startDate, trip.endDate)}
          </Text>
          <Text maxFontSizeMultiplier={1.05} numberOfLines={1} adjustsFontSizeToFit style={styles.metaText}>
            {trip.flightCount} flights  •  {trip.miles.toLocaleString()} mi  •  {trip.airlineCount} airline{trip.airlineCount === 1 ? '' : 's'}
          </Text>
        </View>

        <View pointerEvents="none" style={[styles.stampWrap, { right: compact ? 105 : 112 }]}>
          <PngStamp
            {...trip.stamp}
            size={stampSize}
            variant="trip-card"
            rotate={trip.id.includes('paris') ? 2 : -8}
          />
        </View>

        <View style={[styles.photoFrame, { width: imageWidth, height: imageHeight }]}>
          {trip.destinationImage ? (
            <Image source={trip.destinationImage} resizeMode="cover" style={StyleSheet.absoluteFillObject} />
          ) : (
            <View style={[styles.photoPlaceholder, { backgroundColor: getPhotoTone(trip.id) }]}>
              <View style={styles.placeholderSun} />
              <View style={styles.placeholderHorizon} />
              <View style={styles.placeholderRidgeA} />
              <View style={styles.placeholderRidgeB} />
              <Text allowFontScaling={false} style={styles.placeholderCode}>{trip.countryCode}</Text>
            </View>
          )}
          <View style={styles.favoriteBubble}>
            <Text allowFontScaling={false} style={[styles.favoriteStar, favorite && styles.favoriteStarFilled]}>
              {favorite ? '★' : '☆'}
            </Text>
          </View>
        </View>
      </ImageBackground>
    </View>
  );
}

function splitRoute(routeLabel: string) {
  const normalized = routeLabel.replace('→', '->');
  const [origin, destination] = normalized.split('->').map((part) => part.trim());
  return [origin || 'DFW', destination || '---'];
}

function formatVerticalDate(start: string, end: string) {
  const startDate = new Date(`${start}T00:00:00`);
  const endDate = new Date(`${end}T00:00:00`);
  const startMonth = startDate.toLocaleString('en-US', { month: 'short' }).toUpperCase();
  const endMonth = endDate.toLocaleString('en-US', { month: 'short' }).toUpperCase();
  return `${startMonth} ${startDate.getDate()} – ${endMonth} ${endDate.getDate()}, ${endDate.getFullYear()}`;
}

function formatReadableDate(start: string, end: string) {
  const startDate = new Date(`${start}T00:00:00`);
  const endDate = new Date(`${end}T00:00:00`);
  const startMonth = startDate.toLocaleString('en-US', { month: 'short' });
  const endMonth = endDate.toLocaleString('en-US', { month: 'short' });
  return `${startMonth} ${startDate.getDate()} – ${endMonth} ${endDate.getDate()}, ${endDate.getFullYear()}`;
}

function getPhotoTone(id: string) {
  if (id.includes('tokyo')) return '#1D3940';
  if (id.includes('paris')) return '#254A4C';
  if (id.includes('denver')) return '#665436';
  if (id.includes('cancun')) return '#2F6B66';
  if (id.includes('barcelona')) return '#604637';
  return '#40575A';
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
  accentStrip: {
    alignSelf: 'stretch',
    alignItems: 'center',
    justifyContent: 'center',
    borderRightWidth: 1,
    borderRightColor: 'rgba(64, 42, 20, 0.25)',
  },
  stripInset: {
    ...StyleSheet.absoluteFillObject,
    borderRightWidth: 1,
    borderRightColor: 'rgba(255, 246, 225, 0.24)',
  },
  punchOuter: {
    width: 27,
    height: 27,
    borderRadius: 14,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: 'rgba(0,0,0,0.18)',
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.22)',
  },
  punchInner: {
    width: 17,
    height: 17,
    borderRadius: 9,
    backgroundColor: colors.paper,
    borderWidth: 1,
    borderColor: colors.paperBorder,
  },
  dateColumn: {
    alignSelf: 'stretch',
    alignItems: 'center',
    justifyContent: 'center',
    borderRightWidth: 1,
    borderStyle: 'dotted',
    borderRightColor: colors.divider,
  },
  verticalDate: {
    width: 142,
    color: colors.ink,
    fontFamily: fonts.mono,
    fontSize: 10.5,
    letterSpacing: 0.7,
    textAlign: 'center',
    transform: [{ rotate: '-90deg' }],
  },
  mainContent: {
    flex: 1,
    minWidth: 0,
    alignSelf: 'stretch',
    justifyContent: 'center',
    paddingLeft: 12,
    paddingRight: 2,
    zIndex: 2,
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
    fontSize: 28,
    lineHeight: 32,
    fontWeight: '500',
  },
  titleCompact: {
    fontSize: 24,
    lineHeight: 29,
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
    gap: 9,
    marginTop: 7,
  },
  airportCode: {
    fontFamily: fonts.sansBold,
    fontSize: 18,
    letterSpacing: 1.4,
  },
  dateText: {
    color: colors.ink,
    fontFamily: fonts.sansRegular,
    fontSize: 12.5,
    marginTop: 6,
  },
  metaText: {
    color: colors.mutedInk,
    fontFamily: fonts.sansRegular,
    fontSize: 12,
    marginTop: 5,
  },
  stampWrap: {
    position: 'absolute',
    top: 56,
    zIndex: 1,
    opacity: 0.78,
    transform: [{ scale: 0.84 }],
  },
  photoFrame: {
    position: 'absolute',
    right: 20,
    top: 36,
    borderWidth: 6,
    borderColor: colors.paperSoft,
    backgroundColor: colors.dashboard,
    overflow: 'hidden',
    transform: [{ rotate: '4deg' }],
    zIndex: 3,
    ...shadows.paper,
  },
  photoPlaceholder: {
    flex: 1,
    overflow: 'hidden',
  },
  placeholderSun: {
    position: 'absolute',
    right: 13,
    top: 11,
    width: 18,
    height: 18,
    borderRadius: 9,
    backgroundColor: 'rgba(248, 238, 219, 0.75)',
  },
  placeholderHorizon: {
    position: 'absolute',
    left: 0,
    right: 0,
    bottom: 22,
    height: 1,
    backgroundColor: 'rgba(248, 238, 219, 0.28)',
  },
  placeholderRidgeA: {
    position: 'absolute',
    left: -8,
    bottom: 0,
    width: 84,
    height: 38,
    backgroundColor: 'rgba(10, 12, 10, 0.26)',
    transform: [{ rotate: '-10deg' }],
  },
  placeholderRidgeB: {
    position: 'absolute',
    right: -12,
    bottom: 0,
    width: 80,
    height: 44,
    backgroundColor: 'rgba(248, 238, 219, 0.16)',
    transform: [{ rotate: '11deg' }],
  },
  placeholderCode: {
    position: 'absolute',
    left: 8,
    bottom: 6,
    color: 'rgba(248, 238, 219, 0.82)',
    fontFamily: fonts.mono,
    fontSize: 11,
    letterSpacing: 1.2,
  },
  favoriteBubble: {
    position: 'absolute',
    top: -8,
    right: -8,
    width: 34,
    height: 34,
    borderRadius: 17,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.dashboard,
    borderWidth: 1,
    borderColor: colors.darkBorder,
    zIndex: 4,
  },
  favoriteStar: {
    color: colors.brassSoft,
    fontSize: 22,
    lineHeight: 24,
  },
  favoriteStarFilled: {
    color: colors.brassSoft,
  },
});
