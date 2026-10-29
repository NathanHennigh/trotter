import React from 'react';
import { ScrollView, StyleSheet, Text, View } from 'react-native';
import { colors, fonts } from '../../../theme/trotterTheme';
import { PressFeedback, useReducedMotion } from '../motion';
import { formatDay } from './plannerEditing';

export function ItineraryDayNav({ dates, active, onSelect }: { dates: string[]; active?: string; onSelect: (date: string) => void }) {
  const scroll = React.useRef<ScrollView>(null), positions = React.useRef<Record<string, { x: number; width: number }>>({});
  const width = React.useRef(0), reduced = useReducedMotion();
  const reveal = React.useCallback(() => {
    const item = active ? positions.current[active] : undefined;
    if (item && width.current) scroll.current?.scrollTo({ x: Math.max(0, item.x - (width.current - item.width) / 2), animated: !reduced });
  }, [active, reduced]);
  React.useEffect(reveal, [reveal]);
  return <View style={styles.container}>
    <ScrollView ref={scroll} horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.days}
      onLayout={event => { width.current = event.nativeEvent.layout.width; reveal(); }}>
      {dates.map((date, index) => <PressFeedback key={date} onLayout={event => { positions.current[date] = event.nativeEvent.layout; if (date === active) reveal(); }}
        onPress={() => onSelect(date)} accessibilityRole="button" accessibilityLabel={`Jump to day ${index + 1}, ${formatDay(date)}`} accessibilityState={{ selected: date === active }}
        style={[styles.day, date === active && styles.selected]}>
        <Text style={[styles.label, date === active && styles.active]}>Day {index + 1}</Text>
        <Text style={styles.date}>{formatDay(date)}</Text>
      </PressFeedback>)}
    </ScrollView>
  </View>;
}

const styles = StyleSheet.create({
  container: { width: '100%', maxWidth: 632, alignSelf: 'center', backgroundColor: colors.paperSoft, borderBottomWidth: 1, borderBottomColor: colors.paperBorderSoft },
  days: { gap: 8, paddingVertical: 6 },
  day: { minHeight: 44, paddingHorizontal: 13, paddingVertical: 5, justifyContent: 'center', gap: 2, borderRadius: 3 },
  selected: { backgroundColor: colors.paperDeep },
  label: { fontFamily: fonts.sansRegular, color: colors.mutedInk, fontSize: 12 },
  active: { fontFamily: fonts.sansSemi, color: colors.ink },
  date: { fontFamily: fonts.sansRegular, color: colors.mutedInk, fontSize: 10 },
});
