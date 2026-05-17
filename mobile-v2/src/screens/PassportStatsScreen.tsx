import React from 'react';
import { Pressable, RefreshControl, ScrollView, StyleSheet, Text, useWindowDimensions, View, Image } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import {
  BottomNav,
  DarkPanel,
  IconButton,
  IconGlyph,
  PaperSurface,
  ScreenHeader,
  SplitFlapNumber,
  Stamp,
} from '../components/trotter/TrotterKit';
import { PngStamp, StampShapeKey } from '../components/trotter/stamps/PngStamp';
import { CountryIconAssetKey } from '../assets/generated/stampAssetManifest';
import { BottomNavTab } from '../data/trotterMock';
import { useTravelTrips } from '../services/travelTrips';
import { colors, fonts, layout, spacing } from '../theme/trotterTheme';

const STAMP_TEST_BASE_WIDTH = 204.75;

const japanPreviewStamp = {
  shape: 'archedCountryCanonical' as const,
  icon: 'japan_mount_fuji',
  color: '#B6543F',
  country: 'JAPAN',
  city: 'Tokyo',
  airportCode: 'HND',
  date: '12 MAY 2025',
};

const COUNTRY_ROSTER: Array<{ country: string; icon: CountryIconAssetKey }> = [
  { country: 'United States', icon: 'united_states_golden_gate_bridge' },
  { country: 'Canada', icon: 'canada_rocky_mountains' },
  { country: 'Mexico', icon: 'mexico_chichen_itza' },
  { country: 'Brazil', icon: 'brazil_christ_the_redeemer' },
  { country: 'Argentina', icon: 'argentina_obelisco_de_buenos_aires' },
  { country: 'Chile', icon: 'chile_torres_del_paine' },
  { country: 'Peru', icon: 'peru_machu_picchu' },
  { country: 'Colombia', icon: 'colombia_cartagena_clock_tower' },
  { country: 'Costa Rica', icon: 'costa_rica_arenal_volcano' },
  { country: 'Panama', icon: 'panama_panama_canal' },
  { country: 'Cuba', icon: 'cuba_havana_capitol' },
  { country: 'Jamaica', icon: 'jamaica_dunns_river_falls' },
  { country: 'Dominican Republic', icon: 'dominican_republic_puerta_del_conde' },
  { country: 'Iceland', icon: 'iceland_northern_lights' },
  { country: 'Ireland', icon: 'ireland_cliffs_of_moher' },
  { country: 'United Kingdom', icon: 'united_kingdom_big_ben' },
  { country: 'France', icon: 'france_eiffel_tower' },
  { country: 'Spain', icon: 'spain_sagrada_familia' },
  { country: 'Portugal', icon: 'portugal_belem_tower' },
  { country: 'Italy', icon: 'italy_colosseum' },
  { country: 'Greece', icon: 'greece_parthenon' },
  { country: 'Germany', icon: 'germany_brandenburg_gate' },
  { country: 'Netherlands', icon: 'netherlands_amsterdam_canal_houses' },
  { country: 'Belgium', icon: 'belgium_atomium' },
  { country: 'Switzerland', icon: 'switzerland_matterhorn' },
  { country: 'Austria', icon: 'austria_st_stephens_cathedral' },
  { country: 'Czech Republic', icon: 'czech_republic_charles_bridge_prague_castle' },
  { country: 'Hungary', icon: 'hungary_hungarian_parliament' },
  { country: 'Poland', icon: 'poland_palace_of_culture' },
  { country: 'Norway', icon: 'norway_fjord_cliffs' },
  { country: 'Sweden', icon: 'sweden_stockholm_city_hall' },
  { country: 'Denmark', icon: 'denmark_nyhavn_harbor' },
  { country: 'Finland', icon: 'finland_helsinki_cathedral' },
  { country: 'Turkey', icon: 'turkey_hagia_sophia' },
  { country: 'Morocco', icon: 'morocco_hassan_ii_mosque' },
  { country: 'Egypt', icon: 'egypt_pyramids_of_giza' },
  { country: 'South Africa', icon: 'south_africa_table_mountain' },
  { country: 'Kenya', icon: 'kenya_mount_kenya' },
  { country: 'Tanzania', icon: 'tanzania_mount_kilimanjaro' },
  { country: 'Ethiopia', icon: 'ethiopia_lalibela_church' },
  { country: 'United Arab Emirates', icon: 'united_arab_emirates_burj_khalifa' },
  { country: 'Saudi Arabia', icon: 'saudi_arabia_alula' },
  { country: 'Jordan', icon: 'jordan_petra' },
  { country: 'Israel', icon: 'israel_dome_of_the_rock' },
  { country: 'India', icon: 'india_taj_mahal' },
  { country: 'Nepal', icon: 'nepal_mount_everest' },
  { country: 'Sri Lanka', icon: 'sri_lanka_sigiriya_rock' },
  { country: 'Thailand', icon: 'thailand_wat_arun' },
  { country: 'Vietnam', icon: 'vietnam_ha_long_bay' },
  { country: 'Cambodia', icon: 'cambodia_angkor_wat' },
  { country: 'Singapore', icon: 'singapore_marina_bay_sands' },
  { country: 'Malaysia', icon: 'malaysia_petronas_towers' },
  { country: 'Indonesia', icon: 'indonesia_borobudur' },
  { country: 'Philippines', icon: 'philippines_mayon_volcano' },
  { country: 'China', icon: 'china_great_wall' },
  { country: 'Japan', icon: 'japan_mount_fuji' },
  { country: 'South Korea', icon: 'south_korea_n_seoul_tower' },
  { country: 'Taiwan', icon: 'taiwan_taipei_101' },
  { country: 'Hong Kong', icon: 'hong_kong_victoria_peak_skyline' },
  { country: 'Australia', icon: 'australia_sydney_opera_house' },
  { country: 'New Zealand', icon: 'new_zealand_milford_sound' },
  { country: 'Fiji', icon: 'fiji_tropical_island' },
  { country: 'French Polynesia', icon: 'french_polynesia_bora_bora_overwater_huts' },
  { country: 'Maldives', icon: 'maldives_overwater_bungalow' },
  { country: 'Qatar', icon: 'qatar_museum_of_islamic_art' },
  { country: 'Oman', icon: 'oman_sultan_qaboos_grand_mosque' },
  { country: 'Iran', icon: 'iran_azadi_tower' },
  { country: 'Iraq', icon: 'iraq_ziggurat_of_ur' },
  { country: 'Lebanon', icon: 'lebanon_baalbek_ruins' },
  { country: 'Armenia', icon: 'armenia_mount_ararat' },
  { country: 'Georgia', icon: 'georgia_gergeti_trinity_church' },
  { country: 'Romania', icon: 'romania_bran_castle' },
  { country: 'Croatia', icon: 'croatia_dubrovnik_city_walls' },
  { country: 'Slovenia', icon: 'slovenia_lake_bled_church' },
  { country: 'Serbia', icon: 'serbia_saint_sava' },
  { country: 'Bulgaria', icon: 'bulgaria_alexander_nevsky_cathedral' },
  { country: 'Ukraine', icon: 'ukraine_saint_sophia_cathedral' },
  { country: 'Russia', icon: 'russia_saint_basils_cathedral' },
  { country: 'Mongolia', icon: 'mongolia_yurt' },
  { country: 'Kazakhstan', icon: 'kazakhstan_bayterek_tower' },
];

