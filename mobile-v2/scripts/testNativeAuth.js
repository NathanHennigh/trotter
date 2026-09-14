const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
const { test } = require('node:test');
const serviceRoot = path.join(__dirname, '../src/services');
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };
const response = (status, body) => ({ status, ok: status >= 200 && status < 300, text: async () => JSON.stringify(body) });
const flush = async () => { for (let n = 0; n < 60; n += 1) await Promise.resolve(); };

function environment({ stored, plainStored = {}, os = 'android', fetcher, secureRead } = {}) {
  const secure = new Map(stored ? [['trotter.auth.v2', stored]] : []);
  const plain = new Map([['trotterAuthToken', 'legacy-personal-token'], ...Object.entries(plainStored)]);
  const session = new Map();
  const calls = [];
  const storage = map => ({ getItem: key => map.get(key) ?? null, setItem: (key, value) => map.set(key, value), removeItem: key => map.delete(key) });
  let browserResult;
  let nextToken = 'token-a';
  let fetchImpl = fetcher || (async (url, init) => response(200, url.endsWith('/auth/me')
    ? { user_id: init.headers.Authorization === 'Bearer token-b' ? 2 : 1, name: init.headers.Authorization === 'Bearer token-b' ? 'Blair Browser' : 'Alex Avery', email: 'owner@example.invalid' } : []));
  const slots = [];
  let cursor = 0;
  let effects = [];
  const same = (a, b) => a && b && a.length === b.length && a.every((value, index) => value === b[index]);
  const react = {
    createContext: () => ({}), createElement: () => ({}),
    useState(initial) { const index = cursor++; if (!(index in slots)) slots[index] = typeof initial === 'function' ? initial() : initial; return [slots[index], value => { slots[index] = typeof value === 'function' ? value(slots[index]) : value; }]; },
    useRef(value) { const index = cursor++; if (!(index in slots)) slots[index] = { current: value }; return slots[index]; },
    useCallback(fn, deps) { const index = cursor++; if (!slots[index] || !same(slots[index].deps, deps)) slots[index] = { fn, deps }; return slots[index].fn; },
    useEffect(fn, deps) { const index = cursor++; if (!slots[index] || !same(slots[index].deps, deps)) { slots[index]?.cleanup?.(); slots[index] = { deps }; effects.push(() => { slots[index].cleanup = fn(); }); } },
  };
  const web = {
    openAuthSessionAsync: async (start, redirect) => {
      calls.push({ kind: 'oauth', start, redirect });
      if (browserResult) return browserResult;
      const expected = new URL(start).searchParams.get('app_redirect_uri');
      return { type: 'success', url: `${expected}&token=${nextToken}` };
    },
    dismissAuthSession: () => calls.push({ kind: 'dismiss' }),
  };
  const native = { Platform: { OS: os } };
  const secureStore = {
    WHEN_UNLOCKED_THIS_DEVICE_ONLY: 'device-only',
    getItemAsync: secureRead || (async key => secure.get(key) ?? null),
    setItemAsync: async (key, value, options) => { calls.push({ kind: 'secure-write', options }); secure.set(key, value); },
    deleteItemAsync: async key => { secure.delete(key); },
  };
  const cache = new Map();
  const globals = {
    localStorage: storage(plain), sessionStorage: storage(session),
    location: { href: 'https://app.example.invalid/', origin: 'https://app.example.invalid', assign(url) { calls.push({ kind: 'navigate', url }); } },
    history: { replaceState() { calls.push({ kind: 'clean-url' }); } },
  };
  function load(name) {
    if (cache.has(name)) return cache.get(name).exports;
    const file = path.join(serviceRoot, `${name}.ts`);
    const source = fs.readFileSync(file, 'utf8');
    assert(!source.includes('realTravelSnapshot'), 'auth provider must not import a personal snapshot');
    const output = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, esModuleInterop: true, target: ts.ScriptTarget.ES2020 } }).outputText;
    const module = { exports: {} }; cache.set(name, module);
    const mockRequire = request => {
      if (request === 'react') return react;
      if (request === 'react-native') return native;
      if (request === 'expo-web-browser') return web;
      if (request === 'expo-crypto') return { randomUUID: () => 'test-attempt' };
      if (request === 'expo-secure-store') return secureStore;
      if (request === '@react-native-async-storage/async-storage') return { getItem: async key => plain.get(key) ?? null, setItem: async (key, value) => { plain.set(key, value); }, removeItem: async key => { plain.delete(key); } };
      if (request === './googleAuth') return load('googleAuth');
      if (request.includes('stampIdentity')) return { stampIdentity: () => ({ shape: 'circle', color: '#111' }) };
      if (request.includes('passport-arrivals')) return { buildPassportArrivals: () => [] };
      if (request.includes('countryArrivals')) return { firstCountryEntry: () => undefined, buildCountryArrivals: () => [] };
      if (request.includes('travelCountry')) return { travelCountry: country => ({ country }), SOMALILAND_ICON_KEY: '' };
      if (request.includes('tripItineraries')) return { groupTripItineraries: () => [] };
      throw new Error(`Unexpected auth dependency: ${request}`);
    };
    new Function('module', 'exports', 'require', 'fetch', 'process', '__DEV__', 'globalThis', `${output}\n${name === 'travelTrips' ? 'module.exports.testState = useTravelTripsState; module.exports.testMapApiSegment = mapApiSegment;' : ''}`)(
      module, module.exports, mockRequire, async (url, init) => { calls.push({ kind: 'fetch', url, token: init.headers.Authorization }); return fetchImpl(url, init); },
      { env: { EXPO_PUBLIC_TROTTER_API_URL: 'https://api.example.invalid', EXPO_PUBLIC_TROTTER_AUTH_TOKEN: 'must-ignore-build-token' } }, false, globals);
    return module.exports;
  }
  const auth = load('googleAuth');
  const travel = load('travelTrips');
  return {
    auth, travel, secure, plain, session, calls, globals, secureStore,
    token: value => { nextToken = value; },
    browserResult: value => { browserResult = value; },
    fetcher: value => { fetchImpl = value; },
    render() { cursor = 0; const value = travel.testState(); const pending = effects; effects = []; pending.forEach(fn => fn()); return value; },
    dispose() { slots.forEach(slot => slot?.cleanup?.()); },
  };
}

