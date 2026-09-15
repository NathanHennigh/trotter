// Exercise real catalogues, matching/filtering logic and the collection index's state.
// Only native painting/branding components are replaced; no catalogue or progress mocks.
const assert = require('node:assert/strict');
const { test } = require('node:test');
const fs = require('node:fs'), path = require('node:path'), ts = require('typescript');
const root = path.resolve(__dirname, '..'), modules = new Map();
function pure(file) {
  const absolute = path.resolve(root, file);
  if (modules.has(absolute)) return modules.get(absolute);
  if (absolute.endsWith('.json')) return require(absolute);
  let source = fs.readFileSync(absolute, 'utf8');
  if (absolute.endsWith(path.join('world-window', 'AirlineLogo.tsx'))) {
    const ast = ts.createSourceFile(absolute, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
    source = ast.statements.filter(node => ts.isFunctionDeclaration(node) && node.name?.text === 'airlineName'
      || ts.isVariableStatement(node) && node.declarationList.declarations.some(d => d.name.getText(ast) === 'names'))
      .map(node => node.getText(ast)).join('\n');
  }
  const output = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, esModuleInterop: true } }).outputText;
  const mod = { exports: {} };
  const local = ref => {
    const base = path.resolve(path.dirname(absolute), ref);
    const found = [base, base + '.ts', base + '.tsx', base + '.json'].find(candidate => fs.existsSync(candidate) && fs.statSync(candidate).isFile());
    if (!found) throw Error(`Unexpected dependency ${ref}`);
    return pure(path.relative(root, found));
  };
  new Function('require', 'module', 'exports', output)(local, mod, mod.exports);
  modules.set(absolute, mod.exports); return mod.exports;
}
const model = pure('src/components/world-window/collections/transportCollectionModel.ts');
const { transportEntries, transportFirstVisit, filterTransportEntries, transportCatalog } = model;
const progressHelpers = pure('src/components/world-window/collections/catalogProgress.ts');
const { collectionProgress } = progressHelpers;
const archive = (airports = [], airlines = []) => ({ airports, airlines, arrivals: [], years: [], records: [] });
const segment = changes => ({ id: 'flight', depAirport: 'DFW', arrAirport: 'SIN', airline: 'UA', depTime: '2025-02-20T09:00:00Z', arrTime: '2025-02-21T09:00:00Z', ...changes });
const trip = (id, segments) => ({ id, startDate: '1900-01-01', segments });
const airport = (code, trips = [], fields = {}) => ({ code, city: code, flights: trips.length, trips, ...fields });
const airline = (code, trips = [], fields = {}) => ({ code, flights: trips.length, miles: 100, trips, ...fields });
const keys = entries => entries.map(entry => entry.key);

test('normalized observations have one catalog row without mutating records or sharing row state between calls', () => {
  const original = airport(' dfw ', [trip('one', [segment()])]);
  const duplicate = { ...original, code: 'DFW' }, inputs = archive([original, duplicate]);
  const snapshot = JSON.stringify(inputs), entries = transportEntries('airports', inputs);
  assert.equal(entries.filter(entry => entry.key === 'DFW').length, 1);
  assert.strictEqual(entries.find(entry => entry.key === 'DFW').record, duplicate);
  assert.equal(collectionProgress(transportCatalog('airports'), inputs.airports.map(row => row.code)).collected, 1);
  assert.equal(JSON.stringify(inputs), snapshot);
  entries.find(entry => entry.key === 'DFW').name = 'Local display state';
  assert.notEqual(transportEntries('airports', inputs).find(entry => entry.key === 'DFW').name, 'Local display state');
  const carrierEntries = transportEntries('airlines', archive([], [airline(' am '), airline('AM')]));
  assert.equal(carrierEntries.filter(entry => entry.key === 'AM').length, 1);
  assert.equal(carrierEntries.find(entry => entry.key === 'AM').name, 'Aeroméxico', 'Recorded carrier uses the actual app branding name');
});

