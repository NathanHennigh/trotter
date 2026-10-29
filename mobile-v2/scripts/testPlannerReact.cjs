const assert = require('node:assert/strict');
const { test } = require('node:test');
const fs = require('node:fs'), path = require('node:path'), ts = require('typescript');
const React = require('react'), Renderer = require('react-test-renderer');
const { act } = React;
global.IS_REACT_ACT_ENVIRONMENT = true;

// Real React rendering, state, effects and cleanup. Only native hosts and network/auth boundaries are replaced.
function harness(api = {}, nativeOverrides = {}) {
  let revision = 1;
  const cache = new Map();
  const native = Object.fromEntries(['Text', 'View', 'Pressable', 'TextInput', 'Image', 'ScrollView', 'ActivityIndicator', 'KeyboardAvoidingView'].map(name => [name, name]));
  Object.assign(native, {
    StyleSheet: { create: value => value, absoluteFill: {}, absoluteFillObject: {} }, Platform: { OS: 'android' }, Keyboard: { isVisible: () => false },
    useWindowDimensions: () => ({ width: 390, height: 844 }),
    Animated: { View: 'AnimatedView', Value: class { stopAnimation() {} setValue() {} interpolate(config) { return config; } },
      timing: () => ({ start: callback => callback?.({ finished: true }), stop() {} }) },
    Modal: props => props.visible ? React.createElement('Modal', props, props.children) : null,
  }, nativeOverrides);
  const auth = { getAuthRevision: () => revision, subscribeAuthToken: () => () => {}, getStoredToken: () => 'local-test-token', getApiBaseUrl: () => 'https://test.invalid' };
  function load(file) {
    file = path.resolve(file);
    if (cache.has(file)) return cache.get(file).exports;
    if (file.endsWith('.json')) return JSON.parse(fs.readFileSync(file, 'utf8'));
    const module = { exports: {} }; cache.set(file, module);
    const source = ts.transpileModule(fs.readFileSync(file, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.React, esModuleInterop: true, target: ts.ScriptTarget.ES2022 } }).outputText;
    function requireModule(name) {
      if (name === 'react') return React;
      if (name === 'react-native') return native;
      if (name === 'react-native-safe-area-context') return { useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }) };
      if (name === 'react-native-svg') return { __esModule: true, default: 'Svg', Path: 'Path', Rect: 'Rect' };
      if (name.endsWith('/services/planner')) return { plannerApi: api };
      if (name.endsWith('/services/travelTrips')) return auth;
      if (name.endsWith('/experiencePreferences')) return { selectionHaptic() {} };
      if (name.endsWith('/motion')) return { PressFeedback: 'Pressable', useReducedMotion: () => true, paperEase: value => value };
      if (name.endsWith('/WorldWindowUI')) return { WWIcon: 'Icon' };
      if (name.endsWith('/countryArtwork')) return { findCountryArtwork: () => undefined };
      if (name.endsWith('/DreamPhoto')) return { PlaceSymbol: 'PlaceSymbol' };
      if (name.startsWith('.')) {
        const base = path.resolve(path.dirname(file), name);
        const resolved = ['', '.tsx', '.ts', '.json'].map(ext => base + ext).find(candidate => fs.existsSync(candidate));
        return load(resolved);
      }
      throw new Error(`Unexpected unmocked dependency: ${name}`);
    }
    new Function('require', 'module', 'exports', source)(requireModule, module, module.exports);
    return module.exports;
  }
  return { component: (name, exported = name) => load(path.resolve(__dirname, `../src/components/world-window/planner/${name}.tsx`))[exported], changeAccount: () => revision++ };
}
const pending = () => { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b; }); return { promise, resolve, reject }; };
const scope = { id: 'morocco', country: 'Morocco', city: null, label: 'Morocco' };
const off = { enabled: false, active: false, paused_reason: null, consented_at: null };
const on = { enabled: true, active: true, paused_reason: null, consented_at: '2026-10-26T12:00:00Z' };
const trip = { id: 'trip-one', title: 'Morocco, together', destination: 'Morocco', match_scope: scope, dream_sharing: off, updated_at: 'one', end_date: '2099-01-01' };
const row = id => ({ dream_item_id: String(id), title: `Saved place ${id}`, category: 'attraction', city: 'Marrakech', country: 'Morocco' });
const page = (ids, extra = {}) => ({ scope, sharing: off, total: ids.length, suggestions: ids.map(row), next_cursor: null, ...extra });
const plain = node => typeof node === 'string' ? node : (node.children || []).map(plain).join('');
const allText = root => root.findAllByType('Text').map(plain).join('\n');
const buttons = root => root.findAllByType('Pressable');
const button = (root, label) => buttons(root).find(node => (node.props.accessibilityLabel || plain(node)) === label) || assert.fail(`Missing button ${label}\n${buttons(root).map(node => node.props.accessibilityLabel || plain(node)).join('\n')}`);
const click = async (root, label) => { const target = button(root, label); assert.ok(!target.props.disabled, `${label} is disabled`); await act(async () => { target.props.onPress(); }); };
const render = async (element, options) => { let view; await act(async () => { view = Renderer.create(element, options); }); return view; };
const dispose = async view => act(async () => view.unmount());
const props = overrides => ({ trip, visible: true, dreamsRevision: 'one', onChanged() {}, onBrowseDreams() {}, ...overrides });

