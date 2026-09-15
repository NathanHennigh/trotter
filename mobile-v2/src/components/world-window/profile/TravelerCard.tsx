import React from 'react';
import { StyleSheet, Text, useWindowDimensions, View } from 'react-native';
import Svg, { Circle, Path } from 'react-native-svg';
import world from '../../../data/worldCountries.json';
import type { TripSegmentSummary } from '../../../data/trotterMock';
import { colors, fonts } from '../../../theme/trotterTheme';
import { createTripAtlasGeometryCache } from '../trips/tripAtlasGeometry';
import { fitDisplayFont } from '../displayTextFit';
import { WWEmblem, WWIcon } from '../WorldWindowUI';
import { PressFeedback } from '../motion';
import { getMobileVisualWidth } from '../../../utils/mobileLayout';

const geometry = createTripAtlasGeometryCache();
export function TravelerCard({ name, firstYear, homeAirport, homeCity, segments, ready, onChooseHome, onOpenAirport }: {
  name: string; firstYear?: string; homeAirport?: string; homeCity?: string; segments: TripSegmentSummary[]; ready: boolean;
  onChooseHome: () => void; onOpenAirport?: (code: string) => void;
}) {
  const { width, fontScale } = useWindowDimensions();
  const visualWidth = getMobileVisualWidth(width);
  const large = fontScale >= 1.35 || visualWidth < 350;
  const size = fitDisplayFont(name, 33, Math.min(visualWidth, 640) - 96, fontScale);
  const map = React.useMemo(() => geometry(segments, world, homeAirport, { maxLabels: 0 }), [segments, homeAirport]);
  return <View style={s.card} testID="traveler-card">
    <View pointerEvents="none" style={s.innerRule} />
    <View style={s.top}><Text style={s.brand}>TROTTER</Text><WWEmblem size={43} color={colors.blue} /></View>
    <Text accessibilityRole="header" style={[s.name, { fontSize: size, lineHeight: size * 1.12 }]}>{name}</Text>
    <View style={[s.identity, large && s.identityLarge]}>
      <View style={s.home}>
        <Text style={s.label}>HOME AIRPORT</Text>
        <PressFeedback accessibilityRole="button" disabled={!ready} accessibilityLabel={homeAirport && onOpenAirport ? `View ${homeAirport} airport history` : 'Choose home airport'}
          onPress={() => homeAirport && onOpenAirport ? onOpenAirport(homeAirport) : onChooseHome()} style={s.airportButton}>
          <Text style={homeAirport ? s.code : s.choose}>{homeAirport || (ready ? 'Choose airport' : 'Loading…')}</Text>
          {homeAirport && onOpenAirport ? <WWIcon name="arrow" size={16} color={colors.blue} /> : null}
        </PressFeedback>
        {homeCity ? <Text style={s.city}>{homeCity}</Text> : null}
      </View>
      {segments.length > 0 ? <View testID="traveler-route-signature" pointerEvents="none" accessible={false} accessibilityElementsHidden importantForAccessibility="no-hide-descendants" style={[s.routeSignature, large && s.routeSignatureLarge]}>
        <Svg width="100%" height="100%" viewBox="0 0 400 230">
          <Path d={map.landPath} fill="#EDF0E6" stroke="#C3CEC5" strokeWidth={1} fillRule="evenodd" />
          {map.paths.map((d, i) => <Path key={i} d={d} fill="none" stroke="#66899A" strokeWidth={1.35} strokeLinecap="round" />)}
          {map.ports.map(port => <Circle key={port.code} cx={port.x} cy={port.y} r={2.3} fill={port.code === homeAirport ? colors.copper : colors.blue} />)}
        </Svg>
      </View> : null}
    </View>
    {(firstYear || homeAirport) ? <View style={s.footer}>{firstYear ? <Text style={s.since}>First flight · {firstYear}</Text> : null}
      {homeAirport ? <PressFeedback accessibilityRole="button" accessibilityLabel="Change home airport" onPress={onChooseHome} style={s.change}><Text style={s.changeText}>Change airport</Text></PressFeedback> : null}
    </View> : null}
  </View>;
}
const s = StyleSheet.create({
  card: { backgroundColor: '#FFFCF1', borderWidth: 1, borderColor: '#B7C6C1', borderRadius: 5, padding: 22, paddingBottom: 8, shadowColor: '#31576B', shadowOpacity: .07, shadowOffset: { width: 0, height: 3 }, shadowRadius: 7, elevation: 1 },
  innerRule: { position: 'absolute', top: 6, left: 6, right: 6, bottom: 6, borderWidth: 1, borderColor: '#E0E2D4', borderRadius: 2 },
  top: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 12 }, brand: { fontFamily: fonts.sansSemi, fontSize: 11, letterSpacing: 3, color: colors.blue },
  name: { fontFamily: fonts.display, color: colors.ink, marginTop: 12, marginBottom: 18 },
  identity: { flexDirection: 'row', alignItems: 'center', gap: 12, borderTopWidth: 1, borderTopColor: '#D7DDD0', paddingTop: 12 }, identityLarge: { flexWrap: 'wrap' },
  home: { flex: 1, minWidth: 125 }, label: { fontFamily: fonts.mono, fontSize: 9, letterSpacing: .8, color: colors.mutedInk, lineHeight: 15 },
  airportButton: { minHeight: 44, flexDirection: 'row', alignItems: 'center', gap: 8 }, code: { fontFamily: fonts.sansBold, fontSize: 30, lineHeight: 36, color: colors.ink, letterSpacing: -.7 },
  choose: { fontFamily: fonts.sans, color: colors.blue, fontSize: 14, lineHeight: 20 }, city: { fontFamily: fonts.sansRegular, color: colors.mutedInk, fontSize: 11, lineHeight: 16, marginTop: -2 },
  routeSignature: { width: 122, height: 76, overflow: 'hidden' }, routeSignatureLarge: { width: '100%', height: 80 },
  footer: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between', gap: 8, marginTop: 10 },
  since: { fontFamily: fonts.sansRegular, color: colors.mutedInk, fontSize: 10, lineHeight: 16, paddingVertical: 10 },
  change: { minHeight: 44, justifyContent: 'center' }, changeText: { fontFamily: fonts.sans, color: colors.blue, fontSize: 10, lineHeight: 16 },
});
