import React from "react";
import {
  Image,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  useWindowDimensions,
  View,
} from "react-native";
import { PressFeedback as Pressable, PaperReveal } from "../motion";
import { CroppedPassportStamp } from "./PassportStamp";
import type { TripSummary } from "../../../data/trotterMock";
import type { CountryArrival } from "../../../utils/countryArrivals";
import { colors, fonts } from "../../../theme/trotterTheme";
import { WWIcon, WWEmpty } from "../WorldWindowUI";
import { AirlineLogo, airlineName } from "../AirlineLogo";
import {
  readableDate,
  type PassportArchive,
  type AirportRecord,
  type AirlineRecord,
} from "./passport-model";
import { getMobileVisualWidth } from "../../../utils/mobileLayout";
import { AirportRouteFan } from "./AirportRouteFan";
import { tripsForCountry } from "./passport-collection-model";
import { countryCatalog, airportCatalog, airlineCatalog } from "../../../data/collections/catalogs";
import { collectionProgress } from "../collections/catalogProgress";
import { TransportCollectionIndex } from "../collections/TransportCollectionIndex";
import { AirportLuggageLabel } from "../collections/AirportLuggageLabel";
import { transportEntries } from "../collections/transportCollectionModel";
export type CollectionKind = "countries" | "airports" | "airlines";
const emblems = require("../../../../assets/world-window/passport/window-collection-emblems.png");

