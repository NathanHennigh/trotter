// Shipping collection screens, RN-web projection with real bundled typography.
// Focus and hardware Back behavior are exercised in testCollectionSearch.cjs.
const fs=require('node:fs'),path=require('node:path'),Module=require('node:module'),assert=require('node:assert/strict');
const mobile=path.resolve(__dirname,'..'),from=Module.createRequire(path.join(mobile,'package.json'));
const ts=from('typescript'),React=from('react'),RN=from('react-native-web'),server=from('react-dom/server');
const out=path.resolve(mobile,'../artifacts/collection-headers-20260915');fs.mkdirSync(out,{recursive:true});
let width=320,fontScale=1,search='';const noop=()=>{};
function ScaledText({style,...props}){const s=RN.StyleSheet.flatten(style)||{},scaled={},scale=props.allowFontScaling===false?1:Math.min(fontScale,props.maxFontSizeMultiplier||fontScale);if(s.fontSize)scaled.fontSize=s.fontSize*scale;if(s.lineHeight)scaled.lineHeight=s.lineHeight*scale;return React.createElement(RN.Text,{...props,style:[style,scaled]});}
function ScaledInput({style,...props}){const s=RN.StyleSheet.flatten(style)||{},scaled={};if(s.fontSize)scaled.fontSize=s.fontSize*fontScale;return React.createElement(RN.TextInput,{...props,style:[style,scaled]});}
const load=Module._load;Module._load=function(request,parent,isMain){
 if(request==='react-native')return {...RN,Text:ScaledText,TextInput:ScaledInput,useWindowDimensions:()=>({width,height:920,scale:1,fontScale})};
 if(request==='react-native-svg')return from('react-native-svg/lib/commonjs/elements.web');
 if(request.endsWith('/motion'))return {PressFeedback:RN.Pressable,PaperReveal:RN.View,useReducedMotion:()=>true};
 if(request.endsWith('/experiencePreferences'))return {selectionHaptic:noop};
 return load.call(this,request,parent,isMain);
};
for(const ext of ['.tsx','.ts'])require.extensions[ext]=(module,file)=>{
 let source=fs.readFileSync(file,'utf8');
 // Seed only the parent's controlled query for an initially open search fixture.
 if(file.endsWith('PassportCollections.tsx'))source=source.replace('[query, setQuery] = React.useState("")','[query, setQuery] = React.useState(globalThis.__collectionProofSearch ?? "")');
 module._compile(ts.transpileModule(source,{fileName:file,compilerOptions:{jsx:ts.JsxEmit.ReactJSX,module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,esModuleInterop:true}}).outputText,file);
};
require.extensions['.png']=(module,file)=>module.exports={uri:'data:image/png;base64,'+fs.readFileSync(file).toString('base64')};
const {CountryCollectionIndex}=require(path.join(mobile,'src/components/world-window/passport/CountryCollectionIndex.tsx'));
const {CollectionList}=require(path.join(mobile,'src/components/world-window/passport/PassportCollections.tsx'));
const {buildPassportArchive}=require(path.join(mobile,'src/components/world-window/passport/passport-model.ts'));
const p=(code,city,country,countryCode,lat,lon)=>({code,city,country,countryCode,lat,lon});
const ports={DFW:p('DFW','Dallas–Fort Worth','United States','US',32.9,-97.03),AMS:p('AMS','Amsterdam','Netherlands','NL',52.31,4.76),SIN:p('SIN','Singapore','Singapore','SG',1.36,103.99)};
const segment=(id,from,to,day)=>({id,mode:'flight',depAirport:from,arrAirport:to,depTime:`2025-06-${day}T10:00:00`,arrTime:`2025-06-${day}T19:00:00`,airline:'KL',flightNumber:'1040',depPoint:ports[from],arrPoint:ports[to],distanceMiles:4500});
const trip={id:'fixture',title:'Singapore',city:'Singapore',country:'Singapore',countryCode:'SG',airportCode:'SIN',startDate:'2025-06-19',endDate:'2025-06-25',flightCount:3,segments:[segment('one','DFW','AMS','19'),segment('two','AMS','SIN','20'),segment('three','SIN','DFW','25')],miles:13500,stamp:{shape:'archedCountryCanonical',icon:'singapore_marina_bay_sands',country:'Singapore',color:'#4f755b',date:'2025-06-20',airportCode:'SIN'}};
const archive=buildPassportArchive([trip],{name:'Alex Morgan',homeAirport:'DFW',homeAirportName:'Dallas–Fort Worth',firstFlightDate:'2025-06-19'});
let fonts='';for(const font of ['Newsreader-Regular','Newsreader-Medium','Newsreader-Italic','DMSans-Regular','DMSans-Medium','DMSans-SemiBold','DMSans-Bold','IBMPlexMono-Regular','IBMPlexMono-Medium'])fonts+=`@font-face{font-family:'${font}';src:url(data:font/ttf;base64,${fs.readFileSync(path.join(mobile,'assets/world-window/fonts',font+'.ttf')).toString('base64')})}`;
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||path.join(require('node:os').homedir(),'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'));
(async()=>{const browser=await chromium.launch({headless:true,channel:'chrome'}),cases=[];try{
 for(const w of [320,420])for(const scale of [1,2])for(const kind of ['countries','airports','airlines'])for(const mode of ['closed','search','year']){
  width=w;fontScale=scale;search=mode==='search'?(kind==='airlines'?'KL':'SIN'):'';globalThis.__collectionProofSearch=search;
  const year=mode==='year'?'2025':undefined;
  const body=kind==='countries'?React.createElement(CountryCollectionIndex,{arrivals:archive.arrivals,lifetimeArrivals:archive.arrivals,query:search,setQuery:noop,width,onBack:noop,backLabel:'Passport',onSelect:noop,onSelectUnvisited:noop,year,onClearYear:noop}):React.createElement(CollectionList,{kind,archive,onBack:noop,onSelectCountry:noop,onOpenTrip:noop,year,onClearYear:noop});
  const name=`${kind}-${mode}-${width}-font${scale}`;RN.AppRegistry.registerComponent(name,()=>()=>React.createElement(RN.View,{style:{width,height:920,backgroundColor:'#FAF8F2'}},body));const app=RN.AppRegistry.getApplication(name,{});
  const page=await browser.newPage({viewport:{width,height:920}}),record={name,width,fontScale,requests:[],errors:[]};page.on('pageerror',error=>record.errors.push(error.message));await page.route('**/*',route=>{record.requests.push(route.request().url());route.abort()});
  await page.setContent('<!doctype html><html><head><meta charset="utf-8">'+server.renderToStaticMarkup(app.getStyleElement())+'<style>'+fonts+'html,body{margin:0;background:#FAF8F2}</style></head><body>'+server.renderToStaticMarkup(app.element)+'</body></html>');await page.evaluate(()=>document.fonts.ready);
  record.layout=await page.evaluate(()=>{
   const horizontal=e=>{for(let p=e;p;p=p.parentElement)if(['auto','scroll'].includes(getComputedStyle(p).overflowX)&&p.scrollWidth>p.clientWidth+2)return true;return false};
   const header=document.querySelector('[data-testid="collection-index-header"]'),progress=document.querySelector('[data-testid="collection-progress"]');
   const text=[...document.querySelectorAll('*')].filter(e=>[...e.childNodes].some(n=>n.nodeType===3&&n.textContent.trim())&&!horizontal(e)&&!e.namespaceURI.includes('svg'));
   const overflow=text.filter(e=>{const r=e.getBoundingClientRect();return r.left< -1||r.right>innerWidth+1||e.scrollWidth>e.clientWidth+1}).map(e=>e.textContent);
   const buttons=[...document.querySelectorAll('[role="button"],[role="tab"]')].filter(e=>!horizontal(e)).map(e=>({label:e.getAttribute('aria-label')||e.textContent,rect:e.getBoundingClientRect().toJSON()}));
   return {bodyWidth:document.body.scrollWidth,overflow,buttons,header:header?.getBoundingClientRect().toJSON(),progress:progress?.getBoundingClientRect().toJSON(),search:document.querySelector('input')?.getAttribute('value')??null};
  });
  assert(record.layout.header,'All three collections use the actual shared header');assert(record.layout.progress,'All three collections use the actual shared progress row');
  assert.equal(record.layout.search,mode==='search'?search:null);
  await page.screenshot({path:path.join(out,name+'.png')});cases.push(record);await page.close();
 }
}finally{await browser.close();fs.writeFileSync(path.join(out,'layout-proof.json'),JSON.stringify({scope:'Actual CountryCollectionIndex/CollectionList and shared header/progress, bundled fonts/stamp assets, 320/420px with 1x/2x text. Only controlled search query is seeded for static open state. Intentional horizontal filters excluded from overflow test. RN-web projection, not native GPU/keyboard validation.',cases},null,2));}
assert(cases.every(c=>!c.requests.length&&!c.errors.length&&c.layout.bodyWidth<=c.width&&!c.layout.overflow.length),'Collection header layout overflow or runtime failures; inspect layout-proof.json');
assert(cases.every(c=>c.layout.buttons.every(b=>b.rect.height>=44)),'Collection controls must remain at least 44px tall');
console.log('Collection headers proof passed: 36 native-screen fixtures, 320/420px and 1x/2x text, closed/search/year states.');})().catch(error=>{console.error(error);process.exitCode=1});
