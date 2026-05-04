import React from 'react';
import { GestureHandlerRootView } from 'react-native-gesture-handler';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { useFonts, Outfit_400Regular, Outfit_500Medium, Outfit_600SemiBold, Outfit_700Bold } from '@expo-google-fonts/outfit';
import { Asset } from 'expo-asset';
import { Platform, StyleSheet, View, ViewStyle } from 'react-native';
import { StatusBar } from 'expo-status-bar';
import { CountryStampCollectionScreen } from './src/screens/CountryStampCollectionScreen';
import { HomeGlobeScreen } from './src/screens/HomeGlobeScreen';
import { PassportStatsScreen } from './src/screens/PassportStatsScreen';
import { TripsListScreen } from './src/screens/TripsListScreen';
import { BottomNavTab } from './src/data/trotterMock';
import { colors } from './src/theme/trotterTheme';

const tabs: BottomNavTab[] = ['globe', 'trips', 'passport', 'dreams', 'profile'];
const globeAssets = [
  require('./assets/globe/blue-marble-day-2048.jpg'),
  require('./assets/globe/black-marble-2016-3600.jpg'),
];

function getInitialTab(): BottomNavTab {
  const location = (globalThis as { location?: { search?: string } }).location;
  const requested = new URLSearchParams(location?.search ?? '').get('tab');
  return tabs.includes(requested as BottomNavTab) ? (requested as BottomNavTab) : 'globe';
}

export default function App() {
  const [activeTab, setActiveTab] = React.useState<BottomNavTab>(getInitialTab);
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

  const renderOverlayScreen = () => {
    if (activeTab === 'trips') return <TripsListScreen active={activeTab} onChange={setActiveTab} />;
    if (activeTab === 'passport') return <PassportStatsScreen active={activeTab} onChange={setActiveTab} />;
    // Temporary: Countries is parked behind Profile until the final v2 nav IA adds a dedicated collection route.
    if (activeTab === 'profile') return <CountryStampCollectionScreen active={activeTab} onChange={setActiveTab} />;
    return null;
  };

  return (
    <GestureHandlerRootView style={[styles.gestureRoot, styles.webViewportRoot]}>
      <SafeAreaProvider>
        <StatusBar style="light" translucent />
        <View style={styles.shell}>
          <HomeGlobeScreen active={activeTab} onChange={setActiveTab} />
          {activeTab !== 'globe' ? (
            <View style={styles.overlayScreen}>
              {renderOverlayScreen()}
            </View>
          ) : null}
        </View>
      </SafeAreaProvider>
    </GestureHandlerRootView>
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
