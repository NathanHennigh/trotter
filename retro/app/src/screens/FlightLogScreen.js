import React from 'react';
import { View, Text, TouchableOpacity, ScrollView, StyleSheet } from 'react-native';
import { FLIGHTS, TOTAL_MI } from '../data/flights';

export default function FlightLogScreen({ onBack }) {
  return (
    <View style={s.container}>
      {/* Header */}
      <View style={s.header}>
        <Text style={s.headerTitle}>FLIGHT LOG</Text>
        <TouchableOpacity onPress={onBack}>
          <Text style={s.backBtn}>← HOME</Text>
        </TouchableOpacity>
      </View>

      <ScrollView style={s.body} contentContainerStyle={{ paddingBottom: 40 }}>
        {/* Receipt top */}
        <View style={s.receiptTop}>
          <Text style={s.receiptTitleArt}>* TROTTER *</Text>
          <Text style={s.receiptSub}>FLIGHT MANIFEST — 2024/25</Text>
          <View style={s.receiptDivider} />
        </View>

        {/* Receipt paper */}
        <View style={s.receiptPaper}>
          {/* Column headers */}
          <View style={[s.row, { borderBottomColor: '#c0b090', borderBottomWidth: 1, paddingBottom: 4, marginBottom: 4 }]}>
            <Text style={s.colHeader}>FLIGHT</Text>
            <Text style={s.colHeader}>DATE</Text>
            <Text style={s.colHeader}>MILES</Text>
          </View>

          {FLIGHTS.map(f => (
            <View key={f.id} style={s.flightItem}>
              <View style={s.row}>
                <Text style={s.flightRoute}>{f.from} → {f.to}</Text>
                <Text style={s.flightMeta}>{f.date}</Text>
                <Text style={s.flightMiles}>{f.mi.toLocaleString()}</Text>
              </View>
              <View style={s.row}>
                <Text style={s.flightSubMeta}>{f.carrier}</Text>
                <Text style={s.flightSubMeta}>DUR: {f.dur}</Text>
              </View>
            </View>
          ))}

          {/* Totals */}
          <View style={[s.row, { borderTopWidth: 2, borderTopColor: '#3a3020', paddingTop: 6, marginTop: 4 }]}>
            <Text style={s.totalLabel}>TOTAL FLIGHTS</Text>
            <Text style={s.totalValue}>{FLIGHTS.length} SECTORS</Text>
          </View>
          <View style={s.row}>
            <Text style={s.totalLabel}>LIFETIME MILES</Text>
            <Text style={[s.totalValue, { color: '#e8006f' }]}>{TOTAL_MI.toLocaleString()} MI</Text>
          </View>

          <Text style={s.endOfLog}>
            {'*** END OF LOG ***\nPRINTED 22-APR-2026'}
          </Text>
        </View>
      </ScrollView>
    </View>
  );
}

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
    fontWeight: '900',
    letterSpacing: 2,
    color: '#e8006f',
    textTransform: 'uppercase',
  },
  body: { flex: 1, backgroundColor: '#f0ead8' },
  receiptTop: {
    backgroundColor: '#f5f0e0',
    marginHorizontal: 16,
    padding: 12,
    borderTopLeftRadius: 4,
    borderTopRightRadius: 4,
    alignItems: 'center',
    shadowColor: '#8a7d5a',
    shadowOffset: { width: 3, height: 0 },
    shadowOpacity: 1,
    shadowRadius: 0,
  },
  receiptTitleArt: {
    fontFamily: 'SpaceMono',
    fontSize: 14,
    fontWeight: 'bold',
    letterSpacing: 5,
    color: '#1a1408',
    marginBottom: 4,
  },
  receiptSub: {
    fontFamily: 'SpaceMono',
    fontSize: 9,
    letterSpacing: 2,
    color: '#8a7a5a',
    marginBottom: 4,
  },
  receiptDivider: { height: 1, backgroundColor: '#c0b090', width: '100%' },
  receiptPaper: {
    backgroundColor: '#f5f0e0',
    marginHorizontal: 16,
    padding: 14,
    borderBottomLeftRadius: 4,
    borderBottomRightRadius: 4,
    shadowColor: '#8a7d5a',
    shadowOffset: { width: 3, height: 3 },
    shadowOpacity: 1,
    shadowRadius: 0,
    elevation: 4,
  },
  row: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  colHeader: {
    fontFamily: 'SpaceMono',
    fontSize: 9,
    color: '#8a7a5a',
    flex: 1,
    textAlign: 'center',
  },
  flightItem: {
    borderBottomWidth: 1,
    borderBottomColor: '#d0c8a8',
    borderStyle: 'dashed',
    paddingBottom: 5,
    marginBottom: 5,
  },
  flightRoute: { fontFamily: 'SpaceMono', fontSize: 11, fontWeight: 'bold', color: '#1a1408', flex: 1 },
  flightMeta: { fontFamily: 'SpaceMono', fontSize: 10, color: '#5a4a30', flex: 1, textAlign: 'center' },
  flightMiles: { fontFamily: 'SpaceMono', fontSize: 10, color: '#e8006f', flex: 1, textAlign: 'right' },
  flightSubMeta: { fontFamily: 'SpaceMono', fontSize: 9, color: '#8a7a5a' },
  totalLabel: { fontFamily: 'SpaceMono', fontSize: 11, fontWeight: 'bold', color: '#1a1408' },
  totalValue: { fontFamily: 'SpaceMono', fontSize: 11, color: '#1a1408' },
  endOfLog: {
    fontFamily: 'SpaceMono',
    fontSize: 8,
    color: '#c0b090',
    letterSpacing: 2,
    textAlign: 'center',
    marginTop: 12,
    lineHeight: 16,
  },
});
