import React, { useState, useEffect } from 'react';
import { View, StyleSheet, StatusBar, SafeAreaView } from 'react-native';
import { useFonts, SpaceMono_400Regular } from '@expo-google-fonts/space-mono';
import { useAuthStore }    from './src/store/useAuthStore';
import { useFlightsStore } from './src/store/useFlightsStore';

import BootScreen      from './src/screens/BootScreen';
import LoginScreen     from './src/screens/LoginScreen';
import HomeScreen      from './src/screens/HomeScreen';
import FlightLogScreen from './src/screens/FlightLogScreen';
import StatsScreen     from './src/screens/StatsScreen';
import ImportScreen    from './src/screens/ImportScreen';

export default function App() {
  const [fontsLoaded] = useFonts({ SpaceMono: SpaceMono_400Regular });
  const [screen, setScreen] = useState('boot');

  const authStatus  = useAuthStore(s => s.status);
  const authToken   = useAuthStore(s => s.token);
  const restoreAuth = useAuthStore(s => s.restore);
  const loadFlights = useFlightsStore(s => s.load);

  // Restore persisted session on first app load
  useEffect(() => { restoreAuth(); }, []);

  // After boot animation finishes, decide where to go
  const handleBootDone = () => {
    if (authStatus === 'authenticated') {
      // Try to load real flights in background; home renders with dummy data in the meantime
      if (authToken) loadFlights(authToken).catch(() => {});
      setScreen('home');
    } else {
      setScreen('login');
    }
  };

  // After login, kick off flight load and go home via boot
  useEffect(() => {
    if (authStatus === 'authenticated' && screen === 'login') {
      if (authToken) loadFlights(authToken).catch(() => {});
      setScreen('boot');
    }
  }, [authStatus]);

  if (!fontsLoaded) return null;

  const renderScreen = () => {
    switch (screen) {
      case 'boot':
        return <BootScreen onDone={handleBootDone} />;
      case 'login':
        return <LoginScreen />;
      case 'home':
        return <HomeScreen onNavigate={setScreen} casingKey="beige" displayKey="amber" />;
      case 'log':
        return <FlightLogScreen onBack={() => setScreen('home')} />;
      case 'stats':
        return <StatsScreen onBack={() => setScreen('home')} />;
      case 'import':
        return (
          <ImportScreen
            onBack={() => setScreen('home')}
            onDone={() => setScreen('home')}
          />
        );
      default:
        return <HomeScreen onNavigate={setScreen} />;
    }
  };

  return (
    <SafeAreaView style={s.safe}>
      <StatusBar barStyle="light-content" backgroundColor="#050c03" />
      <View style={s.container}>
        {renderScreen()}
      </View>
    </SafeAreaView>
  );
}

const s = StyleSheet.create({
  safe:      { flex: 1, backgroundColor: '#2a2a2a' },
  container: { flex: 1 },
});
