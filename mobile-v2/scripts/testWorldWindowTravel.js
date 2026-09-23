const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const ts=require('typescript');
const {test}=require('node:test');
const root=path.join(__dirname,'../src');
function load(file,mocks={},extra='',globals={}){const source=fs.readFileSync(path.join(root,file),'utf8');const output=ts.transpileModule(source,{fileName:file,compilerOptions:{jsx:ts.JsxEmit.ReactJSX,module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2020,esModuleInterop:true}}).outputText;const module={exports:{}};new Function('module','exports','require',...Object.keys(globals),output+'\n'+extra)(module,module.exports,key=>{if(key in mocks)return mocks[key];throw new Error(`Unexpected dependency ${key}`);},...Object.values(globals));return module.exports;}
const trip=load('components/world-window/trips/tripPresentation.ts');
const dreams=load('components/world-window/dreams/dreamPresentation.ts');
const locations=load('components/world-window/dreams/locationPresentation.ts',{'./dreamPresentation':dreams});
test('bundled native map HTML has complete executable scripts and no runtime CDN dependency',()=>{const assets=load('components/world-window/trips/leafletAssets.ts'),symbols=load('components/world-window/dreams/placeSymbols.ts');const map=load('components/world-window/trips/PaperMap.tsx',{'react':{},'react/jsx-runtime':{},'react-native':{StyleSheet:{create:value=>value}},'react-native-webview':{},'../../../theme/trotterTheme':{colors:{},fonts:{}},'./leafletAssets':assets,'../dreams/placeSymbols':symbols},'module.exports.html=mapHTML;');const scripts=[...map.html.matchAll(/<script>([\s\S]*?)<\/script>/g)];assert.equal(scripts.length,3);for(const script of scripts)new(require('node:vm').Script)(script[1]);assert(!/<script[^>]+src=/i.test(map.html));assert(assets.leafletLicense.includes('BSD'));assert(assets.clusterLicense.includes('MIT'));});
const place=(id,changes={})=>({id:String(id),dreamId:'one',sourcePlatform:'instagram',sourceUrl:`https://www.instagram.com/reel/${id}`,category:'cafe',placeName:`Place ${id}`,city:'Lisbon',country:'Portugal',summary:'Saved place',tags:[],needsReview:false,status:'confirmed',createdAt:'2026-01-01',updatedAt:'2026-01-01',...changes});
const segment=(id,dep,arr,day,changes={})=>({id,mode:'flight',depAirport:dep,arrAirport:arr,depTime:`2026-02-${day}T10:30:00`,arrTime:`2026-02-${day}T12:20:00`,...changes});

test('wallet coupons separate visits while keeping connections and every recorded flight',()=>{
 const flights=[segment('home','ATL','IAH','23',{depTime:'2026-02-23T14:00:00'}),segment('out','IAH','IAD','18'),segment('orlando','IAD','MCO','21'),segment('return','MCO','ATL','23')];
 const groups=trip.tripItineraries({segments:flights,airportCode:'MCO'});
 assert.deepEqual(groups.map(g=>g.legs.map(f=>f.id)),[['out'],['orlando'],['return','home']]);
 assert.deepEqual(groups[2].via,['ATL']);
 assert.equal(groups.flatMap(g=>g.legs).length,flights.length);
 assert.equal(flights[0].id,'home');
 assert.equal(trip.tripItineraries({segments:[]}).length,0);
});

test('native paper atlas fits Pacific routes and handles absent geometry without invalid paths',()=>{
 const atlas=load('components/world-window/trips/tripAtlasGeometry.ts',{'./tripPresentation':trip});
 const point=(code,lat,lon)=>({code,city:code,lat,lon});
 const flights=[segment('pacific','SFO','NRT','21',{depPoint:point('SFO',37.62,-122.38),arrPoint:point('NRT',35.77,140.39)})];
 const map=atlas.tripAtlasGeometry(flights,null,'NRT');
 assert.equal(map.paths.length,1);assert.equal(map.ports.length,2);assert(!/NaN|Infinity/.test(map.paths[0]));
 assert(map.ports.every(p=>p.x>=0&&p.x<=400&&p.y>=0&&p.y<=230));
 assert(map.ports.find(p=>p.code==='NRT').x>map.ports.find(p=>p.code==='SFO').x-400);
 assert.deepEqual(atlas.tripAtlasGeometry([],null),{landPath:'',paths:[],ports:[]});
 const unknown=atlas.tripAtlasGeometry([segment('missing','A','B','21')],null);assert.equal(unknown.paths.length,0);
 const coincident=atlas.tripAtlasGeometry([segment('same','A','B','21',{depPoint:point('A',0,0),arrPoint:point('B',0,0)})],null);assert(!/NaN|Infinity/.test(coincident.paths[0]));
});