test('unscheduled activities show factual reasons and a direct travel action without counting hotels', async () => {
  const h = harness(), Component = h.component('PlannerResult', 'UnscheduledActivities');
  const ideas = [{ id: 'desert', title: 'Agafay', category: 'sight' }, { id: 'unknown', title: 'New save', category: 'sight' },
    { id: 'later', title: 'Another place', category: 'cafe' }, { id: 'hotel', title: 'Saved hotel', category: 'hotel' }];
  const plan = { days: [], warnings: [], unplaced_idea_ids: ideas.map(i => i.id), unplaced_reasons: {
    desert: { code: 'transport_required', transport_mode: 'walk' }, unknown: { code: 'needs_location' }, later: { code: 'no_fit' },
  } };
  let transport = 0, opened;
  const view = await render(React.createElement(Component, { plan, ideas, modes: ['walk'], onIdea: idea => opened = idea.id, onTransport: () => transport++ }));
  assert.match(allText(view.root), /3 activities/); assert.match(allText(view.root), /beyond walking/);
  assert.doesNotMatch(allText(view.root), /Saved hotel|Another place/);
  await click(view.root, 'Getting around'); assert.equal(transport, 1);
  await click(view.root, 'Review Agafay'); assert.equal(opened, 'desert');
  await click(view.root, 'Show 1 more'); assert.match(allText(view.root), /Another place/);
  await act(async () => view.update(React.createElement(Component, { plan, ideas, modes: ['walk', 'drive'], onIdea() {}, onTransport() {} })));
  assert.doesNotMatch(allText(view.root), /beyond walking|Getting around/);
  await dispose(view);
});

test('legacy plan hides obsolete unused-hotel warnings and keeps neutral unscheduled copy', async () => {
  const h = harness(), Notes = h.component('PlanNotes'), Remaining = h.component('PlannerResult', 'UnscheduledActivities');
  const note = await render(React.createElement(Notes, { warnings: ['14 ideas remain in Ideas; they were not forced into the itinerary.', 'Confirm opening hours.'] }));
  assert.doesNotMatch(allText(note.root), /14 ideas/); assert.match(allText(note.root), /Confirm opening hours/);
  const view = await render(React.createElement(Remaining, { plan: { days: [], warnings: [], unplaced_idea_ids: ['a'] },
    ideas: [{ id: 'a', title: 'Old save', category: 'sight' }], modes: ['walk'], onIdea() {} }));
  assert.match(allText(view.root), /Not included in this version/);
  assert.doesNotMatch(allText(view.root), /closed|beyond walking|Getting around/);
  await dispose(note); await dispose(view);
});

