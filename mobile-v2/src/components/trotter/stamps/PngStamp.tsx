import React from 'react';
import { Image, ImageSourcePropType, StyleSheet, View } from 'react-native';
import Svg, { Defs, Path, Text as SvgText, TextPath } from 'react-native-svg';
import {
  CountryIconAssetKey,
  StampShapeAssetKey,
  countryIconAssets,
  stampShapeAssets,
} from '../../../assets/generated/stampAssetManifest';
import { colors, fonts } from '../../../theme/trotterTheme';
import stampTemplateBundles from './stampTemplates.json';
import { fitFontSize } from './stampLayout';
import { resolveStampGeometry } from './stampGeometry';

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
  /** Retained for trip-data compatibility; city text is never printed on an arrival stamp. */
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
  coordinateSpace?: 'frame' | 'canvas';
  circleTitleRadius?: number;
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
    <Svg pointerEvents="none" width={rootWidth} height={rootHeight} viewBox={`0 0 ${rootWidth} ${rootHeight}`} style={styles.svgText}>
      <SvgText fill={color} fontFamily={mono ? fonts.mono : fonts.sansBold} fontSize={fontSize}
        fontWeight={mono ? '400' : '700'} textAnchor="middle" alignmentBaseline="central"
        x={rootWidth * (box.left + box.width / 2)} y={rootHeight * (box.top + box.height / 2)}
        letterSpacing={(box.tracking ?? 0) * rootWidth / 204.75}>
        {text}
      </SvgText>
    </Svg>
  );
}

function ArcStampText({
  text, box, rootWidth, rootHeight, baseSize, color, arcDepth = 0.7,
}: {
  text?: string; box: TextBox; rootWidth: number; rootHeight: number;
  baseSize: number; color: string; arcDepth?: number; arcTextLength?: number;
}) {
  const pathId = `stamp-${React.useId().replace(/[^a-zA-Z0-9_-]/g, '')}`;
  if (!text) return null;
  const w = rootWidth * box.width;
  const h = rootHeight * box.height;
  const fontSize = fitFontSize(text, baseSize * (box.fontScale ?? 1), w * 0.84, h * 0.85, box, rootWidth);
  const left = rootWidth * box.left;
  const top = rootHeight * box.top;
  const depth = Math.max(0.2, Math.min(1.5, arcDepth));
  const startY = top + h * Math.min(0.88, 0.6 + depth * 0.15);
  const middleY = top + h * Math.max(0.06, 0.52 - depth * 0.34);
  const controlY = middleY - (startY - middleY) * 0.4;
  const d = `M ${left + w * .08} ${startY} C ${left + w * .25} ${controlY}, ${left + w * .75} ${controlY}, ${left + w * .92} ${startY}`;
  return (
    <Svg pointerEvents="none" width={rootWidth} height={rootHeight} viewBox={`0 0 ${rootWidth} ${rootHeight}`} style={styles.svgText}>
      <Defs><Path id={pathId} d={d} /></Defs>
      <SvgText fill={color} fontFamily={fonts.sansBold} fontSize={fontSize} fontWeight="700" textAnchor="middle" letterSpacing={(box.tracking ?? 0) * rootWidth / 204.75}>
        <TextPath href={`#${pathId}`} startOffset="50%">{text}</TextPath>
      </SvgText>
    </Svg>
  );
}

function CircleArcStampText({
  text, box, frame, rootWidth, rootHeight, baseSize, color, arcCenterYOffset, radiusRatio = .28,
}: {
  text?: string; box: TextBox; frame: Box; rootWidth: number; rootHeight: number;
  baseSize: number; color: string; arcCenterYOffset?: number; radiusRatio?: number;
}) {
  const pathId = `stamp-circle-${React.useId().replace(/[^a-zA-Z0-9_-]/g, '')}`;
  if (!text) return null;
  const frameWidth = rootWidth * frame.width;
  const frameHeight = rootHeight * frame.height;
  const centerX = rootWidth * frame.left + frameWidth / 2;
  const centerY = rootHeight * frame.top + frameHeight * (0.5 + (arcCenterYOffset ?? -0.02));
  const radius = Math.min(frameWidth, frameHeight) * radiusRatio;
  const halfAngle = 70 * Math.PI / 180;
  const fontSize = fitFontSize(text, baseSize * (box.fontScale ?? 1), radius * halfAngle * 1.8, rootHeight * box.height * .7, box, rootWidth);
  const x = Math.sin(halfAngle) * radius;
  const y = centerY - Math.cos(halfAngle) * radius;
  const d = `M ${centerX - x} ${y} A ${radius} ${radius} 0 0 1 ${centerX + x} ${y}`;
  return (
    <Svg pointerEvents="none" width={rootWidth} height={rootHeight} viewBox={`0 0 ${rootWidth} ${rootHeight}`} style={styles.svgText}>
      <Defs><Path id={pathId} d={d} /></Defs>
      <SvgText fill={color} fontFamily={fonts.sansBold} fontSize={fontSize} fontWeight="700" textAnchor="middle" letterSpacing={(box.tracking ?? 0) * rootWidth / 204.75}>
        <TextPath href={`#${pathId}`} startOffset="50%">{text}</TextPath>
      </SvgText>
    </Svg>
  );
}

export function PngStamp({
  shape,
  icon,
  color,
  country,
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
  const upperCountry = country.replace(/\s+/g, ' ').trim().toUpperCase();
  const width = config.width * scale;
  const height = config.height * scale;
  const template = resolveStampGeometry(shape, templateOverride || resolveTemplate(shape, upperCountry.length), width, height);
  const countryLabel = upperCountry;
  const stampDate = formatStampDate(date);
  const airportBox = template.airport;
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
          radiusRatio={template.circleTitleRadius}
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
    overflow: 'visible',
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
    left: 0,
    top: 0,
    overflow: 'visible',
  },
});
