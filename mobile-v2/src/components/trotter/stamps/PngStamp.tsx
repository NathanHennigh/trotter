import React from 'react';
import { Image, ImageSourcePropType, StyleSheet, Text, View } from 'react-native';
import Svg, { Defs, Path, Text as SvgText, TextPath } from 'react-native-svg';
import {
  CountryIconAssetKey,
  StampShapeAssetKey,
  countryIconAssets,
  stampShapeAssets,
} from '../../../assets/generated/stampAssetManifest';
import { colors, fonts } from '../../../theme/trotterTheme';

export type StampShapeKey =
  | 'archedCountryCanonical'
  | 'archedCountryBanner'
  | 'archedCountryVariant'
  | 'circularCityClean'
  | 'circularCityDoubleLine'
  | 'roundedImmigrationCanonical'
  | 'roundedImmigrationWithBand'
  | 'shieldBadgeRounded'
  | 'ticketStubNotched'
  | 'horizontalAirportOblong';

export type CountryIconKey = CountryIconAssetKey | string;

export type PngStampProps = {
  shape: StampShapeKey;
  icon?: CountryIconKey;
  color: string;
  country: string;
  city?: string;
  airportCode?: string;
  date?: string;
  footer?: string;
  size?: 'sm' | 'md' | 'lg';
  variant?: 'trip-card' | 'country-card' | 'collection';
  faded?: boolean;
  rotate?: number;
  scale?: number;
};

export const stampInkColors = {
  red: '#B6543F',
  blue: '#2F5E9E',
  green: '#52745A',
  brown: '#9A5A32',
  mustard: '#C79A43',
} as const;

const shapeAssetKeyMap: Record<StampShapeKey, StampShapeAssetKey> = {
  archedCountryCanonical: 'arched_country_canonical',
  archedCountryBanner: 'arched_country_banner',
  archedCountryVariant: 'arched_country_variant',
  circularCityClean: 'circular_city_clean',
  circularCityDoubleLine: 'circular_city_double_line',
  roundedImmigrationCanonical: 'rounded_immigration_canonical',
  roundedImmigrationWithBand: 'rounded_immigration_with_band',
  shieldBadgeRounded: 'shield_badge_rounded',
  ticketStubNotched: 'ticket_stub_notched',
  horizontalAirportOblong: 'horizontal_airport_oblong',
};

const sizeConfig = {
  sm: {
    width: 149.5,
    height: 117,
    icon: 45.5,
    country: 17.9,
    meta: 12.2,
    date: 11.05,
    footer: 11.4,
  },
  md: {
    width: 204.75,
    height: 165.75,
    icon: 65,
    country: 22.75,
    meta: 14.6,
    date: 13.16,
    footer: 12.2,
  },
  lg: {
    width: 269.75,
    height: 214.5,
    icon: 87.75,
    country: 29.25,
    meta: 17.9,
    date: 15.44,
    footer: 14.625,
  },
} as const;

type Box = {
  left: number;
  top: number;
  width: number;
  height: number;
};

type TextBox = Box & {
  fontScale?: number;
  minScale?: number;
  charFactor?: number;
  tracking?: number;
};

type StampTemplate = {
  frame: Box;
  titleMode: 'straight' | 'arc' | 'circleArc';
  arcDepth?: number;
  arcTextLength?: number;
  straightTitleMaxChars?: number;
  maxCountryChars: number;
  maxPlaceChars: number;
  country: TextBox;
  icon: Box;
  place: TextBox;
  date: TextBox;
  footer: TextBox;
};

