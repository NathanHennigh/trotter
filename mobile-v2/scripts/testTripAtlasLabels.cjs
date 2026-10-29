const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
const { test } = require('node:test');
const root = path.join(__dirname, '../src');
function load(file, mocks = {}) {
  const output = ts.transpileModule(fs.readFileSync(path.join(root, file), 'utf8'), {
    fileName: file, compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.React, target: ts.ScriptTarget.ES2022, esModuleInterop: true },
  }).outputText;
  const module = { exports: {} };
  new Function('module', 'exports', 'require', output)(module, module.exports, name => {
    assert(name in mocks, `Unexpected dependency ${name}`); return mocks[name];
  });
  return module.exports;
}
const presentation = load('components/world-window/trips/tripPresentation.ts');
const geometry = load('components/world-window/trips/tripAtlasGeometry.ts', { './tripPresentation': presentation });
const point = (code, lat, lon) => ({ code, city: code, lat, lon });
const flight = (dep, arr, id = dep.code + arr.code) => ({ id, depAirport: dep.code, arrAirport: arr.code, depPoint: dep, arrPoint: arr, depTime: '2026-01-01', arrTime: '2026-01-01' });
const bounds = label => ({ left: label.x - 3, right: label.x + label.width + 3, top: label.y - 1, bottom: label.y + label.height });
function assertClear(map) {
  const labels = map.ports.filter(port => port.label).map(port => ({ code: port.code, ...bounds(port.label) }));
  for (const label of labels) {
    assert(label.left >= 0 && label.right <= 400 && label.top >= 0 && label.bottom <= 230, `${label.code} label stays inside atlas`);
    for (const marker of map.ports) {
      const dx = marker.x - Math.max(label.left, Math.min(label.right, marker.x));
      const dy = marker.y - Math.max(label.top, Math.min(label.bottom, marker.y));
      assert(Math.hypot(dx, dy) >= marker.radius + .6, `${label.code} label covers ${marker.code} marker/stroke`);
    }
    for (const other of labels) {
      if (label === other) continue;
      assert(label.left > other.right || label.right < other.left || label.top > other.bottom || label.bottom < other.top, `${label.code}/${other.code} label backgrounds overlap`);
    }
  }
  for (const marker of map.ports) assert(marker.x >= 0 && marker.x <= 400 && marker.y >= 0 && marker.y <= 230, `${marker.code} is outside atlas`);
}

test('regional airport clusters keep label backgrounds clear of every marker', () => {
  const ports = [point('JFK', 40.64, -73.78), point('LGA', 40.78, -73.87), point('EWR', 40.69, -74.17), point('BOS', 42.36, -71.01), point('IAH', 29.99, -95.34)];
  const flights = ports.slice(1).map(port => flight(ports[0], port));
  const map = geometry.tripAtlasGeometry(flights, null, 'LGA');
  assertClear(map); assert.equal(map.ports.length, ports.length);
  assert(map.ports.find(port => port.code === 'LGA').label, 'Destination gets first label placement');
  assert.equal(map.paths.length, flights.length);
});

test('dense coincident pins retain every airport even when labels must be omitted', () => {
  const anchor = point('HUB', 35, 139);
  const ports = Array.from({ length: 80 }, (_, n) => point(`A${String(n).padStart(2, '0')}`, 35 + (n % 4) / 100, 139 + Math.floor(n / 4) / 100));
  ports.push(point('DUP', 35, 139));
  const map = geometry.tripAtlasGeometry(ports.map(port => flight(anchor, port)), null, 'HUB');
  assertClear(map); assert.equal(map.ports.length, ports.length + 1);
  assert(map.ports.some(port => !port.label), 'Crowding may omit a label, never its marker');
  assert.deepEqual(new Set(map.ports.map(port => port.code)), new Set(['HUB', ...ports.map(port => port.code)]));
});

test('Pacific and date-line routes have deterministic collision-free labels independent of input order', () => {
  const ports = [point('SFO', 37.62, -122.38), point('NRT', 35.77, 140.39), point('HND', 35.55, 139.78), point('SIN', 1.36, 103.99), point('NAN', -17.76, 177.44), point('APW', -13.83, -172.01)];
  const flights = ports.slice(1).map(port => flight(ports[0], port));
  const first = geometry.tripAtlasGeometry(flights, null, 'SIN');
  const reverse = geometry.tripAtlasGeometry([...flights].reverse(), null, 'SIN');
  assertClear(first); assertClear(reverse);
  assert.deepEqual(first.ports.map(port => [port.code, port.label]), reverse.ports.map(port => [port.code, port.label]));
});

