import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { useTravelTrips } from '../../../services/travelTrips';
import { colors, fonts } from '../../../theme/trotterTheme';
import { PressFeedback } from '../motion';
import { HEADER_GEOMETRY } from '../headerGeometry';

/** A small visual mark with a full-sized touch target. */
export function ProfileAvatar({ onPress }: { onPress: () => void }) {
  const { profile } = useTravelTrips();
  const initial = Array.from(profile.name?.trim() || 'T')[0].toLocaleUpperCase();
  return <PressFeedback onPress={onPress} accessibilityRole="button" accessibilityLabel="Open your profile and settings" style={s.touch}>
    <View style={s.circle}><Text maxFontSizeMultiplier={1.3} style={s.initial}>{initial}</Text></View>
  </PressFeedback>;
}

const s = StyleSheet.create({
  touch: { width: HEADER_GEOMETRY.touchSize, height: HEADER_GEOMETRY.touchSize, alignItems: 'center', justifyContent: 'center', flexShrink: 0, alignSelf: 'flex-start' },
  circle: { width: HEADER_GEOMETRY.avatarSize, height: HEADER_GEOMETRY.avatarSize, borderRadius: HEADER_GEOMETRY.avatarSize / 2, backgroundColor: '#E0E7E2', alignItems: 'center', justifyContent: 'center' },
  initial: { fontFamily: fonts.sans, fontSize: 15, color: colors.ink },
});
