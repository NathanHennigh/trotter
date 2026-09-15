import React from "react";
import {
  FlatList,
  RefreshControl,
  StyleSheet,
  Text,
  TextInput,
  useWindowDimensions,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { BottomNav } from "../components/trotter/TrotterKit";
import {
  WWButton,
  WWEmpty,
  WWHeader,
  WWIcon,
} from "../components/world-window/WorldWindowUI";
import { PressFeedback } from "../components/world-window/motion";
import { WalletCover, type WalletOrigin } from "../components/world-window/trips/WalletCover";
import { matchesTrip } from "../components/world-window/trips/tripPresentation";
import { normalizeTravelYear, scopeTripsToYear } from "../utils/travelScope";
import type { BottomNavTab, TripSummary } from "../data/trotterMock";
import { useTravelTrips } from "../services/travelTrips";
import { colors, fonts, layout } from "../theme/trotterTheme";

export function TripsListScreen({
  active,
  onChange,
  onOpenTrip,
  initialYear,
  scopeEpoch = 0,
  onClearYear,
  liftedTripId,
}: {
  active: BottomNavTab;
  onChange: (tab: BottomNavTab) => void;
  onOpenTrip?: (trip: TripSummary, flightId?: string, origin?: WalletOrigin) => void;
  initialYear?: string;
  scopeEpoch?: number;
  onClearYear?: () => void;
  liftedTripId?: string;
}) {
  const insets = useSafeAreaInsets(),
    { trips, status, error, refresh } = useTravelTrips();
  const { width, fontScale } = useWindowDimensions();
  const stackCount = width <= 360 && fontScale >= 1.35;
  const [query, setQuery] = React.useState("");
  const [selectedYear, setSelectedYear] = React.useState(() => normalizeTravelYear(initialYear));
  const list = React.useRef<FlatList<TripSummary>>(null);
  React.useEffect(() => {
    setSelectedYear(normalizeTravelYear(initialYear));
    setQuery("");
    list.current?.scrollToOffset({ offset: 0, animated: false });
  }, [initialYear, scopeEpoch]);
  const originals = React.useMemo(() => new Map(trips.map(trip => [trip.id, trip])), [trips]);
  const scoped = React.useMemo(() => scopeTripsToYear(trips, selectedYear), [trips, selectedYear]);
  const visible = React.useMemo(() => scoped.filter(trip => matchesTrip(trip, query, false, 0)), [scoped, query]);
  const year = selectedYear ?? String(new Date().getFullYear());
  const yearTrips = React.useMemo(() => scopeTripsToYear(trips, year), [trips, year]);
  const clearYear = () => { setSelectedYear(undefined); onClearYear?.(); };
  const loading =
    status === "loading" || status === "refreshing" || status === "syncing";
  return (
    <View style={[s.screen, { paddingTop: insets.top }]}>
      <FlatList
        ref={list}
        data={visible}
        keyExtractor={(trip) => trip.id}
        keyboardShouldPersistTaps="handled"
        keyboardDismissMode="on-drag"
        showsVerticalScrollIndicator={false}
        contentContainerStyle={{
          paddingBottom: insets.bottom + layout.bottomNavHeight + 24,
        }}
        refreshControl={
          <RefreshControl
            refreshing={loading}
            onRefresh={() => void refresh()}
            tintColor={colors.blue}
          />
        }
        initialNumToRender={6}
        windowSize={7}
        ListHeaderComponent={
          <>
            <WWHeader
              title="Trips"
              action={!stackCount ? <Text style={s.headerCount}>{query || selectedYear ? `${visible.length} / ${trips.length}` : trips.length}</Text> : undefined}
            />
            {stackCount ? <Text style={s.stackedCount}>{visible.length}{query || selectedYear ? ` of ${trips.length}` : ""} trips</Text> : null}
            <View style={s.searchRow}>
              <WWIcon name="search" size={19} color={colors.mutedInk} />
              <TextInput
                value={query}
                onChangeText={setQuery}
                placeholder="Search city or airport"
                placeholderTextColor={colors.mutedInk}
                accessibilityLabel="Search trips"
                style={s.search}
              />
              {query.length > 0 && (
                <PressFeedback
                  accessibilityLabel="Clear search"
                  onPress={() => setQuery("")}
                  style={s.icon}
                >
                  <WWIcon name="close" size={17} />
                </PressFeedback>
              )}
            </View>
            <View style={s.toolbar}>
              <View style={s.tabs}>
                {[
                  { label: "All years", value: undefined, count: trips.length },
                  {
                    label: year,
                    value: year,
                    count: yearTrips.length,
                  },
                ].map(({ label, value, count }) => (
                  <PressFeedback
                    key={label}
                    accessibilityRole="tab"
                    accessibilityState={{ selected: selectedYear === value }}
                    onPress={() => { if (value) setSelectedYear(value); else clearYear(); }}
                    style={[s.tab, selectedYear === value && s.activeTab]}
                  >
                    <Text
                      style={[s.tabText, selectedYear === value && s.activeText]}
                    >
                      {label} <Text style={s.tabCount}>{count}</Text>
                    </Text>
                  </PressFeedback>
                ))}
              </View>
            </View>
            {error && (
              <PressFeedback onPress={() => void refresh()} style={s.error}>
                <Text style={s.errorText}>{error} · Tap to retry</Text>
              </PressFeedback>
            )}
          </>
        }
        renderItem={({ item, index }) => (
          <View>
            {(index === 0 ||
              (!selectedYear && visible[index - 1].startDate.slice(0, 4) !==
                item.startDate.slice(0, 4))) && (
              <View style={s.yearDivider}>
                <Text style={s.year}>{selectedYear ?? item.startDate.slice(0, 4)}</Text>
                <View style={s.yearRule} />
              </View>
            )}
            <View style={liftedTripId === item.id ? { opacity: 0 } : undefined}>
            <WalletCover
              trip={item}
              scopeYear={selectedYear}
              totalFlightCount={originals.get(item.id)?.flightCount}
              onPress={(origin) => { const original = originals.get(item.id); if (original) onOpenTrip?.(original, undefined, origin); }}
            />
            </View>
          </View>
        )}
        ListEmptyComponent={
          <WWEmpty
            title={
              loading
                ? "Loading your trips…"
                : query || selectedYear
                  ? "No matching trips"
                  : "Your trips will live here"
            }
            body={
              loading
                ? undefined
                : query || selectedYear
                  ? "Try another search or view all trips."
                  : "Import your flight confirmations from Profile."
            }
            action={!loading ? <WWButton label={error ? "Retry" : query || selectedYear ? "Show all trips" : "Open Profile"} onPress={() => { if (error) void refresh(); else if (query || selectedYear) { setQuery(""); clearYear(); } else onChange("profile"); }} secondary /> : undefined}
          />
        }
      />
      <BottomNav active={active} onChange={onChange} />
    </View>
  );
}
const s = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.paperSoft },
  icon: {
    width: 44,
    height: 44,
    alignItems: "center",
    justifyContent: "center",
  },
  searchRow: {
    marginHorizontal: 24,
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    paddingVertical: 9,
    borderBottomWidth: 1,
    borderBottomColor: colors.paperBorder,
    marginBottom: 6,
  },
  search: {
    flex: 1,
    paddingVertical: 10,
    minHeight: 44,
    fontFamily: fonts.sansRegular,
    color: colors.ink,
    fontSize: 15,
  },
  toolbar: {
    marginHorizontal: 24,
    marginBottom: 0,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    borderBottomWidth: 1,
    borderBottomColor: colors.paperBorder,
  },
  tabs: { flexDirection: "row", flex: 1 },
  tab: {
    flex: 1,
    minHeight: 46,
    justifyContent: "center",
    paddingHorizontal: 6,
    borderBottomWidth: 2,
    borderBottomColor: "transparent",
  },
  activeTab: { borderBottomColor: colors.blue },
  tabText: {
    fontFamily: fonts.sansRegular,
    fontSize: 14,
    color: colors.mutedInk,
  },
  activeText: { fontFamily: fonts.sans, color: colors.blue },
  tabCount: { fontFamily: fonts.sansRegular, fontSize: 12 },
  headerCount: {
    fontFamily: fonts.display,
    fontSize: 25,
    lineHeight: 30,
    color: "#cd744f",
    includeFontPadding: false,
  },
  stackedCount: { marginHorizontal: 24, marginTop: -10, marginBottom: 12, fontFamily: fonts.sansRegular, fontSize: 13, lineHeight: 19, color: colors.mutedInk },
  yearDivider: {
    marginHorizontal: 20,
    marginTop: 16,
    marginBottom: 12,
    flexDirection: "row",
    alignItems: "center",
    gap: 16,
  },
  year: {
    fontFamily: fonts.display,
    fontSize: 28,
    lineHeight: 32,
    color: "#315b70",
    includeFontPadding: false,
  },
  yearRule: { flex: 1, height: 1, backgroundColor: colors.paperBorder },
  error: {
    marginHorizontal: 24,
    marginBottom: 16,
    padding: 12,
    backgroundColor: colors.paper,
    borderWidth: 1,
    borderColor: colors.paperBorder,
  },
  errorText: {
    fontFamily: fonts.sansRegular,
    fontSize: 12,
    lineHeight: 18,
    color: colors.red,
  },
});