test('country boards retain every save across uneven city/category collections',()=>{const input=Array.from({length:28},(_,index)=>place(index,{category:index<7?'cafe':index<23?'restaurant':'hotel',city:index<20?'Lisbon':'Porto'}));const [board]=dreams.countryBoards(input);assert.equal(board.items.length,28);assert.equal(board.cities.length,2);assert.equal(dreams.filterDreams(input,'','','Cafés').length,7);assert.equal(dreams.filterDreams(input,'','','Restaurants').length,16);assert.equal(dreams.filterDreams(input,'','','Hotels').length,5);assert.equal(dreams.filterDreams(input,'','Porto','All').length,8);});
test('country aliases group consistently and missing locations remain visible',()=>{const boards=dreams.countryBoards([place(1,{country:'USA'}),place(2,{country:'United States'}),place(3,{country:undefined,status:'failed'})]);assert.equal(boards.length,2);assert.equal(boards[0].items.length,2);assert.equal(boards[1].title,'Unsorted');assert.equal(dreams.filterDreams([place(1,{placeName:'Café João'})],'cafe joao','','All').length,1);});
test('map points use exact pin/geometry and never a map camera or city centre',()=>{assert.equal(dreams.exactMapPoint(place(1,{googleMapsUrl:'https://google.com/maps/@38.7,-9.1,13z'})),undefined);assert.equal(dreams.exactMapPoint(place(1,{googleMapsUrl:'https://google.com/maps/search/?query=Lisbon'})),undefined);const pin=dreams.exactMapPoint(place(1,{googleMapsUrl:'https://google.com/maps/search/?query=0%2C0'}));assert.equal(pin.lat,0);assert.equal(pin.lon,0);const raw=dreams.exactMapPoint(place(1,{latitude:38.7,longitude:-9.1,coordinatePrecision:'area'}));assert.equal(raw.area,true);assert.equal(dreams.exactMapPoint(place(1,{latitude:99,longitude:181})),undefined);assert.equal(dreams.safeWebUrl('javascript:alert(1)'),undefined);});
test('flight dates preserve recorded local clock, unknown times and cross-year dates',()=>{assert.equal(trip.flightTime('2026-02-21T23:45:00+09:00'),'23:45');assert.equal(trip.flightTime('2026-02-21'),'—');assert.equal(trip.calendarDate('2026-02-30'),undefined);assert.equal(trip.calendarDate('2024-02-29'),'2024-02-29');assert.match(trip.tripDates({startDate:'2025-12-30',endDate:'2026-01-05'}),/2025.*2026/);});
test('all flights including connections and return survive chronological presentation',()=>{const flights=[segment('home','ATL','IAH','23'),segment('out','IAD','MCO','21'),segment('return','MCO','ATL','23',{depTime:'2026-02-23T07:30:00',arrTime:'2026-02-23T09:20:00'}),segment('unknown','IAH','JFK','21',{depTime:''})];assert.deepEqual(trip.orderedSegments(flights).map(f=>f.id),['out','return','home','unknown']);assert.equal(flights[0].id,'home');assert.match(trip.connectionText(flights[1],flights[2]),/MCO.*day/);assert.match(trip.connectionText(flights[2],flights[0]),/ATL connection/);assert.match(trip.connectionText(flights[0],{...flights[3],depTime:'2026-02-24'}),/timing needs review/);});
test('route map includes every known leg and identifies missing geometry without dropping flights',()=>{const points={IAH:{code:'IAH',city:'Houston',lat:29.9,lon:-95.3},ATL:{code:'ATL',city:'Atlanta',lat:33.6,lon:-84.4},MCO:{code:'MCO',city:'Orlando',lat:28.4,lon:-81.3}};const flights=[segment('one','IAH','MCO','21',{depPoint:points.IAH,arrPoint:points.MCO}),segment('two','MCO','ATL','23',{depPoint:points.MCO,arrPoint:points.ATL}),segment('three','ATL','IAH','23',{depPoint:points.ATL,arrPoint:points.IAH}),segment('missing','IAH','JFK','24')];const map=trip.tripMapData(flights);assert.equal(map.lines.length,3);assert.equal(map.points.length,3);assert.deepEqual(map.lines[2],{id:'three',from:'ATL',to:'IAH'});assert.equal(flights.length,4);});

const response=(status,body)=>({status,ok:status>=200&&status<300,text:async()=>JSON.stringify(body)});
const flush=async()=>{for(let n=0;n<120;n++)await Promise.resolve();};
function serviceEnvironment(options = {}) {
  let token = 'account-a', revision = 1, accountId = options.accountId ?? 11, fetcher = async () => response(200, []), cursor = 0, effects = [], slots = [], listeners = new Set();
  let now = 0, nextTimer = 0;
  const calls = [], timers = new Map();
  const setTimer = (fn, ms) => { const id = ++nextTimer; timers.set(id, { fn, due: now + ms, ms }); return id; };
  const clock = {
    pending: () => [...timers.values()].map(timer => timer.ms),
    async advance(ms) {
      const target = now + ms;
      for (;;) {
        const next = [...timers].filter(([, timer]) => timer.due <= target).sort((a, b) => a[1].due - b[1].due)[0];
        if (!next) break;
        now = next[1].due; timers.delete(next[0]); next[1].fn(); await flush();
      }
      now = target; await flush();
    },
  };
  const same = (a, b) => a && b && a.length === b.length && a.every((value, index) => value === b[index]);
  const react = {
    createContext: () => ({}), createElement: () => ({}), useContext: () => undefined,
    useState(initial) { const i = cursor++; if (!(i in slots)) slots[i] = typeof initial === 'function' ? initial() : initial; return [slots[i], value => { slots[i] = typeof value === 'function' ? value(slots[i]) : value; }]; },
    useRef(value) { const i = cursor++; if (!(i in slots)) slots[i] = { current: value }; return slots[i]; },
    useMemo(fn, deps) { const i = cursor++; if (!slots[i] || !same(slots[i].deps, deps)) slots[i] = { value: fn(), deps }; return slots[i].value; },
    useCallback(fn, deps) { return this.useMemo(() => fn, deps); },
    useEffect(fn, deps) { const i = cursor++; if (!slots[i] || !same(slots[i].deps, deps)) { slots[i]?.cleanup?.(); slots[i] = { deps }; effects.push(() => { slots[i].cleanup = fn(); }); } },
  };
  const storage = options.storage ?? new Map();
  const storageAdapter = { failWrite: false, getItem: async key => storage.get(key) ?? null,
    async setItem(key, value) { if (this.failWrite) throw Error('storage full'); storage.set(key, value); }, removeItem: async key => storage.delete(key) };
  const TestDate = class extends Date { constructor(...args) { super(...(args.length ? args : [Date.parse('2026-09-23T12:00:00Z') + now])); } static now() { return Date.parse('2026-09-23T12:00:00Z') + now; } };
  const outbox = load('services/dreamShareOutbox.ts', { '@react-native-async-storage/async-storage': storageAdapter }, '', { Date: TestDate });
  const appListeners = new Set();
  const AppState = { currentState: options.appState ?? 'active', addEventListener: (_name, fn) => { appListeners.add(fn); return { remove: () => appListeners.delete(fn) }; } };
  const changeToken = value => { token = value; revision++; listeners.forEach(fn => fn()); };
  const auth = { getApiBaseUrl: () => 'https://api.example.invalid', getStoredToken: () => token, hydrateStoredToken: async () => token, getAuthRevision: () => revision,
    useTravelTrips: () => ({ accountId, authStatus: token ? 'signed-in' : 'signed-out' }),
    subscribeAuthToken: fn => { listeners.add(fn); return () => listeners.delete(fn); }, clearAuthToken: async () => changeToken(undefined) };
  const module = load('services/dreams.ts', { react, './travelTrips': auth, './dreamShareOutbox': outbox, 'react-native': { AppState } }, 'module.exports.testState=useDreamsState;module.exports.testFetch=dreamsAuthenticatedFetch;', {
    fetch: async (url, init) => { calls.push({ url, init }); return fetcher(url, init); }, setTimeout: setTimer, clearTimeout: id => timers.delete(id),
    Date: TestDate,
  });
  return { module, calls, clock, changeToken, storage, storageAdapter, outbox: outbox.dreamShareOutbox,
    owner: { apiBaseUrl: auth.getApiBaseUrl(), ownerId: accountId },
    foreground(value = 'active') { AppState.currentState = value; appListeners.forEach(fn => fn(value)); }, fetcher: fn => fetcher = fn,
    render() { cursor = 0; const state = module.testState(); const pending = effects; effects = []; pending.forEach(fn => fn()); return state; },
    dispose() { slots.forEach(slot => slot?.cleanup?.()); },
  };
}
const apiItem=(id,changes={})=>({id,dream_id:1,source_platform:'instagram',source_url:`https://www.instagram.com/reel/${id}`,category:'cafe',place_name:'Cafe One',city:'Lisbon',country:'Portugal',summary:'Notes',tags_json:[],needs_review:true,status:'needs_review',created_at:'2026-01-01',...changes});

