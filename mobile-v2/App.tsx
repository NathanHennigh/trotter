import React from 'react';
import { GestureHandlerRootView } from 'react-native-gesture-handler';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { useFonts, Outfit_400Regular, Outfit_500Medium, Outfit_600SemiBold, Outfit_700Bold } from '@expo-google-fonts/outfit';
import { Asset } from 'expo-asset';
import { Linking, Platform, StyleSheet, View, ViewStyle } from 'react-native';
import { StatusBar } from 'expo-status-bar';
import { CountryStampCollectionScreen } from './src/screens/CountryStampCollectionScreen';
import { DreamsScreen } from './src/screens/DreamsScreen';
import { HomeGlobeScreen } from './src/screens/HomeGlobeScreen';
import { PassportStatsScreen } from './src/screens/PassportStatsScreen';
import { ProfileScreen } from './src/screens/ProfileScreen';
import { TripDetailScreen } from './src/screens/TripDetailScreen';
import { TripsListScreen } from './src/screens/TripsListScreen';
import { BottomNavTab } from './src/data/trotterMock';
import { DreamsProvider, parseIncomingDreamShare, useDreams } from './src/services/dreams';
import { TravelTripsProvider, useTravelTrips } from './src/services/travelTrips';
import { colors } from './src/theme/trotterTheme';

const tabs: BottomNavTab[] = ['globe', 'trips', 'passport', 'dreams', 'profile'];
const globeAssets = [
  require('./assets/globe/blue-marble-day-2048.jpg'),
  require('./assets/globe/blue-marble-day-4096.jpg'),
  require('./assets/globe/black-marble-2016-3600.jpg'),
];

function getInitialTab(): BottomNavTab {
  const location = (globalThis as { location?: { search?: string } }).location;
  const requested = new URLSearchParams(location?.search ?? '').get('tab');
  return tabs.includes(requested as BottomNavTab) ? (requested as BottomNavTab) : 'globe';
}

export default function App() {
  const [fontsLoaded] = useFonts({
    Outfit_400Regular,
    Outfit_500Medium,
    Outfit_600SemiBold,
    Outfit_700Bold,
  });

  React.useEffect(() => {
    Asset.loadAsync(globeAssets).catch(() => undefined);
  }, []);

  if (!fontsLoaded) {
    return <View style={{ flex: 1, backgroundColor: colors.appBackground }} />;
  }

  return (
    <GestureHandlerRootView style={[styles.gestureRoot, styles.webViewportRoot]}>
      <SafeAreaProvider>
        <TravelTripsProvider>
          <DreamsProvider>
            <AppShell />
          </DreamsProvider>
        </TravelTripsProvider>
      </SafeAreaProvider>
    </GestureHandlerRootView>
  );
}

function AppShell() {
  const [activeTab, setActiveTab] = React.useState<BottomNavTab>(getInitialTab);
  const [selectedTripId, setSelectedTripId] = React.useState<string | null>(null);
  const [showCountryStamps, setShowCountryStamps] = React.useState(false);
  const { trips } = useTravelTrips();
  const { shareInstagramLink } = useDreams();
  const shareInstagramLinkRef = React.useRef(shareInstagramLink);
  const handledShareUrlsRef = React.useRef(new Set<string>());
  const selectedTrip = selectedTripId ? trips.find((trip) => trip.id === selectedTripId) ?? null : null;

  React.useEffect(() => {
    shareInstagramLinkRef.current = shareInstagramLink;
  }, [shareInstagramLink]);

  const changeTab = (tab: BottomNavTab) => {
    setActiveTab(tab);
    if (tab !== 'trips') setSelectedTripId(null);
    setShowCountryStamps(false);
  };

  const renderOverlayScreen = () => {
    if (activeTab === 'trips' && selectedTrip) {
      return <TripDetailScreen trip={selectedTrip} active={activeTab} onBack={() => setSelectedTripId(null)} onChange={changeTab} />;
    }
    if (activeTab === 'trips') return <TripsListScreen active={activeTab} onChange={changeTab} onOpenTrip={(trip) => setSelectedTripId(trip.id)} />;
    if (activeTab === 'passport' && showCountryStamps) {
      return <CountryStampCollectionScreen active={activeTab} onChange={changeTab} onBack={() => setShowCountryStamps(false)} />;
    }
    if (activeTab === 'passport') {
      return <PassportStatsScreen active={activeTab} onChange={changeTab} onOpenCountries={() => setShowCountryStamps(true)} />;
    }
    if (activeTab === 'dreams') return <DreamsScreen active={activeTab} onChange={changeTab} />;
    if (activeTab === 'profile') {
      return (
        <ProfileScreen
          active={activeTab}
          onChange={changeTab}
          onOpenStamps={() => {
            setActiveTab('passport');
            setShowCountryStamps(true);
          }}
        />
      );
    }
    return null;
  };

  React.useEffect(() => {
    const handleUrl = ({ url }: { url: string }) => {
      const incomingShare = parseIncomingDreamShare(url);
      if (!incomingShare) return;
      const shareKey = `${incomingShare.sourceUrl}|${incomingShare.sharedText ?? ''}`;
      if (handledShareUrlsRef.current.has(shareKey)) return;
      handledShareUrlsRef.current.add(shareKey);
      shareInstagramLinkRef.current(incomingShare.sourceUrl, incomingShare.sharedText);
      setSelectedTripId(null);
      setActiveTab('dreams');
    };

    const subscription = Linking.addEventListener('url', handleUrl);
    Linking.getInitialURL()
      .then((url) => {
        if (url) handleUrl({ url });
      })
      .catch(() => undefined);
    return () => subscription.remove();
  }, []);

  return (
    <>
      <StatusBar style="light" translucent />
      <View style={styles.shell}>
        <HomeGlobeScreen active={activeTab} onChange={changeTab} />
        {activeTab !== 'globe' ? (
          <View style={styles.overlayScreen}>
            {renderOverlayScreen()}
          </View>
        ) : null}
      </View>
    </>
  );
}

const styles = StyleSheet.create({
  gestureRoot: {
    flex: 1,
  },
  webViewportRoot:
    Platform.OS === 'web'
      ? ({
          minHeight: '100vh',
        } as unknown as ViewStyle)
      : {},
  shell: {
    flex: 1,
    backgroundColor: colors.appBackground,
  },
  overlayScreen: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: colors.paperSoft,
  },
});
