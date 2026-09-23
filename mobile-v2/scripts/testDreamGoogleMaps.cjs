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
function nativeMap(configured = true) {
  const h = hooks(), moves = [], selects = [], placements = [], timers = new Map(); let timerId = 0, props = { points: [p('a', 38.72, -9.14)], fitKey: 'Portugal', onSelect: id => selects.push(id), onPlace: (...point) => placements.push(point) };
  const jsx = (type, props, key) => ({ type, props, key });
  const loaded = load('components/world-window/dreams/DreamPlacesMap.native.tsx', {
    react: h.react, 'react/jsx-runtime': { jsx, jsxs: jsx },
    'react-native': { View: 'View', Pressable: 'Pressable', Text: 'Text', ScrollView: 'ScrollView', Platform: { OS: 'android' }, StyleSheet: { create: x => x, absoluteFill: {} }, Linking: { openURL: async () => {} }, AccessibilityInfo: { isReduceMotionEnabled: async () => false, addEventListener: () => ({ remove() {} }) } },
    'expo-constants': { expoConfig: { extra: { googleMapsAndroidConfigured: configured } } },
    'react-native-maps': { __esModule: true, default: 'MapView', Marker: 'Marker', PROVIDER_GOOGLE: 'google' },
    '../../../theme/trotterTheme': { colors: {}, fonts: {} }, '../WorldWindowUI': { WWIcon: 'Icon' }, './DreamPhoto': { PlaceSymbol: 'PlaceSymbol' }, './dreamMapModel': model,
  }, '', { setTimeout: (fn, ms) => { const id = ++timerId; timers.set(id, { fn, ms }); return id; }, clearTimeout: id => timers.delete(id) });
  return { moves, selects, placements, timers, ...h,
    render(next = {}) { props = { ...props, ...next }; const tree = h.render(() => loaded.DreamPlacesMap(props)); const map = find(tree, 'MapView'); if (map) map.props.ref.current = { animateToRegion: (...args) => moves.push(args) }; return tree; },
    ready() { let tree = this.render(); find(tree, 'MapView').props.onMapReady(); tree = this.render(); return tree; },
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
  assert.equal(groups.find(group => group.points.some(point => point.id === '13')).points.length, 1);
  assert(groups.some(group => group.points.length > 1));
  assert.equal(model.cleanMapPoints([p('a', 0, 0), p('a', 2, 3)]).length, 1);
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
test('manual placement accepts exact valid taps without refitting after every pin move', () => {
  const h = nativeMap(); let tree = h.ready(); tree = h.render({ placing: true });
  const tap = find(tree, 'MapView').props.onPress;
  tap({ nativeEvent: { coordinate: { latitude: 38.713, longitude: -9.142 } } });
  tap({ nativeEvent: { coordinate: { latitude: NaN, longitude: 0 } } });
  assert.deepEqual(h.placements, [[38.713, -9.142]]);
  const count = h.moves.length; h.render({ points: [p('a', 38.713, -9.142)] }); assert.equal(h.moves.length, count); h.dispose();
});
test('an empty country fits its first resolved pin once, then leaves ordinary point updates and user pans alone', () => {
  const h = nativeMap(); h.render({ points: [], overview: { label: 'Portugal', bounds: [[36.9, -9.5], [42.2, -6.1]] } });
  let tree = h.ready(); assert.equal(h.moves.length, 1);
  const pan = { latitude: 40, longitude: -7, latitudeDelta: .2, longitudeDelta: .2 };
  find(tree, 'MapView').props.onRegionChangeComplete(pan);
  tree = h.render({ points: [p('first', 38.72, -9.14)] });
  assert.equal(h.moves.length, 2); assert(Math.abs(h.moves[1][0].latitude - 38.72) < 1e-10); assert(Math.abs(h.moves[1][0].longitude + 9.14) < 1e-10);
  find(tree, 'MapView').props.onRegionChangeComplete(pan);
  h.render({ points: [p('first', 38.721, -9.14), p('second', 41, -8)] });
  h.render({ points: [] }); h.render({ points: [p('first', 38.72, -9.14)] });
  assert.equal(h.moves.length, 2, 'Later changes, including temporary removal, must not repeatedly refit');
  h.render({ fitKey: 'France', points: [], overview: { label: 'France', bounds: [[42, -5], [51, 8]] } });
  h.render({ points: [p('paris', 48.8, 2.3)] }); assert.equal(h.moves.length, 4, 'A new country gets its own first-pin fit'); h.dispose();
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
test('exact overlapping places can each be selected and marker taps cannot trigger blank-map deselection', () => {
  const h = nativeMap(); h.render({ points: [p('a', 0, 0), p('b', 0, 0), p('c', 0, 0)] }); let tree = h.ready();
  const cluster = nodes(tree).find(node => node.props?.cluster?.points.length === 3); assert(cluster); cluster.props.onPress();
  tree = h.render(); assert(find(tree, 'ScrollView'));
  const choice = nodes(tree).find(node => node.type === 'Pressable' && nodes(node).some(child => child.type === 'Text' && child.props.children === 'Saved b'));
  assert(choice); choice.props.onPress(); assert.deepEqual(h.selects, ['b']);
  find(tree, 'MapView').props.onPress({ nativeEvent: { action: 'marker-press' } }); assert.deepEqual(h.selects, ['b']); h.dispose();
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
