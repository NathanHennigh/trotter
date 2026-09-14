import React from "react";
import {
  ActivityIndicator,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { BottomNav } from "../components/trotter/TrotterKit";
import { WWEmblem, WWIcon } from "../components/world-window/WorldWindowUI";
import { TripAtlas } from "../components/world-window/trips/TripAtlas";
import { flightDate } from "../components/world-window/trips/tripPresentation";
import type { BottomNavTab, TripSegmentSummary } from "../data/trotterMock";
import { useTravelTrips } from "../services/travelTrips";
import { colors, fonts, layout } from "../theme/trotterTheme";

export function ProfileScreen({
  active,
  onChange,
  onOpenStamps,
}: {
  active: BottomNavTab;
  onChange: (tab: BottomNavTab) => void;
  onOpenStamps: () => void;
}) {
  const insets = useSafeAreaInsets();
  const {
    profile,
    trips,
    status,
    error,
    accountEmail,
    lastSyncedAt,
    gmailSyncStatus,
    gmailSyncError,
    lastGmailSyncedAt,
    refresh,
    syncFromGmail,
    signOut,
  } = useTravelTrips();
  const busy = ["loading", "refreshing", "syncing"].includes(status);
  const firstYear = profile.firstFlightDate?.match(/^\d{4}/)?.[0];
  const segments = React.useMemo(
    () => [
      ...new Map(
        trips
          .flatMap((trip) => trip.segments ?? [])
          .map((segment) => [segment.id, segment]),
      ).values(),
    ],
    [trips],
  );
  const airport = React.useMemo(() => frequentAirport(segments), [segments]);
  const latestDate =
    segments
      .map((segment) => segment.depTime)
      .filter(Boolean)
      .sort()
      .slice(-1)[0] ??
    trips
      .map((trip) => trip.startDate)
      .filter(Boolean)
      .sort()
      .slice(-1)[0];
  return (
    <View style={[styles.screen, { paddingTop: insets.top }]}>
      <ScrollView
        showsVerticalScrollIndicator={false}
        contentContainerStyle={[
          styles.content,
          { paddingBottom: insets.bottom + layout.bottomNavHeight + 28 },
        ]}
        refreshControl={
          <RefreshControl
            refreshing={status === "refreshing"}
            onRefresh={() => void refresh()}
            tintColor={colors.blue}
          />
        }
      >
        <View style={styles.signature}>
          <View style={styles.brand} accessibilityLabel="Trotter">
            <WWEmblem size={18.5} color={colors.blue} />
            <Text style={styles.wordmark}>TROTTER</Text>
          </View>
          <Text style={styles.signatureLabel}>Profile</Text>
        </View>
        <View style={styles.owner}>
          <Text accessibilityRole="header" style={styles.name}>
            {profile.name}
          </Text>
          {firstYear ? (
            <View style={styles.ownerDetails}>
              <Text style={styles.since}>
                First recorded flight in {firstYear}
              </Text>
            </View>
          ) : null}
        </View>
        <View style={styles.source}>
          <View style={styles.sourceHeading}>
            <Text style={styles.sectionTitle}>Flight confirmations</Text>
            <View style={styles.sourceStatus}>
              <View style={styles.statusDot} />
              <Text style={styles.statusText}>
                {gmailSyncStatus === "syncing" ? "Checking" : gmailSyncStatus === "synced" ? "Synced" : gmailSyncStatus === "error" ? "Needs attention" : "Not checked"}
              </Text>
            </View>
          </View>
          <View style={styles.sourceProvider}>
            <WWIcon name="sync" size={23} color={colors.blue} />
            <View style={styles.sourceCopy}>
              <Text style={styles.providerName}>Gmail</Text>
              <Text style={styles.secondary}>
                {profile.flights.toLocaleString()} saved{" "}
                {profile.flights === 1 ? "flight" : "flights"}
              </Text>
            </View>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Check Gmail for new flights"
              accessibilityState={{
                disabled: busy,
                busy: status === "syncing",
              }}
              disabled={busy}
              onPress={() => void syncFromGmail()}
              style={({ pressed }) => [
                styles.syncButton,
                busy && styles.disabled,
                pressed && styles.pressed,
              ]}
            >
              {status === "syncing" ? (
                <ActivityIndicator color={colors.blue} size="small" />
              ) : (
                <WWIcon name="sync" size={19} color={colors.blue} />
              )}
              <Text style={styles.textButtonLabel}>Check mail</Text>
            </Pressable>
          </View>
          <Text style={styles.sourceNote} accessibilityLiveRegion="polite">
            {status === "syncing"
              ? "Finding flight confirmations. Your import continues if you close Trotter."
              : lastGmailSyncedAt
                ? `Last successful scan ${formatUpdated(lastGmailSyncedAt)}`
                : "Check Gmail to add flight confirmations to your archive."}
          </Text>
          {gmailSyncError ? (
            <Text
              style={styles.error}
              accessibilityRole="alert"
              accessibilityLiveRegion="polite"
            >
              {gmailSyncError}
            </Text>
          ) : null}
        </View>
        {airport ? (
          <View style={styles.routeSheet}>
            <View style={styles.routeSheetHeading}>
              <Text style={styles.routeSheetLabel}>Most visited airport</Text>
              <Text style={styles.routeSheetLabel}>
                {airport.routes} {airport.routes === 1 ? "route" : "routes"}
              </Text>
            </View>
            <TripAtlas
              variant="profile"
              segments={airport.segments}
              destination={airport.code}
              backgroundColor="#b5ced1"
            />
            <View style={styles.airport}>
              <Text style={styles.airportCode}>{airport.code}</Text>
              <View style={styles.airportCopy}>
                {airport.point?.city ? (
                  <Text style={styles.airportCity}>{airport.point.city}</Text>
                ) : null}
                <Text style={styles.airportFlights}>
                  {airport.segments.length} recorded{" "}
                  {airport.segments.length === 1 ? "flight" : "flights"}
                </Text>
              </View>
            </View>
            {airport.point ? (
              <Text style={styles.coordinates}>
                {coordinates(airport.point.lat, airport.point.lon)}
              </Text>
            ) : null}
          </View>
        ) : null}
        <View style={styles.history}>
          <Text style={styles.secondary}>Latest recorded flight</Text>
          <Text style={styles.historyDate}>
            {latestDate ? flightDate(latestDate) : "No flights yet"}
          </Text>
        </View>
        <ArchiveRow
          label="Trip archive"
          value={`${trips.length.toLocaleString()} ${trips.length === 1 ? "trip" : "trips"}`}
          onPress={() => onChange("trips")}
        />
        <ArchiveRow
          label="Country stamps"
          value={`${profile.countries.toLocaleString()} ${profile.countries === 1 ? "country" : "countries"}`}
          onPress={onOpenStamps}
        />
        <View style={styles.account}>
          <Text style={styles.sectionTitle}>Google account</Text>
          <Text style={styles.accountEmail} selectable>
            {accountEmail}
          </Text>
          {lastSyncedAt ? <Text style={styles.secondary}>Archive refreshed {formatUpdated(lastSyncedAt)}</Text> : null}
          {error && error !== gmailSyncError ? <Text style={styles.error} accessibilityRole="alert">{error}</Text> : null}
          <View style={styles.accountActions}>
            <Pressable
              accessibilityRole="button"
              accessibilityState={{
                disabled: busy,
                busy: status === "refreshing",
              }}
              disabled={busy}
              onPress={() => void refresh()}
              style={({ pressed }) => [
                styles.textButton,
                busy && styles.disabled,
                pressed && styles.pressed,
              ]}
            >
              {status === "refreshing" ? (
                <ActivityIndicator color={colors.blue} size="small" />
              ) : (
                <WWIcon name="sync" size={16} color={colors.blue} />
              )}
              <Text style={styles.textButtonLabel}>
                {status === "refreshing" ? "Refreshing…" : "Refresh archive"}
              </Text>
            </Pressable>
            <Pressable
              accessibilityRole="button"
              onPress={() => void signOut()}
              style={({ pressed }) => [
                styles.textButton,
                pressed && styles.pressed,
              ]}
            >
              <Text style={styles.textButtonLabel}>Sign out</Text>
              <WWIcon name="logout" size={16} color={colors.blue} />
            </Pressable>
          </View>
        </View>
      </ScrollView>
      <BottomNav active={active} onChange={onChange} />
    </View>
  );
}
function ArchiveRow({
  label,
  value,
  onPress,
}: {
  label: string;
  value: string;
  onPress: () => void;
}) {
  return (
    <Pressable
      accessibilityRole="button"
      onPress={onPress}
      style={({ pressed }) => [styles.archiveRow, pressed && styles.pressed]}
    >
      <Text style={styles.archiveLabel}>{label}</Text>
      <View style={styles.archiveValue}>
        <Text style={styles.archiveLabel}>{value}</Text>
        <WWIcon name="arrow" size={17} color={colors.blue} />
      </View>
    </Pressable>
  );
}
// An observed airport is not a user-declared home. Keep that distinction in the label.
function frequentAirport(segments: TripSegmentSummary[]) {
  const counts = new Map<string, number>();
  for (const segment of segments) {
    for (const code of new Set(
      [segment.depAirport, segment.arrAirport].filter(Boolean),
    ))
      counts.set(code, (counts.get(code) ?? 0) + 1);
  }
  const code = [...counts].sort(
    (a, b) => b[1] - a[1] || a[0].localeCompare(b[0]),
  )[0]?.[0];
  if (!code) return undefined;
  const flights = segments.filter(
    (segment) => segment.depAirport === code || segment.arrAirport === code,
  );
  const point = flights
    .flatMap((segment) => [segment.depPoint, segment.arrPoint])
    .find(
      (point) =>
        point?.code === code &&
        Number.isFinite(point.lat) &&
        Number.isFinite(point.lon),
    );
  return {
    code,
    point,
    segments: flights,
    routes: new Set(
      flights
        .map((segment) =>
          segment.depAirport === code ? segment.arrAirport : segment.depAirport,
        )
        .filter(Boolean),
    ).size,
  };
}
function coordinates(lat: number, lon: number) {
  return `${Math.abs(lat).toFixed(2)}° ${lat < 0 ? "S" : "N"} / ${Math.abs(lon).toFixed(2)}° ${lon < 0 ? "W" : "E"}`;
}
function formatUpdated(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "recently"
    : date.toLocaleString(undefined, {
        month: "short",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit",
      });
}
// Profile-specific geometry follows identity.css and approved window-polish.css.
const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.paperSoft },
  content: {
    paddingHorizontal: 24,
    paddingTop: 25,
    maxWidth: 640,
    width: "100%",
    alignSelf: "center",
  },
  signature: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 12,
  },
  brand: { flexDirection: "row", alignItems: "center", minHeight: 25, gap: 7 },
  wordmark: {
    fontFamily: fonts.sansSemi,
    fontSize: 15,
    color: colors.blue,
    letterSpacing: 1.8,
  },
  signatureLabel: {
    fontFamily: fonts.sansRegular,
    fontSize: 12,
    color: colors.blue,
  },
  owner: { paddingTop: 28, paddingBottom: 18 },
  name: {
    fontFamily: fonts.display,
    fontSize: 38,
    lineHeight: 42,
    letterSpacing: -0.7,
    color: colors.blue,
  },
  ownerDetails: { minHeight: 44, justifyContent: "center", marginTop: 8 },
  since: {
    fontFamily: fonts.sansRegular,
    fontSize: 13,
    lineHeight: 20,
    color: colors.mutedInk,
  },
  routeSheet: {
    borderWidth: 1,
    borderColor: colors.paperBorder,
    backgroundColor: "#F4F5EB",
    marginBottom: 25,
    overflow: "hidden",
  },
  routeSheetHeading: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 10,
    paddingHorizontal: 13,
    paddingVertical: 11,
    borderBottomWidth: 1,
    borderColor: colors.paperBorder,
    flexWrap: "wrap",
  },
  routeSheetLabel: {
    fontFamily: fonts.mono,
    fontSize: 12,
    lineHeight: 18,
    color: colors.blue,
  },
  airport: {
    flexDirection: "row",
    alignItems: "center",
    gap: 14,
    paddingHorizontal: 13,
    paddingTop: 15,
    paddingBottom: 10,
  },
  airportCode: {
    fontFamily: fonts.mono,
    fontSize: 36,
    lineHeight: 42,
    letterSpacing: -1.2,
    color: colors.blue,
  },
  airportCopy: { flex: 1, minWidth: 0 },
  airportCity: {
    fontFamily: fonts.display,
    fontSize: 24,
    lineHeight: 27,
    color: colors.blue,
  },
  airportFlights: {
    fontFamily: fonts.sansRegular,
    fontSize: 13,
    lineHeight: 20,
    color: colors.mutedInk,
    marginTop: 6,
  },
  coordinates: {
    fontFamily: fonts.mono,
    fontSize: 12,
    lineHeight: 18,
    paddingHorizontal: 13,
    paddingBottom: 13,
    color: colors.mutedInk,
  },
  source: {
    borderTopWidth: 1,
    borderColor: colors.paperBorder,
    paddingTop: 20,
    paddingBottom: 16,
  },
  sourceHeading: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 12,
    flexWrap: "wrap",
  },
  sectionTitle: {
    fontFamily: fonts.sans,
    fontSize: 14,
    lineHeight: 20,
    color: colors.blue,
  },
  sourceStatus: { flexDirection: "row", alignItems: "center", gap: 5 },
  statusDot: {
    width: 5,
    height: 5,
    borderRadius: 3,
    backgroundColor: colors.blue,
  },
  statusText: {
    fontFamily: fonts.sansRegular,
    fontSize: 12,
    color: colors.blue,
  },
  sourceProvider: {
    flexDirection: "row",
    alignItems: "center",
    gap: 13,
    paddingTop: 19,
  },
  sourceCopy: { flex: 1, minWidth: 0, gap: 5 },
  providerName: {
    fontFamily: fonts.display,
    fontSize: 24,
    lineHeight: 29,
    color: colors.blue,
  },
  secondary: {
    fontFamily: fonts.sansRegular,
    fontSize: 13,
    lineHeight: 20,
    color: colors.mutedInk,
  },
  syncButton: {
    minHeight: 44,
    paddingHorizontal: 10,
    paddingVertical: 8,
    flexDirection: "row",
    gap: 7,
    borderRadius: 3,
    borderWidth: 1,
    borderColor: colors.paperBorder,
    backgroundColor: "#EDF0E7",
    alignItems: "center",
    justifyContent: "center",
  },
  sourceNote: {
    fontFamily: fonts.sansRegular,
    fontSize: 12,
    lineHeight: 19,
    color: colors.mutedInk,
    backgroundColor: "#EDF0E7",
    padding: 15,
    marginTop: 14,
  },
  history: {
    borderTopWidth: 1,
    borderColor: colors.paperBorder,
    flexDirection: "row",
    justifyContent: "space-between",
    gap: 12,
    paddingVertical: 18,
    flexWrap: "wrap",
  },
  historyDate: {
    fontFamily: fonts.sansRegular,
    fontSize: 13,
    lineHeight: 20,
    color: colors.blue,
    fontVariant: ["tabular-nums"],
  },
  archiveRow: {
    borderTopWidth: 1,
    borderColor: colors.paperBorder,
    minHeight: 59,
    paddingVertical: 16,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 13,
    flexWrap: "wrap",
  },
  archiveLabel: {
    fontFamily: fonts.sansRegular,
    fontSize: 14,
    lineHeight: 21,
    color: colors.blue,
  },
  archiveValue: { flexDirection: "row", alignItems: "center", gap: 11 },
  account: {
    borderTopWidth: 1,
    borderColor: colors.paperBorder,
    paddingTop: 20,
    paddingBottom: 4,
  },
  accountEmail: {
    fontFamily: fonts.sansRegular,
    fontSize: 13,
    lineHeight: 20,
    color: colors.mutedInk,
    marginTop: 7,
  },
  accountActions: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 16,
    marginTop: 8,
    flexWrap: "wrap",
  },
  textButton: {
    minHeight: 44,
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
  },
  textButtonLabel: {
    fontFamily: fonts.sansRegular,
    fontSize: 13,
    lineHeight: 20,
    color: colors.blue,
  },
  error: {
    fontFamily: fonts.sansRegular,
    color: colors.redDeep,
    fontSize: 12,
    lineHeight: 18,
    marginTop: 14,
  },
  pressed: { opacity: 0.7, transform: [{ scale: 0.985 }] },
  disabled: { opacity: 0.5 },
});