const templates: Record<StampShapeKey, StampTemplate> = {
  archedCountryCanonical: {
    frame: { left: 0.08, top: 0.03, width: 0.84, height: 0.92 },
    titleMode: 'arc',
    arcDepth: 0.78,
    arcTextLength: 0.66,
    maxCountryChars: 14,
    maxPlaceChars: 12,
    country: { left: 0.16, top: 0.20, width: 0.68, height: 0.16, fontScale: 0.56, minScale: 0.32, charFactor: 0.95, tracking: 0.34 },
    icon: { left: 0.34, top: 0.40, width: 0.32, height: 0.22 },
    place: { left: 0.19, top: 0.66, width: 0.62, height: 0.08, fontScale: 0.86, minScale: 0.52 },
    date: { left: 0.19, top: 0.78, width: 0.62, height: 0.09, fontScale: 0.7, minScale: 0.52 },
    footer: { left: 0.21, top: 0.86, width: 0.58, height: 0.07, fontScale: 0.9, minScale: 0.62 },
  },
  archedCountryBanner: {
    frame: { left: 0.08, top: 0.03, width: 0.84, height: 0.92 },
    titleMode: 'arc',
    arcDepth: 0.74,
    arcTextLength: 0.66,
    maxCountryChars: 14,
    maxPlaceChars: 12,
    country: { left: 0.16, top: 0.13, width: 0.68, height: 0.16, fontScale: 0.7, minScale: 0.4, charFactor: 0.74, tracking: 0.5 },
    icon: { left: 0.34, top: 0.40, width: 0.32, height: 0.22 },
    place: { left: 0.18, top: 0.66, width: 0.64, height: 0.08, fontScale: 0.96, minScale: 0.58 },
    date: { left: 0.18, top: 0.78, width: 0.64, height: 0.09, fontScale: 0.7, minScale: 0.52 },
    footer: { left: 0.2, top: 0.86, width: 0.6, height: 0.07, fontScale: 0.9, minScale: 0.62 },
  },
  archedCountryVariant: {
    frame: { left: 0.08, top: 0.04, width: 0.84, height: 0.9 },
    titleMode: 'arc',
    arcDepth: 0.58,
    arcTextLength: 0.62,
    maxCountryChars: 12,
    maxPlaceChars: 11,
    country: { left: 0.17, top: 0.15, width: 0.66, height: 0.14, fontScale: 0.7, minScale: 0.4, charFactor: 0.76, tracking: 0.45 },
    icon: { left: 0.35, top: 0.40, width: 0.3, height: 0.21 },
    place: { left: 0.2, top: 0.66, width: 0.6, height: 0.08, fontScale: 0.94, minScale: 0.58 },
    date: { left: 0.2, top: 0.78, width: 0.6, height: 0.09, fontScale: 0.7, minScale: 0.52 },
    footer: { left: 0.22, top: 0.86, width: 0.56, height: 0.07, fontScale: 0.9, minScale: 0.62 },
  },
  circularCityClean: {
    frame: { left: 0.08, top: 0.06, width: 0.84, height: 0.84 },
    titleMode: 'circleArc',
    arcDepth: 2.35,
    arcTextLength: 0.88,
    straightTitleMaxChars: 6,
    maxCountryChars: 13,
    maxPlaceChars: 11,
    country: { left: 0.08, top: 0.10, width: 0.84, height: 0.18, fontScale: 0.58, minScale: 0.30, charFactor: 0.9, tracking: 0.24 },
    icon: { left: 0.35, top: 0.34, width: 0.3, height: 0.21 },
    place: { left: 0.21, top: 0.55, width: 0.58, height: 0.08, fontScale: 0.72, minScale: 0.46 },
    date: { left: 0.21, top: 0.63, width: 0.58, height: 0.08, fontScale: 0.62, minScale: 0.48 },
    footer: { left: 0.22, top: 0.81, width: 0.56, height: 0.08, fontScale: 0.82, minScale: 0.56 },
  },
  circularCityDoubleLine: {
    frame: { left: 0.08, top: 0.06, width: 0.84, height: 0.84 },
    titleMode: 'circleArc',
    arcDepth: 2.4,
    arcTextLength: 0.9,
    straightTitleMaxChars: 6,
    maxCountryChars: 13,
    maxPlaceChars: 11,
    country: { left: 0.08, top: 0.10, width: 0.84, height: 0.18, fontScale: 0.56, minScale: 0.30, charFactor: 0.92, tracking: 0.22 },
    icon: { left: 0.35, top: 0.34, width: 0.3, height: 0.21 },
    place: { left: 0.21, top: 0.55, width: 0.58, height: 0.08, fontScale: 0.72, minScale: 0.46 },
    date: { left: 0.21, top: 0.63, width: 0.58, height: 0.08, fontScale: 0.62, minScale: 0.48 },
    footer: { left: 0.22, top: 0.81, width: 0.56, height: 0.08, fontScale: 0.82, minScale: 0.56 },
  },
  roundedImmigrationCanonical: {
    frame: { left: 0.04, top: 0.14, width: 0.92, height: 0.72 },
    titleMode: 'straight',
    maxCountryChars: 20,
    maxPlaceChars: 12,
    country: { left: 0.12, top: 0.235, width: 0.76, height: 0.09, fontScale: 0.64, minScale: 0.36, charFactor: 0.82, tracking: 0.28 },
    icon: { left: 0.38, top: 0.4, width: 0.24, height: 0.2 },
    place: { left: 0.16, top: 0.60, width: 0.68, height: 0.08, fontScale: 0.92, minScale: 0.54 },
    date: { left: 0.17, top: 0.67, width: 0.66, height: 0.08, fontScale: 0.66, minScale: 0.5 },
    footer: { left: 0.2, top: 0.78, width: 0.6, height: 0.07, fontScale: 0.78, minScale: 0.52 },
  },
  roundedImmigrationWithBand: {
    frame: { left: 0.04, top: 0.14, width: 0.92, height: 0.72 },
    titleMode: 'straight',
    maxCountryChars: 20,
    maxPlaceChars: 12,
    country: { left: 0.12, top: 0.235, width: 0.76, height: 0.09, fontScale: 0.64, minScale: 0.36, charFactor: 0.82, tracking: 0.28 },
    icon: { left: 0.38, top: 0.4, width: 0.24, height: 0.2 },
    place: { left: 0.16, top: 0.60, width: 0.68, height: 0.08, fontScale: 0.92, minScale: 0.54 },
    date: { left: 0.17, top: 0.67, width: 0.66, height: 0.08, fontScale: 0.66, minScale: 0.5 },
    footer: { left: 0.2, top: 0.78, width: 0.6, height: 0.07, fontScale: 0.78, minScale: 0.52 },
  },
  shieldBadgeRounded: {
    frame: { left: 0.1, top: 0.04, width: 0.8, height: 0.9 },
    titleMode: 'arc',
    arcDepth: 0.35,
    arcTextLength: 0.58,
    maxCountryChars: 11,
    maxPlaceChars: 10,
    country: { left: 0.19, top: 0.18, width: 0.62, height: 0.13, fontScale: 0.66, minScale: 0.36, charFactor: 0.76, tracking: 0.4 },
    icon: { left: 0.36, top: 0.39, width: 0.28, height: 0.2 },
    place: { left: 0.2, top: 0.62, width: 0.6, height: 0.08, fontScale: 0.88, minScale: 0.52 },
    date: { left: 0.21, top: 0.74, width: 0.58, height: 0.08, fontScale: 0.64, minScale: 0.48 },
    footer: { left: 0.22, top: 0.83, width: 0.56, height: 0.07, fontScale: 0.78, minScale: 0.52 },
  },
  ticketStubNotched: {
    frame: { left: 0.03, top: 0.2, width: 0.94, height: 0.6 },
    titleMode: 'straight',
    maxCountryChars: 16,
    maxPlaceChars: 12,
    country: { left: 0.13, top: 0.27, width: 0.74, height: 0.09, fontScale: 0.62, minScale: 0.42, tracking: 0.4 },
    icon: { left: 0.38, top: 0.43, width: 0.24, height: 0.18 },
    place: { left: 0.15, top: 0.62, width: 0.7, height: 0.08, fontScale: 0.86, minScale: 0.54 },
    date: { left: 0.16, top: 0.71, width: 0.68, height: 0.08, minScale: 0.58 },
    footer: { left: 0.2, top: 0.79, width: 0.6, height: 0.07, fontScale: 0.74, minScale: 0.52 },
  },
  horizontalAirportOblong: {
    frame: { left: 0.03, top: 0.24, width: 0.94, height: 0.52 },
    titleMode: 'straight',
    maxCountryChars: 16,
    maxPlaceChars: 12,
    country: { left: 0.12, top: 0.31, width: 0.76, height: 0.08, fontScale: 0.6, minScale: 0.42, tracking: 0.35 },
    icon: { left: 0.4, top: 0.44, width: 0.2, height: 0.14 },
    place: { left: 0.15, top: 0.59, width: 0.7, height: 0.07, fontScale: 0.78, minScale: 0.5 },
    date: { left: 0.16, top: 0.67, width: 0.68, height: 0.07, minScale: 0.54 },
    footer: { left: 0.2, top: 0.75, width: 0.6, height: 0.06, fontScale: 0.7, minScale: 0.5 },
  },
};

