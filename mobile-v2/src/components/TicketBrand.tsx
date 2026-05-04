import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { colors, fonts, shadows } from '../theme/tokens';

export function TicketBrand() {
  return (
    <View style={[styles.ticket, shadows.paper]}>
      <Text style={styles.year}>2025</Text>
      <View style={styles.copy}>
        <Text style={styles.wordmark}>TROTTER</Text>
        <Text style={styles.tagline}>YOUR TRAVEL, RECORDED.</Text>
      </View>
      <Text style={styles.plane}>AIR</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  ticket: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    width: 222,
    minHeight: 82,
    borderRadius: 8,
    backgroundColor: colors.paper,
    borderWidth: 1,
    borderColor: '#8E7042',
    paddingHorizontal: 14,
    transform: [{ rotate: '-2deg' }],
  },
  year: {
    color: colors.paperInk,
    fontFamily: fonts.sansBold,
    fontSize: 11,
    transform: [{ rotate: '-90deg' }],
    marginLeft: -14,
  },
  copy: {
    flex: 1,
  },
  wordmark: {
    color: colors.paperInk,
    fontFamily: fonts.sansBold,
    fontSize: 29,
    letterSpacing: 7,
  },
  tagline: {
    color: colors.red,
    fontFamily: fonts.sansBold,
    fontSize: 12,
    letterSpacing: 1.7,
    marginTop: 4,
  },
  plane: {
    color: colors.paperInk,
    fontFamily: fonts.sansBold,
    fontSize: 12,
  },
});
