// Shipping Countries UI, bundled stamp assets/fonts and synthetic first entries.
// RN-web projection checks settled layout; this is not a native paint/gesture test.
const fs=require('node:fs'),path=require('node:path'),Module=require('node:module'),assert=require('node:assert/strict');
const mobile=path.resolve(__dirname,'..'),from=Module.createRequire(path.join(mobile,'package.json'));
const ts=from('typescript'),React=from('react'),RN=from('react-native-web'),server=from('react-dom/server');
const out=path.resolve(mobile,'../artifacts/countries-collection-20260915');fs.mkdirSync(out,{recursive:true});
let width=320,fontScale=1,initialFilter='visited';
const noop=()=>{};
function ScaledText({style,...props}){const s=RN.StyleSheet.flatten(style)||{},scaled={},scale=props.allowFontScaling===false?1:Math.min(fontScale,props.maxFontSizeMultiplier||fontScale);if(s.fontSize)scaled.fontSize=s.fontSize*scale;if(s.lineHeight)scaled.lineHeight=s.lineHeight*scale;return React.createElement(RN.Text,{...props,style:[style,scaled]});}
function ScaledInput({style,...props}){const s=RN.StyleSheet.flatten(style)||{},scaled={};if(s.fontSize)scaled.fontSize=s.fontSize*fontScale;return React.createElement(RN.TextInput,{...props,style:[style,scaled]});}
const original=Module._load;Module._load=function(request,parent,isMain){
 if(request==='react-native')return {...RN,Text:ScaledText,TextInput:ScaledInput,useWindowDimensions:()=>({width,height:920,scale:1,fontScale})};
 if(request==='react-native-svg')return from('react-native-svg/lib/commonjs/elements.web');
 if(request.endsWith('/motion'))return {PressFeedback:RN.Pressable,PaperReveal:RN.View,useReducedMotion:()=>true};
 if(request.endsWith('/experiencePreferences'))return {selectionHaptic:noop};
 return original.call(this,request,parent,isMain);
};
for(const ext of ['.tsx','.ts'])require.extensions[ext]=(m,file)=>{
 let source=fs.readFileSync(file,'utf8');
 // SSR fixtures can start on All without altering shipping styles or structure.
 if(file.endsWith('CountryCollectionIndex.tsx'))source=source.replace('React.useState<Filter>("visited")','React.useState<Filter>(globalThis.__countryProofFilter ?? "visited")');
 m._compile(ts.transpileModule(source,{fileName:file,compilerOptions:{jsx:ts.JsxEmit.ReactJSX,module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,esModuleInterop:true}}).outputText,file);
};
require.extensions['.png']=(m,file)=>m.exports={uri:'data:image/png;base64,'+fs.readFileSync(file).toString('base64')};
const {CountryCollectionIndex,UnvisitedCountryRecord}=require(path.join(mobile,'src/components/world-window/passport/CountryCollectionIndex.tsx'));
const {stampIdentity}=require(path.join(mobile,'src/components/trotter/stamps/stampIdentity.ts'));
const records=[
 ['Somaliland','X-SOMALILAND','HGA','2019-09-13','somaliland_laas_geel'],['Tunisia','TN','TUN','2021-06-21','tunisia_el_jem'],
 ['Japan','JP','NRT','2020-05-01','japan_mount_fuji'],['Singapore','SG','SIN','2024-06-22','singapore_marina_bay_sands'],
 ['United Arab Emirates','AE','DXB','2022-01-17','united_arab_emirates_burj_khalifa'],['Philippines','PH','MNL','2023-09-23','philippines_mayon_volcano'],
 ['Netherlands','NL','AMS','2022-06-04','netherlands_amsterdam_canal_houses'],['Dominican Republic','DO','PUJ','2021-11-08','dominican_republic_puerta_del_conde'],
];
const arrivals=records.map(([country,travelCountryKey,airportCode,firstVisitDate,icon])=>({country,travelCountryKey,airportCode,firstVisitDate,airportCount:1,tripCount:2,stamp:{...stampIdentity(country,travelCountryKey),country,airportCode,date:firstVisitDate,icon}}));
let fonts='';for(const font of ['Newsreader-Regular','Newsreader-Medium','Newsreader-Italic','DMSans-Regular','DMSans-Medium','DMSans-SemiBold','DMSans-Bold','IBMPlexMono-Regular','IBMPlexMono-Medium'])fonts+=`@font-face{font-family:'${font}';src:url(data:font/ttf;base64,${fs.readFileSync(path.join(mobile,'assets/world-window/fonts',font+'.ttf')).toString('base64')})}`;
const playwrightPath=process.env.PLAYWRIGHT_MODULE || path.join(require('node:os').homedir(),'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const {chromium}=require(playwrightPath);
if(require.main===module)(async()=>{const browser=await chromium.launch({headless:true,channel:'chrome'}),cases=[];try{
 for(const w of [320,410])for(const scale of [1,2])for(const kind of ['visited','directory','all-search','scoped-search','unvisited']){
  width=w;fontScale=scale;globalThis.__countryProofFilter=kind.includes('search')||kind==='directory'?'all':'visited';
  const body=kind==='unvisited'?React.createElement(UnvisitedCountryRecord,{entry:{key:'GS',name:'South Georgia and the South Sandwich Islands',region:'Antarctica'},width,onBack:noop}):React.createElement(CountryCollectionIndex,{arrivals:kind==='scoped-search'?arrivals.filter(a=>a.firstVisitDate.startsWith('2024')):arrivals,lifetimeArrivals:arrivals,query:kind==='all-search'?'guinea':kind==='scoped-search'?'united':'',setQuery:noop,width,onBack:noop,backLabel:'Passport',onSelect:noop,onSelectUnvisited:noop,year:kind==='scoped-search'?'2024':undefined,onClearYear:noop});
  const name=`${kind}-${width}-font${scale}`;RN.AppRegistry.registerComponent(name,()=>()=>React.createElement(RN.View,{style:{width,backgroundColor:'#faf8f2'}},body));const app=RN.AppRegistry.getApplication(name,{});
  const page=await browser.newPage({viewport:{width,height:920},deviceScaleFactor:1});const record={name,width,fontScale,requests:[],errors:[]};page.on('pageerror',e=>record.errors.push(e.message));await page.route('**/*',r=>{record.requests.push(r.request().url());r.abort()});
  await page.setContent('<!doctype html><html><head><meta charset="utf-8">'+server.renderToStaticMarkup(app.getStyleElement())+'<style>'+fonts+'html,body{margin:0;background:#faf8f2}</style></head><body>'+server.renderToStaticMarkup(app.element)+'</body></html>');await page.evaluate(()=>document.fonts.ready);
  record.layout=await page.evaluate(()=>{
   const inHorizontalScroller=e=>{for(let p=e;p;p=p.parentElement)if(['auto','scroll'].includes(getComputedStyle(p).overflowX)&&p.scrollWidth>p.clientWidth+2)return true;return false};
   const text=[...document.querySelectorAll('*')].filter(e=>[...e.childNodes].some(n=>n.nodeType===3&&n.textContent.trim())&&!inHorizontalScroller(e));
   const overflow=text.map(e=>({text:e.textContent,rect:e.getBoundingClientRect().toJSON()})).filter(x=>x.rect.left< -1||x.rect.right>innerWidth+1);
   const splits=[];for(const e of text){if(e.namespaceURI.includes('svg'))continue;for(const n of e.childNodes){if(n.nodeType!==3)continue;for(const word of n.textContent.matchAll(/[^\s]+/g)){const range=document.createRange();range.setStart(n,word.index);range.setEnd(n,word.index+word[0].length);if(!/[–—-]/.test(word[0])&&new Set([...range.getClientRects()].map(r=>Math.round(r.top))).size>1)splits.push(word[0]);}}}
   return {bodyWidth:document.body.scrollWidth,overflow,wordSplits:splits,buttons:[...document.querySelectorAll('[role=button]')].filter(e=>!inHorizontalScroller(e)).map(e=>({label:e.getAttribute('aria-label')||e.textContent,rect:e.getBoundingClientRect().toJSON()}))};
  });
  await page.screenshot({path:path.join(out,name+'.png'),fullPage:kind!=='directory'});cases.push(record);await page.close();
 }
}finally{await browser.close();fs.writeFileSync(path.join(out,'layout-proof.json'),JSON.stringify({scope:'Actual native CountryCollectionIndex and UnvisitedCountryRecord, RN-web SSR projection with bundled fonts/stamp assets and synthetic first entries. Font scaling simulated at 1x/2x. Only initial filter seeded for static All state. Scrollable continent labels deliberately excluded from viewport overflow checks. Not native GPU, touch, keyboard or TalkBack validation.',cases},null,2));}
assert(cases.every(c=>!c.requests.length&&!c.errors.length&&c.layout.bodyWidth<=c.width&&!c.layout.overflow.length&&!c.layout.wordSplits.length),'Country layout has overflow, split words or runtime failures; inspect layout-proof.json');
assert(cases.every(c=>c.layout.buttons.every(b=>b.rect.height>=44)),'Touch targets must remain 44px tall');console.log('Countries layout proof passed: 20 actual native component fixtures at 320/410px and 1x/2x text, including every catalogue name, no network.');})().catch(e=>{console.error(e);process.exitCode=1});
