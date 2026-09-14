import React from "react";
import { AccessibilityInfo, Animated, Easing, Pressable, StyleSheet, type PressableProps, type StyleProp, type ViewStyle } from "react-native";

export const paperEase = Easing.bezier(0.23, 1, 0.32, 1);

let motionPreference: boolean | undefined;
export function useReducedMotion() {
  const [reduced, setReduced] = React.useState(motionPreference ?? true);
  React.useEffect(() => {
    let active = true;
    const update = (value: boolean) => { motionPreference = value; if (active) setReduced(value); };
    void AccessibilityInfo.isReduceMotionEnabled().then(update).catch(() => update(true));
    const subscription = AccessibilityInfo.addEventListener("reduceMotionChanged", update);
    return () => { active = false; subscription.remove(); };
  }, []);
  return reduced;
}

export function PaperPresence({ children }: { children: React.ReactNode }) {
  const previous = React.useRef<React.ReactNode>(null);
  const [, refresh] = React.useReducer(value => value + 1, 0);
  if (children) previous.current = children;
  const visible = Boolean(children);
  const showing = React.useRef(visible);
  showing.current = visible;
  if (!previous.current) return null;
  return <PaperReveal visible={visible} onHidden={() => {
    if (!showing.current) { previous.current = null; refresh(); }
  }}>{children || previous.current}</PaperReveal>;
}

const AnimatedPressable = Animated.createAnimatedComponent(Pressable);

/** Native opacity feedback for controls; paper objects also depress by 1px. */
export function PressFeedback({ children, style, paper = false, onPressIn, onPressOut, ...props }: PressableProps & { paper?: boolean }) {
  const reduced = useReducedMotion();
  const amount = React.useRef(new Animated.Value(0)).current;
  const [pressed, setPressed] = React.useState(false);
  const baseStyle = typeof style === "function" ? style({ pressed }) : style;
  const base = StyleSheet.flatten(baseStyle);
  const opacity = typeof base?.opacity === "number" ? base.opacity : 1;
  React.useEffect(() => () => amount.stopAnimation(), [amount]);
  const change = (toValue: number) => {
    amount.stopAnimation();
    Animated.timing(amount, { toValue, duration: reduced ? 0 : toValue ? 65 : 150, easing: paperEase, useNativeDriver: true }).start();
  };
  return <AnimatedPressable {...props}
    onPressIn={event => { setPressed(true); change(1); onPressIn?.(event); }}
    onPressOut={event => { setPressed(false); change(0); onPressOut?.(event); }}
    style={[baseStyle, {
      opacity: amount.interpolate({ inputRange: [0, 1], outputRange: [opacity, opacity * (paper ? 0.96 : 0.72)] }),
      ...(paper && !reduced ? { transform: [...(Array.isArray(base?.transform) ? base.transform : []), { translateY: amount.interpolate({ inputRange: [0, 1], outputRange: [0, 1] }) }] } : {}),
    }]}>{children}</AnimatedPressable>;
}

/** A small paper reveal. Parent retains the node for reverse transitions. */
export function PaperReveal({ visible = true, children, style, distance = 12, onHidden }: {
  visible?: boolean; children: React.ReactNode; style?: StyleProp<ViewStyle>; distance?: number; onHidden?: () => void;
}) {
  const reduced = useReducedMotion();
  const amount = React.useRef(new Animated.Value(0)).current;
  const hidden = React.useRef(onHidden);
  hidden.current = onHidden;
  React.useEffect(() => {
    amount.stopAnimation();
    const animation = Animated.timing(amount, { toValue: visible ? 1 : 0, duration: reduced ? 0 : visible ? 210 : 150, easing: paperEase, useNativeDriver: true });
    animation.start(({ finished }) => { if (finished && !visible) hidden.current?.(); });
    return () => animation.stop();
  }, [visible, reduced, amount]);
  return <Animated.View pointerEvents={visible ? "auto" : "none"} style={[style, {
    opacity: amount,
    transform: [{ translateY: amount.interpolate({ inputRange: [0, 1], outputRange: [reduced ? 0 : distance, 0] }) }],
  }]}>{children}</Animated.View>;
}
