const assert = require('node:assert/strict');
const { test } = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
function load(relative, dependencies = {}) {
  const filename = path.join(__dirname, '..', relative);
  const source = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const module = { exports: {} };
  new Function('module', 'exports', 'require', source)(module, module.exports, name => {
    if (Object.hasOwn(dependencies, name)) return dependencies[name];
    throw new Error(`Unexpected dependency ${name}`);
  });
  return module.exports;
}
const presentation = load('src/components/world-window/sharing/flightSharingPresentation.ts');
const leg = (id, patch = {}) => ({ id, passenger_name: null, status: 'needs_review', reason: 'unassigned', shareable: false,
  flight: { pnr: 'ABC123', dep_airport: 'DTW', arr_airport: 'DCA', travel_date: '2026-09-09', flight_number: 'AA123' }, ...patch });
test('groups by booking and explicit traveler without mixing an owner or unrelated unnamed booking', () => {
  const items = [leg('one'), leg('two', { flight: { pnr: 'ABC123', dep_airport: 'DCA', arr_airport: 'DTW', travel_date: '2026-09-11' } }),
    leg('owner', { status: 'belongs_to_you' }), leg('named', { passenger_name: 'Morgan Blake' }),
    leg('missing1', { flight: { dep_airport: 'LAX', arr_airport: 'SFO', travel_date: '2026-08-01' } }),
    leg('missing2', { flight: { dep_airport: 'SFO', arr_airport: 'LAX', travel_date: '2026-08-03' } })];
  const result = presentation.groupRetainedBookings(items);
  assert.equal(result.length, 4);
  assert.deepEqual(result.find(group => group.reference === 'ABC123' && !group.passenger).items.map(item => item.id), ['one', 'two']);
  assert.equal(result.flatMap(group => group.items).some(item => item.id === 'owner'), false);
  assert.deepEqual(items.map(item => item.id), ['one', 'two', 'owner', 'named', 'missing1', 'missing2']);
});
test('owner traveler assignment supplies presentation without replacing extracted name', () => {
  const item = leg('one', { passenger_name: 'Source Name', assigned_passenger_name: 'Assigned Name' });
  assert.equal(presentation.passengerName(item), 'Assigned Name');
  assert.equal(item.passenger_name, 'Source Name');
});
test('reused booking codes do not collect flights from different years', () => {
  const before = leg('old', { passenger_name: 'Morgan Blake', flight: { pnr: 'ABC123', travel_date: '2023-01-01' } });
  const after = leg('new', { passenger_name: 'Morgan Blake', flight: { pnr: 'ABC123', travel_date: '2026-01-01' } });
  assert.equal(presentation.groupRetainedBookings([before, after]).length, 2);
});
test('expired pending shares cannot present an active acceptance action', () => {
  assert.equal(presentation.shareStatus({ status: 'pending', expires_at: '2020-01-01' }, Date.parse('2026-01-01')), 'expired');
  assert.equal(presentation.shareStatus({ status: 'accepted', expires_at: '2020-01-01' }, Date.parse('2026-01-01')), 'accepted');
});
test('submission requires chosen flights, traveler, and another valid account email', () => {
  assert.match(presentation.validateFlightShare('Morgan Blake', 'morgan@example.com', 0), /Choose/);
  assert.match(presentation.validateFlightShare('', 'morgan@example.com', 1), /traveler/);
  for (const email of ['person', 'p@', 'p @example.com', 'p@example']) assert.match(presentation.validateFlightShare('Morgan Blake', email, 1), /email/);
  assert.match(presentation.validateFlightShare('Morgan Blake', 'OWNER@example.com', 1, 'owner@example.com'), /own/);
  assert.equal(presentation.validateFlightShare('Morgan Blake', ' morgan@example.com ', 2, 'owner@example.com'), undefined);
});
test('route summary preserves disconnected legs; dates and times never shift across local timezones', () => {
  const flights = [{ dep_airport: 'LAS', arr_airport: 'DCA' }, { dep_airport: 'BWI', arr_airport: 'CLT' }, { dep_airport: 'CLT', arr_airport: 'LAS' }];
  assert.equal(presentation.flightRoute(flights), 'LAS · DCA · BWI · CLT · LAS');
  assert.match(presentation.flightDate('2026-09-09T00:00:00Z'), /2026/);
  assert.equal(presentation.flightDate('2026-02-31'), 'Date unavailable');
  assert.equal(presentation.flightTime('2026-09-09T09:30:00-04:00'), '13:30 UTC');
  assert.equal(presentation.flightTime('2026-09-09T13:30:00'), '13:30 UTC');
  assert.equal(presentation.flightTime('09:30'), undefined);
});
test('acceptance tells recipients when flights already exist', () => {
  assert.match(presentation.acceptanceMessage(0, 3), /already/);
  assert.match(presentation.acceptanceMessage(2, 1), /2 flights added/);
  assert.match(presentation.acceptanceMessage(2, 1), /no duplicates/);
});
test('overnight arrival labels use UTC calendar dates, including offset timestamps', () => {
  assert.equal(presentation.arrivalDayOffset({dep_time:'2026-11-15T22:30:00Z',arr_time:'2026-11-16T07:30:00Z'}),1);
  assert.equal(presentation.arrivalDayOffset({dep_time:'2026-11-15T23:30:00-04:00',arr_time:'2026-11-16T08:30:00+01:00'}),0);
  assert.equal(presentation.arrivalDayOffset({dep_time:'2026-11-15T22:30:00',arr_time:'2026-11-17T07:30:00'}),2);
  assert.equal(presentation.arrivalDayOffset(null),0);
});