const iconAssets = countryIconAssets as Record<string, ImageSourcePropType>;
const shapeAssets = stampShapeAssets as Record<string, ImageSourcePropType>;

function resolveIcon(icon?: CountryIconKey) {
  if (!icon) return undefined;
  return iconAssets[String(icon)];
}

function formatStampDate(date?: string) {
  if (!date) return undefined;
  const parsed = new Date(`${date}T00:00:00`);
  if (Number.isNaN(parsed.getTime())) return date.toUpperCase();

  const day = String(parsed.getDate()).padStart(2, '0');
  const month = parsed.toLocaleString('en-US', { month: 'short' }).toUpperCase();
  return `${day} ${month} ${parsed.getFullYear()}`;
}

function getPlaceLine(city?: string, airportCode?: string, omitAirportCode?: boolean) {
  if (omitAirportCode) return city;
  if (city && airportCode) return `${city} (${airportCode})`;
  return city ?? airportCode;
}

function fitToLimit(value: string | undefined, maxChars: number) {
  if (!value) return undefined;
  const normalized = value.replace(/\s+/g, ' ').trim();
  if (normalized.length <= maxChars) return normalized;
  if (normalized.includes(' ')) return normalized;
  return normalized.slice(0, maxChars);
}

function fitFontSize(text: string, baseSize: number, boxWidth: number, boxHeight: number, options?: TextBox) {
  const charFactor = options?.charFactor ?? 0.62;
  const minScale = options?.minScale ?? 0.5;
  const tracking = options?.tracking ?? 0;
  const estimatedWidth = Math.max(1, text.length * baseSize * charFactor + Math.max(0, text.length - 1) * tracking);
  const widthScale = Math.min(1, boxWidth / estimatedWidth);
  const heightScale = Math.min(1, (boxHeight * 0.88) / baseSize);
  return baseSize * Math.max(minScale, Math.min(widthScale, heightScale));
}

