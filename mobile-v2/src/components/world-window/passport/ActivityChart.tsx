import React, { useState } from "react";
import { Pressable, StyleSheet, Text, useWindowDimensions, View } from "react-native";
import Svg, { Circle, Line, Path, Text as SvgText } from "react-native-svg";
import { colors, fonts } from "../../../theme/trotterTheme";
import { WWIcon } from "../WorldWindowUI";
import { readableDate, type ActivityYear } from "./passport-model";
import { activityYearLabelIndices } from "./passport-collection-model";

export function ActivityChart({ years, width, onYear, latestDate }: { years: ActivityYear[]; width: number; onYear?: (year: string) => void; latestDate?: string }) {
  const largeText = useWindowDimensions().fontScale >= 1.35;
  const [selected, setSelected] = useState<number | null>(null), [metric, setMetric] = useState<"flights" | "miles">("flights");
  const index = Math.max(0, Math.min(selected ?? years.length - 1, years.length - 1)), current = years[index];
  const innerWidth = width - 30, left = 40, right = innerWidth - 18, top = 7, bottom = 157, height = 191;
  const step = metric === "flights" ? 10 : 10000, limit = Math.max(step, Math.ceil(Math.max(0, ...years.map(y => y[metric])) / step) * step);
  const points = years.map((year, i) => ({ x: years.length === 1 ? (left + right) / 2 : left + i / (years.length - 1) * (right - left), y: bottom - year[metric] / limit * (bottom - top) }));
  const labeledYears = new Set(activityYearLabelIndices(years.length, right - left));
  const path = points.map((p, i) => `${i ? "L" : "M"} ${p.x} ${p.y}`).join(" ");
  const selectAt = (x: number) => setSelected(Math.max(0, Math.min(years.length - 1, Math.round((x - left) / (right - left) * (years.length - 1)))));
  if (!current) return <Text style={styles.empty}>Your flight history will appear here.</Text>;
  const compact = (n: number) => metric === "miles" ? `${Math.round(n / 1000)}k` : String(n);
  return <View style={styles.chart}>
    <View style={styles.switch}>{(["flights", "miles"] as const).map(m => <Pressable key={m} accessibilityRole="button" accessibilityState={{ selected: metric === m }} onPress={() => setMetric(m)} style={[styles.switchButton, metric === m && styles.switchSelected]}><Text style={[styles.switchLabel, metric === m && styles.switchActive]}>{m === "flights" ? "Flights" : "Miles"}</Text></Pressable>)}</View>
    <View style={[styles.summary, largeText && styles.stacked]}><View style={{ gap: 8, flexShrink: 1 }}><Text style={styles.number}>{Math.round(current[metric]).toLocaleString()}</Text><Text style={styles.unit}>{metric} in {current.year}</Text></View><Text style={[styles.period, largeText && styles.periodLarge]}>{latestDate?.startsWith(String(current.year)) ? `Through ${readableDate(latestDate)}` : "Full year"}</Text></View>
    <Pressable accessibilityRole="adjustable" accessibilityLabel={`${metric} by year. ${current.year}: ${current[metric]} ${metric}.`} accessibilityActions={[{ name: "increment", label: "Next year" }, { name: "decrement", label: "Previous year" }]} onAccessibilityAction={event => setSelected(Math.max(0, Math.min(years.length - 1, index + (event.nativeEvent.actionName === "increment" ? 1 : -1))))} onPress={event => selectAt(event.nativeEvent.locationX)} onTouchMove={event => selectAt(event.nativeEvent.locationX)}>
      <Svg width={innerWidth} height={height} accessible={false}>
        {[1, .5, 0].map(value => <React.Fragment key={value}><Line x1={left} x2={right} y1={bottom - value * (bottom - top)} y2={bottom - value * (bottom - top)} stroke={colors.paperBorder} strokeWidth={1} strokeDasharray="2 4"/><SvgText x={30} y={bottom - value * (bottom - top) + 4} textAnchor="end" fontFamily={fonts.sansRegular} fontSize={12} fill={colors.mutedInk}>{compact(value * limit)}</SvgText></React.Fragment>)}
        <Line x1={points[index].x} x2={points[index].x} y1={top} y2={bottom} stroke="#b27655" strokeWidth={1} strokeDasharray="3 4" opacity={.5}/>
        <Path d={path} fill="none" stroke={colors.blue} strokeWidth={2.3} strokeLinejoin="round" strokeLinecap="round"/>
        {points.map((point, i) => <Circle key={years[i].year} cx={point.x} cy={point.y} r={i === index ? 4.5 : 2.4} fill={i === index ? "#b27655" : colors.paperSoft} stroke={i === index ? colors.paperSoft : colors.blue} strokeWidth={i === index ? 2.5 : 1.6}/>)}
        {years.map((year, i) => labeledYears.has(i) && <SvgText key={year.year} x={points[i].x} y={height - 9} fontFamily={fonts.sansRegular} fontSize={12} textAnchor="middle" fill={colors.mutedInk}>{year.year}</SvgText>)}
      </Svg>
    </Pressable>
    <View style={[styles.controls, largeText && styles.stacked]}><View style={styles.yearControls}><Pressable accessibilityRole="button" accessibilityLabel="Previous activity year" disabled={index === 0} onPress={() => setSelected(index - 1)} style={[styles.arrow, index === 0 && styles.disabled]}><WWIcon name="back" size={17}/></Pressable><Text style={styles.year}>{current.year}</Text><Pressable accessibilityRole="button" accessibilityLabel="Next activity year" disabled={index === years.length - 1} onPress={() => setSelected(index + 1)} style={[styles.arrow, index === years.length - 1 && styles.disabled]}><WWIcon name="arrow" size={17}/></Pressable></View>
      {current.flights > 0 && onYear ? <Pressable accessibilityRole="button" onPress={() => onYear(String(current.year))} style={[styles.routes, largeText && styles.routesLarge]}><Text style={styles.routeText}>View routes</Text><WWIcon name="arrow" size={15}/></Pressable> : !current.flights ? <Text style={styles.noRoutes}>No flights recorded</Text> : null}
    </View>
  </View>;
}
const styles = StyleSheet.create({
  chart: { backgroundColor: "#e4eeea", paddingHorizontal: 15, paddingVertical: 18, borderBottomWidth: 2, borderBottomColor: "#9db9b4" },
  switch: { flexDirection: "row", alignSelf: "flex-start", padding: 3, borderWidth: 1, borderColor: colors.paperBorder, borderRadius: 4, marginBottom: 6 },
  switchButton: { minHeight: 48, paddingHorizontal: 16, justifyContent: "center", borderRadius: 2 },
  switchSelected: { backgroundColor: colors.blue },
  switchLabel: { fontFamily: fonts.sansRegular, fontSize: 13, color: colors.ink },
  switchActive: { color: colors.paperSoft },
  summary: { flexDirection: "row", justifyContent: "space-between", alignItems: "flex-end", gap: 12, marginTop: 23, marginBottom: 22 },
  number: { fontFamily: fonts.display, fontSize: 42, lineHeight: 46, letterSpacing: -1, color: colors.ink },
  unit: { fontFamily: fonts.sansRegular, fontSize: 14, color: colors.ink },
  period: { fontFamily: fonts.sansRegular, fontSize: 12, lineHeight: 18, color: colors.mutedInk, textAlign: "right", maxWidth: 100 },
  controls: { flexDirection: "row", alignItems: "center", gap: 1, marginTop: 10, borderTopWidth: 1, borderTopColor: colors.paperBorder },
  yearControls: { flexDirection: "row", alignItems: "center" },
  stacked: { flexDirection: "column", alignItems: "flex-start" },
  periodLarge: { maxWidth: "100%", textAlign: "left" },
  routesLarge: { marginLeft: 0, justifyContent: "flex-start" },
  arrow: { width: 44, minHeight: 48, alignItems: "center", justifyContent: "center" },
  disabled: { opacity: .25 },
  year: { minWidth: 45, textAlign: "center", fontFamily: fonts.sansRegular, fontSize: 15, color: colors.ink },
  routes: { marginLeft: "auto", flexDirection: "row", alignItems: "center", justifyContent: "flex-end", minHeight: 48, gap: 7 },
  routeText: { fontFamily: fonts.sansRegular, fontSize: 13, color: colors.ink },
  noRoutes: { flex: 1, textAlign: "right", fontFamily: fonts.sansRegular, fontSize: 12, color: colors.mutedInk },
  empty: { paddingVertical: 24, fontFamily: fonts.sansRegular, color: colors.mutedInk, fontSize: 14 },
});