test('Dreams fetches all user items, including unassigned/review saves',async()=>{const env=serviceEnvironment();env.fetcher(async url=>response(200,url.endsWith('/dream-items')?[apiItem(1),apiItem(2,{dream_id:999,country:null})]:[]));env.render();await flush();const state=env.render();assert.equal(state.items.length,2);assert.equal(state.needsReviewItems.length,2);assert.equal(env.calls.length,2);env.dispose();});
test('Dreams 401 clears auth and never obtains a developer account or retries',async()=>{const env=serviceEnvironment();env.fetcher(async()=>response(401,{detail:'Expired'}));await assert.rejects(env.module.testFetch('/dream-items'),/expired/);assert.equal(env.calls.length,1);assert(!env.calls.some(call=>call.url.includes('dev-token')));await assert.rejects(env.module.testFetch('/dream-items'),/Sign in/);assert.equal(env.calls.length,1);});
test('old-account responses cannot populate Dreams after sign out',async()=>{const env=serviceEnvironment();let resolve;const pending=new Promise(done=>resolve=done);env.fetcher(async()=>pending);env.render();env.changeToken(undefined);resolve(response(200,[apiItem(1)]));await flush();assert.deepEqual(env.render().items,[]);env.dispose();});
test('failed edit retains item; confirmed edit persists to backend with location and review decision',async()=>{const env=serviceEnvironment();env.fetcher(async url=>response(200,url.endsWith('/dream-items')?[apiItem(1)]:[]));env.render();await flush();let state=env.render();env.fetcher(async()=>response(503,{detail:'Offline'}));await assert.rejects(state.updateItem('1',{placeName:'Corrected place'}),/Offline/);assert.equal(env.render().items[0].placeName,'Cafe One');env.fetcher(async()=>response(200,apiItem(1,{place_name:'Corrected place',city:'Porto',status:'confirmed',needs_review:false})));await state.updateItem('1',{placeName:'Corrected place',city:'Porto',needsReview:false});state=env.render();assert.equal(state.items[0].city,'Porto');assert.equal(state.needsReviewItems.length,0);const request=env.calls.at(-1);assert.equal(request.init.method,'POST');assert.equal(JSON.parse(request.init.body).edits.place_name,'Corrected place');assert.equal(JSON.parse(request.init.body).decision,'confirm');env.dispose();});
test('delete is server-first and a failure cannot remove the local save',async()=>{const env=serviceEnvironment();env.fetcher(async url=>response(200,url.endsWith('/dream-items')?[apiItem(1),apiItem(2)]:[]));env.render();await flush();env.fetcher(async()=>response(500,{detail:'Try later'}));await assert.rejects(env.render().deleteItem('1'),/Try later/);assert.equal(env.render().items.length,2);env.fetcher(async()=>response(204,{}));await env.render().deleteItem('1');assert.deepEqual(env.render().items.map(item=>item.id),['2']);assert.equal(env.calls.at(-1).init.method,'DELETE');env.dispose();});
test('capture rejects bad links and keeps failed post with original caption for retry',async()=>{const env=serviceEnvironment();env.render();await flush();env.fetcher(async()=>response(503,{detail:'Offline'}));const state=env.render();assert.equal(state.shareInstagramLink('not-a-url'),undefined);const pending=state.shareInstagramLink('https://www.instagram.com/reel/new','Original caption');assert(pending);await flush();const item=env.render().items[0];assert.equal(item.status,'failed');assert.equal(item.caption,'Original caption');assert.match(item.sourceUrl,/reel\/new/);env.dispose();});

const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };

