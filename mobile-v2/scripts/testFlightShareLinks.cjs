const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
const source = fs.readFileSync(path.join(__dirname, '../src/services/flightShareLinks.ts'), 'utf8');
const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, esModuleInterop: true, target: ts.ScriptTarget.ES2020 } }).outputText;
const token = 'a'.repeat(43), nextToken = 'b'.repeat(43);
const api = 'https://api.trotter.example', app = 'https://app.trotter.example';
const key = 'trotter.pending-flight-invitation.v1';
const flush = async () => { for (let n = 0; n < 40; n++) await Promise.resolve(); };

function environment({ saved, initial = null, delayedRead = false } = {}) {
  const storage = new Map(saved ? [[key, saved]] : []);
  const slots = []; let cursor = 0, effects = [], listener, finishRead;
  const same = (a, b) => a && b && a.length === b.length && a.every((v, i) => Object.is(v, b[i]));
  const react = {
    createContext: value => ({ Provider: 'provider', value }), createElement: (type, props) => ({ type, props }),
    useState(initial) { const i = cursor++; if (!(i in slots)) slots[i] = { value: typeof initial === 'function' ? initial() : initial }; return [slots[i].value, next => { slots[i].value = typeof next === 'function' ? next(slots[i].value) : next; }]; },
    useRef(value) { const i = cursor++; return slots[i] ??= { current: value }; },
    useCallback(fn, deps) { const i = cursor++; if (!slots[i] || !same(slots[i].deps, deps)) slots[i] = { fn, deps }; return slots[i].fn; },
    useEffect(fn, deps) { const i = cursor++; if (!slots[i] || !same(slots[i].deps, deps)) effects.push(() => { slots[i]?.cleanup?.(); slots[i] = { deps, cleanup: fn() }; }); },
  };
  const module = { exports: {} };
  const requireMock = name => {
    if (name === 'react') return react;
    if (name === 'react-native') return { Platform: { OS: 'android' }, Linking: {
      addEventListener: (_name, fn) => { listener = fn; return { remove() {} }; }, getInitialURL: async () => initial,
    } };
    if (name === './travelTrips') return { getApiBaseUrl: () => api };
    if (name === 'expo-secure-store') return {
      WHEN_UNLOCKED_THIS_DEVICE_ONLY: 'device-only',
      getItemAsync: () => delayedRead ? new Promise(resolve => { finishRead = resolve; }) : Promise.resolve(storage.get(key) ?? null),
      setItemAsync: async (k, v, options) => { assert.equal(options.keychainAccessible, 'device-only'); storage.set(k, v); },
      deleteItemAsync: async k => { storage.delete(k); },
    };
    throw new Error(name);
  };
  new Function('module', 'exports', 'require', code)(module, module.exports, requireMock);
  return {
    ...module.exports, storage,
    render() { cursor = 0; effects = []; const tree = module.exports.FlightInvitationProvider({ children: null }); effects.forEach(fn => fn()); return tree.props.value; },
    receive: value => listener({ url: value }), finishRead: value => finishRead(value),
    dispose: () => slots.forEach(slot => slot?.cleanup?.()),
  };
}

test('only trusted invitation URLs are accepted; OAuth and arbitrary token URLs are rejected', () => {
  const { parseFlightShareLink: parse } = environment();
  assert.equal(parse(`trotterv2://flight-share?token=${token}`, api), token);
  assert.equal(parse(`${api}/travel-sharing/open#token=${token}`, api), token);
  assert.equal(parse(`${app}/#flight-invitation=${token}`, api, app), token);
  for (const bad of [
    `trotterv2://oauthredirect?token=${token}`, `trotterv2://flight-share.evil?token=${token}`,
    `trotterv2://flight-share/extra?token=${token}`, `trotterv2://user@flight-share?token=${token}`,
    `trotterv2://flight-share?token=${token}&token=${nextToken}`, `trotterv2://flight-share?token=${token}#token=${token}`,
    `trotterv2://flight-share?token=${token}&redirect=evil`, `${api}/travel-sharing/open?token=${token}`,
    `https://evil.example/travel-sharing/open#token=${token}`, `${api}.evil/travel-sharing/open#token=${token}`,
    `${app}/oauthredirect#token=${token}`, `${app}/#token=${token}`, `http://api.trotter.example/travel-sharing/open#token=${token}`,
    'trotterv2://flight-share?token=short', `trotterv2://flight-share?token=${'%20'.repeat(43)}`,
  ]) assert.equal(parse(bad, api, app), undefined, bad);
});

test('stored invitations expire and malformed pointers cannot block launch', () => {
  const { readPendingFlightInvitation: read } = environment();
  const now = 2000000000;
  assert.equal(read(JSON.stringify({ token, receivedAt: now - 1000 }), now).token, token);
  for (const value of [null, '{', '{}', JSON.stringify({ token, receivedAt: now + 1 }), JSON.stringify({ token, receivedAt: now - 14 * 86400000 }), JSON.stringify({ token: 'bad', receivedAt: now })]) assert.equal(read(value, now), undefined);
});

test('cold invitation is saved securely and restored through sign-in or process restart', async () => {
  const first = environment({ initial: `trotterv2://flight-share?token=${token}` });
  assert.equal(first.render().ready, false); await flush();
  assert.equal(first.render().token, token);
  const raw = first.storage.get(key); assert.equal(JSON.parse(raw).token, token);
  first.dispose();
  const restored = environment({ saved: raw }); restored.render(); await flush();
  assert.equal(restored.render().token, token);
  restored.render().consume(token); await flush();
  assert.equal(restored.render().token, undefined); assert.equal(restored.storage.has(key), false);
  restored.dispose();
});

test('a newer live link wins over delayed storage and a stale consume cannot erase it', async () => {
  const old = JSON.stringify({ token, receivedAt: Date.now() });
  const env = environment({ delayedRead: true, initial: `trotterv2://flight-share?token=${token}` });
  env.render(); env.receive(`trotterv2://flight-share?token=${nextToken}`); env.finishRead(old); await flush();
  assert.equal(env.render().token, nextToken);
  env.render().consume(token); await flush();
  assert.equal(env.render().token, nextToken);
  assert.equal(JSON.parse(env.storage.get(key)).token, nextToken);
  env.dispose();
});