const STAMP_SHAPE_KEYS: StampShapeKey[] = [
  'archedCountryCanonical',
  'archedCountryBanner',
  'archedCountryVariant',
  'circularCityClean',
  'circularCityDoubleLine',
  'roundedImmigrationCanonical',
  'roundedImmigrationWithBand',
  'shieldBadgeRounded',
];

const STAMP_INK_COLORS = ['#B6543F', '#2F5E9E', '#52745A', '#9A5A32', '#C79A43'];

const COUNTRY_ABBREVIATIONS: Record<string, string> = {
  'United States': 'USA',
  'United Arab Emirates': 'U.A.E.',
  'United Kingdom': 'U.K.',
};

function hashString(value: string) {
  let h = 0;
  for (let i = 0; i < value.length; i++) {
    h = ((h << 5) - h + value.charCodeAt(i)) | 0;
  }
  return Math.abs(h);
}

function buildStampDate(country: string) {
  const h = hashString(`date:${country}`);
  const day = ((h % 27) + 1).toString().padStart(2, '0');
  const month = (((h >> 4) % 12) + 1).toString().padStart(2, '0');
  const year = 2018 + ((h >> 9) % 8);
  return `${year}-${month}-${day}`;
}

function buildVisitedCountryStampPreviews() {
  return COUNTRY_ROSTER.map((entry, index) => {
    const h = hashString(entry.country);
    const display = COUNTRY_ABBREVIATIONS[entry.country] ?? entry.country;
    return {
      shape: STAMP_SHAPE_KEYS[h % STAMP_SHAPE_KEYS.length],
      icon: entry.icon,
      color: STAMP_INK_COLORS[(h >> 3) % STAMP_INK_COLORS.length],
      country: display,
      city: undefined as string | undefined,
      airportCode: undefined as string | undefined,
      date: buildStampDate(entry.country),
      footer: undefined as string | undefined,
      rotate: index % 2 === 0 ? -3 : 3,
    };
  });
}

