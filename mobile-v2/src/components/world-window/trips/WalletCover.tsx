import React from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";
import Svg, { Defs, Line, LinearGradient, Rect, Stop } from "react-native-svg";
import type { TripSummary } from "../../../data/trotterMock";
import { fonts } from "../../../theme/trotterTheme";
import { WWEmblem, WWIcon } from "../WorldWindowUI";
import { tripDates, walletSummary } from "./tripPresentation";

export const walletColors = {
  blue: "#427494",
  ink: "#315b70",
  muted: "#526975",
  paper: "#f7f5ed",
  rule: "#c7d1cc",
  copper: "#b27655",
};

export function WalletHeading({
  trip,
  compact = false,
}: {
  trip: TripSummary;
  compact?: boolean;
}) {
  const gradient = React.useId();
  return (
    <View style={[s.heading, compact && s.headingCompact]}>
      <Svg
        style={StyleSheet.absoluteFill}
        width="100%"
        height="100%"
        pointerEvents="none"
      >
        <Defs>
          <LinearGradient id={gradient} x1="0" y1="0" x2="1" y2="0.4">
            <Stop offset="0" stopColor="#4e7f9b" />
            <Stop offset="0.74" stopColor="#427494" />
          </LinearGradient>
        </Defs>
        <Rect width="100%" height="100%" fill={`url(#${gradient})`} />
      </Svg>
      <View style={[s.top, compact && s.topCompact]}>
        <Text
          style={[s.country, compact && s.countryCompact]}
          numberOfLines={1}
        >
          {trip.country}
        </Text>
        <View style={compact && s.compactEmblem}>
          <WWEmblem size={compact ? 17 : 28} color="#e7e6d5" />
        </View>
      </View>
      <Text style={[s.title, compact && s.titleCompact]}>
        {trip.city || trip.title}
      </Text>
      <Text style={[s.date, compact && s.dateCompact]}>{tripDates(trip)}</Text>
    </View>
  );
}