test('location queue polls until resolved and automatically creates a real attributed pin', async () => {
  const env = serviceEnvironment();
  env.fetcher(async url => response(200, url.endsWith('/dream-items') ? [apiItem(1), apiItem(2)] : []));
  env.render(); await flush(); env.render();
  env.fetcher(async () => response(200, { queued: 1, items: [apiItem(1, { location_status: 'queued' })] }));
  await env.render().locateMissing(['1','1']);
  assert.deepEqual(JSON.parse(env.calls.at(-1).init.body), {item_ids:[1]});
  let state=env.render(); assert.equal(state.items.length,2); assert.equal(state.locatingItems.length,1);
  assert.equal(dreams.exactMapPoint(state.items[0]),undefined);
  const pending=deferred(); env.fetcher(async url=>{ await pending.promise; return response(200,url.endsWith('/dream-items')?[apiItem(1,{location_status:'resolved',location_provider:'geoapify',location_address:'1 Synthetic Road',latitude:38.71,longitude:-9.13,coordinate_precision:'place'}),apiItem(2)]:[]); });
  await env.clock.advance(5000); const count=env.calls.length;
  await env.clock.advance(12000); assert.equal(env.calls.length,count,'Slow location polls never overlap');
  pending.resolve(); await flush(); state=env.render();
  assert.equal(state.locatingItems.length,0); assert.equal(state.items[0].locationAddress,'1 Synthetic Road');
  assert.equal(dreams.exactMapPoint(state.items[0]).provider,'geoapify');
  assert.equal(env.clock.pending().filter(ms=>ms===5000).length,0); env.dispose();
});

test('legacy candidates wait for automatic resolution, while malformed coordinates are excluded', async () => {
  const env=serviceEnvironment();
  const candidate={id:'one',name:'Cafe One',address:'1 Synthetic Road',latitude:38.7,longitude:-9.1,google_maps_url:'https://www.google.com/maps/search/?api=1&query=38.7,-9.1'};
  env.fetcher(async url=>response(200,url.endsWith('/dream-items')?[apiItem(1,{location_status:'needs_review',location_candidates:[candidate,{...candidate,id:'bad',latitude:null}]})]:[]));
  env.render(); await flush(); let state=env.render();
  assert.equal(state.items[0].locationCandidates.length,1); assert.equal(dreams.exactMapPoint(state.items[0]),undefined);
  assert.equal(locations.canFindLocation(state.items[0]),true); assert.equal(locations.locationNote(state.items[0]),'Finding location…');
  env.fetcher(async url=>response(200,url.endsWith('/dream-items')?[apiItem(1,{location_status:'resolved',location_provider:'google_places',
    location_place_id:'one',location_expires_at:'2099-01-01',location_user_confirmed:false,latitude:38.7,longitude:-9.1})]:[]));
  await state.refresh();
  assert(!env.calls.some(call=>call.url.endsWith('/location-confirm')));
  state=env.render(); assert.equal(dreams.exactMapPoint(state.items[0]).lat,38.7); assert.equal(locations.canFindLocation(state.items[0]),false); env.dispose();
});

test('terminal Google review results stop polling, and an explicit refresh can discover a later resolution', async () => {
  const env=serviceEnvironment();
  env.fetcher(async url=>response(200,url.endsWith('/dream-items')?[apiItem(1,{location_status:'needs_review',location_provider:'google_places'})]:[]));
  env.render(); await flush(); let state=env.render();
  assert.equal(state.locatingItems.length,0);
  const calls = env.calls.length;
  await env.clock.advance(10000); assert.equal(env.calls.length, calls, 'Review is not an active server job');
  env.fetcher(async url=>response(200,url.endsWith('/dream-items')?[apiItem(1,{location_status:'resolved',location_provider:'google_places',
    location_place_id:'automatic',location_expires_at:'2099-01-01',location_user_confirmed:false,latitude:38.7,longitude:-9.1})]:[]));
  await state.refresh(); await flush(); state=env.render();
  assert.equal(state.locatingItems.length,0); assert.equal(dreams.exactMapPoint(state.items[0]).lat,38.7);
  assert(!env.calls.some(call=>call.init?.method==='POST')); env.dispose();
});

test('location failures retain all saves and duplicate queue/edit writes are guarded', async () => {
  const env=serviceEnvironment(); env.fetcher(async url=>response(200,url.endsWith('/dream-items')?[apiItem(1)]:[]));
  env.render(); await flush(); let state=env.render();
  const pending=deferred(); env.fetcher(()=>pending.promise); const request=state.locateItem('1');
  await assert.rejects(state.locateItem('1'),/still saving/); await assert.rejects(state.updateItem('1',{city:'Porto'}),/still saving/);
  pending.resolve(response(503,{detail:'Temporary failure'})); await assert.rejects(request,/Temporary failure/);
  state=env.render(); assert.equal(state.items.length,1); assert.equal(state.items[0].placeName,'Cafe One');
  env.fetcher(async()=>response(404,{})); await assert.rejects(state.locateItem('1'),/not available on this server/);
  assert.equal(env.render().items.length,1); env.dispose();
});

test('account changes invalidate an in-flight location result', async () => {
  const env=serviceEnvironment(); env.fetcher(async url=>response(200,url.endsWith('/dream-items')?[apiItem(1)]:[])); env.render(); await flush();
  const pending=deferred(); env.fetcher(()=>pending.promise); const result=env.render().locateItem('1');
  const rejected=assert.rejects(result,/account changed/); env.changeToken('account-b'); await rejected;
  pending.resolve(response(200,apiItem(1,{location_status:'resolved',latitude:1,longitude:1}))); await flush();
  assert.deepEqual(env.render().items,[]); env.dispose();
});

test('large country location requests use bounded batches without losing saves',async()=>{
  const env=serviceEnvironment(), records=Array.from({length:1001},(_,index)=>apiItem(index+1));
  env.fetcher(async url=>response(200,url.endsWith('/dream-items')?records:[])); env.render(); await flush();
  env.fetcher(async(_url,init)=>{const ids=JSON.parse(init.body).item_ids;return response(200,{queued:ids.length,items:ids.map(id=>({...records[id-1],location_status:'queued'}))});});
  await env.render().locateMissing(records.map(record=>String(record.id)));
  const batches=env.calls.filter(call=>call.url.endsWith('/locate-missing')).map(call=>JSON.parse(call.init.body).item_ids.length);
  assert.deepEqual(batches,[250,250,250,250,1]); const state=env.render(); assert.equal(state.items.length,1001); assert.equal(state.locatingItems.length,1001); env.dispose();
});

