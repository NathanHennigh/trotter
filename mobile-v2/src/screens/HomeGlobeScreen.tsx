import React, { useMemo, useState } from "react";
import {
  ActivityIndicator,
  Modal,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { BottomNav } from "../components/trotter/TrotterKit";
import { WorldWindowGlobe } from "../components/world-window/WorldWindowGlobe";
import {
  WWButton,
  WWEmblem,
  WWIcon,
} from "../components/world-window/WorldWindowUI";
import {
  flightCountryKey,
  type GeoCountry,
} from "../components/world-window/globe-geography";
import { buildPassportArrivals } from "../components/world-window/passport/passport-arrivals";
import type { BottomNavTab, TripSummary } from "../data/trotterMock";
import type { FlightRoute } from "../data/demoTravel";
import { useTravelTrips } from "../services/travelTrips";
import { colors, fonts, layout } from "../theme/trotterTheme";

type Props = {
  active: BottomNavTab;
  onChange: (tab: BottomNavTab) => void;
  onOpenTrip?: (trip: TripSummary, flightId?: string) => void;
  onOpenCountry?: (code: string) => void;
  onOpenCollection?: (kind: "countries" | "airports") => void;
  filterYear?: string;
  onFilterYear?: (year: string) => void;
};
export function HomeGlobeScreen({
  active,
  onChange,
  onOpenTrip,
  onOpenCountry,
  onOpenCollection,
  filterYear,
  onFilterYear,
}: Props) {
  const insets = useSafeAreaInsets();
  const { trips, status, error, syncFromGmail } = useTravelTrips();
  const [localYear, setLocalYear] = useState("All years");
  const year = filterYear ?? localYear;
  const setYear = (next: string) => {
    setLocalYear(next);
    onFilterYear?.(next);
  };
  const [yearOpen, setYearOpen] = useState(false);
  const [mapStyle, setMapStyle] = useState<"classic" | "nasa">("classic");
  const [selected, setSelected] = useState<FlightRoute | null>(null);
  const [country, setCountry] = useState<GeoCountry | null>(null);
  const clear = () => {
    setSelected(null);
    setCountry(null);
  };
  const years = useMemo(
    () =>
      [
        ...new Set(
          trips
            .flatMap((t) =>
              (t.segments ?? []).map((s) => s.depTime.slice(0, 4)),
            )
            .filter((y) => /^\d{4}$/.test(y)),
        ),
      ]
        .sort()
        .reverse(),
    [trips],
  );
  const routes = useMemo(
    () =>
      trips.flatMap((trip) =>
        (trip.segments ?? []).flatMap((segment) => {
          if (
            !segment.depPoint ||
            !segment.arrPoint ||
            (year !== "All years" && !segment.depTime.startsWith(year))
          )
            return [];
          return [
            {
              id: segment.id,
              from: segment.depPoint,
              to: segment.arrPoint,
              tripId: trip.backendId,
              tripTitle: trip.title,
              depTime: segment.depTime,
              arrTime: segment.arrTime,
              airline: segment.airline,
              flightNumber: segment.flightNumber,
              distanceKm: segment.distanceMiles
                ? segment.distanceMiles / 0.621371
                : undefined,
            } satisfies FlightRoute,
          ];
        }),
      ),
    [trips, year],
  );
  const ports = useMemo(
    () => [
      ...new Map(
        routes.flatMap((r) => [
          [r.from.code, r.from] as const,
          [r.to.code, r.to] as const,
        ]),
      ).values(),
    ],
    [routes],
  );
  const visited = useMemo(() => {
    const shown =
      year === "All years"
        ? trips
        : trips
            .filter((t) => t.segments?.some((s) => s.depTime.startsWith(year)))
            .map((t) => ({
              ...t,
              segments: t.segments?.filter((s) => s.depTime.startsWith(year)),
            }));
    return [
      ...new Set(
        buildPassportArrivals(shown)
          .map((a) =>
            flightCountryKey(a.country, a.travelCountryKey, a.airportCode),
          )
          .filter((code): code is string => Boolean(code)),
      ),
    ];
  }, [trips, year]);
  const flightCount = useMemo(
    () =>
      trips
        .flatMap((t) => t.segments ?? [])
        .filter((s) => year === "All years" || s.depTime.startsWith(year))
        .length,
    [trips, year],
  );
  const selectedTrip = selected
    ? trips.find((t) => t.segments?.some((s) => s.id === selected.id))
    : null;
  const openTrip = () => {
    if (selectedTrip && onOpenTrip) onOpenTrip(selectedTrip, selected?.id);
    else onChange("trips");
    clear();
  };
  const syncing = status === "syncing";
  const busy = syncing || status === "loading";
  return (
    <View style={styles.screen}>
      <WorldWindowGlobe
        routes={routes}
        active={active === "globe"}
        mapStyle={mapStyle}
        cycle={false}
        visited={visited}
        selectedRouteId={selected?.id}
        selectedCountryCode={country?.code}
        onRoute={setSelected}
        onCountry={setCountry}
        onClear={clear}
      />
      <View
        pointerEvents="box-none"
        style={[styles.top, { top: insets.top + 18 }]}
      >
        <View style={styles.controls}>
          <View pointerEvents="none" style={styles.brand}>
            <WWEmblem size={33} />
          </View>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Filter flights by year"
            onPress={() => setYearOpen(true)}
            style={({ pressed }) => [styles.year, pressed && styles.pressed]}
          >
            <Text style={styles.yearText} numberOfLines={1}>{year}</Text>
            <WWIcon name="down" size={15} />
          </Pressable>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel={
                mapStyle === "classic"
                  ? "Switch to NASA imagery"
                  : "Switch to classic globe"
              }
              accessibilityState={{ selected: mapStyle === "nasa" }}
              onPress={() =>
                setMapStyle((v) => (v === "classic" ? "nasa" : "classic"))
              }
              style={({ pressed }) => [
                styles.iconButton,
                styles.textureButton,
                mapStyle === "nasa" && styles.chosen,
                pressed && styles.pressed,
              ]}
            >
              <WWIcon name="globe" size={21} />
            </Pressable>
        </View>
        {!trips.length && !busy ? (
          <View style={styles.import}>
            <Text style={styles.importTitle}>Add your flight history</Text>
            <Text style={styles.body}>
              Find flight confirmations in your connected Gmail account.
            </Text>
            <WWButton label="Import flights" onPress={syncFromGmail} />
            {error ? <Text style={styles.error}>{error}</Text> : null}
          </View>
        ) : null}
        {busy ? (
          <View style={styles.loading}>
            <ActivityIndicator color={colors.blue} size="small" />
            <Text style={styles.body}>
              {syncing ? "Importing your flights…" : "Loading your flights…"}
            </Text>
          </View>
        ) : null}
      </View>
      <View
        pointerEvents="box-none"
        style={[
          styles.bottom,
          { bottom: insets.bottom + layout.bottomNavHeight + 12 },
        ]}
      >
        {selected ? (
          <View style={styles.ticket}>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel={`View trip for ${selected.from.code} to ${selected.to.code}`}
              onPress={openTrip}
              style={({ pressed }) => [
                styles.ticketBody,
                pressed && styles.pressed,
              ]}
            >
              <View style={styles.ticketHeading}>
                <Text style={styles.ticketAirline} numberOfLines={1}>
                  {selected.airline || "Flight"}
                </Text>
                {selected.flightNumber ? (
                  <Text style={styles.flightNumber}>
                    {selected.flightNumber}
                  </Text>
                ) : null}
              </View>
              <View style={styles.route}>
                <View style={styles.endpoint}>
                  <Text style={styles.airport}>{selected.from.code}</Text>
                  <Text style={styles.city} numberOfLines={1}>
                    {selected.from.city}
                  </Text>
                </View>
                <WWIcon name="plane" size={25} color={colors.blue} />
                <View style={[styles.endpoint, { alignItems: "flex-end" }]}>
                  <Text style={styles.airport}>{selected.to.code}</Text>
                  <Text style={styles.city} numberOfLines={1}>
                    {selected.to.city}
                  </Text>
                </View>
              </View>
              <View style={styles.tear}>
                <Text style={styles.ticketDate}>
                  {selected.depTime
                    ? new Date(selected.depTime).toLocaleDateString(undefined, {
                        month: "short",
                        day: "numeric",
                        year: "numeric",
                      })
                    : ""}
                </Text>
                <View style={styles.ticketLink}>
                  <Text style={styles.link}>View trip</Text>
                  <WWIcon name="arrow" size={16} />
                </View>
              </View>
            </Pressable>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Dismiss flight"
              onPress={clear}
              style={styles.dismiss}
            >
              <WWIcon name="close" size={16} />
            </Pressable>
          </View>
        ) : country ? (
          <View style={styles.countryCard}>
            <Text style={styles.countryTitle}>{country.name}</Text>
            <Text style={styles.body}>
              {visited.includes(country.code)
                ? "In your travel history"
                : "No flights recorded"}
            </Text>
            {visited.includes(country.code) ? (
              <Pressable
                accessibilityRole="button"
                onPress={() => {
                  onOpenCountry?.(country.code);
                  clear();
                }}
                style={styles.countryLink}
              >
                <Text style={styles.link}>View passport entry</Text>
                <WWIcon name="arrow" size={17} />
              </Pressable>
            ) : null}
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Dismiss country"
              onPress={clear}
              style={styles.dismiss}
            >
              <WWIcon name="close" size={16} />
            </Pressable>
          </View>
        ) : null}
        <View style={styles.stats}>
          {[
            { value: flightCount, label: "Flights", open: () => onChange("trips") },
            { value: visited.length, label: "Countries", open: () => onOpenCollection ? onOpenCollection("countries") : onChange("passport") },
            { value: ports.length, label: "Airports", open: () => onOpenCollection ? onOpenCollection("airports") : onChange("passport") },
          ].map(({ value, label, open }) => (
            <Pressable
              key={String(label)}
              accessibilityRole="button"
              accessibilityLabel={`${value} ${label.toLowerCase()}`}
              onPress={() => { clear(); open(); }}
              style={({ pressed }) => [styles.stat, pressed && styles.pressed]}
            >
              <Text style={styles.statNumber}>{value}</Text>
              <Text style={styles.statLabel}>{label}</Text>
            </Pressable>
          ))}
        </View>
      </View>
      <BottomNav
        active={active}
        onChange={(tab) => {
          clear();
          onChange(tab);
        }}
      />
      <Modal
        visible={yearOpen}
        transparent
        animationType="slide"
        onRequestClose={() => setYearOpen(false)}
      >
        <View style={styles.modal}>
          <Pressable
            accessibilityLabel="Dismiss years"
            style={StyleSheet.absoluteFill}
            onPress={() => setYearOpen(false)}
          />
          <View
            style={[
              styles.sheet,
              { paddingBottom: Math.max(insets.bottom, 20) },
            ]}
          >
            <Text style={styles.sheetTitle}>Flight history</Text>
            <ScrollView>
              {["All years", ...years].map((y) => (
                <Pressable
                  accessibilityRole="button"
                  accessibilityState={{ selected: y === year }}
                  key={y}
                  onPress={() => {
                    setYear(y);
                    setYearOpen(false);
                    clear();
                  }}
                  style={styles.yearOption}
                >
                  <Text style={styles.yearOptionText}>{y}</Text>
                  {year === y ? <WWIcon name="check" size={20} /> : null}
                </Pressable>
              ))}
            </ScrollView>
          </View>
        </View>
      </Modal>
    </View>
  );
}
const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.paperSoft },
  top: { position: "absolute", left: 24, right: 24 },
  brand: { width: 48, height: 44, justifyContent: "center" },
  controls: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    minHeight: 44,
    gap: 12,
  },
  year: {
    minHeight: 44,
    flexShrink: 1,
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
  },
  yearText: { flexShrink: 1, fontFamily: fonts.sans, fontSize: 15, color: colors.ink },
  iconButton: {
    height: 44,
    minWidth: 44,
    paddingHorizontal: 7,
    flexDirection: "row",
    gap: 7,
    borderRadius: 22,
    justifyContent: "center",
    alignItems: "center",
    backgroundColor: colors.paperSoft,
  },
  textureButton: { width: 48, borderWidth: 1, borderColor: colors.paperBorder },
  chosen: { backgroundColor: colors.paperDeep },
  pressed: { opacity: 0.7, transform: [{ scale: 0.98 }] },
  bottom: { position: "absolute", left: 24, right: 24, gap: 20 },
  stats: {
    flexDirection: "row",
    backgroundColor: colors.paperSoft,
    paddingVertical: 12,
    borderTopWidth: 1,
    borderTopColor: colors.blue,
    borderRadius: 8,
    minHeight: 78,
  },
  stat: {
    flex: 1,
    alignItems: "center",
    minHeight: 52,
    justifyContent: "center",
    gap: 2,
  },
  statNumber: {
    fontFamily: fonts.mono,
    fontSize: 32,
    lineHeight: 32,
    letterSpacing: -1.5,
    includeFontPadding: false,
    color: colors.ink,
  },
  statLabel: {
    fontFamily: fonts.sansRegular,
    fontSize: 13,
    lineHeight: 17,
    includeFontPadding: false,
    color: colors.mutedInk,
  },
  ticket: {
    borderWidth: 1,
    borderColor: colors.paperBorder,
    borderRadius: 4,
    backgroundColor: colors.paper,
    shadowColor: colors.ink,
    shadowOffset: { width: 0, height: 5 },
    shadowOpacity: 0.1,
    shadowRadius: 14,
    elevation: 3,
  },
  ticketBody: { padding: 15, paddingBottom: 0 },
  ticketHeading: {
    flexDirection: "row",
    alignItems: "baseline",
    gap: 10,
    paddingRight: 31,
  },
  flightNumber: { fontFamily: fonts.mono, fontSize: 12, color: colors.blue },
  ticketAirline: {
    color: colors.mutedInk,
    fontFamily: fonts.sansRegular,
    fontSize: 12,
    flex: 1,
  },
  route: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginTop: 12,
    marginBottom: 15,
    gap: 12,
  },
  endpoint: { flex: 1 },
  airport: {
    fontFamily: fonts.mono,
    color: colors.blue,
    fontSize: 35,
    lineHeight: 35,
    letterSpacing: -1.3,
    includeFontPadding: false,
  },
  city: {
    fontFamily: fonts.sansRegular,
    fontSize: 12,
    color: colors.mutedInk,
    marginTop: 2,
  },
  tear: {
    borderTopWidth: 1,
    borderStyle: "dashed",
    borderColor: colors.paperBorder,
    paddingVertical: 14,
    marginHorizontal: -15,
    paddingHorizontal: 15,
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  ticketDate: {
    fontFamily: fonts.sansRegular,
    fontSize: 12,
    color: colors.mutedInk,
  },
  ticketLink: { flexDirection: "row", alignItems: "center", gap: 6 },
  link: { fontFamily: fonts.sansSemi, color: colors.blue, fontSize: 13 },
  dismiss: {
    position: "absolute",
    right: 2,
    top: 2,
    width: 40,
    height: 40,
    alignItems: "center",
    justifyContent: "center",
  },
  countryCard: {
    backgroundColor: colors.paper,
    padding: 20,
    borderWidth: 1,
    borderColor: colors.paperBorder,
    borderRadius: 4,
    gap: 7,
  },
  countryTitle: {
    fontFamily: fonts.display,
    fontSize: 29,
    color: colors.ink,
    paddingRight: 25,
  },
  countryLink: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    paddingTop: 12,
    minHeight: 44,
  },
  import: {
    padding: 20,
    backgroundColor: colors.paper,
    borderWidth: 1,
    borderColor: colors.paperBorder,
    borderRadius: 4,
    marginTop: 20,
    gap: 15,
  },
  importTitle: { fontFamily: fonts.display, color: colors.ink, fontSize: 26 },
  body: {
    fontFamily: fonts.sansRegular,
    color: colors.mutedInk,
    fontSize: 13,
    lineHeight: 20,
  },
  error: { color: colors.red, fontFamily: fonts.sansRegular, fontSize: 13 },
  loading: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    paddingVertical: 15,
  },
  modal: { flex: 1, justifyContent: "flex-end", backgroundColor: "#182C3B66" },
  sheet: {
    maxHeight: "70%",
    backgroundColor: colors.paperSoft,
    borderTopLeftRadius: 20,
    borderTopRightRadius: 20,
    padding: 24,
  },
  sheetTitle: {
    fontFamily: fonts.display,
    fontSize: 30,
    color: colors.ink,
    marginBottom: 16,
  },
  yearOption: {
    minHeight: 52,
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    borderBottomWidth: 1,
    borderColor: colors.paperBorderSoft,
  },
  yearOptionText: { fontFamily: fonts.mono, color: colors.ink, fontSize: 16 },
});