test('historical and unknown records remain selectable outside the denominator', () => {
  for (const kind of ['airports', 'airlines']) {
    const code = kind === 'airports' ? 'OLD' : '??';
    assert(!transportCatalog(kind).entries.some(entry => entry.key === code), 'Fixture must be outside real catalogue');
    const record = kind === 'airports' ? airport(code, [], { city: 'Former airport', country: 'United States' }) : airline(code);
    const scoped = archive(); scoped[kind] = [record];
    const entries = transportEntries(kind, scoped), row = entries.find(entry => entry.key === code);
    assert(row); assert.equal(row.inCatalog, false); assert.strictEqual(row.record, record); assert.strictEqual(row.lifetimeRecord, record);
    assert(keys(filterTransportEntries(entries, 'visited', '', '')).includes(code));
    assert(keys(filterTransportEntries(entries, 'all', '', code)).includes(code));
    const progress = collectionProgress(transportCatalog(kind), [code]);
    assert.equal(progress.collected, 0); assert.equal(progress.total, transportCatalog(kind).entries.length);
    assert.deepEqual(progress.outsideCatalogKeys, [code]);
  }
});

test('real catalogue country keys become readable countries and correct continents', () => {
  const entries = transportEntries('airports', archive([airport('DFW'), airport('HGA')]));
  const dfw = entries.find(entry => entry.key === 'DFW'), hga = entries.find(entry => entry.key === 'HGA');
  assert.equal(dfw.countryKey, 'US'); assert.equal(dfw.countryName, 'United States'); assert.equal(dfw.region, 'North America');
  assert(dfw.city && Number.isFinite(dfw.lat) && Number.isFinite(dfw.lon));
  assert.equal(hga.countryKey, 'X-SOMALILAND'); assert.equal(hga.countryName, 'Somaliland'); assert.equal(hga.region, 'Africa');
  assert.deepEqual(keys(filterTransportEntries(entries, 'visited', 'Africa', '')), ['HGA']);
  const unvisited = entries.find(entry => entry.key === 'LHR');
  assert.equal(unvisited.countryKey, 'GB'); assert.equal(unvisited.countryName, 'United Kingdom'); assert.equal(unvisited.region, 'Europe'); assert.equal(unvisited.record, undefined);
});

test('partial lifetime snapshots retain scoped-only catalog and historical records with country aliases', () => {
  for (const kind of ['airports', 'airlines']) {
    const codes = kind === 'airports' ? ['DFW', 'OLD'] : ['UA', '??'];
    const records = codes.map(code => kind === 'airports' ? airport(code, [], { country: 'USA' }) : airline(code));
    const scoped = archive(); scoped[kind] = records;
    const entries = transportEntries(kind, scoped, archive());
    for (const [i, code] of codes.entries()) {
      const row = entries.find(entry => entry.key === code);
      assert(row); assert.strictEqual(row.record, records[i]); assert.strictEqual(row.lifetimeRecord, records[i]); assert.equal(row.inCatalog, i === 0);
    }
    assert.deepEqual(new Set(keys(filterTransportEntries(entries, 'visited', '', ''))), new Set(codes));
    if (kind === 'airports') {
      const outside = entries.find(row => row.key === 'OLD');
      assert.equal(outside.countryKey, 'US'); assert.equal(outside.countryName, 'United States'); assert.equal(outside.region, 'North America');
    }
  }
});