function StampText({
  text,
  box,
  rootWidth,
  rootHeight,
  baseSize,
  color,
  mono,
}: {
  text?: string;
  box: TextBox;
  rootWidth: number;
  rootHeight: number;
  baseSize: number;
  color: string;
  mono?: boolean;
}) {
  if (!text) return null;
  const boxWidth = rootWidth * box.width;
  const boxHeight = rootHeight * box.height;
  const fontSize = fitFontSize(text, baseSize * (box.fontScale ?? 1), boxWidth, boxHeight, box);

  return (
    <Text
      allowFontScaling={false}
      numberOfLines={1}
      adjustsFontSizeToFit
      minimumFontScale={box.minScale ?? 0.5}
      style={[
        styles.text,
        {
          color,
          fontFamily: mono ? fonts.mono : fonts.sansBold,
          fontSize,
          lineHeight: boxHeight,
          letterSpacing: (box.tracking ?? 0.4) * Math.min(1, fontSize / baseSize),
          left: rootWidth * box.left,
          top: rootHeight * box.top,
          width: boxWidth,
          height: boxHeight,
        },
      ]}
    >
      {text}
    </Text>
  );
}

function ArcStampText({
  text,
  box,
  rootWidth,
  rootHeight,
  baseSize,
  color,
  arcDepth = 0.7,
  arcTextLength,
}: {
  text?: string;
  box: TextBox;
  rootWidth: number;
  rootHeight: number;
  baseSize: number;
  color: string;
  arcDepth?: number;
  arcTextLength?: number;
}) {
  const pathId = React.useId().replace(/[^a-zA-Z0-9_-]/g, '');
  if (!text) return null;
  const boxWidth = rootWidth * box.width;
  const boxHeight = rootHeight * box.height;
  const fontSize = fitFontSize(text, baseSize * (box.fontScale ?? 1), boxWidth, boxHeight * 0.58, box);
  const isCircleArc = arcDepth >= 1.8;
  const yStart = boxHeight * (isCircleArc ? 0.96 : Math.min(0.88, 0.6 + arcDepth * 0.15));
  const yMid = boxHeight * (isCircleArc ? -0.18 : Math.max(0.06, 0.52 - arcDepth * 0.34));
  const xInset = isCircleArc ? -0.06 : arcDepth >= 1.2 ? 0.04 : 0.08;
  const path = `M ${boxWidth * xInset} ${yStart} C ${boxWidth * 0.18} ${yMid}, ${boxWidth * 0.82} ${yMid}, ${boxWidth * (1 - xInset)} ${yStart}`;
  const textLength = boxWidth * (arcTextLength ?? (isCircleArc ? 0.88 : 0.64));

  return (
    <Svg
      pointerEvents="none"
      width={boxWidth}
      height={boxHeight}
      style={[
        styles.svgText,
        {
          left: rootWidth * box.left,
          top: rootHeight * box.top,
        },
      ]}
    >
      <Defs>
        <Path id={pathId} d={path} />
      </Defs>
      <SvgText
        fill={color}
        fontFamily={fonts.sansBold}
        fontSize={fontSize}
        fontWeight="700"
        letterSpacing={(box.tracking ?? 0.3) * Math.min(1, fontSize / baseSize)}
        lengthAdjust="spacingAndGlyphs"
        textAnchor="middle"
        textLength={textLength}
      >
        <TextPath href={`#${pathId}`} startOffset="50%">
          {text}
        </TextPath>
      </SvgText>
    </Svg>
  );
}

