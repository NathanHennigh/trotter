import React from "react";
import { Animated, Platform, requireNativeComponent, StyleSheet, UIManager, View, type ViewProps } from "react-native";

type NativeBlurProps = ViewProps & { blurRadius: number };
function nativeBackground() {
  if (Platform.OS !== "android" || Number(Platform.Version) < 31) return undefined;
  try {
    if (!UIManager.getViewManagerConfig("TrotterBlurBackground")) return undefined;
    return Animated.createAnimatedComponent(requireNativeComponent<NativeBlurProps>("TrotterBlurBackground"));
  } catch {
    // Expo Go/older development clients retain the ordinary, dimmed background.
    return undefined;
  }
}
const NativeBackground = nativeBackground();

/** One persistent background, driven by the same native timeline as the wallet. */
export function TripBackground({ progress, dragOffset, children }: {
  progress: Animated.Value; dragOffset: Animated.Value; children: React.ReactNode;
}) {
  const radius = React.useMemo(() => Animated.multiply(
    progress.interpolate({ inputRange: [0, .06, .65, 1], outputRange: [0, 0, 4, 4], extrapolate: "clamp" }),
    dragOffset.interpolate({ inputRange: [0, 260], outputRange: [1, .5], extrapolate: "clamp" }),
  ), [progress, dragOffset]);
  if (NativeBackground) return <NativeBackground testID="trip-background" collapsable={false}
    blurRadius={radius} style={styles.background}>{children}</NativeBackground>;
  if (Platform.OS === "web") return <Animated.View testID="trip-background" collapsable={false}
    style={[styles.background, { filter: radius.interpolate({ inputRange: [0, 4], outputRange: ["blur(0px)", "blur(4px)"] }) }]}>
    {children}
  </Animated.View>;
  return <View testID="trip-background" collapsable={false} style={styles.background}>{children}</View>;
}

const styles = StyleSheet.create({ background: { ...StyleSheet.absoluteFillObject } });
