// Render the shipping native label through RN-web with bundled fonts. This
// checks responsive typography/geometry, not Android GPU paint or touch input.
const fs = require('node:fs'), path = require('node:path'), Module = require('node:module'), assert = require('node:assert/strict');
const mobile = path.resolve(__dirname, '..'), from = Module.createRequire(path.join(mobile, 'package.json'));
const ts = from('typescript'), React = from('react'), RN = from('react-native-web'), server = from('react-dom/server');
const out = path.resolve(mobile, '../artifacts/airport-labels-20260915'); fs.mkdirSync(out, { recursive: true });
let width = 320, fontScale = 1;
function ScaledText({ style, ...props }) {
  const original = RN.StyleSheet.flatten(style) || {}, scaled = {}, multiplier = props.allowFontScaling === false ? 1 : Math.min(fontScale, props.maxFontSizeMultiplier || fontScale);
  if (original.fontSize) scaled.fontSize = original.fontSize * multiplier;
  if (original.lineHeight) scaled.lineHeight = original.lineHeight * multiplier;
  return React.createElement(RN.Text, { ...props, style: [style, scaled] });
}
const load = Module._load; Module._load = function (request, parent, isMain) {
  if (request === 'react-native') return { ...RN, Text: ScaledText, useWindowDimensions: () => ({ width, height: 920, scale: 1, fontScale }) };
  if (request === 'react-native-svg') return from('react-native-svg/lib/commonjs/elements.web');
  return load.call(this, request, parent, isMain);
};
for (const ext of ['.tsx', '.ts']) require.extensions[ext] = (module, file) => module._compile(ts.transpileModule(fs.readFileSync(file, 'utf8'), { fileName: file, compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, esModuleInterop: true } }).outputText, file);
require.extensions['.png'] = (module, file) => module.exports = { uri: 'data:image/png;base64,' + fs.readFileSync(file).toString('base64') };
const { AirportLuggageLabel } = require(path.join(mobile, 'src/components/world-window/collections/AirportLuggageLabel.tsx'));
const { entries } = require(path.join(mobile, 'src/data/collections/airports.json'));
const countries = require(path.join(mobile, 'src/data/collections/countries.json')).entries;
const countryNames = new Map(countries.map(entry => [entry.key, entry.name]));
function entry(key, visited = true) {
  const source = entries.find(row => row.key === key); assert(source, key);
  return { ...source, countryKey: source.country, countryName: countryNames.get(source.country), inCatalog: true, ...(visited ? { firstVisit: '2018-11-01', record: { code: key, city: source.city, flights: key === 'DFW' ? 50 : 1, trips: [] } } : {}) };
}
const longNames = [...entries].sort((a, b) => Math.max(b.name.length, b.city?.length || 0) - Math.max(a.name.length, a.city?.length || 0)).slice(0, 18);
const longCountries = [...entries].sort((a, b) => (countryNames.get(b.country)?.length || 0) - (countryNames.get(a.country)?.length || 0)).slice(0, 4);
const proofKeys = [...new Set([...longNames, ...longCountries].map(row => row.key))];
let fonts = ''; for (const name of ['DMSans-Regular', 'DMSans-Medium', 'DMSans-Bold']) fonts += `@font-face{font-family:'${name}';src:url(data:font/ttf;base64,${fs.readFileSync(path.join(mobile, 'assets/world-window/fonts', name + '.ttf')).toString('base64')})}`;
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || path.join(require('node:os').homedir(), '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'));
(async () => {
  const browser = await chromium.launch({ headless: true, channel: 'chrome' }), cases = [];
  try {
    for (const w of [320, 420]) for (const scale of [1, 2]) for (const kind of ['visited', 'long-directory', 'year']) {
      width = w; fontScale = scale;
      const records = kind === 'long-directory' ? proofKeys.map(key => entry(key, false)) : ['DFW', 'EWR', 'HGA', 'CDG'].map(key => entry(key));
      if (kind === 'year') records.forEach(row => { row.lifetimeRecord = row.record; delete row.record; });
      const name = `${kind}-${width}-font${fontScale}`;
      const content = records.map(row => React.createElement(RN.View, { key: row.key, style: { marginBottom: 16 } }, React.createElement(AirportLuggageLabel, { entry: row, hero: kind === 'long-directory', year: kind === 'year' ? '2026' : undefined })));
      RN.AppRegistry.registerComponent(name, () => () => React.createElement(RN.View, { style: { width, padding: 24, backgroundColor: '#FAF8F2' } }, content));
      const app = RN.AppRegistry.getApplication(name, {}), page = await browser.newPage({ viewport: { width, height: 920 } });
      const record = { name, width, fontScale, requests: [], errors: [] };
      page.on('pageerror', error => record.errors.push(error.message)); await page.route('**/*', route => { record.requests.push(route.request().url()); route.abort(); });
      await page.setContent('<!doctype html><html><head><meta charset="utf-8">' + server.renderToStaticMarkup(app.getStyleElement()) + '<style>' + fonts + 'html,body{margin:0;background:#FAF8F2}</style></head><body>' + server.renderToStaticMarkup(app.element) + '</body></html>');
      await page.evaluate(() => document.fonts.ready);
      record.layout = await page.evaluate(() => {
        const rows = [...document.querySelectorAll('[data-testid="airport-luggage-label"]')];
        const overflow = [];
        for (const row of rows) for (const element of row.querySelectorAll('*')) {
          if (element.namespaceURI.includes('svg') || ![...element.childNodes].some(node => node.nodeType === 3 && node.textContent.trim())) continue;
          const bounds = element.getBoundingClientRect(), parent = row.getBoundingClientRect();
          if (bounds.left < parent.left - 1 || bounds.right > parent.right + 1 || bounds.bottom > parent.bottom + 1 || element.scrollWidth > element.clientWidth + 1) overflow.push(element.textContent);
        }
        return { bodyWidth: document.body.scrollWidth, overflow, rows: rows.map(row => ({ text: row.textContent, rect: row.getBoundingClientRect().toJSON() })) };
      });
      assert.equal(record.layout.rows.length, records.length);
      if (kind === 'year') assert(record.layout.rows.every(row => row.text.includes('No flights in 2026') && row.text.includes('First visit')));
      if (kind === 'long-directory') assert(record.layout.rows.every(row => row.text.includes('Not yet visited') && !row.text.includes('First visit')));
      await page.screenshot({ path: path.join(out, name + '.png'), fullPage: kind !== 'long-directory' }); cases.push(record); await page.close();
    }
  } finally {
    await browser.close(); fs.writeFileSync(path.join(out, 'layout-proof.json'), JSON.stringify({ scope: 'Actual AirportLuggageLabel and bundled fonts projected through RN-web, 320/420px, simulated 1x/2x text. Includes the longest catalogue names/countries, unvisited visual state and lifetime first visit during year scope. No native raster/gesture assertion.', cases }, null, 2));
  }
  assert(cases.every(row => !row.errors.length && !row.requests.length && !row.layout.overflow.length && row.layout.bodyWidth <= row.width), 'Airport-label geometry overflow or runtime failure; inspect layout-proof.json');
  console.log(`Airport-label proof passed: ${cases.length} native component fixtures, 320/420px and 1x/2x text; no network requests or clipped labels.`);
})().catch(error => { console.error(error); process.exitCode = 1; });
