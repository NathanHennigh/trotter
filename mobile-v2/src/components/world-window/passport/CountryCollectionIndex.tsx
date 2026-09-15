import React from "react";
import { ScrollView, StyleSheet, Text, TextInput, useWindowDimensions, View } from "react-native";
import { PressFeedback } from "../motion";
import { WWIcon } from "../WorldWindowUI";
import { CroppedPassportStamp } from "./PassportStamp";
import { readableDate } from "./passport-model";
import type { CountryArrival } from "../../../utils/countryArrivals";
import { colors, fonts } from "../../../theme/trotterTheme";
import { countryCatalog } from "../../../data/collections/catalogs";
import { collectionProgress, resolveCatalogKey } from "../collections/catalogProgress";

export type CountryCatalogRecord = { key: string; name: string; region?: string; aliases?: readonly string[] };
type CountryRow = { entry: CountryCatalogRecord; arrival?: CountryArrival; lifetimeArrival?: CountryArrival };
type Filter = "visited" | "all";
const regionOrder = ["Africa", "Asia", "Europe", "North America", "South America", "Oceania", "Antarctica"];
const normalize = (value: string) => value.normalize("NFKD").replace(/[\u0300-\u036f]/g, "").toLowerCase().trim();
const arrivalKey = (arrival: CountryArrival) => resolveCatalogKey(countryCatalog, arrival.travelCountryKey ?? arrival.country)
  ?? resolveCatalogKey(countryCatalog, arrival.country)
  ?? arrival.travelCountryKey ?? arrival.country;
function indexArrivals(arrivals: CountryArrival[]) {
  const index = new Map<string, CountryArrival>();
  for (const arrival of arrivals) {
    const key = arrivalKey(arrival), previous = index.get(key);
    if (!previous || arrival.firstVisitDate < previous.firstVisitDate) index.set(key, arrival);
  }
  return index;
}

export function countryCollectionRows(arrivals: CountryArrival[], lifetimeArrivals: CountryArrival[]) {
  const scoped = indexArrivals(arrivals);
  const lifetime = indexArrivals(lifetimeArrivals);
  const entries: CountryCatalogRecord[] = [...countryCatalog.entries];
  const known = new Set(entries.map(entry => entry.key));
  // Preserve a recorded arrival even if a future import is outside this catalog.
  for (const [key, arrival] of lifetime) if (!known.has(key))
    entries.push({ key, name: arrival.country, region: "Other recorded places" });
  return entries.map(entry => ({ entry, arrival: scoped.get(entry.key), lifetimeArrival: lifetime.get(entry.key) }));
}

export function countryCollectionGroups(rows: CountryRow[], filter: Filter, query: string, continent: string) {
  const search = normalize(query);
  const result = new Map<string, { region: string; earned: CountryRow[]; remaining: CountryRow[]; total: number; collected: number }>();
  for (const row of rows) {
    const region = row.entry.region ?? "Other recorded places";
    if (continent !== "All regions" && continent !== region) continue;
    const group = result.get(region) ?? { region, earned: [], remaining: [], total: 0, collected: 0 };
    group.total++;
    if (row.arrival) group.collected++;
    result.set(region, group);
    if (search && !normalize([row.entry.name, row.entry.key, ...(row.entry.aliases ?? []), row.lifetimeArrival?.airportCode ?? ""].join(" ")).includes(search)) continue;
    if (row.arrival) group.earned.push(row);
    else if (filter === "all") group.remaining.push(row);
  }
  return [...result.values()].filter(group => group.earned.length || group.remaining.length)
    .sort((a, b) => (regionOrder.indexOf(a.region) < 0 ? 99 : regionOrder.indexOf(a.region)) - (regionOrder.indexOf(b.region) < 0 ? 99 : regionOrder.indexOf(b.region)))
    .map(group => ({ ...group,
      earned: group.earned.sort((a, b) => (a.arrival!.firstVisitDate || "9999").localeCompare(b.arrival!.firstVisitDate || "9999") || a.entry.name.localeCompare(b.entry.name)),
      remaining: group.remaining.sort((a, b) => a.entry.name.localeCompare(b.entry.name)),
    }));
}

