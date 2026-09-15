import React from "react";
import { StyleSheet, Text, useWindowDimensions, View } from "react-native";
import Svg, { Circle, Defs, Line, LinearGradient, Path, Pattern, Stop } from "react-native-svg";
import type { TripSegmentSummary } from "../../../data/trotterMock";
import { colors, fonts } from "../../../theme/trotterTheme";
import { AirlineLogo, airlineName } from "../AirlineLogo";
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
  const [paperSize, setPaperSize] = React.useState({ width: 0, height: 0 });
  const [stubTop, setStubTop] = React.useState(0);
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
  const seam = compact ? stubTop : paperSize.width - (narrow ? 60 : 70) - 1;
  const outline = !compact || stubTop > 0 ? ticketOutline(paperSize.width, paperSize.height, seam, compact) : "";
  const seamOffset = seam / (compact ? paperSize.height : paperSize.width);
  return (
    <View style={s.ticketWrap}>
      <View testID="boarding-pass-paper" style={[s.ticket, compact && s.compact]}
        onLayout={event => {
          const { width, height } = event.nativeEvent.layout;
          setPaperSize(previous => previous.width === width && previous.height === height ? previous : { width, height });
        }}>
        {/* SVG gets an unpadded, explicit viewport. Android rounds percentage/fractional
            view sizes, which otherwise cuts off the far border. Mount only a real path. */}
        {Boolean(outline) && <View pointerEvents="none" style={StyleSheet.absoluteFill}>
          <Svg testID="boarding-pass-art" accessible={false}
            width={Math.ceil(paperSize.width)} height={Math.ceil(paperSize.height)}
            viewBox={`0 0 ${Math.ceil(paperSize.width)} ${Math.ceil(paperSize.height)}`}>
            <Defs>
              <LinearGradient id={`${grain}paper`} gradientUnits="userSpaceOnUse"
                x1={0} y1={0} x2={compact ? 0 : paperSize.width} y2={compact ? paperSize.height : 0}>
                <Stop offset={0} stopColor={colors.paperSheet} />
                <Stop offset={seamOffset} stopColor={colors.paperSheet} />
                <Stop offset={seamOffset} stopColor="#e9eee7" />
                <Stop offset={1} stopColor="#e9eee7" />
              </LinearGradient>
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
            <Path d={outline} fill={`url(#${grain}paper)`} />
            <Path d={outline} fill={`url(#${grain})`} />
            <Line x1={compact ? 5.5 : seam} y1={compact ? seam : 5.5}
              x2={compact ? paperSize.width - 5.5 : seam} y2={compact ? seam : paperSize.height - 5.5}
              stroke="#a7bab5" strokeWidth={1} strokeDasharray="4 3" />
            <Path d={outline} fill="none" stroke={selected ? walletColors.copper : colors.paperBorder} strokeWidth={1} />
          </Svg>
        </View>}
        <View style={[s.main, (narrow || compact) && s.narrowMain]}>
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
              <Svg width={18} height={18} viewBox="0 0 24 24" pointerEvents="none" accessible={false}>
                <Path
                  d="M22 10.8c1.6.3 1.6 2.1 0 2.4l-7.2.5-6.2 7.1H6.2l3.5-7-5.4.3-2 2.5H.8L1.6 12 .8 7.4h1.5l2 2.5 5.4.3-3.5-7h2.4l6.2 7.1z"
                  fill={walletColors.copper}
                />
              </Svg>
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
        <View testID="boarding-pass-stub" style={[s.stub, narrow && s.narrowStub, compact && s.stubBottom, stackEndpoints && s.stackedStub]}
          onLayout={event => setStubTop(event.nativeEvent.layout.y)}>
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

/** A single paper silhouette, including the missing semicircles at the tear line. */
export function ticketOutline(width: number, height: number, seam: number, horizontal: boolean) {
  if (!(width > 8 && height > 8)) return "";
  const l = .5, t = .5, r = width - .5, b = height - .5, c = 3, n = 5;
  const cut = seam > 8 && seam < (horizontal ? height : width) - 8;
  const top = !horizontal && cut ? `H${seam - n} A${n} ${n} 0 0 0 ${seam + n} ${t}` : "";
  const right = horizontal && cut ? `V${seam - n} A${n} ${n} 0 0 0 ${r} ${seam + n}` : "";
  const bottom = !horizontal && cut ? `H${seam + n} A${n} ${n} 0 0 0 ${seam - n} ${b}` : "";
  const left = horizontal && cut ? `V${seam + n} A${n} ${n} 0 0 0 ${l} ${seam - n}` : "";
  return `M${l + c} ${t} ${top} H${r - c} Q${r} ${t} ${r} ${t + c} ${right} V${b - c} Q${r} ${b} ${r - c} ${b} ${bottom} H${l + c} Q${l} ${b} ${l} ${b - c} ${left} V${t + c} Q${l} ${t} ${l + c} ${t} Z`;
}
const s = StyleSheet.create({
  stackedEndpoints: { flexDirection: "column", alignItems: "stretch", gap: 14 },
  stackedStub: { flexDirection: "column", alignItems: "flex-start", gap: 16 },
  largeCity: { fontSize: 11, lineHeight: 17 },
  ticketWrap: { position: "relative" },
  ticket: {
    flexDirection: "row",
    padding: 1,
    borderRadius: 3,
  },
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
