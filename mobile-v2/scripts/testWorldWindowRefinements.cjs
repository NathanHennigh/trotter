// Offline acceptance of production presentation and map behavior; no live records.
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');
const ts = require('typescript'), {test} = require('node:test');
const root = path.resolve(__dirname, '..'), modules = new Map();
function load(file, mocks = {}, extra = '') {
  const absolute = path.resolve(root, file);
  if (!extra && modules.has(absolute)) return modules.get(absolute);
  if (absolute.endsWith('.json')) return JSON.parse(fs.readFileSync(absolute, 'utf8'));
  const code = ts.transpileModule(fs.readFileSync(absolute,'utf8'), {compilerOptions:{jsx:ts.JsxEmit.React,module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,esModuleInterop:true}}).outputText;
  const mod = {exports:{}};
  new Function('require','module','exports',code+'\n'+extra)(ref => {
    if (ref in mocks) return mocks[ref];
    const base=path.resolve(path.dirname(absolute),ref);
    const found=[base,base+'.ts',base+'.tsx',base+'.json'].find(p=>fs.existsSync(p)&&fs.statSync(p).isFile());
    assert(found,'Unmocked dependency: '+ref);
    return load(path.relative(root,found),mocks);
  },mod,mod.exports);
  if (!extra) modules.set(absolute,mod.exports); return mod.exports;
}
const presentation=load('src/components/world-window/trips/tripPresentation.ts');
const leg=(id,from,to,date)=>({id,depAirport:from,arrAirport:to,depTime:date+'T08:00:00',arrTime:date+'T10:00:00'});
test('Wallet shows Singapore across an overnight connection and preserves every return leg',()=>{
  const trip={airportCode:'SIN',segments:[leg('a','IAH','NRT','2025-09-28'),leg('b','NRT','SIN','2025-09-30'),leg('c','SIN','NRT','2025-10-07'),leg('d','NRT','IAH','2025-10-07')]};
  const snapshot=JSON.stringify(trip), result=presentation.walletSummary(trip);
  assert.deepEqual(result.shown.map(g=>[g.first.depAirport,g.last.arrAirport,g.via]),[['IAH','SIN',['NRT']],['SIN','IAH',['NRT']]]);
  assert.equal(result.hidden,0); assert.equal(JSON.stringify(trip),snapshot);
  assert.deepEqual(presentation.tripItineraries(trip).flatMap(g=>g.legs).map(f=>f.id),['a','b','c','d']);
});
test('Wallet does not invent a flight across an open-jaw surface transfer',()=>{
  const trip={airportCode:'FCO',segments:[leg('a','DFW','LHR','2026-04-01'),leg('b','CDG','FCO','2026-04-07'),leg('c','FCO','DFW','2026-04-11')]};
  const result=presentation.walletSummary(trip);
  assert.equal(result.shown[0].last.arrAirport,'LHR'); assert.equal(result.hidden,1);
  assert.equal(result.shown[1].first.depAirport,'FCO');
  assert.deepEqual(presentation.walletSummary({segments:[]}),{shown:[],hidden:0});
});
test('Trip-year membership matches recorded departure years, including cross-year trips',()=>{
  const trip={title:'Singapore',startDate:'2025-12-30',endDate:'2026-01-05',segments:[leg('a','DFW','NRT','2025-12-30'),leg('b','NRT','SIN','2026-01-02')]};
  assert(presentation.tripInYear(trip,2026)); assert(presentation.matchesTrip(trip,'singapore',true,2026));
  assert(!presentation.tripInYear(trip,2024));
  assert(presentation.tripInYear({startDate:'2025-12-30',endDate:'2026-01-05',segments:[]},2026));
});
test('Country overview frames Thailand and dateline islands without creating a place pin',()=>{
  const {countryRegion}=load('src/components/world-window/dreams/countryRegion.ts');
  const thailand=countryRegion('Thailand');assert(thailand);assert(thailand.bounds[0][0]>0);assert(thailand.bounds[0][1]>90);assert(thailand.bounds[1][1]<110);
  const fiji=countryRegion('Fiji');assert(fiji);assert(fiji.bounds[1][1]-fiji.bounds[0][1]<30);
  const france=countryRegion('France');assert(france);assert(france.bounds[1][1]-france.bounds[0][1]<30);
  assert.equal(countryRegion('Unsorted'),undefined);
  assert.deepEqual(Object.keys(thailand).sort(),['bounds','label']);
});
test('Damaged captions retain the source while displaying only recoverable text or known metadata',()=>{
  const {dreamCopy}=load('src/components/world-window/dreams/dreamCopy.ts');
  const item={category:'cafe',city:'Krabi',country:'Thailand',summary:'Beautiful coffee ?? ???'};
  const original=JSON.stringify(item), result=dreamCopy(item);
  assert.equal(result.summary,'Café in Krabi, Thailand.'); assert.equal(result.original,item.summary);assert.equal(JSON.stringify(item),original);
  assert.deepEqual(dreamCopy({...item,summary:'What would you order?'}),{summary:'What would you order?'});
  assert.deepEqual(dreamCopy({...item,summary:'東京のカフェ'}),{summary:'東京のカフェ'});
  assert.deepEqual(dreamCopy({...item,summary:'Itâ€™s lovely'}),{summary:'It’s lovely',original:'Itâ€™s lovely'});
  assert.deepEqual(dreamCopy({...item,summary:undefined}),{});
});
test('Empty-map fitting uses the country, fits the first real pin, and preserves pan on selection',()=>{
  const mod=load('src/components/world-window/trips/PaperMap.tsx',{'react':{},'react-native':{StyleSheet:{create:v=>v}},'react-native-webview':{},'../../../theme/trotterTheme':{colors:{},fonts:{}}},'exports.html=mapHTML;');
  const scripts=[...mod.html.matchAll(/<script>([\s\S]*?)<\/script>/g)];
  const elements=new Map(),fits=[];
  const element=()=>({style:{},setAttribute(){},appendChild(){}});
  const document={getElementById(id){if(!elements.has(id))elements.set(id,element());return elements.get(id)},createElement:element,createElementNS:element};
  const map={setView(){return this},attributionControl:{setPrefix(){}},fitBounds(bounds,options){fits.push({bounds,options})},invalidateSize(){},on(){}};
  const group=()=>({addTo(){return this},on(){return this},clearLayers(){},addLayer(){}});
  const L={map:()=>map,tileLayer:group,layerGroup:group,markerClusterGroup:group,latLngBounds:v=>v,divIcon:v=>v,polyline:group,marker:()=>({bindTooltip(){},on(){}})};
  const window={addEventListener(){},parent:{postMessage(){}}};
  vm.runInNewContext(scripts[2][1],{window,document,L});
  const overview={label:'Thailand',bounds:[[5,97],[21,106]]};
  window.drawTravelMap({points:[],fitKey:'TH',overview});
  assert.deepEqual(fits[0].bounds,overview.bounds);assert.equal(elements.get('fit').textContent,'Country view');
  const point={id:'one',label:'Cafe',lat:8,lon:99};
  window.drawTravelMap({points:[point],fitKey:'TH',overview});assert.equal(fits.length,2);
  window.drawTravelMap({points:[point],fitKey:'TH',overview,selectedId:'one'});assert.equal(fits.length,2);
  window.drawTravelMap({points:[],fitKey:'unsorted'});assert.equal(elements.get('fit').disabled,true);assert.equal(fits.length,2);
});