export function CollectionButtons({
  archive,
  onOpen,
}: {
  archive: PassportArchive;
  onOpen: (kind: CollectionKind) => void;
}) {
  const { width, fontScale } = useWindowDimensions();
  const cardWidth = Math.max(fontScale >= 1.35 ? 145 : 0, (getMobileVisualWidth(width) - 68) / 3);
  const values = React.useMemo(() => ({
    countries: collectionProgress(countryCatalog, archive.arrivals.map(arrival => arrival.travelCountryKey ?? arrival.country)),
    airports: collectionProgress(airportCatalog, archive.airports.map(airport => airport.code)),
    airlines: collectionProgress(airlineCatalog, archive.airlines.map(airline => airline.code)),
  }), [archive]);
  return (
    <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.collections}>
      {(["countries", "airports", "airlines"] as const).map((kind, i) => (
        <Pressable
          key={kind}
          onPress={() => onOpen(kind)}
          accessibilityRole="button"
          accessibilityLabel={`${values[kind].collected} of ${values[kind].total} ${kind}${values[kind].outsideCatalogKeys.length ? `, ${values[kind].outsideCatalogKeys.length} other recorded ${values[kind].outsideCatalogKeys.length === 1 ? 'entry' : 'entries'} outside this catalogue` : ''}`}
          style={[styles.collection, { flexGrow: 0, flexShrink: 0, flexBasis: 'auto', width: cardWidth }]}
        >
          <View style={styles.mark} accessible={false}>
            <View
              style={{
                width: kind === "airports" ? 60 : 72,
                height: 72,
                overflow: "hidden",
              }}
            >
              <Image
                source={emblems}
                style={{
                  position: "absolute",
                  width: 201.6,
                  height: 134.4,
                  left: -64.8 * i - (kind === "airports" ? 6 : 0),
                  top: -31.2,
                }}
              />
            </View>
          </View>
          <Text style={styles.collectionValue}>{values[kind].collected}</Text>
          <Text style={styles.collectionTotal}>of {values[kind].total.toLocaleString()}</Text>
          <Text style={styles.collectionTitle}>
            {kind[0].toUpperCase() + kind.slice(1)}
          </Text>
          <View style={styles.collectionTrack}><View style={[styles.collectionFill, { width: `${Math.min(100, Math.max(0, values[kind].percent))}%` }]} /></View>
          {values[kind].outsideCatalogKeys.length > 0 && <Text style={styles.collectionExtra}>+{values[kind].outsideCatalogKeys.length} other</Text>}
        </Pressable>
      ))}
    </ScrollView>
  );
}
export function CollectionBack({
  label,
  onBack,
}: {
  label: string;
  onBack: () => void;
}) {
  return (
    <Pressable
      style={styles.back}
      accessibilityRole="button"
      accessibilityLabel={`Back to ${label}`}
      onPress={onBack}
    >
      <WWIcon name="back" size={18} />
      <Text style={styles.backLabel}>{label}</Text>
    </Pressable>
  );
}
export function CollectionTitle({
  title,
  count,
  onBack,
  backLabel = "Passport",
}: {
  title: string;
  count?: number;
  onBack: () => void;
  backLabel?: string;
}) {
  const { width, fontScale } = useWindowDimensions();
  const largeText = fontScale >= 1.35;
  const fitTitle = largeText
    ? {
        fontSize: Math.min(
          32,
          (getMobileVisualWidth(width) - 48) /
            (fontScale *
              Math.max(
                4.8,
                ...title.split(/\s+/).map((word) => word.length * 0.56),
              )),
        ),
      }
    : undefined;
  return (
    <View style={styles.titleBar}>
      <CollectionBack label={backLabel} onBack={onBack} />
      <View
        style={[styles.collectionTitleRow, largeText && styles.titleRowLarge]}
      >
        <Text accessibilityRole="header" style={[styles.heading, fitTitle]}>
          {title}
        </Text>
        {count !== undefined && (
          <Text style={styles.headingCount}>{count}</Text>
        )}
      </View>
    </View>
  );
}
export function CollectionScope({
  year,
  onClear,
}: {
  year?: string;
  onClear?: () => void;
}) {
  if (!year) return null;
  return (
    <View style={styles.scope}>
      <Text style={styles.scopeLabel}>Flights in {year}</Text>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel="Show all years"
        onPress={onClear}
        style={styles.scopeClear}
      >
        <Text style={styles.scopeLink}>All years</Text>
      </Pressable>
    </View>
  );
}
export function CollectionHeading({
  title,
  count,
  query,
  setQuery,
  placeholder,
  onBack,
  backLabel = "Passport",
}: {
  title: string;
  count?: number;
  query: string;
  setQuery: (value: string) => void;
  placeholder: string;
  onBack: () => void;
  backLabel?: string;
}) {
  return (
    <View style={styles.inset}>
      <CollectionTitle
        title={title}
        count={count}
        onBack={onBack}
        backLabel={backLabel}
      />
      <View style={styles.search}>
        <WWIcon name="search" size={18} color={colors.mutedInk} />
        <TextInput
          value={query}
          onChangeText={setQuery}
          placeholder={placeholder}
          placeholderTextColor={colors.mutedInk}
          accessibilityLabel={placeholder}
          style={styles.searchInput}
          autoCorrect={false}
          autoCapitalize="none"
        />
        {query ? (
          <Pressable
            onPress={() => setQuery("")}
            accessibilityRole="button"
            accessibilityLabel="Clear search"
            style={styles.clear}
          >
            <WWIcon name="close" size={16} />
          </Pressable>
        ) : null}
      </View>
    </View>
  );
}
export function CountryIndex({
  arrivals,
  onSelect,
  query = "",
}: {
  arrivals: CountryArrival[];
  onSelect: (arrival: CountryArrival) => void;
  query?: string;
}) {
  const { width, fontScale } = useWindowDimensions(),
    columnWidth =
      fontScale >= 1.35
        ? getMobileVisualWidth(width) - 48
        : (getMobileVisualWidth(width) - 48 - 18) / 2;
  const entries = [...arrivals]
    .sort((a, b) => a.country.localeCompare(b.country))
    .filter((a) =>
      `${a.country} ${a.airportCode ?? ""}`
        .toLowerCase()
        .includes(query.trim().toLowerCase()),
    );
  if (!arrivals.length)
    return (
      <WWEmpty
        title="No countries recorded"
        body="Countries from your flights, including connections, will appear here."
      />
    );
  if (!entries.length)
    return <Text style={styles.empty}>No matching countries.</Text>;
  return (
    <View style={styles.countryGrid}>
      {entries.map((arrival) => (
        <Pressable
          key={arrival.travelCountryKey ?? arrival.country}
          accessibilityRole="button"
          onPress={() => onSelect(arrival)}
          style={[styles.countryEntry, { width: columnWidth }]}
        >
          <CroppedPassportStamp
            arrival={arrival}
            width={columnWidth}
            height={148}
          />
          <Text style={styles.countryName}>{arrival.country}</Text>
          <Text style={styles.countryAirport}>
            {arrival.airportCode ?? "—"}
          </Text>
          <Text style={styles.meta}>
            {readableDate(arrival.firstVisitDate)}
          </Text>
        </Pressable>
      ))}
    </View>
  );
}
export function CountryArrivalDetail({
  arrival,
  trips,
  onBack,
  onOpenTrip,
  width,
  backLabel = "Countries",
  onBackHandlerChange,
  year,
  onClearYear,
}: {
  arrival: CountryArrival;
  trips: TripSummary[];
  onBack: () => void;
  onOpenTrip?: (trip: TripSummary) => void;
  width: number;
  backLabel?: string;
  onBackHandlerChange?: (handler: (() => boolean) | null) => void;
  year?: string;
  onClearYear?: () => void;
}) {
  React.useEffect(() => {
    onBackHandlerChange?.(() => false);
    return () => onBackHandlerChange?.(null);
  }, [onBackHandlerChange]);
  const relevant = React.useMemo(
    () => tripsForCountry(trips, arrival, Boolean(year)),
    [trips, arrival, year],
  );
  return (
    <View style={styles.layer}>
      <View style={styles.inset}>
        <CollectionTitle
          title={arrival.country}
          backLabel={backLabel}
          onBack={onBack}
        />
      </View>
      <ScrollView
        showsVerticalScrollIndicator={false}
        contentContainerStyle={{ paddingBottom: 40 }}
      >
        <View style={styles.inset}>
          <CollectionScope year={year} onClear={onClearYear} />
          <View style={styles.detailStamp}>
            <CroppedPassportStamp
              arrival={arrival}
              width={Math.min(width - 48, 330)}
              height={280}
            />
          </View>
          <Text style={styles.sectionLabel}>First recorded entry</Text>
          <View style={styles.entryDetails}>
            <Text style={styles.entryAirport}>
              {arrival.airportCode || arrival.country}
            </Text>
            <Text style={styles.entryDate}>
              {readableDate(arrival.firstVisitDate)}
            </Text>
          </View>
          <Text style={styles.sectionLabel}>
            {year ? `Journeys in ${year}` : "Journeys"} · {relevant.length}
          </Text>
        </View>
        {relevant.length ? (
          <TripRows trips={relevant} onOpenTrip={onOpenTrip} />
        ) : (
          <Text style={styles.empty}>
            {year
              ? `No flights in ${year}. The first-entry stamp remains in your passport.`
              : "No associated journeys recorded."}
          </Text>
        )}
      </ScrollView>
    </View>
  );
}
function TripRows({
  trips,
  onOpenTrip,
}: {
  trips: TripSummary[];
  onOpenTrip?: (trip: TripSummary) => void;
}) {
  const largeText = useWindowDimensions().fontScale >= 1.35;
  return (
    <View style={styles.inset}>
      {trips.map((trip) => (
        <Pressable
          key={trip.id}
          accessibilityRole={onOpenTrip ? "button" : undefined}
          disabled={!onOpenTrip}
          onPress={() => onOpenTrip?.(trip)}
          style={styles.listRow}
        >
          <View style={styles.listCopy}>
            <Text style={styles.tripTitle}>{trip.city || trip.title}</Text>
            <Text style={styles.meta}>
              {readableDate(trip.startDate)} – {readableDate(trip.endDate)}
            </Text>
            {largeText && (
              <Text style={styles.meta}>{trip.flightCount} flights</Text>
            )}
          </View>
          {!largeText && (
            <View style={styles.countCopy}>
              <Text style={styles.flightCount}>{trip.flightCount}</Text>
              <Text style={styles.meta}>flights</Text>
            </View>
          )}
          {onOpenTrip && <WWIcon name="arrow" size={16} />}
        </Pressable>
      ))}
    </View>
  );
}
export function CollectionList({
  kind,
  archive,
  lifetimeArchive = archive,
  onBack,
  onSelectCountry,
  onOpenTrip,
  backLabel,
  onBackHandlerChange,
  initialAirport,
  scopeEpoch,
  year,
  onClearYear,
}: {
  kind: CollectionKind;
  archive: PassportArchive;
  lifetimeArchive?: PassportArchive;
  onBack: () => void;
  onSelectCountry: (arrival: CountryArrival) => void;
  onOpenTrip?: (trip: TripSummary) => void;
  backLabel?: string;
  onBackHandlerChange?: (handler: (() => boolean) | null) => void;
  initialAirport?: string;
  scopeEpoch?: number;
  year?: string;
  onClearYear?: () => void;
}) {
  const largeText = useWindowDimensions().fontScale >= 1.35;
  const [detailCode, setDetailCode] = React.useState<string | null>(
      initialAirport ?? null,
    ),
    [query, setQuery] = React.useState("");
  const list = kind === "airports" ? archive.airports : archive.airlines;
  const entries = React.useMemo(() => transportEntries(kind === 'airports' ? 'airports' : 'airlines', archive, lifetimeArchive), [kind, archive, lifetimeArchive]);
  const selectedEntry = entries.find(entry => entry.key === detailCode);
  const detail: AirportRecord | AirlineRecord | undefined = selectedEntry
    ? selectedEntry.record ?? (kind === 'airports'
      ? { code: selectedEntry.key, city: selectedEntry.city || selectedEntry.name, country: selectedEntry.countryName, flights: 0, trips: [] }
      : { code: selectedEntry.key, flights: 0, miles: 0, trips: [] })
    : list.find((item) => item.code === detailCode);
  const directDetail = Boolean(
    initialAirport && detail?.code === initialAirport,
  );
  React.useEffect(
    () => setDetailCode(initialAirport ?? null),
    [initialAirport, scopeEpoch],
  );
  React.useEffect(() => {
    onBackHandlerChange?.(() => {
      if (!detail || directDetail) return false;
      setDetailCode(null);
      return true;
    });
    return () => onBackHandlerChange?.(null);
  }, [detail, directDetail, onBackHandlerChange]);
  const renderDetail = () => {
    if (!detail) return null;
    const dates = (selectedEntry?.lifetimeRecord ?? detail).trips
      .flatMap((t) => t.segments ?? [])
      .flatMap((s) => [
        s.depAirport?.trim().toUpperCase() === detail.code.trim().toUpperCase() ? s.depTime : "",
        s.arrAirport?.trim().toUpperCase() === detail.code.trim().toUpperCase() ? s.arrTime : "",
      ])
      .filter(date => date && Number.isFinite(Date.parse(date)))
      .sort((a, b) => Date.parse(a) - Date.parse(b));
    return (
      <PaperReveal
        key={`${kind}-${detail.code}`}
        style={styles.detailLayer}
        distance={8}
      >
        <View style={styles.inset}>
          <CollectionTitle
            title={kind === "airports" ? "Airport" : "Airline"}
            backLabel={
              directDetail
                ? (backLabel ?? "Passport")
                : kind === "airports"
                  ? "Airports"
                  : "Airlines"
            }
            onBack={directDetail ? onBack : () => setDetailCode(null)}
          />
        </View>
        <ScrollView
          showsVerticalScrollIndicator={false}
          contentContainerStyle={{ paddingBottom: 40 }}
        >
          <View style={styles.inset}>
            <CollectionScope year={year} onClear={onClearYear} />
            {"city" in detail ? (
              <>
                {selectedEntry && <AirportLuggageLabel entry={selectedEntry} hero year={year} />}
                {dates.length > 0 && (
                  <View
                    style={[styles.visitDates, largeText && styles.stacked]}
                  >
                    <View style={styles.dateCopy}>
                      <Text style={styles.meta}>First recorded visit</Text>
                      <Text style={styles.visitDate}>
                        {readableDate(dates[0])}
                      </Text>
                    </View>
                    <View style={styles.dateCopy}>
                      <Text style={styles.meta}>Latest recorded visit</Text>
                      <Text style={styles.visitDate}>
                        {readableDate(dates.at(-1))}
                      </Text>
                    </View>
                  </View>
                )}
              </>
            ) : (
              <View style={styles.carrierHeading}>
                <AirlineLogo code={detail.code} size={40} />
                <View style={{ flex: 1 }}>
                  <Text style={styles.airportCity}>
                    {selectedEntry?.name || airlineName(detail.code)}
                  </Text>
                  <Text style={styles.meta}>
                    {detail.flights} flights · {detail.trips.length} trips
                  </Text>
                </View>
              </View>
            )}
            {"city" in detail ? (
              detail.trips.length ? <AirportRouteFan airport={detail} onOpenTrip={onOpenTrip} /> : <Text style={styles.empty}>{selectedEntry?.lifetimeRecord && year ? `No recorded flights through ${detail.code} in ${year}.` : 'Your first recorded visit will appear here.'}</Text>
            ) : (
              <Text style={[styles.sectionLabel, { marginTop: 24 }]}>
                Trips
              </Text>
            )}
          </View>
          {!("city" in detail) && (
            detail.trips.length ? <TripRows trips={detail.trips} onOpenTrip={onOpenTrip} /> : <Text style={styles.empty}>{selectedEntry?.lifetimeRecord && year ? `No recorded flights with this airline in ${year}.` : 'Your first recorded flight with this airline will appear here.'}</Text>
          )}
        </ScrollView>
      </PaperReveal>
    );
  };
  return (
    <View style={styles.layer}>
      <View
        style={styles.layer}
        pointerEvents={detail ? "none" : "auto"}
        aria-hidden={Boolean(detail)}
        accessibilityElementsHidden={Boolean(detail)}
        importantForAccessibility={detail ? "no-hide-descendants" : "auto"}
      >
        {kind !== 'countries' ? <TransportCollectionIndex kind={kind} entries={entries} query={query} onSelect={setDetailCode} year={year}
          header={<><CollectionHeading title={kind === 'airports' ? 'Airports' : 'Airlines'} query={query} setQuery={setQuery}
            placeholder={kind === 'airports' ? 'Airport, city or country' : 'Airline name or code'} onBack={onBack} backLabel={backLabel} />
            <View style={styles.inset}><CollectionScope year={year} onClear={onClearYear} /></View></>}
        /> : <ScrollView
          keyboardShouldPersistTaps="handled"
          keyboardDismissMode="on-drag"
          showsVerticalScrollIndicator={false}
          contentContainerStyle={{ paddingBottom: 40 }}
        >
          <CollectionHeading
            title={kind[0].toUpperCase() + kind.slice(1)}
            count={kind === "countries" ? archive.arrivals.length : list.length}
            query={query}
            setQuery={setQuery}
            placeholder={
              kind === "countries"
                ? "Country or entry airport"
                : kind === "airports"
                  ? "Airport or city"
                  : "Airline name or code"
            }
            onBack={onBack}
            backLabel={backLabel}
          />
          <View style={styles.inset}>
            <CollectionScope year={year} onClear={onClearYear} />
          </View>
          {kind === "countries" && (
            <CountryIndex
              arrivals={archive.arrivals}
              onSelect={onSelectCountry}
              query={query}
            />
          )}
        </ScrollView>}
      </View>
      {renderDetail()}
    </View>
  );
}
const styles = StyleSheet.create({
  layer: { flex: 1 },
  detailLayer: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: colors.paperSoft,
  },
  scope: {
    flexDirection: "row",
    flexWrap: "wrap",
    alignItems: "center",
    justifyContent: "space-between",
    columnGap: 16,
    minHeight: 44,
    borderBottomWidth: 1,
    borderBottomColor: colors.paperBorder,
    marginBottom: 16,
  },
  scopeLabel: {
    fontFamily: fonts.sansRegular,
    fontSize: 14,
    color: colors.mutedInk,
  },
  scopeClear: { minHeight: 44, justifyContent: "center" },
  scopeLink: {
    fontFamily: fonts.sans,
    fontSize: 14,
    color: colors.blue,
    textDecorationLine: "underline",
  },
  inset: { paddingHorizontal: 24 },
  collections: { flexDirection: "row", gap: 10 },
  collection: {
    flex: 1,
    alignItems: "center",
    paddingTop: 10,
    paddingBottom: 16,
    gap: 7,
    borderBottomWidth: 1,
    borderBottomColor: colors.paperBorder,
  },
  mark: { width: 72, height: 72, overflow: "hidden", alignItems: "center" },
  collectionValue: { fontFamily: fonts.mono, fontSize: 26, color: colors.ink },
  collectionTotal: { fontFamily: fonts.mono, fontSize: 10, color: colors.mutedInk, marginTop: -5 },
  collectionTrack: { height: 2, backgroundColor: colors.paperBorderSoft, alignSelf: 'stretch', marginTop: 4 },
  collectionFill: { height: 2, backgroundColor: colors.copper },
  collectionExtra: { fontFamily: fonts.sansRegular, fontSize: 10, color: colors.mutedInk, textAlign: 'center' },
  collectionTitle: {
    fontFamily: fonts.sans,
    fontSize: 13,
    color: colors.ink,
    textAlign: "center",
    alignSelf: "stretch",
  },
  back: {
    minHeight: 44,
    flexDirection: "row",
    gap: 10,
    alignItems: "center",
    alignSelf: "flex-start",
    marginBottom: 12,
  },
  backLabel: { fontFamily: fonts.sansRegular, fontSize: 14, color: colors.ink },
  titleBar: {
    alignItems: "stretch",
    paddingTop: 4,
    paddingBottom: 18,
    borderBottomWidth: 1,
    borderBottomColor: colors.paperBorder,
  },
  titleBack: {
    minWidth: 44,
    minHeight: 44,
    alignItems: "flex-start",
    justifyContent: "center",
  },
  collectionTitleRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    alignItems: "baseline",
    columnGap: 14,
    rowGap: 4,
  },
  titleRowLarge: { width: "100%", flex: 0 },
  heading: {
    flexShrink: 1,
    fontFamily: fonts.display,
    fontSize: 32,
    lineHeight: 36,
    letterSpacing: -0.5,
    color: colors.ink,
  },
  headingCount: {
    fontFamily: fonts.mono,
    fontSize: 21,
    color: colors.mutedInk,
  },
  search: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    minHeight: 60,
    borderBottomWidth: 1,
    borderBottomColor: colors.paperBorder,
    marginBottom: 20,
  },
  searchInput: {
    flex: 1,
    minWidth: 0,
    minHeight: 44,
    fontFamily: fonts.sansRegular,
    fontSize: 15,
    color: colors.ink,
    paddingVertical: 8,
  },
  clear: {
    minWidth: 36,
    minHeight: 44,
    alignItems: "center",
    justifyContent: "center",
  },
  countryGrid: {
    paddingHorizontal: 24,
    flexDirection: "row",
    flexWrap: "wrap",
    rowGap: 24,
    columnGap: 18,
  },
  countryEntry: {
    gap: 10,
    borderBottomWidth: 1,
    borderBottomColor: colors.blue,
    paddingBottom: 18,
  },
  countryName: {
    fontFamily: fonts.display,
    fontSize: 21,
    lineHeight: 24,
    color: colors.blue,
  },
  countryAirport: {
    fontFamily: fonts.mono,
    fontSize: 14,
    color: colors.blue,
    letterSpacing: 0.56,
  },
  meta: {
    fontFamily: fonts.sansRegular,
    fontSize: 12,
    lineHeight: 18,
    color: colors.mutedInk,
  },
  detailHeading: {
    marginTop: 14,
    paddingBottom: 15,
    borderBottomWidth: 1,
    borderBottomColor: colors.blue,
  },
  detailStamp: { marginTop: 20, marginBottom: 27, alignItems: "center" },
  sectionLabel: {
    fontFamily: fonts.sans,
    fontSize: 15,
    lineHeight: 21,
    color: colors.ink,
    marginBottom: 16,
  },
  entryDetails: { marginBottom: 24, gap: 7 },
  entryAirport: {
    fontFamily: fonts.sansSemi,
    fontSize: 15,
    lineHeight: 24,
    color: colors.ink,
  },
  entryDate: {
    fontFamily: fonts.sansRegular,
    fontSize: 15,
    lineHeight: 24,
    color: colors.mutedInk,
  },
  listRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    minHeight: 76,
    paddingVertical: 15,
    borderBottomWidth: 1,
    borderBottomColor: colors.paperBorder,
  },
  listCopy: { flex: 1, minWidth: 0, gap: 3 },
  countCopy: { alignItems: "flex-end" },
  flightCount: { fontFamily: fonts.sans, fontSize: 16, color: colors.ink },
  airlineName: {
    fontFamily: fonts.sansRegular,
    fontSize: 16,
    color: colors.ink,
  },
  airportTag: {
    fontFamily: fonts.mono,
    color: colors.blue,
    fontSize: 23,
    minWidth: 53,
  },
  tripTitle: { fontFamily: fonts.display, fontSize: 23, color: colors.ink },
  airportPortrait: {
    flexDirection: "row",
    alignItems: "center",
    gap: 15,
    paddingVertical: 20,
  },
  airportCode: {
    fontFamily: fonts.mono,
    fontSize: 66,
    lineHeight: 76,
    letterSpacing: -3,
    color: colors.ink,
  },
  airportCity: {
    fontFamily: fonts.display,
    fontSize: 28,
    lineHeight: 33,
    color: colors.ink,
    marginBottom: 3,
  },
  portraitCount: { fontFamily: fonts.display, fontSize: 36, color: colors.ink },
  visitDates: {
    flexDirection: "row",
    justifyContent: "space-between",
    gap: 12,
    paddingVertical: 18,
    borderTopWidth: 1,
    borderBottomWidth: 1,
    borderColor: colors.paperBorder,
  },
  stacked: { flexDirection: "column", alignItems: "stretch" },
  dateCopy: { flex: 1, minWidth: 0 },
  portraitCountInline: {
    flexDirection: "row",
    alignItems: "baseline",
    gap: 10,
  },
  airportTagLarge: { fontSize: 17, minWidth: 0 },
  visitDate: {
    fontFamily: fonts.sansRegular,
    fontSize: 14,
    color: colors.ink,
    marginTop: 5,
  },
  carrierHeading: {
    flexDirection: "row",
    alignItems: "center",
    gap: 14,
    paddingVertical: 22,
  },
  empty: {
    fontFamily: fonts.sansRegular,
    fontSize: 14,
    lineHeight: 21,
    color: colors.mutedInk,
    padding: 24,
  },
});
