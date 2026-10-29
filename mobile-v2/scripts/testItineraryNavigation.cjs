const assert = require('node:assert/strict');
const { test } = require('node:test');
const fs = require('node:fs'), path = require('node:path'), ts = require('typescript');
const React = require('react'), Renderer = require('react-test-renderer');
const { act } = React;
global.IS_REACT_ACT_ENVIRONMENT = true;

function harness(api = {}) {
  let revision = 1, serial = 0;
  const calls = [], cache = new Map();
  const hosts = Object.fromEntries(['Text', 'View', 'ScrollView', 'ActivityIndicator', 'RefreshControl', 'TextInput'].map(name => [name, name]));
  class Value { constructor(value) { this.value = value; } setValue(value) { this.value = value; } stopAnimation() {} }
  const native = { ...hosts, StyleSheet: { create: x => x }, Platform: { OS: 'web' }, AppState: { currentState: 'active', addEventListener: () => ({ remove() {} }) },
    BackHandler: { addEventListener: () => ({ remove() {} }) }, Linking: {}, Clipboard: {}, Share: {},
    Animated: { View: 'AnimatedView', Value, timing: (value, options) => ({ start() { value.setValue(options.toValue); calls.push(options); } }) }, PanResponder: { create: value => ({ panHandlers: value }) } };
  class PlannerApiError extends Error { constructor(message, status) { super(message); this.status = status; } }
  const auth = { useTravelTrips: () => ({ accountId: 1 }), getAuthRevision: () => revision };
  const kit = { k: {}, PlannerAction: 'PlannerAction', PlannerSheet: ({ children, ...props }) => React.createElement('PlannerSheet', props, children), PlannerPhoto: 'PlannerPhoto', PlannerGlyph: 'PlannerGlyph', PlannerChoices: 'PlannerChoices', PlannerField: 'PlannerField' };
  function load(file) {
    file = path.resolve(file); if (cache.has(file)) return cache.get(file).exports;
    const module = { exports: {} }; cache.set(file, module);
    const code = ts.transpileModule(fs.readFileSync(file, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.React, esModuleInterop: true, target: ts.ScriptTarget.ES2022 } }).outputText;
    function requireModule(name) {
      if (name === 'react') return React;
      if (name === 'react-native') return native;
      if (name === 'expo-crypto') return { randomUUID: () => `request-${++serial}` };
      if (name === 'react-native-safe-area-context') return { useSafeAreaInsets: () => ({ top: 0, bottom: 24 }) };
      if (name.endsWith('/services/travelTrips')) return auth;
      if (name.endsWith('/services/dreams')) return { useDreams: () => ({ items: [] }) };
      if (name.endsWith('/services/planner')) return { plannerApi: api, PlannerApiError, subscribePlannerChanges: () => () => {} };
      if (name.endsWith('/motion')) return { PressFeedback: 'Pressable', useReducedMotion: () => false, paperEase: 'ease' };
      if (name.endsWith('/experiencePreferences')) return { selectionHaptic() {} };
      if (name.endsWith('/TrotterKit')) return { BottomNav: 'BottomNav' };
      if (name.endsWith('/WorldWindowUI')) return { WWIcon: 'Icon' };
      if (name.endsWith('/ProfileAvatar')) return { ProfileAvatar: 'ProfileAvatar' };
      if (name.endsWith('/PlannerKit')) return kit;
      if (name.endsWith('/PlannerDayParts')) return { PeriodGapRow: 'PeriodGapRow', StayRow: 'StayRow' };
      if (name.endsWith('/PlannerForms')) return {};
      for (const component of ['IdeaVote', 'PlanNotes', 'DreamsForTrip', 'DreamDestinationField']) if (name.endsWith('/' + component)) return { [component]: component };
      if (name.endsWith('/PlannerResult')) return { PlannerTransportForm: 'PlannerTransportForm', UnscheduledActivities: 'UnscheduledActivities' };
      // Screen integration tests inspect the list contract; dedicated tests below render its actual gesture code.
      if (file.endsWith('PlannerScreen.tsx') && name.endsWith('/ReorderableStops')) return { ReorderableStops: 'ReorderableStops' };
      if (file.endsWith('PlannerScreen.tsx') && name.endsWith('/ItineraryDayNav')) return { ItineraryDayNav: 'ItineraryDayNav' };
      if (name.startsWith('.')) {
        const base = path.resolve(path.dirname(file), name), found = ['', '.tsx', '.ts', '.json'].map(ext => base + ext).find(value => fs.existsSync(value));
        return found.endsWith('.json') ? JSON.parse(fs.readFileSync(found, 'utf8')) : load(found);
      }
      throw new Error(`Unexpected dependency ${name}`);
    }
    new Function('require', 'module', 'exports', code)(requireModule, module, module.exports); return module.exports;
  }
  return { load, calls, PlannerApiError, changeAccount: () => revision++ };
}
const base = path.resolve(__dirname, '../src/components/world-window/planner');
const model = harness().load(path.join(base, 'itineraryNavigation.ts'));
const day1 = '2026-11-09', day2 = '2026-11-10';
const stop = id => ({ id, idea_id: id, title: id, kind: 'place', start_time: id === 'a' ? '09:00' : '11:00', duration_minutes: 60, locked: false, travel_source: 'unknown' });
const plan = { days: [{ date: day1, stops: [stop('a'), stop('b')] }, { date: day2, stops: [] }], warnings: [], unplaced_idea_ids: [] };
const trip = { id: 'trip', title: 'Morocco', destination: 'Morocco', start_date: day1, end_date: day2, version: 1, role: 'owner', member_count: 1, transport: 'walk', transport_modes: ['walk'],
  plan, draft: null, generation: null, ideas: [], members: [], invites: [] };
