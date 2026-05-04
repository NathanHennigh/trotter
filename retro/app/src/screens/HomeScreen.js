import React, { useEffect, useState, useRef } from 'react';
import {
  View, Text, TouchableOpacity, TouchableNativeFeedback,
  ScrollView, StyleSheet, Animated, Easing, Platform,
} from 'react-native';
import * as Haptics from 'expo-haptics';
import AsyncStorage from '@react-native-async-storage/async-storage';
import GlobeView from '../components/GlobeView';
import WorldMap from '../components/WorldMap';
import { useFlightsStore } from '../store/useFlightsStore';
import { FLIGHTS as DUMMY_FLIGHTS, TOTAL_MI as DUMMY_MI } from '../data/flights';
import { CASING, DISPLAY } from '../theme/colors';

// ── Flip digit counter ───────────────────────────────────────────────
function FlipCounter({ target, duration = 2000 }) {
  const [display, setDisplay] = useState(0);
  useEffect(() => {
    const start = Date.now();
    let raf;
    const tick = () => {
      const p = Math.min(1, (Date.now() - start) / duration);
      const eased = p < 0.5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2;
      setDisplay(Math.floor(eased * target));
      if (p < 1) raf = requestAnimationFrame(tick);
      else setDisplay(target);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target]);
  return (
    <View style={{ flexDirection: 'row', gap: 3 }}>
      {String(display).padStart(6, '0').split('').map((d, i) => (
        <View key={i} style={s.flipDigit}>
          <View style={s.flipHorzLine} />
          <Text style={s.flipDigitText}>{d}</Text>
        </View>
      ))}
    </View>
  );
}

// ── Toggle switch ────────────────────────────────────────────────────
function ToggleSwitch({ label, on, onChange, ledColor = '#4aff20' }) {
  const handlePress = () => {
    Haptics.selectionAsync();
    onChange();
  };
  return (
    <TouchableOpacity onPress={handlePress} style={s.toggleWrap} activeOpacity={0.8}>
      <View style={[s.toggleLed, { backgroundColor: on ? ledColor : '#1a1a1a', shadowColor: on ? ledColor : 'transparent', shadowOpacity: on ? 1 : 0, shadowRadius: 5 }]} />
      <View style={s.toggleBody}>
        <View style={[s.toggleLever, on ? s.leverOn : s.leverOff]} />
      </View>
      <Text style={s.toggleLabel}>{label}</Text>
    </TouchableOpacity>
  );
}

// ── Cassette window ──────────────────────────────────────────────────
function CassetteWindow({ syncing }) {
  const spinAnim = useRef(new Animated.Value(0)).current;
  const [ledOn, setLedOn] = useState(false);
  useEffect(() => {
    if (!syncing) { spinAnim.setValue(0); setLedOn(false); return; }
    const loop = Animated.loop(Animated.timing(spinAnim, { toValue: 1, duration: 800, easing: Easing.linear, useNativeDriver: true }));
    loop.start();
    const led = setInterval(() => setLedOn(l => !l), 80);
    return () => { loop.stop(); clearInterval(led); };
  }, [syncing]);

  const rotate = spinAnim.interpolate({ inputRange: [0, 1], outputRange: ['0deg', '360deg'] });
  return (
    <View style={s.cassetteWin}>
      <View style={[s.cassetteLed, syncing && ledOn && s.cassetteLedLit]} />
      <View style={{ flexDirection: 'row', gap: 12, alignItems: 'center' }}>
        {[1, -1].map((dir, i) => (
          <Animated.View key={i} style={{ transform: [{ rotate: dir === 1 ? rotate : '0deg' }] }}>
            <View style={s.spool}>
              <View style={s.spoolHub} />
            </View>
          </Animated.View>
        ))}
      </View>
      <Text style={s.cassetteLabel}>{syncing ? 'READ' : 'IDLE'}</Text>
    </View>
  );
}

// ── Chunky button ────────────────────────────────────────────────────
function ChunkyBtn({ label, onPress, style: extraStyle, textStyle }) {
  const pressAnim = useRef(new Animated.Value(0)).current;
  const handlePressIn = () => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    Animated.timing(pressAnim, { toValue: 1, duration: 60, useNativeDriver: true }).start();
  };
  const handlePressOut = () => {
    Animated.timing(pressAnim, { toValue: 0, duration: 80, useNativeDriver: true }).start();
    onPress?.();
  };
  const translateY = pressAnim.interpolate({ inputRange: [0, 1], outputRange: [0, 3] });
  return (
    <TouchableNativeFeedback onPressIn={handlePressIn} onPressOut={handlePressOut} background={TouchableNativeFeedback.Ripple('rgba(255,255,255,0.1)', false)}>
      <Animated.View style={[s.chunkyBtn, extraStyle, { transform: [{ translateY }] }]}>
        <Text style={[s.chunkyBtnText, textStyle]}>{label}</Text>
      </Animated.View>
    </TouchableNativeFeedback>
  );
}

