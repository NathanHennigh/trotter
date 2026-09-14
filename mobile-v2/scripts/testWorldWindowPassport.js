const assert = require('node:assert/strict'), fs = require('node:fs'), path = require('node:path'), ts = require('typescript');
const root = path.resolve(__dirname, '..'), cache = new Map();
function load(file) {
  if (cache.has(file)) return cache.get(file).exports;
  const module = { exports: {} }; cache.set(file, module);
  const output = ts.transpileModule(fs.readFileSync(file, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, esModuleInterop: true } }).outputText;
  const localRequire = request => {
    if (!request.startsWith('.')) return require(request);
    const base = path.resolve(path.dirname(file), request);
    if (base.endsWith('.png')) return base;
    if (base.endsWith('.json')) return JSON.parse(fs.readFileSync(base, 'utf8'));
    const next = [base, base + '.ts', base + '.tsx', base + '.js'].find(candidate => fs.existsSync(candidate) && fs.statSync(candidate).isFile());
    if (!next) throw new Error(request + ' not found'); return load(next);
  };
  new Function('module', 'exports', 'require', output)(module, module.exports, localRequire); return module.exports;
}
const component = file => load(path.join(root, 'src/components/world-window/passport', file));
const { passportPages, chronologicalStamps, naturalStampPlacements, stampBounds, stampLabelsClear, stampAt, passportEdgeTurn, PAGE_WIDTH: W, PAGE_HEIGHT: H } = component('passport-paper.ts');
const unsorted = [{code:'SG',date:'2025-01-02'}, {code:'FR',date:'2017-03-15'}, {code:'AE',date:'2025-01-01'}, {code:'NL',date:'2024-12-31'}, {code:'US',date:'2016-12-05'}, {code:'CA',date:'2017-03-15'}, {code:'XX',date:''}];
const sourceOrder = JSON.stringify(unsorted), ordered = chronologicalStamps(unsorted);
assert.deepEqual(passportPages(ordered.map(s=>s.code)).flatMap(p=>p.stamps.map(s=>s.code)), ['US','CA','FR','NL','AE','SG','XX'], 'Passport starts with oldest arrivals, preserves same-day ties, and keeps unknown dates last');
assert.equal(JSON.stringify(unsorted), sourceOrder, 'Book order must not reorder the country collection source');
for (let count = 0; count <= 240; count++) {
  const codes = Array.from({ length: count }, (_, i) => 'C-' + i), pages = passportPages(codes);
  assert.equal(pages.length % 2, 0, 'Book must always open as complete two-page spreads');
  assert.deepEqual(pages.flatMap(p => p.stamps.map(s => s.code)), codes, 'Every country appears once, in chronological collection order');
  if (count) assert(pages.filter(p => p.kind === 'stamps').every(p => p.stamps.length), 'No blank filler stamp pages');
  for (const page of pages) {
    assert.deepEqual(page.stamps, naturalStampPlacements(page.stamps.map(s => s.code)), 'Placement is deterministic on rerender');
    for (const stamp of page.stamps) {
      const bounds = stampBounds(stamp);
      assert(bounds.left >= 12 && bounds.right <= W - 12 && bounds.top >= 12 && bounds.bottom <= H - 12, 'Rotated corners retain paper clearance');
      assert.equal(stampAt(page, stamp.x, stamp.y), stamp.code, 'Rendered stamp centers select their own country');
      assert(stampLabelsClear(page.stamps), 'Natural overlapping impressions leave all country/date/airport labels clear');
    }
  }
}
const { nativeStampTemplate } = component('passport-native-template.ts'), { stampFootprint } = component('passport-footprint.ts');
const { fittedLines } = component('passport-textures.ts');
const measuringCanvas = { font: '', measureText(value) { return { width: value.length * Number(this.font.match(/([\d.]+)px/)[1]) * .55 }; } };
for (const name of ['Traveler', 'A Very Long Traveler Name With Several Family Names', 'ABCDEFGHIJKLMNOPQRSTUVWXYZABCDEFGHIJKLMNOPQRSTUVWXYZABCDEFGHIJKLMNOPQRSTUVWXYZ']) {
  const fitted = fittedLines(measuringCanvas, name, 44, 264, 4);
  assert(80 + Math.max(0, fitted.lines.length - 1) * fitted.size < 190, 'Multi-line names stay above the identity divider');
  assert(fitted.lines.every(line => { measuringCanvas.font = fitted.size + 'px Newsreader'; return measuringCanvas.measureText(line).width <= 264; }), 'Long names stay inside both paper margins');
}
const templates = JSON.parse(fs.readFileSync(path.join(root, 'src/components/trotter/stamps/stampTemplates.json'), 'utf8'));
const shapes = Object.keys(templates).filter(k => !['ticketStubNotched', 'horizontalAirportOblong'].includes(k));
for (let n = 0; n < 80; n++) {
  const codes = Array.from({length: 3}, (_, i) => 'shape-' + n + '-' + i);
  const footprints = Object.fromEntries(codes.map((code, i) => {
    const t = nativeStampTemplate(shapes[(n + i * 3) % shapes.length], 'A COUNTRY NAME OF VARYING LENGTH'.slice(0, 6 + n % 25));
    const crop = stampFootprint(t);
    for (const b of [t.frame, t.country, t.icon, t.date, t.airport]) {
      assert(b.left * 204.75 >= crop.x && b.top * 165.75 >= crop.y && (b.left + b.width) * 204.75 <= crop.x + crop.width && (b.top + b.height) * 165.75 <= crop.y + crop.height, 'Crop includes complete calibrated artwork and text');
    }
    return [code, crop];
  }));
  const stamps = naturalStampPlacements(codes, footprints);
  assert(stampLabelsClear(stamps, footprints));
  assert(Math.max(...stamps.map(s => s.x)) - Math.min(...stamps.map(s => s.x)) > 35, 'Three stamps retain the approved staggered composition, not one vertical column');
  for (const s of stamps) { const b = stampBounds(s); assert(b.left >= 12 && b.right <= W - 12 && b.top >= 12 && b.bottom <= H - 12); assert.equal(stampAt({kind:'stamps', stamps}, s.x, s.y), s.code); }
}
for (const width of [280, 320, 360, 390, 430, 664, 900]) {
  assert.equal(passportEdgeTurn({ x: 1, y: 120 }, width), -1); assert.equal(passportEdgeTurn({ x: W * 2 - 1, y: 120 }, width), 1);
  assert.equal(passportEdgeTurn({ x: W, y: 120 }, width), null); assert.equal(passportEdgeTurn({ x: 0, y: -1 }, width), null);
  assert.equal(passportEdgeTurn({ x: W * 2 + 1, y: 120 }, width), null);
}
assert.equal(passportEdgeTurn({ x: 1, y: 1 }, NaN), null);
const { PassportCoverController, passportPose, passportPoint, passportViewportHeight } = component('passport-cover.ts');
for (const viewport of [280,320,410,600,900]) for (let p = 0; p <= 1; p += .05) {
  const pose = passportPose(p,viewport), point = { x: 500, y: 250 }, stage = { x: pose.width / 2 + (point.x - W + pose.offset) * pose.scale, y: pose.top + point.y * pose.scale };
  const result = passportPoint(stage.x, stage.y, p,viewport); assert(Math.abs(result.x - point.x) < .001 && Math.abs(result.y - point.y) < .001, 'Hit coordinates invert perspective-aware book scale and breathing room');
  assert(pose.height*viewport/pose.width < passportViewportHeight(viewport), 'Every cover frame fits the fixed native drawing viewport');
}
const { clampFold, PAPER_CLEARANCE } = component('passport-canvas.ts');
const { FlipCalculation } = component('page-fold/fold-geometry.js');
for (const corner of ['top','bottom']) for(let x=-319;x<320;x+=31) for(let y=-H;y<H*2;y+=47){
  const point=clampFold({x,y},corner); if(!point) continue;
  const calc=new FlipCalculation(0,corner,String(W),String(H)); assert(calc.calc(point));
  for(const p of calc.getFlippingClipArea()) if(p){
    assert(p.x>=-W&&p.x<=W&&p.y>=-PAPER_CLEARANCE+19.99&&p.y<=H+PAPER_CLEARANCE-19.99, 'Whole folded page and shadow stay inside fixed paper breathing room');
  }
}
const cover = new PassportCoverController(true); cover.begin(550, 0); cover.release(false, true, 30); assert.equal(cover.progress, 1, 'Cover opens on tap');
cover.begin(20, 100); cover.release(false, false, 140); cover.go(0); for (let i = 0; i < 80; i++) cover.advance(16); assert.equal(cover.progress, 0, 'First-edge tap closes rigid cover');
cover.begin(550, 200); cover.move(190, 240); assert(cover.progress > .5); cover.release(true, true, 260); assert.equal(cover.progress, 0, 'Cancelled cover drag returns to settled state');
const { PassportController } = component('passport-controller.ts');
const controller = new PassportController(4); controller.go(1); for (let i = 0; i < 70; i++) controller.advance(16); assert.equal(controller.spread, 1);
controller.begin({ x: W + 140, y: 150 }, 0); controller.move({ x: 120, y: 190 }, 30); controller.release(true, false, 40); for (let i = 0; i < 70; i++) controller.advance(16); assert.equal(controller.spread, 1, 'Cancelled paper drag cannot change the spread');
controller.go(-1, true); controller.go(-1, true); assert.equal(controller.spread, 0, 'Backward page navigation never leaves book bounds');
for (let i = 0; i < 8; i++) controller.go(1, true); assert.equal(controller.spread, 3);