const pending = () => { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b; }); return { promise, resolve, reject }; };
const render = async (element, options) => { let view; await act(async () => { view = Renderer.create(element, options); }); return view; };
const dispose = async view => act(async () => view.unmount());
const action = (view, label) => view.root.findAllByType('PlannerAction').find(node => node.props.label === label) || assert.fail(`Missing action ${label}`);
const props = { initialTripId: 'trip', onTabChange() {}, onOpenProfile() {}, onBackHandlerChange() {} };
async function screen(api, value = trip) {
  const h = harness({ list: async () => ({ trips: [value] }), get: async () => value, ...api });
  const Screen = h.load(path.resolve(__dirname, '../src/screens/PlannerScreen.tsx')).PlannerScreen;
  const scrolls = [], view = await render(React.createElement(Screen, props), { createNodeMock: node => node.type === 'ScrollView' ? { scrollTo: args => scrolls.push(args) } : null });
  return { h, Screen, view, scrolls };
}
async function reorderMode(view) {
  await act(async () => action(view, 'Edit day').props.onPress());
  await act(async () => action(view, 'Reorder stops').props.onPress());
  return () => view.root.findByType('ReorderableStops');
}

test('day jump accounts for pinned bar, follows manual scrolling, and tolerates missing anchors', () => {
  assert.equal(model.itineraryDayOffset(undefined, 57), undefined);
  assert.equal(model.itineraryDayOffset(20, 57), 0);
  assert.equal(model.itineraryDayOffset(1000, 57), 935);
  assert.equal(model.visibleItineraryDay([day1, day2], { [day1]: 400, [day2]: 1000 }, 935, 57), day2);
  assert.equal(model.visibleItineraryDay([day1, day2], { [day1]: 400, [day2]: 1000 }, 500, 57), day1);
});
test('drag thresholds use variable row heights and clamp ordering without mutating input', () => {
  const ids = ['a', 'b', 'c'], heights = { a: 80, b: 200, c: 100 };
  assert.equal(model.reorderTarget(ids, 'a', 90, heights), 0);
  assert.equal(model.reorderTarget(ids, 'a', 110, heights), 1);
  assert.equal(model.reorderTarget(['a', 'b'], 'a', 80, { a: 200, b: 80 }), 1);
  assert.equal(model.reorderTarget(ids, 'c', -300, heights), 0);
  assert.deepEqual(model.reorderPreview(ids, 'a', 99), ['b', 'c', 'a']); assert.deepEqual(ids, ['a', 'b', 'c']);
  assert.deepEqual(model.stopPositions(['b', 'a', 'c'], heights), { positions: { b: 0, a: 200, c: 280 }, height: 380 });
});
test('continuous itinerary retains every day and the day selector scrolls to measured offsets', async () => {
  const { view, scrolls } = await screen();
  const nav = view.root.findByType('ItineraryDayNav'); assert.deepEqual(nav.props.dates, [day1, day2]);
  const dayViews = view.root.findAllByType('View').filter(node => node.props.onLayout && node.findAllByType('Text').some(t => (t.children || []).includes('Day ')));
  assert.equal(dayViews.length, 2);
  await act(async () => dayViews.forEach((node, index) => node.props.onLayout({ nativeEvent: { layout: { y: 400 + index * 600 } } })));
  await act(async () => nav.props.onSelect(day2)); assert.equal(scrolls.at(-1).y, 935);
  await act(async () => nav.parent.props.onLayout({ nativeEvent: { layout: { y: 300, height: 57 } } }));
  await act(async () => view.root.findByType('ScrollView').props.onScroll({ nativeEvent: { contentOffset: { y: 935 } } }));
  const bars = view.root.findAllByType('ItineraryDayNav'); assert.equal(bars.length, 2); assert.equal(bars[1].props.active, day2);
  assert.equal(bars[0].parent.props.importantForAccessibility, 'no-hide-descendants'); assert.equal(bars[0].parent.props.pointerEvents, 'none');
  await dispose(view);
});
test('draft acceptance remains outside scroll and is absent for contributors and accepted plans', async () => {
  const draftTrip = { ...trip, draft: { id: 'draft', plan } };
  const { view } = await screen({}, draftTrip);
  const button = action(view, 'Use this plan'); let parent = button.parent;
  while (parent) { assert.notEqual(parent.type, 'ScrollView'); parent = parent.parent; }
  await dispose(view);
  for (const value of [trip, { ...draftTrip, role: 'contributor' }]) { const next = await screen({}, value); assert.equal(next.view.root.findAllByType('PlannerAction').filter(n => n.props.label === 'Use this plan').length, 0); await dispose(next.view); }
});
test('reorder is optimistic, sends original version, and rolls back with inline feedback on failure', async () => {
  const deferred = pending(), writes = [];
  const { view } = await screen({ savePlan: (...args) => { writes.push(args); return deferred.promise; } });
  const list = await reorderMode(view);
  await act(async () => assert.equal(list().props.onReorder('a', 1), true));
  assert.deepEqual(list().props.stops.map(s => s.id), ['b', 'a']); assert.equal(list().props.enabled, false); assert.equal(writes[0][1], 1);
  assert.equal(view.root.findAllByType('ActivityIndicator').length, 0, 'saving must not insert a global loading row and shift the itinerary');
  assert.ok(view.root.findAllByType('Text').some(node => node.props.accessibilityLiveRegion === 'polite' && String(node.children) === 'Saving order…'));
  await act(async () => deferred.reject(new Error('Offline')));
  assert.deepEqual(list().props.stops.map(s => s.id), ['a', 'b']); assert.equal(list().props.enabled, true);
  assert.ok(view.root.findAllByType('Text').some(node => String(node.children).includes('previous order has been restored')));
  await dispose(view);
});
test('reorder conflict loads authoritative version and never repeats the write', async () => {
  const deferred = pending(); let reads = 0, writes = 0;
  const latest = { ...trip, version: 2, plan: { ...plan, days: [{ ...plan.days[0], stops: [stop('b')] }, plan.days[1]] } };
  const { h, view } = await screen({ get: async () => ++reads > 1 ? latest : trip, savePlan: () => { writes++; return deferred.promise; } });
  const list = await reorderMode(view); await act(async () => list().props.onReorder('a', 1));
  await act(async () => deferred.reject(new h.PlannerApiError('Conflict', 409)));
  assert.equal(writes, 1); assert.deepEqual(list().props.stops.map(s => s.id), ['b']);
  await dispose(view);
});
test('late reorder response after auth revision changes cannot replace the plan', async () => {
  const deferred = pending(), { h, view } = await screen({ savePlan: () => deferred.promise });
  const list = await reorderMode(view); await act(async () => list().props.onReorder('a', 1)); h.changeAccount();
  await act(async () => deferred.resolve({ ...trip, version: 2, plan: { ...plan, days: [] } }));
  assert.deepEqual(list().props.stops.map(s => s.id), ['a', 'b']); await dispose(view);
});
test('drag preview shifts neighbors, cancellation never writes, and disabled gestures cannot start', async () => {
  const h = harness(), Component = h.load(path.join(base, 'ReorderableStops.tsx')).ReorderableStops, writes = [], dragging = [];
  const view = await render(React.createElement(Component, { stops: plan.days[0].stops, enabled: true, onReorder: (...args) => { writes.push(args); return true; }, onDragging: x => dragging.push(x), renderStop: (stop, handle) => React.createElement('Handle', { ...handle, id: stop.id }) }));
  const handle = () => view.root.findAllByType('Handle')[0];
  await act(async () => handle().props.onPanResponderGrant());
  await act(async () => handle().props.onPanResponderMove({}, { dy: 100 }));
  const rows = view.root.findAllByType('AnimatedView'); assert.equal(rows[1].props.style[1].transform[0].translateY.value, 0);
  await act(async () => handle().props.onPanResponderTerminate()); assert.equal(writes.length, 0); assert.equal(dragging.at(-1), false);
  await act(async () => view.update(React.createElement(Component, { stops: plan.days[0].stops, enabled: false, onReorder: (...args) => writes.push(args), onDragging: x => dragging.push(x), renderStop: (stop, handle) => React.createElement('Handle', { ...handle, id: stop.id }) })));
  assert.equal(handle().props.onStartShouldSetPanResponder(), false);
  await act(async () => { handle().props.onPanResponderGrant(); handle().props.onPanResponderRelease(); }); assert.equal(writes.length, 0);
  await dispose(view);
});