test('native callback requires exact target, attempt, and one token', () => {
  const { auth } = environment();
  const expected = 'trotterv2://oauthredirect?attempt=one';
  assert.equal(auth.readOAuthCallbackToken(`${expected}&token=valid`, expected), 'valid');
  for (const invalid of [
    'evil://oauthredirect?attempt=one&token=bad', 'trotterv2://oauthredirect.evil?attempt=one&token=bad',
    'trotterv2://oauthredirect/extra?attempt=one&token=bad', 'trotterv2://oauthredirect?attempt=two&token=bad',
    'trotterv2://oauthredirect?attempt=one&attempt=two&token=bad', `${expected}&token=a&token=b`,
    `${expected}&token=a#token=b`, `${expected}&token=`,
  ]) assert.throws(() => auth.readOAuthCallbackToken(invalid, expected), /sign-in|Google/);
});

test('native auth uses ephemeral browser session and preserves nonce in signed redirect', async () => {
  const env = environment();
  assert.equal(await env.auth.requestGoogleAuthToken('https://api.example.invalid'), 'token-a');
  const call = env.calls.find(call => call.kind === 'oauth');
  assert.equal(new URL(call.start).searchParams.get('app_redirect_uri'), 'trotterv2://oauthredirect?attempt=test-attempt');
  assert.equal(call.redirect, 'trotterv2://oauthredirect');
  env.browserResult({ type: 'cancel' });
  await assert.rejects(env.auth.requestGoogleAuthToken('https://api.example.invalid'), env.auth.GoogleSignInCanceled);
});

test('signed-out startup is empty and ignores embedded credentials', async () => {
  const env = environment();
  assert.equal(env.render().authStatus, 'loading');
  await flush();
  const state = env.render();
  assert.equal(state.authStatus, 'signed-out');
  assert.deepEqual(state.trips, []);
  assert.equal(state.profile.flights, 0);
  assert.equal(state.profile.name, 'Traveler');
  assert.equal(state.accountEmail, undefined);
  assert.equal(env.calls.filter(call => call.kind === 'fetch').length, 0);
  assert.equal(env.plain.size, 0);
  env.dispose();
});

test('validated account supplies profile, secure storage, and sign-out clears all local data', async () => {
  const env = environment(); env.render(); await flush();
  await env.render().signIn(); await flush();
  const state = env.render();
  assert.equal(state.authStatus, 'signed-in');
  assert.equal(state.accountId, 1);
  assert.equal(state.profile.name, 'Alex Avery');
  assert.equal(state.profile.homeAirport, '');
  assert.equal(state.profile.firstFlightDate, '');
  assert.equal(JSON.parse(env.secure.get('trotter.auth.v2')).apiBaseUrl, 'https://api.example.invalid');
  assert.equal(env.calls.find(call => call.kind === 'secure-write').options.keychainAccessible, 'device-only');
  await state.signOut(); await flush();
  assert.equal(env.render().authStatus, 'signed-out');
  assert.equal(env.render().accountId, undefined);
  assert.equal(env.render().lastSyncedAt, undefined);
  assert.deepEqual(env.render().trips, []);
  assert.equal(env.secure.size, 0);
  env.dispose();
});