const visitedCountryStampPreviews = buildVisitedCountryStampPreviews();

export function PassportStatsScreen({ active, onChange }: { active: BottomNavTab; onChange: (tab: BottomNavTab) => void }) {
  const insets = useSafeAreaInsets();
  const { width } = useWindowDimensions();
  const screenPadding = width < 390 ? 16 : layout.screenPadding;
  const contentWidth = width - screenPadding * 2;
  const cardWidth = (contentWidth - layout.cardGap) / 2;
  const { profile, status, refresh } = useTravelTrips();

  return (
    <View style={[styles.screen, { paddingTop: insets.top + 12 }]}>
      <ScrollView
        showsVerticalScrollIndicator={false}
        refreshControl={<RefreshControl refreshing={status === 'loading' || status === 'refreshing' || status === 'syncing'} onRefresh={refresh} tintColor={colors.red} />}
        contentContainerStyle={{ paddingBottom: insets.bottom + layout.bottomNavHeight + 24 }}
      >
        <ScreenHeader
          title="PASSPORT"
          subtitle="TRAVELER IDENTITY"
          leftAction={<IconButton variant="paper" shape="circle" icon={<IconGlyph name="passport" color={colors.ink} size={22} />} />}
          rightActions={[<IconButton key="globe" variant="paper" shape="circle" icon={<IconGlyph name="globe" color={colors.ink} size={22} />} />]}
        />
        <PaperSurface radius={18} padding={spacing.lg} style={[styles.identity, { marginHorizontal: screenPadding, width: contentWidth }]}>
          <View style={styles.identityTop}>
            <PassportBookletGraphic />
            <View style={styles.identityCopy}>
              <Text allowFontScaling={false} numberOfLines={1} adjustsFontSizeToFit style={styles.kicker}>TRAVELER</Text>
              <Text allowFontScaling={false} numberOfLines={1} adjustsFontSizeToFit style={styles.name}>{profile.name}</Text>
              <Text maxFontSizeMultiplier={1.05} numberOfLines={1} style={styles.homeAirport}>{profile.homeAirport} / {profile.homeAirportName}</Text>
              <Text maxFontSizeMultiplier={1.05} numberOfLines={2} style={styles.firstFlight}>FIRST DISCOVERED FLIGHT {profile.firstFlightDate}</Text>
            </View>
          </View>
          <View style={styles.stampRow}>
            <Stamp type="circle" color={colors.red} title="ADVENTURE" subtitle={`${profile.flights} FLIGHTS`} footer="VERIFIED" size="sm" />
            <Stamp type="rounded-immigration" color={colors.blue} title="ISSUED" subtitle="TROTTER APP" date="2026" size="sm" />
          </View>
          <View style={styles.statStrip}>
            <StripStat label="FLIGHTS" value={profile.flights} />
            <StripStat label="COUNTRIES" value={profile.countries} />
            <StripStat label="AIRPORTS" value={profile.airports} />
          </View>
        </PaperSurface>

        <View style={[styles.grid, { paddingHorizontal: screenPadding, gap: layout.cardGap }]}>
          <StatCard width={cardWidth} label="TOTAL MILES" value={profile.miles.toLocaleString()} sublabel="lifetime distance" icon="plane" />
          <StatCard width={cardWidth} label="TIME IN AIR" value={`${profile.hoursInAir}h`} sublabel="logged cabin time" icon="crosshair" />
          <StatCard width={cardWidth} label="COUNTRIES VISITED" value={`${profile.countries} / 195`} sublabel="visited from flight history" icon="globe" />
          <StatCard width={cardWidth} label="AIRLINES FLOWN" value={`${profile.airlines}`} sublabel="carriers flown" icon="tag" />
          <StatCard width={cardWidth} label="FURTHEST FLIGHT" value="7,238 mi" sublabel="DFW to HND" icon="plane" />
          <StatCard width={cardWidth} label="LONGEST TRIP" value="9 days" sublabel="Tokyo, Japan" icon="passport" />
        </View>

        <Text style={[styles.sectionTitle, { marginHorizontal: screenPadding }]}>COLLECTIONS</Text>
        <View style={[styles.collectionRow, { paddingHorizontal: screenPadding, gap: layout.cardGap }]}>
          <CollectionCard
            width={cardWidth}
            title="COUNTRIES"
            value={`${profile.countries} / 195`}
            onPress={() => onChange('profile')}
            preview={<PngStamp {...japanPreviewStamp} size="md" variant="collection" rotate={-4} scale={0.7} />}
          />
          <CollectionCard width={cardWidth} title="CONTINENTS" value="4 / 7" preview={<Image source={require('../../assets/objects/globe.png')} style={{ width: 110, height: 110, resizeMode: 'contain' }} />} />
          <CollectionCard width={cardWidth} title="AIRPORTS" value={`${profile.airports}`} preview={<Image source={require('../../assets/objects/airport.png')} style={{ width: 150, height: 150, resizeMode: 'contain' }} />} />
          <CollectionCard width={cardWidth} title="AIRLINES" value={`${profile.airlines}`} preview={<Image source={require('../../assets/objects/airline.png')} style={{ width: 150, height: 150, resizeMode: 'contain' }} />} />
        </View>

        <PaperSurface radius={14} padding={spacing.md} style={[styles.countryPreviewPanel, { marginHorizontal: screenPadding, width: contentWidth }]}>
          <View style={styles.countryPreviewHeader}>
            <Text allowFontScaling={false} style={styles.countryPreviewTitle}>COUNTRY STAMP TEST</Text>
            <Text allowFontScaling={false} style={styles.countryPreviewCount}>{visitedCountryStampPreviews.length} stamps</Text>
          </View>
          <View style={styles.countryPreviewGrid}>
            {visitedCountryStampPreviews.map((stamp) => {
              const cellWidth = (contentWidth - spacing.md * 2 - spacing.sm) / 2;
              const stampScale = Math.max(0.5, Math.min(1, (cellWidth - 12) / STAMP_TEST_BASE_WIDTH));
              return (
                <View key={stamp.country} style={[styles.countryPreviewStamp, { width: cellWidth, minHeight: 165.75 * stampScale + 24 }]}>
                  <PngStamp {...stamp} size="md" variant="collection" rotate={stamp.rotate} scale={stampScale} />
                </View>
              );
            })}
          </View>
        </PaperSurface>
      </ScrollView>
      <BottomNav active={active} onChange={onChange} />
    </View>
  );
}