test('travel editor saves only after an explicit choice and never generates a draft', async () => {
  const h = harness({ generate: () => assert.fail('Transport edit must not regenerate') });
  const Component = h.component('PlannerResult', 'PlannerTransportForm'), saves = [];
  const view = await render(React.createElement(Component, { modes: ['walk'], busy: false, onSave: modes => saves.push(modes) }));
  assert.equal(saves.length, 0);
  await click(view.root, 'Driving'); assert.equal(saves.length, 0);
  await click(view.root, 'Save travel options'); assert.deepEqual(saves, [['walk', 'drive']]);
  await dispose(view);
});

test('private suggestions never share on render; Share all includes matches beyond the loaded page', async () => {
  const request = pending(), calls = []; let reads = 0, changed = 0;
  const h = harness({ dreamSuggestions: async () => ++reads === 1 ? page([1, 2, 3, 4], { total: 25, next_cursor: '4' }) : page([]),
    importMatchingDreams: (...args) => { calls.push(args); return request.promise; }, setDreamSharing: () => assert.fail('Consent must be explicit') });
  const Component = h.component('DreamsForTrip'), view = await render(React.createElement(Component, props({ onChanged: () => changed++ })));
  assert.equal(calls.length, 0); assert.match(allText(view.root), /Only you can see/); assert.doesNotMatch(allText(view.root), /Saved place 4/);
  await click(view.root, 'Share all 25 with this trip');
  assert.deepEqual(calls, [['trip-one', { scope_id: 'morocco', all: true }]]);
  await act(async () => request.resolve(trip));
  assert.equal(changed, 1); assert.match(allText(view.root), /Shared with this trip/); assert.doesNotMatch(allText(view.root), /Saved place 1/);
  await dispose(view);
});

test('selection spans pages, survives an import failure, and retries exactly the explicit selection', async () => {
  const calls = []; let importCount = 0;
  const h = harness({ dreamSuggestions: async (_id, cursor) => cursor ? page([2, 3], { total: 3 }) : page([1, 2], { total: 3, next_cursor: '2' }),
    importMatchingDreams: async (...args) => { calls.push(args); if (++importCount === 1) throw new Error('Connection interrupted'); return trip; } });
  const Component = h.component('DreamsForTrip'), view = await render(React.createElement(Component, props()));
  await click(view.root, 'Review'); await click(view.root, 'Saved place 1'); await click(view.root, 'Show more saved places'); await click(view.root, 'Saved place 3');
  assert.equal(buttons(view.root).filter(node => node.props.accessibilityLabel === 'Saved place 2').length, 1, 'overlapping pages must dedupe');
  await click(view.root, 'Share 2 selected');
  assert.match(allText(view.root), /Connection interrupted/); assert.equal(button(view.root, 'Saved place 3').props.accessibilityState.checked, true);
  await click(view.root, 'Share 2 selected');
  assert.deepEqual(calls, Array(2).fill(['trip-one', { scope_id: 'morocco', dream_item_ids: ['1', '3'] }]));
  await dispose(view);
});

test('future sharing starts off and a failed consent request cannot look enabled', async () => {
  let sharing = off, attempts = 0; const writes = [];
  const h = harness({ dreamSuggestions: async () => page([], { sharing }), setDreamSharing: async (...args) => { writes.push(args); if (++attempts === 1) throw new Error('Offline'); sharing = on; return { ...trip, dream_sharing: on }; } });
  const Component = h.component('DreamsForTrip'), view = await render(React.createElement(Component, props()));
  assert.equal(writes.length, 0); await click(view.root, 'Future saves · sharing off');
  const label = 'Automatically share future saves in Morocco';
  assert.equal(button(view.root, label).props.accessibilityState.checked, false);
  await click(view.root, label); assert.equal(button(view.root, label).props.accessibilityState.checked, false); assert.match(allText(view.root), /Offline/);
  await click(view.root, label); assert.equal(button(view.root, label).props.accessibilityState.checked, true);
  assert.deepEqual(writes, [['trip-one', 'morocco', true], ['trip-one', 'morocco', true]]);
  await dispose(view);
});