const pathPieces = path => (path.match(/M[^M]*/g) ?? []).map(piece => [...piece.matchAll(/[ML](-?[\d.]+),(-?[\d.]+)/g)].map(match => [Number(match[1]), Number(match[2])]));
const near = (a, b, message) => assert(Math.hypot(a[0] - b[0], a[1] - b[1]) <= .02, message);

test('a global archive splits the trans-Pacific route at both visible edges without a world-spanning line', () => {
  const ports = [point('JFK', 40.64, -73.78), point('LHR', 51.47, -.45), point('DEL', 28.56, 77.10), point('NRT', 35.77, 140.39), point('SFO', 37.62, -122.38)];
  const flights = ports.map((port, i) => flight(port, ports[(i + 1) % ports.length]));
  const map = geometry.tripAtlasGeometry(flights, null, undefined, { maxLabels: 7, prioritizeByFrequency: true });
  assertClear(map);
  const crossing = pathPieces(map.paths[3]);
  assert.equal(crossing.length, 2, 'NRT–SFO crosses the archive’s Pacific seam');
  const exit = crossing[0].at(-1), entry = crossing[1][0];
  assert.deepEqual(new Set([exit[0], entry[0]]), new Set([0, 400]), 'Route continues flush with the actual map edges');
  assert.equal(exit[1], entry[1], 'Both sides share the same interpolated crossing latitude');
  for (let i = 0; i < map.paths.length; i += 1) {
    const pieces = pathPieces(map.paths[i]);
    const dep = map.ports.find(port => port.code === flights[i].depAirport), arr = map.ports.find(port => port.code === flights[i].arrAirport);
    near(pieces[0][0], [dep.x, dep.y], 'Route still starts at its departure marker');
    near(pieces.at(-1).at(-1), [arr.x, arr.y], 'Route still finishes at its arrival marker');
    for (const piece of pieces) for (let j = 1; j < piece.length; j += 1) {
      assert(Math.abs(piece[j][0] - piece[j - 1][0]) < 30, 'No seam-spanning SVG line');
    }
  }
  const reverse = geometry.tripAtlasGeometry(flights.map(f => flight(f.arrPoint, f.depPoint)), null);
  const reversedCrossing = pathPieces(reverse.paths[3]);
  near(reversedCrossing[0].at(-1), entry, 'Reversing direction retains the seam intersection');
  near(reversedCrossing[1][0], exit, 'Reversing direction retains the opposite continuation');
  assert.deepEqual(reverse.ports.map(({ code, x, y }) => ({ code, x, y })), map.ports.map(({ code, x, y }) => ({ code, x, y })).sort((a, b) => a.code.localeCompare(b.code)));
});

test('a Pacific-only trip keeps its compact regional fit across the geographic date line', () => {
  const dep = point('NRT', 35.77, 140.39), arr = point('SFO', 37.62, -122.38);
  const map = geometry.tripAtlasGeometry([flight(dep, arr)], null);
  assert.equal(pathPieces(map.paths[0]).length, 1, 'Its fitted regional seam is outside the flight, even across ±180°');
  const positions = map.ports.map(port => port.x).sort((a, b) => a - b);
  assert(Math.abs(positions[0] - 35) < .001 && Math.abs(positions[1] - 365) < .001, 'Existing regional padding and fit are retained');
  assertClear(map);
});

test('an endpoint without a complete route still receives an in-frame marker', () => {
  const flights = [flight(point('LHR', 51.47, -.45), point('CDG', 49.01, 2.55)), { id: 'partial', depAirport: 'SIN', arrAirport: 'XXX', depPoint: point('SIN', 1.36, 103.99), arrPoint: undefined }];
  const map = geometry.tripAtlasGeometry(flights, null);
  assert.equal(map.paths.length, 1); assert.equal(map.ports.length, 3); assertClear(map);
});