function CollectionCard({
  title,
  value,
  preview,
  width,
  onPress,
}: {
  title: string;
  value: string;
  preview: React.ReactNode;
  width: number;
  onPress?: () => void;
}) {
  const content = (
      <PaperSurface radius={12} padding={spacing.md} style={styles.collectionCard}>
        <Text allowFontScaling={false} numberOfLines={1} style={styles.collectionTitle}>{title}</Text>
        <Text allowFontScaling={false} numberOfLines={1} style={styles.collectionValue}>{value}</Text>
        <View style={styles.collectionPreview}>{preview}</View>
      </PaperSurface>
  );

  return onPress ? (
    <Pressable onPress={onPress} style={{ width }}>
      {content}
    </Pressable>
  ) : (
    <View style={{ width }}>
      {content}
    </View>
  );
}

function PassportBookletGraphic() {
  return (
    <DarkPanel radius={12} padding={spacing.md} style={styles.booklet}>
      <Text allowFontScaling={false} style={styles.bookletTitle}>PASSPORT</Text>
      <View style={styles.bookletGlobe}><IconGlyph name="globe" color={colors.brassSoft} size={44} /></View>
      <Text allowFontScaling={false} style={styles.bookletCode}>TROTTER / DFW</Text>
    </DarkPanel>
  );
}

function StripStat({ label, value }: { label: string; value: number }) {
  return (
    <View style={styles.stripStat}>
      <SplitFlapNumber value={value} minDigits={label === 'COUNTRIES' ? 2 : 3} />
      <Text allowFontScaling={false} numberOfLines={1} style={styles.stripLabel}>{label}</Text>
    </View>
  );
}

