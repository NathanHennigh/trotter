import React from "react";
import { StyleSheet, Text, View } from "react-native";
import { PressFeedback as Pressable } from "../motion";
import Svg, { Circle, G, Path, Rect, Text as SvgText } from "react-native-svg";
import world from "../../../data/worldCountries.json";
import { tripAtlasGeometry } from "../trips/tripAtlasGeometry";
import { airportPresentation } from "./airport-presentation";
import { readableDate, type AirportRecord } from "./passport-model";
import type { TripSummary } from "../../../data/trotterMock";
import { colors, fonts } from "../../../theme/trotterTheme";
import { WWIcon } from "../WorldWindowUI";

export function AirportRouteFan({
  airport,
  onOpenTrip,
}: {
  airport: AirportRecord;
  onOpenTrip?: (trip: TripSummary) => void;
}) {
  const fan = React.useMemo(() => airportPresentation(airport), [airport]);
  const map = React.useMemo(
    () => tripAtlasGeometry(fan.segments, world, airport.code),
    [fan.segments, airport.code],
  );
  const selectedPorts = new Set(
    fan.selected?.trip.segments?.flatMap((s) => [s.depAirport, s.arrAirport]) ??
      [],
  );
  return (
    <View>
      {map.ports.length > 0 && (
        <>
          <View
            style={s.map}
            accessible
            accessibilityRole="image"
            accessibilityLabel={`${fan.routeCount} routes through ${airport.code}${fan.selected ? ", highlighting " + fan.selected.trip.title : ""}`}
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
                fill="#dfe7df"
                stroke="#91aaa9"
                strokeWidth={0.55}
                fillRule="evenodd"
              />
              {map.paths.map((d, i) => (
                <Path
                  key={i}
                  d={d}
                  stroke={
                    fan.selected && fan.highlighted[i] ? "#995f3e" : "#427494"
                  }
                  strokeWidth={fan.selected && fan.highlighted[i] ? 1.8 : 1.3}
                  opacity={fan.selected && !fan.highlighted[i] ? 0.15 : 0.9}
                />
              ))}
              {map.ports.map((p) => (
                <G
                  key={p.code}
                  opacity={
                    fan.selected &&
                    p.code !== airport.code &&
                    !selectedPorts.has(p.code)
                      ? 0.25
                      : 1
                  }
                >
                  <Circle
                    cx={p.x}
                    cy={p.y}
                    r={p.code === airport.code ? 4.2 : 2.7}
                    fill={p.code === airport.code ? "#b27655" : "#faf8f1"}
                    stroke={p.code === airport.code ? "#faf8f1" : "#427494"}
                    strokeWidth={1.2}
                  />
                  {p.label && (
                    <G>
                      <Rect
                        x={p.label.x - 3}
                        y={p.label.y - 1}
                        width={p.label.width + 6}
                        height={p.label.height + 1}
                        rx={2}
                        fill="#f8f6ed"
                      />
                      <SvgText
                        x={p.label.x}
                        y={p.label.y + 12}
                        fontFamily={fonts.mono}
                        fontSize={12}
                        fill={p.code === airport.code ? "#965e42" : "#315b70"}
                      >
                        {p.code}
                      </SvgText>
                    </G>
                  )}
                </G>
              ))}
            </Svg>
          </View>
          <View style={s.caption}>
            <Text style={s.captionText}>
              {fan.routeCount} {fan.routeCount === 1 ? "route" : "routes"} ·{" "}
              {fan.journeys.length}{" "}
              {fan.journeys.length === 1 ? "journey" : "journeys"}
            </Text>
          </View>
        </>
      )}
      <View>
        {fan.journeys.map(({ trip, incident }) => (
          <Pressable
            key={trip.id}
            accessibilityRole={onOpenTrip ? "button" : undefined}
            disabled={!onOpenTrip}
            accessibilityLabel={`Open ${trip.city || trip.title} itinerary`}
            onPress={() => onOpenTrip?.(trip)}
            style={s.journey}
          >
            <View style={s.journeyCopy}>
              <Text style={s.city}>{trip.city || trip.title}</Text>
              <Text style={s.dates}>
                {readableDate(trip.startDate)} – {readableDate(trip.endDate)}
              </Text>
              <Text style={s.count}>
                {incident.length} {incident.length === 1 ? "flight" : "flights"}{" "}
                through {airport.code}
              </Text>
            </View>
            {onOpenTrip && (
              <View style={s.open}>
                <WWIcon name="arrow" size={18} />
              </View>
            )}
          </Pressable>
        ))}
      </View>
    </View>
  );
}
const s = StyleSheet.create({
  map: {
    width: "100%",
    aspectRatio: 400 / 230,
    backgroundColor: "#f8f6ed",
    borderWidth: 1,
    borderColor: "#c2cfca",
    borderRadius: 2,
    overflow: "hidden",
    marginTop: 20,
  },
  caption: {
    flexDirection: "row",
    alignItems: "center",
    minHeight: 44,
    borderBottomWidth: 1,
    borderBottomColor: colors.paperBorder,
    paddingHorizontal: 10,
    marginBottom: 12,
  },
  captionText: {
    flex: 1,
    fontFamily: fonts.sansRegular,
    fontSize: 12,
    color: colors.mutedInk,
  },
  clear: {
    width: 40,
    minHeight: 44,
    alignItems: "center",
    justifyContent: "center",
  },
  journey: {
    flexDirection: "row",
    alignItems: "center",
    borderBottomWidth: 1,
    borderBottomColor: colors.paperBorder,
  },
  selected: { backgroundColor: "#e4eeea" },
  journeyCopy: { flex: 1, paddingVertical: 15, gap: 6 },
  city: {
    fontFamily: fonts.display,
    fontSize: 23,
    lineHeight: 27,
    color: colors.ink,
  },
  dates: {
    fontFamily: fonts.sansRegular,
    fontSize: 13,
    lineHeight: 19,
    color: colors.mutedInk,
  },
  count: {
    fontFamily: fonts.sansRegular,
    fontSize: 12,
    lineHeight: 18,
    color: colors.mutedInk,
  },
  open: {
    width: 44,
    alignSelf: "stretch",
    alignItems: "center",
    justifyContent: "center",
  },
});
