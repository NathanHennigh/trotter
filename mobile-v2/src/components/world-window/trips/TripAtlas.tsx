import React from "react";
import { StyleSheet, View } from "react-native";
import Svg, { Circle, G, Path, Rect, Text } from "react-native-svg";
import world from "../../../data/worldCountries.json";
import type { TripSegmentSummary } from "../../../data/trotterMock";
import { fonts } from "../../../theme/trotterTheme";
import { createTripAtlasGeometryCache } from "./tripAtlasGeometry";

const cachedGeometry = createTripAtlasGeometryCache();

export function TripAtlas({
  segments,
  destination,
  backgroundColor = "#f8f6ed",
  height,
  variant,
}: {
  segments: TripSegmentSummary[];
  destination?: string;
  backgroundColor?: string;
  height?: number;
  variant?: "profile";
}) {
  const profile = variant === "profile";
  const map = React.useMemo(
    () => cachedGeometry(segments, world, destination, profile ? { maxLabels: 7, prioritizeByFrequency: true } : {}),
    [segments, destination, profile],
  );
  return (
    <View
      accessible
      accessibilityRole="image"
      accessibilityLabel={`Route map. ${map.ports.map((p) => p.code).join(", ")}`}
      style={[
        s.frame,
        !profile && s.paperShadow,
        { backgroundColor },
        profile && { borderWidth: 0, borderRadius: 0 },
        height ? { height } : { aspectRatio: 400 / 230 },
      ]}
    >
      <Svg width="100%" height="100%" viewBox="0 0 400 230" fill="none">
        <Path
          d="M0 46h400M0 92h400M0 138h400M0 184h400M50 0v230M100 0v230M150 0v230M200 0v230M250 0v230M300 0v230M350 0v230"
          stroke="#9eb5b3"
          strokeWidth={0.6}
          opacity={0.4}
        />
        <Path
          d={map.landPath}
          fill={profile ? "#e4e8d7" : "#dfe7df"}
          stroke={profile ? "#759599" : "#91aaa9"}
          strokeWidth={0.55}
          fillRule="evenodd"
        />
        {map.paths.map((d, i) => (
          <Path
            key={i}
            d={d}
            stroke={profile ? "#315d77" : "#427494"}
            strokeWidth={profile ? 1.2 : 1.5}
            opacity={profile ? 0.66 : 0.8}
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        ))}
        {map.ports.map(({ code, x, y, radius }) => (
          <Circle
            key={code}
            cx={x}
            cy={y}
            r={radius}
            fill={code === destination ? "#b27655" : "#faf8f1"}
            stroke={code === destination ? "#faf8f1" : "#427494"}
            strokeWidth={1.2}
          />
        ))}
        {map.ports.map(({ code, label }) => label && (
          <G key={code}>
            <Rect
              x={label.x - 3}
              y={label.y - 1}
              width={label.width + 6}
              height={label.height + 1}
              rx={2}
              fill={profile ? "#f2f4e9" : backgroundColor}
            />
            <Text
              x={label.x}
              y={label.y + 12}
              fontFamily={fonts.mono}
              fontSize={12}
              letterSpacing={0.4}
              fill={code === destination ? "#965e42" : "#315b70"}
            >
              {code}
            </Text>
          </G>
        ))}
        {!profile && (
          <Rect
            x={2.5}
            y={2.5}
            width={395}
            height={225}
            stroke="#f8f3e4"
            strokeOpacity={0.2}
            strokeWidth={5}
          />
        )}
      </Svg>
    </View>
  );
}
const s = StyleSheet.create({
  frame: {
    width: "100%",
    overflow: "hidden",
    borderWidth: 1,
    borderColor: "#c2cfca",
    borderRadius: 2,
  },
  paperShadow: {
    shadowColor: "#e0e5db",
    shadowOffset: { width: 0, height: 2 },
    shadowRadius: 0,
    shadowOpacity: 1,
  },
});
