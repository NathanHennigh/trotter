// Execute the production preference store with offline storage/haptic adapters.
const assert = require('node:assert/strict');
const { test } = require('node:test');
const fs = require('node:fs'), path = require('node:path'), ts = require('typescript');
const flush = async () => { for (let i = 0; i < 12; i++) await Promise.resolve(); };
function store({ raw = null, delayed = false, failRead = false, failWrite = false, platform = 'android' } = {}) {
  let current, resolveRead, effect, reads = 0;
  const writes = [], ticks = [], clock = { now: () => 1000 };
  const react = {
    useState(value) { current ??= value; return [current, value => { current = value; }]; },
    useEffect(fn) { if (!effect) effect = fn(); },
  };
  const deps = {
    react,
    '@react-native-async-storage/async-storage': {
      getItem: () => { reads++; return failRead ? Promise.reject(Error('offline')) : delayed ? new Promise(resolve => { resolveRead = resolve; }) : Promise.resolve(raw); },
      setItem: async (key, value) => { writes.push([key, JSON.parse(value)]); if (failWrite) throw Error('full'); },
    },
    'react-native': { Platform: { OS: platform } },
    'expo-haptics': { ImpactFeedbackStyle: { Light: 'light' }, impactAsync: async strength => ticks.push(strength), selectionAsync: async () => ticks.push('selection') },
  };
  const source = fs.readFileSync(path.join(__dirname, '../src/utils/experiencePreferences.ts'), 'utf8');
  const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, esModuleInterop: true, target: ts.ScriptTarget.ES2022 } }).outputText;
  const module = { exports: {} };
  new Function('require', 'module', 'exports', 'Date', code)(name => { assert(name in deps, name); return deps[name]; }, module, module.exports, clock);
  return { hook: module.exports.useExperiencePreferences, tick: module.exports.selectionHaptic, writes, ticks,
    resolve: value => resolveRead(value), get reads() { return reads; }, advance: value => { clock.now = () => value; } };
}
test('stored NASA and disabled tactile feedback survive a new session without a write', async () => {
  const state = store({ raw: JSON.stringify({ texture: 'nasa', haptics: false }) });
  state.hook(); await flush();
  assert.equal(state.hook().texture, 'nasa'); assert.equal(state.hook().haptics, false);
  state.tick('page'); assert.equal(state.ticks.length, 0); assert.equal(state.writes.length, 0); assert.equal(state.reads, 1);
});
test('a preference changed before hydration preserves the other stored preference', async () => {
  const state = store({ delayed: true });
  state.hook().setHaptics(false);
  state.resolve(JSON.stringify({ texture: 'nasa', haptics: true })); await flush();
  assert.equal(state.hook().texture, 'nasa'); assert.equal(state.hook().haptics, false);
  assert.deepEqual(state.writes.at(-1)[1], { texture: 'nasa', haptics: false });
});
test('rapid changes serialize in order and retain the final choice', async () => {
  const state = store(); state.hook(); await flush();
  state.hook().setTexture('nasa'); state.hook().setHaptics(false); state.hook().setTexture('classic'); await flush();
  assert.deepEqual(state.writes.map(entry => entry[1]), [{ texture: 'nasa', haptics: true }, { texture: 'nasa', haptics: false }, { texture: 'classic', haptics: false }]);
});
test('storage failures and malformed preferences leave controls usable', async () => {
  for (const options of [{ failRead: true }, { raw: '{bad' }, { raw: 'null' }, { failWrite: true }]) {
    const state = store(options); state.hook(); await flush();
    state.hook().setTexture('nasa'); await flush(); assert.equal(state.hook().texture, 'nasa');
  }
});
test('feedback occurs only after hydration and respects throttling, opt-out and web', async () => {
  const state = store(); state.tick('page'); assert.equal(state.ticks.length, 0);
  state.hook(); await flush(); state.tick('page'); state.tick('selection'); assert.deepEqual(state.ticks, ['light']);
  state.advance(1100); state.tick('confirmation'); assert.deepEqual(state.ticks, ['light', 'selection']);
  state.hook().setHaptics(false); state.advance(1200); state.tick('page'); assert.equal(state.ticks.length, 2);
  const web = store({ platform: 'web' }); web.hook(); await flush(); web.tick('page'); assert.equal(web.ticks.length, 0);
});