const { buildPassportArchive } = component('passport-model.ts'), { buildPassportArrivals } = component('passport-arrivals.ts');
const profile = { name: 'Test Traveler', homeAirport: 'IAH', homeAirportName: 'Houston', firstFlightDate: '2020-01-01', flights: 500, countries: 99, airports: 100, airlines: 9, miles: 500000, hoursInAir: 20 };
const segment = (id, depAirport, arrAirport, date, country, code, extra = {}) => ({ id, mode: 'flight', depAirport, arrAirport, depTime: date + 'T08:00:00Z', arrTime: date + 'T12:00:00Z', arrCountry: country, arrCountryCode: code, airline: 'KL', flightNumber: '101', distanceMiles: 1000, ...extra });
const trip = (id, country, code, airport, segments, date = '2025-01-01') => ({ id, title: country + ' journey', country, countryCode: code, airportCode: airport, startDate: date, endDate: '2025-01-06', firstCountryEntryDate: date, firstCountryEntryAirport: airport, routeLabel: 'IAH → ' + airport, flightCount: segments.length, miles: segments.length * 1000, airlineCount: 1, accent: 'blue', segments, stamp: { shape: 'roundedImmigrationCanonical', icon: '', color: '#2F5E9E', country, city: 'Should never print', airportCode: airport, date } });
const connected = trip('connections', 'Singapore', 'SG', 'SIN', [segment('1', 'IAH', 'AMS', '2024-12-31', 'Netherlands', 'NL'), segment('2', 'AMS', 'DXB', '2025-01-01', 'United Arab Emirates', 'AE'), segment('3', 'DXB', 'SIN', '2025-01-02', 'Singapore', 'SG')], '2025-01-02');
const before = JSON.stringify(connected), arrivals = buildPassportArrivals([connected]);
assert.deepEqual(arrivals.map(a => a.country).sort(), ['Netherlands', 'Singapore', 'United Arab Emirates'].sort(), 'Connections with no coordinates still earn country entries');
assert.equal(arrivals.find(a => a.country === 'United Arab Emirates').airportCode, 'DXB'); assert(arrivals.every(a => a.stamp.city === undefined), 'Only airport first entry, never city text, is printed'); assert.equal(JSON.stringify(connected), before, 'Passport aggregation cannot mutate imported records');
const mixed = { ...connected, countryCode: undefined }; assert.equal(buildPassportArrivals([mixed]).find(a => a.country === 'Singapore').tripCount, 1, 'Adding country metadata must not double count one journey');
const sameDay = trip('same-day', 'United States', 'US', 'LAX', [segment('s1', 'LHR', 'JFK', '2025-01-01', 'United States', 'US'), segment('s2', 'JFK', 'LAX', '2025-01-01', 'United States', 'US', { arrTime: '2025-01-01T20:00:00Z' })]);
sameDay.firstCountryEntryAirport = undefined; assert.equal(buildPassportArrivals([sameDay])[0].airportCode, 'JFK', 'A same-day connection is the first entry, before the final destination airport');
sameDay.firstCountryEntryAirport = 'EWR'; assert.equal(buildPassportArrivals([sameDay])[0].airportCode, 'EWR', 'An explicit first-entry correction is preserved on the same day');
assert.equal(component('passport-arrivals.ts').countryArtwork('Tunisia'), 'tunisia_el_jem', 'Tunisia keeps the existing generated artwork');
assert.equal(component('passport-arrivals.ts').countryArtwork('Nicaragua'), 'costa_rica_arenal_volcano', 'Nicaragua retains its approved volcano asset alias when no saved icon is present');
const repeated = { ...connected, id: 'duplicate', segments: connected.segments.map(s => ({ ...s, id: 'different-' + s.id, flightNumber: undefined })) };
const { airportPresentation } = component('airport-presentation.ts');
const position = (code, lon, lat) => ({ code, city: code, lon, lat });
const mapped = { ...connected, segments: connected.segments.map((s, i) => ({ ...s, depPoint: position(s.depAirport, i * 30, 25), arrPoint: position(s.arrAirport, i * 30 + 30, 20) })) };
const hub = { code: 'AMS', city: 'Amsterdam', flights: 2, trips: [mapped] };
const idleFan = airportPresentation(hub), selectedFan = airportPresentation(hub, mapped.id);
assert.equal(idleFan.segments.length, 2, 'Airport fan contains actual incident flight pairs, not shortcuts to final destinations');
assert.equal(selectedFan.segments.length, 3, 'Selecting the airport journey includes its recorded onward connection');
assert(selectedFan.highlighted.every(Boolean)); assert.equal(airportPresentation(hub, 'missing').selected, undefined, 'Stale selection safely returns all airport routes');
const archive = buildPassportArchive([connected, repeated], profile); assert.equal(archive.flights, 3, 'Hydrated/duplicated preview rows do not invent flights'); assert.equal(archive.miles, 3000); assert.deepEqual(archive.years.map(y => [y.year, y.flights]), [[2024, 1], [2025, 2]], 'Each leg belongs to its departure year, including cross-year journeys');
assert.equal(archive.airports.find(a => a.code === 'DXB').country, 'United Arab Emirates', 'Airport identity retains country metadata independently of coordinates');
const { passportIdentityAirport } = component('passport-model.ts');
assert.deepEqual(passportIdentityAirport(archive), { label: 'Home airport', code: 'IAH', place: 'Houston' }, 'An explicitly set home airport takes precedence');
const noHome = { ...archive, homeAirport: ' ', homeAirportName: '', airports: [{ code: 'DFW', city: 'Dallas–Fort Worth', flights: 31, trips: [] }, { code: 'AMS', city: 'Amsterdam', flights: 2, trips: [] }] };
assert.deepEqual(passportIdentityAirport(noHome), { label: 'Most used airport', code: 'DFW', place: 'Dallas–Fort Worth' }, 'A real most-used airport fills the identity page without inventing a home');
assert.equal(noHome.homeAirport, ' ', 'Display fallback must not change account home-airport settings');
assert.equal(passportIdentityAirport({ homeAirport: '', homeAirportName: '', airports: [{ code: 'DFW', city: '', flights: 0, trips: [] }] }), undefined, 'Unranked airport metadata cannot claim most-used status');
const gap = trip('gap', 'Singapore', 'SG', 'SIN', [segment('4', 'DXB', 'SIN', '2027-01-01', 'Singapore', 'SG')], '2027-01-01');
assert.equal(buildPassportArchive([connected, gap], profile).years.find(y => y.year === 2026).flights, 0, 'Zero-flight years remain visible in the line graph');
const empty = buildPassportArchive([], profile); assert.equal(empty.flights, 0); assert.equal(empty.firstFlightDate, ''); assert.deepEqual(empty.arrivals, [], 'Empty accounts cannot inherit a bundled identity');
const african = trip('africa', 'Ethiopia', 'ET', 'ADD', [segment('5', 'DXB', 'ADD', '2025-01-01', 'Ethiopia', 'ET'), segment('6', 'ADD', 'HGA', '2025-01-03', 'Somalia', 'SO'), segment('7', 'HGA', 'DXB', '2025-01-04', 'United Arab Emirates', 'AE')]);
const somaliland = buildPassportArrivals([african]).find(a => a.country === 'Somaliland'); assert(somaliland); assert.equal(somaliland.airportCode, 'HGA'); assert.equal(somaliland.tripCount, 1, 'Somaliland is not re-added for every other connection in a multi-country trip'); assert.equal(somaliland.stamp.icon, 'somaliland_laas_geel');
const { tripsForCountry, activityYearLabelIndices } = component('passport-collection-model.ts');
const aliases = [
  trip('us-a', 'Canada', 'CA', 'YUL', [segment('us-a-return', 'YUL', 'IAH', '2024-05-03', 'United States', 'US')]),
  trip('us-b', 'France', 'FR', 'CDG', [segment('us-b-return', 'CDG', 'JFK', '2025-06-03', 'United States of America', 'US')]),
];
const usa = buildPassportArrivals(aliases).find(a => a.travelCountryKey === 'US');
assert.equal(usa.tripCount, 2);
const aliasSource = JSON.stringify(aliases);
assert.deepEqual(tripsForCountry(aliases, usa).map(t => t.id), ['us-a', 'us-b'], 'Country detail includes airport metadata aliases with one ISO identity, including no-coordinate endpoints');
assert.equal(JSON.stringify(aliases), aliasSource, 'Country matching cannot rewrite flight or destination metadata');
assert.deepEqual(tripsForCountry([connected], arrivals.find(a => a.travelCountryKey === 'AE')).map(t => t.id), ['connections'], 'Connection-country collection opens its whole journey');
const somaliaOnly = trip('somalia', 'Somalia', 'SO', 'MGQ', [segment('so', 'ADD', 'MGQ', '2025-01-01', 'Somalia', 'SO')]);
assert.deepEqual(tripsForCountry([african, somaliaOnly], somaliland).map(t => t.id), ['africa'], 'Somaliland stays distinct from Somalia in collection trip links');
assert.equal(tripsForCountry([{ ...aliases[0], segments: [...aliases[0].segments, ...aliases[0].segments] }], usa).length, 1, 'Multiple country arrivals in a journey list the trip only once');
for (const count of [0,1,2,11,12,40,41,100]) for (const width of [120,160,184,232,320]) {
  const labels = activityYearLabelIndices(count, width);
  if (count) assert.equal(labels.at(-1), count - 1, 'Latest year remains labeled');
  if (count > 1) assert.equal(labels[0], 0, 'First year remains labeled');
  for (let i = 1; i < labels.length; i++) assert((labels[i] - labels[i-1]) * width / (count - 1) >= 42, 'Activity labels reserve enough room even for long flight histories');
}
const { passportPageDescription } = component('passport-accessibility.ts');
const identity = { name: '<Alexandria> Montgomery-Smythe', airportLabel: 'Most used airport', homeAirport: 'DFW', homeAirportName: 'Dallas–Fort Worth', homeAirportCountry: 'United States', firstFlightDate: '2016-05-03', countries: 17, flights: 163, miles: 283884, years: [{year:2025,flights:21}], stamps: [], fonts: {} };
assert.deepEqual(passportPageDescription({kind:'identity',stamps:[]}, identity), {label:'Traveler identity',lines:['Name: <Alexandria> Montgomery-Smythe','Most used airport: DFW, Dallas–Fort Worth, United States','Since: 2016','Countries: 17']}, 'All visual identity fields have honest screen-reader equivalents');
assert(passportPageDescription({kind:'record',stamps:[]}, identity).lines.includes('2025: 21 flights'), 'The record page chart also exposes its data');
assert.equal(passportPageDescription({kind:'stamps',stamps:[]}, identity), undefined, 'Stamp pages use their existing individual arrival controls without duplicate descriptions');
assert(!passportPageDescription({kind:'identity',stamps:[]}, {...identity,name:'',homeAirport:'',homeAirportName:'',homeAirportCountry:'',firstFlightDate:''}).lines.some(line => line.includes('airport') || line.startsWith('Since:')), 'Empty accounts cannot announce invented airport or date fields');
const { scriptJSON } = component('passport-document.ts'); assert(!scriptJSON({ name: '</script><script>alert(1)</script>' }).includes('<'), 'Personal names cannot break the inline document script');
require('node:child_process').execFileSync(process.execPath, [path.join(__dirname, 'buildPassportRuntime.js'), '--check'], { stdio: 'inherit' });
console.log('Passport checks passed: 241 collection sizes, stable rotated bounds/hit targets, cover/fold gestures, connection countries, first-entry preservation, flight deduplication and year boundaries.');
