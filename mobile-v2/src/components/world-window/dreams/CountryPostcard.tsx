import React from "react";
import {
  AccessibilityInfo,
  Animated,
  Easing,
  Pressable,
  StyleSheet,
  Text,
  useWindowDimensions,
  View,
} from "react-native";
import Svg, { Defs, LinearGradient, Rect, Stop } from "react-native-svg";
import { fitDisplayFont } from "../displayTextFit";
import { getMobileVisualWidth } from "../../../utils/mobileLayout";
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
  const { width, fontScale } = useWindowDimensions();
  const photoWidth = getMobileVisualWidth(width) - 66;
  const countrySize = fitDisplayFont(
    board.title, 40, photoWidth - 32, fontScale, "italic",
  );
  const shadeId = `postcard-${React.useId().replace(/:/g, "")}`;
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
      accessibilityLabel={`${board.title}, view ${board.items.length} saved ${board.items.length === 1 ? "place" : "places"}`}
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
        <View style={[s.photo, { minHeight: photoWidth / 1.65 }]}>
          <View style={StyleSheet.absoluteFill}>
            <DreamPhoto item={cover} artworkForCountry={board.title} />
          </View>
          <View style={s.printedTitle}>
            <Svg
              pointerEvents="none"
              accessibilityElementsHidden
              importantForAccessibility="no-hide-descendants"
              style={StyleSheet.absoluteFill}
              width="100%"
              height="100%"
              preserveAspectRatio="none"
              viewBox="0 0 100 100"
            >
              <Defs>
                <LinearGradient id={shadeId} x1="0" y1="0" x2="0" y2="100%">
                  <Stop offset="0" stopColor="#132E3C" stopOpacity={0} />
                  <Stop offset="0.4" stopColor="#132E3C" stopOpacity={0.34} />
                  <Stop offset="1" stopColor="#132E3C" stopOpacity={0.75} />
                </LinearGradient>
              </Defs>
              <Rect width="100" height="100" fill={`url(#${shadeId})`} />
            </Svg>
            <Text
              style={[
                s.country,
                { fontSize: countrySize, lineHeight: countrySize * 1.1 },
              ]}
            >
              {board.title}
            </Text>
          </View>
        </View>
        <View style={s.caption}>
          <Text style={s.cities}>
            {board.items.length} saved{" "}
            {board.items.length === 1 ? "place" : "places"}
            {board.cities.length
              ? ` ·\u00a0${board.cities.length}\u00a0${board.cities.length === 1 ? "city" : "cities"}`
              : ""}
          </Text>
          <View accessibilityElementsHidden importantForAccessibility="no-hide-descendants">
            <WWIcon name="arrow" size={16} color={colors.ink} />
          </View>
        </View>
      </Animated.View>
    </Pressable>
  );
}
const s = StyleSheet.create({
  card: {
    marginHorizontal: 24,
    marginBottom: 22,
    padding: 8,
    paddingBottom: 0,
    backgroundColor: "#fffdf5",
    borderWidth: 1,
    borderBottomWidth: 2,
    borderColor: "#cbd0c5",
    borderBottomColor: "#bcc5bb",
    shadowColor: colors.ink,
    shadowOpacity: 0.1,
    shadowOffset: { width: 0, height: 3 },
    shadowRadius: 5,
    elevation: 2,
  },
  photo: {
    overflow: "hidden",
    justifyContent: "flex-end",
    backgroundColor: colors.paperDeep,
  },
  printedTitle: {
    paddingHorizontal: 16,
    paddingTop: 48,
    paddingBottom: 14,
  },
  country: {
    color: "#fffdf5",
    fontFamily: fonts.displayItalic,
    letterSpacing: -0.65,
    includeFontPadding: false,
    textShadowColor: "rgba(10, 24, 29, 0.3)",
    textShadowOffset: { width: 0, height: 1 },
    textShadowRadius: 2,
  },
  caption: {
    minHeight: 35,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 10,
    paddingHorizontal: 3,
    paddingVertical: 8,
  },
  cities: {
    flex: 1,
    fontFamily: fonts.sansRegular,
    fontSize: 11,
    lineHeight: 17,
    color: colors.mutedInk,
  },
});
