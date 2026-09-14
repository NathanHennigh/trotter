// Render the actual CountryPostcard/DreamPhoto components through React Native
// Web, with local fonts/artwork only. No Metro server or network is required.
const fs = require('node:fs'), path = require('node:path'), ts = require('typescript');
const assert = require('node:assert/strict');
const React = require('react'), native = require('react-native-web');
const { renderToStaticMarkup } = require('react-dom/server');
const { chromium } = require('C:/Users/natha/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const root = path.resolve(__dirname, '..');
const output = path.join(root, '../artifacts/world-window-fidelity');
const cache = new Map();
const photoSources = require('../assets/world-window/dreams/countries/photo-sources.json');
const auth = { getApiBaseUrl: () => 'https://api.example.invalid', getStoredToken: () => undefined, getAuthRevision: () => 0, subscribeAuthToken: () => () => {} };
function load(file) {
  if (cache.has(file)) return cache.get(file).exports;
  const module = { exports: {} }; cache.set(file, module);
  const compiled = ts.transpileModule(fs.readFileSync(file, 'utf8'), { fileName: file, compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } }).outputText;
  new Function('module', 'exports', 'require', compiled)(module, module.exports, request => {
    if (request === 'react-native') return native;
    if (request === 'react-native-svg') return { default: 'svg', Path: 'path' };
    // No icon is shown over loaded country art; use inert SVG for fallback only.
    if (request.endsWith('WorldWindowUI')) return { WWIcon: props => React.createElement('svg', { width: props.size, height: props.size }) };
    if (request.endsWith('services/travelTrips')) return auth;
    if (!request.startsWith('.')) return require(request);
    const base = path.resolve(path.dirname(file), request);
    if (base.endsWith('.webp')) {
      const photo = photoSources.find(photo => photo.bundled.file === path.basename(base));
      assert(photo, 'Bundled photograph must have source metadata');
      return { uri: 'data:image/webp;base64,' + fs.readFileSync(base).toString('base64'), width: photo.bundled.width, height: photo.bundled.height };
    }
    return load([base, base + '.ts', base + '.tsx'].find(candidate => fs.existsSync(candidate) && fs.statSync(candidate).isFile()));
  });
  return module.exports;
}
const { CountryPostcard } = load(path.join(root, 'src/components/world-window/dreams/CountryPostcard.tsx'));
const fonts = fs.readdirSync(path.join(root, 'assets/world-window/fonts')).filter(name => name.endsWith('.ttf')).map(name => {
  const family = name.slice(0, -4), source = fs.readFileSync(path.join(root, 'assets/world-window/fonts', name)).toString('base64');
  return `@font-face{font-family:'${family}';src:url(data:font/ttf;base64,${source}) format('truetype')}`;
}).join('');
const boards = [
  { key: 'france', title: 'France', cities: ['Paris', 'Lyon', 'Nice'], items: Array.from({ length: 28 }, (_, i) => ({ id: String(i), country: 'France', placeName: 'Saved place', category: 'cafe', thumbnailUrl: 'https://private.example.invalid/reel.jpg' })) },
  { key: 'greece', title: 'Greece', cities: ['Athens', 'Chania'], items: Array.from({ length: 7 }, (_, i) => ({ id: String(i), country: 'Greece', placeName: 'Saved place', category: 'restaurant' })) },
];
(async () => {
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({ headless: true, channel: 'chrome' });
  const results = [];
  for (const width of [320, 410]) {
    const tree = React.createElement(native.View, { style: { width, backgroundColor: '#FAF8F2', paddingTop: 20 } }, boards.map(board => React.createElement(CountryPostcard, { key: board.key, board, onPress() {} })));
    const markup = renderToStaticMarkup(tree), css = native.StyleSheet.getSheet().textContent;
    const html = `<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>${fonts}${css}html,body{margin:0;background:#FAF8F2}</style></head><body>${markup}</body></html>`;
    const page = await browser.newPage({ viewport: { width, height: 850 }, deviceScaleFactor: 2 });
    const requests = [], errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.route('**/*', route => { requests.push(route.request().url()); route.abort(); });
    await page.setContent(html); await page.evaluate(() => document.fonts.ready);
    await page.waitForFunction(() => [...document.images].every(image => image.complete));
    const pictures = await page.evaluate(() => [...document.images].map(image => {
      const frame = image.parentElement.getBoundingClientRect();
      return { loaded: image.naturalWidth > 0, width: image.naturalWidth, height: image.naturalHeight, frameWidth: frame.width, frameHeight: frame.height };
    }));
    assert(pictures.length >= 2 && pictures.every(p => p.loaded));
    assert(pictures.every(p => p.frameWidth > 0 && p.frameWidth <= width - 48 && p.frameHeight > 0 && p.frameHeight <= 197), 'Bundled image dimensions cannot overrun the postcard frame');
    assert.deepEqual(requests, []); assert.deepEqual(errors, []);
    const file = path.join(output, `native-dream-country-postcards-${width}.png`);
    await page.screenshot({ path: file, fullPage: true });
    results.push({ width, screenshots: file, pictures, requests, errors });
    await page.close();
  }
  // Review all actual postcard components together, using synthetic saved counts.
  const galleryTree = React.createElement(native.View, { style: { width: 1440, flexDirection: 'row', flexWrap: 'wrap', backgroundColor: '#FAF8F2', paddingTop: 24 } }, photoSources.map(photo => {
    const board = { key: photo.code, title: photo.country, cities: [], items: Array.from({ length: 12 }, (_, i) => ({ id: String(i), country: photo.country, placeName: 'Saved place', category: 'cafe' })) };
    return React.createElement(native.View, { key: photo.code, style: { width: 360 } }, React.createElement(CountryPostcard, { board, onPress() {} }));
  }));
  const galleryMarkup = renderToStaticMarkup(galleryTree), galleryCss = native.StyleSheet.getSheet().textContent;
  const gallery = await browser.newPage({ viewport: { width: 1440, height: 1360 }, deviceScaleFactor: 1 });
  const galleryRequests = [], galleryErrors = [];
  gallery.on('pageerror', error => galleryErrors.push(error.message));
  await gallery.route('**/*', route => { galleryRequests.push(route.request().url()); route.abort(); });
  await gallery.setContent(`<!doctype html><html><head><meta charset="utf-8"><style>${fonts}${galleryCss}html,body{margin:0;background:#FAF8F2}</style></head><body>${galleryMarkup}</body></html>`);
  await gallery.evaluate(() => document.fonts.ready);
  await gallery.waitForFunction(() => [...document.images].every(image => image.complete && image.naturalWidth > 0));
  assert.deepEqual(galleryRequests, []); assert.deepEqual(galleryErrors, []);
  const galleryFile = path.join(output, 'natural-country-postcards.png');
  await gallery.screenshot({ path: galleryFile, fullPage: true });
  results.push({ gallery: galleryFile, countries: photoSources.map(photo => photo.code), requests: galleryRequests, errors: galleryErrors });
  await gallery.close();
  fs.writeFileSync(path.join(output, 'native-dream-country-artwork-proof.json'), JSON.stringify(results, null, 2));
  await browser.close();
  console.log('Actual CountryPostcard/DreamPhoto rendered at 320/410 plus all 16 photographs in a gallery; zero network requests.');
})().catch(error => { console.error(error); process.exitCode = 1; });