export function CountryCollectionIndex({ arrivals, lifetimeArrivals = arrivals, onSelect, onSelectUnvisited, query, setQuery, width, onBack, backLabel, year, onClearYear }: {
  arrivals: CountryArrival[]; lifetimeArrivals?: CountryArrival[];
  onSelect: (arrival: CountryArrival) => void; onSelectUnvisited: (entry: CountryCatalogRecord) => void;
  query: string; setQuery: (query: string) => void; width: number; onBack: () => void; backLabel: string;
  year?: string; onClearYear: () => void;
}) {
  const { fontScale } = useWindowDimensions();
  const largeText = fontScale >= 1.35;
  const [filter, setFilter] = React.useState<Filter>("visited");
  const [continent, setContinent] = React.useState("All regions");
  const rows = React.useMemo(() => countryCollectionRows(arrivals, lifetimeArrivals), [arrivals, lifetimeArrivals]);
  const progress = React.useMemo(() => collectionProgress(countryCatalog, arrivals.map(arrivalKey)), [arrivals]);
  const groups = React.useMemo(() => countryCollectionGroups(rows, filter, query, continent), [rows, filter, query, continent]);
  const continents = React.useMemo(() => ["All regions", ...regionOrder.filter(region => rows.some(row => row.entry.region === region)), ...(rows.some(row => row.entry.region === "Other recorded places") ? ["Other recorded places"] : [])], [rows]);
  const contentWidth = Math.max(160, width - 40), cardWidth = largeText ? contentWidth : (contentWidth - 18) / 2;
  const found = groups.reduce((sum, group) => sum + group.earned.length + group.remaining.length, 0);
  return <View>
    <View style={styles.heading}>
      <PressFeedback onPress={onBack} accessibilityRole="button" accessibilityLabel={`Back to ${backLabel}`} style={styles.back}>
        <WWIcon name="back" size={18} /><Text style={styles.backLabel}>{backLabel}</Text>
      </PressFeedback>
      <View style={[styles.headingRow, largeText && styles.stacked]}>
        <Text accessibilityRole="header" style={[styles.headingTitle, { fontSize: Math.min(36, contentWidth / (fontScale * 4.8)) }]}>Countries</Text>
        <View style={styles.coverage} accessibilityLabel={`${progress.collected} of ${progress.total} countries and territories visited${year ? ` in ${year}` : ""}`}>
          <Text style={styles.coverageValue}>{progress.collected}<Text style={styles.coverageTotal}> / {progress.total}</Text></Text>
          <Text style={styles.coverageLabel}>{year ? `visited in ${year}` : "visited"}</Text>
        </View>
      </View>
      <View style={styles.progressTrack} accessible={false}><View style={[styles.progressInk, { width: `${progress.percent}%` }]} /></View>
      {progress.outsideCatalogKeys.length > 0 && <Text style={styles.additionalPlaces}>{progress.outsideCatalogKeys.length} additional recorded {progress.outsideCatalogKeys.length === 1 ? "place" : "places"}</Text>}
      {year && <View style={styles.yearScope}><Text style={styles.scopeText}>Flights in {year}</Text><PressFeedback onPress={onClearYear} accessibilityRole="button" style={styles.scopeClear}><Text style={styles.scopeLink}>All years</Text></PressFeedback></View>}
      <View style={styles.segmented}>
        {(["visited", "all"] as const).map(value => <PressFeedback key={value} accessibilityRole="button" accessibilityState={{ selected: filter === value }} onPress={() => setFilter(value)} style={[styles.segment, filter === value && styles.segmentActive]}>
          <Text style={[styles.segmentLabel, filter === value && styles.segmentLabelActive]}>{value === "visited" ? "Visited" : "All countries"}</Text>
        </PressFeedback>)}
      </View>
      <View style={styles.search}>
        <WWIcon name="search" size={17} color={colors.mutedInk} />
        <TextInput value={query} onChangeText={setQuery} placeholder="Country or entry airport" placeholderTextColor={colors.mutedInk} accessibilityLabel="Search countries or first-entry airports" autoCorrect={false} autoCapitalize="none" style={styles.searchInput} />
        {query ? <PressFeedback onPress={() => setQuery("")} accessibilityRole="button" accessibilityLabel="Clear country search" style={styles.clearSearch}><WWIcon name="close" size={16} /></PressFeedback> : null}
      </View>
    </View>
    <ScrollView horizontal showsHorizontalScrollIndicator={false} keyboardShouldPersistTaps="handled" contentContainerStyle={styles.continents}>
      {continents.map(region => <PressFeedback key={region} accessibilityRole="button" accessibilityState={{ selected: continent === region }} onPress={() => setContinent(region)} style={[styles.continent, continent === region && styles.continentActive]}><Text style={[styles.continentLabel, continent === region && styles.continentLabelActive]}>{region}</Text></PressFeedback>)}
    </ScrollView>
    <View style={styles.index}>
      {query.trim() ? <Text style={styles.results}>{found} {found === 1 ? "result" : "results"}</Text> : null}
      {groups.map(group => <View key={group.region} style={styles.region}>
        <View style={styles.regionHeading}><Text accessibilityRole="header" style={styles.regionName}>{group.region}</Text><View style={styles.rule} /><Text style={styles.regionCount}>{group.collected} / {group.total}</Text></View>
        {group.earned.length > 0 && <View style={styles.earnedGrid}>
          {group.earned.map(row => <PressFeedback key={row.entry.key} accessibilityRole="button" accessibilityLabel={`${row.entry.name}, first entry ${row.arrival!.airportCode ?? "airport not recorded"}, ${readableDate(row.arrival!.firstVisitDate)}`} onPress={() => onSelect(row.arrival!)} style={[styles.earnedCountry, { width: cardWidth }]}>
            <View style={styles.impression} accessible={false} pointerEvents="none"><CroppedPassportStamp arrival={row.arrival!} width={Math.min(cardWidth - 12, largeText ? 150 : 152)} height={largeText ? 132 : 128} /></View>
            <Text style={styles.countryName}>{row.entry.name}</Text>
            <View style={[styles.entryMeta, largeText && styles.entryMetaLarge]}><Text style={styles.airportCode}>{row.arrival!.airportCode || "Entry recorded"}</Text><Text style={styles.entryDate}>{readableDate(row.arrival!.firstVisitDate)}</Text></View>
          </PressFeedback>)}
        </View>}
        {group.remaining.length > 0 && <View style={styles.unvisited}>
          <Text style={styles.directoryLabel}>{year ? `Not recorded in ${year}` : "Not yet visited"}</Text>
          {group.remaining.map(row => <PressFeedback key={row.entry.key} accessibilityRole="button" accessibilityLabel={`${row.entry.name}, ${row.lifetimeArrival ? "visited in another year" : "not yet visited"}`} onPress={() => row.lifetimeArrival ? onSelect(row.lifetimeArrival) : onSelectUnvisited(row.entry)} style={styles.directoryRow}>
            <View style={styles.directoryCopy}><Text style={styles.directoryName}>{row.entry.name}</Text>{row.lifetimeArrival && <Text style={styles.directoryVisited}>Visited Â· {readableDate(row.lifetimeArrival.firstVisitDate)}</Text>}</View>
            {row.lifetimeArrival ? <WWIcon name="check" size={15} color={colors.copper} /> : row.entry.key.length === 2 ? <Text style={styles.directoryCode}>{row.entry.key}</Text> : null}<WWIcon name="chevron" size={14} color={colors.mutedInk} />
          </PressFeedback>)}
        </View>}
      </View>)}
      {!groups.length && <View style={styles.empty}><WWIcon name="globe" size={28} color={colors.blue} /><Text style={styles.emptyTitle}>{query.trim() ? "No matching countries" : year ? `No visits in ${year}` : "No visits here yet"}</Text><Text style={styles.emptyCopy}>{query.trim() ? "Try a country name or first-entry airport." : "Browse all countries to see the collection."}</Text><PressFeedback accessibilityRole="button" onPress={() => { setQuery(""); setFilter("all"); }} style={styles.emptyButton}><Text style={styles.emptyAction}>Browse all countries</Text><WWIcon name="arrow" size={16} /></PressFeedback></View>}
      <Text style={styles.catalogScope}>{countryCatalog.metadata.total} countries and territories · Connections count</Text>
    </View>
  </View>;
}

