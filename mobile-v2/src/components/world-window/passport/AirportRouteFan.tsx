import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import Svg, { Circle, G, Path, Rect, Text as SvgText } from 'react-native-svg';
import world from '../../../data/worldCountries.json';
import { tripAtlasGeometry } from '../trips/tripAtlasGeometry';
import { airportPresentation } from './airport-presentation';
import { readableDate, type AirportRecord } from './passport-model';
import type { TripSummary } from '../../../data/trotterMock';
import { colors, fonts } from '../../../theme/trotterTheme';
import { WWIcon } from '../WorldWindowUI';

export function AirportRouteFan({ airport, onOpenTrip }: { airport: AirportRecord; onOpenTrip?: (trip: TripSummary) => void }) {
  const [selectedId, setSelectedId] = React.useState<string>();
  const fan = React.useMemo(() => airportPresentation(airport, selectedId), [airport, selectedId]);
  const map = React.useMemo(() => tripAtlasGeometry(fan.segments, world, airport.code), [fan.segments, airport.code]);
  const selectedPorts = new Set(fan.selected?.trip.segments?.flatMap(s => [s.depAirport, s.arrAirport]) ?? []);
  return <View>{map.ports.length > 0 && <><View style={s.map} accessible accessibilityRole="image" accessibilityLabel={`${fan.routeCount} routes through ${airport.code}${fan.selected ? ', highlighting ' + fan.selected.trip.title : ''}`}>
    <Svg width="100%" height="100%" viewBox="0 0 400 230" fill="none">
      <Path d="M0 46h400M0 92h400M0 138h400M0 184h400M50 0v230M100 0v230M150 0v230M200 0v230M250 0v230M300 0v230M350 0v230" stroke="#9eb5b3" strokeWidth={.6} opacity={.4}/>
      <Path d={map.landPath} fill="#dfe7df" stroke="#91aaa9" strokeWidth={.55} fillRule="evenodd"/>
      {map.paths.map((d, i) => <Path key={i} d={d} stroke={fan.selected && fan.highlighted[i] ? '#995f3e' : '#427494'} strokeWidth={fan.selected && fan.highlighted[i] ? 1.8 : 1.3} opacity={fan.selected && !fan.highlighted[i] ? .15 : .9}/>)}
      {map.ports.map(p => <G key={p.code} opacity={fan.selected && p.code !== airport.code && !selectedPorts.has(p.code) ? .25 : 1}>
        <Circle cx={p.x} cy={p.y} r={p.code === airport.code ? 4.2 : 2.7} fill={p.code === airport.code ? '#b27655' : '#faf8f1'} stroke={p.code === airport.code ? '#faf8f1' : '#427494'} strokeWidth={1.2}/>
        {p.label && <G><Rect x={p.label.x - 3} y={p.label.y - 1} width={p.label.width + 6} height={p.label.height + 1} rx={2} fill="#f8f6ed"/><SvgText x={p.label.x} y={p.label.y + 12} fontFamily={fonts.mono} fontSize={12} fill={p.code === airport.code ? '#965e42' : '#315b70'}>{p.code}</SvgText></G>}
      </G>)}
    </Svg>
  </View><View style={s.caption}><Text style={s.captionText}>{fan.selected ? fan.selected.trip.city || fan.selected.trip.title : `${fan.routeCount} routes · ${fan.journeys.length} journeys`}</Text>{fan.selected && <Pressable style={s.clear} accessibilityRole="button" accessibilityLabel="Show all airport routes" onPress={() => setSelectedId(undefined)}><WWIcon name="close" size={17}/></Pressable>}</View></>}
  <View>{fan.journeys.map(({ trip, incident }) => <View key={trip.id} style={[s.journey, selectedId === trip.id && s.selected]}><Pressable accessibilityRole="button" accessibilityState={{ selected: selectedId === trip.id }} onPress={() => setSelectedId(selectedId === trip.id ? undefined : trip.id)} style={s.journeyCopy}><Text style={s.city}>{trip.city || trip.title}</Text><Text style={s.dates}>{readableDate(trip.startDate)} – {readableDate(trip.endDate)}</Text><Text style={s.count}>{incident.length} flights through {airport.code}</Text></Pressable>{onOpenTrip && <Pressable style={s.open} accessibilityLabel={`Open ${trip.city || trip.title} itinerary`} accessibilityRole="button" onPress={() => onOpenTrip(trip)}><WWIcon name="arrow" size={18}/></Pressable>}</View>)}</View>
  </View>;
}
const s = StyleSheet.create({
  map: { width: '100%', aspectRatio: 400 / 230, backgroundColor: '#f8f6ed', borderWidth: 1, borderColor: '#c2cfca', borderRadius: 2, overflow: 'hidden', marginTop: 20 },
  caption: { flexDirection: 'row', alignItems: 'center', minHeight: 44, borderBottomWidth: 1, borderBottomColor: colors.paperBorder, paddingHorizontal: 10, marginBottom: 12 },
  captionText: { flex: 1, fontFamily: fonts.sansRegular, fontSize: 12, color: colors.mutedInk },
  clear: { width: 40, minHeight: 44, alignItems: 'center', justifyContent: 'center' },
  journey: { flexDirection: 'row', alignItems: 'center', borderBottomWidth: 1, borderBottomColor: colors.paperBorder },
  selected: { backgroundColor: '#e4eeea' },
  journeyCopy: { flex: 1, paddingVertical: 15, gap: 6 },
  city: { fontFamily: fonts.display, fontSize: 23, lineHeight: 27, color: colors.ink },
  dates: { fontFamily: fonts.sansRegular, fontSize: 13, lineHeight: 19, color: colors.mutedInk },
  count: { fontFamily: fonts.sansRegular, fontSize: 12, lineHeight: 18, color: colors.mutedInk },
  open: { width: 44, alignSelf: 'stretch', alignItems: 'center', justifyContent: 'center' },
});
