const assert = require('node:assert/strict');
const { test } = require('node:test');
const fs = require('node:fs'), path = require('node:path'), ts = require('typescript'), THREE = require('three');
const root = path.resolve(__dirname, '..');
const compile = file => ts.transpileModule(fs.readFileSync(path.join(root, file), 'utf8'), { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.React, esModuleInterop: true } }).outputText;
function moduleAt(file, requireLocal, globals = {}) {
  const mod = { exports: {} };
  new Function('module', 'exports', 'require', ...Object.keys(globals), compile(file))(mod, mod.exports, requireLocal, ...Object.values(globals));
  return mod.exports;
}
const flush = async () => { for (let i = 0; i < 15; i++) await Promise.resolve(); };
function texture(width = 4096) {
  const value = new THREE.Texture(); value.image = { width, height: width / 2 }; value.disposals = 0;
  value.addEventListener('dispose', () => value.disposals++); return value;
}
function assetHarness() {
  const pending = [], timers = new Map(); let timerId = 0;
  class Loader { load(asset, onLoad, _progress, onError) { const value = texture(); pending.push({ asset, value, resolve: () => onLoad(value), reject: onError }); return value; } }
  const api = moduleAt('src/components/world-window/globeAssets.ts', name => name === 'three' ? THREE : { ExpoTextureLoader: Loader }, {
    setTimeout: callback => { const id = ++timerId; timers.set(id, callback); return id; }, clearTimeout: id => timers.delete(id),
  });
  return { ...api, pending, timers };
}

test('texture retry releases failed attempts, resolves exactly once and leaves no timeout', async () => {
  const h = assetHarness(), loading = h.loadGlobeTexture(10), first = h.pending.shift();
  first.reject(new Error('Temporary copy failure')); await flush(); assert.equal(first.value.disposals, 1);
  const second = h.pending.shift(); second.resolve(); assert.strictEqual(await loading, second.value); assert.equal(h.timers.size, 0);
  first.resolve(); assert.equal(first.value.disposals, 1, 'A late callback cannot double dispose or resurrect the failed texture');
  second.value.dispose();
});
test('aborting an outstanding texture prevents retries and cleans a late native callback', async () => {
  const h = assetHarness(), abort = new AbortController(), loading = h.loadGlobeTexture(10, abort.signal), pending = h.pending.shift();
  abort.abort(); await assert.rejects(loading, { name: 'AbortError' }); pending.resolve(); await flush();
  assert.equal(pending.value.disposals, 1); assert.equal(h.pending.length, 0); assert.equal(h.timers.size, 0);
});
test('a missing native callback has a bounded timeout instead of hanging initialization forever', async () => {
  const h = assetHarness(), loading = h.loadGlobeTexture(10, undefined, 1), pending = h.pending.shift();
  [...h.timers.values()][0](); await assert.rejects(loading, /timed out/); pending.resolve();
  assert.equal(pending.value.disposals, 1); assert.equal(h.timers.size, 0);
});
test('base images recover independently with fallback and preserve actual mask dimensions', async () => {
  const h = assetHarness(), requests = [], values = [];
  const sources = { day: { primary: 1, fallback: 11 }, night: { primary: 2, fallback: 12 }, index: { primary: 3, fallback: 13 } };
  const result = await h.loadGlobeBaseTextures(sources, new AbortController().signal, async asset => {
    requests.push(asset); if (asset === 3) throw Error('Cannot decode large mask'); const value = texture(asset === 13 ? 2048 : 4096); values.push(value); return value;
  });
  assert.deepEqual(requests, [1, 2, 3, 13]); assert.equal(result.index.image.width, 2048); assert(values.every(value => value.disposals === 0));
  values.forEach(value => value.dispose());
});
test('fatal base failure releases both completed and late sibling textures', async () => {
  const h = assetHarness(), pending = [], abort = new AbortController();
  const load = asset => new Promise((resolve, reject) => pending.push({ asset, resolve, reject }));
  const promise = h.loadGlobeBaseTextures({ day: { primary: 1, fallback: 1 }, night: { primary: 2, fallback: 2 }, index: { primary: 3, fallback: 3 } }, abort.signal, load);
  const day = texture(), lateNight = texture(); pending[0].resolve(day); await flush(); pending[2].reject(Error('Missing index'));
  await assert.rejects(promise, /Missing index/); assert.equal(day.disposals, 1);
  pending[1].resolve(lateNight); await flush(); assert.equal(lateNight.disposals, 1);
});

