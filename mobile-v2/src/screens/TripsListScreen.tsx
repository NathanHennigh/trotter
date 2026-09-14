import React from "react";
import {
  FlatList,
  Pressable,
  RefreshControl,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { BottomNav } from "../components/trotter/TrotterKit";
import {
  WWEmpty,
  WWHeader,
  WWIcon,
} from "../components/world-window/WorldWindowUI";
import { WalletCover } from "../components/world-window/trips/WalletCover";
import { matchesTrip } from "../components/world-window/trips/tripPresentation";
import type { BottomNavTab, TripSummary } from "../data/trotterMock";
import { useTravelTrips } from "../services/travelTrips";
import { colors, fonts, layout } from "../theme/trotterTheme";

export function TripsListScreen({
  active,
  onChange,
  onOpenTrip,
}: {
  active: BottomNavTab;
  onChange: (tab: BottomNavTab) => void;
  onOpenTrip?: (trip: TripSummary, flightId?: string) => void;
}) {
  const insets = useSafeAreaInsets(),
    { trips, status, error, refresh } = useTravelTrips();
  const [query, setQuery] = React.useState(""),
    [yearOnly, setYearOnly] = React.useState(false);
  const year = new Date().getFullYear();
  const visible = React.useMemo(
    () => trips.filter((trip) => matchesTrip(trip, query, yearOnly, year)),
    [trips, query, yearOnly, year],
  );
  const loading =
    status === "loading" || status === "refreshing" || status === "syncing";
  return (
    <View style={s.screen}>
      <FlatList
        data={visible}
        keyExtractor={(trip) => trip.id}
        keyboardShouldPersistTaps="handled"
        keyboardDismissMode="on-drag"
        showsVerticalScrollIndicator={false}
        contentContainerStyle={{
          paddingTop: insets.top,
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
              action={<Text style={s.headerCount}>{trips.length}</Text>}
            />
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
                <Pressable
                  accessibilityLabel="Clear search"
                  onPress={() => setQuery("")}
                  style={s.icon}
                >
                  <WWIcon name="close" size={17} />
                </Pressable>
              )}
            </View>
            <View style={s.toolbar}>
              <View style={s.tabs}>
                {[
                  { label: "All trips", value: false, count: trips.length },
                  {
                    label: "This year",
                    value: true,
                    count: trips.filter((t) =>
                      t.startDate.startsWith(String(year)),
                    ).length,
                  },
                ].map(({ label, value, count }) => (
                  <Pressable
                    key={label}
                    accessibilityRole="tab"
                    accessibilityState={{ selected: yearOnly === value }}
                    onPress={() => setYearOnly(value)}
                    style={[s.tab, yearOnly === value && s.activeTab]}
                  >
                    <Text
                      style={[s.tabText, yearOnly === value && s.activeText]}
                    >
                      {label} <Text style={s.tabCount}>{count}</Text>
                    </Text>
                  </Pressable>
                ))}
              </View>
            </View>
            {error && (
              <Pressable onPress={() => void refresh()} style={s.error}>
                <Text style={s.errorText}>{error} · Tap to retry</Text>
              </Pressable>
            )}
          </>
        }
        renderItem={({ item, index }) => (
          <View>
            {(index === 0 ||
              visible[index - 1].startDate.slice(0, 4) !==
                item.startDate.slice(0, 4)) && (
              <View style={s.yearDivider}>
                <Text style={s.year}>{item.startDate.slice(0, 4)}</Text>
                <View style={s.yearRule} />
              </View>
            )}
            <WalletCover
              trip={item}
              onPress={(flightId) => onOpenTrip?.(item, flightId)}
            />
          </View>
        )}
        ListEmptyComponent={
          <WWEmpty
            title={
              loading
                ? "Loading your trips…"
                : query || yearOnly
                  ? "No matching trips"
                  : "Your trips will live here"
            }
            body={
              loading
                ? undefined
                : query || yearOnly
                  ? "Try another search or view all trips."
                  : "Connect your flight archive from Profile to bring your journeys together."
            }
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
