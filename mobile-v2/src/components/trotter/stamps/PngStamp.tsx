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
import stampTemplateBundles from './stampTemplates.json';

export type StampShapeKey =
  | 'archedCountryCanonical'
  | 'archedCountryBanner'
  | 'archedCountryVariant'
  | 'circularCityClean'
  | 'circularCityDoubleLine'
  | 'roundedImmigrationCanonical'
  | 'roundedImmigrationWithBand'
  | 'shieldBadgeRounded';

export type CountryIconKey = CountryIconAssetKey | string;

export type PngStampProps = {
  shape: StampShapeKey;
  icon?: CountryIconKey;
  color: string;
  country: string;
  city?: string;
  airportCode?: string;
  date?: string;
  size?: 'sm' | 'md' | 'lg';
  variant?: 'trip-card' | 'country-card' | 'collection';
  faded?: boolean;
  rotate?: number;
  scale?: number;
  templateOverride?: StampTemplate;
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
};

const sizeConfig = {
  sm: {
    width: 149.5,
    height: 117,
    icon: 45.5,
    country: 17.9,
    meta: 12.2,
    date: 11.05,
    airport: 11.4,
  },
  md: {
    width: 204.75,
    height: 165.75,
    icon: 65,
    country: 22.75,
    meta: 14.6,
    date: 13.16,
    airport: 12.2,
  },
  lg: {
    width: 269.75,
    height: 214.5,
    icon: 87.75,
    country: 29.25,
    meta: 17.9,
    date: 15.44,
    airport: 14.625,
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
  adaptiveLength?: boolean;
};

export type StampTemplate = {
  frame: Box;
  titleMode: 'straight' | 'arc' | 'circleArc';
  arcDepth?: number;
  arcTextLength?: number;
  straightTitleMaxChars?: number;
  arcCenterYOffset?: number;
  maxCountryChars: number;
  maxPlaceChars: number;
  country: TextBox;
  icon: Box;
  place: TextBox;
  date: TextBox;
  airport: TextBox;
};

type StampPresetOverrides = Partial<Omit<StampTemplate, 'frame' | 'icon'>> & {
  frame?: Partial<Box>;
  country?: Partial<TextBox>;
  icon?: Partial<Box>;
  place?: Partial<TextBox>;
  date?: Partial<TextBox>;
  airport?: Partial<TextBox>;
};

export type StampTemplateBundle = {
  default: StampTemplate;
  presets?: Array<{
    name?: string;
    charRange: [number, number];
    overrides: StampPresetOverrides;
  }>;
};

const templateBundles = stampTemplateBundles as unknown as Record<StampShapeKey, StampTemplateBundle>;

export function mergeBox<T extends Record<string, any>>(base: T, override?: Partial<T>): T {
  if (!override) return base;
  return { ...base, ...override };
}

function resolveTemplate(shape: StampShapeKey, length: number): StampTemplate {
  const bundle = templateBundles[shape];
  const preset = bundle.presets?.find((p) => length >= p.charRange[0] && length <= p.charRange[1]);
  if (!preset) return bundle.default;
  const o = preset.overrides;
  return {
    ...bundle.default,
    ...o,
    frame: mergeBox(bundle.default.frame, o.frame),
    country: mergeBox(bundle.default.country, o.country),
    icon: mergeBox(bundle.default.icon, o.icon),
    place: mergeBox(bundle.default.place, o.place),
    date: mergeBox(bundle.default.date, o.date),
    airport: mergeBox(bundle.default.airport, o.airport),
  };
}


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

function getPlaceLine(city?: string) {
  return city;
}

function boxesOverlap(a: Box, b: Box) {
  return !(
    a.left + a.width <= b.left ||
    b.left + b.width <= a.left ||
    a.top + a.height <= b.top ||
    b.top + b.height <= a.top
  );
}

function resolveAirportBox(template: StampTemplate): TextBox {
  if (!boxesOverlap(template.date, template.airport)) return template.airport;

  const gap = 0.012;
  const top = Math.min(0.985 - template.airport.height, template.date.top + template.date.height + gap);
  return { ...template.airport, top };
}

function fitToLimit(value: string | undefined, maxChars: number) {
  if (!value) return undefined;
  const normalized = value.replace(/\s+/g, ' ').trim();
  if (normalized.length <= maxChars) return normalized;
  if (normalized.includes(' ')) return normalized;
  return normalized.slice(0, maxChars);
}

function lengthBoost(len: number) {
  if (len <= 4) return 1.18;
  if (len <= 6) return 1.08;
  if (len <= 9) return 1.0;
  if (len <= 12) return 0.92;
  if (len <= 15) return 0.84;
  return 0.76;
}

function fitFontSize(text: string, baseSize: number, boxWidth: number, boxHeight: number, options?: TextBox, rootWidth: number = 204.75) {
  const charFactor = options?.charFactor ?? 0.62;
  const minScale = options?.minScale ?? 0.5;
  const tracking = (options?.tracking ?? 0) * (rootWidth / 204.75);
  const adaptive = options?.adaptiveLength === false ? 1 : lengthBoost(text.length);
  const adjusted = baseSize * adaptive;
  const estimatedWidth = Math.max(1, text.length * adjusted * charFactor + Math.max(0, text.length - 1) * tracking);
  const widthScale = Math.min(1, boxWidth / estimatedWidth);
  const heightScale = Math.min(1, (boxHeight * 0.88) / adjusted);
  return adjusted * Math.max(minScale, Math.min(widthScale, heightScale));
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
  const fontSize = fitFontSize(text, baseSize * (box.fontScale ?? 1), boxWidth, boxHeight, box, rootWidth);

  return (
    <Text
      allowFontScaling={false}
      numberOfLines={1}
      style={[
        styles.text,
        {
          color,
          fontFamily: mono ? fonts.mono : fonts.sansBold,
          fontSize,
          lineHeight: boxHeight,
          letterSpacing: (box.tracking ?? 0) * (rootWidth / 204.75),
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
  const fontSize = fitFontSize(text, baseSize * (box.fontScale ?? 1), boxWidth, boxHeight * 0.85, box, rootWidth);
  const isCircleArc = arcDepth >= 1.8;
  const rawYStart = boxHeight * (isCircleArc ? 0.96 : Math.min(0.88, 0.6 + arcDepth * 0.15));
  const rawYMid = boxHeight * (isCircleArc ? -0.18 : Math.max(0.06, 0.52 - arcDepth * 0.34));

  // Prevent clipping by expanding the SVG bounding box if the arc exceeds boxHeight
  const topOverflow = Math.max(0, -(rawYMid - fontSize * 1.5));
  const bottomOverflow = Math.max(0, (rawYStart + fontSize * 1.5) - boxHeight);
  const svgHeight = boxHeight + topOverflow + bottomOverflow;

  const yStart = rawYStart + topOverflow;
  const yMid = rawYMid + topOverflow;

  const xInset = isCircleArc ? -0.06 : arcDepth >= 1.2 ? 0.04 : 0.08;
  const startX = boxWidth * xInset;
  const endX = boxWidth * (1 - xInset);
  const cp1X = boxWidth * 0.25;
  const cp2X = boxWidth * 0.75;
  const cpY = yMid - (yStart - yMid) * 0.4;
  const path = `M ${startX} ${yStart} C ${cp1X} ${cpY}, ${cp2X} ${cpY}, ${endX} ${yStart}`;
  const textLength = boxWidth * (arcTextLength ?? 0.7);

  return (
    <Svg
      pointerEvents="none"
      width={boxWidth}
      height={svgHeight}
      style={[
        styles.svgText,
        {
          left: rootWidth * box.left,
          top: rootHeight * box.top - topOverflow,
          overflow: 'visible',
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
        letterSpacing={(box.tracking ?? 0) * (rootWidth / 204.75)}
        lengthAdjust="spacingAndGlyphs"
        textAnchor="middle"
        textLength={textLength}
        dy={fontSize * 0.32}
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
  arcCenterYOffset,
}: {
  text?: string;
  box: TextBox;
  frame: Box;
  rootWidth: number;
  rootHeight: number;
  baseSize: number;
  color: string;
  arcCenterYOffset?: number;
}) {
  if (!text) return null;
  const frameLeft = rootWidth * frame.left;
  const frameTop = rootHeight * frame.top;
  const frameWidth = rootWidth * frame.width;
  const frameHeight = rootHeight * frame.height;
  const ringSize = Math.min(frameWidth, frameHeight);
  const centerX = frameLeft + frameWidth / 2;
  const centerY = frameTop + frameHeight / 2 + frameHeight * (arcCenterYOffset ?? -0.02);
  const radius = ringSize * 0.32;
  const maxArcWidth = radius * 2.35;
  const chars = text.split('');
  const minHalfAngle = chars.length >= 10 ? 53 : chars.length >= 8 ? 44 : chars.length >= 7 ? 36 : 0;
  const maxHalfAngle = chars.length >= 14 ? 78 : chars.length >= 10 ? 70 : chars.length >= 8 ? 60 : 48;
  let fontSize = fitFontSize(text, baseSize * (box.fontScale ?? 1), maxArcWidth, rootHeight * box.height * 0.7, box, rootWidth);
  if (chars.length > 1) {
    const arcLengthAtMaxAngle = ((maxHalfAngle * 2) * Math.PI) / 180 * radius;
    const requiredArcLength = (chars.length - 1) * fontSize * 0.78;
    if (requiredArcLength > arcLengthAtMaxAngle) {
      const minFontFloor = baseSize * (box.minScale ?? 0.36) * 0.85;
      fontSize = Math.max(minFontFloor, (arcLengthAtMaxAngle / (chars.length - 1)) / 0.78);
    }
  }
  const charBoxWidth = Math.max(fontSize * 1.5, 8);
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
        const x = centerX + Math.sin(angle) * radius - charBoxWidth / 2;
        const y = centerY - Math.cos(angle) * radius - fontSize * 1.06;

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
                width: charBoxWidth,
                left: x,
                top: y,
                transform: [{ rotate: `${angleDeg * 0.92}deg` }, { translateY: -fontSize * 0.26 }],
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
  size = 'md',
  variant = 'collection',
  faded = false,
  rotate = 0,
  scale = 1,
  templateOverride,
}: PngStampProps) {
  const config = sizeConfig[size];
  const upperCountry = country.toUpperCase();
  const template = templateOverride || resolveTemplate(shape, upperCountry.length);
  const width = config.width * scale;
  const height = config.height * scale;
  const countryLabel = fitToLimit(upperCountry, template.maxCountryChars) ?? upperCountry.slice(0, template.maxCountryChars);
  const placeLine = fitToLimit(getPlaceLine(city)?.toUpperCase(), template.maxPlaceChars);
  const stampDate = formatStampDate(date);
  const airportBox = resolveAirportBox(template);
  const iconSource = resolveIcon(icon);
  const shapeSource = shapeAssets[shapeAssetKeyMap[shape]];
  const textColor = faded ? colors.mutedInk : color;
  const inkOpacity = faded ? 0.36 : 0.92;
  const titleShouldArc =
    (template.titleMode === 'arc' || template.titleMode === 'circleArc') &&
    (!template.straightTitleMaxChars || countryLabel.length > template.straightTitleMaxChars);
  const iconWidth = width * template.icon.width;
  const iconHeight = height * template.icon.height;
  const iconLeft = width * template.icon.left;
  const iconTop = height * template.icon.top;

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
          arcCenterYOffset={template.arcCenterYOffset}
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
        text={airportCode?.toUpperCase()}
        box={airportBox}
        rootWidth={width}
        rootHeight={height}
        baseSize={config.airport * scale}
        color={textColor}
        mono
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
    textAlignVertical: 'center',
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
