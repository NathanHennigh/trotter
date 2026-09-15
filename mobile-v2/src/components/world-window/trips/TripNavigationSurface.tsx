import React from "react";
import { Animated, Platform, StyleSheet, View, useWindowDimensions } from "react-native";
import type { TripSummary } from "../../../data/trotterMock";
import { colors } from "../../../theme/trotterTheme";
import { getMobileVisualWidth } from "../../../utils/mobileLayout";
import { paperEase, useReducedMotion } from "../motion";
import type { TripOpenOrigin } from "./tripTransition";

/** Move one opaque itinerary above the retained origin. Never recreate its paper. */
export function TripNavigationSurface({ closing, onClosed, children }: {
  trip: TripSummary; flightId?: string; origin?: TripOpenOrigin;
  closing: boolean; onClosed: () => void; children: React.ReactNode;
}) {
  const reduced = useReducedMotion();
  const progress = React.useRef(new Animated.Value(reduced ? 1 : 0)).current;
  const [laidOut, setLaidOut] = React.useState(false);
  const entered = React.useRef(reduced);
  const { width } = useWindowDimensions();
  const travel = Platform.OS === "web" ? getMobileVisualWidth(width) : width;
  const complete = React.useRef(onClosed);
  complete.current = onClosed;

  React.useEffect(() => {
    progress.stopAnimation();
    let animation: Animated.CompositeAnimation | undefined;
    let firstFrame: number | undefined, secondFrame: number | undefined;
    let cancelled = false;
    const start = () => {
      if (cancelled) return;
      animation = Animated.timing(progress, {
        toValue: closing ? 0 : 1,
        duration: reduced || (closing && !entered.current) ? 0 : closing ? 170 : 220,
        easing: paperEase,
        useNativeDriver: true,
      });
      if (!closing) entered.current = true;
      animation.start(({ finished }) => { if (!cancelled && finished && closing) complete.current(); });
    };
    if (closing || reduced || entered.current) start();
    else if (laidOut) {
      // The itinerary's SVG/native tree must commit before its animation clock
      // starts. A layout event plus a paint opportunity avoids spending the
      // whole entry duration mounting an offscreen map on slower Android GPUs.
      firstFrame = requestAnimationFrame(() => {
        secondFrame = requestAnimationFrame(start);
      });
    }
    return () => {
      cancelled = true;
      if (firstFrame != null) cancelAnimationFrame(firstFrame);
      if (secondFrame != null) cancelAnimationFrame(secondFrame);
      animation?.stop();
    };
  }, [closing, reduced, laidOut, progress]);

  return (
    <View style={[StyleSheet.absoluteFill, styles.clip]} pointerEvents={closing ? "none" : "auto"}>
      <Animated.View onLayout={() => { if (!closing) setLaidOut(true); }} style={[
        StyleSheet.absoluteFill,
        styles.surface,
        { transform: reduced ? [] : [{ translateX: progress.interpolate({ inputRange: [0, 1], outputRange: [travel, 0] }) }] },
      ]}>
        {children}
      </Animated.View>
    </View>
  );
}

const styles = StyleSheet.create({
  clip: { overflow: "hidden" },
  surface: { backgroundColor: colors.paperSoft },
});
