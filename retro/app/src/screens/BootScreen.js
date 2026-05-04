import React, { useEffect, useState } from 'react';
import { View, Text, StyleSheet, Animated, Easing } from 'react-native';

const BOOT_LINES = [
  { text: 'TROTTER HARDWARE v2.4.1', bright: true },
  { text: 'INITIALIZING SENSORS...' },
  { text: 'FLIGHT DATABASE: OK' },
  { text: 'GPS MODULE: OK' },
  { text: 'LOADING TRAVEL LOG...' },
  { text: '> 22 FLIGHTS FOUND', bright: true },
  { text: '> 21,792 MI LOGGED', bright: true },
  { text: 'READY.', bright: true },
];

export default function BootScreen({ onDone }) {
  const [visible, setVisible] = useState(0);
  const [progress, setProgress] = useState(0);
  const progressAnim = React.useRef(new Animated.Value(0)).current;

  useEffect(() => {
    const t = setTimeout(() => setVisible(v => Math.min(v + 1, BOOT_LINES.length)), 220);
    return () => clearTimeout(t);
  }, [visible]);

  useEffect(() => {
    Animated.timing(progressAnim, {
      toValue: 1,
      duration: 2200,
      easing: Easing.linear,
      useNativeDriver: false,
    }).start(({ finished }) => {
      if (finished) setTimeout(onDone, 400);
    });
  }, []);

  const width = progressAnim.interpolate({ inputRange: [0, 1], outputRange: ['0%', '100%'] });

  return (
    <View style={s.container}>
      {/* scanlines */}
      <View style={s.scanlines} pointerEvents="none" />

      <Text style={s.logo}>TROTTER</Text>
      <Text style={s.sub}>THE TRAVEL DECK</Text>

      <View style={s.terminal}>
        {BOOT_LINES.map((l, i) => (
          <Text
            key={i}
            style={[s.line, i < visible && s.lineVisible, l.bright && i < visible && s.lineBright]}
          >
            {l.text}
          </Text>
        ))}
      </View>

      <View style={s.progressTrack}>
        <Animated.View style={[s.progressFill, { width }]} />
      </View>
    </View>
  );
}

const GREEN = '#6ab04c';
const GREEN_DIM = '#2d5a1b';

const s = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#050c03',
    alignItems: 'center',
    justifyContent: 'center',
    padding: 24,
  },
  scanlines: {
    position: 'absolute',
    inset: 0,
    // Scanlines are simulated via opacity on the whole container on native
  },
  logo: {
    fontFamily: 'SpaceMono',
    fontSize: 36,
    fontWeight: '900',
    letterSpacing: 8,
    color: GREEN,
    textShadowColor: `rgba(139,195,74,0.6)`,
    textShadowOffset: { width: 0, height: 0 },
    textShadowRadius: 20,
    marginBottom: 4,
  },
  sub: {
    fontFamily: 'SpaceMono',
    fontSize: 10,
    fontWeight: '900',
    letterSpacing: 6,
    color: GREEN_DIM,
    marginBottom: 32,
    textTransform: 'uppercase',
  },
  terminal: {
    width: 280,
    marginBottom: 16,
  },
  line: {
    fontFamily: 'SpaceMono',
    fontSize: 11,
    color: '#2a5a18',
    lineHeight: 20,
    opacity: 0,
  },
  lineVisible: {
    opacity: 1,
  },
  lineBright: {
    color: GREEN,
  },
  progressTrack: {
    width: 200,
    height: 8,
    backgroundColor: '#0f1f08',
    borderColor: GREEN_DIM,
    borderWidth: 1,
    borderRadius: 2,
    overflow: 'hidden',
    marginTop: 8,
  },
  progressFill: {
    height: '100%',
    backgroundColor: GREEN,
    shadowColor: GREEN,
    shadowOpacity: 0.8,
    shadowRadius: 4,
  },
});
