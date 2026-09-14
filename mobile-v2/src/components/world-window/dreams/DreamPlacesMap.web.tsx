import React from "react";
import { Linking, Pressable, StyleSheet, Text, View } from "react-native";
import { colors, fonts } from "../../../theme/trotterTheme";
import { WWIcon } from "../WorldWindowUI";
import { googleMapUrl, type DreamPlacesMapProps } from "./dreamMapModel";

export function DreamPlacesMap({ points, overview, height = 240, placing }: DreamPlacesMapProps) {
  const [error, setError] = React.useState(false);
  const url = googleMapUrl(points, overview);
  return <View style={[s.frame, { minHeight: Math.min(height, 160) }]}>
    <WWIcon name="pin" size={24} />
    <Text style={s.copy}>{placing ? "Use the Trotter app to place a pin, or paste a Google Maps link." : "Explore these places in Google Maps."}</Text>
    {url && <Pressable accessibilityRole="link" style={s.button} onPress={() => { setError(false); void Linking.openURL(url).catch(() => setError(true)); }}>
      <Text style={s.action}>Open Google Maps ↗</Text>
    </Pressable>}
    {error && <Text accessibilityRole="alert" style={s.copy}>The map could not be opened. Your saved places are unchanged.</Text>}
  </View>;
}
const s = StyleSheet.create({
  frame: { backgroundColor: colors.paperDeep, borderColor: colors.paperBorder, borderWidth: 1, padding: 16, alignItems: "center", justifyContent: "center", gap: 8 },
  copy: { color: colors.mutedInk, fontFamily: fonts.sansRegular, fontSize: 13, textAlign: "center" },
  button: { minHeight: 44, paddingHorizontal: 12, justifyContent: "center" },
  action: { color: colors.ink, fontFamily: fonts.sansSemi, fontSize: 13 },
});
