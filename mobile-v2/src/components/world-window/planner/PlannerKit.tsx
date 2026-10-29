import React from 'react';
import {
  ActivityIndicator, Animated, Image, Keyboard, KeyboardAvoidingView, Modal, Platform, Pressable,
  ScrollView, StyleSheet, Text, TextInput, View, useWindowDimensions, type StyleProp, type ViewStyle,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import Svg, { Path, Rect } from 'react-native-svg';
import { colors, fonts } from '../../../theme/trotterTheme';
import { getApiBaseUrl, getAuthRevision, getStoredToken, subscribeAuthToken } from '../../../services/travelTrips';
import { findCountryArtwork } from '../dreams/countryArtwork';
import { PlaceSymbol } from '../dreams/DreamPhoto';
import { WWIcon } from '../WorldWindowUI';
import { paperEase, PressFeedback, useReducedMotion } from '../motion';

export function PlannerGlyph({ name, size = 20, color = colors.ink }: { name: 'up' | 'down' | 'lock' | 'grip' | 'calendar'; size?: number; color?: string }) {
  return <Svg width={size} height={size} viewBox="0 0 24 24" stroke={color} strokeWidth={1.5} strokeLinecap="round" fill="none" accessibilityElementsHidden>
    {name === 'up' ? <Path d="m5 15 7-7 7 7" /> : name === 'down' ? <Path d="m5 9 7 7 7-7" />
      : name === 'lock' ? <><Rect x="6" y="11" width="12" height="10" rx="1.5" /><Path d="M8 11V7a4 4 0 0 1 8 0v4M12 15v2" /></>
      : name === 'calendar' ? <><Rect x="4" y="5" width="16" height="16" rx="1.5" /><Path d="M8 3v4M16 3v4M4 10h16" /></>
      : <Path d="M9 7h.01M15 7h.01M9 12h.01M15 12h.01M9 17h.01M15 17h.01" strokeWidth={3} />}
  </Svg>;
}

export function PlannerAction({ label, onPress, secondary, quiet, disabled, busy, icon, style, prominent }: {
  label: string; onPress: () => void; secondary?: boolean; quiet?: boolean; disabled?: boolean;
  busy?: boolean; icon?: string; style?: StyleProp<ViewStyle>; prominent?: boolean;
}) {
  return <PressFeedback accessibilityRole="button" accessibilityLabel={label} accessibilityState={{ disabled: !!(disabled || busy), busy: !!busy }}
    disabled={disabled || busy} onPress={onPress} style={[k.action, prominent && k.actionProminent, secondary && k.actionSecondary, quiet && k.actionQuiet, (disabled || busy) && k.disabled, style]}>
    {busy ? <ActivityIndicator size="small" color={secondary || quiet ? colors.ink : colors.paperSoft} />
      : icon ? <WWIcon name={icon} size={18} color={secondary || quiet ? colors.ink : colors.paperSoft} /> : null}
    <Text style={[k.actionText, (secondary || quiet) && k.actionTextSecondary]}>{label}</Text>
  </PressFeedback>;
}
export function PlannerField({ label, value, onChangeText, placeholder, keyboardType, multiline, editable = true, hint, onFocus }: {
  label: string; value: string; onChangeText: (value: string) => void; placeholder?: string;
  keyboardType?: 'default' | 'email-address' | 'numeric' | 'url' | 'numbers-and-punctuation'; multiline?: boolean; editable?: boolean; hint?: string; onFocus?: () => void;
}) {
  return <View style={k.field}><Text style={k.label}>{label}</Text><TextInput accessibilityLabel={label} value={value} onChangeText={onChangeText} onFocus={onFocus}
    placeholder={placeholder} placeholderTextColor="#7C898C" keyboardType={keyboardType} multiline={multiline} editable={editable}
    autoCapitalize={keyboardType === 'email-address' || keyboardType === 'url' ? 'none' : 'sentences'} autoCorrect={keyboardType !== 'url' && keyboardType !== 'email-address'}
    style={[k.input, multiline && { height: 84, textAlignVertical: 'top' }]} />{hint ? <Text style={k.hint}>{hint}</Text> : null}</View>;
}
export function PlannerChoices<T extends string>({ label, value, choices, onChange, disabled }: {
  label?: string; value: T; choices: readonly { value: T; label: string }[]; onChange: (value: T) => void; disabled?: boolean;
}) {
  return <View style={k.field}>{label ? <Text style={k.label}>{label}</Text> : null}<View style={k.choices}>
    {choices.map(choice => <PressFeedback key={choice.value} accessibilityRole="radio" accessibilityState={{ selected: choice.value === value, disabled }}
      disabled={disabled} onPress={() => onChange(choice.value)} style={[k.choice, value === choice.value && k.choiceSelected]}>
      <Text style={[k.choiceText, value === choice.value && k.choiceTextSelected]}>{choice.label}</Text></PressFeedback>)}
  </View></View>;
}
export function PlannerSheet({ title, subtitle, onClose, children, busy, error, footer, visible = true, transitionKey }: {
  title: string; subtitle?: string; onClose: () => void; children: React.ReactNode; busy?: boolean; error?: string; footer?: React.ReactNode; visible?: boolean; transitionKey?: string;
}) {
  const insets = useSafeAreaInsets(), reduced = useReducedMotion(), { height: windowHeight } = useWindowDimensions();
  const formScroll = React.useRef<ScrollView>(null), scrollY = React.useRef(0), visibleNow = React.useRef(visible);
  const progress = React.useRef(new Animated.Value(0)).current;
  const settled = React.useRef(false);
  const [sheetHeight, setSheetHeight] = React.useState(0), [windowShown, setWindowShown] = React.useState(false), [closing, setClosing] = React.useState(false);
  const closeRequest = React.useRef<{ onClose: () => void; identity: string } | undefined>(undefined);
  const identity = transitionKey ?? title, currentIdentity = React.useRef(identity);
  visibleNow.current = visible;
  currentIdentity.current = identity;
  React.useEffect(() => {
    closeRequest.current = undefined;
    settled.current = false;
    setClosing(false);
    progress.stopAnimation();
    progress.setValue(0);
    if (!visible) setWindowShown(false);
    return () => { closeRequest.current = undefined; progress.stopAnimation(); };
  }, [visible, identity, progress]);
  React.useEffect(() => {
    if (!visible || !windowShown || !sheetHeight) return;
    settled.current = false;
    const request = closeRequest.current;
    const animation = Animated.timing(progress, {
      toValue: closing ? 0 : 1, duration: reduced ? 0 : closing ? 150 : 240,
      easing: paperEase, useNativeDriver: true,
    });
    animation.start(({ finished }) => {
      if (!finished || !visibleNow.current || currentIdentity.current !== identity) return;
      if (!closing) { settled.current = true; revealFocusedInput(); return; }
      if (!request || closeRequest.current !== request || currentIdentity.current !== request.identity) return;
      closeRequest.current = undefined;
      request.onClose();
      // A parent may keep the form open (for example, to confirm unsaved changes).
      setClosing(false);
    });
    return () => animation.stop();
  }, [visible, identity, windowShown, sheetHeight, reduced, closing, progress]);
  const requestClose = () => {
    if (!visibleNow.current || closeRequest.current) return;
    if (reduced || !windowShown || !sheetHeight) { onClose(); return; }
    closeRequest.current = { onClose, identity };
    setClosing(true);
  };
  const revealFocusedInput = () => {
    if (!visibleNow.current || !settled.current || Platform.OS === 'web' || !Keyboard.isVisible()) return;
    const input = TextInput.State.currentlyFocusedInput(), scroll = formScroll.current, viewport = scroll?.getNativeScrollRef();
    if (!input || !scroll || !viewport) return;
    viewport.measureInWindow((_x, top, _width, height) => {
      input.measureInWindow((_inputX, inputTop, _inputWidth, inputHeight) => {
        if (!visibleNow.current || scroll !== formScroll.current || input !== TextInput.State.currentlyFocusedInput() || !Keyboard.isVisible()) return;
        const below = inputTop + inputHeight + 24 - (top + height), above = inputTop - top - 12;
        if (below > 0) scroll.scrollTo({ y: scrollY.current + below, animated: false });
        else if (above < 0) scroll.scrollTo({ y: Math.max(0, scrollY.current + above), animated: false });
      });
    });
  };
  return <Modal visible={visible} transparent animationType="none" onShow={() => { if (visibleNow.current) setWindowShown(true); }} onRequestClose={requestClose} statusBarTranslucent>
    <KeyboardAvoidingView style={k.modal} behavior={Platform.OS === 'ios' ? 'padding' : Platform.OS === 'android' ? 'height' : undefined}>
      <Animated.View pointerEvents="none" style={[StyleSheet.absoluteFill, k.scrim, { opacity: progress }]} />
      <Pressable style={StyleSheet.absoluteFill} onPress={requestClose} accessibilityLabel="Close" accessibilityRole="button" />
      <Animated.View pointerEvents={closing ? 'none' : 'auto'} onLayout={event => setSheetHeight(event.nativeEvent.layout.height)}
        style={[k.sheet, { paddingBottom: Math.max(insets.bottom, 18), maxHeight: '92%', opacity: reduced ? progress : 1,
          transform: [{ translateY: progress.interpolate({ inputRange: [0, 1], outputRange: [reduced ? 0 : sheetHeight || windowHeight, 0] }) }] }]} accessibilityViewIsModal>
        <View style={k.sheetHeading}><View style={{ flex: 1 }}><Text style={k.sheetTitle}>{title}</Text>{subtitle ? <Text style={k.body}>{subtitle}</Text> : null}</View>
          <PressFeedback onPress={requestClose} style={k.iconButton} accessibilityLabel="Close sheet" accessibilityRole="button"><WWIcon name="close" size={22} /></PressFeedback></View>
        <ScrollView ref={formScroll} onScroll={event => { scrollY.current = event.nativeEvent.contentOffset.y; }} scrollEventThrottle={16} onLayout={revealFocusedInput} onFocus={revealFocusedInput}
          keyboardShouldPersistTaps="handled" showsVerticalScrollIndicator={false} contentContainerStyle={k.sheetContent}>
          {error ? <Text style={k.error} accessibilityRole="alert">{error}</Text> : null}{children}
        </ScrollView>{footer ? <View style={k.sheetFooter}>{footer}</View> : null}
        {busy ? <Text accessibilityLiveRegion="polite" style={k.saving}>Saving…</Text> : null}
      </Animated.View>
    </KeyboardAvoidingView>
  </Modal>;
}

const imageSession = Date.now().toString(36);
export function PlannerPhoto({ uri, country, category = 'unknown', cover = false, large = false, title }: {
  uri?: string | null; country?: string | null; category?: string; cover?: boolean; large?: boolean; title?: string;
}) {
  const revision = React.useSyncExternalStore(subscribeAuthToken, getAuthRevision, getAuthRevision);
  const token = getStoredToken(), artwork = cover ? findCountryArtwork(country) : undefined;
  const [failed, setFailed] = React.useState<string>(), [blob, setBlob] = React.useState<{ key: string; uri: string }>();
  let safeUri: string | undefined, privatePhoto = false;
  try {
    if (uri) {
      const base = new URL(getApiBaseUrl()), url = new URL(uri, `${base.toString().replace(/\/$/, '')}/`);
      if (/^https?:$/.test(url.protocol) && !url.username && !url.password && !uri.startsWith('//')) {
        privatePhoto = url.origin === base.origin && /\/(planner\/trips\/[^/]+\/ideas\/[^/]+|dream-items\/\d+|dream-source-posts\/\d+)\/thumbnail\/?$/.test(url.pathname);
        if (privatePhoto) { url.searchParams.set('session', `${imageSession}-${revision}`); url.searchParams.set('width', cover || large ? '960' : '240'); }
        safeUri = url.toString();
      }
    }
  } catch { /* A missing photo keeps the category symbol. */ }
  const key = `${revision}:${safeUri || ''}`;
  React.useEffect(() => {
    setBlob(undefined);
    if (Platform.OS !== 'web' || !privatePhoto || !safeUri || !token) return;
    const controller = new AbortController(); let live = true, objectUrl: string | undefined;
    void fetch(safeUri, { headers: { Authorization: `Bearer ${token}` }, signal: controller.signal })
      .then(async response => { if (!response.ok) throw new Error(); const image = await response.blob();
        if (live && revision === getAuthRevision()) { objectUrl = URL.createObjectURL(image); setBlob({ key, uri: objectUrl }); } })
      .catch(() => { if (live) setFailed(key); });
    return () => { live = false; controller.abort(); if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [safeUri, privatePhoto, token, key, revision]);
  const imageUri = privatePhoto && !token ? undefined : Platform.OS === 'web' && privatePhoto ? blob?.key === key ? blob.uri : undefined : safeUri;
  const available = imageUri && failed !== key;
  return <View style={k.photo}>
    <View style={k.photoFallback}>{cover ? <PlannerGlyph name="calendar" size={36} /> : <PlaceSymbol category={category} size={24} />}</View>
    {available ? <Image source={{ uri: imageUri, ...(privatePhoto && Platform.OS !== 'web' ? { headers: { Authorization: `Bearer ${token}` } } : {}) }}
      accessibilityLabel={title || 'Travel photograph'} resizeMode="cover" fadeDuration={100} style={k.image} onError={() => setFailed(key)} />
      : artwork ? <Image source={artwork.source} accessibilityLabel={`${country} travel photograph`} resizeMode="cover" fadeDuration={0} style={k.image} /> : null}
  </View>;
}

export const k = StyleSheet.create({
  body: { fontFamily: fonts.sansRegular, fontSize: 14, lineHeight: 21, color: colors.mutedInk },
  hint: { fontFamily: fonts.sansRegular, fontSize: 12, lineHeight: 18, color: colors.mutedInk },
  label: { fontFamily: fonts.sans, fontSize: 13, color: colors.ink },
  field: { gap: 8, marginBottom: 19 },
  input: { minHeight: 48, paddingHorizontal: 12, paddingVertical: 12, borderWidth: 1, borderColor: colors.paperBorder, borderRadius: 4,
    color: colors.ink, backgroundColor: colors.paperPhoto, fontFamily: fonts.sansRegular, fontSize: 16 },
  action: { minHeight: 48, paddingHorizontal: 18, paddingVertical: 12, borderRadius: 4, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8, backgroundColor: colors.ink },
  actionSecondary: { borderWidth: 1, borderColor: colors.paperBorder, backgroundColor: 'transparent' },
  actionProminent: { minHeight: 54, width: '100%', alignSelf: 'stretch', flexShrink: 0 },
  actionQuiet: { backgroundColor: 'transparent', paddingHorizontal: 4 },
  actionText: { fontFamily: fonts.sans, color: colors.paperSoft, fontSize: 15, textAlign: 'center' },
  actionTextSecondary: { color: colors.ink },
  disabled: { opacity: 0.5 },
  iconButton: { width: 44, height: 44, alignItems: 'center', justifyContent: 'center' },
  choices: { flexDirection: 'row', borderBottomWidth: 1, borderColor: colors.paperBorder, gap: 10 },
  choice: { flex: 1, minHeight: 46, justifyContent: 'center', alignItems: 'center', paddingHorizontal: 4, borderBottomWidth: 2, borderBottomColor: 'transparent' },
  choiceSelected: { borderBottomColor: colors.ink },
  choiceText: { fontFamily: fonts.sansRegular, fontSize: 13, color: colors.mutedInk, textAlign: 'center' },
  choiceTextSelected: { color: colors.ink, fontFamily: fonts.sansSemi },
  modal: { flex: 1, justifyContent: 'flex-end', alignItems: 'center' },
  scrim: { backgroundColor: 'rgba(29,47,54,0.36)' },
  sheet: { backgroundColor: colors.paperSoft, borderTopLeftRadius: 18, borderTopRightRadius: 18, width: '100%', maxWidth: 580, paddingTop: 15 },
  sheetHeading: { flexDirection: 'row', alignItems: 'flex-start', paddingLeft: 24, paddingRight: 12, paddingBottom: 14, gap: 8 },
  sheetTitle: { fontFamily: fonts.display, fontSize: 30, lineHeight: 35, color: colors.ink, paddingTop: 5 },
  sheetContent: { paddingHorizontal: 24, paddingBottom: 10 },
  sheetFooter: { paddingHorizontal: 24, paddingTop: 14, gap: 7, borderTopWidth: 1, borderTopColor: colors.paperBorderSoft },
  error: { color: colors.redDeep, fontFamily: fonts.sansRegular, fontSize: 14, lineHeight: 21, paddingVertical: 12 },
  saving: { color: colors.mutedInk, fontFamily: fonts.sansRegular, fontSize: 12, textAlign: 'center', paddingTop: 8 },
  photo: { flex: 1, overflow: 'hidden', backgroundColor: colors.paperDeep },
  photoFallback: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  image: { ...StyleSheet.absoluteFillObject, width: '100%', height: '100%' },
});
