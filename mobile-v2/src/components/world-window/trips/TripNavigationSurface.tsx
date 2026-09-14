import React from "react";
import { Animated, Platform, StyleSheet, Text, View, useWindowDimensions } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import type { TripSummary } from "../../../data/trotterMock";
import { colors, fonts } from "../../../theme/trotterTheme";
import { getMobileVisualWidth } from "../../../utils/mobileLayout";
import { paperEase, useReducedMotion } from "../motion";
import { WalletCover } from "./WalletCover";
import type { TripOpenOrigin } from "./tripTransition";
import { flightDate } from "./tripPresentation";

/** Carry the opening paper to its destination; the real screen never scales. */
export function TripNavigationSurface({ trip, flightId, origin, target, closing, onClosed, children }: {
  trip: TripSummary; flightId?: string; origin?: TripOpenOrigin; target?: TripOpenOrigin;
  closing: boolean; onClosed: () => void; children: React.ReactNode;
}) {
  const progress = React.useRef(new Animated.Value(0)).current;
  const reduced = useReducedMotion(), insets = useSafeAreaInsets(), { width } = useWindowDimensions();
  const visualWidth = getMobileVisualWidth(width);
  const hostX = Platform.OS === "web" ? Math.max(0, (width - visualWidth) / 2) : 0;
  const complete = React.useRef(onClosed);
  complete.current = onClosed;
  const ready = Boolean(target) || !origin || reduced;
  const [fallbackReady, setFallbackReady] = React.useState(false);
  React.useEffect(() => {
    if (ready) return;
    const timer = setTimeout(() => setFallbackReady(true), 100);
    return () => clearTimeout(timer);
  }, [ready]);
  const canAnimate = ready || fallbackReady;
  React.useEffect(() => {
    if (!closing && !canAnimate) return;
    progress.stopAnimation();
    const animation = Animated.timing(progress, { toValue: closing ? 0 : 1,
      duration: reduced ? 0 : closing ? 170 : 240, easing: paperEase, useNativeDriver: true });
    animation.start(({ finished }) => { if (finished && closing) complete.current(); });
    return () => animation.stop();
  }, [closing, canAnimate, reduced, progress]);
  const destination = target ?? { x: hostX + 20, y: insets.top + 55, width: visualWidth - 40, height: 220 };
  const flight = trip.segments?.find(segment => segment.id === flightId);
  const source = origin && [origin.x, origin.y, origin.width, origin.height].every(Number.isFinite) && origin.width > 0 && origin.height > 0 ? origin : undefined;
  const ghostOpacity = progress.interpolate({ inputRange: [0, .45, .64, 1], outputRange: [1, 1, 0, 0] });
  return <View style={StyleSheet.absoluteFill} pointerEvents={closing ? "none" : "auto"}>
    <Animated.View pointerEvents="none" style={[StyleSheet.absoluteFill, { backgroundColor: colors.paperSoft, opacity: progress.interpolate({ inputRange: [0, .3, 1], outputRange: [0, 1, 1] }) }]} />
    <Animated.View style={[StyleSheet.absoluteFill, { opacity: source && !reduced ? progress.interpolate({ inputRange: [0, .64, 1], outputRange: [0, 0, 1] }) : progress,
      transform: source || reduced ? [] : [{ translateY: progress.interpolate({ inputRange: [0, 1], outputRange: [16, 0] }) }] }]}>
      {children}
    </Animated.View>
    {source && !reduced ? <Animated.View pointerEvents="none" accessibilityElementsHidden importantForAccessibility="no-hide-descendants"
      style={{ position: "absolute", left: source.x - hostX, top: source.y, width: source.width, opacity: ghostOpacity,
        transform: [
          { translateX: progress.interpolate({ inputRange: [0, 1], outputRange: [0, destination.x - source.x + (destination.width - source.width) / 2] }) },
          { translateY: progress.interpolate({ inputRange: [0, 1], outputRange: [0, destination.y - source.y + source.height * (destination.width / source.width - 1) / 2] }) },
          { scale: progress.interpolate({ inputRange: [0, 1], outputRange: [1, destination.width / source.width] }) },
        ] }}>
      {flight ? <View style={styles.ticket}>
        <Text style={styles.carrier}>{flight.airline} {flight.flightNumber}</Text>
        <View style={styles.route}><Text style={styles.airport}>{flight.depAirport}</Text><Text style={styles.arrow}>→</Text><Text style={styles.airport}>{flight.arrAirport}</Text></View>
        <Text style={styles.date}>{flightDate(flight.depTime)}</Text>
      </View> : <WalletCover trip={source.wallet?.trip ?? trip} scopeYear={source.wallet?.scopeYear}
        totalFlightCount={source.wallet?.totalFlightCount} embedded onPress={() => undefined} />}
    </Animated.View> : null}
  </View>;
}
const styles = StyleSheet.create({
  ticket: { padding: 20, backgroundColor: colors.paper, borderWidth: 1, borderColor: colors.paperBorder, borderRadius: 8, gap: 12 },
  carrier: { color: colors.mutedInk, fontFamily: fonts.sansSemi, fontSize: 12 },
  route: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  airport: { fontFamily: fonts.mono, color: colors.ink, fontSize: 35 },
  arrow: { fontSize: 22, color: colors.blue },
  date: { fontFamily: fonts.sansRegular, color: colors.mutedInk, fontSize: 13, paddingTop: 10, borderTopWidth: 1, borderTopColor: colors.paperBorder },
});
