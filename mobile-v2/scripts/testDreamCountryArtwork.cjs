const assert = require('node:assert/strict');
const { test } = require('node:test');
const fs = require('node:fs'), path = require('node:path'), ts = require('typescript');
const directory = path.resolve(__dirname, '../src/components/world-window/dreams');
function load(name, mocks = {}, globals = {}) {
  const file = path.join(directory, name), module = { exports: {} };
  const compiled = ts.transpileModule(fs.readFileSync(file, 'utf8'), { fileName: file, compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } }).outputText;
  new Function('module', 'exports', 'require', ...Object.keys(globals), compiled)(module, module.exports, request => {
    if (request in mocks) return mocks[request];
    if (/\.(png|webp)$/.test(request)) return path.resolve(path.dirname(file), request);
    throw Error('Unexpected dependency: ' + request);
  }, ...Object.values(globals));
  return module.exports;
}
const artwork = load('countryArtwork.ts'), sources = load('dreamImageSource.ts');
const base = 'https://api.trotter.test';
const item = (thumbnailUrl, country = 'Japan') => ({ id: 'one', country, city: 'Tokyo', placeName: 'A saved café', category: 'cafe', thumbnailUrl });

if (process.argv.includes('--assets')) test('every catalog entry has its final bundled WebP asset', () => {
  for (const record of artwork.countryArtworkCatalog) {
    const bytes = fs.readFileSync(record.source);
    assert.equal(bytes.toString('ascii', 0, 4), 'RIFF');
    assert.equal(bytes.toString('ascii', 8, 12), 'WEBP');
    assert(bytes.length > 1000, record.code + ' must contain a real image');
  }
});

test('16 reusable country covers match exact country names, ISO2/3 codes and normalized aliases', () => {
  assert.equal(artwork.countryArtworkCatalog.length, 16);
  const aliases = new Map();
  for (const record of artwork.countryArtworkCatalog) {
    for (const value of [record.code, record.country, ...record.aliases]) {
      assert.equal(artwork.findCountryArtwork(`  ${value.toUpperCase()}  `)?.code, record.code);
      const key = artwork.normalizeArtworkCountry(value);
      assert(!aliases.has(key) || aliases.get(key) === record.code, 'Aliases cannot silently select another country');
      aliases.set(key, record.code);
    }
    assert.equal(path.basename(record.source), record.code + '.webp');
  }
  for (const [value, code] of [['Türkiye', 'TR'], ['México', 'MX'], ['U.S.A.', 'US'], ['Viet  Nam', 'VN'], ['United-Kingdom', 'GB']]) assert.equal(artwork.findCountryArtwork(value)?.code, code);
  for (const value of [undefined, '', 'Unsorted', 'Bali', 'Paris', 'Georgia', 'Japan and Thailand', 'New Mexico', 'Singapore restaurant', 'Atlantis']) assert.equal(artwork.findCountryArtwork(value), undefined, 'Unrecognized countries/cities must keep their real thumbnail fallback');
});

test('thumbnail authentication is restricted to the exact API origin and thumbnail path', () => {
  assert.deepEqual(sources.resolveDreamThumbnail('/dream-items/41/thumbnail', base), { uri: base + '/dream-items/41/thumbnail', privateImage: true });
  assert.equal(sources.resolveDreamThumbnail('https://api.trotter.test/dream-items/41/thumbnail', base).privateImage, true);
  assert.equal(sources.resolveDreamThumbnail('/dream-items/41/thumbnail', base + '/v1/').uri, base + '/v1/dream-items/41/thumbnail');
  for (const raw of ['https://cdn.instagram.test/cover.jpg', 'https://api.trotter.test.evil/dream-items/41/thumbnail', 'http://api.trotter.test/dream-items/41/thumbnail', 'https://api.trotter.test/public/cover.jpg']) assert.equal(sources.resolveDreamThumbnail(raw, base).privateImage, false);
  for (const raw of ['javascript:alert(1)', 'file:///private/photo.png', 'data:image/png;base64,abc', '//outside.test/image.png', 'https://api.trotter.test@outside.test/image.png']) assert.equal(sources.resolveDreamThumbnail(raw, base), undefined);
  const items = [item(undefined), item('javascript:no'), item('/dream-items/3/thumbnail'), item('https://cdn.test/good.png')];
  assert.equal(sources.postcardReelCover(items, base), items[2]);
  assert.equal(sources.postcardReelCover([], base), undefined);
});