// ── Home Screen ────────────────────────────────────────────────────────
export default function HomeScreen({ onNavigate, casingKey = 'beige', displayKey = 'amber' }) {
  const casing  = CASING[casingKey];
  const display = DISPLAY[displayKey];
  // Use real data from store, fall back to dummy for dev
  const storeFlights  = useFlightsStore(s => s.flights);
  const storeTotalMi  = useFlightsStore(s => s.totalMi);
  const flights = storeFlights.length > 0 ? storeFlights : DUMMY_FLIGHTS;
  const totalMi = storeFlights.length > 0 ? storeTotalMi : DUMMY_MI;

  const [activePath, setActivePath] = useState(0);
  const [mapMode, setMapMode]       = useState('globe');
  const [showPaths, setShowPaths]   = useState(true);
  const [showGrid, setShowGrid]     = useState(true);
  const [syncing, setSyncing]       = useState(false);
  const [time, setTime]             = useState(new Date());

  useEffect(() => {
    const t = setInterval(() => setTime(new Date()), 1000);
    return () => clearInterval(t);
  }, []);

  // Animate paths in on mount + whenever flights change
  useEffect(() => {
    setActivePath(0);
    if (flights.length === 0) return;
    let i = 0;
    const t = setInterval(() => {
      i++;
      setActivePath(i);
      if (i >= flights.length) clearInterval(t);
    }, 700);
    return () => clearInterval(t);
  }, [flights.length]);

  const handleSync = () => {
    if (syncing) return;
    onNavigate('import');
  };

  const pad2 = n => String(n).padStart(2, '0');
  const timeStr = `${pad2(time.getHours())}.${pad2(time.getMinutes())}`;
  const dateStr = `${pad2(time.getDate())}-${pad2(time.getMonth() + 1)}-${String(time.getFullYear()).slice(2)}`;

  // Screw positions
  const screwPositions = [
    { top: 14, left: 14 }, { top: 14, right: 14 },
    { bottom: 48, left: 14 }, { bottom: 48, right: 14 },
  ];

  return (
    <View style={[s.shell, { backgroundColor: casing.body }]}>
      {/* Corner screws */}
      {screwPositions.map((pos, i) => (
        <View key={i} style={[s.screw, pos]} />
      ))}

      {/* Status bar */}
      <View style={[s.statusBar, { backgroundColor: casing.mid, borderBottomColor: casing.dark }]}>
        <Text style={s.statusLabel}>{dateStr}</Text>
        <Text style={s.statusBrand}>TROTTER</Text>
        <Text style={s.statusLabel}>{timeStr}</Text>
      </View>

      {/* CRT Zone */}
      <View style={[s.crtZone, { borderBottomColor: casing.dark }]}>
        <View style={s.crtBezel}>
          <View style={[s.crtScreen, { backgroundColor: displayKey === 'amber' ? '#0e0500' : '#040c02' }]}>
            {mapMode === 'globe'
              ? <GlobeView
                  activePath={activePath}
                  displayMode={displayKey}
                  showGrid={showGrid}
                  showPaths={showPaths}
                  W={374} H={200}
                />
              : <WorldMap
                  activePath={activePath}
                  displayMode={displayKey}
                  showGrid={showGrid}
                  showPaths={showPaths}
                  W={374} H={200}
                />
            }
            <Text style={[s.crtLabel, { color: display.phosphor }]}>
              {mapMode === 'globe' ? 'ORTHOGRAPHIC GLOBE' : 'RADAR / FLIGHT MAP'}
            </Text>
            <Text style={[s.crtCoords, { color: display.phosphor }]}>
              {activePath > 0 ? `${Math.min(activePath, flights.length)}/${flights.length} PATHS` : 'AWAITING SYNC'}
            </Text>
          </View>
        </View>

        {/* View toggle bar */}
        <View style={[s.viewToggleBar, { borderTopColor: casing.dark }]}>
          {[{ id: 'map', label: '▦ MAP' }, { id: 'globe', label: '◉ GLOBE' }].map(({ id, label }) => (
            <TouchableOpacity key={id} style={[s.viewToggleBtn, mapMode === id && { backgroundColor: '#0d1f08' }]}
              onPress={() => { Haptics.selectionAsync(); setMapMode(id); }}>
              <Text style={[s.viewToggleBtnText, mapMode === id && { color: display.phosphor }]}>{label}</Text>
            </TouchableOpacity>
          ))}
        </View>
      </View>

      {/* Control Panel */}
      <ScrollView style={[s.controlPanel, { backgroundColor: casing.panel }]} contentContainerStyle={{ gap: 8, paddingBottom: 8 }} scrollEnabled={false}>
        {/* Stats row */}
        <View style={s.statsRow}>
          {/* Miles counter */}
          <View style={[s.milesModule, { backgroundColor: display.statBg, borderColor: display.statBorder, shadowColor: display.statShadow }]}>
            <Text style={[s.milesLabel, { color: display.label }]}>LIFETIME MI</Text>
            <FlipCounter target={totalMi} duration={2000} />
          </View>
          {/* Local time */}
          <View style={[s.statModule, { backgroundColor: '#1a0800', borderColor: '#0a0400', shadowColor: '#5a4020' }]}>
            <Text style={[s.statModuleLabel, { color: '#804020' }]}>LOCAL</Text>
            <Text style={[s.segDisplay, { color: '#ff9500' }]}>{timeStr}</Text>
          </View>
        </View>

        <View style={[s.panelDivider, { backgroundColor: casing.dark }]} />

        {/* Cassette + Toggles */}
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
          <CassetteWindow syncing={syncing} />
          <View style={{ flex: 1 }} />
          <View style={{ alignItems: 'center', gap: 3 }}>
            <Text style={s.layersLabel}>LAYERS</Text>
            <View style={{ flexDirection: 'row', gap: 8 }}>
              <ToggleSwitch label="PATHS" on={showPaths} onChange={() => setShowPaths(v => !v)} ledColor="#e8006f" />
              <ToggleSwitch label="GRID"  on={showGrid}  onChange={() => setShowGrid(v => !v)}  ledColor="#4a9a20" />
            </View>
          </View>
        </View>

        {/* Receipt slit */}
        <View style={s.receiptSlit} />

        {/* Recent flights snippet */}
        <View style={[s.receiptModule, { shadowColor: casing.dark }]}>
          <View style={s.receiptHeader}>
            <Text style={s.receiptHeaderText}>RECENT FLIGHTS</Text>
            <Text style={s.receiptScrollHint}>← SCROLL</Text>
          </View>
          <View style={s.receiptSlot}>
            {flights.slice(0, 3).map((f, idx) => (
              <View key={f.id ?? idx} style={s.receiptRow}>
                <Text style={s.receiptRoute}>{f.from}→{f.to}</Text>
                <Text style={s.receiptDate}>{f.date}</Text>
                <Text style={s.receiptMi}>{f.mi.toLocaleString()}mi</Text>
              </View>
            ))}
          </View>
        </View>

        <View style={[s.panelDivider, { backgroundColor: casing.dark }]} />

        {/* Buttons row */}
        <View style={s.buttonsRow}>
          <ChunkyBtn label="⟳ SYNC" onPress={handleSync}
            style={[s.chunkyBtnBase, { backgroundColor: '#e8006f', shadowColor: '#8a0040' }]}
            textStyle={{ color: '#fff' }} />
          <ChunkyBtn label="LOG" onPress={() => onNavigate('log')}
            style={[s.chunkyBtnBase, { backgroundColor: '#1a1a1a', shadowColor: '#000' }]}
            textStyle={{ color: '#ccc5a0' }} />
          <ChunkyBtn label="STATS" onPress={() => onNavigate('stats')}
            style={[s.chunkyBtnBase, { backgroundColor: '#2d4a1a', shadowColor: '#0a1a04' }]}
            textStyle={{ color: '#8bc34a' }} />
        </View>

        {/* Speaker grille */}
        <View style={[s.speakerGrille, { borderTopColor: casing.dark }]}>
          {Array.from({ length: 42 }).map((_, i) => (
            <View key={i} style={s.speakerDot} />
          ))}
        </View>

        {/* Stickers row */}
        <View style={s.stickersRow}>
          <View style={s.warningSticker}>
            <Text style={s.warningStickerText}>⚠ CAUTION: DATA LINK</Text>
          </View>
          <View style={{ flex: 1 }} />
          <View style={s.serialSticker}>
            <Text style={s.serialStickerText}>S/N TR0TT-MK2-260422</Text>
          </View>
        </View>
      </ScrollView>

      {/* Home indicator */}
      <View style={[s.homeInd, { backgroundColor: casing.mid, borderTopColor: casing.dark }]}>
        <View style={[s.homeBar, { backgroundColor: casing.dark }]} />
      </View>
    </View>
  );
}