export function UnvisitedCountryRecord({ entry, onBack, width }: { entry: CountryCatalogRecord; onBack: () => void; width: number }) {
  const { fontScale } = useWindowDimensions();
  return <ScrollView contentContainerStyle={[styles.unvisitedRecord, { width }]}>
    <PressFeedback onPress={onBack} accessibilityRole="button" accessibilityLabel="Back to Countries" style={styles.back}><WWIcon name="back" size={18} /><Text style={styles.backLabel}>Countries</Text></PressFeedback>
    <View style={styles.recordPaper}>
      <Text style={styles.recordRegion}>{entry.region}</Text>
      <Text accessibilityRole="header" style={[styles.recordTitle, { fontSize: Math.min(34, (width - 80) / (fontScale * Math.max(5, ...entry.name.split(/\s+/).map(word => word.length * .55)))) }]}>{entry.name}</Text>
      <View style={styles.recordRule} />
      <View style={styles.notVisited}><WWIcon name="globe" size={20} color={colors.mutedInk} /><Text style={styles.notVisitedTitle}>Not yet visited</Text></View>
      <Text style={styles.recordCopy}>Your first recorded arrival will add this country to your passport.</Text>
    </View>
  </ScrollView>;
}

const styles = StyleSheet.create({
  catalogScope: { paddingVertical: 16, fontFamily: fonts.sansRegular, fontSize: 11, lineHeight: 17, color: colors.mutedInk },
  heading: { paddingHorizontal: 20, paddingTop: 5 }, back: { minHeight: 44, flexDirection: "row", alignItems: "center", gap: 8, alignSelf: "flex-start" }, backLabel: { fontFamily: fonts.sansRegular, fontSize: 13, color: colors.mutedInk },
  headingRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 12, marginTop: 5, marginBottom: 18 }, stacked: { flexDirection: "column", alignItems: "flex-start" }, headingTitle: { fontFamily: fonts.display, color: colors.ink, flexShrink: 1 }, coverage: { gap: 2 }, coverageValue: { fontFamily: fonts.mono, fontSize: 22, color: colors.ink }, coverageTotal: { fontSize: 14, color: colors.mutedInk }, coverageLabel: { fontFamily: fonts.sansRegular, fontSize: 12, color: colors.mutedInk }, progressTrack: { height: 2, backgroundColor: colors.paperBorderSoft, marginBottom: 20 }, progressInk: { height: 2, backgroundColor: colors.copper },
  yearScope: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 8, marginTop: -12, marginBottom: 6 }, scopeText: { flexShrink: 1, fontFamily: fonts.sansRegular, fontSize: 13, color: colors.mutedInk }, scopeClear: { minHeight: 44, justifyContent: "center" }, scopeLink: { fontFamily: fonts.sans, fontSize: 13, color: colors.blue },
  additionalPlaces: { fontFamily: fonts.sansRegular, fontSize: 12, color: colors.mutedInk, marginTop: -9, marginBottom: 16 },
  segmented: { flexDirection: "row", borderWidth: 1, borderColor: colors.paperBorder, borderRadius: 4, padding: 3, gap: 3 }, segment: { flex: 1, minHeight: 44, paddingVertical: 9, paddingHorizontal: 6, alignItems: "center", justifyContent: "center", borderRadius: 2 }, segmentActive: { backgroundColor: colors.ink }, segmentLabel: { fontFamily: fonts.sans, fontSize: 13, color: colors.mutedInk, textAlign: "center" }, segmentLabelActive: { color: colors.paperSoft },
  search: { flexDirection: "row", alignItems: "center", gap: 8, minHeight: 48, marginTop: 13, borderBottomWidth: 1, borderBottomColor: colors.paperBorder }, searchInput: { flex: 1, minWidth: 0, fontFamily: fonts.sansRegular, fontSize: 14, color: colors.ink, paddingVertical: 10 }, clearSearch: { width: 44, minHeight: 44, alignItems: "center", justifyContent: "center" },
  continents: { paddingHorizontal: 20, paddingTop: 8, paddingBottom: 11, gap: 20 }, continent: { minHeight: 44, justifyContent: "center", borderBottomWidth: 2, borderBottomColor: "transparent" }, continentActive: { borderBottomColor: colors.copper }, continentLabel: { fontFamily: fonts.sansRegular, fontSize: 13, color: colors.mutedInk }, continentLabelActive: { fontFamily: fonts.sans, color: colors.ink },
  index: { paddingHorizontal: 20 }, results: { marginVertical: 10, fontFamily: fonts.sansRegular, fontSize: 12, color: colors.mutedInk }, region: { marginTop: 12, marginBottom: 20 }, regionHeading: { flexDirection: "row", alignItems: "center", flexWrap: "wrap", gap: 10, marginBottom: 15 }, regionName: { fontFamily: fonts.sans, fontSize: 14, color: colors.ink, flexShrink: 1 }, rule: { flex: 1, height: 1, minWidth: 12, backgroundColor: colors.paperBorder }, regionCount: { fontFamily: fonts.mono, fontSize: 11, color: colors.mutedInk },
  earnedGrid: { flexDirection: "row", flexWrap: "wrap", gap: 18, alignItems: "flex-start" }, earnedCountry: { paddingBottom: 16, gap: 6 }, impression: { alignItems: "center", justifyContent: "center", paddingVertical: 10, backgroundColor: colors.paperSheet, borderTopWidth: 1, borderBottomWidth: 1, borderColor: colors.paperBorderSoft, marginBottom: 5 }, countryName: { fontFamily: fonts.sans, fontSize: 15, lineHeight: 20, color: colors.ink }, entryMeta: { gap: 3 }, entryMetaLarge: { gap: 5 }, airportCode: { fontFamily: fonts.mono, fontSize: 11, color: colors.copper }, entryDate: { fontFamily: fonts.sansRegular, fontSize: 11, color: colors.mutedInk },
  unvisited: { marginTop: 6 }, directoryLabel: { fontFamily: fonts.sansRegular, fontSize: 12, color: colors.mutedInk, marginBottom: 9 }, directoryRow: { minHeight: 48, flexDirection: "row", alignItems: "center", gap: 10, paddingVertical: 11, borderBottomWidth: 1, borderBottomColor: colors.paperBorderSoft }, directoryCopy: { flex: 1, minWidth: 0, gap: 4 }, directoryName: { fontFamily: fonts.sansRegular, fontSize: 14, color: colors.mutedInk }, directoryVisited: { fontFamily: fonts.sansRegular, fontSize: 11, color: colors.copper }, directoryCode: { fontFamily: fonts.mono, fontSize: 11, color: colors.mutedInk },
  empty: { paddingVertical: 32, gap: 12, alignItems: "flex-start" }, emptyTitle: { fontFamily: fonts.sans, fontSize: 17, color: colors.ink }, emptyCopy: { fontFamily: fonts.sansRegular, fontSize: 14, lineHeight: 21, color: colors.mutedInk }, emptyButton: { minHeight: 44, flexDirection: "row", alignItems: "center", gap: 10 }, emptyAction: { fontFamily: fonts.sans, fontSize: 14, color: colors.blue },
  unvisitedRecord: { padding: 20 }, recordPaper: { marginTop: 20, paddingHorizontal: 20, paddingVertical: 24, backgroundColor: colors.paperSheet, borderTopWidth: 2, borderBottomWidth: 1, borderColor: colors.paperBorder, gap: 14 }, recordRegion: { fontFamily: fonts.sansRegular, fontSize: 13, color: colors.mutedInk }, recordTitle: { fontFamily: fonts.display, color: colors.ink }, recordRule: { height: 1, backgroundColor: colors.paperBorderSoft, marginVertical: 5 }, notVisited: { flexDirection: "row", alignItems: "center", gap: 10 }, notVisitedTitle: { flex: 1, fontFamily: fonts.sans, fontSize: 15, color: colors.mutedInk }, recordCopy: { fontFamily: fonts.sansRegular, fontSize: 14, lineHeight: 21, color: colors.mutedInk },
});
