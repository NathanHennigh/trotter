const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
const { test } = require('node:test');
const root = path.join(__dirname, '../src');
function load(file, mocks = {}, extra = '', globals = {}) {
  const source = fs.readFileSync(path.join(root, file), 'utf8');
  const output = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } }).outputText;
  const module = { exports: {} };
  new Function('module', 'exports', 'require', ...Object.keys(globals), output + '\n' + extra)(module, module.exports, name => { assert(name in mocks, `Unmocked ${name}`); return mocks[name]; }, ...Object.values(globals));
  return module.exports;
}
const model = load('components/world-window/dreams/dreamMapModel.ts');
const markerManifestFile = 'assets/generated/dreamMarkerManifest.ts';
const markerAssets = Object.fromEntries([...fs.readFileSync(path.join(root, markerManifestFile), 'utf8').matchAll(/require\('([^']+)'\)/g)].map(match => [match[1], match[1]]));
const markerManifest = load(markerManifestFile, markerAssets);
const markerImages = load('components/world-window/dreams/dreamMarkerImages.ts', {
  '../../../assets/generated/dreamMarkerManifest': markerManifest, './placeSymbols': load('components/world-window/dreams/placeSymbols.ts'),
});
const presentation = load('components/world-window/dreams/dreamPresentation.ts');
const p = (id, lat, lon, extra = {}) => ({ id, label: `Saved ${id}`, lat, lon, category: 'cafe', ...extra });
const flush = async () => { for (let i = 0; i < 25; i++) await Promise.resolve(); };
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
function hooks() {
  const slots = []; let cursor = 0, effects = [];
  const same = (a, b) => a && b && a.length === b.length && a.every((v, i) => v === b[i]);
  const react = {
    createContext: () => ({}),
    useState(initial) { const i = cursor++; if (!(i in slots)) slots[i] = typeof initial === 'function' ? initial() : initial; return [slots[i], value => { slots[i] = typeof value === 'function' ? value(slots[i]) : value; }]; },
    useRef(value) { const i = cursor++; if (!(i in slots)) slots[i] = { current: value }; return slots[i]; },
    useMemo(fn, deps) { const i = cursor++; if (!slots[i] || !same(slots[i].deps, deps)) slots[i] = { value: fn(), deps }; return slots[i].value; },
    useCallback(fn, deps) { return react.useMemo(() => fn, deps); },
    useEffect(fn, deps) { const i = cursor++; if (!slots[i] || !same(slots[i].deps, deps)) { slots[i]?.cleanup?.(); slots[i] = { deps }; effects.push(() => { slots[i].cleanup = fn(); }); } },
    useReducer(fn, initial) { const [value, set] = react.useState(initial); return [value, action => set(previous => fn(previous, action))]; },
    useSyncExternalStore(_subscribe, get) { return get(); },
  };
  return { react, render(fn) { cursor = 0; const value = fn(); const pending = effects; effects = []; pending.forEach(effect => effect()); return value; }, dispose() { slots.forEach(slot => slot?.cleanup?.()); } };
}
function nodes(value, seen = new Set()) { if (!value || typeof value !== 'object' || seen.has(value)) return []; seen.add(value); return [value, ...Object.values(value).flatMap(child => nodes(child, seen))]; }
const find = (tree, type) => nodes(tree).find(node => node.type === type);
const findLabel = (tree, text) => nodes(tree).find(node => node.props?.accessibilityLabel === text);
function nativeMap(configured = true, requireNativeLayout = false) {
  const h = hooks(), moves = [], selects = [], placements = [], timers = new Map(); let hasNativeSize = false, timerId = 0, props = { points: [p('a', 38.72, -9.14)], fitKey: 'Portugal', onSelect: id => selects.push(id), onPlace: (...point) => placements.push(point) };
  const jsx = (type, props, key) => ({ type, props, key });
  const loaded = load('components/world-window/dreams/DreamPlacesMap.native.tsx', {
    react: h.react, 'react/jsx-runtime': { jsx, jsxs: jsx },
    'react-native': { View: 'View', Pressable: 'Pressable', Text: 'Text', ScrollView: 'ScrollView', Platform: { OS: 'android' }, StyleSheet: { create: x => x, absoluteFill: {} }, Linking: { openURL: async () => {} }, AccessibilityInfo: { isReduceMotionEnabled: async () => false, addEventListener: () => ({ remove() {} }) } },
    'expo-constants': { expoConfig: { extra: { googleMapsAndroidConfigured: configured } } },
    'react-native-maps': { __esModule: true, default: 'MapView', Marker: 'Marker', PROVIDER_GOOGLE: 'google' },
    '../../../theme/trotterTheme': { colors: {}, fonts: {} }, '../WorldWindowUI': { WWIcon: 'Icon' }, './DreamPhoto': { PlaceSymbol: 'PlaceSymbol' }, './dreamMapModel': model, './dreamMarkerImages': markerImages,
  }, '', { setTimeout: (fn, ms) => { const id = ++timerId; timers.set(id, { fn, ms }); return id; }, clearTimeout: id => timers.delete(id) });
  return { moves, selects, placements, timers, ...h,
    render(next = {}) { props = { ...props, ...next }; const tree = h.render(() => loaded.DreamPlacesMap(props)); const map = find(tree, 'MapView'); if (map) map.props.ref.current = { animateToRegion: (...args) => { if (requireNativeLayout && !hasNativeSize) throw new Error('IllegalStateException: Map size cannot be 0. Most likely, layout has not yet occurred'); moves.push(args); } }; return tree; },
    layout(width = 320, height = 240) { const tree = this.render(); hasNativeSize = width > 0 && height > 0; find(tree, 'MapView').props.onLayout?.({ nativeEvent: { layout: { width, height } } }); return this.render(); },
    ready() { this.layout(); let tree = this.render(); find(tree, 'MapView').props.onMapReady(); tree = this.render(); return tree; },
  };
}

test('Dreams country bounds fit the date line and preserve usable street-level one-place framing', () => {
  const crossing = model.placesRegion([p('fiji', -17.8, 179.7), p('samoa', -16.3, -179.5)], undefined, 320, 240);
  assert(crossing.longitudeDelta < 10); assert(Math.abs(crossing.longitude) > 175);
  const country = model.placesRegion([], { label: 'Fiji', bounds: [[-20, 176], [-12, 183]] });
  assert(country.longitudeDelta < 20); assert(Math.abs(country.longitude) > 175);
  const single = model.placesRegion([p('cafe', 38.7, -9.1)]);
  assert(single.latitudeDelta > 0 && single.longitudeDelta < .02);
  for (const region of [crossing, country, single, model.placesRegion([])]) assert(Object.values(region).every(Number.isFinite));
});
test('invalid geometry never becomes a pin and category clusters preserve every valid saved ID', () => {
  const points = [...Array.from({ length: 28 }, (_, i) => p(String(i), 38.7 + i * .00001, -9.1)), p('bad', NaN, 2), p('bad2', 0, 181)];
  const groups = model.clusterPlaces(points, model.placesRegion(points), 320, 248, '13');
  assert.equal(groups.flatMap(group => group.points).length, 28);
  const selected = groups.find(group => group.points.some(point => point.id === '13'));
  assert.equal(selected.selectedPoint.id, '13'); assert.equal(selected.latitude, points[13].lat);
  assert(groups.some(group => group.points.length > 1));
  assert.equal(model.cleanMapPoints([p('a', 0, 0), p('a', 2, 3)]).length, 1);
});

function clusterFixture() {
  const region = { latitude: 31.63, longitude: -7.99, latitudeDelta: .2, longitudeDelta: .2 };
  const mercator = lat => Math.log(Math.tan(Math.PI / 4 + lat * Math.PI / 360));
  const yCenter = mercator(region.latitude);
  const ySpan = mercator(region.latitude + region.latitudeDelta / 2) - mercator(region.latitude - region.latitudeDelta / 2);
  const point = (id, x, y) => p(id, (2 * Math.atan(Math.exp(yCenter + (y - 200) / 400 * ySpan)) - Math.PI / 2) * 180 / Math.PI,
    region.longitude + (x - 200) / 400 * region.longitudeDelta);
  const screen = cluster => ({
    x: model.normalizeLongitude(cluster.longitude - region.longitude) / region.longitudeDelta * 400,
    y: (mercator(cluster.latitude) - yCenter) / ySpan * 400,
  });
  return { region, point, screen, groups: (points, selectedId) => model.clusterPlaces(points, region, 400, 400, selectedId) };
}

test('nearby Marrakech pins across a grid boundary form one legible cluster', () => {
  const { point, groups } = clusterFixture();
  const points = [point('a', 42, 100), point('b', 43, 101), point('c', 45, 100), point('d', 46, 101)];
  const clusters = groups(points);
  assert.equal(clusters.length, 1, 'Adjacent grid cells must not draw overlapping count circles');
  assert.deepEqual(clusters[0].points.map(point => point.id).sort(), ['a', 'b', 'c', 'd']);
  assert.deepEqual(groups([...points].reverse()), clusters, 'An API refresh with a different order keeps the same cluster');
});

test('clustering handles transitive neighbors and collisions created by a newly merged center', () => {
  const { point, groups } = clusterFixture();
  const examples = [
    [point('a', 40, 100), point('b', 82, 100), point('c', 124, 100)],
    // A and B initially overlap. C is over 44px from either, but only 41px from their new center.
    [point('a', 166.5, 180), point('b', 209.5, 180), point('c', 188, 221)],
  ];
  for (const points of examples) {
    const clusters = groups([...points, point('far', 340, 340)]);
    assert.equal(clusters.length, 2, 'Merge until the displayed centers no longer collide, leaving distant places separate');
    assert.deepEqual(clusters.find(cluster => cluster.points.length === 3).points.map(point => point.id).sort(), ['a', 'b', 'c']);
    assert.deepEqual(clusters.find(cluster => cluster.id === 'far').points.map(point => point.id), ['far']);
  }
});

test('cluster merging preserves selected coordinates, date-line neighbors and zoomed-in individual pins', () => {
  const { region, point, groups } = clusterFixture();
  const points = [point('a', 40, 100), point('b', 82, 100), point('c', 124, 100)];
  const selected = groups(points, 'b').find(cluster => cluster.selectedPoint?.id === 'b');
  assert.equal(selected.points.length, 3, 'A selected pin cannot overlap its nearby cluster');
  assert.equal(selected.latitude, points[1].lat); assert(Math.abs(selected.longitude - points[1].lon) < 1e-10);
  const zoomed = model.clusterPlaces(points, { ...region, latitudeDelta: .05, longitudeDelta: .05 }, 400, 400);
  assert.equal(zoomed.length, 3, 'Zooming in separates places at their original coordinates');
  const crossing = model.clusterPlaces([p('east', -17, 179.99), p('west', -17, -179.999)],
    { latitude: -17, longitude: 179.99, latitudeDelta: .4, longitudeDelta: .4 }, 400, 400);
  assert.equal(crossing.length, 1); assert.equal(crossing[0].points.length, 2); assert(Math.abs(crossing[0].longitude) > 179);
});

test('selected groups retain exact coordinates and full counts without marker collisions at any display density', () => {
  const { point, screen, groups } = clusterFixture();
  const points = [point('selected', 200, 200), point('near', 220, 200), point('near-2', 223, 200),
    point('opposite', 160, 200), point('far', 330, 330), point('far-2', 345, 335)];
  const original = JSON.stringify(points), clusters = groups(points, 'selected');
  const selected = clusters.find(cluster => cluster.selectedPoint);
  assert.equal(selected.latitude, points[0].lat); assert.equal(selected.longitude, points[0].lon);
  assert.equal(selected.points.length, 4); assert.equal(clusters.length, 2);
  assert.equal(JSON.stringify(points), original, 'Clustering never displaces a saved coordinate');
  assert.deepEqual(groups([...points].reverse(), 'selected'), clusters);
  assert.deepEqual(clusters.flatMap(cluster => cluster.points.map(point => point.id)).sort(), points.map(point => point.id).sort());
  // Native layout reports logical pixels; marker artwork scales with device density.
  for (const density of [1, 1.5, 2, 3, 4]) for (let i = 0; i < clusters.length; i++) for (let j = i + 1; j < clusters.length; j++) {
    const a = screen(clusters[i]), b = screen(clusters[j]);
    assert(Math.hypot(a.x - b.x, a.y - b.y) * density >= 44 * density - 1e-6,
      `Selected and unselected circles keep clearance at ${density}x density`);
  }
  const collocated = groups([point('a', 200, 200), point('b', 200, 200), point('area', 200, 200)], 'b');
  assert.equal(collocated.length, 1); assert.equal(collocated[0].points.length, 3);
});

test('large collections preserve every place while checking only neighboring marker cells', () => {
  const { point, groups } = clusterFixture();
  const points = Array.from({ length: 10000 }, (_, i) => point(String(i), (i % 100) * 80, Math.floor(i / 100) * 80));
  const clusters = groups(points, '43');
  assert.equal(clusters.length, points.length);
  assert.equal(new Set(clusters.flatMap(cluster => cluster.points.map(point => point.id))).size, points.length);
  const selected = clusters.find(cluster => cluster.selectedPoint);
  assert.equal(selected.latitude, points[43].lat); assert.equal(selected.longitude, points[43].lon);
});

test('place selection focuses locally once while respecting a closer camera and area framing', () => {
  const venue = p('venue', 31.63, -7.99), country = { latitude: 32, longitude: -7, latitudeDelta: 5, longitudeDelta: 8 };
  const focused = model.focusPlaceRegion(venue, country, 400, 248);
  assert.equal(focused.latitude, venue.lat); assert.equal(focused.longitude, venue.lon);
  assert(focused.longitudeDelta < .02 && focused.latitudeDelta < .02, 'A list selection reveals the venue neighborhood');
  const close = { ...country, latitudeDelta: .001, longitudeDelta: .002 };
  const kept = model.focusPlaceRegion(venue, close, 400, 248);
  assert.equal(kept.latitudeDelta, close.latitudeDelta); assert.equal(kept.longitudeDelta, close.longitudeDelta);
  const area = model.focusPlaceRegion({ ...venue, area: true }, close, 400, 248);
  assert(area.latitudeDelta > .18 && area.longitudeDelta > .18, 'An area does not claim building-level precision');
});

test('town, lake and region markers frame an area without changing exact venue framing or inventing boundaries', () => {
  const venue = p('venue', 38.7, -9.1);
  const area = p('town', 38.7, -9.1, { area: true });
  const street = model.placesRegion([venue]);
  const broad = model.placesRegion([area]);
  assert(street.longitudeDelta < .02);
  assert(broad.latitudeDelta >= .18 && broad.longitudeDelta > .18);
  const selected = model.focusPlaceRegion(area, street);
  assert(selected.latitudeDelta >= broad.latitudeDelta && selected.longitudeDelta >= broad.longitudeDelta);
  const alreadyWide = { ...broad, latitudeDelta: 4, longitudeDelta: 5 };
  assert.equal(model.focusPlaceRegion(area, alreadyWide).longitudeDelta, 5, 'Selecting an area preserves a wider user camera');
  assert.equal(model.focusPlaceRegion(venue, street).longitudeDelta, street.longitudeDelta);
  const crossing = model.placesRegion([p('island', -17.8, 179.99, { area: true })]);
  assert(crossing.longitudeDelta < 2 && Math.abs(crossing.longitude) > 175);
});

test('area precision survives list and live detail mapping and opens the Google area ID instead of its centroid', async () => {
  const h = service();
  const item = h.api.mapItem({ id: 9, dream_id: 1, source_platform: 'instagram', source_url: 'https://instagram.com/reel/synthetic',
    category: 'unknown', region_or_neighborhood: 'Lake Atitlán', country: 'Guatemala', summary: '', needs_review: false,
    status: 'parsed', created_at: '2026-01-01', location_provider: 'google_places', latitude: 14.7, longitude: -91.2,
    coordinate_precision: 'area', location_place_id: 'synthetic-lake-id', location_expires_at: '2099-01-01' });
  const point = presentation.exactMapPoint(item);
  assert.equal(point.area, true); assert.equal(point.label, 'Lake Atitlán'); assert.equal(presentation.dreamLocationType(item), 'Area');
  const link = new URL(model.googleMapUrl([point]));
  assert.equal(link.searchParams.get('query_place_id'), 'synthetic-lake-id'); assert.equal(link.searchParams.get('query'), 'Lake Atitlán');
  h.respond(async () => ({ ok: true, status: 200, text: async () => JSON.stringify({ coordinate_precision: 'area', location_provider: 'google_places', location_candidates: [] }) }));
  assert.equal((await h.api.fetchDreamLocationDetails('9')).coordinatePrecision, 'area');
  h.respond(async () => ({ ok: true, status: 200, text: async () => '{}' }));
  const oldServerDetails = await h.api.fetchDreamLocationDetails('9');
  assert.equal({ ...item, ...oldServerDetails }.coordinatePrecision, 'area', 'Older detail responses cannot erase known area precision');
});
test('country map uses Google and waits for readiness before framing; selection does not repeatedly reset a panned camera', async () => {
  const h = nativeMap(); let tree = h.render(); assert.equal(find(tree, 'MapView').props.provider, 'google'); assert.equal(h.moves.length, 0);
  await flush(); tree = h.ready(); assert.equal(h.moves.length, 1);
  find(tree, 'MapView').props.onRegionChangeComplete({ latitude: 39, longitude: -8, latitudeDelta: 2, longitudeDelta: 2 });
  tree = h.render({ selectedId: 'a' }); assert.equal(h.moves.length, 2); assert.equal(h.moves[1][1], 240);
  h.render({ points: [p('a', 38.72, -9.14)] }); assert.equal(h.moves.length, 2);
  find(tree, 'MapView').props.onPress({ nativeEvent: { coordinate: { latitude: 1, longitude: 2 } } }); assert.deepEqual(h.selects, [undefined]);
  h.dispose(); assert.equal(h.timers.size, 0);
});

test('Unsorted map readiness before native layout cannot issue the crashing Android bounds command', () => {
  const h = nativeMap(true, true); let tree = h.render({ points: [], overview: undefined, fitKey: 'Unsorted' });
  find(tree, 'MapView').props.onMapReady();
  assert.doesNotThrow(() => { tree = h.render(); });
  assert.equal(h.moves.length, 0); assert.equal(findLabel(tree, 'Show country on map').props.disabled, true);
  h.layout(320, 0); assert.equal(h.moves.length, 0, 'A zero-height view is not laid out for a bounds camera');
  h.layout(320, 248); assert.equal(h.moves.length, 1);
  assert(Object.values(h.moves[0][0]).every(Number.isFinite)); h.dispose();
});
test('manual placement accepts exact valid taps without refitting after every pin move', () => {
  const h = nativeMap(); let tree = h.ready(); tree = h.render({ placing: true });
  const tap = find(tree, 'MapView').props.onPress;
  tap({ nativeEvent: { coordinate: { latitude: 38.713, longitude: -9.142 } } });
  tap({ nativeEvent: { coordinate: { latitude: NaN, longitude: 0 } } });
  assert.deepEqual(h.placements, [[38.713, -9.142]]);
  const count = h.moves.length; h.render({ points: [p('a', 38.713, -9.142)] }); assert.equal(h.moves.length, count); h.dispose();
});
test('an empty country fits newly resolved pins, then leaves coordinate updates and user pans alone', () => {
  const h = nativeMap(); h.render({ points: [], overview: { label: 'Portugal', bounds: [[36.9, -9.5], [42.2, -6.1]] } });
  let tree = h.ready(); assert.equal(h.moves.length, 1);
  const pan = { latitude: 40, longitude: -7, latitudeDelta: .2, longitudeDelta: .2 };
  find(tree, 'MapView').props.onRegionChangeComplete(pan);
  tree = h.render({ points: [p('first', 38.72, -9.14)] });
  assert.equal(h.moves.length, 2); assert(Math.abs(h.moves[1][0].latitude - 38.72) < 1e-10); assert(Math.abs(h.moves[1][0].longitude + 9.14) < 1e-10);
  find(tree, 'MapView').props.onRegionChangeComplete(pan, { isGesture: true });
  h.render({ points: [p('first', 38.721, -9.14), p('second', 41, -8)] });
  h.render({ points: [] }); h.render({ points: [p('first', 38.72, -9.14)] });
  assert.equal(h.moves.length, 2, 'Later changes, including temporary removal, must not repeatedly refit');
  h.render({ fitKey: 'France', points: [], overview: { label: 'France', bounds: [[42, -5], [51, 8]] } });
  h.render({ points: [p('paris', 48.8, 2.3)] }); assert.equal(h.moves.length, 4, 'A new country gets its own first-pin fit'); h.dispose();
});

test('separately resolved places stay visible until a user pans or selects a place', () => {
  const h = nativeMap(); h.render({ points: [] }); h.ready();
  h.render({ points: [p('marrakech', 31.63, -7.99)] });
  assert.equal(h.moves.length, 2);
  h.render({ points: [p('marrakech', 31.63, -7.99), p('agafay', 31.42, -8.27)] });
  assert.equal(h.moves.length, 3, 'A later worker result must not remain outside the first-pin camera');
  assert(h.moves.at(-1)[0].latitudeDelta > .21);
  let tree = h.render({ points: [p('marrakech', 31.631, -7.99), p('agafay', 31.42, -8.27)] });
  assert.equal(h.moves.length, 3, 'Refreshed coordinates do not move the camera');
  find(tree, 'MapView').props.onPanDrag();
  h.render({ points: [p('marrakech', 31.631, -7.99), p('agafay', 31.42, -8.27), p('fes', 34.03, -5)] });
  assert.equal(h.moves.length, 3, 'An intentional user camera is preserved');
  tree = h.render(); findLabel(tree, 'Fit saved places on map').props.onPress();
  assert.equal(h.moves.length, 4, 'The fit button includes every newly arrived pin');
  h.render({ points: [p('marrakech', 31.631, -7.99), p('agafay', 31.42, -8.27), p('fes', 34.03, -5), p('rabat', 34.02, -6.84)] });
  assert.equal(h.moves.length, 5, 'Explicitly fitting restores follow-new-places behavior'); h.dispose();
});

test('Fit saved places clears pin focus and restores all country pins with room for markers', () => {
  const points = [p('milos', 36.65, 24.32), p('parga', 39.28, 20.40), p('santorini', 36.46, 25.38), p('crete', 35.30, 24.02)];
  const h = nativeMap(); h.render({ fitKey: 'Greece', points }); h.ready();
  const overview = h.moves.at(-1)[0];
  assert.equal(h.moves.length, 1, 'A country overview should issue only its all-pins fit');
  let tree = h.render({ selectedId: 'milos' });
  assert.equal(h.moves.at(-1)[0].longitude, 24.32, 'Only an explicit selection recenters on Milos');
  findLabel(tree, 'Fit saved places on map').props.onPress();
  assert.deepEqual(h.selects, [undefined], 'Fit tells the parent to clear its selected pin');
  assert.deepEqual(h.moves.at(-1)[0], overview);
  const count = h.moves.length;
  h.render({ selectedId: undefined });
  assert.equal(h.moves.length, count, 'Clearing the selection cannot override the completed fit');
  for (const point of points) {
    const horizontalPixels = Math.abs(model.normalizeLongitude(point.lon - overview.longitude)) / overview.longitudeDelta * 320;
    assert(horizontalPixels < 160 - 22, 'Every 36-pixel marker has horizontal breathing room');
  }
  h.dispose();
});

test('a pinch gesture and selected pin preserve the map camera as more places resolve', () => {
  const h = nativeMap(); let tree = h.ready();
  find(tree, 'MapView').props.onRegionChangeComplete({ latitude: 38.72, longitude: -9.14, latitudeDelta: .1, longitudeDelta: .1 }, { isGesture: true });
  h.render({ points: [p('a', 38.72, -9.14), p('b', 40, -8)] });
  assert.equal(h.moves.length, 1);
  h.render({ fitKey: 'new', selectedId: 'a' });
  const count = h.moves.length;
  h.render({ points: [p('a', 38.72, -9.14), p('b', 40, -8), p('c', 42, -7)] });
  assert.equal(h.moves.length, count); h.dispose();
});
test('placing the first manual pin preserves the chosen street camera', () => {
  const h = nativeMap(); h.render({ points: [], placing: true }); const tree = h.ready();
  find(tree, 'MapView').props.onRegionChangeComplete({ latitude: 38.72, longitude: -9.14, latitudeDelta: .002, longitudeDelta: .002 });
  h.render({ points: [p('manual', 38.721, -9.142)] }); assert.equal(h.moves.length, 1); h.dispose();
});
test('category and area edits replace a native marker snapshot without refitting the map', () => {
  const h = nativeMap(); let tree = h.ready();
  const marker = value => nodes(value).find(node => node.props?.cluster?.points[0].id === 'a');
  const originalKey = marker(tree).key;
  tree = h.render({ points: [p('a', 38.72, -9.14, { category: 'hotel' })] }); const hotelKey = marker(tree).key;
  assert.notEqual(hotelKey, originalKey);
  tree = h.render({ points: [p('a', 38.72, -9.14, { category: 'hotel', area: true })] }); assert.notEqual(marker(tree).key, hotelKey);
  const areaKey = marker(tree).key;
  tree = h.render({ points: [p('a', 38.73, -9.15, { category: 'hotel', area: true })] }); assert.equal(marker(tree).key, areaKey, 'Position changes use the native coordinate update');
  assert.equal(h.moves.length, 1); h.dispose();
});

test('iOS custom marker snapshots wait for real layout and map readiness, then redraw after tiles load', () => {
  const h = hooks(), timers = new Map(); let timerId = 0, redraws = 0;
  const jsx = (type, props, key) => ({ type, props, key });
  const loaded = load('components/world-window/dreams/DreamPlacesMap.native.tsx', {
    react: h.react, 'react/jsx-runtime': { jsx, jsxs: jsx },
    'react-native': { View: 'View', Text: 'Text', StyleSheet: { create: value => value } },
    'expo-constants': {}, 'react-native-maps': { Marker: 'Marker' },
    '../../../theme/trotterTheme': { colors: {}, fonts: {} }, '../WorldWindowUI': {}, './DreamPhoto': { PlaceSymbol: 'PlaceSymbol' }, './dreamMapModel': model, './dreamMarkerImages': markerImages,
  }, '\nmodule.exports.PlaceMarker = SnapshotPlaceMarker;', {
    setTimeout: (fn, ms) => { const id = ++timerId; timers.set(id, { fn, ms }); return id; }, clearTimeout: id => timers.delete(id),
  });
  let props = { cluster: { id: 'a', points: [p('a', 31, -7)], latitude: 31, longitude: -7 }, selected: false, mapReady: false, mapLoaded: false, onPress() {} };
  const render = changes => { props = { ...props, ...changes }; const tree = h.render(() => loaded.PlaceMarker(props)); tree.props.ref.current = { redraw: () => redraws++ }; return tree; };
  let tree = render(); assert.equal(timers.size, 0); assert.equal(tree.props.tracksViewChanges, true);
  tree = render({ mapReady: true }); assert.equal(timers.size, 0, 'Ready before layout must not freeze a blank bitmap');
  find(tree, 'View').props.onLayout(); tree = render(); assert.equal(timers.size, 1); assert.equal(redraws, 1);
  const timer = [...timers.values()][0]; timer.fn(); tree = render(); assert.equal(redraws, 2); assert.equal(tree.props.tracksViewChanges, false);
  tree = render({ mapLoaded: true }); assert.equal(redraws, 3, 'Map/tile readiness gives an existing native marker a fresh snapshot');
  h.dispose(); assert.equal(timers.size, 0);
});

test('Android markers use complete native image descriptors instead of Fabric custom-view snapshots', () => {
  const jsx = (type, props, key) => ({ type, props, key });
  const loaded = load('components/world-window/dreams/DreamPlacesMap.native.tsx', {
    react: {}, 'react/jsx-runtime': { jsx, jsxs: jsx },
    'react-native': { Platform: { OS: 'android' }, StyleSheet: { create: value => value } },
    'expo-constants': {}, 'react-native-maps': { Marker: 'Marker' },
    '../../../theme/trotterTheme': { colors: {}, fonts: {} }, '../WorldWindowUI': {}, './DreamPhoto': {}, './dreamMapModel': model, './dreamMarkerImages': markerImages,
  }, '\nmodule.exports.PlaceMarker = PlaceMarker;');
  const variants = [
    { points: [p('cafe', 31, -7)], key: 'cafe' },
    { points: [p('area', 31, -7, { area: true })], key: 'area' },
    { points: Array.from({ length: 12 }, (_, i) => p(String(i), 31, -7)), key: 'count-12' },
    { points: Array.from({ length: 101 }, (_, i) => p(String(i), 31, -7)), key: 'count-99plus' },
  ];
  for (const { points, key } of variants) for (const selected of [false, true]) {
    let stops = 0, presses = 0;
    const marker = loaded.PlaceMarker({ cluster: { id: 'example', points, latitude: 31, longitude: -7 }, selected, mapReady: false, mapLoaded: false, onPress: () => presses++ });
    assert.equal(marker.type, 'Marker');
    assert(marker.props.image.endsWith(`/${key}${selected ? '-selected' : ''}.png`));
    assert.equal(marker.props.children, undefined, 'No React children can send Android through its fixed 100px snapshot canvas');
    assert.equal(marker.props.tracksViewChanges, false);
    assert.deepEqual(marker.props.anchor, { x: .5, y: .5 });
    assert.deepEqual(marker.props.coordinate, { latitude: 31, longitude: -7 });
    marker.props.onPress({ stopPropagation: () => stops++ });
    assert.equal(stops, 1); assert.equal(presses, 1);
    if (points.length > 1) assert(marker.props.accessibilityLabel.startsWith(`${points.length} saved places`), 'Accessible count stays exact even for 99+ artwork');
  }
});

test('bundled markers retain a transparent margin and full circular bounds at every Android density', async () => {
  const sharp = require('sharp');
  const { keys, size } = require('./buildDreamMapMarkers.cjs');
  const directory = path.join(root, '../assets/world-window/dreams/map-markers');
  for (const key of keys) for (const selected of [false, true]) for (const scale of [1, 2, 3]) {
    const filename = `${key}${selected ? '-selected' : ''}${scale > 1 ? `@${scale}x` : ''}.png`;
    const { data, info } = await sharp(path.join(directory, filename)).ensureAlpha().raw().toBuffer({ resolveWithObject: true });
    assert.equal(info.width, size * scale, filename); assert.equal(info.height, size * scale, filename);
    const alpha = (x, y) => data[(y * info.width + x) * info.channels + 3];
    for (let i = 0; i < info.width; i++) {
      assert.equal(alpha(i, 0), 0, `${filename} top margin`); assert.equal(alpha(0, i), 0, `${filename} left margin`);
      assert.equal(alpha(i, info.height - 1), 0, `${filename} bottom margin`); assert.equal(alpha(info.width - 1, i), 0, `${filename} right margin`);
    }
    const centre = 20 * scale, inset = 4 * scale;
    for (const [x, y] of [[centre, inset], [centre, info.height - inset - 1], [inset, centre], [info.width - inset - 1, centre]]) {
      assert(alpha(x, y) > 240, `${filename} circle reaches all four sides without truncation`);
    }
  }
});
test('exact overlapping places can each be selected and marker taps cannot trigger blank-map deselection', () => {
  const h = nativeMap(); h.render({ points: [p('a', 0, 0), p('b', 0, 0), p('c', 0, 0)] }); let tree = h.ready();
  const cluster = nodes(tree).find(node => node.props?.cluster?.points.length === 3); assert(cluster); cluster.props.onPress();
  tree = h.render(); assert(find(tree, 'ScrollView'));
  const choice = nodes(tree).find(node => node.type === 'Pressable' && nodes(node).some(child => child.type === 'Text' && child.props.children === 'Saved b'));
  assert(choice); choice.props.onPress(); assert.deepEqual(h.selects, ['b']);
  find(tree, 'MapView').props.onPress({ nativeEvent: { action: 'marker-press' } }); assert.deepEqual(h.selects, ['b']); h.dispose();
});
test('a selected nearby group opens choices and changing its place preserves the user camera', () => {
  const points = [p('a', 31.6300, -7.99), p('b', 31.6301, -7.99), p('c', 31.6302, -7.99), p('far', 34, -5)];
  const h = nativeMap(); h.render({ points }); h.ready(); h.render({ selectedId: 'b' });
  let tree = h.render();
  assert(h.moves.at(-1)[0].longitudeDelta < .02);
  const marker = nodes(tree).find(node => node.props?.cluster?.selectedPoint?.id === 'b');
  assert.equal(marker.props.cluster.points.length, 3);
  assert.equal(marker.props.cluster.latitude, points[1].lat);
  assert.equal(marker.props.selected, true);
  const moves = h.moves.length; marker.props.onPress(); tree = h.render();
  assert.equal(h.moves.length, moves, 'Opening nearby places does not fight the chosen camera');
  const choice = nodes(tree).find(node => node.type === 'Pressable' && nodes(node).some(child => child.type === 'Text' && child.props.children === 'Saved a'));
  choice.props.onPress(); assert.deepEqual(h.selects, ['a']);
  h.render({ selectedId: 'a' }); assert.equal(h.moves.length, moves);
  tree = h.render();
  find(tree, 'MapView').props.onRegionChangeComplete({ latitude: 31.64, longitude: -7.98, latitudeDelta: .003, longitudeDelta: .004 }, { isGesture: true });
  h.render({ points: [{ ...points[0], lat: 31.63001 }, ...points.slice(1)] });
  assert.equal(h.moves.length, moves, 'Refreshing the selected coordinates does not reset a user pan');
  h.dispose();
});

test('a collocated selected area remains one accurate marker and every saved place can be chosen', () => {
  const points = [p('area', 31.63, -7.99, { area: true }), p('b', 31.63, -7.99), p('c', 31.63, -7.99)];
  const h = nativeMap(); h.render({ points, selectedId: 'area' }); h.ready(); let tree = h.render();
  const markers = nodes(tree).filter(node => node.props?.cluster);
  assert.equal(markers.length, 1); assert.equal(markers[0].props.cluster.selectedPoint.area, true);
  assert(h.moves.at(-1)[0].latitudeDelta > .18);
  markers[0].props.onPress(); tree = h.render();
  const choices = nodes(find(tree, 'ScrollView')).filter(node => node.type === 'Pressable');
  assert.equal(choices.length, 3); assert.equal(choices.filter(choice => choice.props.accessibilityState.selected).length, 1);
  h.dispose();
});

test('web Maps links follow the selected place identity instead of the country overview', () => {
  const h = hooks(), opened = [], jsx = (type, props) => ({ type, props });
  const loaded = load('components/world-window/dreams/DreamPlacesMap.web.tsx', {
    react: h.react, 'react/jsx-runtime': { jsx, jsxs: jsx },
    'react-native': { View: 'View', Text: 'Text', Pressable: 'Pressable', StyleSheet: { create: value => value }, Linking: { openURL: async url => opened.push(url) } },
    '../../../theme/trotterTheme': { colors: {}, fonts: {} }, '../WorldWindowUI': { WWIcon: 'Icon' }, './dreamMapModel': model,
  });
  const tree = h.render(() => loaded.DreamPlacesMap({ points: [p('a', 31.63, -7.99, { googlePlaceId: 'selected-place-id' }), p('b', 34, -5)],
    selectedId: 'a', fitKey: 'Morocco', overview: { label: 'Morocco', bounds: [[28, -14], [36, -1]] } }));
  find(tree, 'Pressable').props.onPress();
  assert.equal(new URL(opened[0]).searchParams.get('query_place_id'), 'selected-place-id'); h.dispose();
});

test('missing-key and stalled-map states preserve all places and expose an intentional retry', () => {
  const missing = nativeMap(false); const tree = missing.render(); assert(!find(tree, 'MapView')); assert(findLabel(tree, 'Open in Google Maps')); missing.dispose();
  const h = nativeMap(); h.ready(); const timeout = [...h.timers.values()].find(t => t.ms === 15000); timeout.fn(); let slow = h.render();
  const retry = nodes(slow).find(node => node.type === 'Pressable' && nodes(node).some(child => child.props?.children === 'Reload map')); assert(retry); retry.props.onPress(); slow = h.ready();
  assert(nodes(slow).some(node => node.props?.cluster?.points[0].id === 'a')); h.dispose();
});
test('expired Google coordinates cannot return through a numeric Maps URL; manual/user data remains usable', () => {
  const item = { id: '1', placeName: 'Original reel title', category: 'cafe', latitude: 38.7, longitude: -9.1, googleMapsUrl: 'https://maps.google.com/?q=38.7,-9.1', locationProvider: 'google_places', locationExpiresAt: '2000-01-01' };
  assert.equal(presentation.exactMapPoint(item), undefined);
  assert(presentation.exactMapPoint({ ...item, locationExpiresAt: '2099-01-01' }));
  assert(presentation.exactMapPoint({ ...item, locationProvider: 'manual' }));
});

function service() {
  let revision = 1, token = 'synthetic-test-session'; const subscriptions = new Set(), calls = []; let response = () => Promise.resolve({ ok: true, status: 200, text: async () => '{}' });
  const api = load('services/dreams.ts', {
    'react-native': { AppState: {} }, './dreamShareOutbox': {},
    react: { createContext: () => ({}) }, './travelTrips': { getApiBaseUrl: () => 'https://synthetic.invalid', getStoredToken: () => token, hydrateStoredToken: async () => token, getAuthRevision: () => revision, subscribeAuthToken: fn => { subscriptions.add(fn); return () => subscriptions.delete(fn); }, clearAuthToken: async () => { token = undefined; } },
  }, 'module.exports.mapItem = mapApiDreamItem;', { fetch: async (url, init) => { calls.push({ url, init }); return response(url, init); } });
  return { api, calls, respond: fn => response = fn, accountChanged() { revision++; subscriptions.forEach(fn => fn()); } };
}
test('fresh Google details are owner-authenticated, uncached, attributed, and never copied into normal list records', async () => {
  const h = service(); const apiCandidate = { id: 'place-id', name: 'Fresh provider name', address: 'Fresh provider address', latitude: 38.7, longitude: -9.1, attributions: [{ display_name: 'Provider', uri: 'https://provider.invalid' }] };
  h.respond(async () => ({ ok: true, status: 200, text: async () => JSON.stringify({ location_provider: 'google_places', location_candidates: [apiCandidate], location_attributions: apiCandidate.attributions, location_expires_at: '2099-01-01' }) }));
  const details = await h.api.fetchDreamLocationDetails('9');
  assert(h.calls[0].url.endsWith('/dream-items/9/location-details')); assert.equal(h.calls[0].init.cache, 'no-store'); assert.equal(h.calls[0].init.headers.Authorization, 'Bearer synthetic-test-session');
  assert.equal(details.locationCandidates[0].attributions[0].displayName, 'Provider');
  assert.equal(h.calls[0].init.headers['X-Trotter-Maps'], 'google');
  const item = h.api.mapItem({ id: 9, dream_id: 1, source_platform: 'instagram', source_url: 'https://instagram.com/reel/synthetic', category: 'cafe', place_name: 'Original title', summary: '', needs_review: false, status: 'confirmed', created_at: '2026-01-01', location_provider: 'google_places', latitude: 38.7, longitude: -9.1, location_expires_at: '2000-01-01', location_address: 'Do not retain', location_candidates: [apiCandidate] });
  assert.equal(item.placeName, 'Original title'); assert.equal(item.latitude, undefined); assert.equal(item.locationAddress, undefined); assert.deepEqual(item.locationCandidates, []);
});
test('leaving a detail view or changing account aborts a pending provider request instead of accepting its late content', async () => {
  const h = service(), wait = deferred(); h.respond(() => wait.promise); const abort = new AbortController();
  const task = h.api.fetchDreamLocationDetails('9', abort.signal); await flush(); abort.abort();
  await assert.rejects(task, /cancelled/); assert.equal(h.calls[0].init.signal.aborted, true);
  const task2 = h.api.fetchDreamLocationDetails('10'); await flush(); h.accountChanged(); await assert.rejects(task2, /account changed/);
  wait.resolve({ ok: true, status: 200, text: async () => '{}' }); await flush();
});
test('live detail hook does not poll provider data, discards old view/account content, and retries after failure', async () => {
  const h = hooks(), calls = []; let revision = 1;
  const hook = load('components/world-window/dreams/useLiveDreamLocation.ts', { react: h.react,
    '../../../services/dreams': { fetchDreamLocationDetails: (id, signal) => { const wait = deferred(); calls.push({ id, signal, ...wait }); return wait.promise; } },
    '../../../services/travelTrips': { getAuthRevision: () => revision, subscribeAuthToken: () => () => {} } });
  const item = { id: '1', locationProvider: 'google_places', locationPlaceId: 'chosen', locationStatus: 'resolved' };
  const render = (value = item) => h.render(() => hook.useLiveDreamLocation(value));
  render(); assert.equal(calls.length, 1); calls[0].resolve({ locationAddress: 'Fresh', locationCandidates: [] }); await flush(); assert.equal(render().details.locationAddress, 'Fresh');
  render({ ...item, updatedAt: 'a-new-poll' }); assert.equal(calls.length, 1);
  revision++; assert.equal(render().details, undefined); assert(calls[0].signal.aborted); assert.equal(calls.length, 2);
  calls[1].reject(new Error('Offline')); await flush(); const failed = render(); assert.equal(failed.error, 'Offline'); failed.retry(); render(); assert.equal(calls.length, 3);
  h.dispose(); assert(calls[2].signal.aborted); calls[2].resolve({ locationAddress: 'Late content' }); await flush();
});

test('structured source and recovery states survive API mapping without copying provider content or changing country', () => {
  const h = service();
  const item = h.api.mapItem({ id: 91, dream_id: 8, source_platform: 'instagram', source_url: 'https://instagram.com/reel/synthetic',
    category: 'hotel', country: 'Greece', summary: 'A holiday stay.', needs_review: true, status: 'needs_review',
    created_at: '2026-01-01', location_state: 'source_details', location_reason: 'creator_link_required',
    location_hint: 'Open the reel for the creator’s instructions.', location_retry_at: null, processing_retry_at: null,
    location_provider: 'google_places', location_address: 'Never store this', location_candidates: [] });
  assert.equal(item.country, 'Greece'); assert.equal(item.locationState, 'source_details');
  assert.equal(item.locationReason, 'creator_link_required'); assert.equal(item.locationHint, 'Open the reel for the creator’s instructions.');
  assert.equal(item.locationRetryAt, undefined); assert.equal(item.locationAddress, undefined);
  const deferred = h.api.mapItem({ id: 92, dream_id: 8, source_platform: 'instagram', source_url: 'https://instagram.com/reel/synthetic',
    category: 'unknown', summary: '', needs_review: true, status: 'failed', created_at: '2026-01-01',
    location_state: 'unavailable', location_reason: 'provider_unavailable', location_retry_at: '2026-10-21T12:00:00Z', processing_retry_at: '2026-10-21T13:00:00Z' });
  assert.equal(deferred.locationRetryAt, '2026-10-21T12:00:00Z'); assert.equal(deferred.processingRetryAt, '2026-10-21T13:00:00Z');
});

test('source omissions, unresolved matches and deferred lookups never request live Google venue details', () => {
  const h = hooks(), calls = [];
  const hook = load('components/world-window/dreams/useLiveDreamLocation.ts', { react: h.react,
    '../../../services/dreams': { fetchDreamLocationDetails: (id, signal) => { calls.push({ id, signal }); return new Promise(() => {}); } },
    '../../../services/travelTrips': { getAuthRevision: () => 1, subscribeAuthToken: () => () => {} } });
  const item = { id: '91', locationProvider: 'google_places', locationStatus: 'not_found' };
  for (const state of ['source_details', 'unresolved', 'processing', 'unavailable']) {
    const view = h.render(() => hook.useLiveDreamLocation({ ...item, locationState: state }));
    assert(!view.loading); assert.equal(calls.length, 0);
  }
  h.render(() => hook.useLiveDreamLocation({ ...item, locationState: 'place', locationStatus: 'resolved', locationPlaceId: 'verified-id' }));
  assert.equal(calls.length, 1, 'A later verified pin keeps normal live address and attribution loading');
  h.render(() => hook.useLiveDreamLocation({ ...item, locationState: 'source_details' }));
  assert(calls[0].signal.aborted); h.dispose();
});

test('a verified Google identity refreshes expired details but never rehydrates absent or deferred identities', async () => {
  const h = hooks(), calls = [];
  const hook = load('components/world-window/dreams/useLiveDreamLocation.ts', { react: h.react,
    '../../../services/dreams': { fetchDreamLocationDetails: (id, signal) => { const wait = deferred(); calls.push({ id, signal, ...wait }); return wait.promise; } },
    '../../../services/travelTrips': { getAuthRevision: () => 1, subscribeAuthToken: () => () => {} } });
  const item = { id: '91', locationProvider: 'google_places', locationStatus: 'resolved',
    locationState: 'unavailable', locationReason: 'location_unavailable', locationPlaceId: 'verified-id', locationExpiresAt: '2020-01-01' };
  h.render(() => hook.useLiveDreamLocation(item)); assert.equal(calls.length, 1);
  calls[0].resolve({ locationStatus: 'resolved', locationPlaceId: 'verified-id', locationCandidates: [{ id: 'verified-id', latitude: 36, longitude: 24 }], locationExpiresAt: '2099-01-01' });
  await flush(); assert.equal(h.render(() => hook.useLiveDreamLocation(item)).details.locationCandidates[0].latitude, 36);
  h.render(() => hook.useLiveDreamLocation({ ...item, locationPlaceId: undefined })); assert.equal(calls.length, 1);
  h.render(() => hook.useLiveDreamLocation({ ...item, locationRetryAt: '2099-01-01' })); assert.equal(calls.length, 1);
  h.render(() => hook.useLiveDreamLocation({ ...item, locationStatus: 'not_found' })); assert.equal(calls.length, 1);
  h.dispose();
});

test('an explicit retry queues a failed authoritative sorting job even if the item status is stale',async()=>{
 for(const sortingState of ['failed','unavailable','sorted']){
  const h=hooks(),queued=[];let first=true;
  const originalState=h.react.useState;
  h.react.useState=initial=>{const value=first?[{id:'33',dreamId:'1',sourceUrl:'https://www.instagram.com/reel/retry/',category:'cafe',summary:'',tags:[],status:'processing',sortingState,needsReview:false}]:initial;first=false;return originalState(value)};
  // Mount only the store's event handlers; background account/polling effects are independent.
  h.react.useEffect=()=>{};
  const api=load('services/dreams.ts',{
   react:h.react,'react-native':{AppState:{currentState:'active'}},
   './travelTrips':{useTravelTrips:()=>({accountId:1,authStatus:'signed-in'}),getApiBaseUrl:()=> 'https://synthetic.invalid',getStoredToken:()=> 'synthetic-token',getAuthRevision:()=>1},
   './dreamShareOutbox':{canonicalDreamShareUrl:()=> 'https://www.instagram.com/reel/retry/',dreamShareOutbox:{enqueue:async(owner,share)=>{queued.push(share);return {...share,id:'pending-33',status:'queued'}},list:async()=>[]}},
  },'module.exports.useStateForTest=useDreamsState;');
  const store=h.render(()=>api.useStateForTest());
  await store.shareInstagramLinkDurable('https://www.instagram.com/reel/retry/');await flush();
  if(sortingState==='sorted')assert.equal(queued.length,0);
  else{assert.equal(queued.length,1);assert.equal(queued[0].retryItemId,'33');}
  h.dispose();
 }
});
