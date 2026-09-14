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
const flush=async()=>{for(let n=0;n<30;n++)await Promise.resolve();};
function serviceEnvironment() {
  let token = 'account-a', revision = 1, fetcher = async () => response(200, []), cursor = 0, effects = [], slots = [], listeners = new Set();
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
  const changeToken = value => { token = value; revision++; listeners.forEach(fn => fn()); };
  const auth = { getApiBaseUrl: () => 'https://api.example.invalid', getStoredToken: () => token, hydrateStoredToken: async () => token, getAuthRevision: () => revision,
    subscribeAuthToken: fn => { listeners.add(fn); return () => listeners.delete(fn); }, clearAuthToken: async () => changeToken(undefined) };
  const module = load('services/dreams.ts', { react, './travelTrips': auth }, 'module.exports.testState=useDreamsState;module.exports.testFetch=dreamsAuthenticatedFetch;', {
    fetch: async (url, init) => { calls.push({ url, init }); return fetcher(url, init); }, setTimeout: setTimer, clearTimeout: id => timers.delete(id),
  });
  return { module, calls, clock, changeToken, fetcher: fn => fetcher = fn,
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

test('ambiguous candidates stay unpinned until confirmation, and malformed coordinates are excluded', async () => {
  const env=serviceEnvironment();
  const candidate={id:'one',name:'Cafe One',address:'1 Synthetic Road',latitude:38.7,longitude:-9.1,google_maps_url:'https://www.google.com/maps/search/?api=1&query=38.7,-9.1'};
  env.fetcher(async url=>response(200,url.endsWith('/dream-items')?[apiItem(1,{location_status:'needs_review',location_candidates:[candidate,{...candidate,id:'bad',latitude:null}]})]:[]));
  env.render(); await flush(); let state=env.render();
  assert.equal(state.items[0].locationCandidates.length,1); assert.equal(dreams.exactMapPoint(state.items[0]),undefined);
  assert.equal(locations.canFindLocation(state.items[0]),false); assert.equal(locations.locationNote(state.items[0]),'Check location');
  env.fetcher(async()=>response(200,apiItem(1,{location_status:'manual',google_maps_url:candidate.google_maps_url,latitude:38.7,longitude:-9.1})));
  await state.confirmLocation('1','one'); assert.deepEqual(JSON.parse(env.calls.at(-1).init.body),{candidate_id:'one'});
  state=env.render(); assert.equal(dreams.exactMapPoint(state.items[0]).lat,38.7); assert.equal(locations.canFindLocation(state.items[0]),false); env.dispose();
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

test('a failed Dreams endpoint does not release its refresh while the sibling request is pending', async () => {
  const env = serviceEnvironment(), sibling = deferred();
  env.fetcher(async url => url.endsWith('/dream-items') ? sibling.promise : response(503, { detail: 'Synthetic unavailable endpoint' }));
  const first = env.render().refresh(); await flush();
  const second = env.render().refresh(); assert.equal(first, second); assert.equal(env.calls.length, 2);
  await env.clock.advance(10000); assert.equal(env.calls.length, 2);
  sibling.resolve(response(200, [])); await first;
  assert.equal(env.render().status, 'error'); assert.match(env.render().error, /unavailable endpoint/);
  env.dispose();
});
