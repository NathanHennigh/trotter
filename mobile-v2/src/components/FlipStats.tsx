import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { colors, fonts } from '../theme/tokens';

const stats = [
  { label: 'FLIGHTS', value: '143' },
  { label: 'COUNTRIES', value: '28' },
  { label: 'AIRPORTS', value: '72' },
];

export function FlipStats() {
  return (
    <View>
      <View style={styles.panel}>
        {stats.map((stat, index) => (
          <View key={stat.label} style={[styles.stat, index > 0 && styles.divider]}>
            <Text style={styles.label}>{stat.label}</Text>
            <View style={styles.flipBox}>
              <Text style={styles.value}>{stat.value}</Text>
              <View style={styles.flipLine} />
            </View>
          </View>
        ))}
      </View>
      <View style={styles.sync}>
        <View style={styles.syncDot} />
        <Text style={styles.syncText}>Last synced 2h ago</Text>
        <Text style={styles.gmail}>Gmail</Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  panel: {
    flexDirection: 'row',
    backgroundColor: '#11100D',
    borderWidth: 1,
    borderColor: '#4B3920',
    borderRadius: 12,
    overflow: 'hidden',
  },
  stat: {
    width: 92,
    paddingVertical: 9,
    alignItems: 'center',
  },
  divider: {
    borderLeftWidth: 1,
    borderLeftColor: '#3B2D1B',
  },
  label: {
    color: colors.paperDark,
    fontFamily: fonts.sansBold,
    fontSize: 11,
    letterSpacing: 0.7,
  },
  flipBox: {
    marginTop: 5,
    backgroundColor: '#0A0A08',
    borderRadius: 5,
    borderWidth: 1,
    borderColor: '#302719',
    paddingHorizontal: 8,
    paddingVertical: 2,
    minWidth: 60,
    alignItems: 'center',
  },
  value: {
    color: colors.gold,
    fontFamily: fonts.mono,
    fontSize: 32,
    letterSpacing: 2,
  },
  flipLine: {
    position: 'absolute',
    left: 0,
    right: 0,
    top: '52%',
    height: 1,
    backgroundColor: '#2C261B',
  },
  sync: {
    alignSelf: 'flex-end',
    marginTop: 6,
    minWidth: 246,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    borderRadius: 9,
    borderWidth: 1,
    borderColor: '#5C4325',
    backgroundColor: '#19160F',
    paddingHorizontal: 11,
    paddingVertical: 5,
  },
  syncDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: colors.green,
  },
  syncText: {
    color: colors.paper,
    fontFamily: fonts.sansRegular,
    fontSize: 12,
    flex: 1,
  },
  gmail: {
    color: colors.paper,
    fontFamily: fonts.sansSemi,
    fontSize: 12,
  },
});
