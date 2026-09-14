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
import type { CountryArrival } from "../utils/countryArrivals";
import { useTravelTrips } from "../services/travelTrips";
import { colors, layout } from "../theme/trotterTheme";
import { getMobileVisualWidth } from "../utils/mobileLayout";

export function CountryStampCollectionScreen({
  active,
  onChange,
  onBack,
  initialCountry,
  onOpenTrip,
}: {
  active: BottomNavTab;
  onChange: (tab: BottomNavTab) => void;
  onBack?: () => void;
  initialCountry?: string;
  onOpenTrip?: (trip: TripSummary) => void;
}) {
  const insets = useSafeAreaInsets(),
    { width } = useWindowDimensions(),
    visualWidth = getMobileVisualWidth(width);
  const { trips, status, refresh } = useTravelTrips();
  // Preserve the calibrated native stamp system and first-entry identity fixes.
  const arrivals = React.useMemo(() => buildPassportArrivals(trips), [trips]);
  const [selected, setSelected] = React.useState<CountryArrival | null>(null);
  const [query, setQuery] = React.useState("");
  React.useEffect(() => {
    setSelected(
      initialCountry
        ? (arrivals.find(
            (a) =>
              a.country.toLowerCase() === initialCountry.toLowerCase() ||
              a.travelCountryKey?.toLowerCase() ===
                initialCountry.toLowerCase(),
          ) ?? null)
        : null,
    );
  }, [initialCountry]);
  const selectInitial = initialCountry
    ? arrivals.find(
        (a) =>
          a.country.toLowerCase() === initialCountry.toLowerCase() ||
          a.travelCountryKey?.toLowerCase() === initialCountry.toLowerCase(),
      )
    : undefined;
  const [dismissedInitial, setDismissedInitial] = React.useState(false);
  React.useEffect(() => setDismissedInitial(false), [initialCountry]);
  const country = selected ?? (!dismissedInitial ? selectInitial : undefined);
  const back = () => {
    if (country) {
      setSelected(null);
      setDismissedInitial(true);
      if (initialCountry) onBack?.();
    } else (onBack ?? (() => onChange("passport")))();
  };
  return (
    <View style={[styles.screen, { paddingTop: insets.top }]}>
      {country ? (
        <View
          style={{
            flex: 1,
            width: visualWidth,
            paddingBottom: layout.bottomNavHeight + insets.bottom,
          }}
        >
          <CountryArrivalDetail
            arrival={country}
            trips={trips}
            onBack={back}
            onOpenTrip={onOpenTrip}
            width={visualWidth}
            backLabel={initialCountry ? "Globe" : "Countries"}
          />
        </View>
      ) : (
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
          <CollectionHeading title="Countries" count={arrivals.length} query={query} setQuery={setQuery} placeholder="Country or entry airport" onBack={back} />
          <CountryIndex arrivals={arrivals} onSelect={setSelected} query={query} />
        </ScrollView>
      )}
      <BottomNav active={active} onChange={onChange} />
    </View>
  );
}
const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.paperSoft },
});