const s = StyleSheet.create({
  shell: {
    flex: 1,
    borderRadius: 44,
    overflow: 'hidden',
    position: 'relative',
    shadowColor: '#000',
    shadowOffset: { width: 8, height: 12 },
    shadowOpacity: 0.4,
    shadowRadius: 0,
    elevation: 16,
  },
  screw: {
    position: 'absolute',
    width: 11, height: 11, borderRadius: 6,
    backgroundColor: '#b0a080',
    zIndex: 50,
    shadowColor: '#000',
    shadowOffset: { width: 1, height: 1 },
    shadowOpacity: 0.4,
    shadowRadius: 2,
    elevation: 2,
  },
  statusBar: {
    height: 48, flexDirection: 'row', alignItems: 'flex-end',
    justifyContent: 'space-between', paddingHorizontal: 24, paddingBottom: 8,
    borderBottomWidth: 2,
  },
  statusLabel: { fontFamily: 'SpaceMono', fontSize: 9, fontWeight: '900', letterSpacing: 2, color: '#3a3020', textTransform: 'uppercase' },
  statusBrand: { fontFamily: 'SpaceMono', fontSize: 11, fontWeight: '900', letterSpacing: 4, color: '#1a1a1a' },
  crtZone: { borderBottomWidth: 4 },
  crtBezel: {
    margin: 8, marginBottom: 0,
    backgroundColor: '#0a0d06', borderRadius: 6, overflow: 'hidden',
    borderWidth: 3, borderColor: '#050805',
    shadowColor: '#000', shadowOffset: { width: 0, height: 0 }, shadowOpacity: 0.9, shadowRadius: 24,
  },
  crtScreen: { height: 200, position: 'relative', overflow: 'hidden', borderRadius: 4 },
  crtLabel: {
    position: 'absolute', top: 5, left: 10,
    fontFamily: 'SpaceMono', fontSize: 8, fontWeight: '900', letterSpacing: 3, opacity: 0.5,
  },
  crtCoords: {
    position: 'absolute', bottom: 5, right: 10,
    fontFamily: 'SpaceMono', fontSize: 8, opacity: 0.45,
  },
  viewToggleBar: {
    height: 34, marginHorizontal: 8, backgroundColor: '#080c05',
    borderBottomLeftRadius: 6, borderBottomRightRadius: 6,
    borderWidth: 3, borderColor: '#050805', borderTopWidth: 1, borderTopColor: '#1a2a10',
    flexDirection: 'row', alignItems: 'center', paddingHorizontal: 24, gap: 0,
  },
  viewToggleBtn: {
    flex: 1, height: 22, backgroundColor: '#111', borderWidth: 1, borderColor: '#222',
    alignItems: 'center', justifyContent: 'center',
  },
  viewToggleBtnText: { fontFamily: 'SpaceMono', fontSize: 8, fontWeight: '900', letterSpacing: 2, color: '#3a3a3a' },
  controlPanel: { flex: 1, paddingHorizontal: 16, paddingTop: 12 },
  statsRow: { flexDirection: 'row', gap: 10, alignItems: 'stretch' },
  milesModule: {
    flex: 1.4, borderRadius: 4, padding: 8, borderWidth: 2,
    shadowOffset: { width: 3, height: 3 }, shadowOpacity: 1, shadowRadius: 0, elevation: 4,
  },
  milesLabel: { fontFamily: 'SpaceMono', fontSize: 7, fontWeight: '900', letterSpacing: 3, textTransform: 'uppercase', marginBottom: 3 },
  flipDigit: {
    width: 22, height: 30, backgroundColor: '#0f1f08', borderWidth: 1, borderColor: '#1a3010',
    borderRadius: 3, alignItems: 'center', justifyContent: 'center', overflow: 'hidden',
  },
  flipHorzLine: { position: 'absolute', top: '50%', left: 0, right: 0, height: 1, backgroundColor: 'rgba(0,0,0,0.6)' },
  flipDigitText: { fontFamily: 'SpaceMono', fontSize: 17, color: '#8bc34a', textShadowColor: 'rgba(139,195,74,0.7)', textShadowOffset: { width: 0, height: 0 }, textShadowRadius: 6 },
  statModule: {
    flex: 1, borderRadius: 4, padding: 8, borderWidth: 2,
    shadowOffset: { width: 3, height: 3 }, shadowOpacity: 1, shadowRadius: 0, elevation: 4,
  },
  statModuleLabel: { fontFamily: 'SpaceMono', fontSize: 7, fontWeight: '900', letterSpacing: 3, textTransform: 'uppercase', marginBottom: 2 },
  segDisplay: { fontFamily: 'SpaceMono', fontSize: 22, textShadowColor: 'rgba(255,149,0,0.8)', textShadowOffset: { width: 0, height: 0 }, textShadowRadius: 8 },
  panelDivider: { height: 2 },
  layersLabel: { fontFamily: 'SpaceMono', fontSize: 7, fontWeight: '900', letterSpacing: 2, color: 'rgba(55,45,25,0.55)', textTransform: 'uppercase' },
  toggleWrap: { alignItems: 'center', gap: 2 },
  toggleLed: { width: 5, height: 5, borderRadius: 3 },
  toggleBody: { width: 14, height: 26, backgroundColor: '#1c1c1c', borderRadius: 3, borderWidth: 1, borderColor: '#0a0a0a', alignItems: 'center', justifyContent: 'center' },
  toggleLever: { width: 10, height: 10, backgroundColor: '#555', borderRadius: 2, borderWidth: 1, borderColor: '#222', position: 'absolute' },
  leverOn:  { top: 3 },
  leverOff: { bottom: 3 },
  toggleLabel: { fontFamily: 'SpaceMono', fontSize: 6, fontWeight: '900', letterSpacing: 1, color: 'rgba(55,45,25,0.65)', textTransform: 'uppercase' },
  cassetteWin: {
    width: 74, height: 46, backgroundColor: '#08080a', borderRadius: 5,
    borderWidth: 2, borderColor: '#050506', alignItems: 'center', justifyContent: 'center',
    shadowColor: '#000', shadowOffset: { width: 0, height: 0 }, shadowOpacity: 0.9, shadowRadius: 5,
  },
  cassetteLed: { position: 'absolute', top: 5, right: 6, width: 5, height: 5, borderRadius: 3, backgroundColor: '#1a0000' },
  cassetteLedLit: { backgroundColor: '#ff2020', shadowColor: '#ff2020', shadowOpacity: 1, shadowRadius: 7 },
  spool: { width: 16, height: 16, borderRadius: 8, backgroundColor: '#141410', borderWidth: 1, borderColor: '#2a2a20', alignItems: 'center', justifyContent: 'center' },
  spoolHub: { width: 6, height: 6, borderRadius: 3, backgroundColor: '#0a0a08' },
  cassetteLabel: { position: 'absolute', bottom: 3, fontFamily: 'SpaceMono', fontSize: 6, fontWeight: '900', letterSpacing: 2, color: 'rgba(80,70,40,0.5)', textTransform: 'uppercase' },
  receiptSlit: { height: 10, backgroundColor: '#0a0800', marginHorizontal: -16 },
  receiptModule: { backgroundColor: '#f5f0e0', borderRadius: 2, overflow: 'hidden', shadowOffset: { width: 3, height: 3 }, shadowOpacity: 1, shadowRadius: 0, elevation: 4 },
  receiptHeader: { backgroundColor: '#1a1a1a', padding: 4, paddingHorizontal: 10, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  receiptHeaderText: { fontFamily: 'SpaceMono', fontSize: 8, fontWeight: '900', letterSpacing: 3, color: '#ccc5a0', textTransform: 'uppercase' },
  receiptScrollHint: { fontFamily: 'SpaceMono', fontSize: 8, color: '#e8006f', fontWeight: '900' },
  receiptSlot: { padding: 6, paddingHorizontal: 10 },
  receiptRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', borderBottomWidth: 1, borderBottomColor: '#c0b090', borderStyle: 'dotted', paddingVertical: 2 },
  receiptRoute: { fontFamily: 'SpaceMono', fontSize: 10, fontWeight: 'bold', color: '#3a3020', flex: 1 },
  receiptDate: { fontFamily: 'SpaceMono', fontSize: 9, color: '#8a7a5a', flex: 1, textAlign: 'center' },
  receiptMi: { fontFamily: 'SpaceMono', fontSize: 9, color: '#e8006f', flex: 1, textAlign: 'right' },
  buttonsRow: { flexDirection: 'row', gap: 8, alignItems: 'center' },
  chunkyBtn: {  },
  chunkyBtnBase: {
    flex: 1, paddingVertical: 10, paddingHorizontal: 8, borderRadius: 6,
    shadowOffset: { width: 0, height: 4 }, shadowOpacity: 1, shadowRadius: 0, elevation: 6, alignItems: 'center',
  },
  chunkyBtnText: { fontFamily: 'SpaceMono', fontSize: 9, fontWeight: '900', letterSpacing: 2, textTransform: 'uppercase' },
  speakerGrille: { flexDirection: 'row', flexWrap: 'wrap', gap: 3.5, paddingVertical: 5, paddingHorizontal: 14, borderTopWidth: 1 },
  speakerDot: { width: 5, height: 5, borderRadius: 3, backgroundColor: '#2a2415' },
  stickersRow: { flexDirection: 'row', alignItems: 'center', paddingVertical: 2 },
  warningSticker: { backgroundColor: '#f5c800', borderWidth: 1, borderColor: '#b09500', paddingHorizontal: 5, paddingVertical: 2 },
  warningStickerText: { fontFamily: 'SpaceMono', fontSize: 6, fontWeight: '900', letterSpacing: 2, color: '#1a1000' },
  serialSticker: { backgroundColor: '#d8d8d8', borderWidth: 1, borderColor: '#909090', paddingHorizontal: 6, paddingVertical: 2 },
  serialStickerText: { fontFamily: 'SpaceMono', fontSize: 6, color: '#2a2a2a' },
  homeInd: { height: 34, alignItems: 'center', justifyContent: 'flex-end', paddingBottom: 8, borderTopWidth: 2 },
  homeBar: { width: 120, height: 5, borderRadius: 3 },
});
