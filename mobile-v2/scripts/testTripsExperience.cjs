// Offline component behaviors with synthetic trips; no account, server or device.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
const { test } = require('node:test');
const root = path.join(__dirname, '../src');
const noop = () => {};
const flush = async () => { for (let i = 0; i < 30; i++) await Promise.resolve(); };
function load(file, mocks = {}) {
  const module = { exports: {} };
  const code = ts.transpileModule(fs.readFileSync(path.join(root, file), 'utf8'), { compilerOptions: { jsx: ts.JsxEmit.React, module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, esModuleInterop: true } }).outputText;
  new Function('module', 'exports', 'require', code)(module, module.exports, name => { assert(name in mocks, `Unexpected dependency: ${name}`); return mocks[name]; });
  return module.exports;
}
const presentation = load('components/world-window/trips/tripPresentation.ts');
const scope = load('utils/travelScope.ts');
const palette = { paperSoft: '#faf8f2', paper: '#f7f5ed', ink: '#31576b' };
function host(file, name, options = {}) {
  const slots = []; let cursor = 0, effects = [], props;
  const same = (a, b) => a && b && a.length === b.length && a.every((v, i) => v === b[i]);
  const react = {
    Fragment: 'Fragment', createElement: (type, props, ...children) => ({ type, props: { ...props, children } }),
    useState(initial) { const i = cursor++; if (!(i in slots)) slots[i] = typeof initial === 'function' ? initial() : initial; return [slots[i], value => { slots[i] = typeof value === 'function' ? value(slots[i]) : value; }]; },
    useRef(value) { const i = cursor++; if (!(i in slots)) slots[i] = { current: value }; return slots[i]; },
    useId: () => ':offline-id:',
    useMemo(fn, deps) { const i = cursor++; if (!slots[i] || !same(slots[i].deps, deps)) slots[i] = { value: fn(), deps }; return slots[i].value; },
    useEffect(fn, deps) { const i = cursor++; if (!slots[i] || !same(slots[i].deps, deps)) { slots[i]?.cleanup?.(); slots[i] = { deps }; effects.push(() => { slots[i].cleanup = fn(); }); } },
  };
  const tags = 'FlatList RefreshControl View Text Pressable TextInput ActivityIndicator'.split(' ');
  const native = { ...Object.fromEntries(tags.map(tag => [tag, tag])), Animated: { View: 'AnimatedView' }, Platform: { OS: options.platform ?? 'android' }, StyleSheet: { create: x => x }, useWindowDimensions: () => ({ width: options.width ?? 410, height: 880, fontScale: options.fontScale ?? 1 }) };
  const ui = Object.fromEntries('WWHeader WWButton WWEmpty WWIcon WWEmblem'.split(' ').map(tag => [tag, tag]));
  const wallet = { WalletCover: 'WalletCover', WalletHeading: 'WalletHeading', walletColors: palette };
  const motion = { PressFeedback: 'Pressable', useReducedMotion: () => options.reducedMotion !== false };
  const theme = { colors: palette, fonts: {}, layout: { bottomNavHeight: 68 } };
  const mocks = {
    react, 'react-native': native,
    'react-native-svg': Object.fromEntries('default Svg Defs Line LinearGradient Rect Stop Circle Pattern'.split(' ').map(tag => [tag, tag])),
    'react-native-safe-area-context': { useSafeAreaInsets: () => ({ top: 24, bottom: 20 }) },
    '../components/trotter/TrotterKit': { BottomNav: 'BottomNav' },
    '../components/world-window/WorldWindowUI': ui, '../WorldWindowUI': ui,
    '../components/world-window/motion': motion, '../motion': motion,
    '../components/world-window/trips/WalletCover': wallet, './WalletCover': wallet,
    '../components/world-window/trips/BoardingPass': { BoardingPass: 'BoardingPass' },
    '../components/world-window/trips/TripAtlas': { TripAtlas: 'TripAtlas' },
    '../components/world-window/trips/tripPresentation': presentation, './tripPresentation': presentation,
    '../utils/travelScope': scope,
    '../services/travelTrips': { useTravelTrips: () => ({ trips: [], status: 'idle', refresh: async () => {}, loadTripDetail: async () => undefined, ...options.service }) },
    '../theme/trotterTheme': theme, '../../../theme/trotterTheme': theme,
    '../displayTextFit': { fitDisplayFont: (...args) => { options.fitArgs?.push(args); return args[1]; } },
    '../../../utils/mobileLayout': { getMobileVisualWidth: width => options.platform === 'web' ? Math.min(globalThis.innerWidth ?? width, 430) : width },
    '../AirlineLogo': { AirlineLogo: 'AirlineLogo', airlineName: code => code },
  };
  const Component = load(file, mocks)[name];
  return {
    render(next = props) { props = next; cursor = 0; const tree = Component(props); const pending = effects; effects = []; pending.forEach(fn => fn()); return tree; },
    dispose() { slots.forEach(slot => slot?.cleanup?.()); },
  };
}
function nodes(value, seen = new Set()) {
  if (!value || typeof value !== 'object' || seen.has(value)) return [];
  seen.add(value); return [value, ...Object.values(value).flatMap(child => nodes(child, seen))];
}
const find = (tree, type) => nodes(tree).find(node => node.type === type);
const button = (tree, label) => nodes(tree).find(node => node.props?.label === label || node.props?.accessibilityLabel === label);
const texts = tree => nodes(tree).filter(node => node.type === 'Text').map(node => node.props.children.flat().filter(value => typeof value !== 'object').join(''));
const segment = (id, depTime, arrTime, depAirport, arrAirport) => ({ id, depTime, arrTime, depAirport, arrAirport, airline: 'UA', flightNumber: '10', distanceMiles: 100, depPoint: { code: depAirport, city: depAirport, lat: 20, lon: 10 }, arrPoint: { code: arrAirport, city: arrAirport, lat: 30, lon: 20 } });
const earlier = segment('old', '2025-12-31T23:30:00-06:00', '2026-01-01T09:00:00+00:00', 'IAH', 'LHR');
const later = segment('new', '2026-01-08T11:00:00+00:00', '2026-01-08T17:00:00-06:00', 'LHR', 'IAH');
const trip = { id: 'trip-1', title: 'London', city: 'London', country: 'United Kingdom', airportCode: 'LHR', startDate: '2025-12-31', endDate: '2026-01-08', routeLabel: 'IAH to LHR', flightCount: 2, miles: 200, airlineCount: 1, airports: ['IAH', 'LHR'], airlines: ['UA'], segments: [earlier, later] };
// Tests feed page bounds; deliberately different local offsets must never become the popup origin.
function rootMeasurement(callbacks) {
  return { measure: callback => callbacks.push((pageX, pageY, width, height) => callback(999, 777, width, height, pageX, pageY)),
    measureInWindow: () => assert.fail('Window coordinates apply a status-bar offset and must not drive the popup') };
}



