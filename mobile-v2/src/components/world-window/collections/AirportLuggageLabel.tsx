import React from 'react';
import { StyleSheet, Text, useWindowDimensions, View } from 'react-native';
import Svg, { Circle, Path } from 'react-native-svg';
import { colors, fonts } from '../../../theme/trotterTheme';
import { readableDate } from '../passport/passport-model';
import type { TransportEntry } from './transportCollectionModel';

// Three pieces let the clipped shoulders follow the text's natural height. There
// is no measured SVG background to resize after the label's first native frame.
function PunchedHead({ paper, border, earned }: { paper: string; border: string; earned: boolean }) {
  return <View pointerEvents="none" accessible={false} style={s.head}>
    <Svg width={36} height={22} viewBox="0 0 36 22">
      <Path d="M36 .5H22L.5 22H36Z" fill={paper} />
      <Path d="M36 .5H22L.5 22" fill="none" stroke={border} strokeWidth={1} />
    </Svg>
    <View style={[s.headMiddle, { backgroundColor: paper, borderLeftColor: border }]}>
      <Svg width={20} height={20} viewBox="0 0 20 20">
        <Circle cx={10} cy={10} r={8} fill={earned ? '#EEE4CF' : '#ECEBE3'} stroke={earned ? '#C4AB85' : border} strokeWidth={.75} />
        <Circle cx={10} cy={10} r={3.75} fill={colors.paperSoft} stroke={earned ? '#AD9676' : border} strokeWidth={.8} />
      </Svg>
    </View>
    <Svg width={36} height={22} viewBox="0 0 36 22">
      <Path d="M.5 0L22 21.5H36V0Z" fill={paper} />
      <Path d="M.5 0L22 21.5H36" fill="none" stroke={border} strokeWidth={1} />
    </Svg>
  </View>;
}

export function AirportLuggageLabel({ entry, hero = false, year }: { entry: TransportEntry; hero?: boolean; year?: string }) {
  const { width, fontScale } = useWindowDimensions();
  const stacked = fontScale >= 1.35 || width < 350 || Boolean(year);
  const visited = Boolean(entry.lifetimeRecord ?? entry.record);
  const paper = visited ? '#FFFCF2' : '#F4F4ED';
  const border = visited ? '#C9C8B8' : colors.paperBorderSoft;
  const ink = visited ? colors.ink : '#748186';
  const flights = entry.record?.flights ?? 0;
  return <View testID="airport-luggage-label" style={[s.tag, hero && s.hero]}>
    <PunchedHead paper={paper} border={border} earned={visited} />
    <View style={[s.body, { backgroundColor: paper, borderColor: border }]}>
      <Text style={[s.country, { color: visited ? colors.mutedInk : ink }]}>{entry.countryName || 'Airport'}</Text>
      <Text testID="airport-luggage-code" maxFontSizeMultiplier={1.25} numberOfLines={1} adjustsFontSizeToFit minimumFontScale={.5} style={[s.code, hero && width >= 350 && s.heroCode, { color: ink }]}>{entry.key}</Text>
      <Text style={[s.city, { color: ink }]}>{entry.city || entry.name}</Text>
      {hero && entry.city && entry.name !== entry.city && <Text style={s.airportName}>{entry.name}</Text>}
      <View style={[s.footer, stacked && s.footerStacked]}>
        <Text style={s.visit}>{entry.firstVisit ? `First visit · ${readableDate(entry.firstVisit)}` : visited ? 'Recorded in your archive' : 'Not yet visited'}</Text>
        {entry.record && <Text style={s.flights}>{flights} {flights === 1 ? 'flight' : 'flights'}{year ? ` · ${year}` : ''}</Text>}
        {!entry.record && visited && year && <Text style={s.flights}>No flights in {year}</Text>}
      </View>
    </View>
  </View>;
}

const s = StyleSheet.create({
  tag: { flexDirection: 'row', minHeight: 157 },
  hero: { marginTop: 6, marginBottom: 18 },
  head: { width: 36 },
  headMiddle: { flex: 1, minHeight: 25, borderLeftWidth: 1, alignItems: 'center', justifyContent: 'center' },
  body: { flex: 1, minWidth: 0, borderTopWidth: 1, borderRightWidth: 1, borderBottomWidth: 1, borderTopRightRadius: 2, borderBottomRightRadius: 2, paddingLeft: 9, paddingRight: 16, paddingTop: 13, paddingBottom: 12 },
  country: { fontFamily: fonts.sans, fontSize: 10, letterSpacing: .85, textTransform: 'uppercase', lineHeight: 14 },
  code: { fontFamily: fonts.sansBold, fontSize: 64, letterSpacing: -2.4, lineHeight: 69, marginTop: 1 },
  heroCode: { fontSize: 76, lineHeight: 80, marginTop: 3 },
  city: { fontFamily: fonts.sans, fontSize: 15, lineHeight: 21 },
  airportName: { fontFamily: fonts.sansRegular, fontSize: 12, color: colors.mutedInk, lineHeight: 18, marginTop: 4 },
  footer: { borderTopWidth: 1, borderTopColor: '#DEDCCE', paddingTop: 8, marginTop: 11, flexDirection: 'row', flexWrap: 'wrap', alignItems: 'baseline', justifyContent: 'space-between', columnGap: 8, rowGap: 3 },
  footerStacked: { flexDirection: 'column', alignItems: 'flex-start', gap: 3 },
  visit: { fontFamily: fonts.sansRegular, fontSize: 10, color: colors.mutedInk, lineHeight: 15, flexShrink: 1 },
  flights: { fontFamily: fonts.sans, fontSize: 10, color: colors.mutedInk, lineHeight: 15, flexShrink: 1 },
});
