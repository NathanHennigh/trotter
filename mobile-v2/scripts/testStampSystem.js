const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const root = path.join(__dirname, '..');
const cache = new Map();
const native = {
  StyleSheet: { create: (styles) => styles },
  Text: ({ children }) => React.createElement('span', {}, children),
  View: ({ children }) => React.createElement('div', {}, children),
  Image: () => React.createElement('img', { alt: '' }),
};
const svg = { __esModule: true, default: 'svg', Defs: 'defs', Path: 'path', Text: 'text', TextPath: 'textPath' };
function load(filename) {
  if (cache.has(filename)) return cache.get(filename).exports;
  const module = { exports: {} };
  cache.set(filename, module);
  const output = ts.transpileModule(fs.readFileSync(filename, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.React, esModuleInterop: true } }).outputText;
  const localRequire = (request) => {
    if (request === 'react-native') return native;
    if (request === 'react-native-svg') return svg;
    if (!request.startsWith('.')) return require(request);
    const base = path.resolve(path.dirname(filename), request);
    if (base.endsWith('.png')) return base;
    if (base.endsWith('.json')) return JSON.parse(fs.readFileSync(base, 'utf8'));
    const next = [base, `${base}.ts`, `${base}.tsx`].find((candidate) => fs.existsSync(candidate) && fs.statSync(candidate).isFile());
    return load(next);
  };
  new Function('module', 'exports', 'require', output)(module, module.exports, localRequire);
  return module.exports;
}
const { firstCountryEntry, buildCountryArrivals } = load(path.join(root, 'src/utils/countryArrivals.ts'));
const first = firstCountryEntry([
  { airportCode: 'LAX', date: '2025-04-08T22:00:00Z', countryCode: 'US' },
  { airportCode: 'JFK', date: '2025-04-08T12:00:00Z', countryCode: 'US' },
  { airportCode: 'YYZ', date: '2025-04-08T02:00:00Z', countryCode: 'CA' },
], 'United States', 'US');
assert.equal(first.airportCode, 'JFK', 'Entry is the first arrival in the destination country, not its final city or a foreign connection');
assert.equal(firstCountryEntry([{ airportCode: 'CDG', date: 'invalid', country: 'France' }], 'France'), undefined);
assert.equal(firstCountryEntry([{ airportCode: 'CDG', date: '2025-01-01', country: 'France' }], 'France').airportCode, 'CDG');
const trip = (id, date, airport, entry) => ({ id, country: 'United States', countryCode: 'US', airportCode: airport, firstCountryEntryAirport: entry, firstCountryEntryDate: date, startDate: date, airports: ['LHR', 'JFK', airport], stamp: { shape: 'shieldBadgeRounded', country: 'USA', city: 'Los Angeles', airportCode: airport, date, icon: 'united_states_golden_gate_bridge', color: '#52745A' } });
const arrivals = buildCountryArrivals([trip('later', '2026-02-01', 'BOS'), trip('first', '2025-04-08', 'LAX', 'JFK')]);
assert.equal(arrivals.length, 1);
assert.equal(arrivals[0].airportCode, 'JFK');
assert.equal(arrivals[0].firstVisitDate, '2025-04-08');
assert.equal(arrivals[0].stamp.city, undefined);
assert.equal(arrivals[0].stamp.airportCode, 'JFK');
assert.equal(arrivals[0].tripCount, 2);
assert.equal(arrivals[0].airportCount, 3, 'Only known destination/entry airports count toward this country');
assert.deepEqual(buildCountryArrivals([]), [], 'An empty archive must not invent a country stamp');
const fallback = buildCountryArrivals([trip('snapshot', '2020-12-11', 'DFW')]);
assert.equal(fallback[0].airportCode, 'DFW');
const legacy = trip('legacy', '2025-01-01', 'TPE');
legacy.firstCountryEntryDate = undefined;
legacy.stamp.date = '09 APR 2020';
assert.equal(buildCountryArrivals([legacy])[0].firstVisitDate, '2020-04-09');
const sameDayEarly = trip('z-early', '2025-04-08', 'JFK');
sameDayEarly.segments = [{ arrAirport: 'JFK', arrTime: '2025-04-08T07:00:00Z' }];
const sameDayLate = trip('a-late', '2025-04-08', 'LAX');
sameDayLate.segments = [{ arrAirport: 'LAX', arrTime: '2025-04-08T19:00:00Z' }];
assert.equal(buildCountryArrivals([sameDayLate, sameDayEarly])[0].airportCode, 'JFK');
const unenriched = trip('no-code', '2019-01-01', 'SFO');
unenriched.countryCode = undefined;
const mixedMetadata = buildCountryArrivals([unenriched, trip('coded', '2025-04-08', 'JFK')]);
assert.equal(mixedMetadata.length, 1, 'Adding enriched country metadata must not split an existing country collection');
assert.equal(mixedMetadata[0].airportCode, 'SFO');
const { stampIdentity, NATIVE_STAMP_SHAPES, NATIVE_STAMP_COLORS } = load(path.join(root, 'src/components/trotter/stamps/stampIdentity.ts'));
const countries = [{ name: 'Taiwan', code: 'TW' }, { name: 'Philippines', code: 'PH' }, { name: 'Dominican Republic', code: 'DO' }, { name: 'Singapore', code: 'SG' }];
const identities = new Map(countries.map(({ name, code }) => [code, stampIdentity(name, code)]));
for (const { name, code } of [{ name: 'France', code: 'FR' }, ...countries.slice().reverse()]) {
  const identity = stampIdentity(name, code);
  if (identities.has(code)) assert.deepEqual(identity, identities.get(code), 'New or reordered trips cannot alter a country stamp');
  assert(NATIVE_STAMP_SHAPES.includes(identity.shape));
  assert(NATIVE_STAMP_COLORS.includes(identity.color));
}
assert.deepEqual(stampIdentity('Taiwan', ' tw '), identities.get('TW'));
assert.deepEqual(stampIdentity('  New   Zealand  '), stampIdentity('NEW ZEALAND'));
assert.deepEqual(stampIdentity('United States', 'US'), { shape: 'shieldBadgeRounded', color: '#52745A' });
assert.deepEqual(stampIdentity('USA'), stampIdentity('United States', 'US'));
assert.deepEqual(stampIdentity('C\u00f4te d Ivoire'), stampIdentity('COTE D IVOIRE'), 'Name fallback normalizes accents and case');
const { travelCountry, SOMALILAND_TRAVEL_KEY } = load(path.join(root, 'src/utils/travelCountry.ts'));
assert.deepEqual(travelCountry('Somalia', 'SO', 'HGA'), { country: 'Somaliland', countryCode: undefined, travelCountryKey: SOMALILAND_TRAVEL_KEY });
assert.equal(travelCountry('Somalia', 'SO', 'MGQ').country, 'Somalia');
assert.equal(travelCountry('Somalia', 'SO', 'BBO').travelCountryKey, SOMALILAND_TRAVEL_KEY);
assert.deepEqual(stampIdentity('Somaliland'), stampIdentity('Somaliland', 'X-SOMALILAND'));
const mixedTrip = trip('ethiopia-visit', '2022-12-16', 'ADD');
mixedTrip.country = 'Ethiopia'; mixedTrip.countryCode = 'ET';
mixedTrip.segments = [{ arrAirport: 'HGA', arrTime: '2022-12-18T08:00:00Z' }, { arrAirport: 'BBO', arrTime: '2022-12-20T08:00:00Z' }];
const somaliaTrip = trip('somalia-visit', '2020-06-01', 'MGQ');
somaliaTrip.country = 'Somalia'; somaliaTrip.countryCode = 'SO';
const regionalArrivals = buildCountryArrivals([somaliaTrip, mixedTrip]);
assert.equal(regionalArrivals.length, 3, 'Somaliland remains a separate visit alongside Ethiopia and Somalia');
const somaliland = regionalArrivals.find((arrival) => arrival.travelCountryKey === SOMALILAND_TRAVEL_KEY);
assert.equal(somaliland.airportCode, 'HGA');
assert.equal(somaliland.firstVisitDate, '2022-12-18');
assert.equal(somaliland.stamp.icon, 'somaliland_laas_geel');
assert.equal(somaliland.tripCount, 1);
const regionalSegments = [
 { airportCode: 'MGQ', date: '2020-01-01', countryCode: 'SO', country: 'Somalia' },
 { airportCode: 'HGA', date: '2022-12-18', countryCode: 'SO', country: 'Somalia' },
];
assert.equal(firstCountryEntry(regionalSegments, 'Somaliland').airportCode, 'HGA');
assert.equal(firstCountryEntry(regionalSegments, 'Somalia', 'SO').airportCode, 'MGQ');
const { PngStamp } = load(path.join(root, 'src/components/trotter/stamps/PngStamp.tsx'));
const { resolveStampGeometry, STAMP_FRAME_PIXELS } = load(path.join(root, 'src/components/trotter/stamps/stampGeometry.ts'));
const { countryIconAssets } = load(path.join(root, 'src/assets/generated/stampAssetManifest.ts'));
assert(fs.existsSync(countryIconAssets.somaliland_laas_geel), 'Generated Somaliland artwork is registered and exists');
const nativeSomalilandHtml = renderToStaticMarkup(React.createElement(PngStamp, { ...somaliland.stamp, scale: 1 }));
assert.equal((nativeSomalilandHtml.match(/<img/g) || []).length, 2, 'Somaliland stamp renders its own artwork and frame');
assert(nativeSomalilandHtml.includes('HGA') && !nativeSomalilandHtml.includes('MGQ'));
const templates = JSON.parse(fs.readFileSync(path.join(root, 'src/components/trotter/stamps/stampTemplates.json'), 'utf8'));
const shapes = Object.keys(templates).slice(0, 8);
for (const shape of shapes) {
  for (const country of ['USA', 'Taiwan', 'Philippines', 'Dominican Republic', 'Bosnia and Herzegovina', 'Liechtenstein', 'Somaliland']) {
    const html = renderToStaticMarkup(React.createElement(PngStamp, { shape, color: '#52745A', country, city: 'THIS CITY MUST NOT PRINT', airportCode: 'jfk', date: '2025-04-08', scale: .5 }));
    assert(!html.includes('THIS CITY'), `${shape}: city text leaked into stamp`);
    assert(html.includes(country.toUpperCase()), `${shape}: country name truncated`);
    assert(html.includes('JFK'), `${shape}: missing entry airport`);
    assert(html.includes('08 APR 2025'), `${shape}: missing first arrival date`);
    assert(!html.includes('NaN'), `${shape}: invalid SVG/text geometry`);
    assert((html.match(/>JFK</g) || []).length === 1, `${shape}: duplicated entry code`);
  }
}
for (const shape of shapes) {
  for (const [width, height] of [[149.5, 117], [204.75, 165.75], [269.75, 214.5]]) {
    for (const scale of [.5, .76, 1, 1.3]) {
      const t = resolveStampGeometry(shape, templates[shape].default, width * scale, height * scale);
      const [iw, ih] = STAMP_FRAME_PIXELS[shape];
      assert(Math.abs(t.frame.width * width / (t.frame.height * height) - iw / ih) < 1e-9, 'Layout follows the original PNG contain aspect ratio');
      for (const key of ['country', 'icon', 'date', 'airport']) {
        const b = t[key], f = t.frame;
        assert(b.left >= f.left && b.top >= f.top && b.left + b.width <= f.left + f.width && b.top + b.height <= f.top + f.height, `${shape}/${key}: content lies inside the contained frame image`);
      }
    }
  }
}
console.log(`Stamp regressions passed: entry chronology, foreign connections, empty archives, snapshot fallback, stable country identities, and ${shapes.length * 7} rendered stamp cases.`);
