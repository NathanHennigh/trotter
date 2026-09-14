import React from "react";
import {
  RefreshControl,
  ScrollView,
  StyleSheet,
  useWindowDimensions,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { BottomNav } from "../components/trotter/TrotterKit";
import {
  CollectionHeading,
  CountryIndex,
  CountryArrivalDetail,
} from "../components/world-window/passport/PassportCollections";
import { buildPassportArrivals } from "../components/world-window/passport/passport-arrivals";
import type { BottomNavTab, TripSummary } from "../data/trotterMock";
import { useTravelTrips } from "../services/travelTrips";
import { colors, layout } from "../theme/trotterTheme";
import { getMobileVisualWidth } from "../utils/mobileLayout";

export function CountryStampCollectionScreen({
  active,
  onChange,
  onBack,
  initialCountry,
  onOpenTrip,
  backLabel = "Passport",
  visible = true,
  onBackHandlerChange,
}: {
  active: BottomNavTab;
  onChange: (tab: BottomNavTab) => void;
  onBack?: () => void;
  initialCountry?: string;
  onOpenTrip?: (trip: TripSummary) => void;
  backLabel?: string;
  visible?: boolean;
  onBackHandlerChange?: (handler: (() => boolean) | null) => void;
}) {
  const insets = useSafeAreaInsets(),
    { width } = useWindowDimensions(),
    visualWidth = getMobileVisualWidth(width);
  const { trips, status, refresh } = useTravelTrips();
  // Preserve the calibrated native stamp system and first-entry identity fixes.
  const arrivals = React.useMemo(() => buildPassportArrivals(trips), [trips]);
  const [selectedKey, setSelectedKey] = React.useState<string | null>(initialCountry ?? null);
  const [query, setQuery] = React.useState("");
  const detailBack = React.useRef<(() => boolean) | null>(null);
  const registerDetailBack = React.useCallback((handler: (() => boolean) | null) => { detailBack.current = handler; }, []);
  React.useEffect(() => setSelectedKey(initialCountry ?? null), [initialCountry]);
  const country = arrivals.find(arrival => selectedKey && [arrival.country, arrival.travelCountryKey].some(value => value?.toLowerCase() === selectedKey.toLowerCase()));
  const handleBack = React.useCallback(() => {
    if (detailBack.current?.()) return true;
    if (!country || initialCountry) return false;
    setSelectedKey(null);
    return true;
  }, [country, initialCountry]);
  React.useEffect(() => {
    onBackHandlerChange?.(visible ? handleBack : null);
    return () => onBackHandlerChange?.(null);
  }, [visible, handleBack, onBackHandlerChange]);
  const back = () => { if (!handleBack()) (onBack ?? (() => onChange("passport")))(); };
  return (
    <View style={[styles.screen, { paddingTop: insets.top }]}>
      <View style={{ flex: 1 }} pointerEvents={country ? "none" : "auto"} aria-hidden={Boolean(country)} accessibilityElementsHidden={Boolean(country)} importantForAccessibility={country ? "no-hide-descendants" : "auto"}>
        <ScrollView
          showsVerticalScrollIndicator={false}
          keyboardShouldPersistTaps="handled"
          refreshControl={
            <RefreshControl
              refreshing={status === "refreshing" || status === "syncing"}
              onRefresh={refresh}
              tintColor={colors.blue}
            />
          }
          contentContainerStyle={{
            width: visualWidth,
            paddingBottom: layout.bottomNavHeight + insets.bottom + 24,
          }}
        >
          <CollectionHeading title="Countries" count={arrivals.length} query={query} setQuery={setQuery} placeholder="Country or entry airport" onBack={back} backLabel={backLabel} />
          <CountryIndex arrivals={arrivals} onSelect={arrival => setSelectedKey(arrival.travelCountryKey ?? arrival.country)} query={query} />
        </ScrollView>
      </View>
      {country && <View style={[styles.overlay, { top: insets.top, width: visualWidth, paddingBottom: layout.bottomNavHeight + insets.bottom }]}>
        <CountryArrivalDetail key={country.travelCountryKey ?? country.country} arrival={country} trips={trips} onBack={back} onOpenTrip={onOpenTrip} width={visualWidth} backLabel={initialCountry ? backLabel : "Countries"} onBackHandlerChange={registerDetailBack} />
      </View>}
      <BottomNav active={active} onChange={onChange} />
    </View>
  );
}
const styles = StyleSheet.create({
  overlay: { ...StyleSheet.absoluteFillObject, backgroundColor: colors.paperSoft },
  screen: { flex: 1, backgroundColor: colors.paperSoft },
});