test('a 401 from profile clears the session even when trips returned 200', async () => {
  const env = environment({ stored: JSON.stringify({ token: 'expired', apiBaseUrl: 'https://api.example.invalid' }), fetcher: async url => response(url.endsWith('/auth/me') ? 401 : 200, []) });
  env.render(); await flush();
  assert.equal(env.render().authStatus, 'signed-out');
  assert.match(env.render().error, /expired/);
  assert.equal(env.travel.getStoredToken(), undefined);
  assert.equal(env.secure.size, 0);
  assert.deepEqual(env.render().trips, []);
  env.dispose();
});

test('late old-account trip responses cannot populate the next account', async () => {
  const older = deferred();
  const env = environment({ fetcher: async (url, init) => {
    const first = init.headers.Authorization === 'Bearer token-a';
    if (url.endsWith('/trips') && first) return older.promise;
    return response(200, url.endsWith('/auth/me') ? { user_id: first ? 1 : 2, name: first ? 'Alex' : 'Blair', email: first ? 'alex@example.invalid' : 'blair@example.invalid' } : []);
  } });
  env.render(); await flush(); await env.render().signIn(); await flush();
  await env.render().signOut(); env.token('token-b');
  await env.render().signIn(); await flush();
  assert.equal(env.render().accountId, 2);
  older.resolve(response(200, [{ id: 99, segments: [{ id: 3, dep_airport: 'IAH', arr_airport: 'MCO', dep_time: '2026-01-01T10:00:00Z', arr_time: '2026-01-01T12:00:00Z' }] }]));
  await flush();
  assert.equal(env.render().accountId, 2);
  assert.equal(env.render().profile.name, 'Blair');
  assert.deepEqual(env.render().trips, []);
  env.dispose();
});

test('an in-flight secure read cannot resurrect a signed-out account', async () => {
  const read = deferred();
  const env = environment({ secureRead: () => read.promise });
  const hydrate = env.travel.hydrateStoredToken();
  await flush();
  await env.travel.clearAuthToken();
  read.resolve(JSON.stringify({ token: 'old', apiBaseUrl: 'https://api.example.invalid' }));
  assert.equal(await hydrate, undefined);
  assert.equal(env.travel.getStoredToken(), undefined);
});

test('saved token from a different server is discarded without making an API request', async () => {
  const env = environment({ stored: JSON.stringify({ token: 'wrong-account', apiBaseUrl: 'https://another.example.invalid' }) });
  env.render(); await flush();
  assert.equal(env.render().authStatus, 'signed-out');
  assert.equal(env.secure.size, 0);
  assert.equal(env.calls.filter(call => call.kind === 'fetch').length, 0);
  env.dispose();
});

test('network errors show retry state without personal snapshot fallback', async () => {
  const env = environment({ stored: JSON.stringify({ token: 'saved', apiBaseUrl: 'https://api.example.invalid' }), fetcher: async () => { throw new TypeError('offline'); } });
  env.render(); await flush();
  assert.equal(env.render().authStatus, 'signed-out');
  assert.equal(env.render().status, 'error');
  assert.match(env.render().error, /connection/);
  assert.deepEqual(env.render().trips, []);
  env.dispose();
});

test('web rejects unsolicited and unrelated callbacks and scrubs tokens', () => {
  const env = environment({ os: 'web' });
  env.globals.location.href = 'https://app.example.invalid/anything#token=bad';
  assert.equal(env.auth.consumeWebOAuthCallback(), undefined);
  env.globals.location.href = 'https://app.example.invalid/oauthredirect#token=bad';
  assert.throws(() => env.auth.consumeWebOAuthCallback(), /Start sign-in/);
  assert.equal(env.calls.filter(call => call.kind === 'clean-url').length, 1);
  assert.equal(env.travel.getStoredToken(), undefined);
});