function nativeAssetHarness() {
  const files = new Set(), assets = new Map(); let copies = 0, checks = 0, sizeReads = 0, failNext = false;
  class Asset {
    constructor(id) { this.uri = `drawable-${id}`; this.localUri = this.uri; this.downloaded = true; this.width = 4096; this.height = 2048; }
    static fromModule(id) { if (!assets.has(id)) assets.set(id, new Asset(id)); return assets.get(id); }
    static fromURI(uri) { return Asset.fromModule(uri); }
    async downloadAsync() { copies++; if (failNext) { failNext = false; throw Error('Synthetic asset copy failure'); } await Promise.resolve(); this.localUri = `file:///cache/${this.uri}.jpg`; this.downloaded = true; files.add(this.localUri); return this; }
  }
  const api = moduleAt('src/lib/expoThree.ts', name => {
    if (name === 'three') return THREE;
    if (name === 'expo-asset') return { Asset };
    if (name === 'expo-file-system/legacy') return { getInfoAsync: async uri => { checks++; return { exists: files.has(uri) }; } };
    if (name === 'react-native') return { Platform: { OS: 'android' }, Image: { getSize: (_uri, success) => { sizeReads++; success(4096, 2048); } } };
    throw Error(name);
  });
  const load = id => new Promise((resolve, reject) => new api.ExpoTextureLoader().load(id, resolve, undefined, reject));
  return { Asset, files, load, fail: () => failNext = true, counts: () => ({ copies, checks, sizeReads }) };
}
test('native source resolution copies drawable resources once and coalesces concurrent texture loads', async () => {
  const h = nativeAssetHarness(), [a, b] = await Promise.all([h.load(1), h.load(1)]);
  assert.equal(h.counts().copies, 1); assert.notStrictEqual(a, b, 'Texture ownership remains per renderer');
  assert.strictEqual(a.image.data, b.image.data); assert(a.image.data.localUri.startsWith('file://'));
  await h.load(1); assert.equal(h.counts().copies, 1); assert.equal(h.counts().checks, 1);
});
test('an OS-cleared file is recopied even if Expo still marks the source downloaded', async () => {
  const h = nativeAssetHarness(); await h.load(1); h.files.clear(); assert.equal(h.Asset.fromModule(1).downloaded, true);
  const loaded = await h.load(1); assert.equal(h.counts().copies, 2); assert(h.files.has(loaded.image.data.localUri));
});
test('failed asset resolutions do not poison the next retry and discovered dimensions are reused', async () => {
  const h = nativeAssetHarness(); h.fail(); await assert.rejects(h.load(1), /copy failure/);
  const asset = h.Asset.fromModule(1); asset.width = asset.height = undefined;
  await h.load(1); await h.load(1); assert.equal(h.counts().copies, 2); assert.equal(h.counts().sizeReads, 1);
});

