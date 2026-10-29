import React from "react";
import { Animated, Easing, StyleSheet, View, useWindowDimensions } from "react-native";
import { colors } from "../../../theme/trotterTheme";

/** A country opens as a paper page over its retained postcard library. Wait for
 * native layout before starting so mounting the list cannot consume its entrance. */
export function DreamCountryTransition({ library, detail, open, reducedMotion, onClosed }: {
  library: React.ReactNode; detail?: React.ReactNode; open: boolean;
  reducedMotion: boolean; onClosed: () => void;
}) {
  const progress = React.useRef(new Animated.Value(0)).current;
  const { width: windowWidth } = useWindowDimensions();
  const [width, setWidth] = React.useState(windowWidth);
  const [pageReady, setPageReady] = React.useState(false);
  const closed = React.useRef(onClosed); closed.current = onClosed;
  const present = Boolean(detail);
  React.useEffect(() => {
    progress.stopAnimation();
    if (!present) { progress.setValue(0); setPageReady(false); return; }
    if (reducedMotion) {
      progress.setValue(open ? 1 : 0);
      if (!open) closed.current();
      return;
    }
    if (!pageReady) { if (!open) closed.current(); return; }
    const animation = Animated.timing(progress, {
      toValue: open ? 1 : 0, duration: open ? 280 : 220,
      easing: Easing.bezier(.32, .72, 0, 1), useNativeDriver: true,
    });
    // The first committed frame establishes the off-screen paper. Starting in
    // the mounting effect can finish most of the animation before Android draws.
    const frame = requestAnimationFrame(() => {
      animation.start(({ finished }) => { if (finished && !open) closed.current(); });
    });
    return () => { cancelAnimationFrame(frame); animation.stop(); };
  }, [open, present, reducedMotion, progress, pageReady]);
  return <View style={s.stage} onLayout={event => {
    const nextWidth = event.nativeEvent.layout.width;
    if (nextWidth > 0) setWidth(nextWidth);
  }}>
    <Animated.View pointerEvents={present ? "none" : "auto"}
      accessibilityElementsHidden={present} importantForAccessibility={present ? "no-hide-descendants" : "auto"}
      style={[s.library, { opacity: progress.interpolate({ inputRange: [0, 1], outputRange: [1, .7] }),
        transform: [{ translateX: progress.interpolate({ inputRange: [0, 1], outputRange: [0, reducedMotion ? 0 : -width * .18] }) }] }]}>
      {library}
    </Animated.View>
    {present && <Animated.View onLayout={() => setPageReady(true)} pointerEvents={open ? "auto" : "none"} style={[s.page, {
      opacity: reducedMotion ? progress : 1,
      transform: [{ translateX: progress.interpolate({ inputRange: [0, 1], outputRange: [reducedMotion ? 0 : width, 0] }) }],
    }]}>{detail}</Animated.View>}
  </View>;
}
const s = StyleSheet.create({
  stage: { flex: 1, overflow: "hidden" }, library: { flex: 1 },
  page: { ...StyleSheet.absoluteFillObject, backgroundColor: colors.paperSoft,
    borderLeftWidth: 1, borderLeftColor: colors.paperBorder,
    shadowColor: colors.ink, shadowOffset: { width: -5, height: 0 }, shadowOpacity: .1, shadowRadius: 12, elevation: 8 },
});