test('cancel invalidates a late browser success instead of accepting its token', async () => {
  const env = environment();
  const browser = deferred();
  env.browserResult(browser.promise);
  const pending = env.auth.requestGoogleAuthToken('https://api.example.invalid');
  env.auth.cancelGoogleAuthSession();
  browser.resolve({ type: 'success', url: 'trotterv2://oauthredirect?attempt=test-attempt&token=late' });
  await assert.rejects(pending, env.auth.GoogleSignInCanceled);
  assert.equal(env.travel.getStoredToken(), undefined);
});

test('signed-in Gmail sync retains import polling and final trip refresh', async () => {
  const env = environment({ fetcher: async url => {
    if (url.endsWith('/auth/me')) return response(200, { user_id: 1, name: 'Alex', email: 'alex@example.invalid' });
    if (url.endsWith('/ingest/gmail/import')) return response(200, { job_id: 'job-one' });
    if (url.endsWith('/ingest/jobs/job-one')) return response(200, { state: 'done', parsed_count: 1, segment_count: 1 });
    return response(200, []);
  } });
  env.render(); await flush(); await env.render().signIn(); await flush();
  await env.render().syncFromGmail(); await flush();
  assert.equal(env.render().authStatus, 'signed-in');
  assert.equal(env.render().status, 'idle');
  assert(env.calls.some(call => call.kind === 'fetch' && call.url.endsWith('/ingest/jobs/job-one')));
  assert(env.calls.filter(call => call.kind === 'fetch' && call.url.endsWith('/trips')).length >= 2);
  env.dispose();
});

test('signing out during import launch prevents stale job polling', async () => {
  const pendingImport = deferred();
  const env = environment({ fetcher: async url => url.endsWith('/ingest/gmail/import') ? pendingImport.promise : response(200,
    url.endsWith('/auth/me') ? { user_id: 1, name: 'Alex', email: 'alex@example.invalid' } : []) });
  env.render(); await flush(); await env.render().signIn(); await flush();
  const sync = env.render().syncFromGmail();
  await env.render().signOut();
  pendingImport.resolve(response(200, { job_id: 'old-account-job' }));
  await sync; await flush();
  assert.equal(env.render().authStatus, 'signed-out');
  assert(!env.calls.some(call => call.kind === 'fetch' && call.url.includes('/ingest/jobs/')));
  env.dispose();
});

test('endpoint country metadata survives missing map coordinates', () => {
  const env = environment();
  const segment = env.travel.testMapApiSegment({ id: 1, dep_airport: 'AMS', arr_airport: 'DXB', dep_time: '2026-01-01T10:00:00Z', arr_time: '2026-01-01T17:00:00Z',
    meta_json: { enrichment: { airports: { departure: { country_name: 'Netherlands', country_code: 'NL' }, arrival: { countryName: 'United Arab Emirates', countryCode: 'AE' } } } } });
  assert.equal(segment.depCountry, 'Netherlands');
  assert.equal(segment.depCountryCode, 'NL');
  assert.equal(segment.arrCountry, 'United Arab Emirates');
  assert.equal(segment.arrCountryCode, 'AE');
  assert.equal(segment.depPoint, undefined);
  assert.equal(segment.arrPoint, undefined);
});

const itinerary = (id, count) => ({ id, title: 'Synthetic trip', segments: Array.from({ length: count }, (_, n) => ({ id: id * 10 + n, dep_airport: 'LHR', arr_airport: 'SIN', dep_time: `2026-09-${String(n + 1).padStart(2, '0')}T10:00:00Z`, arr_time: `2026-09-${String(n + 1).padStart(2, '0')}T18:00:00Z` })) });
const identityResponse = () => response(200, { user_id: 1, email: 'alex@example.invalid' });
async function signedInArchive() {
  const env = environment({ fetcher: async url => url.endsWith('/auth/me') ? identityResponse() : response(200, [itinerary(1, 1), itinerary(2, 1)]) });
  env.render(); await flush(); await env.render().signIn(); await flush();
  return env;
}

test('late trip detail cannot overwrite a newer refresh or resurrect a removed trip', async () => {
  const env = await signedInArchive(), detail = deferred();
  env.fetcher(async url => url.endsWith('/trips/1') ? detail.promise : url.endsWith('/auth/me') ? identityResponse() : response(200, [itinerary(1, 2), itinerary(2, 1)]));
  const pending = env.render().loadTripDetail(1);
  await env.render().refresh();
  detail.resolve(response(200, itinerary(1, 1)));
  assert.equal((await pending).segments.length, 2);
  assert.equal(env.render().trips.find(t => t.backendId === 1).segments.length, 2);
  const deleted = deferred();
  env.fetcher(async url => url.endsWith('/trips/1') ? deleted.promise : url.endsWith('/auth/me') ? identityResponse() : response(200, [itinerary(2, 1)]));
  const pendingDeleted = env.render().loadTripDetail(1); await env.render().refresh();
  deleted.resolve(response(200, itinerary(1, 2)));
  assert.equal(await pendingDeleted, undefined);
  assert.deepEqual(env.render().trips.map(t => t.backendId), [2]); env.dispose();
});