test('location actions preserve manual pins and incomplete saves without claiming false progress',()=>{
  assert.equal(locations.canFindLocation(place(1)),true);
  for(const changes of [{id:'dream-item-pending'}, {placeName:''}, {status:'processing'}, {locationStatus:'running'}, {locationStatus:'queued'}, {latitude:38,longitude:-9}, {googleMapsUrl:'https://www.google.com/maps/search/?query=38,-9'}]) assert.equal(locations.canFindLocation(place(1,changes)),false);
  assert.equal(locations.locationNote(place(1,{locationStatus:'blocked'})),'Location lookup unavailable');
  assert.equal(locations.isFindingLocation(place(1,{locationStatus:'failed'})),false);
});
test('slow Dreams polls apply completed results and concurrent refreshes share one request pair', async () => {
  const env = serviceEnvironment();
  env.fetcher(async url => response(200, url.endsWith('/dream-items') ? [apiItem(1, { status: 'processing' })] : []));
  env.render(); await flush(); env.render();
  const pending = deferred(); env.fetcher(async url => { await pending.promise; return response(200, url.endsWith('/dream-items') ? [apiItem(1, { status: 'confirmed', needs_review: false })] : []); });
  await env.clock.advance(5000); assert.equal(env.calls.length, 4);
  const first = env.render().refresh(), second = env.render().refresh();
  assert.equal(first, second);
  await env.clock.advance(12000); assert.equal(env.calls.length, 4, 'No overlapping poll despite multiple intervals passing');
  pending.resolve(); await first; await flush();
  assert.equal(env.render().items[0].status, 'confirmed');
  assert.equal(env.clock.pending().filter(ms => ms === 5000).length, 0, 'No poll remains after processing stops');
  env.dispose();
});

test('Dreams deadlines cover stalled headers and stalled bodies; timeout never deletes a retained item', async () => {
  const env = serviceEnvironment();
  env.fetcher(async url => response(200, url.endsWith('/dream-items') ? [apiItem(1)] : []));
  env.render(); await flush();
  const headers = deferred(); env.fetcher(() => headers.promise);
  const deletion = env.render().deleteItem('1'); const rejected = assert.rejects(deletion, /may still finish.*Refresh saved places/);
  await env.clock.advance(30000); await rejected;
  assert.equal(env.render().items.length, 1); assert.equal(env.calls.at(-1).init.signal.aborted, true);
  headers.resolve(response(204, {})); await flush(); assert.equal(env.render().items.length, 1, 'Late success cannot commit after timeout');
  const body = deferred(); env.fetcher(async () => ({ status: 200, ok: true, text: () => body.promise }));
  const saving = env.render().updateItem('1', { placeName: 'Updated' }); const bodyRejected = assert.rejects(saving, /timed out/);
  await env.clock.advance(30000); await bodyRejected;
  assert.equal(env.render().items[0].placeName, 'Cafe One');
  body.resolve(JSON.stringify(apiItem(1, { place_name: 'Updated' }))); await flush();
  assert.equal(env.render().items[0].placeName, 'Cafe One'); env.dispose();
});

test('an old Dreams refresh cannot overwrite a successful edit or deletion', async () => {
  const env = serviceEnvironment();
  env.fetcher(async url => response(200, url.endsWith('/dream-items') ? [apiItem(1), apiItem(2)] : []));
  env.render(); await flush();
  const old = deferred(); env.fetcher(async url => { await old.promise; return response(200, url.endsWith('/dream-items') ? [apiItem(1), apiItem(2)] : []); });
  const refresh = env.render().refresh();
  env.fetcher(async url => url.endsWith('/review') ? response(200, apiItem(1, { place_name: 'New name' })) : response(204, {}));
  await env.render().updateItem('1', { placeName: 'New name' }); await env.render().deleteItem('2');
  old.resolve(); await refresh;
  assert.deepEqual(env.render().items.map(item => [item.id, item.placeName]), [['1', 'New name']]); env.dispose();
});

test('duplicate concurrent writes are blocked and account changes abort pending Dreams requests', async () => {
  const env = serviceEnvironment();
  env.fetcher(async url => response(200, url.endsWith('/dream-items') ? [apiItem(1)] : []));
  env.render(); await flush();
  const pending = deferred(); env.fetcher(() => pending.promise);
  const save = env.render().updateItem('1', { placeName: 'New name' });
  await assert.rejects(env.render().deleteItem('1'), /still saving/);
  const rejected = assert.rejects(save, /account changed/);
  env.changeToken('account-b'); await rejected;
  assert.equal(env.calls.at(-1).init.signal.aborted, true);
  assert.deepEqual(env.render().items, []);
  pending.resolve(response(200, apiItem(1, { place_name: 'New name' }))); await flush();
  assert.deepEqual(env.render().items, []); env.dispose();
});

test('a failed board endpoint does not release a refresh early or discard a successful items response', async () => {
  const env = serviceEnvironment(), sibling = deferred();
  env.fetcher(async url => url.endsWith('/dream-items') ? sibling.promise : response(503, { detail: 'Synthetic unavailable endpoint' }));
  const first = env.render().refresh(); await flush();
  const second = env.render().refresh(); assert.equal(first, second); assert.equal(env.calls.length, 2);
  await env.clock.advance(10000); assert.equal(env.calls.length, 2);
  sibling.resolve(response(200, [apiItem(1)])); await first;
  assert.equal(env.render().status, 'idle'); assert.equal(env.render().error, undefined);
  assert.equal(env.render().items[0].id, '1');
  env.dispose();
});

const shareAck = (id, status = 'created') => response(200, { dream_item_id: id, dream_id: 1, status });
const sharePosts = env => env.calls.filter(call => call.url.endsWith('/dreams/share'));