function serviceState() {
  let revision = 1, token = 'initial-token';
  const subscribers = new Set();
  const auth = {
    getApiBaseUrl: () => 'https://api.example.test', getStoredToken: () => token, getAuthRevision: () => revision,
    hydrateStoredToken: async () => token, subscribeAuthToken: listener => { subscribers.add(listener); return () => subscribers.delete(listener); },
    clearAuthToken: async () => { revision++; token = undefined; for (const listener of subscribers) listener(); },
  };
  return { api: load('src/services/flightSharing.ts', { './travelTrips': auth }).flightSharing,
    changeAccount: () => { revision++; token = 'other-token'; for (const listener of subscribers) listener(); },
    subscriberCount: () => subscribers.size, token: () => token };
}
test('API preserves explicit idempotency key and sends only selected passenger fields', async () => {
  const state = serviceState();
  const original = global.fetch;
  const input = { item_ids: ['one', 'two'], passenger_name: 'Morgan Blake', recipient_email: 'morgan@example.com', client_request_id: 'fixed-key' };
  global.fetch = async (url, options) => {
    assert.equal(url, 'https://api.example.test/travel-sharing');
    assert.equal(options.method, 'POST');
    assert.equal(options.headers.Authorization, 'Bearer initial-token');
    assert.deepEqual(JSON.parse(options.body), input);
    return { status: 200, ok: true, text: async () => JSON.stringify({ share: { id: 'share1' }, share_url: 'link' }) };
  };
  try { assert.equal((await state.api.create(input)).share.id, 'share1'); assert.equal(state.subscriberCount(), 0); }
  finally { global.fetch = original; }
});
test('account changes during a request abort instead of exposing old account tickets', async () => {
  const state = serviceState();
  const original = global.fetch;
  global.fetch = async () => { state.changeAccount(); return { status: 200, ok: true, text: async () => JSON.stringify({ items: ['private'] }) }; };
  try { await assert.rejects(state.api.inbox(), /account changed/); assert.equal(state.subscriberCount(), 0); }
  finally { global.fetch = original; }
});
test('expired sessions clear credentials and return a useful sign-in error', async () => {
  const state = serviceState();
  const original = global.fetch;
  global.fetch = async () => ({ status: 401, ok: false, text: async () => '{}' });
  try { await assert.rejects(state.api.inbox(), /session expired/); assert.equal(state.token(), undefined); assert.equal(state.subscriberCount(), 0); }
  finally { global.fetch = original; }
});
test('recipient mismatch message passes through without printing the invitation token', async () => {
  const state = serviceState();
  const original = global.fetch;
  global.fetch = async () => ({ status: 403, ok: false, text: async () => JSON.stringify({ detail: 'This invitation is for a different account.' }) });
  try { await assert.rejects(state.api.resolve('private-token'), error => error.message === 'This invitation is for a different account.'); }
  finally { global.fetch = original; }
});