test('all wallet targets capture the whole stable wallet before release and open synchronously', () => {
  const opened = [], callbacks = [], bounds = [20, 310, 370, 260];
  const h = host('components/world-window/trips/WalletCover.tsx', 'WalletCover');
  const tree = h.render({ trip, onPress: (...args) => opened.push(args) });
  tree.props.ref.current = rootMeasurement(callbacks);
  assert.equal(tree.props.collapsable, false);
  const targets = nodes(tree).filter(node => node.type === 'Pressable');
  assert(targets.length >= 3);
  targets.forEach((node, index) => {
    node.props.onPressIn({ nativeEvent: { pageX: 100, pageY: 400 } });
    callbacks[index](...bounds);
    node.props.onPress();
    assert.equal(opened.length, index + 1);
  });
  assert.deepEqual(opened, targets.map(() => [{ x: 20, y: 310, width: 370, height: 260,
    wallet: { trip, scopeYear: undefined, totalFlightCount: undefined } }]));
  h.dispose(); targets[0].props.onPress(); assert.equal(opened.length, targets.length);
});

test('native origin uses React-root page coordinates without the Android visible-window inset', () => {
  for (const platform of ['android', 'ios']) {
    const opened = [], callbacks = [];
    const h = host('components/world-window/trips/WalletCover.tsx', 'WalletCover', { platform, width: 420 });
    const tree = h.render({ trip, onPress: origin => opened.push(origin) });
    let windowMeasurements = 0;
    tree.props.ref.current = {
      measure: callback => callbacks.push(callback),
      measureInWindow: callback => { windowMeasurements++; callback(20, 251 + 1 / 3, 380, 254); },
    };
    const target = nodes(tree).find(node => node.type === 'Pressable');
    target.props.onPressIn();
    callbacks.shift()(0, 0, 380, 254, 20, 305 + 1 / 3);
    target.props.onPress();
    assert.equal(windowMeasurements, 0);
    assert.equal(opened[0].x, 20); assert.equal(opened[0].y, 305 + 1 / 3);
    assert.equal(opened[0].width, 380); assert.equal(opened[0].height, 254);
    h.dispose();
  }
});

