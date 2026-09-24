import React from "react";
import { AccessibilityInfo, Linking, Platform, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import Constants from "expo-constants";
import MapView, { Marker, PROVIDER_GOOGLE, type MapPressEvent } from "react-native-maps";
import { colors, fonts } from "../../../theme/trotterTheme";
import { WWIcon } from "../WorldWindowUI";
import { PlaceSymbol } from "./DreamPhoto";
import { cleanMapPoints, clusterPlaces, focusPlaceRegion, googleMapUrl, placesMapStyle, placesRegion, validMapCoordinate, type DreamPlacesMapProps, type PlaceCluster, type PlacesRegion } from "./dreamMapModel";

export function DreamPlacesMap({ points, fitKey, selectedId, placing = false, onSelect, onPlace, height = 240, overview }: DreamPlacesMapProps) {
  const configured = Constants.expoConfig?.extra?.[Platform.OS === "ios" ? "googleMapsIosConfigured" : "googleMapsAndroidConfigured"] === true;
  const clean = React.useMemo(() => cleanMapPoints(points), [points]);
  const ref = React.useRef<MapView>(null), mounted = React.useRef(true), reduceMotion = React.useRef(true);
  const [width, setWidth] = React.useState(320), [ready, setReady] = React.useState(false), [loaded, setLoaded] = React.useState(false);
  const [slow, setSlow] = React.useState(false), [attempt, setAttempt] = React.useState(0), [linkError, setLinkError] = React.useState(false);
  const [region, setRegion] = React.useState(() => placesRegion(clean, overview, width, height));
  const currentRegion = React.useRef(region), fittedKey = React.useRef<string | undefined>(undefined), selectedFromMap = React.useRef<string | undefined>(undefined), focusedPoint = React.useRef<string | undefined>(undefined);
  const fittedPointIds = React.useRef(new Set<string>()), userFramed = React.useRef(false);
  const [choices, setChoices] = React.useState<string[]>([]);
  React.useEffect(() => {
    mounted.current = true;
    void AccessibilityInfo.isReduceMotionEnabled().then(value => { if (mounted.current) reduceMotion.current = value; });
    const subscription = AccessibilityInfo.addEventListener("reduceMotionChanged", value => { reduceMotion.current = value; });
    return () => { mounted.current = false; subscription.remove(); };
  }, []);
  React.useEffect(() => {
    if (!configured || loaded) return;
    const timer = setTimeout(() => setSlow(true), 15000);
    return () => clearTimeout(timer);
  }, [configured, loaded, attempt]);
  const move = React.useCallback((next: PlacesRegion, animated: boolean) => {
    currentRegion.current = next; setRegion(next);
    if (ready) ref.current?.animateToRegion(next, animated && !reduceMotion.current ? 240 : 0);
  }, [ready]);
  // Workers resolve places independently. Keep newly arriving pins in view until
  // the user takes control; a one-time first-pin fit hid later places offscreen.
  // Coordinate refreshes never reset a camera, even when no gesture occurred.
  React.useEffect(() => {
    const key = `${fitKey}:${attempt}:${width}:${height}`;
    if (!ready || width <= 0) return;
    const newView = fittedKey.current !== key;
    if (newView) { fittedPointIds.current = new Set(); userFramed.current = false; }
    const newPin = clean.some(point => !fittedPointIds.current.has(point.id));
    for (const point of clean) fittedPointIds.current.add(point.id);
    if (!newView && (placing || userFramed.current || !newPin)) return;
    fittedKey.current = key; setChoices([]);
    move(placesRegion(clean, overview, width, height), false);
  }, [ready, fitKey, attempt, width, height, clean, overview, placing, move]);
  React.useEffect(() => {
    if (!selectedId) { focusedPoint.current = undefined; selectedFromMap.current = undefined; return; }
    if (!ready || placing) return;
    const point = clean.find(p => p.id === selectedId);
    if (!point) return;
    const key = `${point.id}:${point.lat}:${point.lon}:${Boolean(point.area)}`;
    if (focusedPoint.current === key) return;
    focusedPoint.current = key;
    userFramed.current = true;
    if (selectedFromMap.current === selectedId) { selectedFromMap.current = undefined; return; }
    move(focusPlaceRegion(point, currentRegion.current, width, height), true);
  }, [selectedId, ready, placing, clean, move, width, height]);
  const clusters = React.useMemo(() => placing ? clean.map(point => ({ id: point.id, points: [point], latitude: point.lat, longitude: point.lon })) : clusterPlaces(clean, region, width, height, selectedId), [clean, region, width, height, selectedId, placing]);
  const open = async () => {
    const url = googleMapUrl(clean.filter(p => !selectedId || p.id === selectedId), overview);
    if (!url) return;
    setLinkError(false);
    try { await Linking.openURL(url); } catch { if (mounted.current) setLinkError(true); }
  };
  const select = (cluster: PlaceCluster) => {
    userFramed.current = true;
    if (cluster.points.length === 1) {
      const point = cluster.points[0]; selectedFromMap.current = point.id; setChoices([]);
      if (placing) onPlace?.(point.lat, point.lon); else onSelect?.(point.id);
      return;
    }
    const next = placesRegion(cluster.points, undefined, width, height);
    const collocated = cluster.points.every(point => Math.abs(point.lat - cluster.points[0].lat) < 0.0001 && Math.abs(point.lon - cluster.points[0].lon) < 0.0001);
    if (collocated || next.longitudeDelta >= currentRegion.current.longitudeDelta * .9) setChoices(cluster.points.map(p => p.id));
    else { setChoices([]); move(next, true); }
  };
  const blankPress = (event: MapPressEvent) => {
    if (event.nativeEvent.action === "marker-press") return;
    const coordinate = event.nativeEvent.coordinate;
    setChoices([]); selectedFromMap.current = undefined;
    if (placing) { if (coordinate && validMapCoordinate(coordinate.latitude, coordinate.longitude)) onPlace?.(coordinate.latitude, coordinate.longitude); }
    else onSelect?.(undefined);
  };
  return <View style={s.frame}>
    <View style={s.toolbar}>
      <Pressable accessibilityRole="button" accessibilityLabel={clean.length ? "Fit saved places on map" : "Show country on map"} disabled={!configured || !ready} style={s.action}
        onPress={() => { userFramed.current = false; setChoices([]); move(placesRegion(clean, overview, width, height), true); }}>
        <WWIcon name="globe" size={15} /><Text style={s.actionText}>{clean.length ? "Fit places" : "Country view"}</Text>
      </Pressable>
      {googleMapUrl(clean, overview) && <Pressable accessibilityRole="link" accessibilityLabel="Open in Google Maps" style={s.action} onPress={() => void open()}><WWIcon name="arrow" size={17} /></Pressable>}
    </View>
    {configured ? <View style={{ height }} onLayout={event => setWidth(event.nativeEvent.layout.width)}>
      <MapView key={attempt} ref={ref} provider={PROVIDER_GOOGLE} style={StyleSheet.absoluteFill}
        initialRegion={placesRegion(clean, overview, width, height)} customMapStyle={placesMapStyle}
        showsUserLocation={false} showsMyLocationButton={false} showsCompass={false} showsBuildings={false}
        pitchEnabled={false} rotateEnabled={false} zoomControlEnabled={false} toolbarEnabled={false}
        minZoomLevel={2} maxZoomLevel={20} loadingEnabled loadingBackgroundColor={colors.paperDeep} loadingIndicatorColor={colors.ink}
        onMapReady={() => setReady(true)} onMapLoaded={() => { setLoaded(true); setSlow(false); }}
        onPanDrag={() => { userFramed.current = true; }}
        onRegionChangeComplete={(next, details) => { if (details?.isGesture) userFramed.current = true; currentRegion.current = next; setRegion(next); }}
        onPress={blankPress} onPoiClick={event => { if (placing && validMapCoordinate(event.nativeEvent.coordinate.latitude, event.nativeEvent.coordinate.longitude)) onPlace?.(event.nativeEvent.coordinate.latitude, event.nativeEvent.coordinate.longitude); else if (!placing) onSelect?.(undefined); }}>
        {clusters.map(cluster => <PlaceMarker key={JSON.stringify([cluster.id, cluster.points.some(p => p.id === selectedId), cluster.points.length === 1 ? cluster.points[0].category : undefined, cluster.points.length === 1 && Boolean(cluster.points[0].area)])} cluster={cluster} mapReady={ready} mapLoaded={loaded} selected={cluster.points.some(p => p.id === selectedId)} onPress={() => select(cluster)} />)}
      </MapView>
    </View> : <View style={[s.unavailable, { minHeight: Math.min(height, 160) }]}>
      <WWIcon name="pin" size={24} /><Text style={s.note}>Maps aren’t available in this build. Your saved places are still here.</Text>
      {placing && <Text style={s.note}>You can paste a Google Maps link in Edit details.</Text>}
    </View>}
    {slow && <View style={s.status}><Text style={s.note}>Map detail is taking longer to load. Check your connection or try again.</Text><Pressable accessibilityRole="button" onPress={() => { setReady(false); setLoaded(false); setSlow(false); fittedKey.current = undefined; setAttempt(value => value + 1); }} style={s.action}><Text style={s.actionText}>Reload map</Text></Pressable></View>}
    {!clean.length && <Text style={s.empty}>{placing ? "Tap the exact location to place your pin." : "Saved places will appear here when their locations are ready."}</Text>}
    {!placing && clean.some(point => point.area) && <Text style={s.empty}>Area markers show a general location.</Text>}
    {choices.length > 0 && <ScrollView style={s.choices} nestedScrollEnabled>
      {choices.map(id => clean.find(p => p.id === id)).filter(Boolean).map(point => point && <Pressable key={point.id} accessibilityRole="button" style={s.choice} onPress={() => { selectedFromMap.current = point.id; onSelect?.(point.id); setChoices([]); }}>
        {point.area ? <WWIcon name="globe" size={18} /> : <PlaceSymbol category={point.category ?? "unknown"} size={18} />}<Text style={s.choiceText}>{point.area ? `${point.label} · Area` : point.label}</Text>
      </Pressable>)}
    </ScrollView>}
    {linkError && <Text accessibilityRole="alert" style={s.empty}>Google Maps could not be opened.</Text>}
    {clean.some(point => point.provider === "geoapify") && <View style={s.legacyCredit}>
      <Text style={s.note}>Location data: </Text>
      <Pressable accessibilityRole="link" onPress={() => void Linking.openURL("https://www.geoapify.com/").catch(() => {})}><Text style={s.credit}>Geoapify</Text></Pressable>
      <Pressable accessibilityRole="link" onPress={() => void Linking.openURL("https://www.openstreetmap.org/copyright").catch(() => {})}><Text style={s.credit}>© OpenStreetMap</Text></Pressable>
    </View>}
  </View>;
}
function PlaceMarker({ cluster, selected, mapReady, mapLoaded, onPress }: { cluster: PlaceCluster; selected: boolean; mapReady: boolean; mapLoaded: boolean; onPress: () => void }) {
  const marker = React.useRef<React.ElementRef<typeof Marker>>(null);
  const [laidOut, setLaidOut] = React.useState(false);
  const [tracking, setTracking] = React.useState(true);
  React.useEffect(() => {
    if (!mapReady || !laidOut) return;
    // The Android marker is a native bitmap, not a live React view. Starting the
    // old timer at mount could freeze that bitmap before layout / map readiness.
    marker.current?.redraw();
    const timer = setTimeout(() => { marker.current?.redraw(); setTracking(false); }, 500);
    return () => clearTimeout(timer);
  }, [mapReady, laidOut, mapLoaded]);
  const point = cluster.points[0], count = cluster.points.length;
  return <Marker ref={marker} coordinate={{ latitude: cluster.latitude, longitude: cluster.longitude }} identifier={cluster.id}
    anchor={{ x: .5, y: .5 }} stopPropagation tracksViewChanges={tracking} zIndex={selected ? 3 : count > 1 ? 2 : 1}
    accessibilityLabel={count > 1 ? `${count} saved places, zoom or choose a place` : `${point.label}${point.area ? ", approximate area" : ""}`}
    accessibilityRole="button" onPress={event => { event.stopPropagation(); onPress(); }}>
    <View collapsable={false} onLayout={() => setLaidOut(true)} style={[s.marker, selected && s.selectedMarker, point.area && count === 1 && s.areaMarker]}>
      {count > 1 ? <Text allowFontScaling={false} style={s.count}>{count}</Text> : point.area
        ? <WWIcon name="globe" size={20} color={colors.paper} /> : <PlaceSymbol category={point.category ?? "unknown"} size={20} color={colors.paper} />}
    </View>
  </Marker>;
}
const s = StyleSheet.create({
  frame: { borderWidth: 1, borderColor: colors.paperBorder, backgroundColor: colors.paperSoft },
  toolbar: { flexDirection: "row", flexWrap: "wrap", alignItems: "center", justifyContent: "space-between", borderBottomWidth: 1, borderColor: colors.paperBorder },
  action: { minHeight: 44, minWidth: 44, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, paddingHorizontal: 12 },
  actionText: { fontFamily: fonts.sansSemi, color: colors.ink, fontSize: 12 },
  unavailable: { padding: 18, alignItems: "center", justifyContent: "center", gap: 9, backgroundColor: colors.paperDeep },
  status: { paddingHorizontal: 12, paddingTop: 10 },
  note: { fontFamily: fonts.sansRegular, color: colors.mutedInk, fontSize: 13 },
  empty: { fontFamily: fonts.sansRegular, color: colors.mutedInk, fontSize: 12, padding: 12 },
  marker: { width: 36, height: 36, borderRadius: 18, borderWidth: 2, borderColor: colors.paper, backgroundColor: colors.ink, alignItems: "center", justifyContent: "center" },
  selectedMarker: { backgroundColor: "#995e3d", borderWidth: 3 },
  areaMarker: { borderStyle: "dashed" },
  count: { fontFamily: fonts.sansSemi, color: colors.paper, fontSize: 13 },
  choices: { maxHeight: 180, borderTopWidth: 1, borderColor: colors.paperBorder },
  choice: { flexDirection: "row", alignItems: "center", minHeight: 48, padding: 12, gap: 10 },
  choiceText: { flex: 1, color: colors.ink, fontFamily: fonts.sansRegular, fontSize: 14 },
  legacyCredit: { flexDirection: "row", flexWrap: "wrap", alignItems: "center", gap: 8, paddingHorizontal: 12 },
  credit: { fontFamily: fonts.sansRegular, color: colors.mutedInk, fontSize: 12, paddingVertical: 14 },
});
