import React from "react";
import {
  Image,
  StyleSheet,
  Text,
  View,
  type ImageSourcePropType,
} from "react-native";
import { colors, fonts } from "../../theme/trotterTheme";

const logos: Record<string, ImageSourcePropType> = {
  AA: require("../../../assets/world-window/airlines/AA.png"),
  AM: require("../../../assets/world-window/airlines/AM.png"),
  AT: require("../../../assets/world-window/airlines/AT.png"),
  B6: require("../../../assets/world-window/airlines/B6.png"),
  BR: require("../../../assets/world-window/airlines/BR.png"),
  DL: require("../../../assets/world-window/airlines/DL.png"),
  EK: require("../../../assets/world-window/airlines/EK.png"),
  ET: require("../../../assets/world-window/airlines/ET.png"),
  F9: require("../../../assets/world-window/airlines/F9.png"),
  G4: require("../../../assets/world-window/airlines/G4.png"),
  IB: require("../../../assets/world-window/airlines/IB.png"),
  NH: require("../../../assets/world-window/airlines/NH.png"),
  NK: require("../../../assets/world-window/airlines/NK.png"),
  SY: require("../../../assets/world-window/airlines/SY.png"),
  UA: require("../../../assets/world-window/airlines/UA.png"),
  WN: require("../../../assets/world-window/airlines/WN.png"),
  Z2: require("../../../assets/world-window/airlines/Z2.png"),
};
const names: Record<string, string> = {
  AA: "American Airlines",
  AM: "Aeroméxico",
  AT: "Royal Air Maroc",
  B6: "JetBlue",
  BR: "EVA Air",
  DL: "Delta Air Lines",
  EK: "Emirates",
  ET: "Ethiopian Airlines",
  F9: "Frontier Airlines",
  G4: "Allegiant Air",
  IB: "Iberia",
  NH: "ANA",
  NK: "Spirit Airlines",
  SY: "Sun Country Airlines",
  UA: "United Airlines",
  WN: "Southwest Airlines",
  Z2: "Philippines AirAsia",
  KL: "KLM",
  QR: "Qatar Airways",
  SQ: "Singapore Airlines",
  BA: "British Airways",
  LH: "Lufthansa",
  AF: "Air France",
  TK: "Turkish Airlines",
  AS: "Alaska Airlines",
};
export function airlineName(code: string) {
  return names[code.trim().toUpperCase()] ?? code;
}
export function AirlineLogo({
  code,
  size = 30,
}: {
  code: string;
  size?: number;
}) {
  const key = code.trim().toUpperCase(),
    source = logos[key];
  const [failed, setFailed] = React.useState(false);
  React.useEffect(() => setFailed(false), [key]);
  return source && !failed ? (
    <Image
      source={source}
      accessibilityLabel={airlineName(key)}
      resizeMode="contain"
      onError={() => setFailed(true)}
      style={{ width: size, height: size, borderRadius: 3 }}
    />
  ) : (
    <View
      accessibilityLabel={airlineName(key) || "Airline"}
      style={[styles.fallback, { width: size, height: size }]}
    >
      <Text style={[styles.code, { fontSize: size * 0.35 }]}>
        {key.slice(0, 2) || "✈"}
      </Text>
    </View>
  );
}
const styles = StyleSheet.create({
  fallback: {
    borderWidth: 1,
    borderColor: colors.paperBorder,
    backgroundColor: colors.paper,
    borderRadius: 3,
    alignItems: "center",
    justifyContent: "center",
  },
  code: { color: colors.ink, fontFamily: fonts.mono },
});