function globeHarness() {
  const slots = [], pending = [], renderers = [], frames = new Map(), nativeEvents = new Map(); let cursor = 0, effects = [], frameId = 0, props, tree;
  const same = (a, b) => a && b && a.length === b.length && a.every((value, i) => Object.is(value, b[i]));
  const React = { createElement: (type, props, ...children) => ({ type, props: { ...props, children } }),
    useRef: value => { const i = cursor++; return slots[i] ??= { current: value }; },
    useState: initial => { const i = cursor++; slots[i] ??= { value: typeof initial === 'function' ? initial() : initial }; return [slots[i].value, next => slots[i].value = typeof next === 'function' ? next(slots[i].value) : next]; },
    useMemo: (fn, deps) => { const i = cursor++; if (!slots[i] || !same(slots[i].deps, deps)) slots[i] = { value: fn(), deps }; return slots[i].value; },
    useCallback: (fn, deps) => React.useMemo(() => fn, deps),
    useEffect: (fn, deps) => { const i = cursor++; if (!slots[i] || !same(slots[i].deps, deps)) effects.push(() => { slots[i]?.cleanup?.(); slots[i] = { deps, cleanup: fn() }; }); },
  };
  class Renderer {
    constructor() { this.capabilities = { getMaxAnisotropy: () => 4 }; this.disposals = this.draws = 0; renderers.push(this); }
    setSize() {} setClearColor() {} dispose() { this.disposals++; }
    render() { if (this.failure) throw this.failure; this.draws++; }
  }
  const api = moduleAt('src/components/world-window/WorldWindowGlobe.tsx', name => {
    if (name === 'react') return React; if (name === 'three') return THREE;
    if (name === 'react-native') return { ...Object.fromEntries(['View', 'Text', 'Pressable'].map(name => [name, name])), StyleSheet: { create: value => value }, PanResponder: { create: panHandlers => ({ panHandlers }) },
      AppState: { currentState: 'active', addEventListener: (event, callback) => { nativeEvents.set(event, callback); return { remove() { nativeEvents.delete(event); } }; } },
      AccessibilityInfo: { isReduceMotionEnabled: async () => false, addEventListener: () => ({ remove() {} }) } };
    if (name === 'expo-gl') return { GLView: 'GLView' };
    if (name.includes('expoThree')) return { ExpoRenderer: Renderer };
    if (name === './globeAssets') return { loadGlobeBaseTextures: (_sources, signal) => new Promise((resolve, reject) => pending.push({ signal, resolve, reject })), loadGlobeTexture: async () => texture() };
    if (name === './globe-geography') return { globeCountries: [], sunPosition: () => ({ lat: 0, lon: 0 }) };
    if (name === './routeSelection') return { flightPathKey: () => '' };
    if (name.includes('trotterTheme')) return { colors: { paperSoft: '#faf4e8' }, fonts: {} };
    if (name.includes('DetailTiles')) return { [name.split('/').pop()]: [] };
    if (/\.(jpg|png)$/.test(name)) return 1;
    throw Error(name);
  }, { requestAnimationFrame: callback => { const id = ++frameId; frames.set(id, callback); return id; }, cancelAnimationFrame: id => frames.delete(id), console: { warn() {} } });
  const render = next => { props = next ?? props; cursor = 0; effects = []; tree = api.WorldWindowGlobe(props); effects.forEach(fn => fn()); return tree; };
  const gl = () => ({ pixelStorei() {}, drawingBufferWidth: 390, drawingBufferHeight: 800, getParameter: () => 4096, endFrameEXP() {} });
  const textures = () => ({ day: texture(), night: texture(), index: texture() });
  return { pending, renderers, frames, render, textures, gl, initial: { active: true, routes: [], visited: [], mapStyle: 'classic', cycle: false, onClear() {}, onRoute() {}, onCountry() {} },
    step(time = 16) { const [id, callback] = frames.entries().next().value; frames.delete(id); callback(time); },
    unmount: () => slots.forEach(slot => slot?.cleanup?.()),
    background: state => nativeEvents.get('change')?.(state),
  };
}
function find(tree, type) { if (!tree || typeof tree !== 'object') return undefined; if (Array.isArray(tree)) return tree.map(node => find(node, type)).find(Boolean); return tree.type === type ? tree : find(tree.props.children, type); }
test('base loading gates first draw and tab/background return reuses the same renderer and textures', async () => {
  const h = globeHarness(); let view = h.render(h.initial); view.props.onLayout({ nativeEvent: { layout: { width: 390, height: 800 } } });
  const first = find(view, 'GLView'), creating = first.props.onContextCreate(h.gl()); assert.equal(h.frames.size, 0);
  const base = h.textures(); h.pending.shift().resolve(base); await creating; h.step(); assert.equal(h.renderers[0].draws, 1);
  view = h.render({ ...h.initial, active: false }); assert.equal(h.frames.size, 0); assert.equal(h.renderers[0].disposals, 0); assert(Object.values(base).every(t => t.disposals === 0));
  view = h.render(h.initial); assert.equal(find(view, 'GLView').props.key, first.props.key); assert.equal(h.pending.length, 0); assert.equal(h.frames.size, 1); h.step();
  h.background('background'); assert.equal(h.frames.size, 0); h.background('active'); assert.equal(h.frames.size, 1); assert.equal(h.renderers.length, 1);
  h.unmount(); assert.equal(h.frames.size, 0); assert.equal(h.renderers[0].disposals, 1); assert(Object.values(base).every(t => t.disposals === 1));
});
test('replacement context and unmount cannot be corrupted by a late initialization callback', async () => {
  const h = globeHarness(), view = h.render(h.initial), create = find(view, 'GLView').props.onContextCreate;
  const first = create(h.gl()), old = h.pending.shift(), second = create(h.gl()), current = h.pending.shift();
  assert.equal(old.signal.aborted, true); assert.equal(h.renderers[0].disposals, 1);
  const currentTextures = h.textures(); current.resolve(currentTextures); await second;
  const oldTextures = h.textures(); old.resolve(oldTextures); await first;
  assert(Object.values(oldTextures).every(t => t.disposals === 1)); assert(Object.values(currentTextures).every(t => t.disposals === 0)); assert.equal(h.renderers[1].disposals, 0); assert.equal(h.frames.size, 1);
  h.unmount(); assert.equal(h.renderers[1].disposals, 1); assert(Object.values(currentTextures).every(t => t.disposals === 1));
});
test('initialization automatically recovers once; persistent failure exposes a working manual retry', async () => {
  const h = globeHarness(); let view = h.render(h.initial); const creating = find(view, 'GLView').props.onContextCreate(h.gl());
  h.pending.shift().reject(Error('Synthetic fatal asset failure')); await creating; view = h.render();
  assert.equal(find(view, 'GLView').props.key, 1); assert.equal(find(view, 'Pressable'), undefined); assert.equal(h.renderers[0].disposals, 1); assert.equal(h.frames.size, 0);
  const recovering = find(view, 'GLView').props.onContextCreate(h.gl()); h.pending.shift().reject(Error('Persistent file failure')); await recovering; view = h.render();
  assert.equal(find(view, 'GLView'), undefined); assert.equal(h.renderers[1].disposals, 1);
  find(view, 'Pressable').props.onPress(); view = h.render(); assert.equal(find(view, 'GLView').props.key, 2);
  const retry = find(view, 'GLView').props.onContextCreate(h.gl()), base = h.textures(); h.pending.shift().resolve(base); await retry; h.step(); assert.equal(h.renderers[2].draws, 1);
  h.unmount(); assert(Object.values(base).every(t => t.disposals === 1));
});
test('a first-frame upload failure gets one automatic context recovery, never an infinite remount loop', async () => {
  const h = globeHarness(); let view = h.render(h.initial);
  const creating = find(view, 'GLView').props.onContextCreate(h.gl()), first = h.textures(); h.pending.shift().resolve(first); await creating;
  h.renderers[0].failure = Error('Synthetic upload failure'); h.step(); view = h.render();
  assert.equal(find(view, 'GLView').props.key, 1); assert(Object.values(first).every(t => t.disposals === 1)); assert.equal(h.frames.size, 0);
  const recovering = find(view, 'GLView').props.onContextCreate(h.gl()), second = h.textures(); h.pending.shift().resolve(second); await recovering; h.step(); assert.equal(h.renderers[1].draws, 1);
  h.renderers[1].failure = Error('Persistent GL failure'); h.step(); view = h.render();
  assert.equal(find(view, 'GLView'), undefined); assert(find(view, 'Pressable')); assert.equal(h.frames.size, 0); assert(Object.values(second).every(t => t.disposals === 1));
  h.unmount(); assert.equal(h.renderers.length, 2);
});
test('an initialization failure after leaving Home waits to recover until Home is visible', async () => {
  const h = globeHarness(); let view = h.render(h.initial);
  const creating = find(view, 'GLView').props.onContextCreate(h.gl()); h.render({ ...h.initial, active: false });
  h.pending.shift().reject(Error('Failure while away')); await creating; view = h.render(); assert.equal(find(view, 'GLView').props.key, 0); assert.equal(h.frames.size, 0);
  h.render(h.initial); view = h.render(); assert.equal(find(view, 'GLView').props.key, 1); assert.equal(h.renderers.length, 1, 'Only the native remount may create a replacement renderer');
  h.unmount();
});
