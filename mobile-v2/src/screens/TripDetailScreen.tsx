import React from "react";
import {
  ActivityIndicator,
  FlatList,
  StyleSheet,
  Text,
  useWindowDimensions,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { BottomNav } from "../components/trotter/TrotterKit";
import { WWButton, WWEmpty, WWIcon } from "../components/world-window/WorldWindowUI";
import { PressFeedback } from "../components/world-window/motion";
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
  popup = false,
  deferUpdates = false,
}: {
  trip: TripSummary;
  active: BottomNavTab;
  onBack: () => void;
  onChange: (tab: BottomNavTab) => void;
  selectedFlightId?: string;
  backLabel?: string;
  popup?: boolean;
  deferUpdates?: boolean;
}) {
  const insets = useSafeAreaInsets(),
    { loadTripDetail, trips, refresh } = useTravelTrips();
  const { width, fontScale } = useWindowDimensions();
  const [contentWidth, setContentWidth] = React.useState(popup ? width - 40 : width);
  const stackTotals = contentWidth <= 360 && fontScale >= 1.35;
  const [hydrated, setHydrated] = React.useState<TripSummary>(),
    [loading, setLoading] = React.useState(false),
    [error, setError] = React.useState<string>(),
    [retry, setRetry] = React.useState(0);
  const list = React.useRef<FlatList<TripSegmentSummary>>(null),
    focused = React.useRef<string>("");
  React.useEffect(() => {
    // Keep network responses and the map's refreshed SVG tree out of the wallet motion.
    if (deferUpdates) return;
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
  }, [trip.id, trip.backendId, loadTripDetail, retry, deferUpdates]);
  const latest = trips.find((entry) => entry.id === trip.id || (trip.backendId != null && entry.backendId === trip.backendId)) || hydrated || trip;
  const displayed = React.useRef(latest);
  if (!deferUpdates || displayed.current.id !== trip.id) displayed.current = latest;
  const current = displayed.current,
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
    if (!selectedFlightId || focused.current === selectedFlightId)
      return;
    const index = segments.findIndex(
      (segment) => segment.id === selectedFlightId,
    );
    if (index >= 0) {
      focused.current = selectedFlightId;
      list.current?.scrollToIndex({
        index,
        // Position the requested flight before entry, without a second moving axis.
        animated: false,
        viewPosition: 0,
        viewOffset: 12,
      });
    }
  };
  const retryDetails = () => {
    if (loading) return;
    if (trip.backendId) setRetry(value => value + 1);
    else {
      setLoading(true);
      void refresh().finally(() => setLoading(false));
    }
  };
  return (
    <View onLayout={event => setContentWidth(event.nativeEvent.layout.width)}
      style={[s.screen, popup && s.popup, { paddingTop: popup ? 0 : insets.top }]}>
      {!popup && <View style={s.detailBar}>
        <PressFeedback accessibilityRole="button" accessibilityLabel={backLabel} onPress={onBack} style={s.backButton}>
          <WWIcon name="back" size={19} />
          <Text numberOfLines={1} style={s.backLabel}>{backLabel.replace(/^Back to /i, "")}</Text>
        </PressFeedback>
        <View style={s.detailStatus}>
          <ActivityIndicator size="small" color={colors.blue} animating={loading}
            style={[s.detailLoading, { opacity: loading ? 1 : 0 }]} />
          <Text style={s.detailLabel}>Itinerary</Text>
        </View>
      </View>}
      <FlatList
        ref={list}
        data={segments}
        keyExtractor={(segment) => segment.id}
        showsVerticalScrollIndicator={false}
        contentContainerStyle={{
          paddingBottom: popup ? 0 : insets.bottom + layout.bottomNavHeight + 28,
        }}
        onContentSizeChange={focus}
        onScrollToIndexFailed={(info) => {
          list.current?.scrollToOffset({
            offset: info.averageItemLength * info.index,
            animated: false,
          });
          focused.current = "";
        }}
        initialNumToRender={5}
        ListHeaderComponent={
          <>
            <View style={s.wallet}>
              <WalletHeading trip={current} compact={popup} availableWidth={contentWidth} />
              <View pointerEvents="none" style={s.coverLight} />
              <View style={s.mapInsert}>
                <View style={s.mapHeader}>
                  <Text style={s.mapTitle}>Route map</Text>
                  <View style={s.detailStatus}>
                    {popup && <ActivityIndicator size="small" color={colors.blue} animating={loading}
                      style={[s.detailLoading, { opacity: loading ? 1 : 0 }]} />}
                    <Text style={s.mapCount}>{segments.length} {segments.length === 1 ? "flight" : "flights"}</Text>
                  </View>
                </View>
                {map.points.length > 0 ? (
                  <TripAtlas
                    segments={segments}
                    destination={current.airportCode}
                  />
                ) : (
                  (!loading || segments.length > 0) && (
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
              <Text style={s.scheduleNote}>Dates and times as recorded for each airport.</Text>
              {error && segments.length > 0 && (
                <PressFeedback
                  accessibilityRole="button"
                  onPress={retryDetails}
                  style={s.error}
                >
                  <Text style={s.errorText}>{error} Tap to retry.</Text>
                </PressFeedback>
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
                      stackTotals && s.stackedGroupHeader,
                    ]}
                  >
                    <Text style={s.sequence}>
                      {String(groupIndex + 1).padStart(2, "0")}
                    </Text>
                    <View style={{ flex: 1 }}>
                      <Text style={[s.groupTitle, stackTotals && s.largeGroupTitle]}>{group.title}</Text>
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
                  availableWidth={contentWidth}
                />
              </View>
            </View>
          );
        }}
        ListFooterComponent={
          <View style={[s.documentRail, s.walletEnd]}>
            <View style={[s.documentPaper, s.totals, stackTotals && s.stackedTotals]}>
              {[
                { label: "Flights", value: String(segments.length) },
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
                  style={stackTotals ? s.totalRow : { flex: stat.label === "Flights" ? 0.65 : 1 }}
                >
                  <Text style={s.totalLabel}>{stat.label}</Text>
                  <Text style={[s.totalValue, stackTotals && s.stackedValue]}>{stat.value}</Text>
                </View>
              ))}
            </View>
          </View>
        }
        ListEmptyComponent={
          !loading ? (
            <WWEmpty
              title="No flight details yet"
              body={error || "The trip is preserved. Retry to load its recorded flights."}
              action={<WWButton label="Retry flight details" onPress={retryDetails} secondary />}
            />
          ) : null
        }
      />
      {!popup && <BottomNav active={active} onChange={onChange} />}
    </View>
  );
}
const s = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.paperSoft },
  popup: { backgroundColor: walletColors.blue },
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
  detailStatus: { flexDirection: "row", alignItems: "center", gap: 8 },
  detailLoading: { width: 18, height: 18 },
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
  stackedGroupHeader: { flexDirection: "column", alignItems: "stretch", gap: 5 },
  detailBar: {
    minHeight: 52,
    flexShrink: 0,
    backgroundColor: colors.paperSoft,
    borderBottomWidth: 1,
    borderBottomColor: walletColors.rule,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: 18,
    gap: 12,
  },
  backButton: {
    flex: 1,
    minHeight: 44,
    flexDirection: "row",
    gap: 9,
    alignItems: "center",
  },
  backLabel: { flexShrink: 1, fontFamily: fonts.sansRegular, fontSize: 13, lineHeight: 19, color: colors.ink },
  scheduleNote: { fontFamily: fonts.sansRegular, fontSize: 11, lineHeight: 17, color: walletColors.muted, backgroundColor: walletColors.paper, paddingHorizontal: 13, paddingBottom: 13 },
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
    fontFamily: fonts.display,
    fontSize: 23,
    lineHeight: 28,
    color: walletColors.ink,
  },
  largeGroupTitle: { fontSize: 21, lineHeight: 26 },
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
  stackedTotals: { flexDirection: "column", gap: 14 },
  totalRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "baseline", gap: 12 },
  stackedValue: { flexShrink: 1, textAlign: "right" },
  totalValue: {
    fontFamily: fonts.mono,
    fontSize: 14,
    lineHeight: 20,
    color: walletColors.ink,
  },
});
