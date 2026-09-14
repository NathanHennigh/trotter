import React from "react";
import { Pressable, StyleSheet, Text, useWindowDimensions, View } from "react-native";
import Svg, { Path, Circle, Ellipse, Rect } from "react-native-svg";
import paths from "./emblem-paths.json";
import { fitDisplayFont } from "./displayTextFit";
import { getMobileVisualWidth } from "../../utils/mobileLayout";
import { colors, fonts } from "../../theme/trotterTheme";
import { PressFeedback } from "./motion";

export function WWEmblem({
  size = 32,
  color = colors.blue,
}: {
  size?: number;
  color?: string;
}) {
  return (
    <Svg
      width={(size * 450) / 333}
      height={size}
      viewBox="64 147 450 333"
      fill={color}
      accessibilityElementsHidden
      importantForAccessibility="no"
    >
      <>
        {paths.map((d, i) => (
          <Path key={i} d={d} />
        ))}
      </>
    </Svg>
  );
}
export function WWIcon({
  name,
  size = 22,
  color = colors.ink,
  strokeWidth = 1.6,
}: {
  name: string;
  size?: number;
  color?: string;
  strokeWidth?: number;
}) {
  const shapes: Record<string, React.ReactNode> = {
    daylight: (
      <>
        <Circle cx="12" cy="12" r="9" />
        <Path d="M12 3a9 9 0 0 0 0 18Z" fill={color} stroke="none" />
      </>
    ),
    globe: (
      <>
        <Circle cx="12" cy="12" r="9" />
        <Ellipse cx="12" cy="12" rx="4" ry="9" />
        <Path d="M3 12h18M5 6.5q7 4 14 0M5 17.5q7-4 14 0" />
      </>
    ),
    trips: (
      <>
        <Rect x="4" y="7" width="16" height="13" rx="2" />
        <Path d="M9 7V4h6v3M8 11v5m8-5v5" />
      </>
    ),
    suitcase: (
      <>
        <Rect x="4" y="7" width="16" height="13" rx="2" />
        <Path d="M9 7V4h6v3" />
      </>
    ),
    passport: (
      <>
        <Rect x="5" y="3" width="14" height="18" rx="2" />
        <Circle cx="12" cy="10" r="3" />
        <Path d="M9 17h6M12 7v6M9 10h6" />
      </>
    ),
    dreams: <Path d="M6 3h12v18l-6-4-6 4Z" />,
    profile: (
      <>
        <Circle cx="12" cy="8" r="3.5" />
        <Path d="M5 21v-3a7 7 0 0 1 14 0v3" />
      </>
    ),
    arrow: <Path d="M4 12h16m-6-6 6 6-6 6" />,
    back: <Path d="M20 12H4m6-6-6 6 6 6" />,
    plus: <Path d="M12 4v16M4 12h16" />,
    close: <Path d="m6 6 12 12M6 18 18 6" />,
    search: (
      <>
        <Circle cx="10" cy="10" r="6.5" />
        <Path d="m15 15 6 6" />
      </>
    ),
    check: <Path d="m5 12 4 4L19 6" />,
    sync: (
      <Path d="M20 9a8 8 0 0 0-14-5L3 7m0-5v5h5M4 15a8 8 0 0 0 14 5l3-3m0 5v-5h-5" />
    ),
    pin: (
      <>
        <Path d="M18 10c0 5-6 10-6 10S6 15 6 10a6 6 0 1 1 12 0Z" />
        <Circle cx="12" cy="10" r="2" />
      </>
    ),
    plane: <Path d="m21 3-7 8 2 8-2 2-4-7-5 3-3-1 6-6-4-5 2-2 7 4Z" />,
    chevron: <Path d="m8 5 7 7-7 7" />,
    down: <Path d="m5 9 7 7 7-7" />,
    sun: (
      <>
        <Circle cx="12" cy="12" r="4" />
        <Path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5" />
      </>
    ),
    logout: <Path d="M9 4H4v16h5m6-13 5 5-5 5M8 12h12" />,
    mail: (
      <>
        <Rect x="3" y="5" width="18" height="14" rx="2" />
        <Path d="m3 6 9 7 9-7" />
      </>
    ),
    settings: (
      <>
        <Circle cx="12" cy="12" r="3" />
        <Path d="m9 3 6 0 1 3 3 1 2 5-2 5-3 1-1 3H9l-1-3-3-1-2-5 2-5 3-1Z" />
      </>
    ),
  };
  return (
    <Svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke={color}
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      accessibilityElementsHidden
      importantForAccessibility="no"
    >
      {shapes[name] ?? shapes.globe}
    </Svg>
  );
}
export function WWButton({
  label,
  onPress,
  disabled = false,
  secondary = false,
}: {
  label: string;
  onPress: () => void;
  disabled?: boolean;
  secondary?: boolean;
}) {
  return (
    <PressFeedback
      accessibilityRole="button"
      accessibilityState={{ disabled }}
      onPress={onPress}
      disabled={disabled}
      style={({ pressed }) => [
        s.button,
        secondary && s.secondary,
        disabled && s.disabled,
      ]}
    >
      <Text style={[s.buttonText, secondary && { color: colors.ink }]}>
        {label}
      </Text>
    </PressFeedback>
  );
}
export function WWHeader({
  title,
  onBack,
  action,
}: {
  title: string;
  onBack?: () => void;
  action?: React.ReactNode;
}) {
  const { width, fontScale } = useWindowDimensions();
  const available = getMobileVisualWidth(width) - 48 - (onBack ? 46 : 0) - (action ? 58 : 0);
  const titleSize = fitDisplayFont(title, 38, available, fontScale);
  return (
    <View style={s.header}>
      {onBack && (
        <PressFeedback
          accessibilityRole="button"
          accessibilityLabel="Back"
          hitSlop={8}
          onPress={onBack}
          style={s.back}
        >
          <WWIcon name="back" />
        </PressFeedback>
      )}
      <Text accessibilityRole="header" style={[s.title, { fontSize: titleSize, lineHeight: titleSize * 42 / 38 }]}>
        {title}
      </Text>
      {action && <View style={{ flexShrink: 0 }}>{action}</View>}
    </View>
  );
}
export function WWEmpty({
  title,
  body,
  action,
}: {
  title: string;
  body?: string;
  action?: React.ReactNode;
}) {
  return (
    <View style={s.empty}>
      <Text style={s.emptyTitle}>{title}</Text>
      {body && <Text style={s.body}>{body}</Text>}
      {action}
    </View>
  );
}
const s = StyleSheet.create({
  button: {
    minHeight: 50,
    justifyContent: "center",
    alignItems: "center",
    paddingHorizontal: 20,
    paddingVertical: 12,
    backgroundColor: colors.ink,
    borderRadius: 4,
  },
  secondary: {
    backgroundColor: colors.paper,
    borderWidth: 1,
    borderColor: colors.paperBorder,
  },
  disabled: { opacity: 0.45 },
  buttonText: { fontFamily: fonts.sansSemi, fontSize: 15, color: colors.paper },
  header: {
    flexDirection: "row",
    alignItems: "center",
    gap: 14,
    paddingHorizontal: 24,
    paddingTop: 14,
    paddingBottom: 19,
  },
  back: { width: 32, minHeight: 44, justifyContent: "center" },
  title: {
    flex: 1,
    minWidth: 0,
    fontFamily: fonts.display,
    fontSize: 38,
    lineHeight: 42,
    letterSpacing: -0.7,
    includeFontPadding: false,
    color: colors.ink,
  },
  empty: { paddingHorizontal: 24, paddingVertical: 38, gap: 14 },
  emptyTitle: { fontFamily: fonts.display, fontSize: 31, color: colors.ink },
  body: {
    fontFamily: fonts.sansRegular,
    fontSize: 15,
    lineHeight: 23,
    color: colors.mutedInk,
  },
});
