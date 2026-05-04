import React from 'react';
import { StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { colors, fonts, shadows } from '../theme/tokens';
import { FlipStats } from '../components/FlipStats';
import { GlobeScene } from '../components/GlobeScene';
import { TicketBrand } from '../components/TicketBrand';

const navItems = [
  ['GLOBE', '◎'],
  ['TRIPS', '▣'],
  ['PASSPORT', '▤'],
  ['DREAMS', '◇'],
  ['PROFILE', '●'],
] as const;

export function GlobeHomeScreen() {
  const insets = useSafeAreaInsets();

  return (
    <View style={styles.screen}>
      <View style={[styles.hero, { paddingTop: insets.top + 16, paddingBottom: insets.bottom + 88 }]}>
        <View style={styles.topRow}>
          <TicketBrand />
          <FlipStats />
        </View>

        <View style={styles.filterRow}>
          <TouchableOpacity activeOpacity={0.84} style={styles.yearButton}>
            <Text style={styles.yearText}>2025</Text>
            <Text style={styles.chevron}>v</Text>
          </TouchableOpacity>
          <View style={styles.sideButtons}>
            <TouchableOpacity activeOpacity={0.84} style={styles.roundButton}>
              <Text style={styles.roundIcon}>O</Text>
            </TouchableOpacity>
            <TouchableOpacity activeOpacity={0.84} style={styles.roundButton}>
              <Text style={styles.roundIcon}>--</Text>
            </TouchableOpacity>
          </View>
        </View>

        <View style={styles.globeWrap}>
          <GlobeScene />
          <View style={[styles.mileageCard, shadows.paper]}>
            <Text style={styles.mileageLabel}>AIR You've flown</Text>
            <Text style={styles.mileageDigits}>183,726</Text>
            <Text style={styles.mileageUnit}>MILES</Text>
          </View>
          <View style={[styles.passportStamp, shadows.paper]}>
            <Text style={styles.passportText}>PASSPORT{'\n'}VIEW</Text>
          </View>
        </View>
      </View>

      <View style={[styles.bottomNav, { paddingBottom: insets.bottom + 8 }]}>
        {navItems.map(([label, icon], index) => (
          <TouchableOpacity key={label} activeOpacity={0.8} style={[styles.navItem, index === 0 && styles.navActive]}>
            <Text style={[styles.navIcon, index === 0 && styles.navIconActive]}>{icon}</Text>
            <Text style={[styles.navText, index === 0 && styles.navTextActive]}>{label}</Text>
          </TouchableOpacity>
        ))}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
    backgroundColor: colors.ink,
  },
  hero: {
    flex: 1,
    backgroundColor: colors.ink,
    overflow: 'hidden',
  },
  topRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    justifyContent: 'space-between',
    paddingHorizontal: 12,
    zIndex: 4,
  },
  filterRow: {
    zIndex: 5,
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    paddingHorizontal: 16,
    marginTop: 22,
  },
  yearButton: {
    minWidth: 82,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    borderRadius: 8,
    borderWidth: 1,
    borderColor: '#5C4325',
    backgroundColor: '#18140E',
    paddingHorizontal: 12,
    paddingVertical: 9,
  },
  yearText: {
    color: colors.paper,
    fontFamily: fonts.sansBold,
    fontSize: 20,
  },
  chevron: {
    color: colors.paper,
    fontFamily: fonts.sansBold,
    fontSize: 14,
  },
  sideButtons: {
    gap: 14,
  },
  roundButton: {
    width: 50,
    height: 50,
    borderRadius: 25,
    borderWidth: 1,
    borderColor: '#5C4325',
    backgroundColor: '#1A150F',
    alignItems: 'center',
    justifyContent: 'center',
  },
  roundIcon: {
    color: colors.paper,
    fontFamily: fonts.sansBold,
    fontSize: 19,
  },
  globeWrap: {
    marginTop: -198,
    height: 760,
    justifyContent: 'center',
  },
  mileageCard: {
    position: 'absolute',
    left: 12,
    bottom: 72,
    width: 176,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#5C4325',
    backgroundColor: '#17130E',
    padding: 10,
  },
  mileageLabel: {
    color: colors.paper,
    fontFamily: fonts.sansSemi,
    fontSize: 12,
  },
  mileageDigits: {
    color: colors.gold,
    fontFamily: fonts.mono,
    fontSize: 28,
    letterSpacing: 1.2,
    marginTop: 4,
  },
  mileageUnit: {
    color: colors.paperDark,
    textAlign: 'right',
    fontFamily: fonts.sansBold,
    fontSize: 12,
  },
  passportStamp: {
    position: 'absolute',
    right: 24,
    bottom: 62,
    width: 90,
    height: 90,
    borderRadius: 45,
    borderWidth: 3,
    borderColor: '#B24A35',
    backgroundColor: colors.paper,
    alignItems: 'center',
    justifyContent: 'center',
    transform: [{ rotate: '-16deg' }],
  },
  passportText: {
    color: colors.red,
    fontFamily: fonts.sansBold,
    fontSize: 13,
    letterSpacing: 1.2,
    textAlign: 'center',
  },
  bottomNav: {
    position: 'absolute',
    left: 0,
    right: 0,
    bottom: 0,
    minHeight: 84,
    flexDirection: 'row',
    backgroundColor: '#12110E',
    borderTopWidth: 1,
    borderTopColor: '#3A3125',
  },
  navItem: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    gap: 3,
    borderLeftWidth: 1,
    borderLeftColor: '#302A22',
  },
  navActive: {
    backgroundColor: '#1B170E',
  },
  navIcon: {
    color: '#9C8B70',
    fontFamily: fonts.sansBold,
    fontSize: 26,
  },
  navIconActive: {
    color: colors.gold,
  },
  navText: {
    color: '#9C8B70',
    fontFamily: fonts.sansBold,
    fontSize: 11,
  },
  navTextActive: {
    color: colors.gold,
  },
});
