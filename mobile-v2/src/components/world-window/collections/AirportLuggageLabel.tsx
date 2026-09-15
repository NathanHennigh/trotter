import React from 'react';
import { StyleSheet, Text, useWindowDimensions, View } from 'react-native';
import { colors, fonts } from '../../../theme/trotterTheme';
import { readableDate } from '../passport/passport-model';
import type { TransportEntry } from './transportCollectionModel';

export function AirportLuggageLabel({ entry, hero = false, year }: { entry: TransportEntry; hero?: boolean; year?: string }) {
  const { width, fontScale } = useWindowDimensions();
  const stacked = fontScale >= 1.35 || width < 350;
  const visited = Boolean(entry.lifetimeRecord ?? entry.record);
  const ink = visited ? colors.ink : '#687d82';
  const flights = entry.record?.flights ?? 0;
  return <View style={[s.tag, hero && s.hero, !visited && s.unvisited]}>
    <View pointerEvents="none" accessible={false} style={s.holeRail}>
      <View style={s.punch}><View style={s.hole} /></View>
      <View style={s.railLine} />
      <View style={[s.railEnd, { backgroundColor: visited ? colors.copper : colors.paperBorder }]} />
    </View>
    <View style={s.body}>
      <View style={s.top}><Text style={[s.country, { color: ink }]}>{entry.countryName || 'Airport'}</Text>
        {entry.countryKey && <Text style={[s.countryCode, { color: ink }]}>{entry.countryKey.replace('X-SOMALILAND', 'SML')}</Text>}</View>
      <View style={[s.identity, stacked && s.stacked]}>
        <Text style={[s.code, { color: ink }, hero && s.heroCode]}>{entry.key}</Text>
        <View style={[s.place, !stacked && s.placeRule]}>
          <Text style={[s.city, { color: ink }]}>{entry.city || entry.name}</Text>
          {hero && entry.city && entry.name !== entry.city && <Text style={s.airportName}>{entry.name}</Text>}
        </View>
      </View>
      <View style={s.footer}>
        <Text style={s.visit}>{entry.firstVisit ? `First visit · ${readableDate(entry.firstVisit)}` : visited ? 'Recorded in your archive' : 'Not yet visited'}</Text>
        {entry.record && <Text style={s.flights}>{flights} {flights === 1 ? 'flight' : 'flights'}{year ? ` · ${year}` : ''}</Text>}
        {!entry.record && visited && year && <Text style={s.flights}>No flights in {year}</Text>}
      </View>
    </View>
    <View pointerEvents="none" style={[s.bottomRule, { backgroundColor: visited ? colors.blue : colors.paperBorder }]} />
  </View>;
}

const s = StyleSheet.create({
  tag: { flexDirection: 'row', backgroundColor: '#FFFCF2', borderWidth: 1, borderColor: '#B7C4BB', borderRadius: 4, overflow: 'hidden', minHeight: 151 },
  hero: { marginTop: 6, marginBottom: 18 }, unvisited: { backgroundColor: '#F4F4EC', borderColor: colors.paperBorderSoft },
  holeRail: { width: 29, alignItems: 'center', paddingTop: 19, paddingBottom: 18, borderRightWidth: 1, borderRightColor: '#D9DED2', backgroundColor: '#F0ECDC' },
  punch: { height: 13, width: 13, borderRadius: 7, borderWidth: 1, borderColor: '#B7C4BB', alignItems: 'center', justifyContent: 'center' },
  hole: { width: 7, height: 7, borderRadius: 4, backgroundColor: colors.paperSoft, borderWidth: 1, borderColor: '#D1D2C5' },
  railLine: { width: 1, flex: 1, minHeight: 20, backgroundColor: '#CECFC1', marginVertical: 10 }, railEnd: { width: 7, height: 22 },
  body: { flex: 1, minWidth: 0, paddingHorizontal: 16, paddingTop: 12, paddingBottom: 15 },
  top: { flexDirection: 'row', alignItems: 'flex-start', gap: 8 }, country: { flex: 1, fontFamily: fonts.sans, fontSize: 10, letterSpacing: .9, textTransform: 'uppercase', lineHeight: 15 },
  countryCode: { fontFamily: fonts.mono, fontSize: 10, lineHeight: 15 },
  identity: { flexDirection: 'row', alignItems: 'center', gap: 16, marginTop: 11, marginBottom: 12 }, stacked: { flexDirection: 'column', alignItems: 'flex-start', gap: 5 },
  code: { fontFamily: fonts.mono, fontSize: 38, letterSpacing: -1.5, lineHeight: 47 }, heroCode: { fontSize: 44, lineHeight: 52 },
  place: { flex: 1, minWidth: 0 }, placeRule: { borderLeftWidth: 1, borderLeftColor: '#CDD4C9', paddingLeft: 14 },
  city: { fontFamily: fonts.display, fontSize: 22, lineHeight: 25 }, airportName: { fontFamily: fonts.sansRegular, fontSize: 12, color: colors.mutedInk, lineHeight: 18, marginTop: 5 },
  footer: { borderTopWidth: 1, borderTopColor: '#D8DDCF', paddingTop: 9, gap: 4 }, visit: { fontFamily: fonts.sansRegular, fontSize: 11, color: colors.mutedInk, lineHeight: 16 },
  flights: { fontFamily: fonts.mono, fontSize: 10, color: colors.ink, lineHeight: 16 }, bottomRule: { position: 'absolute', bottom: 0, right: 0, left: 29, height: 3 },
});
