import React from "react";
import { StyleSheet, Text, useWindowDimensions, View } from "react-native";
import Svg, { Circle, Defs, Line, Pattern, Rect } from "react-native-svg";
import type { TripSegmentSummary } from "../../../data/trotterMock";
import { colors, fonts } from "../../../theme/trotterTheme";
import { AirlineLogo, airlineName } from "../AirlineLogo";
import { WWIcon } from "../WorldWindowUI";
import { arrivalDayChange, calendarDate, flightDate, flightTime } from "./tripPresentation";
import { walletColors } from "./WalletCover";
import { getMobileVisualWidth } from "../../../utils/mobileLayout";

export function BoardingPass({
  segment,
  selected = false,
  availableWidth,
}: {
  segment: TripSegmentSummary;
  selected?: boolean;
  availableWidth?: number;
}) {
  const { width: windowWidth, fontScale } = useWindowDimensions();
  const width = availableWidth ?? (getMobileVisualWidth(windowWidth) || 410);
  const grain = React.useId().replace(/:/g, "");
  const flight = segment.flightNumber
    ? segment.flightNumber
        .toUpperCase()
        .startsWith(segment.airline?.toUpperCase() || "\0")
      ? segment.flightNumber.replace(/\s+/g, "")
      : `${segment.airline || ""}${segment.flightNumber}`.replace(/\s+/g, "")
    : "—";
  const compact = width <= 350 || fontScale >= 1.35;
  const stackEndpoints = width <= 360 && fontScale >= 1.35;
  const narrow = width <= 360 && !compact;
  const date = calendarDate(segment.depTime);
  const day = date?.slice(8, 10),
    month = date
      ? new Date(`${date}T12:00:00Z`).toLocaleDateString("en-GB", {
          month: "short",
          timeZone: "UTC",
        })
      : undefined;
  const dayChange = arrivalDayChange(segment.depTime, segment.arrTime);
  return (
    <View style={s.ticketWrap}>
      <View pointerEvents="none" style={s.paperEdge} />
      <View style={[s.ticket, selected && s.selected, compact && s.compact]}>
        <View style={[s.main, (narrow || compact) && s.narrowMain]}>
          <Svg
            pointerEvents="none"
            style={StyleSheet.absoluteFill}
            width="100%"
            height="100%"
          >
            <Defs>
              <Pattern
                id={grain}
                width={7}
                height={7}
                patternUnits="userSpaceOnUse"
              >
                <Circle
                  cx={1}
                  cy={1.3}
                  r={0.45}
                  fill="#918571"
                  opacity={0.065}
                />
                <Circle
                  cx={4.5}
                  cy={4.7}
                  r={0.3}
                  fill="#918571"
                  opacity={0.045}
                />
              </Pattern>
            </Defs>
            <Rect width="100%" height="100%" fill={`url(#${grain})`} />
          </Svg>
          <View style={s.airline}>
            <AirlineLogo code={segment.airline || ""} size={26} />
            <Text style={s.airlineName}>
              {segment.airline
                ? airlineName(segment.airline)
                : "Airline unavailable"}
            </Text>
          </View>
          <View style={[s.airports, stackEndpoints && s.stackedEndpoints]}>
            <View style={s.endpoint}>
              <Text
                style={[
                  s.code,
                  narrow && s.narrowCode,
                  compact && s.compactCode,
                ]}
              >
                {segment.depAirport || "—"}
              </Text>
              <Text style={[s.city, stackEndpoints && s.largeCity]}>
                {segment.depPoint?.city || "Departure"}
              </Text>
            </View>
            <View style={s.direction}>
              <View style={{ transform: [{ rotate: "45deg" }] }}>
                <WWIcon name="plane" size={15} color={walletColors.copper} />
              </View>
            </View>
            <View style={[s.endpoint, s.arrival]}>
              <Text
                style={[
                  s.code,
                  narrow && s.narrowCode,
                  compact && s.compactCode,
                ]}
              >
                {segment.arrAirport || "—"}
              </Text>
              <Text style={[s.city, s.right, stackEndpoints && s.largeCity]}>
                {segment.arrPoint?.city || "Arrival"}
              </Text>
            </View>
          </View>
          <View style={[s.times, stackEndpoints && s.stackedEndpoints]}>
            <View style={s.endpoint}>
              <Text style={s.scheduleLabel}>Departure</Text>
              <Text
                style={[
                  s.time,
                  narrow && s.narrowTime,
                  compact && s.compactTime,
                ]}
              >
                {flightTime(segment.depTime)}
              </Text>
              <Text style={s.date}>{flightDate(segment.depTime)}</Text>
            </View>
            <View style={[s.endpoint, s.arrival]}>
              <Text style={s.scheduleLabel}>Arrival</Text>
              <Text
                style={[
                  s.time,
                  narrow && s.narrowTime,
                  compact && s.compactTime,
                ]}
              >
                {flightTime(segment.arrTime)}
              </Text>
              <Text style={[s.date, s.right, dayChange && s.changedDate]}>
                {flightDate(segment.arrTime)}
              </Text>
              {dayChange ? <Text style={s.dayChange}>{dayChange}</Text> : null}
            </View>
          </View>
          {(segment.bookingReference || segment.distanceMiles != null) && (
            <View style={s.metadata}>
              {segment.bookingReference && (
                <Text selectable style={s.metaText}>
                  Booking {segment.bookingReference}
                </Text>
              )}
              {segment.distanceMiles != null && (
                <Text style={s.metaText}>
                  {Math.round(segment.distanceMiles).toLocaleString()} mi
                </Text>
              )}
            </View>
          )}
        </View>
        <View style={[s.stub, narrow && s.narrowStub, compact && s.stubBottom, stackEndpoints && s.stackedStub]}>
          <Svg
            pointerEvents="none"
            style={StyleSheet.absoluteFill}
            width="100%"
            height="100%"
          >
            {compact ? (
              <Line
                x1={0}
                y1={0.5}
                x2="100%"
                y2={0.5}
                stroke="#a7bab5"
                strokeWidth={1}
                strokeDasharray="4 3"
              />
            ) : (
              <Line
                x1={0.5}
                y1={0}
                x2={0.5}
                y2="100%"
                stroke="#a7bab5"
                strokeWidth={1}
                strokeDasharray="4 3"
              />
            )}
          </Svg>
          {!compact && (
            <View pointerEvents="none" style={[s.notch, s.notchTop]} />
          )}
          {!compact && (
            <View pointerEvents="none" style={[s.notch, s.notchBottom]} />
          )}
          <View>
            <Text style={[s.label, compact && s.compactLabel]}>FLIGHT</Text>
            <Text style={[s.flight, compact && s.left]}>{flight}</Text>
          </View>
          <View>
            <Text style={[s.label, compact && s.compactLabel]}>DATE</Text>
            {date ? (
              <View style={compact && s.inlineDate}>
                <Text style={[s.stubDay, compact && s.compactDay]}>{day}</Text>
                <Text style={s.stubMonth}>{month}</Text>
                <Text style={s.stubYear}>{date.slice(0, 4)}</Text>
              </View>
            ) : (
              <Text style={s.stubDate}>—</Text>
            )}
          </View>
        </View>
      </View>
    </View>
  );
}
const s = StyleSheet.create({
  stackedEndpoints: { flexDirection: "column", alignItems: "stretch", gap: 14 },
  stackedStub: { flexDirection: "column", alignItems: "flex-start", gap: 16 },
  largeCity: { fontSize: 11, lineHeight: 17 },
  ticketWrap: { position: "relative" },
  paperEdge: {
    position: "absolute",
    top: 3,
    bottom: -2,
    left: 0,
    right: 0,
    backgroundColor: "#e0e5db",
    borderRadius: 3,
  },
  ticket: {
    backgroundColor: colors.paperSheet,
    flexDirection: "row",
    borderWidth: 1,
    borderColor: colors.paperBorder,
    borderRadius: 3,
    shadowColor: colors.ink,
    shadowOpacity: 0.045,
    shadowOffset: { width: 0, height: 2 },
    shadowRadius: 2,
  },
  selected: { borderColor: walletColors.copper },
  compact: { flexDirection: "column" },
  main: {
    flex: 1,
    paddingTop: 15,
    paddingHorizontal: 13,
    paddingBottom: 11,
    minWidth: 0,
  },
  airline: {
    flexDirection: "row",
    alignItems: "center",
    gap: 9,
    paddingBottom: 12,
    borderBottomWidth: 1,
    borderBottomColor: "#d7ded5",
  },
  airlineName: {
    fontFamily: fonts.sans,
    fontSize: 13,
    color: walletColors.ink,
    flex: 1,
  },
  airports: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: 6,
    paddingTop: 20,
    paddingBottom: 16,
  },
  endpoint: { flex: 1, minWidth: 0 },
  arrival: { alignItems: "flex-end" },
  right: { textAlign: "right" },
  left: { textAlign: "left" },
  code: {
    fontFamily: fonts.mono,
    fontSize: 32,
    lineHeight: 32,
    color: walletColors.ink,
    letterSpacing: -1.3,
    includeFontPadding: false,
  },
  city: {
    fontFamily: fonts.sansRegular,
    fontSize: 12,
    lineHeight: 17,
    marginTop: 6,
    color: colors.mutedInk,
  },
  times: {
    flexDirection: "row",
    paddingTop: 13,
    gap: 13,
    borderTopWidth: 1,
    borderTopColor: "#d7ded5",
  },
  scheduleLabel: {
    fontFamily: fonts.sansRegular,
    fontSize: 12,
    color: colors.mutedInk,
    marginBottom: 6,
  },
  time: {
    fontFamily: fonts.mono,
    fontSize: 21,
    lineHeight: 27,
    color: walletColors.ink,
    includeFontPadding: false,
  },
  date: {
    fontFamily: fonts.sansRegular,
    fontSize: 12,
    lineHeight: 17,
    color: colors.mutedInk,
    marginTop: 7,
  },
  changedDate: { color: walletColors.ink },
  dayChange: { color: walletColors.copper, fontFamily: fonts.sansSemi, fontSize: 11, lineHeight: 16, marginTop: 4, textAlign: "right" },
  metadata: {
    flexDirection: "row",
    flexWrap: "wrap",
    justifyContent: "space-between",
    gap: 5,
    marginTop: 14,
  },
  metaText: {
    fontFamily: "IBMPlexMono-Regular",
    fontSize: 12,
    lineHeight: 18,
    color: colors.mutedInk,
  },
  stub: {
    width: 70,
    paddingTop: 19,
    paddingBottom: 16,
    paddingHorizontal: 6,
    gap: 20,
    justifyContent: "space-between",
    backgroundColor: "#e9eee7",
    borderTopRightRadius: 3,
    borderBottomRightRadius: 3,
  },
  stubBottom: {
    width: "100%",
    borderLeftWidth: 0,
    flexDirection: "row",
    paddingHorizontal: 15,
    paddingVertical: 13,
  },
  label: {
    fontFamily: fonts.sansRegular,
    fontSize: 11,
    letterSpacing: 0.6,
    color: colors.mutedInk,
    marginBottom: 9,
    textAlign: "center",
  },
  flight: {
    fontFamily: fonts.mono,
    fontSize: 12,
    lineHeight: 17,
    color: walletColors.ink,
    textAlign: "center",
  },
  compactLabel: { textAlign: "left", marginBottom: 5 },
  inlineDate: { flexDirection: "row", gap: 5, alignItems: "baseline" },
  stubDay: {
    fontFamily: fonts.display,
    fontSize: 29,
    lineHeight: 30,
    color: walletColors.ink,
    textAlign: "center",
    includeFontPadding: false,
  },
  stubMonth: {
    fontFamily: fonts.sans,
    fontSize: 12,
    lineHeight: 17,
    textTransform: "uppercase",
    color: walletColors.ink,
    textAlign: "center",
    marginTop: 4,
  },
  stubYear: {
    fontFamily: "IBMPlexMono-Regular",
    fontSize: 11,
    color: walletColors.muted,
    textAlign: "center",
    marginTop: 4,
  },
  stubDate: {
    fontFamily: fonts.mono,
    fontSize: 10,
    lineHeight: 15,
    color: colors.ink,
  },
  notch: {
    position: "absolute",
    width: 10,
    height: 10,
    borderRadius: 5,
    backgroundColor: walletColors.paper,
    borderWidth: 1,
    borderColor: colors.paperBorder,
  },
  notchTop: { left: -5, top: -5 },
  notchBottom: { left: -5, bottom: -5 },
  direction: {
    width: 18,
    height: 32,
    alignItems: "center",
    justifyContent: "center",
  },
  narrowMain: { paddingHorizontal: 10 },
  narrowStub: { width: 60 },
  narrowCode: { fontSize: 29 },
  narrowTime: { fontSize: 17, lineHeight: 22.1 },
  compactCode: { fontSize: 34, lineHeight: 34 },
  compactTime: { fontSize: 20, lineHeight: 26 },
  compactDay: { fontSize: 20, lineHeight: 20 },
});
