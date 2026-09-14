import React from "react";
import {
  Modal,
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
  CollectionList,
  CountryArrivalDetail,
  type CollectionKind,
} from "../components/world-window/passport/PassportCollections";
import { buildPassportArchive } from "../components/world-window/passport/passport-model";
import type { CountryArrival } from "../utils/countryArrivals";
import type { BottomNavTab, TripSummary } from "../data/trotterMock";
import { useTravelTrips } from "../services/travelTrips";
import { colors, fonts, layout } from "../theme/trotterTheme";
import { getMobileVisualWidth } from "../utils/mobileLayout";

export function PassportStatsScreen({
  active,
  onChange,
  onOpenCountries,
  onOpenTrip,
  onYear,
  initialCollection,
  collectionBackLabel,
  onCloseCollection,
}: {
  active: BottomNavTab;
  onChange: (tab: BottomNavTab) => void;
  onOpenCountries?: () => void;
  onOpenTrip?: (trip: TripSummary) => void;
  onYear?: (year: string) => void;
  initialCollection?: CollectionKind;
  collectionBackLabel?: string;
  onCloseCollection?: () => void;
}) {
  const insets = useSafeAreaInsets(),
    { width } = useWindowDimensions(),
    visualWidth = getMobileVisualWidth(width);
  const { trips, profile, status, refresh } = useTravelTrips();
  const archive = React.useMemo(
    () => buildPassportArchive(trips, profile),
    [trips, profile],
  );
  const [interacting, setInteracting] = React.useState(false),
    [collection, setCollection] = React.useState<CollectionKind | null>(initialCollection ?? null),
    [country, setCountry] = React.useState<CountryArrival | null>(null);
  const detailBack = React.useRef<(() => boolean) | null>(null);
  const registerDetailBack = React.useCallback((handler: (() => boolean) | null) => {
    detailBack.current = handler;
  }, []);
  React.useEffect(() => {
    setCollection(initialCollection ?? null);
    setCountry(null);
  }, [initialCollection]);
  const openCollection = (kind: CollectionKind) => {
    if (kind === "countries" && onOpenCountries) onOpenCountries();
    else setCollection(kind);
  };
  const close = () => {
    if (country) setCountry(null);
    else {
      setCollection(null);
      onCloseCollection?.();
    }
  };
  const openTrip = onOpenTrip
    ? (trip: TripSummary) => {
        setCountry(null);
        setCollection(null);
        onOpenTrip(trip);
      }
    : undefined;
  return (
    <View style={[styles.screen, { paddingTop: insets.top }]}>
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
        <View style={styles.book}>
          <PassportBook
            archive={archive}
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
            <ActivityChart years={archive.years} width={visualWidth - 48} onYear={onYear} latestDate={trips.flatMap(t => (t.segments ?? []).map(s => s.depTime)).sort().at(-1)} />
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
                  <View style={styles.recordCopy}>
                    <Text style={styles.recordValue}>{record.value}</Text>
                    <Text style={styles.recordDetail}>{record.detail}</Text>
                  </View>
                </Pressable>
              ))}
            </View>
          )}
        </View>
      </ScrollView>
      <BottomNav active={active} onChange={onChange} />
      <Modal
        visible={Boolean(collection || country)}
        animationType="fade"
        presentationStyle="fullScreen"
        onRequestClose={() => { if (!detailBack.current?.()) close(); }}
      >
        <View
          style={[
            styles.screen,
            {
              paddingTop: insets.top,
              paddingBottom: insets.bottom + layout.bottomNavHeight,
              maxWidth: visualWidth,
              width: "100%",
              alignSelf: "center",
            },
          ]}
        >
          {country ? (
            <CountryArrivalDetail
              arrival={country}
              trips={trips}
              onBack={close}
              onOpenTrip={openTrip}
              width={visualWidth}
              backLabel={collection ? "Countries" : "Passport"}
              onBackHandlerChange={registerDetailBack}
            />
          ) : collection ? (
            <CollectionList
              key={collection}
              kind={collection}
              archive={archive}
              onBack={close}
              onSelectCountry={setCountry}
              onOpenTrip={openTrip}
              backLabel={collectionBackLabel}
              onBackHandlerChange={registerDetailBack}
            />
          ) : null}
          <BottomNav active="passport" onChange={(tab) => { setCountry(null); setCollection(null); onChange(tab); }} />
        </View>
      </Modal>
    </View>
  );
}
const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.paperSoft },
  book: { alignItems: "center", marginTop: 8, marginBottom: 24 },
  content: { paddingHorizontal: 24 },
  activity: { marginTop: 28 },
  sectionTitle: { fontFamily: fonts.sans, fontSize: 15, lineHeight: 21, color: colors.ink, marginBottom: 16 },
  records: { marginTop: 28 },
  record: { paddingVertical: 13, borderBottomWidth: 1, borderBottomColor: colors.paperBorder, gap: 5 },
  recordCopy: { flexDirection: "row", alignItems: "flex-end", gap: 8 },
  recordLabel: { fontFamily: fonts.sansRegular, fontSize: 13, color: colors.mutedInk },
  recordValue: { flex: 1, fontFamily: fonts.display, fontSize: 21, lineHeight: 24, color: colors.ink },
  recordDetail: { maxWidth: 90, fontFamily: fonts.sansRegular, fontSize: 13, lineHeight: 19.5, color: colors.mutedInk, textAlign: "right" },
});