test('web origin removes only the centered app-root inset and remains unchanged on a phone viewport', () => {
  const previousWidth = globalThis.innerWidth;
  try {
    for (const viewport of [1200, 320]) {
      globalThis.innerWidth = viewport;
      const opened = [], callbacks = [], rootLeft = Math.max(0, (viewport - 430) / 2);
      const h = host('components/world-window/trips/WalletCover.tsx', 'WalletCover', { platform: 'web', width: viewport });
      const tree = h.render({ trip, onPress: origin => opened.push(origin) });
      tree.props.ref.current = rootMeasurement(callbacks);
      const target = nodes(tree).find(node => node.type === 'Pressable');
      target.props.onPressIn(); callbacks.shift()(rootLeft + 20, 310, Math.min(viewport, 430) - 40, 254);
      target.props.onPress();
      assert.equal(opened[0].x, 20); assert.equal(opened[0].y, 310); h.dispose();
    }
  } finally {
    if (previousWidth === undefined) delete globalThis.innerWidth; else globalThis.innerWidth = previousWidth;
  }
});

test('a fast press uses a fresh layout fallback but never waits for or navigates from a measurement callback', () => {
  const opened = [], callbacks = [];
  const h = host('components/world-window/trips/WalletCover.tsx', 'WalletCover');
  const tree = h.render({ trip, onPress: origin => opened.push(origin) });
  tree.props.ref.current = rootMeasurement(callbacks);
  const target = nodes(tree).find(node => node.type === 'Pressable');
  tree.props.onLayout(); callbacks.shift()(20, 310, 370, 260);
  target.props.onPressIn(); target.props.onPress();
  assert.equal(opened.length, 1); assert.equal(opened[0].y, 310);
  callbacks.shift()(20, 99, 370, 260); assert.equal(opened.length, 1);
  target.props.onPressIn(); target.props.onPress();
  assert.equal(opened.length, 2); assert.equal(opened[1], undefined);
  callbacks.shift()(20, 120, 370, 260); assert.equal(opened.length, 2); h.dispose();
});

test('source callbacks reject zero/nonfinite/expired bounds and an unmounted wallet', () => {
  const originalNow = Date.now; let now = 1000; Date.now = () => now;
  try {
    const opened = [], callbacks = [];
    const h = host('components/world-window/trips/WalletCover.tsx', 'WalletCover');
    const tree = h.render({ trip, onPress: origin => opened.push(origin) });
    tree.props.ref.current = rootMeasurement(callbacks);
    const target = nodes(tree).find(node => node.type === 'Pressable');
    for (const bounds of [[20, 310, 0, 260], [NaN, 310, 370, 260], [20, 310, 370, -10]]) {
      target.props.onPressIn(); callbacks.shift()(...bounds); target.props.onPress();
      assert.equal(opened.at(-1), undefined);
    }
    target.props.onPressIn(); callbacks.shift()(20, 310, 370, 260); now += 251;
    target.props.onPress(); assert.equal(opened.at(-1), undefined);
    target.props.onPressIn(); now += 251; callbacks.shift()(20, 310, 370, 260);
    target.props.onPress(); assert.equal(opened.at(-1), undefined);
    target.props.onPressIn(); h.dispose(); callbacks.shift()(20, 310, 370, 260);
    const count = opened.length; target.props.onPress(); assert.equal(opened.length, count);
  } finally { Date.now = originalNow; }
});

test('scroll movement and newer presses invalidate stale source positions without reacting to tap jitter', () => {
  const opened = [], callbacks = [];
  const h = host('components/world-window/trips/WalletCover.tsx', 'WalletCover');
  const tree = h.render({ trip, onPress: origin => opened.push(origin) });
  tree.props.ref.current = rootMeasurement(callbacks);
  const target = nodes(tree).find(node => node.type === 'Pressable');
  target.props.onPressIn({ nativeEvent: { pageX: 100, pageY: 400 } });
  callbacks.shift()(20, 310, 370, 260);
  tree.props.onTouchMove({ nativeEvent: { pageX: 102, pageY: 402 } });
  target.props.onPress(); assert.equal(opened.at(-1).y, 310);
  target.props.onPressIn({ nativeEvent: { pageX: 100, pageY: 400 } });
  tree.props.onTouchMove({ nativeEvent: { pageX: 100, pageY: 440 } });
  callbacks.shift()(20, 310, 370, 260); target.props.onPress(); assert.equal(opened.at(-1), undefined);
  target.props.onPressIn(); target.props.onPressIn();
  callbacks[1](20, 140, 370, 260); callbacks[0](20, 300, 370, 260);
  target.props.onPress(); assert.equal(opened.at(-1).y, 140); h.dispose();
});

