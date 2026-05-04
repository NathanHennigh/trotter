# Expo Port Plan

## Key HTML → RN Mapping
- `div` → `View`
- `span/p` → `Text`
- CSS classes → `StyleSheet`
- SVG globe (canvas RAF) → `react-native-svg` + `d3-geo`
- `canvas` globe → expo-gl or pure SVG via `react-native-svg`
- WebFonts (Share Tech Mono, DSEG7, VT323) → `expo-font`
- `localStorage` → `AsyncStorage`
- Mouse/touch drag → `PanResponder` or `react-native-gesture-handler`

## Screens
1. BootScreen
2. HomeScreen (Map/Globe + control panel)
3. FlightLogScreen
4. StatsScreen
