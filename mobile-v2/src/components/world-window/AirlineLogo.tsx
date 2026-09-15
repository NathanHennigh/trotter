import React from "react";
import {
  Image,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { SvgXml } from 'react-native-svg';
import { colors, fonts } from "../../theme/trotterTheme";
import { bundledAirlineLogos } from './airlineLogoAssets';
import { cachedAirlineSymbol, loadAirlineSymbol, normalizeAirlineCode } from './airlineLogoRemote';

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
  const key = normalizeAirlineCode(code), source = bundledAirlineLogos[key];
  const [failedKey, setFailedKey] = React.useState<string>();
  const [remote, setRemote] = React.useState<{ key: string; xml: string | null }>();
  const localAvailable = source && failedKey !== key;
  React.useEffect(() => {
    if (localAvailable) return;
    let current = true;
    void loadAirlineSymbol(key).then(xml => { if (current) setRemote({ key, xml }); });
    return () => { current = false; };
  }, [key, localAvailable]);
  const xml = remote?.key === key ? remote.xml : cachedAirlineSymbol(key);
  const fallback = (
    <View accessibilityLabel={airlineName(key) || "Airline"} style={[styles.fallback, { width: size, height: size }]}>
      <Text style={[styles.code, { fontSize: size * 0.35 }]}>{key.slice(0, 2) || "✈"}</Text>
    </View>
  );
  return localAvailable ? (
    <Image
      key={key}
      source={source}
      accessibilityLabel={airlineName(key)}
      resizeMode="contain"
      onError={() => setFailedKey(key)}
      style={{ width: size, height: size, borderRadius: 3 }}
    />
  ) : xml ? (
    <View accessible accessibilityLabel={airlineName(key) || 'Airline'} style={{ width: size, height: size }}>
      <SvgXml xml={xml} width={size} height={size} preserveAspectRatio="xMidYMid meet" onError={ignoreInvalidSymbol} fallback={fallback} />
    </View>
  ) : fallback;
}
const ignoreInvalidSymbol = () => {};
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