test('source capture preserves the current scoped wallet and ignores callbacks for replaced trip content', () => {
  const opened = [], callbacks = [];
  const h = host('components/world-window/trips/WalletCover.tsx', 'WalletCover');
  const onPress = origin => opened.push(origin);
  let tree = h.render({ trip, onPress });
  tree.props.ref.current = rootMeasurement(callbacks);
  nodes(tree).find(node => node.type === 'Pressable').props.onPressIn();
  const scoped = scope.scopeTripsToYear([trip], '2026')[0];
  tree = h.render({ trip: scoped, scopeYear: '2026', totalFlightCount: 2, onPress });
  callbacks.shift()(20, 310, 370, 260);
  const target = nodes(tree).find(node => node.type === 'Pressable');
  target.props.onPress(); assert.equal(opened.at(-1), undefined);
  target.props.onPressIn(); callbacks.shift()(20, 310, 370, 260); target.props.onPress();
  assert.strictEqual(opened.at(-1).wallet.trip, scoped);
  assert.equal(opened.at(-1).wallet.scopeYear, '2026'); assert.equal(opened.at(-1).wallet.totalFlightCount, 2);
  assert.deepEqual(trip.segments, [earlier, later]); h.dispose();
});

test('popup and source headings have identical usable text widths while respecting actual wallet insets', () => {
  const fitArgs = [], h = host('components/world-window/trips/WalletCover.tsx', 'WalletHeading', { width: 420, fitArgs });
  h.render({ trip, compact: true, availableWidth: 376 });
  assert.equal(fitArgs.at(-1)[2], 338);
  h.render({ trip, availableWidth: 376 }); assert.equal(fitArgs.at(-1)[2], 332);
  h.render({ trip, compact: true }); const sourceWidth = fitArgs.at(-1)[2];
  h.render({ trip, compact: true, availableWidth: 380 }); assert.equal(fitArgs.at(-1)[2], sourceWidth);
  h.render({ trip }); assert.equal(fitArgs.at(-1)[2], 336); h.dispose();
});

test('year scope counts departure-year legs but opens the preserved complete trip', () => {
  const opened = [], h = host('screens/TripsListScreen.tsx', 'TripsListScreen', { service: { trips: [trip] } });
  const props = { active: 'trips', onChange: noop, onOpenTrip: (...args) => opened.push(args), initialYear: '2026', scopeEpoch: 1 };
  h.render(props); const tree = h.render(); const list = find(tree, 'FlatList');
  assert.equal(list.props.data.length, 1); assert.deepEqual(list.props.data[0].segments, [later]);
  const wallet = find(list.props.renderItem({ item: list.props.data[0], index: 0 }), 'WalletCover');
  assert.equal(wallet.props.trip.flightCount, 1); assert.equal(wallet.props.totalFlightCount, 2); assert.equal(wallet.props.scopeYear, '2026');
  const origin = { x: 0, y: 100, width: 400, height: 250 }; wallet.props.onPress(origin);
  assert.strictEqual(opened[0][0], trip); assert.equal(opened[0][1], undefined); assert.equal(opened[0][2], origin);
  assert.deepEqual(trip.segments, [earlier, later]); h.dispose();
});

test('retained Trips keeps search until an explicit scope epoch changes and All years clears the scope', () => {
  let clears = 0;
  const h = host('screens/TripsListScreen.tsx', 'TripsListScreen', { service: { trips: [trip] } });
  const props = { active: 'trips', onChange: noop, initialYear: '2026', scopeEpoch: 1, onClearYear: () => clears++ };
  h.render(props); let tree = h.render();
  find(tree, 'TextInput').props.onChangeText('No such city'); tree = h.render();
  assert.equal(find(tree, 'FlatList').props.data.length, 0);
  tree = h.render(props); assert.equal(find(tree, 'TextInput').props.value, 'No such city');
  h.render({ ...props, scopeEpoch: 2 }); tree = h.render(); assert.equal(find(tree, 'TextInput').props.value, '');
  const all = nodes(tree).find(node => node.props?.accessibilityRole === 'tab' && texts(node).some(value => value.startsWith('All years')));
  all.props.onPress(); tree = h.render(); assert.equal(clears, 1); assert.equal(find(tree, 'FlatList').props.data[0].segments.length, 2);
  h.dispose();
});

