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
import type { BottomNavTab, TripSummary } from "../data/trotterMock";
import { useTravelTrips } from "../services/travelTrips";
import { colors, fonts, layout } from "../theme/trotterTheme";

export function TripsListScreen({
  active,
  onChange,
  onOpenTrip,
  resetEpoch = 0,
  liftedTripId,
}: {
  active: BottomNavTab;
  onChange: (tab: BottomNavTab) => void;
  onOpenTrip?: (trip: TripSummary, flightId?: string, origin?: WalletOrigin) => void;
  resetEpoch?: number;
  liftedTripId?: string;
}) {
  const insets = useSafeAreaInsets(),
    { trips, status, error, refresh } = useTravelTrips();
  const { width, fontScale } = useWindowDimensions();
  const stackCount = width <= 360 && fontScale >= 1.35;
  const [query, setQuery] = React.useState("");
  const list = React.useRef<FlatList<TripSummary>>(null);
  React.useEffect(() => {
    setQuery("");
    list.current?.scrollToOffset({ offset: 0, animated: false });
  }, [resetEpoch]);
  const visible = React.useMemo(() => trips.filter(trip => matchesTrip(trip, query, false, 0)), [trips, query]);
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
              action={!stackCount ? <Text style={s.headerCount}>{query ? `${visible.length} / ${trips.length}` : trips.length}</Text> : undefined}
            />
            {stackCount ? <Text style={s.stackedCount}>{visible.length}{query ? ` of ${trips.length}` : ""} {(query ? trips.length : visible.length) === 1 ? "trip" : "trips"}</Text> : null}
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
              visible[index - 1].startDate.slice(0, 4) !==
                item.startDate.slice(0, 4)) && (
              <View style={s.yearDivider}>
                <Text style={s.year}>{item.startDate.slice(0, 4)}</Text>
                <View style={s.yearRule} />
              </View>
            )}
            <View style={liftedTripId === item.id ? { opacity: 0 } : undefined}>
            <WalletCover
              trip={item}
              onPress={(origin) => onOpenTrip?.(item, undefined, origin)}
            />
            </View>
          </View>
        )}
        ListEmptyComponent={
          <WWEmpty
            title={
              loading
                ? "Loading your trips…"
                : query
                  ? "No matching trips"
                  : "Your trips will live here"
            }
            body={
              loading
                ? undefined
                : query
                  ? "Try another search or view all trips."
                  : "Import your flight confirmations from Profile."
            }
            action={!loading ? <WWButton label={error ? "Retry" : query ? "Show all trips" : "Open Profile"} onPress={() => { if (error) void refresh(); else if (query) setQuery(""); else onChange("profile"); }} secondary /> : undefined}
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
