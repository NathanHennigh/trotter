const assert=require('node:assert/strict'),{test}=require('node:test'),fs=require('node:fs'),path=require('node:path'),ts=require('typescript');
const cache={};function load(name){const file=path.resolve(__dirname,'../src/components/world-window/dreams',name+'.ts');if(cache[file])return cache[file];const m={exports:{}};const source=ts.transpileModule(fs.readFileSync(file,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;new Function('module','exports','require',source)(m,m.exports,r=>load(path.basename(r)));return cache[file]=m.exports;}
const {browseDreams,needsDreamAttention}=load('dreamBrowse');
const {destinationNames, dreamDestination, exactMapPoint}=load('dreamPresentation');
const {dreamCardTitle,dreamCardMeta}=load('dreamCardPresentation');
const {isMapsSearchUrl,locationNote,locationExplanation}=load('locationPresentation');
const base={id:'1',placeName:'Café Sol',city:'Lisbon',country:'Portugal',summary:'',tags:[],category:'cafe',createdAt:'2026-01-01',sortingState:'sorted',status:'parsed',needsReview:false};
test('search crosses city, country, original caption, and personal notes without mutating store order',()=>{
 const saves=[base,{...base,id:'2',placeName:'Garden',city:'Porto',category:'hotel',personalNote:'Bring Sam',createdAt:'2026-02-01'},{...base,id:'3',placeName:'Museum',category:'museum',caption:'azulejos'}];
 assert.equal(browseDreams(saves,'portugal').length,3);assert.deepEqual(browseDreams(saves,'Sam').map(x=>x.id),['2']);assert.equal(browseDreams(saves,'cafe')[0].id,'1');assert.equal(browseDreams(saves,'azulejos')[0].id,'3');
 assert.equal(browseDreams(saves,'','Porto','Stay')[0].id,'2');assert.deepEqual(browseDreams(saves,'','','Eat & drink').map(x=>x.id),['1']);assert.equal(browseDreams(saves)[0].id,'2');assert.deepEqual(saves.map(x=>x.id),['1','2','3']);
});
test('only actionable saves ask for attention, including failures in known countries',()=>{
 for(const patch of [{sortingState:'running'},{sortingState:'queued'},{uploadStatus:'queued'},{uploadStatus:'sending'},{sortingState:'failed',processingRetryAt:'2099-01-01'},{locationState:'source_details'}])assert.equal(needsDreamAttention({...base,...patch}),false);
 for(const patch of [{sortingState:'failed'},{sortingState:'unavailable'},{sortingState:'needs_details'},{uploadStatus:'failed'},{country:undefined}])assert.equal(needsDreamAttention({...base,...patch}),true);
 assert.equal(needsDreamAttention({...base,country:undefined,locationState:'source_details',sortingState:'needs_details',locationReason:'creator_link_required'}),false);
 assert.equal(needsDreamAttention({...base,country:undefined,locationState:'source_details',uploadStatus:'failed'}),true);
});

test('destinations include islands and regions without manufacturing an exact map pin',()=>{
 const island={...base,id:'2',city:undefined,country:'Greece',regionOrNeighborhood:'Milos',latitude:undefined,longitude:undefined};
 const city={...base,id:'3',city:'Athens',regionOrNeighborhood:'Attica',country:'Greece'};
 assert.equal(dreamDestination(island),'Milos');
 assert.deepEqual(destinationNames([island,{...island,regionOrNeighborhood:'mílos'},city]),['Athens','Milos']);
 assert.equal(browseDreams([island,city],'','Milos')[0].id,'2');
 assert.equal(browseDreams([island,city],'','Attica').length,0,'filter uses the same primary destination as the row');
 assert.deepEqual(browseDreams([island,city],'','','All types','city').map(x=>x.id),['3','2']);
 assert.equal(exactMapPoint(island),undefined);
});

test('promotional calls to action stay in source copy instead of becoming a place headline',()=>{
 const source={...base,placeName:undefined,city:'Milos',country:'Greece',locationState:'source_details',caption:'☀️ Comment LINK for free travel guides and the exact location!'};
 assert.equal(dreamCardTitle(source),'Inspiration in Milos');
 assert.equal(dreamCardMeta(source),'Inspiration · Milos');
 assert.equal(dreamCardTitle({...source,caption:'A little house by the sea. Comment LINK to get the address.'}),'A little house by the sea.');
 assert.equal(dreamCardTitle({...source,placeName:source.caption}),'Inspiration in Milos');
 assert.equal(dreamCardTitle({...source,placeName:'Café del Mar'}),'Café del Mar');
 assert.equal(dreamCardTitle({...source,city:undefined,country:undefined,caption:'🏖️ #travel'}),'Saved inspiration');
});

test('text queries are Maps searches while coordinates, chosen IDs and shared links keep their original meaning',()=>{
 for(const url of ['https://www.google.com/maps/search/?api=1&query=Serenya+Marrakech','https://maps.google.com/?q=Serenya','https://www.google.co.uk/maps/search/Serenya'])assert.equal(isMapsSearchUrl(url),true,url);
 for(const url of ['https://www.google.com/maps/search/?api=1&query=31.6,-7.98','https://www.google.com/maps/search/?api=1&query=Serenya&query_place_id=chosen','https://maps.google.com/?q=place_id:chosen','https://maps.app.goo.gl/shared','https://www.google.com/maps/place/Serenya/data=!3d31.6!4d-7.98','not a URL'])assert.equal(isMapsSearchUrl(url),false,url);
 const saved={...base,googleMapsUrl:'https://www.google.com/maps/search/?api=1&query=Serenya+Marrakech',locationState:'unresolved',locationStatus:'not_found'};
 assert.equal(locationNote(saved),'No confirmed pin');assert.equal(exactMapPoint(saved),undefined);
 assert.equal(locationNote({...saved,latitude:31.6,longitude:-7.98}),undefined,'An actual pin takes priority over a search-only link');
 assert.match(locationExplanation({...saved,locationReason:'ambiguous_match'}),/Several places may match/);
});
