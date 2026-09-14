import React from "react";
import { GestureHandlerRootView } from "react-native-gesture-handler";
import { SafeAreaProvider } from "react-native-safe-area-context";
import {
  useFonts,
  Outfit_400Regular,
  Outfit_500Medium,
  Outfit_600SemiBold,
  Outfit_700Bold,
} from "@expo-google-fonts/outfit";
import {
  BackHandler,
  Linking,
  Platform,
  StyleSheet,
  View,
  type ViewStyle,
} from "react-native";
import { StatusBar } from "expo-status-bar";
import { AuthScreen } from "./src/screens/AuthScreen";
import { CountryStampCollectionScreen } from "./src/screens/CountryStampCollectionScreen";
import { DreamsScreen } from "./src/screens/DreamsScreen";
import { HomeGlobeScreen } from "./src/screens/HomeGlobeScreen";
import { PassportStatsScreen } from "./src/screens/PassportStatsScreen";
import type { CollectionKind } from "./src/components/world-window/passport/PassportCollections";
import { ProfileScreen } from "./src/screens/ProfileScreen";
import { TripDetailScreen } from "./src/screens/TripDetailScreen";
import { TripsListScreen } from "./src/screens/TripsListScreen";
import type { BottomNavTab, TripSummary } from "./src/data/trotterMock";
import {
  DreamsProvider,
  parseIncomingDreamShare,
  useDreams,
  type IncomingDreamShare,
} from "./src/services/dreams";
import {
  TravelTripsProvider,
  useTravelTrips,
} from "./src/services/travelTrips";
import { colors } from "./src/theme/trotterTheme";

const tabs: BottomNavTab[] = [
  "globe",
  "trips",
  "passport",
  "dreams",
  "profile",
];
function getInitialTab(): BottomNavTab {
  const location = (globalThis as { location?: { search?: string } }).location;
  const requested = new URLSearchParams(location?.search ?? "").get("tab");
  return tabs.includes(requested as BottomNavTab)
    ? (requested as BottomNavTab)
    : "globe";
}

export default function App() {
  const [fontsLoaded, fontError] = useFonts({
    Outfit_400Regular,
    Outfit_500Medium,
    Outfit_600SemiBold,
    Outfit_700Bold,
    "Newsreader-Regular": require("./assets/world-window/fonts/Newsreader-Regular.ttf"),
    "Newsreader-Medium": require("./assets/world-window/fonts/Newsreader-Medium.ttf"),
    "DMSans-Regular": require("./assets/world-window/fonts/DMSans-Regular.ttf"),
    "DMSans-Medium": require("./assets/world-window/fonts/DMSans-Medium.ttf"),
    "DMSans-SemiBold": require("./assets/world-window/fonts/DMSans-SemiBold.ttf"),
    "DMSans-Bold": require("./assets/world-window/fonts/DMSans-Bold.ttf"),
    "IBMPlexMono-Regular": require("./assets/world-window/fonts/IBMPlexMono-Regular.ttf"),
    "IBMPlexMono-Medium": require("./assets/world-window/fonts/IBMPlexMono-Medium.ttf"),
  });
  if (!fontsLoaded && !fontError)
    return <View style={{ flex: 1, backgroundColor: colors.paperSoft }} />;
  return (
    <GestureHandlerRootView style={[styles.root, styles.webRoot]}>
      <SafeAreaProvider>
        <StatusBar style="dark" />
        <TravelTripsProvider>
          <AccountGate />
        </TravelTripsProvider>
      </SafeAreaProvider>
    </GestureHandlerRootView>
  );
}

type QueuedShare = IncomingDreamShare & {
  queueId: number;
  ownerId?: number;
  key: string;
};
type ShareQueue = {
  ownerId?: number;
  items: QueuedShare[];
  nextId: number;
  recent: { key: string; at: number }[];
};
type ShareQueueAction =
  | { type: "owner"; ownerId?: number }
  | {
      type: "receive";
      ownerId?: number;
      share: IncomingDreamShare;
      now: number;
    }
  | { type: "consume"; queueId: number };