test('older full refresh preserves a newer detail and concurrent trip reads stay independent', async () => {
  const env = await signedInArchive(), full = deferred(), oldDetail = deferred();
  env.fetcher(async url => url.endsWith('/auth/me') ? identityResponse() : url.endsWith('/trips') ? full.promise : response(200, itinerary(Number(url.split('/').at(-1)), 3)));
  const refresh = env.render().refresh();
  await env.render().loadTripDetail(1);
  full.resolve(response(200, [itinerary(1, 1), itinerary(2, 1)])); await refresh;
  assert.equal(env.render().trips.find(t => t.backendId === 1).segments.length, 3);
  env.fetcher(async () => oldDetail.promise);
  const old = env.render().loadTripDetail(1);
  env.fetcher(async url => response(200, itinerary(Number(url.split('/').at(-1)), 4)));
  await Promise.all([env.render().loadTripDetail(1), env.render().loadTripDetail(2)]);
  oldDetail.resolve(response(200, itinerary(1, 2)));
  assert.equal((await old).segments.length, 4);
  assert(env.render().trips.every(t => t.segments.length === 4)); env.dispose();
});

test('failed secure logout blocks hydration and sign-in until retry, including a cold restart', async () => {
  const env = await signedInArchive();
  env.secureStore.deleteItemAsync = async () => { throw Error('Synthetic locked keystore'); };
  await env.render().signOut();
  const state = env.render();
  assert.equal(state.signOutPending, true); assert.equal(state.authStatus, 'signed-out');
  assert.deepEqual(state.trips, []); assert.equal(state.accountId, undefined);
  assert.equal(env.plain.get('trotter.auth.clear-pending'), '1');
  await assert.rejects(env.travel.hydrateStoredToken(), /Retry sign out/);
  const oauthCount = env.calls.filter(c => c.kind === 'oauth').length;
  await state.signIn(); assert.equal(env.calls.filter(c => c.kind === 'oauth').length, oauthCount);
  const restart = environment({ stored: env.secure.get('trotter.auth.v2'), plainStored: Object.fromEntries(env.plain) });
  restart.render(); await flush();
  assert.equal(restart.render().signOutPending, true);
  assert.equal(restart.calls.filter(c => c.kind === 'fetch').length, 0);
  await restart.render().signOut(); await flush();
  assert.equal(restart.render().signOutPending, false); assert.equal(restart.secure.size, 0);
  assert.equal(restart.plain.has('trotter.auth.clear-pending'), false);
  await restart.render().signIn(); await flush(); assert.equal(restart.render().authStatus, 'signed-in');
  env.dispose(); restart.dispose();
});

test('Gmail import status is independent of archive refresh and clears on account logout', async () => {
  const env = await signedInArchive(); assert.equal(env.render().gmailSyncStatus, 'unknown');
  env.fetcher(async url => url.endsWith('/ingest/gmail/import') ? response(200, { job_id: 'synthetic' }) : response(200, { state: 'failed', error_message: 'No Google account linked' }));
  await env.render().syncFromGmail();
  assert.equal(env.render().gmailSyncStatus, 'error');
  assert.equal(env.render().gmailSyncError, 'No Google account linked');
  env.fetcher(async url => url.endsWith('/auth/me') ? identityResponse() : response(200, [itinerary(1, 1)]));
  await env.render().refresh();
  assert.equal(env.render().gmailSyncStatus, 'error'); assert.equal(env.render().gmailSyncError, 'No Google account linked');
  env.fetcher(async url => url.endsWith('/auth/me') ? identityResponse() : url.endsWith('/ingest/gmail/import') ? response(200, { job_id: 'synthetic' }) : url.includes('/ingest/jobs/') ? response(200, { state: 'done' }) : response(200, [itinerary(1, 1)]));
  await env.render().syncFromGmail();
  assert.equal(env.render().gmailSyncStatus, 'synced'); assert.equal(env.render().gmailSyncError, undefined); assert(env.render().lastGmailSyncedAt);
  await env.render().signOut(); assert.equal(env.render().gmailSyncStatus, 'unknown'); assert.equal(env.render().lastGmailSyncedAt, undefined); env.dispose();
});
