import React from "react";
import { Animated, Easing, Platform, Pressable, StyleSheet, View, useWindowDimensions } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { PanGestureHandler, State, type PanGestureHandlerStateChangeEvent } from "react-native-gesture-handler";
import type { TripSummary } from "../../../data/trotterMock";
import { colors } from "../../../theme/trotterTheme";
import { getMobileVisualWidth } from "../../../utils/mobileLayout";
import { useReducedMotion } from "../motion";
import { WWIcon } from "../WorldWindowUI";
import { WalletCover, walletColors } from "./WalletCover";
import { shouldDismissWallet, walletMotionFrame, walletMotionSamples, type TripOpenOrigin } from "./tripTransition";
import { walletPopupGeometry } from "./walletPopupGeometry";

type WalletPopupChildProps = {
  walletHeader?: (heading: React.ReactNode) => React.ReactNode;
  walletDragging?: boolean;
  freezeUpdates?: boolean;
};

/** A single native timeline lifts and opens the wallet without scaling its paper. */
export function TripNavigationSurface({ origin, closing, onClosed, onRequestClose, closeLabel = "Close itinerary", children, motionProgress, onEntered }: {
  trip: TripSummary; flightId?: string; origin?: TripOpenOrigin;
  closing: boolean; onClosed: () => void; onRequestClose: () => void;
  closeLabel?: string; children: React.ReactNode;
  motionProgress?: Animated.Value;
  onEntered?: () => void;
}) {
  const reduced = useReducedMotion();
  const localProgress = React.useRef(new Animated.Value(reduced ? 1 : 0)).current;
  const progress = motionProgress ?? localProgress;
  const dragY = React.useRef(new Animated.Value(0)).current;
  const [laidOut, setLaidOut] = React.useState(false);
  const [settled, setSettled] = React.useState(reduced);
  const [dragging, setDragging] = React.useState(false);
  const [gestureBusy, setGestureBusy] = React.useState(false);
  const entered = React.useRef(reduced);
  const { width, height } = useWindowDimensions();
  const insets = useSafeAreaInsets();
  const viewportWidth = Platform.OS === "web" ? getMobileVisualWidth(width) : width;
  // Hydration and source-list updates must never move an in-flight wallet.
  const capturedOrigin = React.useRef(origin).current;
  const { target, source, anchored } = walletPopupGeometry(viewportWidth, height, insets.top, insets.bottom, capturedOrigin);
  const complete = React.useRef(onClosed);
  complete.current = onClosed;
  const didEnter = React.useRef(onEntered);
  didEnter.current = onEntered;
  const requestClose = React.useRef(onRequestClose);
  requestClose.current = onRequestClose;
  const closingNow = React.useRef(closing);
  closingNow.current = closing;
  const gestureGeneration = React.useRef(0);
  const gestureBegan = React.useRef(false);
  const dragSpring = React.useRef<Animated.CompositeAnimation | undefined>(undefined);
  const alive = React.useRef(true);
  React.useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      gestureGeneration.current++;
      dragSpring.current?.stop();
      dragY.stopAnimation();
    };
  }, [dragY]);

  React.useEffect(() => {
    progress.stopAnimation();
    let animation: Animated.CompositeAnimation | undefined;
    let dragExit: Animated.CompositeAnimation | undefined;
    let firstFrame: number | undefined, secondFrame: number | undefined;
    let cancelled = false;
    const timing = (toValue: number, duration: number) => Animated.timing(progress, {
      toValue, duration, easing: Easing.linear, useNativeDriver: true,
    });
    const start = () => {
      if (cancelled) return;
      const duration = reduced || (closing && !entered.current) ? 0 : closing ? 210 : anchored ? 300 : 245;
      const timeline = reduced || (closing && !entered.current)
        ? timing(closing ? 0 : 1, 0)
        : timing(closing ? 0 : 1, duration);
      if (closing || entered.current) {
        setSettled(reduced && !closing);
        setDragging(false);
        gestureBegan.current = false;
        gestureGeneration.current++;
        dragSpring.current?.stop();
        dragY.flattenOffset();
        dragExit = Animated.timing(dragY, {
          toValue: 0, duration, easing: Easing.bezier(.2, .8, .2, 1), useNativeDriver: true,
        });
        dragExit.start();
      }
      animation = timeline;
      if (!closing) entered.current = true;
      animation.start(({ finished }) => {
        if (!cancelled && finished) {
          if (closing) complete.current();
          else { setSettled(true); setGestureBusy(false); didEnter.current?.(); }
        }
      });
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
      dragExit?.stop();
    };
  }, [closing, reduced, laidOut, progress, anchored, dragY]);

  const dragMotion = React.useMemo(() => ({
    position: dragY.interpolate({ inputRange: [-200, 0, 1000], outputRange: [-24, 0, 1000], extrapolateLeft: "clamp" }),
    shade: dragY.interpolate({ inputRange: [0, 260], outputRange: [1, .5], extrapolate: "clamp" }),
    event: Animated.event([{ nativeEvent: { translationY: dragY } }], { useNativeDriver: true }),
  }), [dragY]);

  const onHeaderGesture = (event: PanGestureHandlerStateChangeEvent) => {
    if (!alive.current || closingNow.current || !settled) return;
    const { state, oldState, velocityY } = event.nativeEvent;
    if (state === State.BEGAN) {
      gestureGeneration.current++;
      gestureBegan.current = true;
      dragSpring.current?.stop();
      dragY.stopAnimation();
      // Native offset extraction preserves the current spring position on re-grab.
      dragY.extractOffset();
      return;
    }
    if (state === State.ACTIVE) {
      setDragging(true);
      setGestureBusy(true);
      return;
    }
    if ((state !== State.END && state !== State.CANCELLED && state !== State.FAILED) || !gestureBegan.current) return;
    gestureBegan.current = false;
    setDragging(false);
    dragY.flattenOffset();
    const generation = ++gestureGeneration.current;
    dragY.stopAnimation((distance) => {
      if (!alive.current || closingNow.current || generation !== gestureGeneration.current) return;
      if (state === State.END && oldState === State.ACTIVE && shouldDismissWallet(distance, velocityY, target.height)) {
        requestClose.current();
        return;
      }
      dragSpring.current = reduced
        ? Animated.timing(dragY, { toValue: 0, duration: 0, useNativeDriver: true })
        : Animated.spring(dragY, { toValue: 0, stiffness: 280, damping: 30, mass: 1,
          overshootClamping: true, restDisplacementThreshold: .25, restSpeedThreshold: .25, useNativeDriver: true });
      dragSpring.current.start(({ finished }) => {
        if (finished && alive.current && !closingNow.current && generation === gestureGeneration.current) setGestureBusy(false);
      });
    });
  };
  const walletHeader = (heading: React.ReactNode) => (
    <PanGestureHandler enabled={settled && !closing} minPointers={1} maxPointers={1}
      activeOffsetY={8} failOffsetY={-8} failOffsetX={[-18, 18]} shouldCancelWhenOutside={false}
      onGestureEvent={dragMotion.event} onHandlerStateChange={onHeaderGesture}>
      <Animated.View collapsable={false} testID="wallet-drag-header">{heading}</Animated.View>
    </PanGestureHandler>
  );
  const content = React.isValidElement<WalletPopupChildProps>(children)
    ? React.cloneElement(children, { walletHeader, walletDragging: dragging,
      freezeUpdates: children.props.freezeUpdates || gestureBusy })
    : children;

  const clipWidth = Math.max(source.width, target.width), clipHeight = Math.max(source.height, target.height);
  const { translateX, translateY, scaleX, scaleY, cropX, cropY, restoreX, restoreY, coverOpacity, summaryOpacity, curtainOpacity, sourceScaleX, tintOpacity, dismissOpacity } = React.useMemo(() => {
    const dx = source.x - target.x, dy = source.y - target.y;
    const values = walletMotionSamples.map(value => walletMotionFrame(value, anchored));
    const tween = (pick: (value: ReturnType<typeof walletMotionFrame>) => number) => progress.interpolate({
      inputRange: walletMotionSamples, outputRange: values.map(pick), extrapolate: "clamp",
    });
    const cropX = tween(value => source.width + (target.width - source.width) * value.expansion - clipWidth);
    const cropY = tween(value => source.height + (target.height - source.height) * value.expansion - clipHeight);
    return {
      translateX: tween(value => dx * (1 - value.travel)),
      translateY: tween(value => dy * (1 - value.travel) - value.lift),
      scaleX: tween(value => (source.width + (target.width - source.width) * value.expansion) / target.width),
      scaleY: tween(value => (source.height + (target.height - source.height) * value.expansion) / target.height),
      cropX, cropY, restoreX: Animated.multiply(cropX, -1), restoreY: Animated.multiply(cropY, -1),
      coverOpacity: tween(value => value.cover), summaryOpacity: tween(value => value.summary),
      curtainOpacity: tween(value => 1 - value.reveal),
      sourceScaleX: tween(value => (source.width + (target.width - source.width) * value.expansion) / source.width),
      tintOpacity: progress.interpolate({ inputRange: [0, 1], outputRange: [0, .22] }),
      dismissOpacity: progress.interpolate({ inputRange: [0, .35, 1], outputRange: [0, 0, 1] }),
    };
  }, [progress, anchored, source.x, source.y, source.width, source.height, target.x, target.y, target.width, target.height, clipWidth, clipHeight]);

  return (
    <View testID="wallet-popup" style={[StyleSheet.absoluteFill, styles.clip]}
      accessibilityViewIsModal onAccessibilityEscape={onRequestClose}>
      <Animated.View pointerEvents="none" testID="wallet-backdrop-tint" style={[StyleSheet.absoluteFill, styles.tint,
        { opacity: Animated.multiply(reduced ? .22 : tintOpacity, dragMotion.shade) }]} />
      <Pressable testID="wallet-backdrop" style={StyleSheet.absoluteFill} accessible={false}
        onPress={closing ? undefined : onRequestClose} />
      <Animated.View testID="wallet-drag-stage" pointerEvents="box-none"
        style={[StyleSheet.absoluteFill, { transform: [{ translateY: dragMotion.position }] }]}>
      <Animated.View testID="wallet-popup-paper" pointerEvents="none" style={[styles.paper,
        { left: target.x, top: target.y, width: target.width, height: target.height,
          transform: reduced ? [] : [{ translateX }, { translateY }, { scaleX }, { scaleY }] }]} />
      <Animated.View testID="wallet-popup-panel" onLayout={() => { if (!closing) setLaidOut(true); }}
        pointerEvents={closing ? "none" : "auto"}
        style={[styles.panel, { left: target.x, top: target.y, width: clipWidth, height: clipHeight,
          transform: reduced ? [] : [{ translateX }, { translateY }] }]}>
        {/* Intersect two full-size clips. Their opposing translations reveal a growing
            rectangle while the map and type keep their original raster dimensions. */}
        <Animated.View testID="wallet-popup-crop" style={[styles.paperClip, { width: clipWidth, height: clipHeight,
          transform: reduced ? [] : [{ translateX: cropX }, { translateY: cropY }] }]}>
          <Animated.View testID="wallet-popup-content" style={{ width: target.width, height: target.height,
            opacity: 1, transform: reduced ? [] : [{ translateX: restoreX }, { translateY: restoreY }] }}>
            {content}
            {/* Paint native SVGs before revealing them, rather than first rasterizing mid-turn. */}
            <Animated.View testID="wallet-reveal-curtain" pointerEvents="none" accessible={false}
              accessibilityElementsHidden importantForAccessibility="no-hide-descendants"
              style={[StyleSheet.absoluteFill, { backgroundColor: walletColors.blue,
                opacity: reduced ? 0 : curtainOpacity }]} />
          </Animated.View>
        </Animated.View>
      </Animated.View>
      {anchored && !reduced && capturedOrigin?.wallet && (
        <Animated.View testID="wallet-source-cover" pointerEvents="none" accessible={false}
          accessibilityElementsHidden importantForAccessibility="no-hide-descendants"
          style={{ position: "absolute", left: target.x, top: target.y, width: source.width,
            zIndex: 3, elevation: 16,
            transformOrigin: "top left", opacity: coverOpacity,
            transform: [{ translateX }, { translateY }, { scaleX: sourceScaleX }] }}>
          <WalletCover {...capturedOrigin.wallet} embedded bodyOpacity={summaryOpacity} onPress={() => {}} />
        </Animated.View>
      )}
      <Animated.View testID="wallet-popup-dismiss" style={{ position: "absolute", right: target.x,
        zIndex: 4, elevation: 20,
        top: insets.top + 3, opacity: reduced ? 1 : dismissOpacity }}>
        <Pressable accessibilityRole="button" accessibilityLabel={closeLabel}
          disabled={closing} onPress={onRequestClose} style={styles.close}>
          <WWIcon name="close" size={20} color={colors.ink} />
        </Pressable>
      </Animated.View>
      </Animated.View>
    </View>
  );
}

const styles = StyleSheet.create({
  clip: { overflow: "hidden" },
  tint: { backgroundColor: "#183642" },
  paper: { position: "absolute", zIndex: 1, transformOrigin: "top left", borderRadius: 9,
    backgroundColor: walletColors.blue, shadowColor: "#102c3a", shadowOpacity: .23,
    shadowOffset: { width: 0, height: 10 }, shadowRadius: 18, elevation: 11 },
  panel: { position: "absolute", zIndex: 2, elevation: 12, overflow: "hidden", borderRadius: 9 },
  paperClip: { overflow: "hidden", borderRadius: 9 },
  close: { width: 44, height: 44, borderRadius: 22, backgroundColor: colors.paperSoft,
    justifyContent: "center", alignItems: "center", borderWidth: 1, borderColor: colors.paperBorder },
});