test('durable share resolves after disk commit, before network acknowledgement, and failed GETs cannot strand it', async () => {
  const env = serviceEnvironment(); env.render(); await flush();
  const disk = deferred(), network = deferred(), write = env.storageAdapter.setItem;
  let firstWrite = true, received = false;
  env.storageAdapter.setItem = async function(key, value) { if (firstWrite) { firstWrite = false; await disk.promise; } return write.call(this, key, value); };
  env.fetcher((url, init) => init?.method === 'POST' ? network.promise : Promise.resolve(response(503, { detail: 'Lists unavailable' })));
  const receiving = env.render().shareInstagramLinkDurable('https://www.instagram.com/reel/shared/?igsh=abc', 'A lovely cafe').then(() => { received = true; });
  await flush(); assert.equal(received, false); assert.equal(sharePosts(env).length, 0);
  disk.resolve(); await receiving; await flush();
  assert.equal(received, true); assert.equal(sharePosts(env).length, 1);
  let state = env.render(); assert.equal(state.pendingUploadItems.length, 1); assert.equal(state.processingItems.length, 0);
  assert.equal((await env.outbox.list(env.owner))[0].sharedText, 'A lovely cafe');
  network.resolve(shareAck(42)); await flush(); state = env.render();
  assert.equal(state.items.length, 1); assert.equal(state.items[0].id, '42'); assert.equal(state.items[0].status, 'created');
  assert.equal(state.pendingUploadItems.length, 0); assert.equal(state.processingItems.length, 1);
  assert.deepEqual(await env.outbox.list(env.owner), []); assert.equal(state.status, 'idle'); env.dispose();
});

test('offline shares keep their caption through bounded retries, cold restore, and a foreground retry', async () => {
  const env = serviceEnvironment(); env.render(); await flush(); env.fetcher(async () => response(503, { detail: 'Offline' }));
  await env.render().shareInstagramLinkDurable('https://instagram.com/p/offline', 'Useful caption'); await flush();
  assert.equal(sharePosts(env).length, 1); assert.equal(env.render().pendingUploadItems[0].uploadStatus, 'failed');
  assert.equal(env.render().processingItems.length, 0);
  await env.clock.advance(5000); assert.equal(sharePosts(env).length, 2);
  await env.clock.advance(10000); assert.equal(sharePosts(env).length, 3);
  await env.clock.advance(20000); assert.equal(sharePosts(env).length, 4);
  await env.clock.advance(300000); assert.equal(sharePosts(env).length, 4, 'Automatic retries stop rather than spin forever');
  const storage = env.storage; env.dispose();
  const cold = serviceEnvironment({ storage, appState: 'background' }); cold.render(); await flush();
  assert.equal(cold.render().pendingUploadItems[0].caption, 'Useful caption'); assert.equal(sharePosts(cold).length, 0);
  cold.fetcher(async (url, init) => init?.method === 'POST' ? shareAck(81, 'needs_review') : response(503, {}));
  cold.foreground(); await flush();
  assert.equal(sharePosts(cold).length, 1); assert.equal(cold.render().items[0].id, '81');
  assert.equal(cold.render().items[0].status, 'needs_review'); assert.equal(cold.render().processingItems.length, 0);
  assert.deepEqual(await cold.outbox.list(cold.owner), []); cold.dispose();
});

test('late upload acknowledgement cannot cross an account change; only the same verified owner restores it', async () => {
  const env = serviceEnvironment(); env.render(); await flush(); const network = deferred();
  env.fetcher((url, init) => init?.method === 'POST' ? network.promise : Promise.resolve(response(200, [])));
  await env.render().shareInstagramLinkDurable('https://instagram.com/reel/ownerA', 'Private caption'); await flush();
  env.changeToken('unverified-replacement'); network.resolve(shareAck(31)); await flush();
  assert.deepEqual(env.render().items, []);
  await assert.rejects(env.render().shareInstagramLinkDurable('https://instagram.com/reel/notVerified'), /Sign in/);
  const storage = env.storage; env.dispose();
  const other = serviceEnvironment({ storage, accountId: 22 }); other.render(); await flush();
  assert.deepEqual(other.render().items, []); assert.equal(sharePosts(other).length, 0); other.dispose();
  const verifiedSame = serviceEnvironment({ storage, accountId: 11 });
  verifiedSame.fetcher(async (url, init) => init?.method === 'POST' ? shareAck(31) : response(200, []));
  verifiedSame.render(); await flush();
  assert.equal(sharePosts(verifiedSame).length, 1); assert.equal(verifiedSame.render().items[0].id, '31');
  assert.deepEqual(await verifiedSame.outbox.list(verifiedSame.owner), []); verifiedSame.dispose();
});

test('simultaneous native delivery variants enqueue and POST one canonical Instagram link', async () => {
  const env = serviceEnvironment(); env.render(); await flush(); const network = deferred();
  env.fetcher((url, init) => init?.method === 'POST' ? network.promise : Promise.resolve(response(200, [])));
  const state = env.render();
  await Promise.all([state.shareInstagramLinkDurable('https://www.instagram.com/reel/duplicate/?igsh=one', 'Caption'),
    state.shareInstagramLinkDurable('https://instagram.com/reel/duplicate#other', 'Caption')]);
  await flush(); assert.equal(sharePosts(env).length, 1); assert.equal((await env.outbox.list(env.owner)).length, 1);
  network.resolve(shareAck(77)); await flush(); assert.equal(env.render().items.length, 1);
  assert.deepEqual(await env.outbox.list(env.owner), []); env.dispose();
});

