import React from "react";
import { Animated, Platform, Pressable, StyleSheet, View, useWindowDimensions } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import type { TripSummary } from "../../../data/trotterMock";
import { colors } from "../../../theme/trotterTheme";
import { getMobileVisualWidth } from "../../../utils/mobileLayout";
import { paperEase, useReducedMotion } from "../motion";
import { WWIcon } from "../WorldWindowUI";
import { WalletCover, walletColors } from "./WalletCover";
import type { TripOpenOrigin } from "./tripTransition";
import { walletPopupGeometry } from "./walletPopupGeometry";

/** Lift the selected wallet, then reveal its paper inside a growing native clip. */
export function TripNavigationSurface({ origin, closing, onClosed, onRequestClose, closeLabel = "Close itinerary", children }: {
  trip: TripSummary; flightId?: string; origin?: TripOpenOrigin;
  closing: boolean; onClosed: () => void; onRequestClose: () => void;
  closeLabel?: string; children: React.ReactNode;
}) {
  const reduced = useReducedMotion();
  const progress = React.useRef(new Animated.Value(reduced ? 1 : 0)).current;
  const [laidOut, setLaidOut] = React.useState(false);
  const entered = React.useRef(reduced);
  const { width, height } = useWindowDimensions();
  const insets = useSafeAreaInsets();
  const viewportWidth = Platform.OS === "web" ? getMobileVisualWidth(width) : width;
  // Hydration and source-list updates must never move an in-flight wallet.
  const capturedOrigin = React.useRef(origin).current;
  const { target, source, anchored } = walletPopupGeometry(viewportWidth, height, insets.top, insets.bottom, capturedOrigin);
  const complete = React.useRef(onClosed);
  complete.current = onClosed;

  React.useEffect(() => {
    progress.stopAnimation();
    let animation: Animated.CompositeAnimation | undefined;
    let firstFrame: number | undefined, secondFrame: number | undefined;
    let cancelled = false;
    const timing = (toValue: number, duration: number) => Animated.timing(progress, {
      toValue, duration, easing: paperEase, useNativeDriver: true,
    });
    const start = () => {
      if (cancelled) return;
      animation = reduced || (closing && !entered.current)
        ? timing(closing ? 0 : 1, 0)
        : closing ? timing(0, 230)
        : anchored && !entered.current
          ? Animated.sequence([timing(.22, 85), timing(1, 245)])
          : timing(1, 245);
      if (!closing) entered.current = true;
      animation.start(({ finished }) => { if (!cancelled && finished && closing) complete.current(); });
    };
    if (closing || reduced || entered.current) start();
    else if (laidOut) {
      firstFrame = requestAnimationFrame(() => { secondFrame = requestAnimationFrame(start); });
    }
    return () => {
      cancelled = true;
      if (firstFrame != null) cancelAnimationFrame(firstFrame);
      if (secondFrame != null) cancelAnimationFrame(secondFrame);
      animation?.stop();
    };
  }, [closing, reduced, laidOut, progress, anchored]);

  const frames = [0, .22, 1];
  const dx = source.x - target.x, dy = source.y - target.y;
  const translateX = progress.interpolate({ inputRange: frames, outputRange: [dx, dx, 0] });
  const translateY = progress.interpolate({ inputRange: frames, outputRange: [dy, dy - (anchored ? 22 : 0), 0] });
  const scaleX = progress.interpolate({ inputRange: frames, outputRange: [source.width / target.width, source.width / target.width, 1] });
  const scaleY = progress.interpolate({ inputRange: frames, outputRange: [source.height / target.height, source.height / target.height, 1] });
  const detailReveal = progress.interpolate({ inputRange: [0, .34, .56, 1], outputRange: [anchored ? 0 : 1, anchored ? 0 : 1, 1, 1] });
  const coverOpacity = progress.interpolate({ inputRange: [0, .34, .56, 1], outputRange: [1, 1, 0, 0] });
  const summaryOpacity = progress.interpolate({ inputRange: [0, .22, .34, 1], outputRange: [1, 1, 0, 0] });

  return (
    <View testID="wallet-popup" style={[StyleSheet.absoluteFill, styles.clip]}
      accessibilityViewIsModal onAccessibilityEscape={onRequestClose}>
      <Animated.View pointerEvents="none" testID="wallet-backdrop-tint" style={[StyleSheet.absoluteFill, styles.tint,
        { opacity: reduced ? .22 : progress.interpolate({ inputRange: [0, 1], outputRange: [0, .22] }) }]} />
      <Pressable testID="wallet-backdrop" style={StyleSheet.absoluteFill} accessible={false}
        onPress={closing ? undefined : onRequestClose} />
      <Animated.View testID="wallet-popup-panel" onLayout={() => { if (!closing) setLaidOut(true); }}
        pointerEvents={closing ? "none" : "auto"}
        style={[styles.panel, { left: target.x, top: target.y, width: target.width, height: target.height,
          transform: reduced ? [] : [{ translateX }, { translateY }, { scaleX }, { scaleY }] }]}>
        <View style={styles.paperClip}>
          <Animated.View testID="wallet-popup-content" style={{ width: target.width, height: target.height,
            transformOrigin: "top left", opacity: 1,
            // Grow the clipping surface without stretching the type or map vertically.
            transform: reduced ? [] : [{ scaleY: Animated.divide(1, scaleY) }] }}>
            {children}
          </Animated.View>
          {/* Paint native SVGs behind blue paper before revealing them, rather than first rasterizing mid-turn. */}
          <Animated.View testID="wallet-reveal-curtain" pointerEvents="none" accessible={false}
            accessibilityElementsHidden importantForAccessibility="no-hide-descendants"
            style={[StyleSheet.absoluteFill, { backgroundColor: walletColors.blue,
              opacity: reduced ? 0 : Animated.subtract(1, detailReveal) }]} />
        </View>
      </Animated.View>
      {anchored && !reduced && capturedOrigin?.wallet && (
        <Animated.View testID="wallet-source-cover" pointerEvents="none" accessible={false}
          accessibilityElementsHidden importantForAccessibility="no-hide-descendants"
          style={{ position: "absolute", left: target.x, top: target.y, width: source.width,
            zIndex: 3, elevation: 16,
            transformOrigin: "top left", opacity: coverOpacity,
            transform: [{ translateX }, { translateY }, { scaleX: Animated.divide(scaleX, source.width / target.width) }] }}>
          <WalletCover {...capturedOrigin.wallet} embedded bodyOpacity={summaryOpacity} onPress={() => {}} />
        </Animated.View>
      )}
      <Animated.View testID="wallet-popup-dismiss" style={{ position: "absolute", right: target.x,
        zIndex: 4, elevation: 20,
        top: insets.top + 3, opacity: reduced ? 1 : progress.interpolate({ inputRange: [0, .35, 1], outputRange: [0, 0, 1] }) }}>
        <Pressable accessibilityRole="button" accessibilityLabel={closeLabel}
          disabled={closing} onPress={onRequestClose} style={styles.close}>
          <WWIcon name="close" size={20} color={colors.ink} />
        </Pressable>
      </Animated.View>
    </View>
  );
}

const styles = StyleSheet.create({
  clip: { overflow: "hidden" },
  tint: { backgroundColor: "#183642" },
  panel: { position: "absolute", zIndex: 2, transformOrigin: "top left", borderRadius: 9,
    backgroundColor: walletColors.blue, shadowColor: "#102c3a", shadowOpacity: .23,
    shadowOffset: { width: 0, height: 10 }, shadowRadius: 18, elevation: 12 },
  paperClip: { flex: 1, overflow: "hidden", borderRadius: 9 },
  close: { width: 44, height: 44, borderRadius: 22, backgroundColor: colors.paperSoft,
    justifyContent: "center", alignItems: "center", borderWidth: 1, borderColor: colors.paperBorder },
});
