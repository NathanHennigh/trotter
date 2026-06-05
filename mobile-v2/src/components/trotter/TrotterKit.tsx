import React from 'react';
import {
  ImageBackground,
  Image,
  Platform,
  Pressable,
  StyleProp,
  StyleSheet,
  Text,
  useWindowDimensions,
  View,
  ViewStyle,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { BottomNavTab, LandmarkKey, StampData, StampType, TripSummary } from '../../data/trotterMock';
import { accentColors, colors, fonts, layout, radii, shadows, spacing } from '../../theme/trotterTheme';
import { PngStamp } from './stamps/PngStamp';

const paperTexture = require('../../../assets/textures/paper_texture_clean.png');
const darkTexture = require('../../../assets/textures/dark_dashboard_texture.png');

type SurfaceProps = {
  children: React.ReactNode;
  radius?: number;
  padding?: number;
  style?: StyleProp<ViewStyle>;
  bordered?: boolean;
  texture?: boolean;
};

export function PaperSurface({ children, radius = radii.md, padding = spacing.lg, style, bordered = true, texture = true }: SurfaceProps) {
  const content = (
    <View style={[styles.paperSurface, shadows.paper, { borderRadius: radius, padding }, bordered && styles.paperBorder, style]}>
      {children}
    </View>
  );

  if (!texture) return content;
  return (
    <ImageBackground source={paperTexture} imageStyle={{ borderRadius: radius, opacity: 0.18 }} style={styles.surfaceBackground}>
      {content}
    </ImageBackground>
  );
}

export function DarkPanel({ children, radius = radii.md, padding = spacing.lg, style, bordered = true, texture = true }: SurfaceProps) {
  const content = (
    <View style={[styles.darkPanel, shadows.darkPanel, { borderRadius: radius, padding }, bordered && styles.darkBorder, style]}>
      {children}
    </View>
  );

  if (!texture) return content;
  return (
    <ImageBackground source={darkTexture} imageStyle={{ borderRadius: radius, opacity: 0.2 }} style={styles.surfaceBackground}>
      {content}
    </ImageBackground>
  );
}

export function IconGlyph({ name, color = colors.creamText, size = 24 }: { name: string; color?: string; size?: number }) {
  const stroke = Math.max(1.6, Math.round(size / 13));
  if (name === 'plane') {
    return (
      <View style={[iconStyles.box, { width: size, height: size }]}>
        <View style={[iconStyles.planeBody, { backgroundColor: color, height: stroke, width: size * 0.84 }]} />
        <View style={[iconStyles.planeWingA, { backgroundColor: color, height: stroke, width: size * 0.42 }]} />
        <View style={[iconStyles.planeWingB, { backgroundColor: color, height: stroke, width: size * 0.34 }]} />
      </View>
    );
  }
  if (name === 'globe') {
    return (
      <View style={[iconStyles.circle, { width: size, height: size, borderRadius: size / 2, borderColor: color, borderWidth: stroke }]}>
        <View style={[iconStyles.globeMeridian, { borderColor: color, borderWidth: stroke, width: size * 0.4, borderRadius: size }]} />
        <View style={[iconStyles.globeEquator, { backgroundColor: color, height: stroke }]} />
      </View>
    );
  }
  if (name === 'passport') {
    return <View style={[iconStyles.passport, { width: size * 0.78, height: size, borderColor: color, borderWidth: stroke }]} />;
  }
  if (name === 'sliders') {
    return (
      <View style={[iconStyles.stack, { width: size, height: size }]}>
        {[0, 1, 2].map((i) => (
          <View key={i} style={[iconStyles.sliderTrack, { width: size * 0.78 }]}>
            <View style={[iconStyles.sliderLine, { backgroundColor: color, height: stroke }]} />
            <View style={[iconStyles.sliderKnob, { borderColor: color, width: stroke * 3.5, height: stroke * 3.5, left: i === 1 ? '58%' : '24%' }]} />
          </View>
        ))}
      </View>
    );
  }
  if (name === 'crosshair') {
    return (
      <View style={[iconStyles.circle, { width: size, height: size, borderRadius: size / 2, borderColor: color, borderWidth: stroke }]}>
        <View style={[iconStyles.crossV, { backgroundColor: color, width: stroke }]} />
        <View style={[iconStyles.crossH, { backgroundColor: color, height: stroke }]} />
      </View>
    );
  }
  if (name === 'tag') {
    return <View style={[iconStyles.tag, { width: size, height: size * 0.68, borderColor: color, borderWidth: stroke }]} />;
  }
  if (name === 'suitcase') {
    return (
      <View style={[iconStyles.suitcase, { width: size * 0.82, height: size * 0.68, borderColor: color, borderWidth: stroke }]}>
        <View style={[iconStyles.suitcaseHandle, { borderColor: color, borderWidth: stroke, width: size * 0.34, height: size * 0.18 }]} />
      </View>
    );
  }
  if (name === 'profile') {
    return (
      <View style={[iconStyles.box, { width: size, height: size }]}>
        <View style={[iconStyles.profileHead, { backgroundColor: color, width: size * 0.32, height: size * 0.32, borderRadius: size }]} />
        <View style={[iconStyles.profileBody, { backgroundColor: color, width: size * 0.68, height: size * 0.28, borderTopLeftRadius: size, borderTopRightRadius: size }]} />
      </View>
    );
  }
  if (name === 'plus') {
    return (
      <View style={[iconStyles.box, { width: size, height: size }]}>
        <View style={[iconStyles.crossV, { backgroundColor: color, width: stroke }]} />
        <View style={[iconStyles.crossH, { backgroundColor: color, height: stroke }]} />
      </View>
    );
  }
  return <Text style={{ color, fontFamily: fonts.sansBold, fontSize: size * 0.72 }}>{name.slice(0, 1).toUpperCase()}</Text>;
}

export function IconButton({
  icon,
  variant,
  shape = 'square',
  onPress,
}: {
  icon: React.ReactNode;
  variant: 'paper' | 'dark';
  shape?: 'square' | 'circle';
  onPress?: () => void;
}) {
  return (
    <Pressable
      onPress={onPress}
      style={[
        styles.iconButton,
        shape === 'circle' && styles.circleButton,
        variant === 'paper' ? styles.paperIconButton : styles.darkIconButton,
      ]}
    >
      {icon}
    </Pressable>
  );
}

export function SplitFlapNumber({
  value,
  minDigits = 1,
  scale = 1,
}: {
  value: number | string;
  minDigits?: number;
  scale?: number;
}) {
  const characters = String(value).replace(/,/g, '').padStart(minDigits, '0').split('');
  return (
    <View style={styles.splitRow}>
      {characters.map((char, index) => (
        <View key={`${char}-${index}`} style={[styles.digitTile, { minWidth: 20 * scale, height: 31 * scale }]}>
          <Text allowFontScaling={false} style={[styles.digitText, { fontSize: 21 * scale, lineHeight: 25 * scale }]}>{char}</Text>
          <View style={styles.digitHinge} />
        </View>
      ))}
    </View>
  );
}

export function SplitFlapStatsPanel({
  flights,
  countries,
  airports,
  width,
  compact = false,
}: {
  flights: number;
  countries: number;
  airports: number;
  width?: number;
  compact?: boolean;
}) {
  const stats = [
    { label: 'FLIGHTS', value: flights },
    { label: 'COUNTRIES', value: countries },
    { label: 'AIRPORTS', value: airports },
  ];
  return (
    <DarkPanel padding={compact ? 6 : spacing.sm} radius={radii.md} style={[styles.statsPanel, width ? { width } : null]}>
      {stats.map((stat, index) => (
        <View key={stat.label} style={[styles.statBlock, index > 0 && styles.statDivider, compact && styles.statBlockCompact]}>
          <Text allowFontScaling={false} numberOfLines={1} adjustsFontSizeToFit style={[styles.darkLabel, compact && styles.darkLabelCompact]}>{stat.label}</Text>
          <SplitFlapNumber value={stat.value} minDigits={stat.label === 'COUNTRIES' ? 2 : 3} scale={compact ? 0.72 : 0.86} />
        </View>
      ))}
    </DarkPanel>
  );
}

export function SyncStatusPill({ lastSyncedLabel, sourceLabel = 'Gmail' }: { lastSyncedLabel: string; sourceLabel?: string }) {
  return (
    <DarkPanel padding={spacing.sm} radius={radii.sm} style={styles.syncPill}>
      <View style={styles.greenDot} />
      <Text numberOfLines={1} style={styles.syncText}>{lastSyncedLabel}</Text>
      <Text style={styles.sourceText}>{sourceLabel}</Text>
    </DarkPanel>
  );
}

export function TrotterHeaderTag({ width, year = new Date().getFullYear() }: { width?: number; year?: number | string }) {
  return (
    <PaperSurface radius={radii.sm} padding={spacing.md} style={[styles.headerTag, width ? { width } : null]}>
      <Text allowFontScaling={false} style={styles.headerYear}>{year}</Text>
      <View style={styles.headerCopy}>
        <Text allowFontScaling={false} numberOfLines={1} adjustsFontSizeToFit style={styles.wordmark}>TROTTER</Text>
        <Text allowFontScaling={false} numberOfLines={1} adjustsFontSizeToFit style={styles.tagline}>YOUR TRAVEL, RECORDED.</Text>
      </View>
      <IconGlyph name="plane" color={colors.ink} size={28} />
    </PaperSurface>
  );
}

export function ScreenHeader({
  title,
  subtitle,
  leftAction,
  rightActions,
}: {
  title: string;
  subtitle?: string;
  leftAction?: React.ReactNode;
  rightActions?: React.ReactNode[];
}) {
  const { width } = useWindowDimensions();
  const screenPadding = width < 390 ? 16 : layout.screenPadding;
  const contentWidth = width - screenPadding * 2;
  const titleFontSize = title.length >= 9 ? 40 : title.length >= 8 ? 44 : 52;
  const titleSpacing = title.length >= 8 ? 3 : 5;

  return (
    <View style={[styles.screenHeader, { paddingHorizontal: screenPadding }]}>
      <View pointerEvents="box-none" style={[styles.headerAction, { left: screenPadding }]}>{leftAction}</View>
      <View style={[styles.headerTitleWrap, { width: contentWidth }]}>
        <Text
          allowFontScaling={false}
          maxFontSizeMultiplier={1}
          numberOfLines={1}
          adjustsFontSizeToFit
          minimumFontScale={0.78}
          style={[styles.screenTitle, { fontSize: titleFontSize, letterSpacing: titleSpacing }]}
        >
          {title}
        </Text>
        {subtitle ? (
          <Text maxFontSizeMultiplier={1.1} numberOfLines={1} adjustsFontSizeToFit style={styles.screenSubtitle}>
            {subtitle}
          </Text>
        ) : null}
      </View>
      <View pointerEvents="box-none" style={[styles.headerRight, { right: screenPadding }]}>{rightActions?.map((action, index) => <View key={index}>{action}</View>)}</View>
    </View>
  );
}

export function SegmentedFilterTabs({
  tabs,
  activeKey,
  onChange,
}: {
  tabs: { key: string; label: string; count?: number }[];
  activeKey: string;
  onChange: (key: string) => void;
}) {
  const { width } = useWindowDimensions();
  const screenPadding = width < 390 ? 16 : layout.screenPadding;

  return (
    <View style={[styles.tabs, { marginHorizontal: screenPadding }]}>
      {tabs.map((tab) => {
        const active = tab.key === activeKey;
        return (
          <Pressable key={tab.key} onPress={() => onChange(tab.key)} style={[styles.tab, active && styles.tabActive]}>
            <Text maxFontSizeMultiplier={1.05} numberOfLines={1} adjustsFontSizeToFit style={[styles.tabText, active && styles.tabTextActive]}>{tab.label}{typeof tab.count === 'number' ? ` ${tab.count}` : ''}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}

export function Stamp({
  type,
  color,
  title,
  subtitle,
  date,
  footer,
  landmark,
  faded,
  size = 'md',
  }: StampData & { faded?: boolean; size?: 'sm' | 'md' | 'lg' }) {
    const dims = size === 'sm' ? { w: 74, h: 56, icon: 20 } : size === 'lg' ? { w: 154, h: 112, icon: 38 } : { w: 108, h: 82, icon: 27 };
    const frameStyle = getStampFrameStyle(type, color, faded);
    const visibleFooter = footer?.toUpperCase() === 'FIRST VISIT' ? undefined : footer;
    return (
      <View style={[styles.stamp, { width: dims.w, height: dims.h, opacity: faded ? 0.42 : 0.92 }, frameStyle]}>
      <LandmarkIcon landmark={landmark} color={color} size={dims.icon} />
      <Text allowFontScaling={false} numberOfLines={1} adjustsFontSizeToFit style={[styles.stampTitle, size === 'sm' && styles.stampTitleSmall, { color }]}>{title}</Text>
      {subtitle ? <Text numberOfLines={1} adjustsFontSizeToFit style={[styles.stampSub, { color }]}>{subtitle}</Text> : null}
      {date ? <Text numberOfLines={1} adjustsFontSizeToFit style={[styles.stampDate, { color }]}>{date}</Text> : null}
        {visibleFooter ? <Text numberOfLines={1} adjustsFontSizeToFit style={[styles.stampFooter, { color }]}>{visibleFooter}</Text> : null}
      </View>
    );
  }

function getStampFrameStyle(type: StampType, color: string, faded?: boolean): ViewStyle {
  const base: ViewStyle = {
    borderColor: faded ? colors.mutedInk : color,
    borderWidth: 2,
    borderRadius: type === 'circle' ? 999 : type === 'shield' ? 18 : 8,
  };
  if (type === 'rounded-immigration') return { ...base, borderRadius: 14, borderStyle: 'dashed' };
  if (type === 'horizontal-airport') return { ...base, borderRadius: 6, height: 64 };
  if (type === 'arched') return { ...base, borderTopLeftRadius: 38, borderTopRightRadius: 38 };
  return base;
}

function LandmarkIcon({ landmark, color, size }: { landmark?: LandmarkKey; color: string; size: number }) {
  if (landmark === 'eiffelTower' || landmark === 'bigBen' || landmark === 'sagradaFamilia') {
    return (
      <View style={[landmarkStyles.box, { width: size, height: size }]}>
        <View style={[landmarkStyles.tower, { backgroundColor: color }]} />
        <View style={[landmarkStyles.towerBase, { backgroundColor: color }]} />
      </View>
    );
  }
  if (landmark === 'chichenItza' || landmark === 'colosseum' || landmark === 'brandenburgGate' || landmark === 'parthenon') {
    return (
      <View style={[landmarkStyles.box, { width: size, height: size }]}>
        <View style={[landmarkStyles.steps, { borderBottomColor: color }]} />
        <View style={[landmarkStyles.stepsSmall, { borderBottomColor: color }]} />
      </View>
    );
  }
  return (
    <View style={[landmarkStyles.box, { width: size, height: size }]}>
      <View style={[landmarkStyles.mountainA, { borderBottomColor: color }]} />
      <View style={[landmarkStyles.mountainB, { borderBottomColor: color }]} />
    </View>
  );
}

export function TripCard({
  trip,
  compact = false,
  width,
  height,
}: {
  trip: TripSummary;
  compact?: boolean;
  width?: number;
  height?: number;
}) {
  const accent = accentColors[trip.accent];
  return (
    <PaperSurface radius={radii.sm} padding={0} style={[styles.tripCard, compact && styles.tripCardCompact, width ? { width } : null, height ? { height, minHeight: height } : null]}>
      <View style={[styles.tripStrip, { backgroundColor: accent }]}>
        <View style={styles.tripHole} />
      </View>
      <View style={styles.tripDateColumn}>
        <Text numberOfLines={1} adjustsFontSizeToFit style={styles.tripDate}>{formatShortRange(trip.startDate, trip.endDate)}</Text>
      </View>
      <View style={styles.tripBody}>
        <View style={styles.tripTitleRow}>
          <Text maxFontSizeMultiplier={1.05} numberOfLines={1} adjustsFontSizeToFit style={[styles.tripTitle, compact && styles.tripTitleCompact]}>{trip.title}</Text>
          <Text style={styles.countryCode}>{trip.countryCode}</Text>
        </View>
        <View style={styles.routeRow}>
          <Text style={[styles.routeText, { color: accent }]}>{trip.routeLabel}</Text>
          <IconGlyph name="plane" color={accent} size={20} />
        </View>
        <Text maxFontSizeMultiplier={1.05} numberOfLines={1} adjustsFontSizeToFit style={styles.tripMeta}>{trip.miles.toLocaleString()} mi  -  {trip.flightCount} flights  -  {trip.airlineCount} airlines</Text>
      </View>
      {!compact && trip.stamp ? (
        <View style={styles.cardStamp}>
          <PngStamp {...trip.stamp} size="sm" variant="trip-card" rotate={-7} />
        </View>
      ) : null}
      <DestinationThumbnail trip={trip} compact={compact} />
    </PaperSurface>
  );
}

function DestinationThumbnail({ trip, compact }: { trip: TripSummary; compact: boolean }) {
  const source = trip.destinationImage;
  return (
    <View style={[styles.photoThumb, compact && styles.photoThumbCompact, { backgroundColor: getPhotoTone(trip.id) }]}>
      {source ? <Image source={source} style={StyleSheet.absoluteFillObject} resizeMode="cover" /> : <View style={styles.photoSkyline} />}
      <Text style={styles.photoLabel}>{trip.countryCode}</Text>
    </View>
  );
}

function getPhotoTone(id: string) {
  if (id.includes('tokyo')) return '#748B95';
  if (id.includes('paris')) return '#9CA9A7';
  if (id.includes('denver')) return '#B89C71';
  if (id.includes('cancun')) return '#79AAA9';
  if (id.includes('barcelona')) return '#A87E66';
  return '#8EA1A4';
}

export function RecentTripsSheet({ trips, onViewAll }: { trips: TripSummary[]; onViewAll: () => void }) {
  return (
    <PaperSurface radius={28} padding={spacing.md} style={styles.recentSheet}>
      <View style={styles.handle} />
      <View style={styles.sheetHeader}>
        <IconGlyph name="plane" color={colors.ink} size={22} />
        <Text style={styles.sheetTitle}>RECENT TRIPS</Text>
        <Pressable onPress={onViewAll}><Text style={styles.viewAll}>VIEW ALL</Text></Pressable>
      </View>
      {trips.slice(0, 3).map((trip) => <TripCard key={trip.id} trip={trip} compact />)}
    </PaperSurface>
  );
}

export function NewFlightsBanner({
  count,
  sourceLabel,
  onReview,
  eyebrow = 'NEW FLIGHTS FOUND',
  title,
  actionLabel = 'REVIEW',
}: {
  count: number;
  sourceLabel: string;
  onReview: () => void;
  eyebrow?: string;
  title?: string;
  actionLabel?: string;
}) {
  return (
    <PaperSurface radius={radii.md} padding={spacing.sm} style={styles.newFlights}>
      <View style={styles.terminal}>
        <Text style={styles.terminalTiny}>{eyebrow}</Text>
        <Text style={styles.terminalCount}>{count}</Text>
      </View>
      <View style={styles.newCopy}>
        <Text style={styles.newTitle}>{title ?? `${count} new flights added`}</Text>
        <Text style={styles.newSub}>from {sourceLabel}</Text>
      </View>
      <Pressable onPress={onReview} style={styles.reviewButton}><Text style={styles.reviewText}>{actionLabel}</Text></Pressable>
    </PaperSurface>
  );
}

export function PassportViewButton() {
  return (
    <PaperSurface radius={999} padding={0} style={styles.passportButton}>
      <View style={styles.passportInner}>
        <IconGlyph name="globe" color={colors.red} size={28} />
        <Text style={styles.passportButtonText}>PASSPORT{'\n'}VIEW</Text>
      </View>
    </PaperSurface>
  );
}

export function BottomNav({ active, onChange }: { active: BottomNavTab; onChange: (tab: BottomNavTab) => void }) {
  const insets = useSafeAreaInsets();
  const { width } = useWindowDimensions();
  const tabs: { key: BottomNavTab; label: string; icon: string }[] = [
    { key: 'globe', label: 'Globe', icon: 'globe' },
    { key: 'trips', label: 'Trips', icon: 'suitcase' },
    { key: 'passport', label: 'Passport', icon: 'passport' },
    { key: 'dreams', label: 'Dreams', icon: 'tag' },
    { key: 'profile', label: 'Profile', icon: 'profile' },
  ];
  const navWidth = Platform.OS === 'web' ? Math.min(width, 393) : width;
  const tabWidth = navWidth / tabs.length;
  const webViewportNav =
    Platform.OS === 'web'
      ? ({
          left: 0,
          right: 0,
        } as unknown as ViewStyle)
      : null;

  return (
    <View style={[styles.bottomNav, webViewportNav, { width: navWidth, paddingBottom: insets.bottom + 8 }]}>
      {tabs.map((tab) => {
        const isActive = tab.key === active;
        const tint = isActive ? colors.brassSoft : colors.subtleText;
        return (
          <Pressable key={tab.key} style={[styles.navItem, { width: tabWidth, maxWidth: tabWidth }, isActive && styles.navItemActive]} onPress={() => onChange(tab.key)}>
            <IconGlyph name={tab.icon} color={tint} size={22} />
      <Text allowFontScaling={false} numberOfLines={1} style={[styles.navText, { color: tint }]}>{tab.label}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}

export function formatShortRange(start: string, end: string) {
  const startDate = new Date(`${start}T00:00:00`);
  const endDate = new Date(`${end}T00:00:00`);
  const month = startDate.toLocaleString('en-US', { month: 'short' }).toUpperCase();
  return `${month} ${startDate.getDate()}-${endDate.getDate()}`;
}

const styles = StyleSheet.create({
  surfaceBackground: {
    overflow: 'hidden',
    flexShrink: 0,
  },
  paperSurface: {
    backgroundColor: colors.paper,
  },
  paperBorder: {
    borderWidth: 1,
    borderColor: colors.paperBorder,
  },
  darkPanel: {
    backgroundColor: colors.dashboard,
  },
  darkBorder: {
    borderWidth: 1,
    borderColor: colors.darkBorder,
  },
  iconButton: {
    width: 50,
    height: 50,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 1,
  },
  circleButton: {
    borderRadius: 999,
  },
  paperIconButton: {
    backgroundColor: colors.paper,
    borderColor: colors.paperBorder,
  },
  darkIconButton: {
    backgroundColor: colors.dashboard,
    borderColor: colors.darkBorder,
  },
  splitRow: {
    flexDirection: 'row',
    gap: 2,
    flexShrink: 1,
  },
  digitTile: {
    minWidth: 20,
    height: 31,
    borderRadius: 4,
    backgroundColor: '#090A08',
    borderWidth: 1,
    borderColor: '#2F281C',
    alignItems: 'center',
    justifyContent: 'center',
  },
  digitText: {
    color: colors.brassSoft,
    fontFamily: fonts.mono,
    fontSize: 21,
    lineHeight: 25,
  },
  digitHinge: {
    position: 'absolute',
    left: 0,
    right: 0,
    top: '51%',
    height: 1,
    backgroundColor: '#342B1E',
  },
  statsPanel: {
    flexDirection: 'row',
    flexShrink: 1,
    overflow: 'hidden',
  },
  statBlock: {
    flex: 1,
    minWidth: 0,
    alignItems: 'center',
    paddingHorizontal: 4,
  },
  statBlockCompact: {
    paddingHorizontal: 2,
  },
  statDivider: {
    borderLeftWidth: 1,
    borderLeftColor: '#382D20',
  },
  darkLabel: {
    color: colors.subtleText,
    fontFamily: fonts.sansBold,
    fontSize: 9,
    marginBottom: 5,
  },
  darkLabelCompact: {
    fontSize: 8,
    marginBottom: 4,
  },
  syncPill: {
    marginTop: 6,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 7,
    width: '100%',
    minWidth: 0,
  },
  greenDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: '#72B46C',
  },
  syncText: {
    flex: 1,
    color: colors.creamText,
    fontFamily: fonts.sansRegular,
    fontSize: 12,
  },
  sourceText: {
    color: colors.creamText,
    fontFamily: fonts.sansBold,
    fontSize: 12,
  },
  headerTag: {
    minHeight: 78,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    transform: [{ rotate: '-2deg' }],
  },
  headerYear: {
    color: colors.ink,
    fontFamily: fonts.sansBold,
    fontSize: 11,
    transform: [{ rotate: '-90deg' }],
    marginLeft: -13,
  },
  headerCopy: {
    flex: 1,
    minWidth: 0,
  },
  wordmark: {
    color: colors.ink,
    fontFamily: fonts.display,
    fontSize: 29,
    letterSpacing: 5,
  },
  tagline: {
    color: colors.red,
    fontFamily: fonts.sansBold,
    fontSize: 10,
    marginTop: 2,
  },
  screenHeader: {
    position: 'relative',
    minHeight: 106,
    justifyContent: 'center',
    paddingTop: spacing.sm,
    paddingBottom: spacing.md,
  },
  headerAction: {
    position: 'absolute',
    top: 22,
    zIndex: 3,
    width: 54,
    alignItems: 'flex-start',
  },
  headerTitleWrap: {
    alignSelf: 'center',
    alignItems: 'center',
    minWidth: 0,
    paddingHorizontal: 4,
  },
  screenTitle: {
    color: colors.ink,
    fontFamily: fonts.display,
    includeFontPadding: false,
    textAlign: 'center',
  },
  screenSubtitle: {
    color: colors.red,
    fontFamily: fonts.sansBold,
    fontSize: 11,
    marginTop: -4,
  },
  headerRight: {
    position: 'absolute',
    top: 22,
    zIndex: 3,
    minWidth: 54,
    flexDirection: 'row',
    justifyContent: 'flex-end',
    gap: 8,
  },
  tabs: {
    flexDirection: 'row',
    borderRadius: radii.sm,
    borderWidth: 1,
    borderColor: colors.paperBorder,
    backgroundColor: colors.paperDeep,
    padding: 3,
  },
  tab: {
    flex: 1,
    minHeight: 34,
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: radii.xs,
  },
  tabActive: {
    backgroundColor: colors.dashboard,
  },
  tabText: {
    color: colors.mutedInk,
    fontFamily: fonts.sansBold,
    fontSize: 11,
  },
  tabTextActive: {
    color: colors.creamText,
  },
  stamp: {
    alignItems: 'center',
    justifyContent: 'center',
    padding: 6,
    overflow: 'hidden',
  },
  stampTitle: {
    fontFamily: fonts.sansBold,
    fontSize: 12,
    letterSpacing: 1.4,
    maxWidth: '92%',
  },
  stampTitleSmall: {
    fontSize: 10,
    letterSpacing: 0.8,
  },
  stampSub: {
    fontFamily: fonts.sansBold,
    fontSize: 8,
    maxWidth: '92%',
  },
  stampDate: {
    fontFamily: fonts.mono,
    fontSize: 8,
    marginTop: 2,
  },
  stampFooter: {
    fontFamily: fonts.sansBold,
    fontSize: 7,
  },
  tripCard: {
    minHeight: 148,
    flexDirection: 'row',
    alignItems: 'center',
    overflow: 'hidden',
    marginBottom: spacing.md,
  },
  tripCardCompact: {
    minHeight: 106,
  },
  tripStrip: {
    width: 30,
    alignSelf: 'stretch',
    alignItems: 'center',
    justifyContent: 'center',
  },
  tripHole: {
    width: 15,
    height: 15,
    borderRadius: 8,
    backgroundColor: colors.paper,
    borderWidth: 1,
    borderColor: colors.paperBorder,
  },
  tripDateColumn: {
    width: 30,
    alignItems: 'center',
    justifyContent: 'center',
    alignSelf: 'stretch',
    borderRightWidth: 1,
    borderRightColor: colors.divider,
    marginRight: 8,
  },
  tripDate: {
    width: 92,
    color: colors.mutedInk,
    fontFamily: fonts.sansBold,
    fontSize: 10,
    transform: [{ rotate: '-90deg' }],
    textAlign: 'center',
  },
  tripBody: {
    flex: 1,
    minWidth: 0,
    paddingVertical: spacing.md,
    paddingRight: spacing.xs,
  },
  tripTitleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 7,
  },
  tripTitle: {
    flex: 1,
    color: colors.ink,
    fontFamily: fonts.display,
    fontSize: 26,
    letterSpacing: 0.2,
  },
  tripTitleCompact: {
    fontSize: 24,
  },
  countryCode: {
    color: colors.mutedInk,
    fontFamily: fonts.mono,
    fontSize: 11,
  },
  routeRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    marginTop: 10,
  },
  routeText: {
    fontFamily: fonts.sansBold,
    fontSize: 16,
  },
  tripMeta: {
    color: colors.mutedInk,
    fontFamily: fonts.sansRegular,
    fontSize: 12,
    marginTop: 9,
  },
  cardStamp: {
    width: 56,
    marginRight: -2,
    transform: [{ rotate: '-7deg' }],
  },
  photoThumb: {
    width: 82,
    height: 76,
    borderWidth: 3,
    borderColor: colors.paperSoft,
    marginRight: 8,
    alignItems: 'center',
    justifyContent: 'flex-end',
    overflow: 'hidden',
    transform: [{ rotate: '4deg' }],
  },
  photoThumbCompact: {
    width: 76,
    height: 64,
    marginRight: 8,
  },
  photoSkyline: {
    position: 'absolute',
    left: 8,
    right: 8,
    bottom: 18,
    height: 16,
    borderTopWidth: 2,
    borderColor: 'rgba(255,255,255,0.55)',
  },
  photoLabel: {
    color: 'rgba(255,255,255,0.78)',
    fontFamily: fonts.sansBold,
    fontSize: 10,
    marginBottom: 5,
  },
  recentSheet: {
    borderTopLeftRadius: 28,
    borderTopRightRadius: 28,
  },
  handle: {
    width: 66,
    height: 6,
    borderRadius: 3,
    backgroundColor: '#A99873',
    alignSelf: 'center',
    marginBottom: spacing.md,
  },
  sheetHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 9,
    marginBottom: spacing.sm,
  },
  sheetTitle: {
    flex: 1,
    color: colors.ink,
    fontFamily: fonts.sansBold,
    fontSize: 14,
  },
  viewAll: {
    color: colors.red,
    fontFamily: fonts.sansBold,
    fontSize: 12,
  },
  newFlights: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    minHeight: 78,
  },
  terminal: {
    width: 86,
    height: 55,
    borderRadius: 7,
    backgroundColor: '#0D1C12',
    borderWidth: 2,
    borderColor: colors.dashboard,
    padding: 6,
  },
  terminalTiny: {
    color: '#96D878',
    fontFamily: fonts.mono,
    fontSize: 7,
  },
  terminalCount: {
    color: '#96D878',
    fontFamily: fonts.mono,
    fontSize: 27,
  },
  newCopy: {
    flex: 1,
  },
  newTitle: {
    color: colors.ink,
    fontFamily: fonts.sansSemi,
    fontSize: 15,
  },
  newSub: {
    color: colors.mutedInk,
    fontFamily: fonts.sansRegular,
    fontSize: 12,
  },
  reviewButton: {
    borderRadius: radii.xs,
    borderWidth: 1,
    borderColor: colors.paperBorder,
    paddingHorizontal: 12,
    paddingVertical: 10,
  },
  reviewText: {
    color: colors.ink,
    fontFamily: fonts.sansBold,
    fontSize: 12,
  },
  passportButton: {
    width: 92,
    height: 92,
    borderWidth: 3,
    borderColor: colors.red,
    transform: [{ rotate: '-12deg' }],
  },
  passportInner: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
  passportButtonText: {
    color: colors.red,
    fontFamily: fonts.sansBold,
    fontSize: 11,
    textAlign: 'center',
    marginTop: 4,
  },
  bottomNav: {
    position: 'absolute',
    left: 0,
    right: 0,
    bottom: 0,
    width: '100%',
    minHeight: 88,
    flexDirection: 'row',
    backgroundColor: '#12110E',
    borderTopWidth: 1,
    borderTopColor: colors.darkBorder,
  },
  navItem: {
    flexGrow: 0,
    flexShrink: 0,
    minWidth: 0,
    overflow: 'hidden',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 4,
    borderLeftWidth: 1,
    borderLeftColor: '#302A22',
  },
  navItemActive: {
    backgroundColor: '#1B170E',
  },
  navText: {
    fontFamily: fonts.sansBold,
    fontSize: 10,
  },
});

const iconStyles = StyleSheet.create({
  box: {
    alignItems: 'center',
    justifyContent: 'center',
  },
  planeBody: {
    borderRadius: 2,
    transform: [{ rotate: '-18deg' }],
  },
  planeWingA: {
    position: 'absolute',
    borderRadius: 2,
    transform: [{ rotate: '34deg' }],
  },
  planeWingB: {
    position: 'absolute',
    borderRadius: 2,
    transform: [{ rotate: '-58deg' }],
  },
  circle: {
    alignItems: 'center',
    justifyContent: 'center',
  },
  globeMeridian: {
    position: 'absolute',
    top: 1,
    bottom: 1,
    borderTopWidth: 0,
    borderBottomWidth: 0,
  },
  globeEquator: {
    position: 'absolute',
    left: 3,
    right: 3,
  },
  passport: {
    borderRadius: 4,
  },
  stack: {
    justifyContent: 'space-around',
    alignItems: 'center',
  },
  sliderLine: {
    borderRadius: 2,
    position: 'absolute',
    left: 0,
    right: 0,
    top: '50%',
  },
  sliderTrack: {
    height: 8,
    justifyContent: 'center',
  },
  sliderKnob: {
    position: 'absolute',
    top: 1,
    borderRadius: 999,
    backgroundColor: '#12110E',
  },
  crossV: {
    position: 'absolute',
    top: 3,
    bottom: 3,
  },
  crossH: {
    position: 'absolute',
    left: 3,
    right: 3,
  },
  tag: {
    borderRadius: 5,
    transform: [{ rotate: '-10deg' }],
  },
  suitcase: {
    borderRadius: 4,
    alignItems: 'center',
    justifyContent: 'flex-start',
  },
  suitcaseHandle: {
    position: 'absolute',
    top: -7,
    borderBottomWidth: 0,
    borderTopLeftRadius: 5,
    borderTopRightRadius: 5,
  },
  profileHead: {
    marginBottom: 2,
  },
  profileBody: {},
});

const landmarkStyles = StyleSheet.create({
  box: {
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 1,
  },
  tower: {
    width: 5,
    height: 24,
    borderRadius: 2,
  },
  towerBase: {
    width: 24,
    height: 4,
    borderRadius: 2,
    marginTop: 2,
  },
  steps: {
    width: 0,
    height: 0,
    borderLeftWidth: 18,
    borderRightWidth: 18,
    borderBottomWidth: 22,
    borderLeftColor: 'transparent',
    borderRightColor: 'transparent',
  },
  stepsSmall: {
    position: 'absolute',
    bottom: 4,
    width: 0,
    height: 0,
    borderLeftWidth: 10,
    borderRightWidth: 10,
    borderBottomWidth: 12,
    borderLeftColor: 'transparent',
    borderRightColor: 'transparent',
  },
  mountainA: {
    position: 'absolute',
    bottom: 4,
    left: 3,
    width: 0,
    height: 0,
    borderLeftWidth: 15,
    borderRightWidth: 15,
    borderBottomWidth: 24,
    borderLeftColor: 'transparent',
    borderRightColor: 'transparent',
  },
  mountainB: {
    position: 'absolute',
    bottom: 4,
    right: 2,
    width: 0,
    height: 0,
    borderLeftWidth: 10,
    borderRightWidth: 10,
    borderBottomWidth: 17,
    borderLeftColor: 'transparent',
    borderRightColor: 'transparent',
  },
});
