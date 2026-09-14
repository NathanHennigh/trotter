// Offline contract checks only: no sockets, server listeners, fetches, or ports.
const assert = require('node:assert/strict');
const { test } = require('node:test');
const { createQaHandler, trips, initialItems } = require('./serveNativeQa.cjs');
async function request(handler, method, url, { headers = {}, body } = {}) {
  const req = { method, url, headers: { host: '127.0.0.1:8001', ...headers },
    async *[Symbol.asyncIterator]() { if (body !== undefined) yield Buffer.from(JSON.stringify(body)); } };
  const result = { status: undefined, headers: {}, text: '', ended: false };
  const res = { headersSent: false,
    setHeader(key, value) { result.headers[key.toLowerCase()] = value; },
    writeHead(status, headers = {}) { result.status = status; this.headersSent = true; for (const [key, value] of Object.entries(headers)) this.setHeader(key, value); },
    end(value = '') { result.text = String(value); result.ended = true; } };
  await handler(req, res);
  assert(result.ended, 'Each mock request must complete');
  result.json = () => JSON.parse(result.text);
  return result;
}
async function signIn(handler) {
  const start = await request(handler, 'GET', '/auth/google/start?app_redirect_uri=' + encodeURIComponent('http://localhost:8081/oauthredirect'));
  assert.equal(start.status, 200);
  assert.match(start.text, /<button>Local UI test account<\/button>/);
  assert(!start.text.includes('#token='), 'Opening the consent page must not sign in');
  const action = start.text.match(/action="([^"]+)"/)[1];
  const callback = await request(handler, 'POST', action);
  assert.equal(callback.status, 303);
  const redirect = new URL(callback.headers.location);
  assert.equal(redirect.origin, 'http://localhost:8081');
  assert.equal(redirect.pathname, '/oauthredirect');
  assert.equal((await request(handler, 'POST', action)).status, 400, 'Consent is consumed once');
  return { authorization: 'Bearer ' + new URLSearchParams(redirect.hash.slice(1)).get('token') };
}

test('fixtures contain three synthetic trips, 18 chronological legs, and 16 country arrivals', () => {
  assert.equal(trips.length, 3);
  const legs = trips.flatMap(trip => trip.segments);
  assert.equal(legs.length, 18);
  assert.equal(new Set(legs.map(leg => leg.id)).size, 18);
  const countries = new Set(legs.map(leg => leg.meta_json.enrichment.airports.arrival.country_name));
  assert.equal(countries.size, 16);
  for (const country of ['Singapore', 'Netherlands', 'United Arab Emirates', 'Somaliland']) assert(countries.has(country));
  for (const trip of trips) for (let i = 0; i < trip.segments.length; i++) {
    const leg = trip.segments[i];
    assert(Date.parse(leg.dep_time) < Date.parse(leg.arr_time));
    assert.equal(leg.meta_json.source, 'local_ui_qa');
    if (i) assert(Date.parse(trip.segments[i - 1].arr_time) <= Date.parse(leg.dep_time));
  }
  assert.equal(initialItems().length, 9);
  assert.equal(initialItems().filter(item => item.latitude === null).length, 3);
});

test('private endpoints require the explicit local consent token', async () => {
  const handler = createQaHandler();
  for (const path of ['/auth/me', '/trips', '/trips/101', '/dreams', '/dream-items']) {
    assert.equal((await request(handler, 'GET', path)).status, 401);
    assert.equal((await request(handler, 'GET', path, { headers: { authorization: 'Bearer production-or-arbitrary-token' } })).status, 401);
  }
  const headers = await signIn(handler);
  assert.equal((await request(handler, 'GET', '/auth/me', { headers })).json().email, 'alex.qa@example.invalid');
  assert.equal((await request(handler, 'GET', '/ready')).json().qa_only, true);
});

test('non-loopback callbacks, origins, and hosts are rejected', async () => {
  const handler = createQaHandler();
  for (const callback of ['https://trotter.thehennighs.com/oauthredirect', 'http://example.invalid/oauthredirect', 'http://localhost:8081/other', 'trotterv2://oauthredirect']) {
    assert.equal((await request(handler, 'GET', '/auth/google/start?app_redirect_uri=' + encodeURIComponent(callback))).status, 400);
  }
  assert.equal((await request(handler, 'GET', '/ready', { headers: { host: 'example.invalid' } })).status, 403);
  assert.equal((await request(handler, 'GET', '/ready', { headers: { origin: 'https://example.invalid' } })).status, 403);
  const options = await request(handler, 'OPTIONS', '/dream-items', { headers: { origin: 'http://localhost:8081' } });
  assert.equal(options.status, 204);
  assert.equal(options.headers['access-control-allow-origin'], 'http://localhost:8081');
});

test('trip/detail and simulated sync contracts keep all fixture flight data unchanged', async () => {
  const handler = createQaHandler(), headers = await signIn(handler), before = JSON.stringify(trips);
  assert.equal((await request(handler, 'GET', '/trips', { headers })).json().length, 3);
  const detail = (await request(handler, 'GET', '/trips/101', { headers })).json();
  assert.equal(detail.destination_airport, 'SIN');
  assert.equal(detail.segments.length, 6);
  assert.equal((await request(handler, 'POST', '/trips/101', { headers, body: { title: 'changed' } })).status, 404);
  const job = (await request(handler, 'POST', '/ingest/gmail/import', { headers })).json();
  const progress = (await request(handler, 'GET', '/ingest/jobs/' + job.job_id, { headers })).json();
  assert.equal(progress.state, 'done');
  assert.equal(progress.segment_count, 18);
  assert.equal(JSON.stringify(trips), before);
});

test('Dreams review, pin edits, delete and share stay in the handler memory', async () => {
  const handler = createQaHandler(), headers = await signIn(handler);
  const summary = (await request(handler, 'GET', '/dreams', { headers })).json();
  assert.equal(summary.length, 4);
  assert.equal(summary.reduce((n, dream) => n + dream.item_count, 0), 9);
  const edited = (await request(handler, 'POST', '/dream-items/2/review', { headers, body: { decision: 'confirm', edits: {
    place_name: 'Reviewed local bookshop', google_maps_url: 'https://www.google.com/maps/search/?api=1&query=35.01,135.77', id: 999,
  } } })).json();
  assert.equal(edited.id, 2);
  assert.equal(edited.needs_review, false);
  assert.equal(edited.place_name, 'Reviewed local bookshop');
  assert.match(edited.google_maps_url, /35.01,135.77/);
  assert.equal((await request(handler, 'DELETE', '/dream-items/2', { headers })).status, 200);
  assert.equal((await request(handler, 'GET', '/dream-items/2', { headers })).status, 404);
  const saved = await request(handler, 'POST', '/dreams/share', { headers, body: { source_url: 'https://www.instagram.com/p/LOCAL_NEW/', shared_text: 'Local QA only' } });
  assert.equal(saved.status, 201);
  assert.equal(saved.json().status, 'needs_review');
  assert.equal(initialItems()[1].place_name, 'Canal-side bookshop', 'The source fixtures remain unchanged');
  const fresh = createQaHandler(), freshHeaders = await signIn(fresh);
  assert.equal((await request(fresh, 'GET', '/dream-items/2', { headers: freshHeaders })).json().needs_review, true);
});