// Signed-out receipts bind to the first verified account. Receipts already
// associated with an account never survive its sign-out or account change.
export function reduceIncomingShareQueue(
  state: ShareQueue,
  action: ShareQueueAction,
): ShareQueue {
  if (action.type === "consume")
    return {
      ...state,
      items: state.items.filter((item) => item.queueId !== action.queueId),
    };
  const ownerId = action.ownerId;
  let next = state;
  if (state.ownerId !== ownerId) {
    next = {
      ...state,
      ownerId,
      items: state.items
        .filter(
          (item) => item.ownerId === undefined || item.ownerId === ownerId,
        )
        .map((item) => ({ ...item, ownerId })),
    };
  }
  if (action.type === "owner") return next;
  const key = JSON.stringify([
    action.share.sourceUrl.trim(),
    action.share.sharedText ?? "",
  ]);
  const recent = next.recent.filter(
    (receipt) => action.now - receipt.at < 2000,
  );
  if (
    next.items.some((item) => item.key === key) ||
    recent.some((receipt) => receipt.key === key)
  )
    return next;
  return {
    ...next,
    nextId: next.nextId + 1,
    recent: [...recent, { key, at: action.now }],
    items: [
      ...next.items,
      { ...action.share, key, queueId: next.nextId, ownerId },
    ],
  };
}

// Capture signed-out shares without carrying account-owned content across login.
function AccountGate() {
  const { authStatus, accountId } = useTravelTrips();
  const ownerId = authStatus === "signed-in" ? accountId : undefined;
  const owner = React.useRef(ownerId);
  owner.current = ownerId;
  const initialUrlRead = React.useRef(false);
  const delivered = React.useRef(new Set<string>());
  const [shares, dispatchShare] = React.useReducer(reduceIncomingShareQueue, {
    items: [],
    nextId: 1,
    recent: [],
  });
  React.useEffect(() => {
    dispatchShare({ type: "owner", ownerId });
  }, [ownerId]);
  React.useEffect(() => {
    const receive = (url: string, initial = false) => {
      const incoming = parseIncomingDreamShare(url);
      if (!incoming) return;
      const key = JSON.stringify([
        incoming.sourceUrl.trim(),
        incoming.sharedText ?? "",
      ]);
      if (initial && delivered.current.has(key)) return;
      delivered.current.add(key);
      dispatchShare({
        type: "receive",
        ownerId: owner.current,
        share: incoming,
        now: Date.now(),
      });
    };
    const handleUrl = ({ url }: { url: string }) => receive(url);
    const subscription = Linking.addEventListener("url", handleUrl);
    if (!initialUrlRead.current) {
      initialUrlRead.current = true;
      Linking.getInitialURL()
        .then((url) => {
          if (url) receive(url, true);
        })
        .catch(() => undefined);
    }
    return () => subscription.remove();
  }, []);
  const consumeShare = React.useCallback(
    (queueId: number) => dispatchShare({ type: "consume", queueId }),
    [],
  );
  if (authStatus !== "signed-in") return <AuthScreen />;
  // Filter during render too: the owner-transition effect runs after render.
  const incomingShare = shares.items.find((item) => item.ownerId === accountId);
  return (
    <DreamsProvider key={accountId}>
      <AppShell incomingShare={incomingShare} consumeShare={consumeShare} />
    </DreamsProvider>
  );
}

