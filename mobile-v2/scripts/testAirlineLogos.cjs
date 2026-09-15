const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const ts = require('typescript');
const { test } = require('node:test');
const base = path.resolve(__dirname, '../src/components/world-window');
const catalog = require('../src/data/collections/airlines.json');
const svg = '<svg viewBox="0 0 80 80"><path d="M0 0H80V80H0Z" fill="#f00"/></svg>';
const flush = async () => { for (let i = 0; i < 20; i++) await Promise.resolve(); };
function load(file, mocks, globals = {}) {
  const code = ts.transpileModule(fs.readFileSync(path.join(base, file), 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.React, target: ts.ScriptTarget.ES2022, esModuleInterop: true } }).outputText;
  const module = { exports: {} };
  new Function('require', 'module', 'exports', ...Object.keys(globals), code)(name => {
    assert(name in mocks, `Unexpected dependency ${name}`); return mocks[name];
  }, module, module.exports, ...Object.values(globals));
  return module.exports;
}
function remote(fetch, more = {}) {
  return load('airlineLogoRemote.ts', { '../../data/collections/catalogs': { airlineCatalog: catalog } }, { fetch, ...more });
}
const response = (status = 200, text = svg) => ({ ok: status >= 200 && status < 300, status, text: async () => text });

test('95 bundled square assets preserve all recorded carriers and match verified provenance', () => {
  const directory = path.resolve(__dirname, '../assets/world-window/airlines');
  const codes = fs.readdirSync(directory).filter(name => /^[A-Z0-9]{2}\.png$/.test(name));
  assert.equal(codes.length, 95);
  for (const code of 'AA AM AT B6 BR DL EK ET F9 G4 IB NH NK SY UA WN Z2 KL QR SQ BA LH AF TK AS'.split(' ')) assert(codes.includes(`${code}.png`), `${code} available offline`);
  const requires = [...fs.readFileSync(path.join(base, 'airlineLogoAssets.ts'), 'utf8').matchAll(/airlines\/([A-Z0-9]{2}\.png)/g)].map(match => match[1]);
  assert.deepEqual(requires.sort(), codes.sort());
  const manifest = require('../assets/world-window/airlines/sources.json');
  assert.equal(manifest.entries.length, 78); assert.deepEqual(manifest.unavailable, []);
  for (const file of codes) {
    const bytes = fs.readFileSync(path.join(directory, file));
    assert(bytes.subarray(1, 4).equals(Buffer.from('PNG')));
    assert.equal(bytes.readUInt32BE(16), bytes.readUInt32BE(20), `${file} is square`);
    assert(bytes.readUInt32BE(16) >= 96);
  }
  for (const entry of manifest.entries) {
    const bytes = fs.readFileSync(path.join(directory, `${entry.code}.png`));
    assert.equal(crypto.createHash('sha256').update(bytes).digest('hex'), entry.sha256);
    assert(entry.sourceUrl.includes('/full-color-logo/')); assert(!entry.sourceUrl.includes('lockup'));
  }
});

test('lookup normalizes valid catalogue codes and never requests invalid or fictional carriers', async () => {
  const calls = [], api = remote(async url => { calls.push(url); return response(); });
  assert(api.airlineSymbolUrl(' kl ').endsWith('/KL.svg'));
  for (const code of ['', ' ../KL', 'KL?x=private', 'ZZ', '???', 'ABC']) { assert.equal(api.airlineSymbolUrl(code), undefined); assert.equal(await api.loadAirlineSymbol(code), null); }
  assert.deepEqual(calls, []);
});

test('identical in-flight symbols coalesce; a later mount uses the cached image', async () => {
  let finish, count = 0;
  const api = remote(() => { count++; return new Promise(resolve => { finish = resolve; }); });
  const a = api.loadAirlineSymbol('KL'), b = api.loadAirlineSymbol(' kl ');
  assert.strictEqual(a, b); assert.equal(count, 1); finish(response());
  assert.equal(await a, svg); assert.equal(await api.loadAirlineSymbol('KL'), svg); assert.equal(count, 1);
});

test('scrolling a long catalogue keeps a bounded LRU without retaining every downloaded symbol', async () => {
  let calls = 0;
  const api = remote(async () => { calls++; return response(); });
  const codes = catalog.entries.map(entry => entry.key).filter(code => code !== 'ZZ').slice(0, 100);
  for (const code of codes) await api.loadAirlineSymbol(code);
  assert.equal(calls, 100);
  assert.equal(api.cachedAirlineSymbol(codes[0]), undefined);
  assert.equal(api.cachedAirlineSymbol(codes[4]), svg);
  assert.equal(api.cachedAirlineSymbol(codes.at(-1)), svg);
  await api.loadAirlineSymbol(codes[0]); assert.equal(calls, 101, 'Evicted entries can be fetched again when revisited');
});

test('missing/offline assets keep a neutral tile, back off, and retry after expiry', async () => {
  let now = 1000, count = 0;
  const api = remote(async () => { count++; if (count === 1) throw new Error('offline'); return response(); }, { Date: { now: () => now } });
  assert.equal(await api.loadAirlineSymbol('KL'), null);
  assert.equal(await api.loadAirlineSymbol('KL'), null); assert.equal(count, 1);
  now += 60001; assert.equal(await api.loadAirlineSymbol('KL'), svg); assert.equal(count, 2);
  const missing = remote(async () => response(404)); assert.equal(await missing.loadAirlineSymbol('KL'), null);
});

