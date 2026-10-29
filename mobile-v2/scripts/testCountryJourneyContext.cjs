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
const travelCountry = load('utils/travelCountry.ts');
const { countryTripContext, tripsForCountry } = load('components/world-window/passport/passport-collection-model.ts', { '../../../utils/travelCountry': travelCountry });
const morocco = { country: 'Morocco', travelCountryKey: 'MA', airportCode: 'CMN' };
const endpoint = (code, city, country, countryCode) => ({ code, city, country, countryCode });
const jfk = endpoint('JFK', 'New York', 'United States', 'US'), cmn = endpoint('CMN', 'Casablanca', 'Morocco', 'MA'), rak = endpoint('RAK', 'Marrakech', 'Morocco', 'MA'), nbo = endpoint('NBO', 'Nairobi', 'Kenya', 'KE');
const flight = (dep, arr, date) => ({ depAirport: dep.code, arrAirport: arr.code, depPoint: dep, arrPoint: arr, depTime: date, arrTime: date });
const nairobi = { id: 'nairobi-via-morocco', title: 'Nairobi', city: 'Nairobi', country: 'Kenya', countryCode: 'KE', airportCode: 'NBO', segments: [flight(jfk, cmn, '2025-10-10'), flight(cmn, nbo, '2025-10-11'), flight(nbo, cmn, '2025-10-20'), flight(cmn, jfk, '2025-10-21')] };

test('a trip named for Nairobi explains its real Morocco connection once', () => {
  assert.deepEqual(tripsForCountry([nairobi], morocco), [nairobi]);
  assert.equal(countryTripContext(nairobi, morocco), 'Through Casablanca (CMN)');
  assert.equal(countryTripContext(nairobi, { country: 'Kenya', travelCountryKey: 'KE', airportCode: 'NBO' }), 'Through Nairobi (NBO)');
});

test('local stops use recorded metadata, chronological order and unique airport codes', () => {
  const trip = { ...nairobi, segments: [flight(rak, cmn, '2025-10-14'), flight(jfk, cmn, '2025-10-10'), flight(cmn, rak, '2025-10-12')] };
  assert.equal(countryTripContext(trip, morocco), 'Through Casablanca (CMN) · Marrakech (RAK)');
  const noPoints = { ...nairobi, segments: nairobi.segments.map(({ depPoint, arrPoint, ...s }) => ({ ...s, depCountryCode: depPoint.countryCode, arrCountryCode: arrPoint.countryCode })) };
  assert.equal(countryTripContext(noPoints, morocco), 'Through CMN', 'Missing city metadata is not guessed from the trip title');
  const withScopedSegments = { ...nairobi, segments: [flight(nbo, jfk, '2026-01-01')] };
  assert.equal(countryTripContext(withScopedSegments, morocco), undefined, 'Out-of-year connection metadata is not reconstructed');
});

test('old destination-only records use their own entry airport without mislabelling its city', () => {
  const trip = { country: 'Morocco', countryCode: 'MA', airportCode: 'RAK', city: 'Marrakech', firstCountryEntryAirport: 'CMN' };
  assert.equal(countryTripContext(trip, morocco), 'Through CMN');
  assert.equal(countryTripContext({ ...trip, firstCountryEntryAirport: undefined }, morocco), 'Through Marrakech (RAK)');
  assert.equal(countryTripContext({ ...nairobi, segments: [] }, morocco), undefined);
});

test('Somaliland context stays distinct from Somalia and country name aliases still work', () => {
  const trip = { country: 'Kenya', segments: [flight(nbo, endpoint('HGA', 'Hargeisa', 'Somalia', 'SO'), '2025-10-10')] };
  assert.equal(countryTripContext(trip, { country: 'Somaliland', travelCountryKey: 'X-SOMALILAND', airportCode: 'HGA' }), 'Through Hargeisa (HGA)');
  assert.equal(countryTripContext(trip, { country: 'Somalia', travelCountryKey: 'SO' }), undefined);
  assert.equal(countryTripContext(nairobi, { country: '  morocco ', travelCountryKey: 'MOROCCO' }), 'Through Casablanca (CMN)');
});

test('country journey rows display the local stop and keep the original trip-opening action', () => {
  const filename = path.join(root, 'components/world-window/passport/PassportCollections.tsx');
  const source = fs.readFileSync(filename, 'utf8');
  const ast = ts.createSourceFile(filename, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const declaration = ast.statements.find(node => ts.isFunctionDeclaration(node) && node.name.text === 'TripRows');
  const compiled = ts.transpileModule(declaration.getText(ast) + '\nexports.TripRows = TripRows;', { compilerOptions: { jsx: ts.JsxEmit.React, target: ts.ScriptTarget.ES2022 } }).outputText;
  const React = { createElement: (type, props, ...children) => ({ type, props: { ...props, children } }) };
  const globals = { React, View: 'View', Text: 'Text', Pressable: 'Pressable', WWIcon: 'WWIcon', styles: {}, countryTripContext, readableDate: date => date };
  const nodes = node => Array.isArray(node) ? node.flatMap(nodes) : node && typeof node === 'object' ? [node, ...nodes(node.props.children)] : [];
  const copy = node => Array.isArray(node) ? node.map(copy).join('') : node && typeof node === 'object' ? copy(node.props.children) : node ?? '';
  for (const fontScale of [1, 2]) {
    const module = { exports: {} };
    new Function('exports', 'useWindowDimensions', ...Object.keys(globals), compiled)(module.exports, () => ({ fontScale }), ...Object.values(globals));
    let opened;
    const tree = module.exports.TripRows({ trips: [{ ...nairobi, startDate: '2025-10-10', endDate: '2025-10-21', flightCount: 4 }], country: morocco, onOpenTrip: trip => opened = trip });
    assert(copy(tree).includes('NairobiThrough Casablanca (CMN)'));
    const button = nodes(tree).find(node => node.type === 'Pressable');
    assert.equal(button.props.accessibilityRole, 'button');
    button.props.onPress();
    assert.equal(opened.id, nairobi.id);
    const ordinaryRows = module.exports.TripRows({ trips: [nairobi], onOpenTrip: () => {} });
    assert(!copy(ordinaryRows).includes('Through'), 'Airline journey rows remain unchanged');
  }
});
