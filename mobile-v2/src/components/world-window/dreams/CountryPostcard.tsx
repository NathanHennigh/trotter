import React from "react";
import {
  AccessibilityInfo,
  Animated,
  Easing,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { colors, fonts } from "../../../theme/trotterTheme";
import { WWIcon } from "../WorldWindowUI";
import { CountryBoard } from "./dreamPresentation";
import { DreamPhoto } from "./DreamPhoto";
import { postcardReelCover } from "./dreamImageSource";
import { getApiBaseUrl } from "../../../services/travelTrips";

export function CountryPostcard({
  board,
  onPress,
}: {
  board: CountryBoard;
  onPress: () => void;
}) {
  const turn = React.useRef(new Animated.Value(0)).current;
  const mounted = React.useRef(true),
    opening = React.useRef(false),
    dispatched = React.useRef(false),
    reduceMotion = React.useRef(true),
    open = React.useRef(onPress);
  const [turning, setTurning] = React.useState(false);
  open.current = onPress;
  const finish = React.useCallback(() => {
    if (!mounted.current || dispatched.current) return;
    dispatched.current = true;
    open.current();
  }, []);
  React.useEffect(() => {
    mounted.current = true;
    const update = (enabled: boolean) => {
      if (!mounted.current) return;
      reduceMotion.current = enabled;
      if (enabled && opening.current && !dispatched.current) {
        finish();
        turn.stopAnimation();
      }
    };
    void AccessibilityInfo.isReduceMotionEnabled()
      .then(update)
      .catch(() => {});
    const subscription = AccessibilityInfo.addEventListener(
      "reduceMotionChanged",
      update,
    );
    return () => {
      mounted.current = false;
      subscription.remove();
      turn.stopAnimation();
    };
  }, [finish, turn]);
  const handlePress = () => {
    if (!mounted.current || opening.current) return;
    opening.current = true;
    if (reduceMotion.current) {
      finish();
      return;
    }
    setTurning(true);
    Animated.timing(turn, {
      toValue: 1,
      duration: 180,
      easing: Easing.bezier(0.32, 0, 0.67, 1),
      useNativeDriver: true,
    }).start(({ finished }) => {
      if (!mounted.current) return;
      if (finished) finish();
      else if (!dispatched.current) {
        opening.current = false;
        setTurning(false);
        turn.setValue(0);
      }
    });
  };
  const cover = postcardReelCover(board.items, getApiBaseUrl());
  return (
    <Pressable
      onPress={handlePress}
      disabled={turning}
      accessibilityRole="button"
      accessibilityState={{ disabled: turning }}
      accessibilityLabel={`${board.title}, view ${board.items.length} saved places`}
    >
      <Animated.View
        renderToHardwareTextureAndroid={turning}
        style={[
          s.card,
          {
            backfaceVisibility: "hidden",
            transform: [
              { perspective: 1000 },
              {
                rotateY: turn.interpolate({
                  inputRange: [0, 1],
                  outputRange: ["0deg", "-88deg"],
                }),
              },
            ],
            opacity: turn.interpolate({
              inputRange: [0, 0.75, 1],
              outputRange: [1, 1, 0.5],
            }),
          },
        ]}
      >
        <View style={s.photo}>
          <DreamPhoto item={cover} fallbackCountry={board.title} artworkForCountry={board.title} />
        </View>
        <View style={s.address}>
          <Text style={s.country}>{board.title}</Text>
          <Text style={s.cities}>
            {board.items.length} saved{" "}
            {board.items.length === 1 ? "place" : "places"}
            {board.cities.length
              ? ` · ${board.cities.length} ${board.cities.length === 1 ? "city" : "cities"}`
              : ""}
            <Text style={{ color: colors.blue }}> ↗</Text>
          </Text>
        </View>
      </Animated.View>
    </Pressable>
  );
}
const s = StyleSheet.create({
  card: {
    marginHorizontal: 24,
    marginBottom: 25,
    padding: 10,
    paddingBottom: 0,
    backgroundColor: "#fffdf5",
    borderWidth: 1,
    borderColor: "#c6c9bb",
    shadowColor: colors.ink,
    shadowOpacity: 0.08,
    shadowOffset: { width: 0, height: 3 },
    shadowRadius: 7,
    elevation: 1,
  },
  photo: {
    height: 197,
    overflow: "hidden",
    borderWidth: 1,
    borderColor: "#d7d9ca",
  },
  address: {
    gap: 8,
    paddingHorizontal: 5,
    paddingTop: 19,
    paddingBottom: 21,
  },
  copy: { flex: 1 },
  country: {
    fontSize: 40,
    lineHeight: 43,
    color: colors.ink,
    fontFamily: fonts.displayItalic,
    letterSpacing: -1.1,
    includeFontPadding: false,
  },
  cities: {
    fontFamily: fonts.sansRegular,
    fontSize: 12,
    lineHeight: 19,
    color: colors.mutedInk,
  },
  count: {
    minWidth: 48,
    paddingLeft: 13,
    borderLeftWidth: 1,
    borderLeftColor: colors.paperBorderSoft,
    alignItems: "center",
    justifyContent: "center",
  },
  number: { fontFamily: fonts.mono, fontSize: 22, color: colors.red },
  countLabel: {
    fontFamily: fonts.sansRegular,
    fontSize: 10,
    color: colors.mutedInk,
    marginTop: 3,
  },
  footer: {
    marginHorizontal: 12,
    paddingTop: 10,
    paddingBottom: 7,
    borderTopWidth: 1,
    borderTopColor: colors.paperBorderSoft,
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  open: { fontFamily: fonts.sansSemi, fontSize: 11, color: colors.blue },
});