test('symbol validation accepts local clipping/gradients and rejects unexpected active or external content', async () => {
  const api = remote(async () => response(200, '<html>Not found</html>'));
  assert(api.validAirlineSymbol(svg));
  assert(api.validAirlineSymbol('<svg><defs><path id="p" d="M0 0H2"/></defs><use href="#p" fill="url( #grad )"/></svg>'));
  for (const fragment of ['<script/>', '<image href="https://unrelated.test/i"/>', '<use href="https://unrelated.test/i"/>', '<path fill="url( https://unrelated.test/i )"/>', '<style>@import "https://unrelated.test/i";</style>', '<text>External font</text>', '<path onload="x"/>']) assert(!api.validAirlineSymbol(svg.replace('</svg>', `${fragment}</svg>`)));
  assert(!api.validAirlineSymbol(svg + ' '.repeat(128 * 1024)));
  assert.equal(await api.loadAirlineSymbol('KL'), null);
  const redirect = remote(async () => ({ ...response(), url: 'https://unrelated.test/image.svg' })); assert.equal(await redirect.loadAirlineSymbol('KL'), null);
});

test('only four requests run concurrently, and a stalled request releases its slot on timeout', async () => {
  const requests = [], timers = [];
  const api = remote((url, options) => new Promise((resolve, reject) => { requests.push({ url, resolve }); options.signal.addEventListener('abort', () => reject(new Error('timeout'))); }), {
    setTimeout: callback => { timers.push(callback); return timers.length; }, clearTimeout: () => {},
  });
  const pending = ['KL', 'QR', 'BA', 'LH', 'AF'].map(code => api.loadAirlineSymbol(code));
  assert.equal(requests.length, 4); timers[0](); await flush(); assert.equal(requests.length, 5);
  for (const request of requests.slice(1)) request.resolve(response());
  assert.deepEqual(await Promise.all(pending), [null, svg, svg, svg, svg]);
});

function componentHost(remoteApi) {
  const slots = []; let cursor = 0, effects = [], props;
  const react = { createElement: (type, props, ...children) => ({ type, props: { ...props, children } }),
    useState(value) { const index = cursor++; if (!(index in slots)) slots[index] = value; return [slots[index], next => { slots[index] = next; }]; },
    useEffect(fn, deps) { const index = cursor++, old = slots[index]; if (!old || deps.some((value, i) => value !== old.deps[i])) { old?.cleanup?.(); slots[index] = { deps }; effects.push(() => { slots[index].cleanup = fn(); }); } },
  };
  const { AirlineLogo } = load('AirlineLogo.tsx', { react, 'react-native': { Image: 'Image', View: 'View', Text: 'Text', StyleSheet: { create: value => value } }, 'react-native-svg': { SvgXml: 'SvgXml' }, '../../theme/trotterTheme': { colors: {}, fonts: {} }, './airlineLogoAssets': { bundledAirlineLogos: { NK: 17, UA: 15 } }, './airlineLogoRemote': remoteApi });
  return { render(next = props) { props = next; cursor = 0; const tree = AirlineLogo(props); const pending = effects; effects = []; pending.forEach(fn => fn()); return tree; }, unmount() { slots.forEach(slot => slot?.cleanup?.()); } };
}
const nodes = value => !value || typeof value !== 'object' ? [] : [value, ...Object.values(value).flatMap(nodes)];
test('bundled Spirit renders offline; a broken local asset preserves size and falls back safely', async () => {
  const loads = [];
  const h = componentHost({ normalizeAirlineCode: code => code.trim().toUpperCase(), cachedAirlineSymbol: () => undefined, loadAirlineSymbol: async code => { loads.push(code); return null; } });
  const image = h.render({ code: ' nk ', size: 30 }); assert.equal(image.type, 'Image'); assert.equal(image.props.source, 17); assert.deepEqual(loads, []);
  image.props.onError(); const tile = h.render(); assert.equal(tile.type, 'View'); assert.deepEqual(tile.props.style[1], { width: 30, height: 30 });
  await flush(); assert.deepEqual(loads, ['NK']);
  const next = h.render({ code: 'UA', size: 30 }); assert.equal(next.type, 'Image'); image.props.onError(); assert.equal(h.render().type, 'Image', 'A stale old failure cannot hide another airline'); h.unmount();
});

test('recycled rows never show the previous carrier or accept a stale late SVG response', async () => {
  const pending = {};
  const h = componentHost({ normalizeAirlineCode: code => code.trim().toUpperCase(), cachedAirlineSymbol: () => undefined, loadAirlineSymbol: code => new Promise(resolve => { pending[code] = resolve; }) });
  h.render({ code: 'KL', size: 30 }); h.render({ code: 'QR', size: 30 }); pending.KL(svg); await flush();
  assert(!nodes(h.render()).some(node => node.type === 'SvgXml'));
  pending.QR(svg.replace('#f00', '#600')); await flush(); const result = h.render();
  const mark = nodes(result).find(node => node.type === 'SvgXml'); assert(mark.props.xml.includes('#600')); assert(mark.props.fallback, 'Malformed SVG parsing has an explicit visible fallback');
  assert(!nodes(h.render({ code: 'BA', size: 30 })).some(node => node.type === 'SvgXml'), 'Previous logo disappears synchronously when code changes'); h.unmount(); pending.BA(svg); await flush();
});