function photoEnvironment(platform = 'web') {
  let cursor = 0, slots = [], effects = [], token = 'account-a', revision = 1, respond = async () => ({ ok: true, blob: async () => ({}) });
  const requests = [], revoked = [], created = [];
  const same = (a, b) => a && b && a.length === b.length && a.every((v, i) => v === b[i]);
  const react = {
    useState(initial) { const i = cursor++; if (!(i in slots)) slots[i] = initial; return [slots[i], next => { slots[i] = typeof next === 'function' ? next(slots[i]) : next; }]; },
    useEffect(fn, deps) { const i = cursor++; if (!slots[i] || !same(slots[i].deps, deps)) { slots[i]?.cleanup?.(); slots[i] = { deps }; effects.push(() => { slots[i].cleanup = fn(); }); } },
    useSyncExternalStore: () => revision,
  };
  const auth = { getApiBaseUrl: () => base, getStoredToken: () => token, getAuthRevision: () => revision, subscribeAuthToken: () => () => {} };
  class TestURL extends URL { static createObjectURL() { const value = 'blob:test-' + created.length; created.push(value); return value; } static revokeObjectURL(uri) { revoked.push(uri); } }
  const jsx = (type, props, key) => ({ type, props, key });
  const module = load('DreamPhoto.tsx', {
    react, 'react/jsx-runtime': { jsx, jsxs: jsx },
    'react-native': { Image: 'Image', View: 'View', Text: 'Text', Platform: { OS: platform }, StyleSheet: { create: s => s, absoluteFillObject: {}, absoluteFill: {} } },
    'react-native-svg': { default: 'Svg', Path: 'Path' }, '../../../services/travelTrips': auth,
    '../../../theme/trotterTheme': { colors: {}, fonts: {} }, '../WorldWindowUI': { WWIcon: 'Icon' }, './placeSymbols': { placeSymbol: () => 'place', symbolPaths: { place: [] } },
    './countryArtwork': artwork, './dreamImageSource': sources,
  }, { fetch: async (uri, init) => { requests.push({ uri, init }); return respond(uri, init); }, URL: TestURL });
  return {
    requests, revoked, created,
    respond(fn) { respond = fn; },
    account(next) { token = next; revision++; },
    render(props) { cursor = 0; const tree = module.DreamPhoto(props); const pending = effects; effects = []; pending.forEach(fn => fn()); return tree; },
    dispose() { slots.forEach(s => s?.cleanup?.()); },
  };
}
function image(tree) {
  if (!tree || typeof tree !== 'object') return undefined;
  if (tree.type === 'Image') return tree;
  const children = tree.props?.children;
  return (Array.isArray(children) ? children : [children]).map(image).find(Boolean);
}
const flush = async () => { for (let i = 0; i < 20; i++) await Promise.resolve(); };

test('country postcards prefer offline artwork and request the reel only if artwork fails', async () => {
  const env = photoEnvironment(), props = { item: item('/dream-items/1/thumbnail'), fallbackCountry: 'Japan', artworkForCountry: 'JP' };
  const cover = image(env.render(props));
  assert.equal(cover.props.source, artwork.findCountryArtwork('Japan').source);
  assert.equal(env.requests.length, 0, 'A country cover must not fetch a private reel it will not display');
  cover.props.onError(); env.render(props); await flush();
  const fallback = image(env.render(props));
  assert(fallback.props.source.uri.startsWith('blob:test-'));
  assert.equal(env.requests.length, 1);
  assert.equal(env.requests[0].init.headers.Authorization, 'Bearer account-a');
  env.dispose(); assert.deepEqual(env.revoked, env.created, 'Private thumbnail object URLs are released');
});

test('individual saved places keep their actual photos even when country artwork exists', () => {
  const env = photoEnvironment('android');
  const external = image(env.render({ item: item('https://cdn.instagram.test/coffee.jpg') }));
  assert.equal(external.props.source.uri, 'https://cdn.instagram.test/coffee.jpg');
  assert.equal(external.props.source.headers, undefined, 'External photos never receive account credentials');
  const privatePhoto = image(env.render({ item: item('/dream-items/1/thumbnail') }));
  assert.equal(privatePhoto.props.source.headers.Authorization, 'Bearer account-a');
  const unsupported = image(env.render({ item: item('https://cdn.instagram.test/iceland.jpg', 'Iceland'), artworkForCountry: 'Iceland' }));
  assert.equal(unsupported.props.source.uri, 'https://cdn.instagram.test/iceland.jpg');
  unsupported.props.onError(); assert.equal(image(env.render({ item: item('https://cdn.instagram.test/iceland.jpg', 'Iceland'), artworkForCountry: 'Iceland' })), undefined, 'Broken reels fall back to the neutral country treatment');
  env.dispose();
});

test('late private-thumbnail responses cannot cross account boundaries', async () => {
  const env = photoEnvironment(); let finish;
  env.respond(() => new Promise(resolve => { finish = resolve; }));
  const props = { item: item('/dream-items/1/thumbnail') };
  env.render(props); env.account(undefined); assert.equal(image(env.render(props)), undefined);
  finish({ ok: true, blob: async () => ({}) }); await flush();
  assert.equal(env.created.length, 0); assert.equal(image(env.render(props)), undefined);
  assert.equal(env.requests[0].init.signal.aborted, true);
  env.dispose();
});

test('switching to a country cover aborts a private photo and ignores its late response', async () => {
  const env = photoEnvironment(); let finish;
  env.respond(() => new Promise(resolve => { finish = resolve; }));
  const props = { item: item('/dream-items/1/thumbnail') };
  env.render(props);
  const country = { ...props, artworkForCountry: 'Japan' };
  assert.equal(image(env.render(country)).props.source, artwork.findCountryArtwork('JP').source);
  assert.equal(env.requests[0].init.signal.aborted, true);
  finish({ ok: true, blob: async () => ({}) }); await flush();
  assert.equal(env.created.length, 0);
  assert.equal(image(env.render(country)).props.source, artwork.findCountryArtwork('JP').source);
  env.dispose();
});