function AppShell({
  incomingShare,
  consumeShare,
}: {
  incomingShare?: QueuedShare;
  consumeShare: (queueId: number) => void;
}) {
  const [activeTab, setActiveTab] = React.useState<BottomNavTab>(getInitialTab);
  const [globeYear, setGlobeYear] = React.useState("All years");
  const [selectedTripId, setSelectedTripId] = React.useState<string | null>(
    null,
  );
  const [selectedFlightId, setSelectedFlightId] = React.useState<
    string | undefined
  >();
  const [countries, setCountries] = React.useState<{
    initialCountry?: string;
  } | null>(null);
  const [passportCollection, setPassportCollection] = React.useState<{
    kind: CollectionKind;
    returnTab: BottomNavTab;
  } | null>(null);
  const { trips } = useTravelTrips();
  const { shareInstagramLink } = useDreams();
  const handledShare = React.useRef<number | undefined>(undefined);
  const selectedTrip = trips.find((trip) => trip.id === selectedTripId);
  const changeTab = (tab: BottomNavTab) => {
    setActiveTab(tab);
    setSelectedTripId(null);
    setSelectedFlightId(undefined);
    setCountries(null);
    setPassportCollection(null);
  };
  const openTrip = (trip: TripSummary, flightId?: string) => {
    setSelectedTripId(trip.id);
    setSelectedFlightId(flightId);
    setCountries(null);
    setPassportCollection(null);
    setActiveTab("trips");
  };
  const openCountries = (code?: string) => {
    setPassportCollection(null);
    setCountries({ initialCountry: code });
    setActiveTab("passport");
  };
  const openPassportCollection = (kind: CollectionKind) => {
    setPassportCollection({ kind, returnTab: activeTab });
    setCountries(null);
    setSelectedTripId(null);
    setSelectedFlightId(undefined);
    setActiveTab("passport");
  };
  const closePassportCollection = () => {
    setPassportCollection(null);
    setActiveTab(passportCollection?.returnTab ?? "passport");
  };
  React.useEffect(() => {
    if (!incomingShare || handledShare.current === incomingShare.queueId)
      return;
    handledShare.current = incomingShare.queueId;
    shareInstagramLink(incomingShare.sourceUrl, incomingShare.sharedText);
    setSelectedTripId(null);
    setCountries(null);
    setPassportCollection(null);
    setActiveTab("dreams");
    consumeShare(incomingShare.queueId);
  }, [incomingShare, consumeShare, shareInstagramLink]);
  React.useEffect(() => {
    const listener = BackHandler.addEventListener("hardwareBackPress", () => {
      if (selectedTripId) {
        setSelectedTripId(null);
        setSelectedFlightId(undefined);
        return true;
      }
      if (countries) {
        setCountries(null);
        return true;
      }
      if (passportCollection) {
        closePassportCollection();
        return true;
      }
      if (activeTab !== "globe") {
        setActiveTab("globe");
        return true;
      }
      return false;
    });
    return () => listener.remove();
  }, [selectedTripId, countries, passportCollection, activeTab]);
  let overlay: React.ReactNode = null;
  if (activeTab === "trips")
    overlay = selectedTrip ? (
      <TripDetailScreen
        trip={selectedTrip}
        selectedFlightId={selectedFlightId}
        active={activeTab}
        onBack={() => {
          setSelectedTripId(null);
          setSelectedFlightId(undefined);
        }}
        onChange={changeTab}
      />
    ) : (
      <TripsListScreen
        active={activeTab}
        onChange={changeTab}
        onOpenTrip={openTrip}
      />
    );
  if (activeTab === "passport")
    overlay = (
      <View style={styles.shell}>
        <PassportStatsScreen
          initialCollection={passportCollection?.kind}
          collectionBackLabel={passportCollection?.returnTab === "globe" ? "Globe" : undefined}
          onCloseCollection={passportCollection ? closePassportCollection : undefined}
          onYear={(year) => {
            setGlobeYear(year);
            changeTab("globe");
          }}
          active={activeTab}
          onChange={changeTab}
          onOpenCountries={() => openCountries()}
          onOpenTrip={openTrip}
        />
        {countries ? (
          <View style={styles.overlay}>
            <CountryStampCollectionScreen
              active={activeTab}
              onChange={changeTab}
              initialCountry={countries.initialCountry}
              onBack={() => setCountries(null)}
              onOpenTrip={openTrip}
            />
          </View>
        ) : null}
      </View>
    );
  if (activeTab === "dreams")
    overlay = <DreamsScreen active={activeTab} onChange={changeTab} />;
  if (activeTab === "profile")
    overlay = (
      <ProfileScreen
        active={activeTab}
        onChange={changeTab}
        onOpenStamps={() => openCountries()}
      />
    );
  return (
    <View style={styles.shell}>
      <HomeGlobeScreen
        filterYear={globeYear}
        onFilterYear={setGlobeYear}
        active={activeTab}
        onChange={changeTab}
        onOpenTrip={openTrip}
        onOpenCountry={openCountries}
        onOpenCollection={openPassportCollection}
      />
      {overlay ? <View style={styles.overlay}>{overlay}</View> : null}
    </View>
  );
}
const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.paperSoft },
  webRoot:
    Platform.OS === "web"
      ? ({
          height: "100dvh",
          maxWidth: 430,
          width: "100%",
          alignSelf: "center",
          overflow: "hidden",
        } as unknown as ViewStyle)
      : {},
  shell: { flex: 1, backgroundColor: colors.paperSoft },
  overlay: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: colors.paperSoft,
  },
});
