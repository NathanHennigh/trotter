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
import { fitDisplayFont } from "../displayTextFit";
import { getMobileVisualWidth } from "../../../utils/mobileLayout";
import { colors, fonts } from "../../../theme/trotterTheme";
import { WWIcon } from "../WorldWindowUI";
import { CountryBoard } from "./dreamPresentation";
import { DreamPhoto } from "./DreamPhoto";
import { postcardReelCover } from "./dreamImageSource";
import { dreamProcessingSummary } from "./dreamProcessing";
import { getApiBaseUrl } from "../../../services/travelTrips";

export function CountryPostcard({
  board,
  onPress,
  returning = false,
  visible = true,
  onReturned,
}: {
  board: CountryBoard;
  onPress: () => void;
  returning?: boolean;
  visible?: boolean;
  onReturned?: () => void;
}) {
  const { width, fontScale } = useWindowDimensions();
  const photoWidth = getMobileVisualWidth(width) - 66;
  const countrySize = fitDisplayFont(
    board.title, 40, photoWidth - 32, fontScale, "italic",
  );
  const turn = React.useRef(new Animated.Value(returning ? 1 : 0)).current;
  const returnPending = React.useRef(returning);
  const returningNow = React.useRef(returning);
  const isVisible = React.useRef(visible), didReturn = React.useRef(onReturned);
  isVisible.current = visible; didReturn.current = onReturned;
  const mounted = React.useRef(true),
    opening = React.useRef(false),
    dispatched = React.useRef(false),
    reduceMotion = React.useRef(true),
    open = React.useRef(onPress);
  const [turning, setTurning] = React.useState(false);
  open.current = onPress;
  const finish = React.useCallback(() => {
    if (!mounted.current || !isVisible.current || dispatched.current) return;
    dispatched.current = true;
    open.current();
  }, []);
  React.useEffect(() => {
    mounted.current = true;
    const update = (enabled: boolean) => {
      if (!mounted.current) return;
      reduceMotion.current = enabled;
      if (returnPending.current) {
        returnPending.current = false;
        if (enabled || !isVisible.current) { turn.setValue(0); returningNow.current = false; didReturn.current?.(); }
        else {
          setTurning(true);
          Animated.timing(turn, { toValue: 0, duration: 140, easing: Easing.bezier(0.23, 1, 0.32, 1), useNativeDriver: true })
            .start(() => { if (mounted.current) { turn.setValue(0); returningNow.current = false; setTurning(false); didReturn.current?.(); } });
        }
      }
      if (enabled && returningNow.current) turn.stopAnimation();
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
  React.useEffect(() => {
    if (!visible) {
      turn.stopAnimation(); turn.setValue(0);
      opening.current = false; dispatched.current = false;
      setTurning(false);
    }
  }, [visible, turn]);
  const handlePress = () => {
    if (!mounted.current || !isVisible.current || opening.current || returningNow.current || turning) return;
    opening.current = true;
    if (reduceMotion.current) {
      finish();
      return;
    }
    setTurning(true);
    Animated.timing(turn, {
      toValue: 1,
      duration: 120,
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
                  outputRange: ["0deg", "-76deg"],
                }),
              },
            ],
          },
        ]}
      >
        <View style={[s.photo, { minHeight: photoWidth / 1.65 }]}>
          <View style={StyleSheet.absoluteFill}>
            <DreamPhoto item={cover} artworkForCountry={board.title} />
          </View>
          <View style={s.printedTitle}>
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
            {board.key === "unsorted" ? dreamProcessingSummary(board.items) || `${board.items.length} saved reels` : <>{board.items.length} saved{" "}
            {board.items.length === 1 ? "place" : "places"}
            {board.cities.length
              ? ` ·\u00a0${board.cities.length}\u00a0${board.cities.length === 1 ? "city" : "cities"}`
              : ""}</>}
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
    backgroundColor: colors.paperPhoto,
    borderWidth: 1,
    borderBottomWidth: 2,
    borderColor: colors.paperBorder,
    borderBottomColor: "#bcc5bb",
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
    color: colors.paperPhoto,
    fontFamily: fonts.displayItalic,
    letterSpacing: -0.65,
    includeFontPadding: false,
    textShadowColor: "rgba(10, 24, 29, 0.65)",
    textShadowOffset: { width: 0, height: 1 },
    textShadowRadius: 3,
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
