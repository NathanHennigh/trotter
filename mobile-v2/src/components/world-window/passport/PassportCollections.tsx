import React from "react";
import { Image, Pressable, ScrollView, StyleSheet, Text, TextInput, useWindowDimensions, View } from "react-native";
import { CroppedPassportStamp } from "./PassportStamp";
import type { TripSummary } from "../../../data/trotterMock";
import type { CountryArrival } from "../../../utils/countryArrivals";
import { colors, fonts } from "../../../theme/trotterTheme";
import { WWHeader, WWIcon, WWEmpty, WWButton } from "../WorldWindowUI";
import { AirlineLogo, airlineName } from "../AirlineLogo";
import { readableDate, type PassportArchive, type AirportRecord, type AirlineRecord } from "./passport-model";
import { getMobileVisualWidth } from "../../../utils/mobileLayout";
import { AirportRouteFan } from "./AirportRouteFan";
export type CollectionKind = "countries" | "airports" | "airlines";
const emblems = require("../../../../assets/world-window/passport/window-collection-emblems.png");

export function CollectionButtons({ archive, onOpen }: { archive: PassportArchive; onOpen: (kind: CollectionKind) => void }) {
  const values = { countries: archive.arrivals.length, airports: archive.airports.length, airlines: archive.airlines.length };
  return <View style={styles.collections}>{(["countries", "airports", "airlines"] as const).map((kind, i) => <Pressable key={kind} onPress={() => onOpen(kind)} accessibilityRole="button" accessibilityLabel={`${values[kind]} ${kind}`} style={({ pressed }) => [styles.collection, pressed && styles.pressed]}>
    <View style={styles.mark}><Image source={emblems} style={{ position: "absolute", width: 201.6, height: 134.4, left: -64.8 * i, top: -31.2 }} /></View>
    <Text style={styles.collectionValue}>{values[kind]}</Text><Text style={styles.collectionTitle}>{kind[0].toUpperCase() + kind.slice(1)}</Text>
  </Pressable>)}</View>;
}
export function CollectionBack({ label, onBack }: { label: string; onBack: () => void }) {
  return <Pressable style={styles.back} accessibilityRole="button" onPress={onBack}><WWIcon name="back" size={18} /><Text style={styles.backLabel}>{label}</Text></Pressable>;
}
export function CollectionHeading({ title, count, query, setQuery, placeholder, onBack, backLabel = "Passport" }: { title: string; count: number; query: string; setQuery: (value: string) => void; placeholder: string; onBack: () => void; backLabel?: string }) {
  return <><WWHeader title="Passport" /><View style={styles.inset}><CollectionBack label={backLabel} onBack={onBack} />
    <View style={styles.collectionTitleRow}><Text accessibilityRole="header" style={styles.heading}>{title}</Text><Text style={styles.headingCount}>{count}</Text></View>
    <View style={styles.search}><WWIcon name="search" size={18} color={colors.mutedInk} /><TextInput value={query} onChangeText={setQuery} placeholder={placeholder} placeholderTextColor={colors.mutedInk} accessibilityLabel={placeholder} style={styles.searchInput} autoCorrect={false} autoCapitalize="none" clearButtonMode="while-editing" />{query ? <Pressable onPress={() => setQuery("")} accessibilityLabel="Clear search" style={styles.clear}><WWIcon name="close" size={16}/></Pressable> : null}</View>
  </View></>;
}
export function CountryIndex({ arrivals, onSelect, query = "" }: { arrivals: CountryArrival[]; onSelect: (arrival: CountryArrival) => void; query?: string }) {
  const { width } = useWindowDimensions(), columnWidth = (getMobileVisualWidth(width) - 48 - 18) / 2;
  const entries = [...arrivals].sort((a, b) => a.country.localeCompare(b.country)).filter(a => `${a.country} ${a.airportCode ?? ""}`.toLowerCase().includes(query.trim().toLowerCase()));
  if (!arrivals.length) return <WWEmpty title="No countries recorded" body="Countries from your flights, including connections, will appear here." />;
  if (!entries.length) return <Text style={styles.empty}>No matching countries.</Text>;
  return <View style={styles.countryGrid}>{entries.map(arrival => <Pressable key={arrival.travelCountryKey ?? arrival.country} accessibilityRole="button" onPress={() => onSelect(arrival)} style={({ pressed }) => [styles.countryEntry, { width: columnWidth }, pressed && styles.pressed]}>
    <CroppedPassportStamp arrival={arrival} width={columnWidth} height={148} />
    <Text style={styles.countryName}>{arrival.country}</Text><Text style={styles.countryAirport}>{arrival.airportCode ?? "—"}</Text><Text style={styles.meta}>{readableDate(arrival.firstVisitDate)}</Text>
  </Pressable>)}</View>;
}
export function CountryArrivalDetail({ arrival, trips, onBack, onOpenTrip, width, backLabel = "Countries", onBackHandlerChange }: { arrival: CountryArrival; trips: TripSummary[]; onBack: () => void; onOpenTrip?: (trip: TripSummary) => void; width: number; backLabel?: string; onBackHandlerChange?: (handler: (() => boolean) | null) => void }) {
  const [showTrips, setShowTrips] = React.useState(false);

  React.useEffect(() => {
    onBackHandlerChange?.(() => {
      if (!showTrips) return false;
      setShowTrips(false);
      return true;
    });
    return () => onBackHandlerChange?.(null);
  }, [showTrips, onBackHandlerChange]);
  const relevant = trips.filter(trip => trip.country === arrival.country || Boolean(arrival.travelCountryKey && trip.travelCountryKey === arrival.travelCountryKey) || (trip.segments ?? []).some(segment => (segment.arrPoint?.country ?? segment.arrCountry) === arrival.country || Boolean(arrival.airportCode && segment.arrAirport === arrival.airportCode)));
  const city = relevant.flatMap(t => t.segments ?? []).find(s => s.arrAirport === arrival.airportCode)?.arrPoint?.city;
  return <ScrollView showsVerticalScrollIndicator={false} contentContainerStyle={{ paddingBottom: 40 }}><WWHeader title="Passport" /><View style={styles.inset}>
    <CollectionBack label={showTrips ? arrival.country : backLabel} onBack={showTrips ? () => setShowTrips(false) : onBack} />
    <Text accessibilityRole="header" style={[styles.heading, styles.detailHeading]}>{showTrips ? `Trips to ${arrival.country}` : arrival.country}</Text>
    {!showTrips && <><View style={styles.detailStamp}><CroppedPassportStamp arrival={arrival} width={Math.min(width - 48, 330)} height={310} /></View>
      <Text style={styles.sectionLabel}>First recorded entry</Text><View style={styles.entryDetails}><Text style={styles.entryAirport}>{[city, arrival.airportCode].filter(Boolean).join(" · ") || arrival.country}</Text><Text style={styles.entryDate}>{readableDate(arrival.firstVisitDate)}</Text></View>
      {relevant.length > 0 && <WWButton label={`View ${relevant.length} ${relevant.length === 1 ? "trip" : "trips"}`} onPress={() => setShowTrips(true)} />}
    </>}
  </View>{showTrips && <TripRows trips={relevant} onOpenTrip={onOpenTrip} />}</ScrollView>;
}
function TripRows({ trips, onOpenTrip }: { trips: TripSummary[]; onOpenTrip?: (trip: TripSummary) => void }) {
  return <View style={styles.inset}>{trips.map(trip => <Pressable key={trip.id} accessibilityRole={onOpenTrip ? "button" : undefined} disabled={!onOpenTrip} onPress={() => onOpenTrip?.(trip)} style={({ pressed }) => [styles.listRow, pressed && styles.pressed]}><View style={styles.listCopy}><Text style={styles.tripTitle}>{trip.city || trip.title}</Text><Text style={styles.meta}>{readableDate(trip.startDate)} – {readableDate(trip.endDate)}</Text></View><View style={styles.countCopy}><Text style={styles.flightCount}>{trip.flightCount}</Text><Text style={styles.meta}>flights</Text></View>{onOpenTrip && <WWIcon name="arrow" size={16}/>}</Pressable>)}</View>;
}
export function CollectionList({ kind, archive, onBack, onSelectCountry, onOpenTrip, backLabel, onBackHandlerChange }: { kind: CollectionKind; archive: PassportArchive; onBack: () => void; onSelectCountry: (arrival: CountryArrival) => void; onOpenTrip?: (trip: TripSummary) => void; backLabel?: string; onBackHandlerChange?: (handler: (() => boolean) | null) => void }) {
  const [detail, setDetail] = React.useState<AirportRecord | AirlineRecord | null>(null), [query, setQuery] = React.useState("");

  React.useEffect(() => {
    onBackHandlerChange?.(() => {
      if (!detail) return false;
      setDetail(null);
      return true;
    });
    return () => onBackHandlerChange?.(null);
  }, [detail, onBackHandlerChange]);
  if (detail) {
    const dates = detail.trips.flatMap(t => t.segments ?? []).flatMap(s => [s.depAirport === detail.code ? s.depTime : "", s.arrAirport === detail.code ? s.arrTime : ""]).filter(Boolean).sort();
    return <ScrollView showsVerticalScrollIndicator={false} contentContainerStyle={{ paddingBottom: 40 }}><WWHeader title="Passport"/><View style={styles.inset}><CollectionBack label={kind === "airports" ? "Airports" : "Airlines"} onBack={() => setDetail(null)}/>
      {"city" in detail ? <><View style={styles.airportPortrait}><View style={{ flex: 1 }}><Text style={styles.airportCode}>{detail.code}</Text><Text style={styles.airportCity}>{detail.city || detail.code}</Text>{detail.country ? <Text style={styles.meta}>{detail.country}</Text> : null}</View><View style={styles.countCopy}><Text style={styles.portraitCount}>{detail.flights}</Text><Text style={styles.meta}>flights</Text></View></View>
        {dates.length > 0 && <View style={styles.visitDates}><View><Text style={styles.meta}>First recorded visit</Text><Text style={styles.visitDate}>{readableDate(dates[0])}</Text></View><View><Text style={styles.meta}>Latest recorded visit</Text><Text style={styles.visitDate}>{readableDate(dates.at(-1))}</Text></View></View>}
      </> : <View style={styles.carrierHeading}><AirlineLogo code={detail.code} size={40}/><View style={{ flex: 1 }}><Text style={styles.airportCity}>{airlineName(detail.code)}</Text><Text style={styles.meta}>{detail.flights} flights · {detail.trips.length} trips</Text></View></View>}
      {"city" in detail ? <AirportRouteFan airport={detail} onOpenTrip={onOpenTrip}/> : <Text style={[styles.sectionLabel, { marginTop: 24 }]}>Trips</Text>}</View>{!("city" in detail) && <TripRows trips={detail.trips} onOpenTrip={onOpenTrip}/>}</ScrollView>;
  }
  const list = kind === "airports" ? archive.airports : archive.airlines;
  const filtered = list.filter(item => `${item.code} ${"city" in item ? item.city : airlineName(item.code)} ${"country" in item ? item.country : ""}`.toLowerCase().includes(query.trim().toLowerCase()));
  return <ScrollView keyboardShouldPersistTaps="handled" showsVerticalScrollIndicator={false} contentContainerStyle={{ paddingBottom: 40 }}>
    <CollectionHeading title={kind[0].toUpperCase() + kind.slice(1)} count={kind === "countries" ? archive.arrivals.length : list.length} query={query} setQuery={setQuery} placeholder={kind === "countries" ? "Country or entry airport" : kind === "airports" ? "Airport or city" : "Airline name or code"} onBack={onBack} backLabel={backLabel}/>
    {kind === "countries" ? <CountryIndex arrivals={archive.arrivals} onSelect={onSelectCountry} query={query}/> : <View style={styles.inset}>{filtered.map(item => <Pressable key={item.code} accessibilityRole="button" onPress={() => setDetail(item)} style={({ pressed }) => [styles.listRow, pressed && styles.pressed]}>
      {kind === "airlines" ? <AirlineLogo code={item.code} size={40}/> : <Text style={styles.airportTag}>{item.code}</Text>}
      <View style={styles.listCopy}><Text style={styles.airlineName}>{kind === "airlines" ? airlineName(item.code) : "city" in item ? item.city || item.code : item.code}</Text><Text style={styles.meta}>{kind === "airlines" ? item.code : "country" in item ? item.country : ""}</Text></View>
      <View style={styles.countCopy}><Text style={styles.flightCount}>{item.flights}</Text><Text style={styles.meta}>{item.flights === 1 ? "flight" : "flights"}</Text></View><WWIcon name="arrow" size={16}/>
    </Pressable>)}{!filtered.length && <Text style={styles.empty}>{list.length ? "No matching " : "No recorded "}{kind}.</Text>}</View>}
  </ScrollView>;
}
const styles = StyleSheet.create({
  inset: { paddingHorizontal: 24 },
  collections: { flexDirection: "row", gap: 10 },
  collection: { flex: 1, alignItems: "center", paddingTop: 10, paddingBottom: 16, gap: 7, borderBottomWidth: 1, borderBottomColor: colors.paperBorder },
  mark: { width: 72, height: 72, overflow: "hidden" },
  collectionValue: { fontFamily: fonts.mono, fontSize: 26, color: colors.ink },
  collectionTitle: { fontFamily: fonts.sans, fontSize: 13, color: colors.ink },
  pressed: { opacity: .68 },
  back: { minHeight: 44, flexDirection: "row", gap: 10, alignItems: "center", alignSelf: "flex-start", marginBottom: 12 },
  backLabel: { fontFamily: fonts.sansRegular, fontSize: 14, color: colors.ink },
  collectionTitleRow: { flexDirection: "row", alignItems: "baseline", justifyContent: "space-between", gap: 18, marginTop: 14, marginBottom: 22 },
  heading: { fontFamily: fonts.display, fontSize: 36, lineHeight: 39, letterSpacing: -.5, color: colors.ink },
  headingCount: { fontFamily: fonts.mono, fontSize: 21, color: colors.mutedInk },
  search: { flexDirection: "row", alignItems: "center", gap: 10, minHeight: 60, borderBottomWidth: 1, borderBottomColor: colors.paperBorder, marginBottom: 20 },
  searchInput: { flex: 1, minWidth: 0, minHeight: 44, fontFamily: fonts.sansRegular, fontSize: 15, color: colors.ink, paddingVertical: 8 },
  clear: { minWidth: 36, minHeight: 44, alignItems: "center", justifyContent: "center" },
  countryGrid: { paddingHorizontal: 24, flexDirection: "row", flexWrap: "wrap", gap: 24, columnGap: 18 },
  countryEntry: { gap: 10, borderBottomWidth: 1, borderBottomColor: colors.blue, paddingBottom: 18 },
  countryName: { fontFamily: fonts.display, fontSize: 21, lineHeight: 24, color: colors.blue },
  countryAirport: { fontFamily: fonts.mono, fontSize: 14, color: colors.blue, letterSpacing: .56 },
  meta: { fontFamily: fonts.sansRegular, fontSize: 12, lineHeight: 18, color: colors.mutedInk },
  detailHeading: { marginTop: 14, paddingBottom: 15, borderBottomWidth: 1, borderBottomColor: colors.blue },
  detailStamp: { marginTop: 20, marginBottom: 27, alignItems: "center" },
  sectionLabel: { fontFamily: fonts.sans, fontSize: 15, lineHeight: 21, color: colors.ink, marginBottom: 16 },
  entryDetails: { marginBottom: 24, gap: 7 },
  entryAirport: { fontFamily: fonts.sansSemi, fontSize: 15, lineHeight: 24, color: colors.ink },
  entryDate: { fontFamily: fonts.sansRegular, fontSize: 15, lineHeight: 24, color: colors.mutedInk },
  listRow: { flexDirection: "row", alignItems: "center", gap: 12, minHeight: 76, paddingVertical: 15, borderBottomWidth: 1, borderBottomColor: colors.paperBorder },
  listCopy: { flex: 1, gap: 3 },
  countCopy: { alignItems: "flex-end" },
  flightCount: { fontFamily: fonts.sans, fontSize: 16, color: colors.ink },
  airlineName: { fontFamily: fonts.sansRegular, fontSize: 16, color: colors.ink },
  airportTag: { fontFamily: fonts.mono, color: colors.blue, fontSize: 23, minWidth: 53 },
  tripTitle: { fontFamily: fonts.display, fontSize: 23, color: colors.ink },
  airportPortrait: { flexDirection: "row", alignItems: "center", gap: 15, paddingVertical: 20 },
  airportCode: { fontFamily: fonts.mono, fontSize: 66, lineHeight: 76, letterSpacing: -3, color: colors.ink },
  airportCity: { fontFamily: fonts.display, fontSize: 28, lineHeight: 33, color: colors.ink, marginBottom: 3 },
  portraitCount: { fontFamily: fonts.display, fontSize: 36, color: colors.ink },
  visitDates: { flexDirection: "row", justifyContent: "space-between", gap: 12, paddingVertical: 18, borderTopWidth: 1, borderBottomWidth: 1, borderColor: colors.paperBorder },
  visitDate: { fontFamily: fonts.sansRegular, fontSize: 14, color: colors.ink, marginTop: 5 },
  carrierHeading: { flexDirection: "row", alignItems: "center", gap: 14, paddingVertical: 22 },
  empty: { fontFamily: fonts.sansRegular, fontSize: 14, lineHeight: 21, color: colors.mutedInk, padding: 24 },
});