test('single-point and empty archives remain finite and do not invent markers', () => {
  const single = geometry.tripAtlasGeometry([flight(point('SIN', 1.36, 103.99), point('SIN', 1.36, 103.99))], null, 'SIN');
  assert.equal(single.ports.length, 1); assertClear(single); assert(single.ports[0].label);
  assert.deepEqual(geometry.tripAtlasGeometry([], null), { landPath: '', paths: [], ports: [] });
});

test('bounded atlas cache reuses equivalent flight snapshots but invalidates changed routes, labels and coastlines', () => {
  const cached = geometry.createTripAtlasGeometryCache(2);
  const legs = [flight(point('LHR', 51.47, -.45), point('SIN', 1.36, 103.99))];
  const first = cached(legs, null, 'SIN');
  assert.strictEqual(cached(JSON.parse(JSON.stringify(legs)), null, 'SIN'), first, 'Provider hydration with the same map reuses the projected coastline');
  assert.strictEqual(cached([{ ...legs[0], flightNumber: 'Changed metadata', depTime: '2026-02-01' }], null, 'SIN'), first);
  const updated = [{ ...legs[0], arrPoint: { ...legs[0].arrPoint, lon: 104.01 } }];
  assert.notStrictEqual(cached(updated, null, 'SIN'), first);
  assert.strictEqual(cached(legs, null, 'SIN'), first, 'Recent maps stay hot');
  const limited = cached(legs, null, 'SIN', { maxLabels: 1 });
  assert.notStrictEqual(limited, first); assert.equal(limited.ports.filter(port => port.label).length, 1);
  assert.notStrictEqual(cached(updated, null, 'SIN'), first);
  const recreated = cached(legs, null, 'SIN');
  assert.notStrictEqual(recreated, first, 'Least recent map is evicted at the configured bound');
  assert.deepEqual(recreated, first, 'Eviction changes no rendered geometry');
  assert.notStrictEqual(cached(legs, { features: [] }, 'SIN'), recreated, 'Replacing the land source invalidates cached projections');
});

test('Profile limits labels by importance while retaining all routes and markers', () => {
  const ports = [point('DFW', 33, -97), point('SIN', 1, 104), point('LHR', 51, 0), point('SFO', 38, -122), point('SYD', -34, 151)];
  const flights = ports.slice(1).map(port => flight(ports[0], port));
  flights.push(flight(ports[0], ports[2], 'repeat1'), flight(ports[0], ports[2], 'repeat2'));
  const map = geometry.tripAtlasGeometry(flights, null, 'SIN', { maxLabels: 3, prioritizeByFrequency: true });
  assert.equal(map.paths.length, flights.length); assert.equal(map.ports.length, 5); assertClear(map);
  assert.deepEqual(new Set(map.ports.filter(port => port.label).map(port => port.code)), new Set(['SIN', 'DFW', 'LHR']));
});

test('actual TripAtlas SVG paints all airport circles before every label background and text', () => {
  const react = { createElement: (type, props, ...children) => ({ type, props: { ...props, children } }), useMemo: fn => fn(), useId: () => 'atlas-label-test' };
  const svg = { __esModule: true, default: 'Svg', ...Object.fromEntries('Circle Defs G LinearGradient Path Rect Stop Text'.split(' ').map(tag => [tag, tag])) };
  const { TripAtlas } = load('components/world-window/trips/TripAtlas.tsx', {
    react, 'react-native': { View: 'View', StyleSheet: { create: value => value } }, 'react-native-svg': svg,
    '../../../data/worldCountries.json': { features: [] }, '../../../theme/trotterTheme': { fonts: { mono: 'TestMono' } }, './tripAtlasGeometry': geometry,
  });
  const flatten = node => Array.isArray(node) ? node.flatMap(flatten) : node && typeof node === 'object' ? [node, ...flatten(node.props?.children)] : [];
  for (const variant of [undefined, 'profile']) {
    const tree = TripAtlas({ segments: [flight(point('LHR', 51.47, -.45), point('CDG', 49.01, 2.55))], destination: 'CDG', variant });
    const elements = flatten(tree), circles = elements.map((node, index) => [node, index]).filter(([node]) => node.type === 'Circle');
    const firstLabel = elements.findIndex(node => node.type === 'Rect' && node.props.rx === 2);
    assert.equal(circles.length, 2); assert(firstLabel >= 0);
    assert(circles.every(([, index]) => index < firstLabel));
    assert.equal(elements.filter(node => node.type === 'Text').length, 2);
  }
});
