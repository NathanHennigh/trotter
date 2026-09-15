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
  CountryArrivalDetail,
} from "../components/world-window/passport/PassportCollections";
import {
  CountryCollectionIndex as CountryIndex,
  UnvisitedCountryRecord,
  type CountryCatalogRecord,
} from "../components/world-window/passport/CountryCollectionIndex";
import type { BottomNavTab, TripSummary } from "../data/trotterMock";
import { useTravelTrips } from "../services/travelTrips";
import { colors, layout } from "../theme/trotterTheme";
import { getMobileVisualWidth } from "../utils/mobileLayout";
import { normalizeTravelYear } from "../utils/travelScope";
import { passportScope } from "../components/world-window/passport/passport-scope";

export function CountryStampCollectionScreen({
  active,
  onChange,
  onBack,
  initialCountry,
  onOpenTrip,
  backLabel = "Passport",
  visible = true,
  onBackHandlerChange,
  initialYear,
  scopeEpoch = 0,
  onClearYear,
}: {
  active: BottomNavTab;
  onChange: (tab: BottomNavTab) => void;
  onBack?: () => void;
  initialCountry?: string;
  onOpenTrip?: (trip: TripSummary) => void;
  backLabel?: string;
  visible?: boolean;
  onBackHandlerChange?: (handler: (() => boolean) | null) => void;
  initialYear?: string;
  scopeEpoch?: number;
  onClearYear?: () => void;
}) {
  const insets = useSafeAreaInsets(),
    { width } = useWindowDimensions(),
    visualWidth = getMobileVisualWidth(width);
  const { trips, status, refresh } = useTravelTrips();
  // Preserve the calibrated native stamp system and first-entry identity fixes.
  const [year, setYear] = React.useState(() =>
    normalizeTravelYear(initialYear),
  );
  React.useEffect(
    () => setYear(normalizeTravelYear(initialYear)),
    [initialYear, scopeEpoch],
  );
  const clearYear = () => {
    setYear(undefined);
    onClearYear?.();
  };
  const scope = React.useMemo(() => passportScope(trips, year), [trips, year]);
  const arrivals = scope.arrivals;
  const openTrip = onOpenTrip
    ? (trip: TripSummary) =>
        onOpenTrip(trips.find((item) => item.id === trip.id) ?? trip)
    : undefined;
  const [selectedKey, setSelectedKey] = React.useState<string | null>(
    initialCountry ?? null,
  );
  const [query, setQuery] = React.useState("");
  const [unvisited, setUnvisited] = React.useState<CountryCatalogRecord | null>(null);
  const detailBack = React.useRef<(() => boolean) | null>(null);
  const indexBack = React.useRef<(() => boolean) | null>(null);
  const registerIndexBack = React.useCallback((handler: (() => boolean) | null) => { indexBack.current = handler; }, []);
  const registerDetailBack = React.useCallback(
    (handler: (() => boolean) | null) => {
      detailBack.current = handler;
    },
    [],
  );
  React.useEffect(() => {
    setSelectedKey(initialCountry ?? null);
    setUnvisited(null);
  }, [initialCountry, scopeEpoch]);
  const country = scope.lifetimeArrivals.find(
    (arrival) =>
      selectedKey &&
      [arrival.country, arrival.travelCountryKey].some(
        (value) => value?.toLowerCase() === selectedKey.toLowerCase(),
      ),
  );
  const handleBack = React.useCallback(() => {
    if (detailBack.current?.()) return true;
    if (!country && !unvisited && indexBack.current?.()) return true;
    if ((!country && !unvisited) || initialCountry) return false;
    setSelectedKey(null);
    setUnvisited(null);
    return true;
  }, [country, unvisited, initialCountry]);
  React.useEffect(() => {
    onBackHandlerChange?.(visible ? handleBack : null);
    return () => onBackHandlerChange?.(null);
  }, [visible, handleBack, onBackHandlerChange]);
  const back = () => {
    if (!handleBack()) (onBack ?? (() => onChange("passport")))();
  };
  const hasDetail = Boolean(country || unvisited);
  return (
    <View style={[styles.screen, { paddingTop: insets.top }]}>
      <View
        style={{ flex: 1 }}
        pointerEvents={hasDetail ? "none" : "auto"}
        aria-hidden={hasDetail}
        accessibilityElementsHidden={hasDetail}
        importantForAccessibility={hasDetail ? "no-hide-descendants" : "auto"}
      >
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
          <CountryIndex
            arrivals={arrivals}
            lifetimeArrivals={scope.lifetimeArrivals}
            onSelect={(arrival) => {
              setUnvisited(null);
              setSelectedKey(arrival.travelCountryKey ?? arrival.country);
            }}
            onSelectUnvisited={(entry) => {
              setSelectedKey(entry.key);
              setUnvisited(entry);
            }}
            query={query}
            setQuery={setQuery}
            width={visualWidth}
            onBack={back}
            backLabel={backLabel}
            year={year}
            onClearYear={clearYear}
            active={visible && !hasDetail}
            onBackHandlerChange={registerIndexBack}
          />
        </ScrollView>
      </View>
      {hasDetail && (
        <View
          style={[
            styles.overlay,
            {
              top: insets.top,
              width: visualWidth,
              paddingBottom: layout.bottomNavHeight + insets.bottom,
            },
          ]}
        >
          {country ? <CountryArrivalDetail
            key={country.travelCountryKey ?? country.country}
            arrival={country}
            trips={scope.trips}
            onBack={back}
            onOpenTrip={openTrip}
            width={visualWidth}
            backLabel={initialCountry ? backLabel : "Countries"}
            onBackHandlerChange={registerDetailBack}
            year={year}
            onClearYear={clearYear}
          /> : unvisited ? <UnvisitedCountryRecord entry={unvisited} width={visualWidth} onBack={back} /> : null}
        </View>
      )}
      <BottomNav active={active} onChange={onChange} />
    </View>
  );
}
const styles = StyleSheet.create({
  overlay: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: colors.paperSoft,
  },
  screen: { flex: 1, backgroundColor: colors.paperSoft },
});