function CircleArcStampText({
  text,
  box,
  frame,
  rootWidth,
  rootHeight,
  baseSize,
  color,
}: {
  text?: string;
  box: TextBox;
  frame: Box;
  rootWidth: number;
  rootHeight: number;
  baseSize: number;
  color: string;
}) {
  if (!text) return null;
  const frameLeft = rootWidth * frame.left;
  const frameTop = rootHeight * frame.top;
  const frameWidth = rootWidth * frame.width;
  const frameHeight = rootHeight * frame.height;
  const ringSize = Math.min(frameWidth, frameHeight);
  const centerX = frameLeft + frameWidth / 2;
  const centerY = frameTop + frameHeight / 2 - frameHeight * 0.02;
  const radius = ringSize * 0.32;
  const maxArcWidth = radius * 2.35;
  const chars = text.split('');
  const minHalfAngle = chars.length >= 10 ? 53 : chars.length >= 8 ? 44 : chars.length >= 7 ? 36 : 0;
  const maxHalfAngle = chars.length >= 14 ? 78 : chars.length >= 10 ? 70 : chars.length >= 8 ? 60 : 48;
  let fontSize = fitFontSize(text, baseSize * (box.fontScale ?? 1), maxArcWidth, rootHeight * box.height * 0.42, box);
  if (chars.length > 1) {
    const arcLengthAtMaxAngle = ((maxHalfAngle * 2) * Math.PI) / 180 * radius;
    const requiredArcLength = (chars.length - 1) * fontSize * 0.78;
    if (requiredArcLength > arcLengthAtMaxAngle) {
      const minFontFloor = baseSize * (box.minScale ?? 0.36) * 0.85;
      fontSize = Math.max(minFontFloor, (arcLengthAtMaxAngle / (chars.length - 1)) / 0.78);
    }
  }
  const charWidth = Math.max(fontSize * 0.78, 4);
  const desiredStepRad = (fontSize * 0.76) / radius;
  const computedHalfAngle = ((desiredStepRad * Math.max(0, chars.length - 1)) / 2) * (180 / Math.PI);
  const halfAngleDeg = Math.min(maxHalfAngle, Math.max(minHalfAngle, computedHalfAngle));
  const step = chars.length > 1 ? (halfAngleDeg * 2) / (chars.length - 1) : 0;

  return (
    <View
      pointerEvents="none"
      style={[
        styles.circleArcText,
        {
          left: 0,
          top: 0,
          width: rootWidth,
          height: rootHeight,
        },
      ]}
    >
      {chars.map((char, index) => {
        const angleDeg = chars.length > 1 ? -halfAngleDeg + step * index : 0;
        const angle = (angleDeg * Math.PI) / 180;
        const x = centerX + Math.sin(angle) * radius - charWidth / 2;
        const y = centerY - Math.cos(angle) * radius - fontSize * 0.52;

        return (
          <Text
            key={`${char}-${index}`}
            allowFontScaling={false}
            style={[
              styles.circleArcChar,
              {
                color,
                fontSize,
                lineHeight: fontSize * 1.08,
                width: charWidth,
                left: x,
                top: y,
                transform: [{ rotate: `${angleDeg * 0.92}deg` }],
              },
            ]}
          >
            {char}
          </Text>
        );
      })}
    </View>
  );
}

