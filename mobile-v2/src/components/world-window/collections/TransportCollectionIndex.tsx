import React from 'react';
import { FlatList, ScrollView, StyleSheet, Text, View } from 'react-native';
import { PressFeedback } from '../motion';
import { colors, fonts } from '../../../theme/trotterTheme';
import { AirlineLogo } from '../AirlineLogo';
import { WWIcon } from '../WorldWindowUI';
import { AirportLuggageLabel } from './AirportLuggageLabel';
import { filterTransportEntries, transportCatalog, type TransportEntry, type TransportKind } from './transportCollectionModel';
import { collectionProgress } from './catalogProgress';

export function TransportCollectionIndex({ kind, entries, query, header, onSelect, year }: {
  kind: TransportKind; entries: TransportEntry[]; query: string; header: React.ReactNode;
  onSelect: (code: string) => void; year?: string;
}) {
  const [mode, setMode] = React.useState<'visited' | 'all'>('visited');
  const [region, setRegion] = React.useState('');
  const [showDirectory, setShowDirectory] = React.useState(false);
  const regions = React.useMemo(() => [...new Set(entries.map(entry => entry.region).filter((value): value is string => Boolean(value)))].sort(), [entries]);
  const filtered = React.useMemo(() => filterTransportEntries(entries, mode, region, query), [entries, mode, region, query]);
  const catalog = transportCatalog(kind);
  const regionCatalog = React.useMemo(() => ({ ...catalog, entries: catalog.entries.filter(entry => !region || entry.region === region) }), [catalog, region]);
  const observed = React.useMemo(() => entries.filter(entry => entry.record && (!region || entry.region === region)).map(entry => entry.key), [entries, region]);
  const progress = collectionProgress(regionCatalog, observed);
  const verb = kind === 'airports' ? 'Visited' : 'Flown';
  const metadata = catalog.metadata;
  return <FlatList data={filtered} keyExtractor={entry => entry.key}
    keyboardShouldPersistTaps="handled" keyboardDismissMode="on-drag" showsVerticalScrollIndicator={false}
    initialNumToRender={8} maxToRenderPerBatch={8} windowSize={7} contentContainerStyle={s.content}
    ListHeaderComponent={<>
      {header}
      <View style={s.inset}>
        <View style={s.progressTop}>
          <View style={s.progressNumbers}><Text style={s.collected}>{progress.collected}</Text><Text style={s.total}>/ {progress.total.toLocaleString()}</Text></View>
          <PressFeedback onPress={() => setShowDirectory(value => !value)} accessibilityRole="button" accessibilityLabel="About this collection" accessibilityState={{ expanded: showDirectory }} style={s.info}><Text allowFontScaling={false} style={s.infoGlyph}>i</Text></PressFeedback>
        </View>
        <Text style={s.progressLabel}>{year ? `${verb.toLowerCase()} in ${year}` : verb.toLowerCase()} · {region || 'World'}</Text>
        <View style={s.track}><View style={[s.fill, { width: `${Math.min(100, Math.max(0, progress.percent))}%` }]} /></View>
        {progress.outsideCatalogKeys.length > 0 && <Text style={s.outside}>+ {progress.outsideCatalogKeys.length} other {progress.outsideCatalogKeys.length === 1 ? kind.slice(0, -1) : kind} in your archive</Text>}
        {showDirectory && <View style={s.directory}>
          <Text style={s.directoryTitle}>{metadata.label}</Text>
          <Text style={s.directoryText}>{metadata.scope}</Text>
          <Text style={s.directoryText}>First visits stay tied to your original flight records. Connections count.</Text>
        </View>}
        <View style={s.tabs}>{(['visited', 'all'] as const).map(value => <PressFeedback key={value} accessibilityRole="tab" accessibilityState={{ selected: mode === value }} onPress={() => setMode(value)} style={[s.tab, mode === value && s.tabSelected]}>
          <Text style={[s.tabText, mode === value && s.tabTextSelected]}>{value === 'visited' ? verb : 'All'}</Text>
          <Text style={[s.tabCount, mode === value && s.tabTextSelected]}>{value === 'visited' ? observed.length : entries.filter(entry => !region || entry.region === region).length}</Text>
        </PressFeedback>)}</View>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.regionRow}>
          {['', ...regions].map(value => <PressFeedback key={value || 'world'} accessibilityRole="button" accessibilityState={{ selected: region === value }} onPress={() => setRegion(value)} style={[s.region, region === value && s.regionSelected]}><Text style={[s.regionText, region === value && s.regionTextSelected]}>{value || 'World'}</Text></PressFeedback>)}
        </ScrollView>
      </View>
    </>}
    renderItem={({ item }) => <PressFeedback onPress={() => onSelect(item.key)} accessibilityRole="button"
      accessibilityLabel={`${item.name}, ${item.key}${item.record ? `, ${item.record.flights} flights` : item.lifetimeRecord ? ', visited in another year' : kind === 'airports' ? ', not yet visited' : ', not yet flown'}`}
      style={kind === 'airports' ? s.airportRow : s.airlineRow}>
      {kind === 'airports' ? <AirportLuggageLabel entry={item} year={year} /> : <>
        <View accessible={false} style={s.logo}><AirlineLogo code={item.key} size={30} /></View>
        <View style={s.carrierCopy}><Text style={s.carrier}>{item.name}</Text><Text style={s.carrierMeta}>{item.key}{item.countryName ? ` · ${item.countryName}` : ''}</Text>
          <Text style={s.carrierMeta}>{item.record ? `${item.record.flights} ${item.record.flights === 1 ? 'flight' : 'flights'}${year ? ` · ${year}` : ''}` : item.lifetimeRecord ? `No flights${year ? ` in ${year}` : ''}` : 'Not yet flown'}</Text>
        </View><WWIcon name="arrow" size={15} color={colors.mutedInk} />
      </>}
    </PressFeedback>}
    ListEmptyComponent={<View style={s.empty}><Text style={s.emptyTitle}>{query ? 'No matches' : `No ${kind} ${kind === 'airports' ? 'visited' : 'flown'}${year ? ` in ${year}` : ''}`}</Text>
      <Text style={s.directoryText}>{query ? 'Try a name, airport code, or country.' : 'Browse All to explore the collection.'}</Text></View>}
  />;
}
const s = StyleSheet.create({
  content: { paddingBottom: 36 }, inset: { paddingHorizontal: 24 },
  progressTop: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginTop: 4 }, progressNumbers: { flexDirection: 'row', alignItems: 'baseline', gap: 8, flexWrap: 'wrap', flex: 1 },
  collected: { fontFamily: fonts.display, fontSize: 43, color: colors.ink }, total: { fontFamily: fonts.mono, fontSize: 15, color: colors.mutedInk }, progressLabel: { fontFamily: fonts.sansRegular, fontSize: 12, color: colors.mutedInk, marginTop: 2 },
  info: { width: 44, height: 44, alignItems: 'center', justifyContent: 'center' }, infoGlyph: { borderWidth: 1, borderColor: colors.paperBorder, borderRadius: 10, width: 20, height: 20, textAlign: 'center', fontFamily: fonts.displayItalic, color: colors.ink, fontSize: 15 },
  track: { height: 2, backgroundColor: colors.paperBorderSoft, marginTop: 15, marginBottom: 7 }, fill: { height: 2, backgroundColor: colors.copper },
  outside: { color: colors.mutedInk, fontFamily: fonts.sansRegular, fontSize: 11, lineHeight: 17, marginTop: 4 },
  directory: { paddingVertical: 14, gap: 5, borderBottomWidth: 1, borderBottomColor: colors.paperBorder }, directoryTitle: { fontFamily: fonts.sans, color: colors.ink, fontSize: 14 }, directoryText: { fontFamily: fonts.sansRegular, fontSize: 12, lineHeight: 19, color: colors.mutedInk },
  tabs: { flexDirection: 'row', gap: 22, borderBottomWidth: 1, borderBottomColor: colors.paperBorder, marginTop: 8 }, tab: { flexDirection: 'row', minHeight: 48, alignItems: 'center', gap: 9, borderBottomWidth: 2, borderBottomColor: 'transparent' }, tabSelected: { borderBottomColor: colors.blue }, tabText: { fontFamily: fonts.sans, color: colors.mutedInk, fontSize: 14 }, tabTextSelected: { color: colors.ink }, tabCount: { fontFamily: fonts.mono, fontSize: 11, color: colors.mutedInk },
  regionRow: { gap: 7, paddingTop: 13, paddingBottom: 20 }, region: { minHeight: 44, paddingHorizontal: 12, justifyContent: 'center', borderWidth: 1, borderColor: colors.paperBorderSoft, borderRadius: 3 }, regionSelected: { borderColor: colors.ink, backgroundColor: colors.ink }, regionText: { fontFamily: fonts.sansRegular, fontSize: 11, color: colors.mutedInk }, regionTextSelected: { color: colors.paper },
  airportRow: { marginHorizontal: 24, marginBottom: 15 }, airlineRow: { marginHorizontal: 24, paddingVertical: 17, flexDirection: 'row', alignItems: 'center', gap: 14, borderBottomWidth: 1, borderBottomColor: colors.paperBorderSoft }, logo: { width: 32, alignItems: 'center' }, carrierCopy: { flex: 1, minWidth: 0, gap: 4 }, carrier: { fontFamily: fonts.sans, fontSize: 16, lineHeight: 22, color: colors.ink }, carrierMeta: { fontFamily: fonts.sansRegular, fontSize: 11, lineHeight: 17, color: colors.mutedInk }, empty: { padding: 24, gap: 8 }, emptyTitle: { fontFamily: fonts.display, fontSize: 26, color: colors.ink },
});