function StatCard({ label, value, sublabel, icon, width }: { label: string; value: string; sublabel: string; icon: string; width: number }) {
  return (
    <PaperSurface radius={12} padding={spacing.md} style={[styles.statCard, { width }]}>
      <IconGlyph name={icon} color={colors.red} size={22} />
      <Text maxFontSizeMultiplier={1.05} numberOfLines={1} adjustsFontSizeToFit style={styles.statLabel}>{label}</Text>
      <Text allowFontScaling={false} numberOfLines={1} adjustsFontSizeToFit style={styles.statValue}>{value}</Text>
      <Text maxFontSizeMultiplier={1.05} numberOfLines={1} style={styles.statSub}>{sublabel}</Text>
    </PaperSurface>
  );
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
    backgroundColor: colors.paperSoft,
  },
  identity: {
    marginTop: spacing.sm,
  },
  identityTop: {
    flexDirection: 'row',
    gap: spacing.md,
  },
  booklet: {
    width: 106,
    height: 150,
    alignItems: 'center',
    justifyContent: 'space-between',
    backgroundColor: '#132136',
  },
  bookletTitle: {
    color: colors.brassSoft,
    fontFamily: fonts.sansBold,
    fontSize: 13,
  },
  bookletGlobe: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
  bookletCode: {
    color: colors.brassSoft,
    fontFamily: fonts.mono,
    fontSize: 9,
  },
  identityCopy: {
    flex: 1,
    minWidth: 0,
  },
  kicker: {
    color: colors.red,
    fontFamily: fonts.sansBold,
    fontSize: 10,
  },
  name: {
    color: colors.ink,
    fontFamily: fonts.display,
    fontSize: 29,
    marginTop: 6,
  },
  homeAirport: {
    color: colors.mutedInk,
    fontFamily: fonts.sansBold,
    fontSize: 13,
    marginTop: 4,
  },
  firstFlight: {
    color: colors.mutedInk,
    fontFamily: fonts.mono,
    fontSize: 10,
    marginTop: 12,
  },
  stampRow: {
    marginTop: spacing.md,
    flexDirection: 'row',
    gap: spacing.sm,
  },
  statStrip: {
    marginTop: spacing.md,
    flexDirection: 'row',
    justifyContent: 'space-between',
    borderTopWidth: 1,
    borderTopColor: colors.paperBorder,
    paddingTop: spacing.md,
  },
  stripStat: {
    alignItems: 'center',
    flex: 1,
  },
  stripLabel: {
    color: colors.mutedInk,
    fontFamily: fonts.sansBold,
    fontSize: 9,
    marginTop: 5,
  },
  grid: {
    marginTop: spacing.lg,
    flexDirection: 'row',
    flexWrap: 'wrap',
  },
  statCard: {
    height: 122,
    minWidth: 0,
  },
  statLabel: {
    color: colors.mutedInk,
    fontFamily: fonts.sansBold,
    fontSize: 10,
    marginTop: 8,
  },
  statValue: {
    color: colors.ink,
    fontFamily: fonts.display,
    fontSize: 27,
    marginTop: 2,
  },
  statSub: {
    color: colors.mutedInk,
    fontFamily: fonts.sansRegular,
    fontSize: 11,
  },
  sectionTitle: {
    color: colors.ink,
    fontFamily: fonts.sansBold,
    fontSize: 13,
    marginTop: spacing.xl,
    marginBottom: spacing.sm,
  },
  collectionRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
  },
  collectionCard: {
    alignItems: 'center',
    height: 200,
  },
  collectionTitle: {
    color: colors.ink,
    fontFamily: fonts.sansBold,
    fontSize: 12,
    letterSpacing: 0.8,
  },
  collectionValue: {
    color: colors.ink,
    fontFamily: fonts.display,
    fontSize: 21,
    marginTop: 3,
  },
  collectionPreview: {
    flex: 1,
    width: '100%',
    marginTop: spacing.sm,
    alignItems: 'center',
    justifyContent: 'center',
    overflow: 'hidden',
  },
  countryPreviewPanel: {
    marginTop: spacing.md,
  },
  countryPreviewHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: spacing.sm,
  },
  countryPreviewTitle: {
    color: colors.red,
    fontFamily: fonts.sansBold,
    fontSize: 12,
    letterSpacing: 0.8,
  },
  countryPreviewCount: {
    color: colors.mutedInk,
    fontFamily: fonts.mono,
    fontSize: 11,
  },
  countryPreviewGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    justifyContent: 'space-between',
    rowGap: spacing.md,
  },
  countryPreviewStamp: {
    minWidth: 0,
    alignItems: 'center',
    justifyContent: 'center',
  },
});