test('an older list response cannot resurrect a share placeholder or delete its accepted server receipt', async () => {
  const env = serviceEnvironment(); env.render(); await flush(); const older = deferred(), network = deferred();
  env.fetcher((url, init) => init?.method === 'POST' ? network.promise : older.promise);
  const refresh = env.render().refresh();
  await env.render().shareInstagramLinkDurable('https://instagram.com/p/newer'); await flush();
  network.resolve(shareAck(95)); await flush(); assert.equal(env.render().items[0].id, '95');
  older.resolve(response(200, [])); await refresh; await flush();
  assert.deepEqual(env.render().items.map(item => item.id), ['95']); assert.equal(env.render().pendingUploadItems.length, 0);
  env.fetcher(async () => response(200, [])); await env.render().refresh();
  assert.deepEqual(env.render().items.map(item => item.id), ['95'], 'A lagging list preserves an acknowledged ID until it observes it'); env.dispose();
});

test('retrying a saved review item persists its intent and uses the parse endpoint with its caption', async () => {
  const env = serviceEnvironment(); env.fetcher(async url => response(200, url.endsWith('/dream-items') ? [apiItem(13)] : []));
  env.render(); await flush(); const parse = deferred();
  env.fetcher((url, init) => url.endsWith('/13/parse') ? parse.promise : Promise.resolve(response(503, {})));
  await env.render().shareInstagramLinkDurable('https://instagram.com/reel/13', 'A clearer place name'); await flush();
  assert.equal(sharePosts(env).length, 0);
  const call = env.calls.find(call => call.url.endsWith('/13/parse')); assert(call);
  assert.deepEqual(JSON.parse(call.init.body), { caption: 'A clearer place name' });
  assert.equal((await env.outbox.list(env.owner))[0].retryItemId, '13');
  parse.resolve(response(200, apiItem(13, { status: 'processing', needs_review: false, processing_message: 'Finding places' })));
  await flush(); const state = env.render(); assert.equal(state.items[0].id, '13');
  assert.equal(state.items[0].processingMessage, 'Finding places'); assert.equal(state.processingItems.length, 1);
  assert.deepEqual(await env.outbox.list(env.owner), []); env.dispose();
});

test('deleting an unsent receipt cancels durable upload, while an active upload cannot be deleted', async () => {
  const env = serviceEnvironment({ appState: 'background' }); env.render(); await flush();
  await env.render().shareInstagramLinkDurable('https://instagram.com/p/cancel'); await flush();
  const item = env.render().items[0]; await env.render().deleteItem(item.id);
  assert.deepEqual(await env.outbox.list(env.owner), []); assert.equal(sharePosts(env).length, 0);
  env.foreground(); await flush(); assert.equal(sharePosts(env).length, 0);
  const network = deferred(); env.fetcher((url, init) => init?.method === 'POST' ? network.promise : Promise.resolve(response(200, [])));
  await env.render().shareInstagramLinkDurable('https://instagram.com/p/sending'); await flush();
  await assert.rejects(env.render().deleteItem(env.render().items[0].id), /being sent/);
  assert.equal((await env.outbox.list(env.owner)).length, 1);
  network.resolve(shareAck(101)); await flush(); assert.equal(env.render().items[0].id, '101'); env.dispose();
});

test('storage rejection keeps a native receipt unconsumed and never starts its POST', async () => {
  const env = serviceEnvironment(); env.render(); await flush(); env.storageAdapter.failWrite = true;
  await assert.rejects(env.render().shareInstagramLinkDurable('https://instagram.com/p/diskFull'), /storage full/);
  assert.equal(sharePosts(env).length, 0); assert.deepEqual(await env.outbox.list(env.owner), []);
  env.storageAdapter.failWrite = false;
  env.fetcher(async (url, init) => init?.method === 'POST' ? shareAck(102) : response(200, []));
  await env.render().shareInstagramLinkDurable('https://instagram.com/p/diskFull'); await flush();
  assert.equal(sharePosts(env).length, 1); assert.equal(env.render().items[0].id, '102'); env.dispose();
});

test('editing and retrying a saved post exclude each other, so a late parse cannot erase confirmed edits', async () => {
  const env = serviceEnvironment(); env.fetcher(async url => response(200, url.endsWith('/dream-items') ? [apiItem(13)] : []));
  env.render(); await flush(); const parse = deferred();
  env.fetcher(() => parse.promise);
  await env.render().shareInstagramLinkDurable('https://instagram.com/reel/13', 'A clearer caption'); await flush();
  await assert.rejects(env.render().updateItem('13', { placeName: 'My chosen place', needsReview: false }), /queued for reading/);
  parse.resolve(response(200, apiItem(13, { status: 'needs_review' }))); await flush();
  const edit = deferred(); env.fetcher(() => edit.promise);
  const save = env.render().updateItem('13', { placeName: 'My chosen place', needsReview: false });
  await assert.rejects(env.render().shareInstagramLinkDurable('https://instagram.com/reel/13'), /still saving/);
  edit.resolve(response(200, apiItem(13, { place_name: 'My chosen place', status: 'confirmed', needs_review: false })));
  await save; assert.equal(env.render().items[0].placeName, 'My chosen place'); assert.equal(env.render().items[0].status, 'confirmed'); env.dispose();
});

test('a caption received during the first upload is sent in a second durable generation', async () => {
  const env = serviceEnvironment(); env.render(); await flush(); const first = deferred(), second = deferred(); let posts = 0;
  env.fetcher((url, init) => init?.method === 'POST' ? (++posts === 1 ? first.promise : second.promise) : Promise.resolve(response(503, {})));
  await env.render().shareInstagramLinkDurable('https://instagram.com/p/captionLater'); await flush();
  await env.render().shareInstagramLinkDurable('https://instagram.com/p/captionLater', 'The cafe is in Porto'); await flush();
  first.resolve(shareAck(80)); await flush();
  assert.equal(posts, 2); assert.equal(JSON.parse(sharePosts(env)[1].init.body).shared_text, 'The cafe is in Porto');
  assert.equal((await env.outbox.list(env.owner))[0].sharedText, 'The cafe is in Porto');
  second.resolve(shareAck(80)); await flush(); assert.deepEqual(await env.outbox.list(env.owner), []); env.dispose();
});