export function PngStamp({
  shape,
  icon,
  color,
  country,
  city,
  airportCode,
  date,
  footer,
  size = 'md',
  variant = 'collection',
  faded = false,
  rotate = 0,
  scale = 1,
}: PngStampProps) {
  const config = sizeConfig[size];
  const template = templates[shape];
  const width = config.width * scale;
  const height = config.height * scale;
  const omitAirportCode = variant === 'collection' || variant === 'country-card';
  const countryLabel = fitToLimit(country.toUpperCase(), template.maxCountryChars) ?? country.toUpperCase().slice(0, template.maxCountryChars);
  const placeLine = fitToLimit(getPlaceLine(city, airportCode, omitAirportCode)?.toUpperCase(), template.maxPlaceChars);
  const stampDate = formatStampDate(date);
  const iconSource = resolveIcon(icon);
  const shapeSource = shapeAssets[shapeAssetKeyMap[shape]];
  const textColor = faded ? colors.mutedInk : color;
  const inkOpacity = faded ? 0.36 : 0.92;
  const visibleFooter = footer?.toUpperCase() === 'FIRST VISIT' ? undefined : footer;
  const titleShouldArc =
    (template.titleMode === 'arc' || template.titleMode === 'circleArc') &&
    (!template.straightTitleMaxChars || countryLabel.length > template.straightTitleMaxChars);
  const iconScale = 1.1;
  const iconWidth = width * template.icon.width * iconScale;
  const iconHeight = height * template.icon.height * iconScale;
  const iconLeft = width * (template.icon.left + template.icon.width / 2) - iconWidth / 2;
  const iconTop = height * (template.icon.top + template.icon.height / 2) - iconHeight / 2;

  return (
    <View
      style={[
        styles.root,
        {
          width,
          height,
          opacity: faded ? 0.62 : 1,
          transform: [{ rotate: `${rotate}deg` }],
        },
      ]}
    >
      <Image
        source={shapeSource}
        resizeMode="contain"
        tintColor={color}
        style={[
          styles.shapeImage,
          {
            left: width * template.frame.left,
            top: height * template.frame.top,
            width: width * template.frame.width,
            height: height * template.frame.height,
            opacity: inkOpacity,
          },
        ]}
      />

      {template.titleMode === 'circleArc' && titleShouldArc ? (
        <CircleArcStampText
          text={countryLabel}
          box={template.country}
          frame={template.frame}
          rootWidth={width}
          rootHeight={height}
          baseSize={config.country * scale}
          color={textColor}
        />
      ) : titleShouldArc ? (
        <ArcStampText
          text={countryLabel}
          box={template.country}
          rootWidth={width}
          rootHeight={height}
          baseSize={config.country * scale}
          color={textColor}
          arcDepth={template.arcDepth}
          arcTextLength={template.arcTextLength}
        />
      ) : (
        <StampText
          text={countryLabel}
          box={template.country}
          rootWidth={width}
          rootHeight={height}
          baseSize={config.country * scale}
          color={textColor}
        />
      )}

      {iconSource ? (
        <Image
          source={iconSource}
          resizeMode="contain"
          tintColor={color}
          style={[
            styles.iconImage,
            {
              left: iconLeft,
              top: iconTop,
              width: iconWidth,
              height: iconHeight,
              opacity: faded ? 0.42 : 0.78,
            },
          ]}
        />
      ) : null}

      <StampText
        text={placeLine}
        box={template.place}
        rootWidth={width}
        rootHeight={height}
        baseSize={config.meta * scale}
        color={textColor}
      />
      <StampText
        text={stampDate}
        box={template.date}
        rootWidth={width}
        rootHeight={height}
        baseSize={config.date * scale}
        color={textColor}
        mono
      />
      <StampText
        text={visibleFooter?.toUpperCase()}
        box={template.footer}
        rootWidth={width}
        rootHeight={height}
        baseSize={config.footer * scale}
        color={textColor}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  root: {
    overflow: 'hidden',
  },
  shapeImage: {
    position: 'absolute',
  },
  iconImage: {
    position: 'absolute',
  },
  text: {
    position: 'absolute',
    textAlign: 'center',
    textTransform: 'uppercase',
    includeFontPadding: false,
  },
  svgText: {
    position: 'absolute',
  },
  circleArcText: {
    position: 'absolute',
    overflow: 'visible',
  },
  circleArcChar: {
    position: 'absolute',
    fontFamily: fonts.sansBold,
    textAlign: 'center',
    includeFontPadding: false,
  },
});
