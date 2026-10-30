const assert = require('node:assert/strict'), { test } = require('node:test');
const fs = require('node:fs'), path = require('node:path'), ts = require('typescript');
const React = require('react'), Renderer = require('react-test-renderer');
global.IS_REACT_ACT_ENVIRONMENT = true;
const pending = () => { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b; }); return { promise, resolve, reject }; };
function load(relative, mocks = {}) {
  const source = ts.transpileModule(fs.readFileSync(path.join(__dirname, '..', relative), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.React, esModuleInterop: true, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const m = { exports: {} };
  new Function('require', 'module', 'exports', source)(name => { assert(name in mocks, `Unexpected ${name}`); return mocks[name]; }, m, m.exports);
  return m.exports;
}
const native = { View: 'View', Text: 'Text', ScrollView: 'ScrollView', TextInput: 'TextInput', ActivityIndicator: 'ActivityIndicator', KeyboardAvoidingView: 'KeyboardAvoidingView', RefreshControl: 'RefreshControl', Platform: { OS: 'web' }, StyleSheet: { create: v => v }, BackHandler: { addEventListener: () => ({ remove() {} }) } };
const text = node => typeof node === 'string' ? node : (node.children || []).map(text).join('');
const allText = root => root.findAllByType('Text').map(text).join('\n');
const button = (root, label) => root.findAllByType('Pressable').find(node => text(node) === label || node.props.accessibilityLabel === label) || assert.fail(`Missing ${label}`);
const click = async (root, label) => React.act(async () => { const node = button(root, label); assert(!node.props.disabled, `${label} is disabled`); node.props.onPress(); });
const edit = async (root, name, value) => React.act(async () => root.findAllByType('TextInput').find(node => node.props.accessibilityLabel === name).props.onChangeText(value));
const close = async view => React.act(async () => view.unmount());
const baseIdentity = () => ({ aliases: [], primary_name: 'Alex Morgan', confirmed: false, onboarding_completed: false, recovery: null });
const presentation = load('src/components/world-window/profile/travelNamePresentation.ts');
const flight = (id, name, patch = {}) => ({ id, passenger_name: name, assigned_passenger_name: null, status: 'retained', reason: 'other_traveler', shareable: true, flight: { pnr: 'BOOK01', dep_airport: 'DFW', arr_airport: 'LHR', travel_date: '2026-09-09', flight_number: 'AA50' }, ...patch });

test('names preserve Unicode and airline formatting, normalize whitespace, and omit duplicates', () => {
  assert.deepEqual(presentation.prepareTravelNames([' Alex  Morgan ', 'Élodie O’Neill', 'Élodie O’Neill', 'MAGNO/ELISHAFAITH', '田中 花子', ' Ａｌｅｘ Ｂｌａｋｅ '], 'Alex Morgan'), { aliases: ['Élodie O’Neill', 'MAGNO/ELISHAFAITH', '田中 花子', 'Alex Blake'] });
  assert(presentation.prepareTravelNames(['person@example.com'], 'Alex Morgan').error);
  assert(presentation.prepareTravelNames(['123'], 'Alex Morgan').error);
  assert(presentation.prepareTravelNames(['x'.repeat(101)], 'Alex Morgan').error);
  assert(presentation.prepareTravelNames(Array.from({ length: 21 }, (_, i) => `Alex ${String.fromCharCode(65 + i)}`), 'Primary Name').error);
  assert(presentation.prepareTravelNames([' '], null).error);
  assert.deepEqual(presentation.prepareTravelNames([], 'Alex Morgan'), { aliases: [] });
});
test('self claim uses original evidence only, never assigned names, unnamed tickets or mixed travelers', () => {
  assert.equal(presentation.claimableTravelName([flight('blank', null, { assigned_passenger_name: 'Alex Morgan' })]), undefined);
  assert.equal(presentation.claimableTravelName([flight('cancel', 'Alex Blake', { status: 'canceled' })]), undefined);
  assert.equal(presentation.claimableTravelName([flight('owned', 'Alex Blake', { status: 'belongs_to_you' })]), undefined);
  assert.equal(presentation.claimableTravelName([flight('a', 'Alex Blake'), flight('b', 'Someone Else')]), undefined);
  assert.deepEqual(presentation.claimableTravelName([flight('original', 'BLAKE/ALEX', { assigned_passenger_name: 'Changed Name' })]), { itemId: 'original', name: 'BLAKE/ALEX' });
});
test('recovery copy distinguishes queued, running, completed and retryable failure', () => {
  const job = { state: 'queued', checked: 0, added: 0, needs_review: 0 };
  assert.match(presentation.recoveryMessage(job).detail, /background/);
  assert.match(presentation.recoveryMessage({ ...job, state: 'running', checked: 18 }).detail, /18/);
  assert.match(presentation.recoveryMessage({ ...job, state: 'completed', added: 2 }).title, /2 flights recovered/);
  assert.match(presentation.recoveryMessage({ ...job, state: 'completed' }).detail, /No additional/);
  assert.match(presentation.recoveryMessage({ ...job, state: 'failed' }).detail, /couldn’t finish/);
});

function serviceHarness() {
  let revision = 1, token = 'token-a'; const subscribers = new Set();
  const auth = { getAuthRevision: () => revision, getStoredToken: () => token, getApiBaseUrl: () => 'https://api.example.invalid', hydrateStoredToken: async () => token,
    subscribeAuthToken: listener => { subscribers.add(listener); return () => subscribers.delete(listener); },
    clearAuthToken: async () => { revision++; token = undefined; subscribers.forEach(fn => fn()); }, useTravelTrips: () => ({}) };
  const module = load('src/services/travelIdentity.tsx', { react: React, 'react-native': { AppState: {} }, './travelTrips': auth });
  return { ...module, change: () => { revision++; token = 'token-b'; subscribers.forEach(fn => fn()); }, subscribers, token: () => token };
}
test('identity API sends explicit confirmation and exact original self-claim evidence', async () => {
  const h = serviceHarness(), old = global.fetch, requests = [];
  global.fetch = async (url, options) => { requests.push({ url, ...options }); return { ok: true, status: 200, text: async () => JSON.stringify(baseIdentity()) }; };
  try {
    await h.travelIdentityApi.saveNames(['Alex Blake']); await h.travelIdentityApi.claimSelf('item/a', 'BLAKE/ALEX'); await h.travelIdentityApi.completeOnboarding();
    assert.equal(requests[0].method, 'PUT'); assert.deepEqual(JSON.parse(requests[0].body), { aliases: ['Alex Blake'], confirmed: true });
    assert.equal(requests[1].url, 'https://api.example.invalid/ingest/travel-inbox/item%2Fa/claim-self');
    assert.deepEqual(JSON.parse(requests[1].body), { passenger_name: 'BLAKE/ALEX' }); assert.deepEqual(JSON.parse(requests[2].body), {});
    assert.equal(requests.every(r => r.headers.Authorization === 'Bearer token-a'), true); assert.equal(h.subscribers.size, 0);
  } finally { global.fetch = old; }
});
test('identity responses are discarded on account change and expired credentials are cleared', async () => {
  const h = serviceHarness(), old = global.fetch;
  try {
    global.fetch = async () => { h.change(); return { ok: true, status: 200, text: async () => JSON.stringify(baseIdentity()) }; };
    await assert.rejects(h.travelIdentityApi.get(), /account changed/); assert.equal(h.subscribers.size, 0);
    global.fetch = async () => ({ ok: false, status: 401, text: async () => '{}' });
    await assert.rejects(h.travelIdentityApi.get(), /session expired/); assert.equal(h.token(), undefined);
  } finally { global.fetch = old; }
});

function screenHarness(kind, options = {}) {
  const calls = [], state = { identity: options.identity === null ? undefined : { ...baseIdentity(), ...options.identity }, loading: options.identity === null, saving: false, error: undefined,
    saveNames: async names => { calls.push(['save', names]); if (options.save) return options.save(names); return { ...state.identity, aliases: names, confirmed: true }; },
    refresh: async () => {}, retryRecovery: async () => {}, claimSelf: async (id, name) => { calls.push(['claim', id, name]); return { ...baseIdentity(), recovery: { id: 'job1', state: 'queued' } }; } };
  const account = { accountId: 'account1', accountName: options.accountName === null ? undefined : 'Alex Morgan', accountEmail: 'alex@example.invalid', gmailConnected: false, gmailConnecting: false, gmailSyncStatus: 'idle',
    connectGmail: () => { calls.push(['connect']); return options.connect?.() || Promise.resolve(); }, cancelGmailConnection: () => calls.push(['cancel']), refresh: async () => {} };
  const mocks = { react: React, 'react-native': native, 'react-native-safe-area-context': { useSafeAreaInsets: () => ({ top: 20, bottom: 20 }) },
    '../theme/trotterTheme': { colors: {}, fonts: {} }, '../components/world-window/WorldWindowUI': { WWHeader: props => React.createElement('Header', props), WWIcon: 'Icon' }, '../components/world-window/motion': { PressFeedback: 'Pressable' },
    '../components/world-window/profile/TravelRecoveryStatus': { TravelRecoveryStatus: () => React.createElement('Recovery') }, '../components/world-window/profile/travelNamePresentation': presentation,
    '../services/travelIdentity': { useTravelIdentity: () => state }, '../services/travelTrips': { useTravelTrips: () => account } };
  if (kind === 'FlightSharingScreen') Object.assign(mocks, {
    'expo-crypto': { randomUUID: () => 'id' }, '../utils/experiencePreferences': { selectionHaptic() {} },
    '../components/world-window/sharing/flightSharingPresentation': load('src/components/world-window/sharing/flightSharingPresentation.ts'),
    '../services/flightSharing': { flightSharing: { inbox: async () => ({ items: options.items || [], incoming: [], outgoing: [] }) } },
  });
  const Component = load(`src/screens/${kind}.tsx`, mocks)[kind];
  const props = { onSaved: async identity => { calls.push(['done', identity]); await options.finish?.(); }, onDone: async () => { calls.push(['done']); await options.finish?.(); }, onSkip: async () => { calls.push(['skip']); await options.skip?.(); }, onBack: () => calls.push(['back']), onboarding: true };
  return { state, account, calls, Component, props, async render() { let view; await React.act(async () => { view = Renderer.create(React.createElement(Component, props)); }); return view; }, async update(view) { await React.act(async () => view.update(React.createElement(Component, props))); } };
}
test('travel names form adds and removes aliases without overwriting unsaved edits on a recovery refresh', async () => {
  const h = screenHarness('TravelNamesScreen', { identity: { aliases: ['Alex Blake'] } }), view = await h.render();
  await edit(view.root, 'Travel name 1', 'Alex Avery');
  h.state.identity = { ...h.state.identity, aliases: ['Stale Name'] }; await h.update(view);
  assert.equal(view.root.findByType('TextInput').props.value, 'Alex Avery');
  await click(view.root, 'Add a previous or other name'); await edit(view.root, 'Travel name 2', 'Alex Morgan');
  await click(view.root, 'Confirm names');
  assert.deepEqual(h.calls[0], ['save', ['Alex Avery']]); assert.equal(h.calls[1][0], 'done');
  await click(view.root, 'Remove Alex Avery'); assert.equal(view.root.findAllByType('TextInput').length, 1); await close(view);
});
test('no account name requires a real name, while optional skip never confirms names', async () => {
  const h = screenHarness('TravelNamesScreen', { accountName: null, identity: { primary_name: null } }), view = await h.render();
  await click(view.root, 'Confirm names'); assert.match(allText(view.root), /Enter at least one/); assert.equal(h.calls.length, 0);
  await click(view.root, 'Not now'); assert.deepEqual(h.calls, [['skip']]); assert.doesNotMatch(allText(view.root), /Traveler$/m); await close(view);
});
test('names loading never allows saving empty aliases over existing names', async () => {
  const h = screenHarness('TravelNamesScreen', { identity: null }), view = await h.render();
  assert.equal(button(view.root, 'Confirm names').props.disabled, true); await click(view.root, 'Not now'); assert.deepEqual(h.calls, [['skip']]); await close(view);
});
test('save cannot be duplicated and failure completing onboarding remains visible and retryable', async () => {
  const wait = pending(); const h = screenHarness('TravelNamesScreen', { save: async names => { await wait.promise; return { ...baseIdentity(), aliases: names }; }, finish: async () => { throw new Error('Could not finish setup'); } }), view = await h.render();
  const onPress = button(view.root, 'Confirm names').props.onPress;
  await React.act(async () => { onPress(); onPress(); }); assert.equal(h.calls.filter(c => c[0] === 'save').length, 1);
  await React.act(async () => wait.resolve()); assert.match(allText(view.root), /Could not finish setup/); assert(!button(view.root, 'Confirm names').props.disabled); await close(view);
});
test('Gmail connection unlocks Continue without waiting for scan completion or starting a second scan', async () => {
  const scan = pending(), h = screenHarness('GmailSetupScreen', { connect: () => scan.promise }), view = await h.render();
  await click(view.root, 'Connect Gmail'); h.account.gmailConnected = true; h.account.gmailConnecting = true; h.account.gmailSyncStatus = 'syncing'; await h.update(view);
  assert.match(allText(view.root), /background/); await click(view.root, 'Continue to Trotter');
  assert.deepEqual(h.calls, [['connect'], ['done']]); await close(view); scan.resolve();
});
test('Not now cancels a pending Gmail connection and awaits durable skip errors', async () => {
  const h = screenHarness('GmailSetupScreen', { skip: async () => { throw new Error('Offline. Try again.'); } }), view = await h.render();
  h.account.gmailConnecting = true; await h.update(view); await click(view.root, 'Not now');
  assert.deepEqual(h.calls, [['cancel'], ['skip']]); assert.match(allText(view.root), /Offline/); await close(view);
});
test('This is me requires a separate confirmation and submits original ticket name', async () => {
  const h = screenHarness('FlightSharingScreen', { items: [flight('evidence', 'BLAKE/ALEX')] }), view = await h.render();
  await click(view.root, 'Prepare flights for BLAKE/ALEX'); await click(view.root, 'This is me: BLAKE/ALEX');
  assert.equal(h.calls.length, 0); assert.match(allText(view.root), /future imports/);
  await click(view.root, 'Go back'); assert.equal(h.calls.length, 0);
  await click(view.root, 'This is me: BLAKE/ALEX'); await click(view.root, 'Yes, this is me');
  assert.deepEqual(h.calls, [['claim', 'evidence', 'BLAKE/ALEX']]); await close(view);
});
test('unnamed tickets cannot be claimed just by assigning an owner name', async () => {
  const h = screenHarness('FlightSharingScreen', { items: [flight('unnamed', null, { assigned_passenger_name: 'Alex Morgan' })] }), view = await h.render();
  await click(view.root, 'Prepare flights for Alex Morgan'); assert.equal(view.root.findAllByType('Pressable').some(node => text(node) === 'This is me'), false); await close(view);
});

function providerHarness() {
  const account = { accountId: 'a', accountRevision: 1, refresh: async () => { refreshCount++; } }; let refreshCount = 0, exposed, appState;
  const module = load('src/services/travelIdentity.tsx', { react: React, 'react-native': { AppState: { currentState: 'active', addEventListener: (_, fn) => { appState = fn; return { remove() {} }; } } }, './travelTrips': { useTravelTrips: () => account } });
  function Consumer() { exposed = module.useTravelIdentity(); return null; }
  const element = () => React.createElement(module.TravelIdentityProvider, null, React.createElement(Consumer));
  return { module, account, get value() { return exposed; }, get refreshCount() { return refreshCount; }, appState: state => appState(state), async render() { let view; await React.act(async () => { view = Renderer.create(element()); }); return view; }, async update(view) { await React.act(async () => view.update(element())); } };
}
test('background recovery polls without overlapping slow requests and refreshes Trips once after completion', async () => {
  const oldSet = global.setInterval, oldClear = global.clearInterval, timers = new Set();
  global.setInterval = fn => { timers.add(fn); return fn; }; global.clearInterval = fn => timers.delete(fn);
  const h = providerHarness(); let getCount = 0; const slow = pending();
  const queued = { ...baseIdentity(), recovery: { id: 'job-a', state: 'queued', checked: 0, added: 0, existing: 0, needs_review: 0, error: null } };
  h.module.travelIdentityApi.get = async () => { getCount++; return getCount === 1 ? queued : slow.promise; };
  let view;
  try {
    view = await h.render(); assert.equal(timers.size, 1);
    const poll = [...timers][0]; await React.act(async () => { poll(); poll(); }); assert.equal(getCount, 2);
    assert.equal(h.value.identity.recovery.state, 'queued'); assert.equal(h.value.loading, false);
    await React.act(async () => slow.resolve({ ...queued, recovery: { ...queued.recovery, state: 'completed', added: 3 } }));
    assert.equal(h.refreshCount, 1); assert.equal(timers.size, 0);
    await React.act(async () => h.value.refresh()); assert.equal(h.refreshCount, 1);
    await close(view);
  } finally { global.setInterval = oldSet; global.clearInterval = oldClear; }
});
test('late GET cannot replace a saved name, and account switch cannot apply another account mutation', async () => {
  const h = providerHarness(), read = pending(), write = pending(); let reads = 0;
  h.module.travelIdentityApi.get = async () => { reads++; return reads === 1 ? read.promise : baseIdentity(); };
  h.module.travelIdentityApi.saveNames = async aliases => aliases.includes('Slow Name') ? write.promise : { ...baseIdentity(), aliases, confirmed: true };
  const view = await h.render();
  await React.act(async () => h.value.saveNames(['Alex Blake']));
  await React.act(async () => read.resolve(baseIdentity())); assert.deepEqual(h.value.identity.aliases, ['Alex Blake']);
  let mutation;
  await React.act(async () => { mutation = h.value.saveNames(['Slow Name']).catch(error => error); });
  h.account.accountId = 'b'; h.account.accountRevision = 2; await h.update(view);
  await React.act(async () => write.resolve({ ...baseIdentity(), aliases: ['Private Name'] }));
  assert.match((await mutation).message, /account changed/); assert.deepEqual(h.value.identity.aliases, []); assert.equal(h.value.saving, false); await close(view);
});