test('scoped wallet announces the same dates and counts as its preview', () => {
  const h = host('components/world-window/trips/WalletCover.tsx', 'WalletCover');
  const scoped = scope.scopeTripsToYear([trip], '2026')[0];
  const tree = h.render({ trip: scoped, scopeYear: '2026', totalFlightCount: 2, onPress: noop });
  const heading = nodes(tree).find(node => typeof node.type === 'function');
  assert.equal(heading.props.trip.startDate, '2026-01-08'); assert.equal(heading.props.trip.endDate, '2026-01-08');
  const opener = nodes(tree).find(node => node.type === 'Pressable');
  assert(opener.props.accessibilityLabel.includes('8 Jan 2026')); assert(!opener.props.accessibilityLabel.includes('2025'));
  assert(texts(tree).some(value => value.includes('1 flight in 2026') && value.includes('2 in full itinerary'))); h.dispose();
});

test('Trip Back stays outside scrolling content and empty details have a working retry', async () => {
  let calls = 0, backs = 0;
  const h = host('screens/TripDetailScreen.tsx', 'TripDetailScreen', { service: { loadTripDetail: async () => { calls++; throw new Error('offline'); } } });
  const props = { trip: { ...trip, backendId: 1, segments: [] }, active: 'trips', onChange: noop, onBack: () => backs++ };
  let tree = h.render(props); await flush(); tree = h.render();
  const list = find(tree, 'FlatList'), back = button(tree, 'Back to trips');
  assert(back); assert(!nodes(list.props.ListHeaderComponent).includes(back));
  assert.equal(tree.props.children[0].props.style.backgroundColor, palette.paperSoft);
  back.props.onPress(); assert.equal(backs, 1);
  button(tree, 'Retry flight details').props.onPress(); h.render(); await flush(); h.render();
  assert.equal(calls, 2); h.dispose();
});


test('background refresh never inserts or removes space inside an already populated itinerary', async () => {
  let resolve;
  const pending = new Promise(done => { resolve = done; });
  const h = host('screens/TripDetailScreen.tsx', 'TripDetailScreen', { service: { loadTripDetail: () => pending } });
  const full = { ...trip, backendId: 1 };
  const props = { trip: full, active: 'trips', onBack: noop, onChange: noop, selectedFlightId: 'new' };
  h.render(props); const loading = h.render();
  const header = find(loading, 'FlatList').props.ListHeaderComponent;
  assert(!find(header, 'ActivityIndicator'), 'Loading must not shift the map or flight rows');
  const indicator = find(loading, 'ActivityIndicator'); assert.equal(indicator.props.animating, true);
  const scrolls = [], list = find(loading, 'FlatList');
  list.props.ref.current = { scrollToIndex: value => scrolls.push(value) };
  list.props.onContentSizeChange();
  assert.equal(scrolls[0].index, 1); assert.equal(scrolls[0].animated, false, 'Cached selected flight does not wait for a network refresh');
  resolve(full); await flush(); const loaded = h.render();
  assert.equal(JSON.stringify(find(loaded, 'FlatList').props.ListHeaderComponent), JSON.stringify(header));
  assert.equal(find(loaded, 'ActivityIndicator').props.animating, false);
  assert.equal(find(loaded, 'FlatList').props.data.length, 2); h.dispose();
});

for (const reducedMotion of [true, false]) test(`overview stays at top; exact Home flight entry focuses only that flight (reduced motion ${reducedMotion})`, () => {
  const scrolls = [], h = host('screens/TripDetailScreen.tsx', 'TripDetailScreen', { reducedMotion });
  const props = { trip, active: 'trips', onBack: noop, onChange: noop };
  let tree = h.render(props), list = find(tree, 'FlatList');
  list.props.ref.current = { scrollToIndex: value => scrolls.push(value) };
  list.props.onContentSizeChange(); assert.equal(scrolls.length, 0);
  tree = h.render({ ...props, selectedFlightId: 'new' }); list = find(tree, 'FlatList'); list.props.onContentSizeChange(); list.props.onContentSizeChange();
  assert.equal(scrolls.length, 1); assert.equal(scrolls[0].index, 1); assert.equal(scrolls[0].animated, false);
  assert.equal(list.props.data.length, 2);
  list.props.data.forEach((item, index) => assert(find(list.props.renderItem({ item, index }), 'BoardingPass')));
  h.dispose();
});

