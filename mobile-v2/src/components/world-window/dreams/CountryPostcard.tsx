import React from "react";
import {
  StyleSheet,
  Text,
  useWindowDimensions,
  View,
} from "react-native";
import { PressFeedback as Pressable } from "../motion";
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
  visible = true,
}: {
  board: CountryBoard;
  onPress: () => void;
  visible?: boolean;
}) {
  const { width, fontScale } = useWindowDimensions();
  const photoWidth = getMobileVisualWidth(width) - 66;
  const countrySize = fitDisplayFont(
    board.title, 40, photoWidth - 32, fontScale, "italic",
  );
  const cover = postcardReelCover(board.items, getApiBaseUrl());
  return (
    <Pressable
      onPress={() => { if (visible) onPress(); }}
      disabled={!visible}
      accessibilityRole="button"
      accessibilityState={{ disabled: !visible }}
      accessibilityLabel={`${board.title}, view ${board.items.length} saved ${board.items.length === 1 ? "place" : "places"}`}
    >
      <View style={s.card}>
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
              ? ` ·\u00a0${board.cities.length}\u00a0${board.cities.length === 1 ? "destination" : "destinations"}`
              : ""}</>}
          </Text>
          <View accessibilityElementsHidden importantForAccessibility="no-hide-descendants">
            <WWIcon name="arrow" size={16} color={colors.ink} />
          </View>
        </View>
      </View>
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
