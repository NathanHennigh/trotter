import React from 'react';
import { Keyboard, StyleSheet, Text, TextInput, useWindowDimensions, View } from 'react-native';
import { colors, fonts } from '../../../theme/trotterTheme';
import { getMobileVisualWidth } from '../../../utils/mobileLayout';
import { PressFeedback } from '../motion';
import { WWIcon } from '../WorldWindowUI';

export function CollectionIndexHeader({ title, query, setQuery, placeholder, onBack, backLabel = 'Passport', active = true, onBackHandlerChange }: {
  title: string; query: string; setQuery: (query: string) => void; placeholder: string;
  onBack: () => void; backLabel?: string; active?: boolean;
  onBackHandlerChange?: (handler: (() => boolean) | null) => void;
}) {
  const { width, fontScale } = useWindowDimensions();
  const [searching, setSearching] = React.useState(Boolean(query));
  const input = React.useRef<TextInput>(null);
  const searchWasOpen = React.useRef(false);
  const closeSearch = React.useCallback(() => {
    input.current?.blur();
    Keyboard.dismiss();
    setQuery('');
    setSearching(false);
  }, [setQuery]);
  React.useEffect(() => {
    if (searching && active && !searchWasOpen.current) input.current?.focus();
    if (!searching || !active) input.current?.blur();
    // Returning from a detail keeps the visible query without reopening the keyboard.
    searchWasOpen.current = searching;
  }, [searching, active]);
  React.useEffect(() => {
    onBackHandlerChange?.(active ? () => {
      if (!searching) return false;
      closeSearch();
      return true;
    } : null);
    return () => onBackHandlerChange?.(null);
  }, [active, searching, closeSearch, onBackHandlerChange]);
  // Leave both 44pt controls intact at large text sizes. Only the short display
  // title is fitted; the actual search text and collection data keep font scaling.
  const titleSize = Math.min(32, (getMobileVisualWidth(width) - 148) / (fontScale * Math.max(4, title.length * .56)));
  return <View testID="collection-index-header" style={s.header}>
    {searching ? <>
      <View accessible={false} style={s.icon}><WWIcon name="search" size={18} color={colors.mutedInk} /></View>
      <TextInput ref={input} testID="collection-search-input" value={query} onChangeText={setQuery}
        accessibilityLabel={`Search ${title.toLowerCase()}`} accessibilityHint={placeholder}
        placeholder={placeholder} placeholderTextColor={colors.mutedInk}
        autoCorrect={false} autoCapitalize="none" returnKeyType="search" blurOnSubmit
        onKeyPress={event => { if (event.nativeEvent.key === 'Escape') closeSearch(); }}
        style={s.input} />
      <PressFeedback accessibilityRole="button" accessibilityLabel="Close search" onPress={closeSearch} style={s.icon}>
        <WWIcon name="close" size={18} />
      </PressFeedback>
    </> : <>
      <PressFeedback accessibilityRole="button" accessibilityLabel={`Back to ${backLabel}`} onPress={onBack} style={s.icon}>
        <WWIcon name="back" size={19} />
      </PressFeedback>
      <Text accessibilityRole="header" style={[s.title, { fontSize: titleSize, lineHeight: titleSize * 1.18 }]}>{title}</Text>
      <PressFeedback accessibilityRole="button" accessibilityLabel={`Search ${title.toLowerCase()}`} onPress={() => setSearching(true)} style={s.icon}>
        <WWIcon name="search" size={18} />
      </PressFeedback>
    </>}
  </View>;
}

export function CollectionProgress({ collected, total, percent, label, expanded, onAbout }: {
  collected: number; total: number; percent: number; label: string; expanded: boolean; onAbout: () => void;
}) {
  return <View testID="collection-progress">
    <View style={s.progressRow}>
      <View style={s.progressCopy}>
        <View style={s.progressNumbers}><Text style={s.collected}>{collected}</Text><Text style={s.total}>/ {total.toLocaleString()}</Text></View>
        <Text style={s.label}>{label}</Text>
      </View>
      <PressFeedback accessibilityRole="button" accessibilityLabel="About this collection" accessibilityState={{ expanded }} onPress={onAbout} style={s.icon}>
        <Text allowFontScaling={false} style={s.infoGlyph}>i</Text>
      </PressFeedback>
    </View>
    <View accessible={false} style={s.track}><View style={[s.fill, { width: `${Math.min(100, Math.max(0, percent))}%` }]} /></View>
  </View>;
}

const s = StyleSheet.create({
  header: { flexDirection: 'row', alignItems: 'center', gap: 6, minHeight: 64, paddingHorizontal: 18, paddingTop: 5, paddingBottom: 7 },
  icon: { width: 44, minHeight: 44, alignItems: 'center', justifyContent: 'center' },
  title: { flex: 1, minWidth: 0, fontFamily: fonts.display, color: colors.ink, letterSpacing: -.35 },
  input: { flex: 1, minWidth: 0, minHeight: 44, paddingVertical: 8, fontFamily: fonts.sansRegular, fontSize: 14, color: colors.ink },
  progressRow: { flexDirection: 'row', alignItems: 'center', gap: 8, minHeight: 47 },
  progressCopy: { flex: 1, minWidth: 0, flexDirection: 'row', flexWrap: 'wrap', alignItems: 'baseline', columnGap: 10, rowGap: 3 },
  progressNumbers: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'baseline', columnGap: 5 },
  collected: { fontFamily: fonts.mono, fontSize: 23, color: colors.ink },
  total: { fontFamily: fonts.mono, fontSize: 12, color: colors.mutedInk },
  label: { fontFamily: fonts.sansRegular, fontSize: 11, lineHeight: 17, color: colors.mutedInk, flexShrink: 1 },
  infoGlyph: { borderWidth: 1, borderColor: colors.paperBorder, borderRadius: 10, width: 20, height: 20, textAlign: 'center', fontFamily: fonts.displayItalic, color: colors.ink, fontSize: 15 },
  track: { height: 2, backgroundColor: colors.paperBorderSoft, marginTop: 3, marginBottom: 3 },
  fill: { height: 2, backgroundColor: colors.copper },
});
