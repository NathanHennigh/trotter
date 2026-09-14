import React from "react";
import {
  ActivityIndicator,
  FlatList,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { BottomNav } from "../components/trotter/TrotterKit";
import { WWEmpty, WWIcon } from "../components/world-window/WorldWindowUI";
import { BoardingPass } from "../components/world-window/trips/BoardingPass";
import { TripAtlas } from "../components/world-window/trips/TripAtlas";
import {
  WalletHeading,
  walletColors,
} from "../components/world-window/trips/WalletCover";
import {
  connectionText,
  orderedSegments,
  tripMapData,
  tripItineraries,
} from "../components/world-window/trips/tripPresentation";
import type {
  BottomNavTab,
  TripSegmentSummary,
  TripSummary,
} from "../data/trotterMock";
import { useTravelTrips } from "../services/travelTrips";
import { colors, fonts, layout } from "../theme/trotterTheme";

export function TripDetailScreen({
  trip,
  active,
  onBack,
  onChange,
  selectedFlightId,
  backLabel = "Back to trips",
}: {
  trip: TripSummary;
  active: BottomNavTab;
  onBack: () => void;
  onChange: (tab: BottomNavTab) => void;
  selectedFlightId?: string;
  backLabel?: string;
}) {
  const insets = useSafeAreaInsets(),
    { loadTripDetail, trips } = useTravelTrips();
  const [hydrated, setHydrated] = React.useState<TripSummary>(),
    [loading, setLoading] = React.useState(false),
    [error, setError] = React.useState<string>(),
    [retry, setRetry] = React.useState(0);
  const list = React.useRef<FlatList<TripSegmentSummary>>(null),
    focused = React.useRef<string>("");
  React.useEffect(() => {
    let live = true;
    setHydrated(undefined);
    setError(undefined);
    focused.current = "";
    if (!trip.backendId) {
      setLoading(false);
      return;
    }
    setLoading(true);
    void loadTripDetail(trip.backendId)
      .then((result) => {
        if (!live) return;
        if (result) setHydrated(result);
        else setError("Flight details could not be loaded.");
      })
      .catch(() => {
        if (live) setError("Flight details could not be loaded.");
      })
      .finally(() => {
        if (live) setLoading(false);
      });
    return () => {
      live = false;
    };
  }, [trip.id, trip.backendId, loadTripDetail, retry]);
  const current = trips.find((entry) => entry.id === trip.id || (trip.backendId != null && entry.backendId === trip.backendId)) || hydrated || trip,
    segments = React.useMemo(
      () => orderedSegments(current.segments),
      [current.segments],
    ),
    map = React.useMemo(() => tripMapData(segments), [segments]),
    groups = React.useMemo(() => tripItineraries(current), [current]);
  const durationNights = Math.max(
    0,
    Math.round(
      (Date.parse(current.endDate) - Date.parse(current.startDate)) / 86400000,
    ),
  );
  const focus = () => {
    if (loading || !selectedFlightId || focused.current === selectedFlightId)
      return;
    const index = segments.findIndex(
      (segment) => segment.id === selectedFlightId,
    );
    if (index >= 0) {
      focused.current = selectedFlightId;
      list.current?.scrollToIndex({
        index,
        animated: true,
        viewPosition: 0.18,
      });
    }
  };
  return (
    <View style={[s.screen, { paddingTop: insets.top }]}>
      <FlatList
        ref={list}
        data={segments}
        keyExtractor={(segment) => segment.id}
        showsVerticalScrollIndicator={false}
        contentContainerStyle={{
          paddingBottom: insets.bottom + layout.bottomNavHeight + 28,
        }}
        onContentSizeChange={focus}
        onScrollToIndexFailed={(info) => {
          list.current?.scrollToOffset({
            offset: info.averageItemLength * info.index,
            animated: true,
          });
          focused.current = "";
        }}
        initialNumToRender={5}
        ListHeaderComponent={
          <>
            <View style={s.detailBar}>
              <Pressable
                accessibilityRole="button"
                accessibilityLabel={backLabel}
                onPress={onBack}
                style={s.backButton}
              >
                <WWIcon name="back" size={20} />
              </Pressable>
              <Text style={s.detailLabel}>Trip details</Text>
            </View>
            <View style={s.wallet}>
              <WalletHeading trip={current} />
              <View pointerEvents="none" style={s.coverLight} />
              <View style={s.mapInsert}>
                <View style={s.mapHeader}>
                  <Text style={s.mapTitle}>Route map</Text>
                  <Text style={s.mapCount}>{current.flightCount} flights</Text>
                </View>
                {map.points.length > 0 ? (
                  <TripAtlas
                    segments={segments}
                    destination={current.airportCode}
                  />
                ) : (
                  !loading && (
                    <Text style={s.note}>
                      A route map will appear when airport coordinates are
                      available.
                    </Text>
                  )
                )}
                {map.points.length > 0 &&
                  map.mappedFlights < segments.length && (
                    <Text style={s.note}>
                      {segments.length - map.mappedFlights}{" "}
                      {segments.length - map.mappedFlights === 1
                        ? "flight is"
                        : "flights are"}{" "}
                      missing map coordinates. All recorded flights are listed
                      below.
                    </Text>
                  )}
              </View>
              {loading && (
                <ActivityIndicator color={colors.blue} style={s.loading} />
              )}
              {error && (
                <Pressable
                  accessibilityRole="button"
                  onPress={() => setRetry((value) => value + 1)}
                  style={s.error}
                >
                  <Text style={s.errorText}>{error} Tap to retry.</Text>
                </Pressable>
              )}
            </View>
          </>
        }
        renderItem={({ item, index }) => {
          const groupIndex = groups.findIndex(
              (group) => group.first.id === item.id,
            ),
            group = groups[groupIndex],
            groupEnds = groups.some(
              (candidate) => candidate.last.id === item.id,
            );
          return (
            <View style={s.documentRail}>
              <View style={[s.documentPaper, !groupEnds && s.continuedPaper]}>
                {group ? (
                  <View
                    style={[
                      s.groupHeader,
                      groupIndex === 0 && s.firstGroupHeader,
                    ]}
                  >
                    <Text style={s.sequence}>
                      {String(groupIndex + 1).padStart(2, "0")}
                    </Text>
                    <View style={{ flex: 1 }}>
                      <Text style={s.groupTitle}>{group.title}</Text>
                      <Text style={s.groupDate}>{group.dates}</Text>
                    </View>
                  </View>
                ) : (
                  index > 0 && (
                    <View style={s.connection}>
                      <View style={s.rule} />
                      <Text style={s.connectionText}>
                        {connectionText(segments[index - 1], item)}
                      </Text>
                    </View>
                  )
                )}
                <BoardingPass
                  segment={item}
                  selected={selectedFlightId === item.id}
                />
              </View>
            </View>
          );
        }}
        ListFooterComponent={
          <View style={[s.documentRail, s.walletEnd]}>
            <View style={[s.documentPaper, s.totals]}>
              {[
                { label: "Flights", value: String(current.flightCount) },
                {
                  label: "Distance",
                  value: `${Math.round(current.miles).toLocaleString()} mi`,
                },
                {
                  label: "Duration",
                  value: Number.isFinite(durationNights)
                    ? `${durationNights} ${durationNights === 1 ? "night" : "nights"}`
                    : "Dates to review",
                },
              ].map((stat) => (
                <View
                  key={stat.label}
                  style={{ flex: stat.label === "Flights" ? 0.65 : 1 }}
                >
                  <Text style={s.totalLabel}>{stat.label}</Text>
                  <Text style={s.totalValue}>{stat.value}</Text>
                </View>
              ))}
            </View>
          </View>
        }
        ListEmptyComponent={
          !loading ? (
            <WWEmpty
              title="No flight details yet"
              body="The trip is preserved. Refresh to load its recorded flights."
            />
          ) : null
        }
      />
      <BottomNav active={active} onChange={onChange} />
    </View>
  );
}
const s = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.paperSoft },
  wallet: {
    marginHorizontal: 0,
    backgroundColor: walletColors.blue,
    borderTopLeftRadius: 5,
    borderTopRightRadius: 5,
    borderColor: "#386680",
    borderWidth: 1,
    borderBottomWidth: 0,
    paddingHorizontal: 6,
  },
  mapInsert: {
    backgroundColor: walletColors.paper,
    paddingHorizontal: 13,
    paddingBottom: 20,
    borderTopColor: "#cad6d4",
    borderTopWidth: 3,
    borderTopLeftRadius: 3,
    borderTopRightRadius: 3,
  },
  mapHeader: {
    minHeight: 48,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 10,
  },
  mapTitle: { fontFamily: fonts.sans, fontSize: 14, color: walletColors.ink },
  mapCount: {
    fontFamily: fonts.sansRegular,
    fontSize: 12,
    color: walletColors.muted,
  },
  note: {
    fontFamily: fonts.sansRegular,
    fontSize: 11,
    lineHeight: 17,
    color: colors.mutedInk,
    paddingTop: 8,
  },
  loading: { padding: 15, backgroundColor: walletColors.paper },
  error: { padding: 12, backgroundColor: walletColors.paper },
  errorText: {
    fontFamily: fonts.sansRegular,
    fontSize: 12,
    lineHeight: 18,
    color: colors.red,
  },
  documentRail: {
    marginHorizontal: 0,
    paddingHorizontal: 6,
    backgroundColor: walletColors.blue,
    borderLeftWidth: 1,
    borderRightWidth: 1,
    borderColor: "#386680",
  },
  documentPaper: {
    paddingHorizontal: 13,
    paddingBottom: 7,
    backgroundColor: walletColors.paper,
  },
  continuedPaper: { paddingBottom: 0 },
  coverLight: {
    position: "absolute",
    top: 0,
    left: 5,
    right: 5,
    height: 1,
    backgroundColor: "#8dabb8",
    opacity: 0.8,
  },
  groupHeader: {
    flexDirection: "row",
    alignItems: "baseline",
    gap: 11,
    paddingTop: 23,
    paddingBottom: 14,
  },
  firstGroupHeader: { borderTopWidth: 1, borderTopColor: walletColors.rule },
  detailBar: {
    height: 54,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: 24,
  },
  backButton: {
    width: 44,
    height: 44,
    alignItems: "center",
    justifyContent: "center",
  },
  detailLabel: {
    fontFamily: fonts.sansRegular,
    fontSize: 12,
    lineHeight: 17,
    letterSpacing: 0.84,
    textTransform: "uppercase",
    color: colors.ink,
  },
  sequence: {
    fontFamily: fonts.mono,
    fontSize: 12,
    color: walletColors.copper,
  },
  groupTitle: {
    fontFamily: fonts.sans,
    fontSize: 14,
    lineHeight: 20,
    color: walletColors.ink,
  },
  groupDate: {
    fontFamily: fonts.sansRegular,
    fontSize: 12,
    lineHeight: 18,
    marginTop: 4,
    color: walletColors.muted,
  },
  connection: {
    flexDirection: "row",
    alignItems: "center",
    gap: 9,
    paddingVertical: 13,
    paddingHorizontal: 10,
  },
  connectionText: {
    fontFamily: fonts.sansRegular,
    fontSize: 12,
    lineHeight: 18,
    color: walletColors.muted,
    flexShrink: 1,
  },
  rule: { height: 20, width: 1, backgroundColor: "#b7c6c0" },
  walletEnd: {
    paddingBottom: 7,
    borderBottomWidth: 1,
    borderBottomLeftRadius: 9,
    borderBottomRightRadius: 9,
  },
  totals: {
    paddingTop: 19,
    paddingBottom: 16,
    flexDirection: "row",
    gap: 8,
    borderBottomLeftRadius: 5,
    borderBottomRightRadius: 5,
  },
  totalLabel: {
    fontFamily: fonts.sansRegular,
    fontSize: 10,
    lineHeight: 15,
    color: walletColors.muted,
    marginBottom: 6,
  },
  totalValue: {
    fontFamily: fonts.mono,
    fontSize: 14,
    lineHeight: 20,
    color: walletColors.ink,
  },
});