test('a queued retry whose server item is already gone can still be discarded', async () => {
  const env = serviceEnvironment(); env.fetcher(async url => response(200, url.endsWith('/dream-items') ? [apiItem(13)] : []));
  env.render(); await flush(); env.fetcher(async () => response(404, { detail: 'Dream item not found' }));
  await env.render().shareInstagramLinkDurable('https://instagram.com/reel/13'); await flush();
  assert.equal(env.render().pendingUploadItems.length, 1);
  await env.render().deleteItem('13');
  assert.deepEqual(await env.outbox.list(env.owner), []); assert.deepEqual(env.render().items, []); env.dispose();
});

test('a list exposing the first share before its ACK cannot unlock edits or location mutations prematurely', async () => {
  const env = serviceEnvironment(); env.render(); await flush(); const network = deferred();
  const visibleItem = apiItem(312, { source_url: 'https://www.instagram.com/reel/firstPending/?igsh=list', status: 'needs_review' });
  env.fetcher(async (url, init) => {
    if (url.endsWith('/dreams/share')) return network.promise;
    if (url.endsWith('/312/review')) return response(200, { ...visibleItem, place_name: 'My confirmed cafe', status: 'confirmed', needs_review: false });
    return response(200, url.endsWith('/dream-items') ? [visibleItem] : []);
  });
  await env.render().shareInstagramLinkDurable('https://instagram.com/reel/firstPending'); await flush();
  assert.equal((await env.outbox.list(env.owner))[0].retryItemId, undefined, 'This is the original share, not a parse retry');
  await env.render().refresh('quiet'); await flush();
  const exposed = env.render(); assert.equal(exposed.items[0].id, '312'); assert.equal(exposed.items[0].uploadStatus, 'sending');
  const callsBefore = env.calls.length;
  await assert.rejects(exposed.updateItem('312', { placeName: 'My confirmed cafe', needsReview: false }), /queued for reading/);
  await assert.rejects(exposed.locateItem('312'), /queued for reading/);
  await assert.rejects(exposed.confirmLocation('312', 'candidate'), /queued for reading/);
  await assert.rejects(exposed.locateMissing(['312']), /queued for reading/);
  assert.equal(env.calls.length, callsBefore, 'No edit or location POST can race the outstanding share ACK');
  network.resolve(shareAck(312)); await flush();
  assert.deepEqual(await env.outbox.list(env.owner), []);
  await env.render().updateItem('312', { placeName: 'My confirmed cafe', needsReview: false }); await flush();
  assert.equal(env.render().items[0].placeName, 'My confirmed cafe'); assert.equal(env.render().items[0].status, 'confirmed');
  assert.equal(env.render().pendingUploadItems.length, 0); env.dispose();
});

test('terminal duplicate ACKs show saved copy and quietly recover their details without overlapping or background requests', async () => {
  for (const terminal of ['parsed', 'confirmed']) {
    const env = serviceEnvironment(); env.render(); await flush();
    env.fetcher(async (url, init) => init?.method === 'POST' ? shareAck(401, terminal) : response(503, { detail: 'Lists temporarily unavailable' }));
    await env.render().shareInstagramLinkDurable('https://instagram.com/p/alreadySaved'); await flush();
    let state = env.render();
    assert.equal(state.items[0].status, terminal); assert.equal(state.items[0].summary, 'Saved to Dreams. Refresh to load details.');
    assert.equal(state.processingItems.length, 0); assert.equal(state.pendingUploadItems.length, 0); assert.equal(state.status, 'idle');
    assert.deepEqual(await env.outbox.list(env.owner), []);
    const calls = env.calls.length;
    await env.clock.advance(5000); assert.equal(env.calls.length, calls + 2, 'Receipt details retry even though server sorting is finished');
    assert.equal(env.render().status, 'idle', 'Receipt recovery stays quiet');
    env.foreground('background'); const beforeBackground = env.calls.length;
    await env.clock.advance(10000); assert.equal(env.calls.length, beforeBackground);
    const recovered = deferred();
    env.fetcher(async url => url.endsWith('/dream-items') ? recovered.promise : response(200, []));
    env.foreground(); await flush(); const duringRecovery = env.calls.length;
    await env.clock.advance(10000); assert.equal(env.calls.length, duringRecovery, 'A slow receipt refresh shares the existing request pair');
    recovered.resolve(response(200, [apiItem(401, { source_url: 'https://instagram.com/p/alreadySaved', status: terminal,
      needs_review: false, place_name: 'Recovered cafe', summary: 'Full saved place details' })]));
    await flush(); state = env.render();
    assert.equal(state.items[0].placeName, 'Recovered cafe'); assert.equal(state.items[0].summary, 'Full saved place details');
    assert.equal(env.clock.pending().filter(ms => ms === 5000).length, 0);
    const afterRecovery = env.calls.length; await env.clock.advance(10000);
    assert.equal(env.calls.length, afterRecovery, 'A terminal record stops polling once the list has observed it'); env.dispose();
  }
});

test('terminal ACK preserves known details that arrived from a list while the share was pending', async () => {
  const env = serviceEnvironment(); env.render(); await flush(); const network = deferred(); let listAvailable = true;
  const known = apiItem(402, { source_url: 'https://instagram.com/p/knownDetails', status: 'parsed', needs_review: false,
    summary: 'Known cafe notes', place_name: 'Already sorted cafe' });
  env.fetcher(async (url, init) => init?.method === 'POST' ? network.promise
    : listAvailable ? response(200, url.endsWith('/dream-items') ? [known] : []) : response(503, {}));
  await env.render().shareInstagramLinkDurable('https://instagram.com/p/knownDetails'); await flush();
  await env.render().refresh('quiet'); listAvailable = false;
  network.resolve(shareAck(402, 'parsed')); await flush();
  assert.equal(env.render().items[0].summary, 'Known cafe notes'); assert.equal(env.render().items[0].placeName, 'Already sorted cafe');
  assert.equal(env.render().processingItems.length, 0); env.dispose();
});
