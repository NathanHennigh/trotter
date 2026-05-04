import React, { useEffect, useState } from 'react';
import { View, Text, TouchableOpacity, ScrollView, StyleSheet } from 'react-native';
import { TOTAL_MI } from '../data/flights';

function NixieCount({ target, duration = 1800 }) {
  const [n, setN] = useState(0);
  useEffect(() => {
    const start = Date.now();
    let raf;
    const tick = () => {
      const p = Math.min(1, (Date.now() - start) / duration);
      const e = 1 - Math.pow(1 - p, 3);
      setN(Math.floor(e * target));
      if (p < 1) raf = requestAnimationFrame(tick);
      else setN(target);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target, duration]);
  return <>{n.toLocaleString()}</>;
}

const TOP_ROUTES = [
  ['JFK', 'LHR', 8],
  ['DXB', 'SIN', 5],
  ['NRT', 'LAX', 4],
  ['LAX', 'JFK', 6],
];

const STATUS_ROWS = [
  ['ELITE STATUS', 'GOLD TIER'],
  ['NEXT MILESTONE', '25,000 MI'],
  ['REMAINING', '3,208 MI'],
  ['AVG FLIGHT', '3,632 MI'],
];

export default function StatsScreen({ onBack }) {
  return (
    <View style={s.container}>
      <View style={s.header}>
        <Text style={s.headerTitle}>TRAVEL STATS</Text>
        <TouchableOpacity onPress={onBack}>
          <Text style={s.backBtn}>← HOME</Text>
        </TouchableOpacity>
      </View>

      <ScrollView style={s.body} contentContainerStyle={{ gap: 12, padding: 16, paddingBottom: 40 }}>
        {/* Lifetime Miles */}
        <View style={s.nixieModule}>
          <Text style={s.nixieLabel}>LIFETIME MILES</Text>
          <Text style={s.nixieValue}><NixieCount target={TOTAL_MI} duration={1800} /></Text>
          <Text style={s.nixieUnit}>NAUTICAL MILES LOGGED</Text>
        </View>

        {/* Flights + Countries */}
        <View style={{ flexDirection: 'row', gap: 12 }}>
          <View style={[s.nixieModule, { flex: 1 }]}>
            <Text style={s.nixieLabel}>FLIGHTS</Text>
            <Text style={[s.nixieValue, { fontSize: 30 }]}><NixieCount target={22} duration={1000} /></Text>
            <Text style={s.nixieUnit}>TOTAL SECTORS</Text>
          </View>
          <View style={[s.nixieModule, { flex: 1 }]}>
            <Text style={s.nixieLabel}>COUNTRIES</Text>
            <Text style={[s.nixieValue, { fontSize: 30 }]}><NixieCount target={14} duration={1200} /></Text>
            <Text style={s.nixieUnit}>VISITED</Text>
          </View>
        </View>

        {/* Top Routes */}
        <View style={s.routeModule}>
          <Text style={s.routeLabel}>// TOP ROUTES //</Text>
          {TOP_ROUTES.map(([a, b, n], i) => (
            <View key={i} style={s.routeRow}>
              <Text style={s.routeText}>{a}</Text>
              <Text style={s.routeArrow}>————→</Text>
              <Text style={s.routeText}>{b}</Text>
              <Text style={s.routeCount}>×{n}</Text>
            </View>
          ))}
        </View>

        {/* Status */}
        <View style={s.statusModule}>
          <Text style={s.routeLabel}>// STATUS //</Text>
          {STATUS_ROWS.map(([k, v], i) => (
            <View key={i} style={s.statusRow}>
              <Text style={s.statusKey}>{k}</Text>
              <Text style={s.statusVal}>{v}</Text>
            </View>
          ))}
        </View>
      </ScrollView>
    </View>
  );
}

const GREEN = '#6ab04c';

const s = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#d4c8a8' },
  header: {
    backgroundColor: '#1a1a1a',
    paddingTop: 52,
    paddingHorizontal: 20,
    paddingBottom: 14,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 1,
    shadowRadius: 0,
    elevation: 8,
  },
  headerTitle: {
    fontFamily: 'SpaceMono',
    fontSize: 11,
    fontWeight: '900',
    letterSpacing: 4,
    color: '#ccc5a0',
    textTransform: 'uppercase',
  },
  backBtn: {
    fontFamily: 'SpaceMono',
    fontSize: 9,
    color: '#e8006f',
    textTransform: 'uppercase',
    letterSpacing: 2,
  },
  body: { flex: 1 },
  nixieModule: {
    backgroundColor: '#0a1205',
    borderRadius: 6,
    padding: 14,
    borderWidth: 2,
    borderColor: '#050a02',
    shadowColor: '#2a4010',
    shadowOffset: { width: 4, height: 4 },
    shadowOpacity: 1,
    shadowRadius: 0,
    elevation: 4,
  },
  nixieLabel: {
    fontFamily: 'SpaceMono',
    fontSize: 8,
    fontWeight: '900',
    letterSpacing: 3,
    color: '#2d5a1b',
    textTransform: 'uppercase',
    marginBottom: 6,
  },
  nixieValue: {
    fontFamily: 'SpaceMono',
    fontSize: 38,
    color: GREEN,
    textShadowColor: `rgba(139,195,74,0.8)`,
    textShadowOffset: { width: 0, height: 0 },
    textShadowRadius: 12,
    letterSpacing: 3,
    lineHeight: 42,
  },
  nixieUnit: {
    fontFamily: 'SpaceMono',
    fontSize: 8,
    fontWeight: '900',
    letterSpacing: 3,
    color: '#4a7c2f',
    textTransform: 'uppercase',
    marginTop: 4,
  },
  routeModule: {
    backgroundColor: '#1a1608',
    borderRadius: 6,
    padding: 12,
    borderWidth: 2,
    borderColor: '#0a0d06',
    shadowColor: '#5a4020',
    shadowOffset: { width: 4, height: 4 },
    shadowOpacity: 1,
    shadowRadius: 0,
    elevation: 4,
  },
  routeLabel: {
    fontFamily: 'SpaceMono',
    fontSize: 8,
    fontWeight: '900',
    letterSpacing: 3,
    color: '#804020',
    textTransform: 'uppercase',
    marginBottom: 8,
  },
  routeRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 4,
    borderBottomWidth: 1,
    borderBottomColor: '#2a1a08',
    gap: 8,
  },
  routeText: {
    fontFamily: 'SpaceMono',
    fontSize: 12,
    color: '#ff9500',
    textShadowColor: 'rgba(255,149,0,0.6)',
    textShadowOffset: { width: 0, height: 0 },
    textShadowRadius: 6,
  },
  routeArrow: { fontFamily: 'SpaceMono', fontSize: 10, color: '#804020', flex: 1 },
  routeCount: { fontFamily: 'SpaceMono', fontSize: 10, color: '#5a3010' },
  statusModule: {
    backgroundColor: '#1a1608',
    borderRadius: 6,
    padding: 14,
    borderWidth: 2,
    borderColor: '#0a0d06',
    shadowColor: '#5a4020',
    shadowOffset: { width: 4, height: 4 },
    shadowOpacity: 1,
    shadowRadius: 0,
    elevation: 4,
  },
  statusRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    paddingVertical: 3,
    borderBottomWidth: 1,
    borderBottomColor: '#1a1a08',
  },
  statusKey: {
    fontFamily: 'SpaceMono',
    fontSize: 10,
    color: '#5a3010',
    textTransform: 'uppercase',
    letterSpacing: 1,
  },
  statusVal: {
    fontFamily: 'SpaceMono',
    fontSize: 10,
    color: '#ff9500',
    textShadowColor: 'rgba(255,149,0,0.5)',
    textShadowOffset: { width: 0, height: 0 },
    textShadowRadius: 4,
  },
});