test('year scope never leaks historical flights but retains lifetime identity and original first visit', () => {
  const first = '2020-04-01T10:00:00Z', historic = trip('historic', [segment({ depTime: first })]);
  for (const kind of ['airports', 'airlines']) {
    const record = kind === 'airports' ? airport('DFW', [historic]) : airline('UA', [historic]);
    const lifetime = archive(); lifetime[kind] = [record];
    const entries = transportEntries(kind, archive(), lifetime), row = entries.find(entry => entry.key === record.code);
    assert.equal(row.record, undefined); assert.strictEqual(row.lifetimeRecord, record); assert.equal(row.firstVisit, first);
    assert.deepEqual(filterTransportEntries(entries, 'visited', '', record.code), []);
    assert.strictEqual(filterTransportEntries(entries, 'all', '', record.code).find(entry => entry.key === record.code).lifetimeRecord, record);
    assert.equal(collectionProgress(transportCatalog(kind), entries.filter(entry => entry.record).map(entry => entry.key)).collected, 0);
    assert.strictEqual(transportEntries(kind, lifetime, lifetime).find(entry => entry.key === record.code).record, record);
  }
});

test('first visits use only matching departure/arrival legs and ignore invalid or unrelated dates', () => {
  const flights = [trip('journey', [segment({ depAirport: 'LHR', arrAirport: 'CDG', depTime: '2000-01-01', arrTime: '2000-01-02', airline: 'BA' }),
    segment({ depAirport: 'SIN', arrAirport: 'DFW', depTime: '2024-03-01T10:00:00Z', arrTime: '2024-03-01T21:00:00Z' }),
    segment({ depTime: '2024-03-02T09:00:00Z' }), segment({ depTime: 'invalid', arrTime: '' })])];
  assert.equal(transportFirstVisit(airport('DFW', flights), 'airports'), '2024-03-01T21:00:00Z');
  assert.equal(transportFirstVisit(airline('UA', flights), 'airlines'), '2024-03-01T10:00:00Z');
  assert.equal(transportFirstVisit(airport('OLD', flights), 'airports'), undefined, 'Trip start is not fabricated as a first visit');
  assert.equal(transportFirstVisit(airline('XX', [trip('summary', undefined)]), 'airlines'), undefined);
});

test('first-visit matching normalizes identifiers and compares timestamp instants rather than lexical offsets', () => {
  const earlier = '2024-01-02T00:00:00+09:00', later = '2024-01-01T23:00:00-08:00';
  const flights = [trip('offsets', [segment({ depAirport: ' dfw ', airline: ' ua ', depTime: later }), segment({ depTime: earlier })])];
  assert.equal(transportFirstVisit(airport(' dfw ', flights), 'airports'), earlier);
  assert.equal(transportFirstVisit(airline(' ua ', flights), 'airlines'), earlier);
});

test('search matches accent-insensitive airport/city names, countries and IATA codes without mutating input order', () => {
  const airports = transportEntries('airports', archive()), before = keys(airports);
  for (const [query, key] of [['GRU', 'GRU'], ['São Paulo', 'GRU'], ['sao paulo', 'GRU'], ['Brazil', 'GRU'], ['  lHr  ', 'LHR']]) {
    assert(keys(filterTransportEntries(airports, 'all', '', query)).includes(key), `${query} matches ${key}`);
  }
  const carriers = transportEntries('airlines', archive([], [airline('AM')]));
  for (const query of ['am', 'Aeroméxico', 'aeromexico', 'Mexico']) assert(keys(filterTransportEntries(carriers, 'visited', '', query)).includes('AM'), query);
  assert.deepEqual(keys(airports), before);
  const asiaMatches = filterTransportEntries(airports, 'all', 'Asia', 'GRU');
  assert(!keys(asiaMatches).includes('GRU')); assert(asiaMatches.every(entry => entry.region === 'Asia'));
});