test('airport calendar dates distinguish overnight and date-line changes without device timezone conversion', () => {
  assert.equal(presentation.arrivalDayChange(earlier.depTime, earlier.arrTime), 'Next day');
  assert.equal(presentation.arrivalDayChange('2026-01-02T01:00:00+14:00', '2026-01-01T21:00:00-10:00'), 'Previous day');
  assert.equal(presentation.arrivalDayChange('2026-01-01', '2026-01-03'), '2 days later');
  assert.equal(presentation.arrivalDayChange(later.depTime, later.arrTime), undefined);
  assert.equal(presentation.arrivalDayChange('2026-02-30', '2026-03-01'), undefined);
  assert.equal(presentation.arrivalDayChange(undefined, earlier.arrTime), undefined);
  assert.equal(presentation.flightTime(earlier.depTime), '23:30');
  assert.equal(presentation.connectionText({ ...earlier, arrTime: '2026-01-01' }, later), 'Via LHR · timing needs review');
});

test('boarding pass shows both local dates and the day change; large type moves the stub below', () => {
  const h = host('components/world-window/trips/BoardingPass.tsx', 'BoardingPass', { fontScale: 1.6 });
  const tree = h.render({ segment: earlier }); const copy = texts(tree);
  assert(copy.includes('31 Dec 2025')); assert(copy.includes('1 Jan 2026')); assert(copy.includes('Next day')); assert(copy.includes('23:30'));
  assert(nodes(tree).some(node => node.type === 'View' && Array.isArray(node.props.style) && node.props.style.some(style => style?.flexDirection === 'column')));
  assert(!copy.some(value => /seat|gate|boarding group/i.test(value)), 'No unsupported ticket facts are invented'); h.dispose();
});

test('narrow large text stacks counts, full airport endpoints, group headings and complete totals', () => {
  const options = { width: 320, fontScale: 2, service: { trips: [trip] } };
  const listHost = host('screens/TripsListScreen.tsx', 'TripsListScreen', options);
  const listTree = listHost.render({ active: 'trips', onChange: noop, initialYear: '2026' });
  assert.equal(find(listTree, 'WWHeader').props.action, undefined);
  assert(texts(listTree).some(value => value === '1 of 1 trips')); listHost.dispose();
  const detailHost = host('screens/TripDetailScreen.tsx', 'TripDetailScreen', options);
  const detailTree = detailHost.render({ trip, active: 'trips', onBack: noop, onChange: noop });
  const list = find(detailTree, 'FlatList');
  const isColumn = node => node.type === 'View' && Array.isArray(node.props.style) && node.props.style.some(style => style?.flexDirection === 'column');
  assert(nodes(list.props.ListFooterComponent).some(isColumn));
  assert(nodes(list.props.renderItem({ item: earlier, index: 0 })).some(isColumn)); detailHost.dispose();
  const passHost = host('components/world-window/trips/BoardingPass.tsx', 'BoardingPass', options);
  assert(nodes(passHost.render({ segment: earlier })).filter(isColumn).length >= 3); passHost.dispose();
});

test('wallet popup keeps all flights in one scroll area with no nested screen navigation', () => {
  const h = host('screens/TripDetailScreen.tsx', 'TripDetailScreen', { width: 420 });
  let tree = h.render({ trip, active: 'trips', onBack: noop, onChange: noop, popup: true });
  assert(!find(tree, 'BottomNav'));
  assert(!button(tree, 'Back to trips'), 'Dismissal belongs to the popup, outside its scrolling paper');
  let list = find(tree, 'FlatList');
  assert.equal(list.props.contentContainerStyle.paddingBottom, 0);
  assert.equal(find(list.props.ListHeaderComponent, 'WalletHeading').props.compact, true);
  assert.equal(find(list.props.ListHeaderComponent, 'WalletHeading').props.availableWidth, 380);
  assert.equal(list.props.data.length, 2);
  list.props.data.forEach((item, index) => {
    const pass = find(list.props.renderItem({ item, index }), 'BoardingPass');
    assert.equal(pass.props.segment.id, item.id); assert.equal(pass.props.availableWidth, 380);
  });
  tree.props.onLayout({ nativeEvent: { layout: { width: 280 } } }); tree = h.render();
  list = find(tree, 'FlatList');
  assert.equal(find(list.props.ListHeaderComponent, 'WalletHeading').props.availableWidth, 280);
  assert.equal(find(list.props.renderItem({ item: earlier, index: 0 }), 'BoardingPass').props.availableWidth, 280);
  h.dispose();
});
