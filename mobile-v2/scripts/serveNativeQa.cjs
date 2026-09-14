/**
 * Explicit, loopback-only UI QA service. Never imported by the Expo app.
 * Uses only synthetic in-memory data; never contacts Google or production.
 * Start: node scripts/serveNativeQa.cjs
 */
const http = require('node:http');
const { randomUUID } = require('node:crypto');
const TOKEN = 'trotter-local-ui-qa-only';
const NOW = '2026-09-08T12:00:00.000Z';
const airports = {
  ORD: ['Chicago', 'United States', 'US', 41.9742, -87.9073],
  AMS: ['Amsterdam', 'Netherlands', 'NL', 52.3105, 4.7683],
  DXB: ['Dubai', 'United Arab Emirates', 'AE', 25.2532, 55.3657],
  SIN: ['Singapore', 'Singapore', 'SG', 1.3644, 103.9915],
  NRT: ['Tokyo', 'Japan', 'JP', 35.7720, 140.3929],
  TPE: ['Taipei', 'Taiwan', 'TW', 25.0797, 121.2342],
  YYZ: ['Toronto', 'Canada', 'CA', 43.6777, -79.6248],
  LHR: ['London', 'United Kingdom', 'GB', 51.4700, -0.4543],
  CDG: ['Paris', 'France', 'FR', 49.0097, 2.5479],
  MAD: ['Madrid', 'Spain', 'ES', 40.4983, -3.5676],
  LIS: ['Lisbon', 'Portugal', 'PT', 38.7742, -9.1342],
  ADD: ['Addis Ababa', 'Ethiopia', 'ET', 8.9779, 38.7993],
  NBO: ['Nairobi', 'Kenya', 'KE', -1.3192, 36.9278],
  JNB: ['Johannesburg', 'South Africa', 'ZA', -26.1392, 28.2460],
  HGA: ['Hargeisa', 'Somaliland', 'SO', 9.5182, 44.0888],
  DOH: ['Doha', 'Qatar', 'QA', 25.2731, 51.6081],
};
function airportInfo(code) {
  const [city, country_name, country_code, latitude, longitude] = airports[code];
  return { name: `${city} Airport`, city, country_name, country_code, latitude, longitude };
}
function distance(a, b) {
  const A = airports[a], B = airports[b], radians = value => value * Math.PI / 180;
  const lat = radians(B[3] - A[3]), lon = radians(B[4] - A[4]);
  const h = Math.sin(lat / 2) ** 2 + Math.cos(radians(A[3])) * Math.cos(radians(B[3])) * Math.sin(lon / 2) ** 2;
  return Math.round(6371 * 2 * Math.atan2(Math.sqrt(h), Math.sqrt(1 - h)));
}
function trip(id, title, destination, start, route, offsets) {
  const base = Date.parse(start), iso = hours => new Date(base + hours * 3600000).toISOString();
  const segments = route.slice(1).map((arrival, index) => {
    const departure = route[index], duration = Math.max(1, Math.round(distance(departure, arrival) / 750));
    return { id: id * 100 + index + 1, dep_airport: departure, arr_airport: arrival,
      dep_time: iso(offsets[index]), arr_time: iso(offsets[index] + duration), airline: ['UA', 'SQ', 'KL'][id % 3],
      flight_number: `${['UA', 'SQ', 'KL'][id % 3]}${9000 + index}`, pnr: `QA${id}`, distance_km: distance(departure, arrival),
      meta_json: { source: 'local_ui_qa', confidence: 0.99, nonstop: true,
        enrichment: { airports: { departure: airportInfo(departure), arrival: airportInfo(arrival) } } } };
  });
  return { id, title, start_ts: segments[0].dep_time, end_ts: segments.at(-1).arr_time,
    destination_airport: destination, route_label: `${route[0]} -> ${destination}`, segments };
}
const trips = [
  trip(101, 'Singapore', 'SIN', '2025-05-03T08:00:00Z', ['ORD', 'AMS', 'DXB', 'SIN', 'NRT', 'TPE', 'ORD'], [0, 11, 21, 144, 154, 163]),
  trip(102, 'Lisbon', 'LIS', '2024-09-10T09:00:00Z', ['ORD', 'YYZ', 'LHR', 'CDG', 'MAD', 'LIS', 'ORD'], [0, 5, 72, 144, 192, 288]),
  trip(103, 'Johannesburg', 'JNB', '2023-11-04T06:00:00Z', ['ORD', 'ADD', 'NBO', 'JNB', 'HGA', 'DOH', 'ORD'], [0, 20, 72, 192, 207, 217]),
];
const definitions = [
  [1, 'Japan', 'Tokyo', 'Aoyama Tea Room', 'cafe', 'A quiet courtyard café saved for a future afternoon.', 35.6652, 139.7138, ['tea', 'courtyard']],
  [1, 'Japan', 'Kyoto', 'Canal-side bookshop', 'shopping', 'A small bookshop beside the canal. Check its exact entrance.', null, null, ['books', 'walk']],
  [1, 'Japan', 'Tokyo', 'Night Market Kitchen', 'restaurant', 'A counter dinner to try after exploring the neighborhood.', 35.6718, 139.7041, ['dinner']],
  [2, 'Portugal', 'Lisbon', 'Miradouro morning walk', 'nature', 'A hilltop lookout with room to pause.', 38.7165, -9.1333, ['lookout', 'walk']],
  [2, 'Portugal', 'Porto', 'Riverside Guesthouse', 'hotel', 'A possible base for a few unhurried days.', 41.1406, -8.6110, ['stay']],
  [3, 'Singapore', 'Singapore', 'Botanic Gardens loop', 'nature', 'A green morning route before the city gets busy.', 1.3138, 103.8159, ['garden', 'walk']],
  [3, 'Singapore', 'Singapore', 'Evening hawker stop', 'restaurant', 'Keep this recommendation; the exact stall still needs a pin.', null, null, ['dinner']],
  [4, 'France', 'Paris', 'Canal coffee stop', 'cafe', 'A neighborhood coffee break to add to a walking day.', 48.8712, 2.3638, ['coffee']],
  [4, 'France', 'Lyon', 'Old town courtyard', 'attraction', 'A passageway found in a saved post, awaiting a location check.', null, null, ['architecture']],
];
function initialItems() {
  return definitions.map(([dream_id, country, city, place_name, category, summary, latitude, longitude, tags_json], index) => ({
    id: index + 1, dream_id, source_platform: 'instagram', source_url: `https://www.instagram.com/p/LOCAL_UI_QA_${index + 1}/`,
    caption: 'Synthetic local UI fixture', country, city, place_name, category, summary, latitude, longitude, tags_json,
    needs_review: latitude === null, status: latitude === null ? 'needs_review' : 'confirmed', confidence: latitude === null ? 0.6 : 0.95,
    google_maps_url: latitude === null ? null : `https://www.google.com/maps/search/?api=1&query=${latitude},${longitude}`,
    thumbnail_url: null, created_at: NOW, updated_at: NOW,
  }));
}
function loopback(url) { return ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname); }
function callback(value) {
  try { const url = new URL(value); return url.protocol === 'http:' && loopback(url) && url.pathname === '/oauthredirect' && !url.username && !url.password && !url.search && !url.hash ? url : undefined; }
  catch { return undefined; }
}
function escapeHtml(value) { return value.replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]); }
function createQaHandler() {
  let items = initialItems();
  let nextId = 20;
  const consents = new Map();
  const jobs = new Map();
  function dreams() {
    const groups = new Map();
    for (const item of items) {
      const record = groups.get(item.dream_id) || { id: item.dream_id, title: item.country || 'Unsorted', country: item.country, city: null,
        item_count: 0, needs_review_count: 0, processing_count: 0, created_at: NOW, updated_at: NOW };
      record.item_count += 1; record.needs_review_count += Number(item.needs_review); groups.set(item.dream_id, record);
    }
    return [...groups.values()];
  }
  return async (req, res) => {
    const json = (status, value) => { res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8' }); res.end(JSON.stringify(value)); };
    try {
      const url = new URL(req.url, 'http://127.0.0.1:8001');
      const host = new URL(`http://${req.headers.host || 'invalid'}`);
      if (!loopback(host)) return json(403, { detail: 'This QA server only accepts loopback hosts.' });
      res.setHeader('Cache-Control', 'no-store'); res.setHeader('X-Trotter-QA', 'synthetic-local-only');
      const origin = req.headers.origin;
      if (origin) {
        const parsedOrigin = new URL(origin);
        if (!loopback(parsedOrigin) || parsedOrigin.protocol !== 'http:') return json(403, { detail: 'Loopback UI origin required.' });
        res.setHeader('Access-Control-Allow-Origin', origin); res.setHeader('Vary', 'Origin');
        res.setHeader('Access-Control-Allow-Headers', 'Authorization, Content-Type, ngrok-skip-browser-warning');
        res.setHeader('Access-Control-Allow-Methods', 'GET, POST, DELETE, OPTIONS');
      }
      if (req.method === 'OPTIONS') { res.writeHead(204); return res.end(); }
      if (url.pathname === '/ready') return json(200, { ready: true, qa_only: true, synthetic_trips: trips.length, synthetic_arrival_countries: new Set(trips.flatMap(t => t.segments.map(s => airportInfo(s.arr_airport).country_name))).size });
      if (url.pathname === '/auth/google/start' && req.method === 'GET') {
        const redirect = callback(url.searchParams.get('app_redirect_uri'));
        if (!redirect) return json(400, { detail: 'Only a loopback web /oauthredirect callback is accepted by local QA.' });
        const consent = randomUUID(); consents.set(consent, { redirect, expires: Date.now() + 600000 });
        const action = `/auth/local-callback?consent=${encodeURIComponent(consent)}`;
        res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8', 'Content-Security-Policy': "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'" });
        return res.end(`<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Local Trotter UI QA</title><style>body{font-family:system-ui;background:#f8f7f2;color:#23323b;max-width:400px;margin:15vh auto;padding:24px}h1{font-size:28px}p{line-height:1.6}button{padding:16px;border:0;border-radius:5px;background:#23323b;color:white;font:inherit;width:100%}</style></head><body><h1>Local UI test account</h1><p>Synthetic travel data only. This server does not connect to Google or the production API.</p><form method="POST" action="${escapeHtml(action)}"><button>Local UI test account</button></form></body></html>`);
      }
      if (url.pathname === '/auth/local-callback' && req.method === 'POST') {
        const key = url.searchParams.get('consent'), consent = consents.get(key); consents.delete(key);
        if (!consent || consent.expires < Date.now()) return json(400, { detail: 'Start a new local QA sign-in.' });
        consent.redirect.hash = `token=${TOKEN}`; res.writeHead(303, { Location: consent.redirect.href }); return res.end();
      }
      if (req.headers.authorization !== `Bearer ${TOKEN}`) return json(401, { detail: 'Local UI QA sign-in required.' });
      if (url.pathname === '/auth/me' && req.method === 'GET') return json(200, { user_id: 900001, email: 'alex.qa@example.invalid', name: 'Alex Morgan' });
      if (url.pathname === '/trips' && req.method === 'GET') return json(200, trips);
      const tripMatch = url.pathname.match(/^\/trips\/(\d+)$/);
      if (tripMatch && req.method === 'GET') { const found = trips.find(t => t.id === Number(tripMatch[1])); return json(found ? 200 : 404, found || { detail: 'Trip not found.' }); }
      if (url.pathname === '/dreams' && req.method === 'GET') return json(200, dreams());
      if (url.pathname === '/dream-items' && req.method === 'GET') return json(200, items);
      const dreamMatch = url.pathname.match(/^\/dreams\/(\d+)$/);
      if (dreamMatch && req.method === 'GET') { const found = dreams().find(d => d.id === Number(dreamMatch[1])); return json(found ? 200 : 404, found ? { ...found, items: items.filter(i => i.dream_id === found.id) } : { detail: 'Dream not found.' }); }
      const itemMatch = url.pathname.match(/^\/dream-items\/(\d+)(\/review)?$/);
      if (itemMatch) {
        const item = items.find(i => i.id === Number(itemMatch[1]));
        if (!item) return json(404, { detail: 'Place not found.' });
        if (req.method === 'GET') return json(200, item);
        if (req.method === 'DELETE') { items = items.filter(i => i !== item); return json(200, { deleted: true }); }
        if (req.method === 'POST' && itemMatch[2]) {
          const body = await bodyJson(req);
          const fields = new Set(['place_name', 'city', 'country', 'region_or_neighborhood', 'summary', 'category', 'tags_json', 'google_maps_url']);
          for (const [key, value] of Object.entries(body.edits || {})) if (fields.has(key)) item[key] = value;
          item.needs_review = body.decision !== 'confirm'; item.status = item.needs_review ? 'needs_review' : 'confirmed'; item.updated_at = new Date().toISOString();
          return json(200, item);
        }
      }
      if (url.pathname === '/dreams/share' && req.method === 'POST') {
        const body = await bodyJson(req);
        if (typeof body.source_url !== 'string') return json(422, { detail: 'A source URL is required.' });
        const item = { id: nextId++, dream_id: 99, source_platform: 'instagram', source_url: body.source_url, caption: body.shared_text,
          place_name: 'New local QA save', country: null, city: null, category: 'unknown', summary: 'Local QA keeps this link for manual review; no external post is fetched.',
          tags_json: [], confidence: 0, needs_review: true, status: 'needs_review', latitude: null, longitude: null, thumbnail_url: null,
          google_maps_url: null, created_at: new Date().toISOString(), updated_at: new Date().toISOString() };
        items.push(item); return json(201, item);
      }
      if (url.pathname === '/ingest/gmail/import' && req.method === 'POST') { const id = randomUUID(); jobs.set(id, true); return json(200, { job_id: id }); }
      const job = url.pathname.match(/^\/ingest\/jobs\/(.+)$/);
      if (job && req.method === 'GET' && jobs.has(job[1])) return json(200, { job_id: job[1], state: 'done', scanned_count: 3, parsed_count: 3, segment_count: 18 });
      return json(404, { detail: 'This route is not implemented by the local UI QA server.' });
    } catch { if (!res.headersSent) json(400, { detail: 'Invalid local QA request.' }); else res.end(); }
  };
}
function createQaServer() { return http.createServer(createQaHandler()); }
async function bodyJson(req) {
  let body = '';
  for await (const chunk of req) { body += chunk; if (body.length > 65536) throw new Error('Body too large'); }
  return body ? JSON.parse(body) : {};
}
module.exports = { createQaHandler, createQaServer, trips, initialItems };
if (require.main === module) {
  const port = Number(process.env.TROTTER_QA_PORT || 8001);
  if (!Number.isInteger(port) || port < 1024 || port > 65535) throw new Error('Choose a local QA port between 1024 and 65535');
  createQaServer().listen(port, '127.0.0.1', () => console.log(`Local synthetic Trotter UI QA ready: http://127.0.0.1:${port}/ready`));
}