test('Future saves opens its off switch before a long list of private photos', async () => {
  const h = harness({ dreamSuggestions: async () => page(Array.from({ length: 20 }, (_, index) => index + 1)) });
  const Component = h.component('DreamsForTrip'), view = await render(React.createElement(Component, props()));
  await click(view.root, 'Future saves · sharing off');
  const modal = view.root.findByType('Modal'), controls = buttons(modal);
  const preferenceIndex = controls.findIndex(node => node.props.accessibilityRole === 'switch');
  const firstPlaceIndex = controls.findIndex(node => node.props.accessibilityRole === 'checkbox');
  assert.ok(preferenceIndex >= 0 && preferenceIndex < firstPlaceIndex, 'the sharing preference must be above the photo list');
  assert.equal(controls[preferenceIndex].props.accessibilityState.checked, false);
  assert.equal(controls.filter(node => node.props.accessibilityRole === 'checkbox').length, 20);
  await dispose(view);
});

test('hiding cancels suggestions, dismisses the sheet, and ignores a late response before refreshing on return', async () => {
  const late = pending(); let call = 0, firstSignal;
  const h = harness({ dreamSuggestions: (_id, _cursor, signal) => { if (++call === 1) { firstSignal = signal; return late.promise; } return Promise.resolve(page([9])); } });
  const Component = h.component('DreamsForTrip'), view = await render(React.createElement(Component, props()));
  await click(view.root, 'Review'); assert.equal(view.root.findAllByType('Modal').length, 1);
  await act(async () => view.update(React.createElement(Component, props({ visible: false }))));
  assert.equal(firstSignal.aborted, true); assert.equal(view.root.findAllByType('Modal').length, 0);
  await act(async () => late.resolve(page([1]))); assert.doesNotMatch(allText(view.root), /Saved place 1/);
  await act(async () => view.update(React.createElement(Component, props())));
  assert.match(allText(view.root), /Saved place 9/); assert.equal(call, 2);
  await dispose(view);
});

test('an old account response never exposes its private suggestions', async () => {
  const late = pending(), h = harness({ dreamSuggestions: () => late.promise });
  const Component = h.component('DreamsForTrip'), view = await render(React.createElement(Component, props()));
  h.changeAccount(); await act(async () => late.resolve(page([123])));
  assert.doesNotMatch(allText(view.root), /Saved place 123/); await dispose(view);
});

test('changing a scope remounts private results and ignores the old destination response', async () => {
  const late = pending(); let reads = 0;
  const h = harness({ dreamSuggestions: () => ++reads === 1 ? late.promise : Promise.resolve(page([7], { scope: { ...scope, id: 'city', label: 'Marrakech' } })) });
  const Component = h.component('DreamsForTrip'), view = await render(React.createElement(Component, { ...props(), key: scope.id }));
  await act(async () => view.update(React.createElement(Component, { ...props({ trip: { ...trip, match_scope: { ...scope, id: 'city', label: 'Marrakech' } } }), key: 'city' })));
  await act(async () => late.resolve(page([1])));
  assert.doesNotMatch(allText(view.root), /Saved place 1/); assert.match(allText(view.root), /Saved place 7/); await dispose(view);
});

test('a legacy trip offers a simple destination connection without guessing or sharing', async () => {
  let chose = 0;
  const h = harness({ dreamSuggestions: () => assert.fail('No scope should not request matches') });
  const Component = h.component('DreamsForTrip'), view = await render(React.createElement(Component, props({ trip: { ...trip, match_scope: null }, onChooseDestination: () => chose++ })));
  await click(view.root, 'Choose destination'); assert.equal(chose, 1); await dispose(view);
});

