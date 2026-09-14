import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  ActivityIndicator,
  Modal,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  useWindowDimensions,
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
import { type GeoCountry } from "../components/world-window/globe-geography";
import { buildGlobeHistory } from "../components/world-window/globe-history";
import { flightsOnPath } from "../components/world-window/routeSelection";
import { PaperPresence, PressFeedback, useReducedMotion } from "../components/world-window/motion";
import { useExperiencePreferences } from "../utils/experiencePreferences";
import type { TripOpenOrigin } from "../components/world-window/trips/tripTransition";
import { flightDate } from "../components/world-window/trips/tripPresentation";
import { fitDisplayFont } from "../components/world-window/displayTextFit";
import { getMobileVisualWidth } from "../utils/mobileLayout";
import type { BottomNavTab, TripSummary } from "../data/trotterMock";
import type { FlightRoute } from "../data/demoTravel";
import { useTravelTrips } from "../services/travelTrips";
import { colors, fonts, layout } from "../theme/trotterTheme";

type Props = {
  active: BottomNavTab;
  onChange: (tab: BottomNavTab) => void;
  onOpenTrip?: (trip: TripSummary, flightId?: string, origin?: TripOpenOrigin) => void;
  onOpenCountry?: (code: string) => void;
  onOpenCollection?: (kind: "countries" | "airports", year?: string) => void;
  onOpenFlights?: (year?: string) => void;
  filterYear?: string;
  onFilterYear?: (year: string) => void;
  onBackHandlerChange?: (handler: (() => boolean) | null) => void;
};
export function HomeGlobeScreen({
  active,
  onChange,
  onOpenTrip,
  onOpenCountry,
  onOpenCollection,
  onOpenFlights,
  filterYear,
  onFilterYear,
  onBackHandlerChange,
}: Props) {
  const insets = useSafeAreaInsets();
  const { width, height, fontScale = 1 } = useWindowDimensions();
  const visualWidth = getMobileVisualWidth(width), paperWidth = visualWidth - 48;
  const largeText = fontScale >= 1.35;
  const airportSize = Math.min(35, (paperWidth - 81) / (6 * .62 * fontScale));
  const { trips, status, error, syncFromGmail, refresh } = useTravelTrips();
  const reducedMotion = useReducedMotion();
  const [localYear, setLocalYear] = useState("All years");
  const year = filterYear ?? localYear;
  const setYear = (next: string) => {
    setLocalYear(next);
    onFilterYear?.(next);
  };
  const [yearOpen, setYearOpen] = useState(false);
  useEffect(() => {
    if (active !== "globe") setYearOpen(false);
  }, [active]);
  const { texture: mapStyle, setTexture: setMapStyle } = useExperiencePreferences();
  const [textureNotice, setTextureNotice] = useState<string>();
  const noticeTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => () => { if (noticeTimer.current) clearTimeout(noticeTimer.current); }, []);
  const [flightChoicesOpen, setFlightChoicesOpen] = useState(false);
  const ticketRef = useRef<View>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const liveSelection = useRef({ active, selectedId });
  liveSelection.current = { active, selectedId };
  const [country, setCountry] = useState<GeoCountry | null>(null);
  const clear = () => {
    setSelectedId(null);
    setCountry(null);
    setFlightChoicesOpen(false);
  };
  const { routes, visited, flightCount, airportCount, years } = useMemo(
    () => buildGlobeHistory(trips, year),
    [trips, year],
  );
  const selected = routes.find((route) => route.id === selectedId) ?? null;
  const [statsVisible, setStatsVisible] = useState(true);
  useEffect(() => {
    if (selected || country) { setStatsVisible(false); return; }
    if (reducedMotion) { setStatsVisible(true); return; }
    const timer = setTimeout(() => setStatsVisible(true), 150);
    return () => clearTimeout(timer);
  }, [Boolean(selected), Boolean(country), reducedMotion]);
  const showStats = statsVisible && !selected && !country;
  const routeFlights = useMemo(() => flightsOnPath(routes, selected), [routes, selected]);
  const lifetimeVisited = useMemo(() => buildGlobeHistory(trips, "All years").visited, [trips]);
  const statWidth = paperWidth / 3 - 8;
  const statSize = Math.min(32, statWidth / (Math.max(String(flightCount).length, String(airportCount).length, String(visited.length).length) * .63 * fontScale));
  const statLabelSize = Math.min(13, statWidth / (9 * .56 * fontScale));
  const maxPaperHeight = Math.max(180, height - insets.top - insets.bottom - layout.bottomNavHeight - 118);
  useEffect(() => {
    if (active !== "globe") { onBackHandlerChange?.(null); return; }
    onBackHandlerChange?.(() => {
      if (yearOpen) { setYearOpen(false); return true; }
      if (selected && flightChoicesOpen) { setFlightChoicesOpen(false); return true; }
      if (selected || country) { clear(); return true; }
      return false;
    });
    return () => onBackHandlerChange?.(null);
  }, [active, yearOpen, selected, country, flightChoicesOpen, onBackHandlerChange]);
  const previousYear = useRef(year);
  useEffect(() => {
    if (previousYear.current !== year) {
      previousYear.current = year;
      setSelectedId(null);
      setCountry(null);
    } else if (selectedId && !selected) setSelectedId(null);
  }, [year, selectedId, selected]);
  const selectedTrip = selected
    ? trips.find((t) => t.segments?.some((s) => s.id === selected.id))
    : null;
  const openTrip = () => {
    const navigate = (origin?: TripOpenOrigin) => {
      if (liveSelection.current.active !== "globe" || liveSelection.current.selectedId !== selectedId) return;
      if (selectedTrip && onOpenTrip) onOpenTrip(selectedTrip, selected?.id, origin);
      else if (onOpenFlights) onOpenFlights(year);
      else onChange("trips");
      clear();
    };
    if (ticketRef.current) ticketRef.current.measureInWindow((x, y, width, height) => navigate({ x, y, width, height }));
    else navigate();
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
        onRoute={(route: FlightRoute) => {
          setCountry(null);
          setSelectedId(route.id);
          setFlightChoicesOpen(flightsOnPath(routes, route).length > 1);
        }}
        onCountry={(next: GeoCountry) => {
          setSelectedId(null);
          setCountry(next);
        }}
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
          <PressFeedback
            accessibilityRole="button"
            accessibilityLabel="Filter flights by year"
            onPress={() => setYearOpen(true)}
            style={({ pressed }) => [styles.year]}
          >
            <Text style={styles.yearText} numberOfLines={1}>
              {year}
            </Text>
            <WWIcon name="down" size={15} />
          </PressFeedback>
          <PressFeedback
            accessibilityRole="button"
            accessibilityLabel={
              mapStyle === "classic"
                ? "Switch to NASA imagery"
                : "Switch to classic globe"
            }
            accessibilityState={{ selected: mapStyle === "nasa" }}
            onPress={() => {
              const next = mapStyle === "classic" ? "nasa" : "classic";
              setMapStyle(next);
              setTextureNotice(next === "nasa" ? "Satellite" : "Classic");
              if (noticeTimer.current) clearTimeout(noticeTimer.current);
              noticeTimer.current = setTimeout(() => setTextureNotice(undefined), 1500);
            }}
            style={({ pressed }) => [
              styles.iconButton,
              styles.textureButton,
              mapStyle === "nasa" && styles.chosen,

            ]}
          >
            <WWIcon name="globe" size={21} />
          </PressFeedback>
        </View>
        {textureNotice ? <View pointerEvents="none" style={styles.textureNotice}><Text accessibilityLiveRegion="polite" style={styles.textureNoticeText}>{textureNotice}</Text></View> : null}
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
        {error && trips.length > 0 && !busy ? <PressFeedback accessibilityRole="button" accessibilityLabel="Retry loading your flight history" onPress={() => void refresh()} style={styles.retryNotice}><Text style={styles.error}>{error} Tap to retry.</Text></PressFeedback> : null}
      </View>
      <View
        pointerEvents="box-none"
        style={[
          styles.bottom,
          { bottom: insets.bottom + layout.bottomNavHeight + 12 },
        ]}
      >
        <PaperPresence style={styles.paperLayer}>{selected ? (
          <View ref={ticketRef} collapsable={false} style={styles.ticket}>
            <ScrollView style={{ maxHeight: maxPaperHeight }} nestedScrollEnabled showsVerticalScrollIndicator={largeText}>
            <PressFeedback paper
              accessibilityRole="button"
              accessibilityLabel={`View trip for ${selected.from.code} to ${selected.to.code}, ${flightDate(selected.depTime ?? undefined)}${selected.flightNumber ? `, ${selected.flightNumber}` : ""}`}
              onPress={openTrip}
              style={({ pressed }) => [
                styles.ticketBody,

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
                  <Text style={[styles.airport, { fontSize: airportSize, lineHeight: airportSize * 1.05 }]}>{selected.from.code}</Text>
                  <Text style={styles.city} numberOfLines={1}>
                    {selected.from.city}
                  </Text>
                </View>
                <WWIcon name="plane" size={25} color={colors.blue} />
                <View style={[styles.endpoint, { alignItems: "flex-end" }]}>
                  <Text style={[styles.airport, { fontSize: airportSize, lineHeight: airportSize * 1.05 }]}>{selected.to.code}</Text>
                  <Text style={styles.city} numberOfLines={1}>
                    {selected.to.city}
                  </Text>
                </View>
              </View>
              <View style={[styles.tear, largeText && { flexDirection: "column", alignItems: "flex-start", gap: 12 }]}>
                <Text style={styles.ticketDate}>
                  {flightDate(selected.depTime ?? undefined)}
                </Text>
                <View style={styles.ticketLink}>
                  <Text style={styles.link}>View trip</Text>
                  <WWIcon name="arrow" size={16} />
                </View>
              </View>
            </PressFeedback>
            {routeFlights.length > 1 ? <View style={styles.repeatFlights}>
              <PressFeedback accessibilityRole="button" accessibilityState={{ expanded: flightChoicesOpen }}
                accessibilityLabel={`Choose among ${routeFlights.length} flights on this route`}
                onPress={() => setFlightChoicesOpen(value => !value)} style={styles.flightChoiceHeading}>
                <Text style={styles.flightChoiceCount}>{routeFlights.length} flights on this route</Text>
                <WWIcon name={flightChoicesOpen ? "close" : "down"} size={14} />
              </PressFeedback>
              {flightChoicesOpen ? <ScrollView style={styles.flightChoices} nestedScrollEnabled>
                {routeFlights.map(flight => <PressFeedback key={flight.id} accessibilityRole="button"
                  accessibilityState={{ selected: selected.id === flight.id }}
                  accessibilityLabel={`Select ${flight.from.code} to ${flight.to.code}, ${flightDate(flight.depTime ?? undefined)}, ${flight.flightNumber || flight.airline || "flight"}`}
                  onPress={() => { setSelectedId(flight.id); setFlightChoicesOpen(false); }}
                  style={[styles.flightChoice, selected.id === flight.id && styles.flightChoiceSelected]}>
                  <View style={{ flex: 1, gap: 3, paddingVertical: 7 }}><Text style={styles.ticketDate}>{flightDate(flight.depTime ?? undefined)}</Text>
                    <Text style={styles.flightNumber}>{flight.from.code} → {flight.to.code}</Text></View>
                  <Text style={styles.flightNumber}>{flight.flightNumber || flight.airline || "Flight"}</Text>
                  {selected.id === flight.id ? <WWIcon name="check" size={14} /> : null}
                </PressFeedback>)}
              </ScrollView> : null}
            </View> : null}
            </ScrollView>
            <PressFeedback
              accessibilityRole="button"
              accessibilityLabel="Dismiss flight"
              onPress={clear}
              style={styles.dismiss}
            >
              <WWIcon name="close" size={16} />
            </PressFeedback>
          </View>
        ) : country ? (
          <View style={styles.countryCard}>
            <Text style={[styles.countryTitle, { fontSize: fitDisplayFont(country.name, 29, paperWidth - 65, fontScale) }]}>{country.name}</Text>
            <Text style={styles.body}>
              {visited.includes(country.code)
                ? year === "All years" ? "In your travel history" : `Flights recorded in ${year}`
                : year === "All years" ? "No flights recorded" : `No flights in ${year}`}
            </Text>
            {lifetimeVisited.includes(country.code) ? (
              <PressFeedback
                accessibilityRole="button"
                onPress={() => {
                  onOpenCountry?.(country.code);
                  clear();
                }}
                style={styles.countryLink}
              >
                <Text style={styles.link}>View passport entry</Text>
                <WWIcon name="arrow" size={17} />
              </PressFeedback>
            ) : null}
            <PressFeedback
              accessibilityRole="button"
              accessibilityLabel="Dismiss country"
              onPress={clear}
              style={styles.dismiss}
            >
              <WWIcon name="close" size={16} />
            </PressFeedback>
          </View>
        ) : null}</PaperPresence>
        <View style={[styles.stats, { opacity: showStats ? 1 : 0 }]} pointerEvents={showStats ? "auto" : "none"}
          accessibilityElementsHidden={!showStats} importantForAccessibility={showStats ? "auto" : "no-hide-descendants"} aria-hidden={!showStats}>
          {[
            {
              value: flightCount,
              label: "Flights",
              open: () => onOpenFlights ? onOpenFlights(year) : onChange("trips"),
            },
            {
              value: visited.length,
              label: "Countries",
              open: () =>
                onOpenCollection
                  ? onOpenCollection("countries", year)
                  : onChange("passport"),
            },
            {
              value: airportCount,
              label: "Airports",
              open: () =>
                onOpenCollection
                  ? onOpenCollection("airports", year)
                  : onChange("passport"),
            },
          ].map(({ value, label, open }) => (
            <PressFeedback
              key={String(label)}
              accessibilityRole="button"
              accessibilityLabel={`${value} ${label.toLowerCase()}`}
              onPress={() => {
                clear();
                open();
              }}
              style={({ pressed }) => [styles.stat]}
            >
              <Text style={[styles.statNumber, { fontSize: statSize, lineHeight: statSize * 1.05 }]}>{value}</Text>
              <Text style={[styles.statLabel, { fontSize: statLabelSize, lineHeight: statLabelSize * 1.3 }]}>{label}</Text>
            </PressFeedback>
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
        visible={active === "globe" && yearOpen}
        transparent
        animationType={reducedMotion ? "none" : "slide"}
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
                <PressFeedback
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
                </PressFeedback>
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
  yearText: {
    flexShrink: 1,
    fontFamily: fonts.sans,
    fontSize: 15,
    color: colors.ink,
  },
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
  pressed: { opacity: 0.85 },
  textureNotice: { position: "absolute", top: 52, right: 0, backgroundColor: colors.paperSoft, paddingVertical: 4, paddingHorizontal: 10, borderRadius: 4 },
  textureNoticeText: { fontFamily: fonts.sansRegular, fontSize: 12, color: colors.mutedInk },
  retryNotice: { marginTop: 14, padding: 10, backgroundColor: colors.paperSoft, borderWidth: 1, borderColor: colors.paperBorder },
  repeatFlights: { borderTopWidth: 1, borderTopColor: colors.paperBorder, marginHorizontal: 18, marginBottom: 8 },
  flightChoiceHeading: { minHeight: 44, flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 10 },
  flightChoiceCount: { flex: 1, fontFamily: fonts.sansSemi, fontSize: 12, color: colors.ink },
  flightChoices: { maxHeight: 144 },
  flightChoice: { minHeight: 44, flexDirection: "row", alignItems: "center", gap: 12, paddingHorizontal: 8 },
  flightChoiceSelected: { backgroundColor: colors.paperDeep },
  bottom: { position: "absolute", left: 24, right: 24, gap: 20 },
  paperLayer: { position: "absolute", bottom: 0, left: 0, right: 0 },
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
    width: 44,
    height: 44,
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