function indexHost() {
  const file = path.join(root, 'src/components/world-window/collections/TransportCollectionIndex.tsx');
  const ast = ts.createSourceFile(file, fs.readFileSync(file, 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const source = ast.statements.filter(node => ts.isFunctionDeclaration(node) && node.name?.text === 'TransportCollectionIndex'
    || ts.isVariableStatement(node) && node.declarationList.declarations.some(d => d.name.getText(ast) === 's')).map(node => node.getText(ast)).join('\n');
  let cursor = 0, props, progress; const states = [];
  const React = { Fragment: 'Fragment', createElement: (type, props, ...children) => ({ type, props: { ...props, children } }),
    useState: initial => { const i = cursor++; if (!(i in states)) states[i] = initial; return [states[i], next => states[i] = typeof next === 'function' ? next(states[i]) : next]; },
    useMemo: factory => factory() };
  const globals = { React, ...model, collectionProgress: (...args) => progress = collectionProgress(...args),
    ...Object.fromEntries('FlatList ScrollView Text View PressFeedback AirlineLogo WWIcon AirportLuggageLabel'.split(' ').map(name => [name, name])), StyleSheet: { create: value => value }, colors: {}, fonts: {} };
  const output = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.React } }).outputText;
  const mod = { exports: {} }; new Function('module', 'exports', ...Object.keys(globals), output)(mod, mod.exports, ...Object.values(globals));
  return { render: next => { props = next ?? props; cursor = 0; const tree = mod.exports.TransportCollectionIndex(props); return { tree, progress }; } };
}
function nodes(tree) { if (Array.isArray(tree)) return tree.flatMap(nodes); if (!tree || typeof tree !== 'object') return []; return [tree, ...nodes(tree.props?.children), ...nodes(tree.props?.ListHeaderComponent)]; }
const button = (tree, label, role) => nodes(tree).find(node => node.type === 'PressFeedback' && node.props.accessibilityRole === role && nodes(node).some(child => child.type === 'Text' && child.props.children.includes(label)));

test('real index All/Visited/search/region switching changes rows without conflating visible results with progress', () => {
  for (const kind of ['airports', 'airlines']) {
    const codes = kind === 'airports' ? ['DFW', 'SIN', 'OLD'] : ['UA', 'SQ', '??'];
    const observed = codes.map((code, i) => kind === 'airports' ? airport(code, [], { flights: 3 - i, country: i === 2 ? 'United States' : undefined }) : airline(code, [], { flights: 3 - i }));
    const scoped = archive(); scoped[kind] = observed;
    const entries = transportEntries(kind, scoped), catalog = transportCatalog(kind), host = indexHost();
    const props = { kind, entries, query: '', header: null, onSelect: () => {} };
    let { tree, progress } = host.render(props);
    assert.deepEqual(keys(tree.props.data), codes); assert.equal(progress.collected, 2); assert.equal(progress.total, catalog.entries.length); assert.deepEqual(progress.outsideCatalogKeys, [codes[2]]);
    const world = progress;
    ({ tree, progress } = host.render({ ...props, query: codes[0] })); assert.equal(tree.props.data.length, 1); assert.deepEqual(progress, world);
    button(tree, 'All', 'tab').props.onPress(); ({ tree, progress } = host.render()); assert.deepEqual(progress, world); assert(keys(tree.props.data).includes(codes[0]));
    ({ tree, progress } = host.render({ ...props, query: 'No such airport or airline' })); assert.equal(tree.props.data.length, 0); assert.deepEqual(progress, world);
    ({ tree } = host.render(props)); button(tree, 'North America', 'button').props.onPress(); ({ tree, progress } = host.render());
    assert.equal(progress.collected, 1); assert.equal(progress.total, catalog.entries.filter(row => row.region === 'North America').length); assert(tree.props.data.every(row => row.region === 'North America'));
    const regionProgress = progress;
    button(tree, kind === 'airports' ? 'Visited' : 'Flown', 'tab').props.onPress(); ({ tree, progress } = host.render()); assert.deepEqual(progress, regionProgress); assert(tree.props.data.every(row => row.record));
    button(tree, 'World', 'button').props.onPress(); ({ tree, progress } = host.render()); assert.deepEqual(progress, world); assert.deepEqual(keys(tree.props.data), codes);
  }
});