test('a populated trip shows one compact match shortcut and opens the existing private review', async () => {
  const h = harness({ dreamSuggestions: async () => page([1, 2, 3], { total: 9, next_cursor: '3' }) });
  const Component = h.component('DreamsForTrip'), view = await render(React.createElement(Component, props({ compact: true })));
  assert.doesNotMatch(allText(view.root), /Saved place 1/); assert.match(allText(view.root), /9 new/);
  await click(view.root, 'From your Dreams, 9 new places'); assert.match(allText(view.root), /Saved place 1/);
  assert.equal(view.root.findAllByType('Modal').length, 1); await dispose(view);
});

test('double-tapping Share all creates one request and a scope conflict preserves private suggestions', async () => {
  const deferred = pending(); let writes = 0;
  const h = harness({ dreamSuggestions: async () => page([1]), importMatchingDreams: () => { writes++; return deferred.promise; } });
  const Component = h.component('DreamsForTrip'), view = await render(React.createElement(Component, props()));
  const target = button(view.root, 'Share all 1 with this trip'); await act(async () => { target.props.onPress(); target.props.onPress(); });
  assert.equal(writes, 1); await act(async () => deferred.reject(new Error("This trip's matching destination changed. Review it before sharing.")));
  assert.match(allText(view.root), /Review it before sharing/); assert.match(allText(view.root), /Saved place 1/); assert.equal(writes, 1); await dispose(view);
});

test('an exact initial destination connects to categorized geography; typed edits invalidate that selection', async () => {
  const h = harness({ dreamDestinations: async () => ({ destinations: [{ ...scope, count: 12 }] }) }), Component = h.component('DreamDestinationField');
  let selected;
  function Form() { const [value, setValue] = React.useState('Morocco'), [chosen, setChosen] = React.useState(null); selected = chosen;
    return React.createElement(Component, { value, scope: chosen, selectInitial: true, onChange: (text, option) => { setValue(text); setChosen(option); } }); }
  const view = await render(React.createElement(Form)); assert.equal(selected.id, 'morocco');
  await act(async () => view.root.findByType('TextInput').props.onChangeText('Moroc'));
  assert.equal(selected, null); await click(view.root, 'Choose Morocco'); assert.equal(selected.id, 'morocco'); await dispose(view);
});

test('a delayed destination request cannot override text edited while loading', async () => {
  const late = pending(), h = harness({ dreamDestinations: () => late.promise }), Component = h.component('DreamDestinationField'); let selected;
  function Form() { const [value, setValue] = React.useState('Morocco'), [chosen, setChosen] = React.useState(null); selected = chosen;
    return React.createElement(Component, { value, scope: chosen, selectInitial: true, onChange: (text, option) => { setValue(text); setChosen(option); } }); }
  const view = await render(React.createElement(Form)); await act(async () => view.root.findByType('TextInput').props.onChangeText('Portugal'));
  await act(async () => late.resolve({ destinations: [{ ...scope, count: 12 }] }));
  assert.equal(selected, null); assert.equal(view.root.findByType('TextInput').props.value, 'Portugal'); await dispose(view);
});

test('voting responds immediately, blocks same-frame duplicate taps, and rolls back a failed vote', async () => {
  const request = pending(), calls = [], errors = [], h = harness({ vote: (...args) => { calls.push(args); return request.promise; } });
  const Component = h.component('IdeaVote'), idea = { id: 'a', title: 'A garden', score: 2, my_vote: 0 };
  const view = await render(React.createElement(Component, { tripId: trip.id, idea, onUpdate: () => assert.fail('Failed vote must not update trip'), onError: error => errors.push(error) }));
  const up = button(view.root, 'Vote for A garden'); await act(async () => { up.props.onPress(); up.props.onPress(); });
  assert.equal(calls.length, 1); assert.equal(button(view.root, 'Vote for A garden').props.accessibilityState.selected, true); assert.match(allText(view.root), /^3$/);
  await act(async () => request.reject(new Error('Offline')));
  assert.equal(button(view.root, 'Vote for A garden').props.accessibilityState.selected, false); assert.match(allText(view.root), /^2$/); assert.deepEqual(errors, ['Offline']); await dispose(view);
});

