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
  const progress = React.useRef(new Animated.Value(0)).current;
  const reduced = useReducedMotion();
  const { width } = useWindowDimensions();
  const travel = Platform.OS === "web" ? getMobileVisualWidth(width) : width;
  const complete = React.useRef(onClosed);
  complete.current = onClosed;

  React.useEffect(() => {
    progress.stopAnimation();
    const animation = Animated.timing(progress, {
      toValue: closing ? 0 : 1,
      duration: reduced ? 0 : closing ? 170 : 220,
      easing: paperEase,
      useNativeDriver: true,
    });
    animation.start(({ finished }) => { if (finished && closing) complete.current(); });
    return () => animation.stop();
  }, [closing, reduced, progress]);

  return (
    <View style={[StyleSheet.absoluteFill, styles.clip]} pointerEvents={closing ? "none" : "auto"}>
      <Animated.View style={[
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
