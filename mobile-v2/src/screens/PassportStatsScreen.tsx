import React from "react";
import {
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  useWindowDimensions,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { BottomNav } from "../components/trotter/TrotterKit";
import { WWHeader } from "../components/world-window/WorldWindowUI";
import { PassportBook } from "../components/world-window/passport/PassportBook";
import { ActivityChart } from "../components/world-window/passport/ActivityChart";
import {
  CollectionButtons,
  CollectionScope,
  CollectionList,
  CountryArrivalDetail,
  type CollectionKind,
} from "../components/world-window/passport/PassportCollections";
import { buildPassportArrivals } from "../components/world-window/passport/passport-arrivals";
import type { CountryArrival } from "../utils/countryArrivals";
import type { BottomNavTab, TripSummary } from "../data/trotterMock";
import { useTravelTrips } from "../services/travelTrips";
import { colors, fonts, layout } from "../theme/trotterTheme";
import { getMobileVisualWidth } from "../utils/mobileLayout";
import { normalizeTravelYear, scopeTripsToYear } from "../utils/travelScope";
import { scopedPassportArchive } from "../components/world-window/passport/passport-scope";
import {
  earnedCountries,
  type ArrivalBaseline,
} from "../components/world-window/passport/passport-earned";

export function PassportStatsScreen({
  active,
  onChange,
  onOpenCountries,
  onOpenTrip,
  onYear,
  initialCollection,
  collectionBackLabel,
  onCloseCollection,
  visible = true,
  onBackHandlerChange,
  resetEpoch = 0,
  initialYear,
  scopeEpoch = 0,
  onClearYear,
  initialAirport,
}: {
  active: BottomNavTab;
  onChange: (tab: BottomNavTab) => void;
  onOpenCountries?: () => void;
  onOpenTrip?: (trip: TripSummary) => void;
  onYear?: (year: string) => void;
  initialCollection?: CollectionKind;
  collectionBackLabel?: string;
  onCloseCollection?: () => void;
  visible?: boolean;
  onBackHandlerChange?: (handler: (() => boolean) | null) => void;
  resetEpoch?: number;
  initialYear?: string;
  scopeEpoch?: number;
  onClearYear?: () => void;
  initialAirport?: string;
}) {
  const insets = useSafeAreaInsets(),
    { width, fontScale } = useWindowDimensions(),
    visualWidth = getMobileVisualWidth(width);
  const { trips, profile, status, refresh, lastGmailSyncedAt } =
    useTravelTrips();
  const baseline = React.useRef<ArrivalBaseline | null>(null);
  const [earned, setEarned] = React.useState<{
    key: string;
    codes: string[];
  }>();
  React.useEffect(() => {
    if (status !== "idle") return;
    const next = {
      codes: buildPassportArrivals(trips).map(
        (arrival) => arrival.travelCountryKey ?? arrival.country,
      ),
      syncedAt: lastGmailSyncedAt,
    };
    const codes = earnedCountries(baseline.current, next);
    if (codes.length && lastGmailSyncedAt)
      setEarned({ key: lastGmailSyncedAt, codes });
    baseline.current = next;
  }, [trips, status, lastGmailSyncedAt]);
  const [year, setYear] = React.useState(() =>
    normalizeTravelYear(initialYear),
  );
  React.useEffect(
    () => setYear(normalizeTravelYear(initialYear)),
    [initialYear, scopeEpoch],
  );
  const clearYear = () => {
    setYear(undefined);
    onClearYear?.();
  };
  const scopedTrips = React.useMemo(
    () => scopeTripsToYear(trips, year),
    [trips, year],
  );
  const archive = React.useMemo(
    () => scopedPassportArchive(trips, profile, year),
    [trips, profile, year],
  );
  const [interacting, setInteracting] = React.useState(false),
    [collection, setCollection] = React.useState<CollectionKind | null>(
      initialAirport ? "airports" : (initialCollection ?? null),
    ),
    [country, setCountry] = React.useState<CountryArrival | null>(null);
  const collectionBack = React.useRef<(() => boolean) | null>(null);
  const countryBack = React.useRef<(() => boolean) | null>(null);
  const previousReset = React.useRef(resetEpoch);
  React.useEffect(() => {
    if (previousReset.current === resetEpoch) return;
    previousReset.current = resetEpoch;
    setCountry(null);
    setCollection(null);
  }, [resetEpoch]);
  const registerCollectionBack = React.useCallback(
    (handler: (() => boolean) | null) => {
      collectionBack.current = handler;
    },
    [],
  );
  const registerCountryBack = React.useCallback(
    (handler: (() => boolean) | null) => {
      countryBack.current = handler;
    },
    [],
  );
  React.useEffect(() => {
    setCollection(initialAirport ? "airports" : (initialCollection ?? null));
    setCountry(null);
  }, [initialCollection, initialAirport, scopeEpoch]);
  const openCollection = (kind: CollectionKind) => {
    if (kind === "countries" && onOpenCountries) onOpenCountries();
    else setCollection(kind);
  };
  const close = React.useCallback(() => {
    if (country) setCountry(null);
    else {
      setCollection(null);
      onCloseCollection?.();
    }
  }, [country, onCloseCollection]);
  const handleBack = React.useCallback(() => {
    if (country) {
      if (!countryBack.current?.()) setCountry(null);
      return true;
    }
    if (!collection) return false;
    if (!collectionBack.current?.()) close();
    return true;
  }, [country, collection, close]);
  React.useEffect(() => {
    onBackHandlerChange?.(visible ? handleBack : null);
    return () => onBackHandlerChange?.(null);
  }, [visible, handleBack, onBackHandlerChange]);
  const changeTab = (tab: BottomNavTab) => {
    setCountry(null);
    setCollection(null);
    onChange(tab);
  };
  const openTrip = onOpenTrip
    ? (trip: TripSummary) =>
        onOpenTrip(trips.find((item) => item.id === trip.id) ?? trip)
    : undefined;
  const hasOverlay = Boolean(country || collection);
  return (
    <View style={[styles.screen, { paddingTop: insets.top }]}>
      <View
        style={styles.base}
        pointerEvents={hasOverlay ? "none" : "auto"}
        aria-hidden={hasOverlay}
        accessibilityElementsHidden={hasOverlay}
        importantForAccessibility={hasOverlay ? "no-hide-descendants" : "auto"}
      >
        <ScrollView
          showsVerticalScrollIndicator={false}
          scrollEnabled={!interacting}
          refreshControl={
            <RefreshControl
              enabled={!interacting}
              refreshing={status === "refreshing" || status === "syncing"}
              onRefresh={refresh}
              tintColor={colors.blue}
            />
          }
          contentContainerStyle={{
            width: visualWidth,
            paddingBottom: insets.bottom + layout.bottomNavHeight + 24,
          }}
        >
          <WWHeader title="Passport" />
          <View style={styles.content}>
            <CollectionScope year={year} onClear={clearYear} />
          </View>
          <View style={styles.book}>
            <PassportBook
              archive={archive}
              earned={earned}
              visible={visible && !hasOverlay}
              width={visualWidth - 2}
              onInteractionChange={setInteracting}
              onCountry={(code) => {
                const arrival = archive.arrivals.find(
                  (item) => (item.travelCountryKey ?? item.country) === code,
                );
                if (arrival) setCountry(arrival);
              }}
            />
          </View>
          <View style={styles.content}>
            <Text style={styles.sectionTitle}>Collections</Text>
            <CollectionButtons archive={archive} onOpen={openCollection} />
            <View style={styles.activity}>
              <Text accessibilityRole="header" style={styles.sectionTitle}>
                Travel activity
              </Text>
              <ActivityChart
                years={archive.years}
                width={visualWidth - 48}
                onYear={onYear}
                latestDate={scopedTrips
                  .flatMap((t) => (t.segments ?? []).map((s) => s.depTime))
                  .sort()
                  .at(-1)}
              />
            </View>
            {archive.records.length > 0 && (
              <View style={styles.records}>
                <Text accessibilityRole="header" style={styles.sectionTitle}>
                  Travel records
                </Text>
                {archive.records.map((record) => (
                  <Pressable
                    key={record.label}
                    disabled={!record.trip || !openTrip}
                    accessibilityRole={
                      record.trip && openTrip ? "button" : undefined
                    }
                    onPress={() => record.trip && openTrip?.(record.trip)}
                    style={({ pressed }) => [
                      styles.record,
                      pressed && { opacity: 0.7 },
                    ]}
                  >
                    <Text style={styles.recordLabel}>{record.label}</Text>
                    <View
                      style={[
                        styles.recordCopy,
                        fontScale >= 1.35 && styles.recordStacked,
                      ]}
                    >
                      <Text style={styles.recordValue}>{record.value}</Text>
                      <Text
                        style={[
                          styles.recordDetail,
                          fontScale >= 1.35 && styles.recordDetailLarge,
                        ]}
                      >
                        {record.detail}
                      </Text>
                    </View>
                  </Pressable>
                ))}
              </View>
            )}
          </View>
        </ScrollView>
      </View>
      {collection && (
        <View
          style={[
            styles.overlay,
            {
              top: insets.top,
              paddingBottom: insets.bottom + layout.bottomNavHeight,
            },
          ]}
          pointerEvents={country ? "none" : "auto"}
          aria-hidden={Boolean(country)}
          accessibilityElementsHidden={Boolean(country)}
          importantForAccessibility={country ? "no-hide-descendants" : "auto"}
        >
          <CollectionList
            key={collection}
            kind={collection}
            archive={archive}
            onBack={close}
            onSelectCountry={setCountry}
            onOpenTrip={openTrip}
            backLabel={collectionBackLabel}
            onBackHandlerChange={registerCollectionBack}
            initialAirport={initialAirport}
            scopeEpoch={scopeEpoch}
            year={year}
            onClearYear={clearYear}
          />
        </View>
      )}
      {country && (
        <View
          style={[
            styles.overlay,
            {
              top: insets.top,
              paddingBottom: insets.bottom + layout.bottomNavHeight,
            },
          ]}
        >
          <CountryArrivalDetail
            key={country.travelCountryKey ?? country.country}
            arrival={country}
            trips={scopedTrips}
            onBack={close}
            onOpenTrip={openTrip}
            width={visualWidth}
            backLabel={collection ? "Countries" : "Passport"}
            onBackHandlerChange={registerCountryBack}
            year={year}
            onClearYear={clearYear}
          />
        </View>
      )}
      <BottomNav active={active} onChange={changeTab} />
    </View>
  );
}
const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.paperSoft },
  base: { flex: 1 },
  overlay: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: colors.paperSoft,
  },
  recordStacked: { flexDirection: "column", alignItems: "flex-start" },
  recordDetailLarge: { maxWidth: "100%", textAlign: "left" },
  book: { alignItems: "center", marginTop: 8, marginBottom: 24 },
  content: { paddingHorizontal: 24 },
  activity: { marginTop: 28 },
  sectionTitle: {
    fontFamily: fonts.sans,
    fontSize: 15,
    lineHeight: 21,
    color: colors.ink,
    marginBottom: 16,
  },
  records: { marginTop: 28 },
  record: {
    paddingVertical: 13,
    borderBottomWidth: 1,
    borderBottomColor: colors.paperBorder,
    gap: 5,
  },
  recordCopy: { flexDirection: "row", alignItems: "flex-end", gap: 8 },
  recordLabel: {
    fontFamily: fonts.sansRegular,
    fontSize: 13,
    color: colors.mutedInk,
  },
  recordValue: {
    flex: 1,
    fontFamily: fonts.display,
    fontSize: 21,
    lineHeight: 24,
    color: colors.ink,
  },
  recordDetail: {
    maxWidth: 90,
    fontFamily: fonts.sansRegular,
    fontSize: 13,
    lineHeight: 19.5,
    color: colors.mutedInk,
    textAlign: "right",
  },
});