test('a successful vote persists and tapping the selected chevron clears it', async () => {
  const writes = [], h = harness({ vote: async (_trip, id, value) => { writes.push(value); return { ideas: [{ id, title: 'A garden', score: value, my_vote: value }] }; } }), Component = h.component('IdeaVote');
  function Parent() { const [idea, setIdea] = React.useState({ id: 'a', title: 'A garden', score: 0, my_vote: 0 }); return React.createElement(Component, { tripId: trip.id, idea, onUpdate: (result, id) => setIdea(result.ideas.find(row => row.id === id)), onError: assert.fail }); }
  const view = await render(React.createElement(Parent)); await click(view.root, 'Vote for A garden'); assert.match(allText(view.root), /^1$/);
  await click(view.root, 'Vote for A garden'); assert.match(allText(view.root), /^0$/); assert.deepEqual(writes, [1, 0]); await dispose(view);
});

test('a vote finishing after account rotation cannot update the new account', async () => {
  const late = pending(), h = harness({ vote: () => late.promise }), Component = h.component('IdeaVote'); let changed = 0;
  const view = await render(React.createElement(Component, { tripId: trip.id, idea: { id: 'a', title: 'A garden', score: 0, my_vote: 0 }, onUpdate: () => changed++, onError: assert.fail }));
  await click(view.root, 'Vote for A garden'); h.changeAccount(); await act(async () => late.resolve(trip)); assert.equal(changed, 0); await dispose(view);
});

test('long plan notes disclose all warnings without repeating duplicates', async () => {
  const h = harness(), Component = h.component('PlanNotes'), view = await render(React.createElement(Component, { warnings: ['One', 'Two', 'Three', 'One'] }));
  assert.doesNotMatch(allText(view.root), /Three/); await click(view.root, 'Show 1 more note'); assert.match(allText(view.root), /Three/);
  assert.equal(view.root.findAllByType('Text').filter(node => plain(node) === 'One').length, 1); await dispose(view);
});

test('detail photos request a larger protected thumbnail while rows remain small', async () => {
  const h = harness(), Component = h.component('PlannerKit', 'PlannerPhoto'), uri = '/planner/trips/a/ideas/b/thumbnail';
  const view = await render(React.createElement(Component, { uri, large: true }));
  let image = view.root.findByType('Image'); assert.match(image.props.source.uri, /width=960/); assert.equal(image.props.source.headers.Authorization, 'Bearer local-test-token');
  await act(async () => view.update(React.createElement(Component, { uri })));
  image = view.root.findByType('Image'); assert.match(image.props.source.uri, /width=240/); await dispose(view);
});

test('action labels stay accessible while saving and the busy state explicitly clears afterwards', async () => {
  const h = harness(), Component = h.component('PlannerKit', 'PlannerAction');
  const view = await render(React.createElement(Component, { label: 'Share all 23', busy: true, onPress() {} }));
  assert.equal(button(view.root, 'Share all 23').props.accessibilityState.busy, true);
  await act(async () => view.update(React.createElement(Component, { label: 'Share all 23', onPress() {} })));
  const action = button(view.root, 'Share all 23');
  assert.equal(action.props.accessibilityLabel, 'Share all 23');
  assert.deepEqual(action.props.accessibilityState, { disabled: false, busy: false });
  await dispose(view);
});

