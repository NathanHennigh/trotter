import React from "react";
import { GestureHandlerRootView } from "react-native-gesture-handler";
import { SafeAreaProvider, useSafeAreaInsets } from "react-native-safe-area-context";
import {
  useFonts,
  Outfit_400Regular,
  Outfit_500Medium,
  Outfit_600SemiBold,
  Outfit_700Bold,
} from "@expo-google-fonts/outfit";
import {
  Animated,
  BackHandler,
  Linking,
  Platform,
  StyleSheet,
  Text,
  View,
  type ViewStyle,
} from "react-native";
import { StatusBar } from "expo-status-bar";
import { AuthScreen, SessionRestoringScreen } from "./src/screens/AuthScreen";
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
import { colors, fonts } from "./src/theme/trotterTheme";
import { PressFeedback } from "./src/components/world-window/motion";
import { normalizeTravelYear } from "./src/utils/travelScope";
import type { TripOpenOrigin } from "./src/components/world-window/trips/tripTransition";
import { TripNavigationSurface } from "./src/components/world-window/trips/TripNavigationSurface";
import { TripBackground } from "./src/components/world-window/trips/TripBackground";

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
    "Newsreader-Italic": require("./assets/world-window/fonts/Newsreader-Italic.ttf"),
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
  const { authStatus, accountId, accountRevision } = useTravelTrips();
  const ownerId = authStatus === "signed-in" ? accountId : undefined;
  const owner = React.useRef(ownerId);
  owner.current = ownerId;
  const initialUrlRead = React.useRef(false);
  const [initialUrlResolved, setInitialUrlResolved] = React.useState(false);
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
        .catch(() => undefined)
        .finally(() => setInitialUrlResolved(true));
    }
    return () => subscription.remove();
  }, []);
  const consumeShare = React.useCallback(
    (queueId: number) => dispatchShare({ type: "consume", queueId }),
    [],
  );
  const pendingShare = shares.items.find((item) => item.ownerId === undefined || item.ownerId === ownerId);
  if (authStatus === "loading" || !initialUrlResolved || (authStatus === "signed-in" && shares.ownerId !== ownerId)) {
    return <SessionRestoringScreen sourceUrl={pendingShare?.sourceUrl} />;
  }
  if (authStatus !== "signed-in") return <AuthScreen />;
  // Filter during render too: the owner-transition effect runs after render.
  const incomingShare = shares.items.find((item) => item.ownerId === accountId);
  return (
    <DreamsProvider key={`${accountId}:${accountRevision}`}>
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
  const [activeTab, setActiveTab] = React.useState<BottomNavTab>(() => incomingShare ? "dreams" : getInitialTab());
  const currentTab = React.useRef(activeTab);
  currentTab.current = activeTab;
  const [visitedTabs, setVisitedTabs] = React.useState<BottomNavTab[]>(() => [activeTab]);
  const [globeYear, setGlobeYear] = React.useState("All years");
  const [tripsReset, setTripsReset] = React.useState(0);
  const scopeSequence = React.useRef(0);
  const [passportReset, setPassportReset] = React.useState(0);
  const [selectedTripId, setSelectedTripId] = React.useState<string | null>(null);
  const [selectedFlightId, setSelectedFlightId] = React.useState<string>();
  const [tripClosing, setTripClosing] = React.useState(false);
  const [tripSettled, setTripSettled] = React.useState(false);
  const tripProgress = React.useRef(new Animated.Value(0)).current;
  const tripDragOffset = React.useRef(new Animated.Value(0)).current;
  const [tripPaperOrigin, setTripPaperOrigin] = React.useState<TripOpenOrigin>();
  const [countries, setCountries] = React.useState<{
    initialCountry?: string;
    returnTab: BottomNavTab;
    year?: string;
    epoch: number;
  } | null>(null);
  const [passportCollection, setPassportCollection] = React.useState<{
    kind: CollectionKind;
    returnTab: BottomNavTab;
    year?: string;
    epoch: number;
    airport?: string;
  } | null>(null);
  const tripOrigin = React.useRef<BottomNavTab>("trips");
  const handlers = React.useRef<Record<string, (() => boolean) | null>>({});
  const registerPassportBack = React.useCallback((handler: (() => boolean) | null) => {
    handlers.current.passport = handler;
  }, []);
  const registerCountryBack = React.useCallback((handler: (() => boolean) | null) => {
    handlers.current.countries = handler;
  }, []);
  const registerDreamsBack = React.useCallback((handler: (() => boolean) | null) => {
    handlers.current.dreams = handler;
  }, []);
  const registerGlobeBack = React.useCallback((handler: (() => boolean) | null) => {
    handlers.current.globe = handler;
  }, []);
  const { trips } = useTravelTrips();
  const { shareInstagramLinkDurable } = useDreams();
  const insets = useSafeAreaInsets();
  const handledShare = React.useRef<{ queueId: number; status: "capturing" | "failed" | "retained" } | undefined>(undefined);
  const shareHostMounted = React.useRef(true);
  const [shareCaptureAttempt, setShareCaptureAttempt] = React.useState(0);
  const [shareCaptureError, setShareCaptureError] = React.useState<{ queueId: number; message: string }>();
  const selectedTrip = trips.find((trip) => trip.id === selectedTripId);
  const visit = (tab: BottomNavTab) => {
    setVisitedTabs((visited) => visited.includes(tab) ? visited : [...visited, tab]);
    setActiveTab(tab);
  };
  const changeTab = (tab: BottomNavTab) => {
    tripProgress.stopAnimation(); tripProgress.setValue(0);
    tripDragOffset.stopAnimation(); tripDragOffset.setValue(0);
    setPassportReset((value) => value + 1);
    setSelectedTripId(null);
    setSelectedFlightId(undefined);
    setTripClosing(false);
    setTripSettled(false);
    setCountries(null);
    setPassportCollection(null);
    visit(tab);
  };
  const openTrip = (trip: TripSummary, flightId?: string, paperOrigin?: TripOpenOrigin) => {
    if (currentTab.current !== activeTab) return;
    tripOrigin.current = activeTab;
    tripProgress.stopAnimation(); tripProgress.setValue(0);
    tripDragOffset.stopAnimation(); tripDragOffset.setValue(0);
    setSelectedTripId(trip.id);
    setSelectedFlightId(flightId);
    setTripClosing(false);
    setTripSettled(false);
    setTripPaperOrigin(paperOrigin);
    // Keep the origin mounted, including its collection selection and scroll.
    visit("trips");
  };
  const finishCloseTrip = () => {
    tripProgress.setValue(0); tripDragOffset.setValue(0);
    setSelectedTripId(null);
    setSelectedFlightId(undefined);
    setTripClosing(false);
    setTripSettled(false);
    setTripPaperOrigin(undefined);
    visit(tripOrigin.current);
  };
  const closeTrip = () => setTripClosing(true);
  const openTrips = () => {
    setTripsReset(value => value + 1);
    changeTab("trips");
  };
  const openCountries = (code?: string, year?: string) => {
    setPassportCollection(null);
    setCountries({ initialCountry: code, returnTab: activeTab, year: normalizeTravelYear(year), epoch: ++scopeSequence.current });
    visit("passport");
  };
  const closeCountries = () => {
    const origin = countries?.returnTab ?? "passport";
    setCountries(null);
    visit(origin);
  };
  const openPassportCollection = (kind: CollectionKind, year?: string, airport?: string) => {
    if (kind === "countries") {
      openCountries(undefined, year);
      return;
    }
    setPassportCollection({ kind, returnTab: activeTab, year: normalizeTravelYear(year), epoch: ++scopeSequence.current, airport });
    setCountries(null);
    setSelectedTripId(null);
    setSelectedFlightId(undefined);
    visit("passport");
  };
  const closePassportCollection = () => {
    const origin = passportCollection?.returnTab ?? "passport";
    setPassportCollection(null);
    visit(origin);
  };
  React.useEffect(() => {
    shareHostMounted.current = true;
    return () => { shareHostMounted.current = false; };
  }, []);
  React.useEffect(() => {
    if (!incomingShare || handledShare.current?.queueId === incomingShare.queueId) return;
    const { queueId, sourceUrl, sharedText } = incomingShare;
    handledShare.current = { queueId, status: "capturing" };
    setShareCaptureError(undefined);
    changeTab("dreams");
    void (async () => {
      try {
        // This confirms local retention only. Dreams owns upload progress and
        // only presents a saved receipt after the server acknowledges it.
        await shareInstagramLinkDurable(sourceUrl, sharedText);
        if (!shareHostMounted.current || handledShare.current?.queueId !== queueId) return;
        handledShare.current = { queueId, status: "retained" };
        consumeShare(queueId);
      } catch (caught) {
        if (!shareHostMounted.current || handledShare.current?.queueId !== queueId) return;
        handledShare.current = { queueId, status: "failed" };
        setShareCaptureError({ queueId, message: caught instanceof Error ? caught.message : "Your link is still here. Keep Trotter open and try again." });
      }
    })();
  }, [incomingShare, consumeShare, shareInstagramLinkDurable, shareCaptureAttempt]);
  const retryIncomingShare = () => {
    if (!incomingShare || handledShare.current?.queueId !== incomingShare.queueId || handledShare.current.status !== "failed") return;
    handledShare.current = undefined;
    setShareCaptureError(undefined);
    setShareCaptureAttempt(value => value + 1);
  };
  React.useEffect(() => {
    if (selectedTripId && !selectedTrip) finishCloseTrip();
  }, [selectedTripId, selectedTrip]);
  React.useEffect(() => {
    const listener = BackHandler.addEventListener("hardwareBackPress", () => {
      if (selectedTripId) { closeTrip(); return true; }
      if (activeTab === "passport") {
        if (countries) {
          if (!handlers.current.countries?.()) closeCountries();
          return true;
        }
        if (handlers.current.passport?.()) return true;
        if (passportCollection) { closePassportCollection(); return true; }
      }
      if (activeTab === "dreams" && handlers.current.dreams?.()) return true;
      if (activeTab === "globe" && handlers.current.globe?.()) return true;
      if (activeTab !== "globe") { changeTab("globe"); return true; }
      return false;
    });
    return () => listener.remove();
  }, [selectedTripId, countries, passportCollection, activeTab]);

  // Retain navigation state without exposing or accepting input on hidden screens.
  const layer = (key: string, visible: boolean, content: React.ReactNode) => (
    // Keep Fabric's native boundary stable as opacity and pointer events
    // change; flattening/reparenting this layer would detach the globe TextureView.
    <View key={key} testID={`screen-layer-${key}`} collapsable={false} style={[styles.overlay, !visible && styles.inactive]}
      pointerEvents={visible && !selectedTrip ? "auto" : "none"}
      accessibilityElementsHidden={!visible || Boolean(selectedTrip)}
      aria-hidden={!visible || Boolean(selectedTrip)}
      importantForAccessibility={visible && !selectedTrip ? "auto" : "no-hide-descendants"}>
      {content}
    </View>
  );
  const mainVisible = !selectedTrip;
  const baseTab = selectedTrip ? tripOrigin.current : activeTab;
  const passportVisible = baseTab === "passport" && !countries;
  const countryVisible = baseTab === "passport" && Boolean(countries);
  const label = (tab: BottomNavTab) => tab.charAt(0).toUpperCase() + tab.slice(1);
  return (
    <View style={styles.shell}>
      <TripBackground progress={tripProgress} dragOffset={tripDragOffset}>
      {visitedTabs.includes("globe") && layer("globe", baseTab === "globe",
        <HomeGlobeScreen filterYear={globeYear} onFilterYear={setGlobeYear}
          visible={mainVisible && activeTab === "globe"}
          onBackHandlerChange={registerGlobeBack}
          active={activeTab} onChange={changeTab} onOpenTrip={openTrip}
          onOpenCountry={openCountries} onOpenCollection={openPassportCollection} onOpenFlights={openTrips} />)}
      {visitedTabs.includes("trips") && layer("trips", baseTab === "trips",
        <TripsListScreen active={activeTab} onChange={changeTab} onOpenTrip={openTrip}
          resetEpoch={tripsReset} />)}
      {visitedTabs.includes("passport") && layer("passport", passportVisible,
        <PassportStatsScreen visible={passportVisible && mainVisible} resetEpoch={passportReset} onBackHandlerChange={registerPassportBack}
          initialCollection={passportCollection?.kind}
          initialYear={passportCollection?.year} scopeEpoch={passportCollection?.epoch}
          initialAirport={passportCollection?.airport}
          onClearYear={() => setPassportCollection(value => value ? { ...value, year: undefined, epoch: ++scopeSequence.current } : null)}
          collectionBackLabel={passportCollection ? label(passportCollection.returnTab) : undefined}
          onCloseCollection={passportCollection ? closePassportCollection : undefined}
          onYear={(year) => { setGlobeYear(year); changeTab("globe"); }}
          active={activeTab} onChange={changeTab} onOpenCountries={() => openCountries()}
          onOpenTrip={openTrip} />)}
      {countries && layer("countries", countryVisible,
        <CountryStampCollectionScreen visible={countryVisible && mainVisible}
          onBackHandlerChange={registerCountryBack} backLabel={label(countries.returnTab)}
          active={activeTab} onChange={changeTab} initialCountry={countries.initialCountry}
          initialYear={countries.year} scopeEpoch={countries.epoch}
          onClearYear={() => setCountries(value => value ? { ...value, year: undefined, epoch: ++scopeSequence.current } : null)}
          onBack={closeCountries} onOpenTrip={openTrip} />)}
      {visitedTabs.includes("dreams") && layer("dreams", baseTab === "dreams",
        <DreamsScreen active={activeTab} onChange={changeTab}
          visible={mainVisible && activeTab === "dreams"} onBackHandlerChange={registerDreamsBack} />)}
      {visitedTabs.includes("profile") && layer("profile", baseTab === "profile",
        <ProfileScreen active={activeTab} onChange={changeTab} onOpenStamps={() => openCountries()}
          onOpenAirport={code => openPassportCollection("airports", undefined, code)} />)}
      </TripBackground>
      {selectedTrip && <TripNavigationSurface key={selectedTrip.id} trip={selectedTrip} flightId={selectedFlightId}
        origin={tripPaperOrigin} closing={tripClosing} onClosed={finishCloseTrip} onRequestClose={closeTrip}
        onEntered={() => setTripSettled(true)}
        motionProgress={tripProgress} dragOffset={tripDragOffset}
        closeLabel={tripOrigin.current === "passport" ? "Back to collection" : `Back to ${label(tripOrigin.current).toLowerCase()}`}>
        <TripDetailScreen key={selectedTrip.id} trip={selectedTrip} selectedFlightId={selectedFlightId}
          active="trips" onBack={closeTrip} onChange={changeTab} popup
          deferUpdates={!tripSettled || tripClosing}
          backLabel={tripOrigin.current === "passport" ? "Back to collection" : `Back to ${label(tripOrigin.current).toLowerCase()}`} />
      </TripNavigationSurface>}
      {shareCaptureError && shareCaptureError.queueId === incomingShare?.queueId && (
        <View accessibilityRole="alert" accessibilityLiveRegion="polite" style={[styles.shareError, { bottom: insets.bottom + 72 }]}>
          <Text style={styles.shareErrorTitle}>Couldn’t keep this post</Text>
          <Text style={styles.shareErrorMessage}>{shareCaptureError.message}</Text>
          <PressFeedback accessibilityRole="button" accessibilityLabel="Retry keeping shared post" onPress={retryIncomingShare} style={styles.shareRetry}>
            <Text style={styles.shareRetryText}>Try again</Text>
          </PressFeedback>
        </View>
      )}
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
  shareError: { position: "absolute", left: 16, right: 16, padding: 16, backgroundColor: colors.paper, borderWidth: 1, borderColor: colors.paperBorder, borderRadius: 8, gap: 6 },
  shareErrorTitle: { color: colors.ink, fontFamily: fonts.sansSemi, fontSize: 15, lineHeight: 20 },
  shareErrorMessage: { color: colors.mutedInk, fontFamily: fonts.sansRegular, fontSize: 13, lineHeight: 19 },
  shareRetry: { minHeight: 44, alignSelf: "flex-start", justifyContent: "center", paddingHorizontal: 12, marginLeft: -12 },
  shareRetryText: { color: colors.blue, fontFamily: fonts.sansSemi, fontSize: 13 },
  inactive: { opacity: 0 },
  overlay: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: colors.paperSoft,
  },
});