export function WalletCover({
  trip,
  onPress,
}: {
  trip: TripSummary;
  onPress: (flightId?: string) => void;
}) {
  const { shown, hidden } = React.useMemo(() => walletSummary(trip), [trip]);
  return (
    <View style={s.stack}>
      <View pointerEvents="none" style={s.paperEdgeBack} />
      <View pointerEvents="none" style={s.paperEdgeFront} />
      <View style={s.wallet}>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={`Open ${trip.title}, ${tripDates(trip)}, ${trip.flightCount} flights`}
          onPress={() => onPress()}
          style={({ pressed }) => pressed && s.pressed}
        >
          <WalletHeading trip={trip} compact />
        </Pressable>
        <View style={s.insert}>
          {shown.map((group) => (
            <Pressable
              accessibilityRole="button"
              accessibilityLabel={`${group.first.depAirport} to ${group.last.arrAirport}, ${group.dates}`}
              onPress={() => onPress(group.first.id)}
              style={s.coupon}
              key={group.id}
            >
              <View style={s.routeCopy}>
                <View style={s.route}>
                  <Text style={s.airport}>{group.first.depAirport}</Text>
                  <WWIcon name="arrow" size={16} color={walletColors.copper} />
                  <Text style={s.airport}>{group.last.arrAirport}</Text>
                </View>
                {group.via.length > 0 && (
                  <Text style={s.via}>Via {group.via.join(" · ")}</Text>
                )}
              </View>
              <Text style={s.when}>{group.dates}</Text>
              <Svg
                pointerEvents="none"
                width="100%"
                height={1}
                style={s.couponRule}
              >
                <Line
                  x1={0}
                  y1={0.5}
                  x2="100%"
                  y2={0.5}
                  stroke="#bccbc7"
                  strokeWidth={1}
                  strokeDasharray="4 3"
                />
              </Svg>
            </Pressable>
          ))}
          {!shown.length && (
            <View style={s.coupon}>
              <Text style={s.fallback}>{trip.routeLabel}</Text>
            </View>
          )}
          <Pressable
            accessibilityRole="button"
            onPress={() => onPress()}
            style={s.open}
          >
            <Text style={s.openText}>
              {hidden > 0
                ? `${hidden} more ${hidden === 1 ? "flight" : "flights"}`
                : "Full itinerary"}
            </Text>
            <View style={s.openEnd}>
              <Text style={s.count}>
                {trip.flightCount}{" "}
                {trip.flightCount === 1 ? "flight" : "flights"}
              </Text>
              <WWIcon name="arrow" size={15} color={walletColors.ink} />
            </View>
          </Pressable>
        </View>
        <View pointerEvents="none" style={s.spine} />
        <View pointerEvents="none" style={s.topLight} />
      </View>
    </View>
  );
}
const s = StyleSheet.create({
  stack: { marginHorizontal: 20, marginBottom: 18 },
  paperEdgeBack: {
    position: "absolute",
    left: 0,
    right: 0,
    top: 5,
    bottom: -4,
    borderRadius: 9,
    backgroundColor: "#e2e7df",
  },
  paperEdgeFront: {
    position: "absolute",
    left: 0,
    right: 0,
    top: 3,
    bottom: -2,
    borderRadius: 9,
    backgroundColor: "#b4c5c8",
  },
  wallet: {
    paddingHorizontal: 6,
    paddingBottom: 7,
    backgroundColor: walletColors.blue,
    borderColor: "#386680",
    borderWidth: 1,
    borderTopLeftRadius: 5,
    borderTopRightRadius: 5,
    borderBottomLeftRadius: 9,
    borderBottomRightRadius: 9,
    shadowColor: "#213e4c",
    shadowOpacity: 0.1,
    shadowOffset: { width: 0, height: 4 },
    shadowRadius: 4,
    elevation: 2,
  },
  pressed: { transform: [{ scale: 0.991 }], opacity: 0.97 },
  heading: {
    paddingHorizontal: 15,
    paddingTop: 19,
    paddingBottom: 18,
    overflow: "hidden",
    borderTopLeftRadius: 4,
    borderTopRightRadius: 4,
  },
  headingCompact: { paddingHorizontal: 12, paddingTop: 7, paddingBottom: 8 },
  top: {
    minHeight: 30,
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    gap: 12,
  },
  country: {
    fontFamily: fonts.sansRegular,
    fontSize: 11,
    lineHeight: 16,
    color: "#e7e6d5",
    letterSpacing: 1.1,
    textTransform: "uppercase",
    flex: 1,
    includeFontPadding: false,
  },
  title: {
    fontFamily: fonts.display,
    fontSize: 33,
    lineHeight: 36,
    color: "#faf8f2",
    letterSpacing: -0.5,
    marginTop: 8,
    marginBottom: 10,
    includeFontPadding: false,
  },
  titleCompact: { fontSize: 27, lineHeight: 29, marginTop: 1, marginBottom: 3 },
  date: {
    fontFamily: fonts.sansRegular,
    fontSize: 12,
    lineHeight: 19.2,
    color: "#e1eaeb",
    includeFontPadding: false,
  },
  insert: {
    backgroundColor: walletColors.paper,
    borderTopWidth: 3,
    borderTopColor: "#cad6d4",
    borderRadius: 3,
    paddingHorizontal: 13,
    borderBottomLeftRadius: 5,
    borderBottomRightRadius: 5,
  },
  coupon: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    minHeight: 46,
    paddingVertical: 6,
    borderBottomWidth: 1,
    borderBottomColor: "transparent",
  },
  couponRule: { position: "absolute", left: 0, bottom: 0 },
  routeCopy: { flex: 1, minWidth: 0, gap: 3 },
  route: { flexDirection: "row", gap: 8, alignItems: "center" },
  airport: {
    fontFamily: fonts.mono,
    fontSize: 19,
    lineHeight: 23,
    color: walletColors.ink,
    letterSpacing: -0.7,
    includeFontPadding: false,
  },
  via: {
    fontFamily: fonts.sansRegular,
    fontSize: 12,
    lineHeight: 16,
    color: walletColors.muted,
  },
  when: {
    fontFamily: fonts.sansRegular,
    fontSize: 12,
    lineHeight: 17,
    color: walletColors.muted,
    maxWidth: 96,
    textAlign: "right",
  },
  fallback: { fontFamily: fonts.mono, fontSize: 18, color: walletColors.ink },
  open: {
    minHeight: 44,
    flexDirection: "row",
    gap: 10,
    justifyContent: "space-between",
    alignItems: "center",
  },
  openText: {
    fontFamily: fonts.sansRegular,
    fontSize: 13,
    color: walletColors.muted,
    flex: 1,
  },
  openEnd: { flexDirection: "row", alignItems: "center", gap: 8 },
  count: {
    fontFamily: fonts.sansRegular,
    fontSize: 12,
    color: walletColors.muted,
  },
  spine: {
    position: "absolute",
    left: 3,
    top: 7,
    bottom: 9,
    borderLeftColor: "#9ab6c080",
    borderLeftWidth: 1,
  },
  topCompact: { minHeight: 17 },
  compactEmblem: {
    width: 23,
    height: 23,
    alignItems: "center",
    justifyContent: "center",
  },
  countryCompact: { fontSize: 11, lineHeight: 15, letterSpacing: 0.66 },
  dateCompact: { fontSize: 12, lineHeight: 17 },
  topLight: {
    position: "absolute",
    top: 0,
    left: 5,
    right: 5,
    height: 1,
    backgroundColor: "#8dabb8",
    opacity: 0.8,
  },
});