test('Getting around allows any combination and setup refuses an empty selection', async () => {
  const h = harness(), Component = h.component('PlannerForms', 'SetupForm'), submitted = [];
  const value = { ...trip, start_date: '2026-11-01', end_date: '2026-11-03', timezone: 'Africa/Casablanca', pace: 'balanced', transport: 'walk', transport_modes: ['walk'] };
  const view = await render(React.createElement(Component, { trip: value, active: false, busy: false, onSubmit: result => submitted.push(result) }));
  await click(view.root, 'Walking'); await click(view.root, 'Save trip details');
  assert.equal(submitted.length, 0); assert.match(allText(view.root), /at least one way/);
  await click(view.root, 'Driving'); await click(view.root, 'Transit'); await click(view.root, 'Walking');
  for (const label of ['Walking', 'Driving', 'Transit']) assert.equal(button(view.root, label).props.accessibilityState.checked, true);
  await click(view.root, 'Save trip details');
  assert.deepEqual(submitted[0].transport_modes, ['drive', 'transit', 'walk']); assert.equal(submitted[0].transport, 'drive');
  await dispose(view);
});

test('a period can become a directly editable durable text plan, with duration constrained to the opening', async () => {
  const h = harness(), Component = h.component('PlannerDayParts', 'PeriodPlanForm'), added = [];
  const view = await render(React.createElement(Component, { gap: { label: 'Morning', start_time: '10:00', end_time: '12:00', duration_minutes: 120 }, ideas: [], plan: null, busy: false, onPlace: assert.fail, onText: value => added.push(value) }));
  await click(view.root, 'My own plan'); await click(view.root, 'Add to this day'); assert.equal(added.length, 0);
  await act(async () => view.root.findAllByType('TextInput').find(node => node.props.accessibilityLabel === 'What would you like to do?').props.onChangeText('Slow morning'));
  const minutes = () => view.root.findAllByType('TextInput').find(node => node.props.accessibilityLabel === 'Minutes');
  await act(async () => minutes().props.onChangeText('121')); await click(view.root, 'Add to this day'); assert.equal(added.length, 0); assert.match(allText(view.root), /5 and 120 minutes/);
  await act(async () => minutes().props.onChangeText('120')); await click(view.root, 'Add to this day');
  assert.deepEqual(added, [{ title: 'Slow morning', start_time: '10:00', duration_minutes: 120, kind: 'break', locked: false, user_created: true }]);
  await dispose(view);
});

test('editing an existing generated break marks it as the user’s own plan', async () => {
  const h = harness(), Component = h.component('PlannerForms', 'StopEditor'), saved = [];
  const stop = { id: 'break-one', title: 'Free time', start_time: '09:00', duration_minutes: 120, kind: 'break', locked: false };
  const view = await render(React.createElement(Component, { stop, date: '2026-11-01', days: [{ date: '2026-11-01', stops: [stop] }], busy: false, onSave: result => saved.push(result), onRemove() {}, onMove() {}, onSwap() {} }));
  await act(async () => view.root.findAllByType('TextInput').find(node => node.props.accessibilityLabel === 'Stop').props.onChangeText('Slow morning'));
  await click(view.root, 'Save changes'); assert.equal(saved[0].user_created, true); assert.equal(saved[0].locked, false); await dispose(view);
});

test('the nightly picker offers only saved accommodation and explicit selection does not imply a booking', async () => {
  const h = harness(), Component = h.component('PlannerDayParts', 'StayPicker'), selected = [];
  const ideas = [{ id: 'hotel', title: 'Saved riad', category: 'hotel', city: 'Marrakech' }, { id: 'food', title: 'Cafe', category: 'restaurant' }];
  const view = await render(React.createElement(Component, { ideas, busy: false, onChoose: value => selected.push(value) }));
  assert.match(allText(view.root), /doesn’t book it/); assert.doesNotMatch(allText(view.root), /Cafe/);
  await click(view.root, 'Choose Saved riad for this night'); assert.deepEqual(selected[0], { status: 'selected', idea_id: 'hotel', city: 'Marrakech' });
  await click(view.root, 'No accommodation needed this night'); assert.deepEqual(selected[1], { status: 'not_needed' }); await dispose(view);
});

test('missing or non-hotel stay suggestions remain honestly marked as accommodation needed', async () => {
  const h = harness(), Component = h.component('PlannerDayParts', 'StayRow');
  const view = await render(React.createElement(Component, { stay: { status: 'suggested', idea_id: 'food' }, ideas: [{ id: 'food', title: 'Cafe', category: 'restaurant' }] }));
  assert.match(allText(view.root), /Accommodation needed/); assert.doesNotMatch(allText(view.root), /Cafe/); await dispose(view);
});

test('stay uncertainty and distance reasons remain visible without parsing their wording', async () => {
  const h = harness(), Row = h.component('PlannerDayParts', 'StayRow'), Picker = h.component('PlannerDayParts', 'StayPicker');
  const ideas = [{ id: 'hotel', title: 'Saved riad', category: 'hotel', city: 'Marrakech' }];
  for (const reason of ['Saved in this city; confirm its location and availability.', 'This selected stay is far from the day’s plans.']) {
    const stay = { status: 'suggested', idea_id: 'hotel', reason };
    const rowView = await render(React.createElement(Row, { stay, ideas })); assert.ok(allText(rowView.root).includes(reason)); await dispose(rowView);
    const pickerView = await render(React.createElement(Picker, { stay, ideas, busy: false, onChoose() {} })); assert.ok(allText(pickerView.root).includes(reason)); await dispose(pickerView);
  }
});

test('primary planning actions keep a full-width target larger than the minimum tap size', async () => {
  const h = harness(), Component = h.component('PlannerKit', 'PlannerAction');
  const view = await render(React.createElement(Component, { label: 'Plan this trip', prominent: true, onPress() {} }));
  const style = Object.assign({}, ...button(view.root, 'Plan this trip').props.style.filter(Boolean));
  assert.equal(style.width, '100%'); assert.ok(style.minHeight >= 48); assert.equal(style.flexShrink, 0); await dispose(view);
});

test('Android planner sheets reveal focused inputs using their modal viewport and ignore late focus measurements', async () => {
  let focused, later; const movements = [];
  const input = { measureInWindow: callback => callback(0, 350, 300, 48) }; focused = input;
  const TextInput = Object.assign(props => React.createElement('TextInput', props), { State: { currentlyFocusedInput: () => focused } });
  const h = harness({}, { Keyboard: { isVisible: () => true }, TextInput }), Component = h.component('PlannerKit', 'PlannerSheet');
  const scroll = { getNativeScrollRef: () => ({ measureInWindow: callback => callback(0, 180, 400, 220) }), scrollTo: value => movements.push(value) };
  const view = await render(React.createElement(Component, { title: 'Edit this stop', onClose() {} }), { createNodeMock: element => element.type === 'ScrollView' ? scroll : null });
  assert.equal(view.root.findByType('KeyboardAvoidingView').props.behavior, 'height');
  const viewport = view.root.findByType('ScrollView');
  await act(async () => {
    viewport.props.onScroll({ nativeEvent: { contentOffset: { y: 30 } } });
    view.root.findByType('Modal').props.onShow();
    view.root.findAllByType('AnimatedView').find(node => node.props.accessibilityViewIsModal).props.onLayout({ nativeEvent: { layout: { height: 450 } } });
  });
  assert.deepEqual(movements, [{ y: 52, animated: false }], 'scroll only the overflow relative to the modal viewport');
  input.measureInWindow = callback => { later = callback; }; await act(async () => viewport.props.onFocus());
  focused = {}; await act(async () => later(0, 350, 300, 48)); assert.equal(movements.length, 1, 'an old field cannot move the new focus');
  await dispose(view);
});
