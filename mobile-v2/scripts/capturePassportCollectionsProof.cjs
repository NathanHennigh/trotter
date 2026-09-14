// Actual native collection components rendered through RN Web at their settled
// state. Offline layout proof only; Android gesture arbitration is separate.
const fs=require('node:fs'),path=require('node:path'),Module=require('node:module'),assert=require('node:assert/strict');
const mobile=path.resolve(__dirname,'..'),fromMobile=Module.createRequire(path.join(mobile,'package.json'));
const ts=fromMobile('typescript'),React=fromMobile('react'),native=fromMobile('react-native-web'),server=fromMobile('react-dom/server');
const out=path.resolve(mobile,'../artifacts/world-window-fidelity'); let width=410;
const original=Module._load;
Module._load=function(request,parent,isMain){
  if(request==='react-native')return {...native,useWindowDimensions:()=>({width,height:900,scale:1,fontScale:1})};
  if(request==='react-native-svg')return fromMobile('react-native-svg/lib/commonjs/elements.web');
  if(request.endsWith('/motion'))return {PressFeedback:native.Pressable,PaperReveal:native.View,useReducedMotion:()=>true};
  if(request.endsWith('/experiencePreferences'))return {selectionHaptic(){}};
  return original.call(this,request,parent,isMain);
};
for(const ext of ['.tsx','.ts'])require.extensions[ext]=(module,file)=>module._compile(ts.transpileModule(fs.readFileSync(file,'utf8'),{fileName:file,compilerOptions:{jsx:ts.JsxEmit.ReactJSX,module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2020,esModuleInterop:true}}).outputText,file);
require.extensions['.png']=(module,file)=>module.exports={uri:'data:image/png;base64,'+fs.readFileSync(file).toString('base64')};
const {CollectionList,CountryArrivalDetail}=require(path.join(mobile,'src/components/world-window/passport/PassportCollections.tsx'));
const {ActivityChart}=require(path.join(mobile,'src/components/world-window/passport/ActivityChart.tsx'));
const {buildPassportArchive}=require(path.join(mobile,'src/components/world-window/passport/passport-model.ts'));
const p=(code,city,country,countryCode,lat,lon)=>({code,city,country,countryCode,lat,lon});
const ports={DFW:p('DFW','Dallas–Fort Worth','United States','US',32.9,-97.03),AMS:p('AMS','Amsterdam','Netherlands','NL',52.31,4.76),SIN:p('SIN','Singapore','Singapore','SG',1.36,103.99)};
const segment=(id,from,to,day)=>({id,mode:'flight',depAirport:from,arrAirport:to,depTime:`2025-06-${day}T10:00:00`,arrTime:`2025-06-${day}T19:00:00`,airline:'KL',flightNumber:'1040',depPoint:ports[from],arrPoint:ports[to],distanceMiles:4500});
const trip={id:'fixture',title:'Singapore',city:'Singapore',country:'Singapore',countryCode:'SG',airportCode:'SIN',startDate:'2025-06-19',endDate:'2025-06-25',flightCount:3,segments:[segment('one','DFW','AMS','19'),segment('two','AMS','SIN','20'),segment('three','SIN','DFW','25')],miles:13500,stamp:{shape:'archedCountryCanonical',icon:'singapore_marina_bay_sands',country:'Singapore',color:'#4f755b',date:'2025-06-20',airportCode:'SIN'}};
const archive=buildPassportArchive([trip],{name:'Alex Morgan',homeAirport:'DFW',homeAirportName:'Dallas–Fort Worth',firstFlightDate:'2025-06-19'});
let fontCss=''; for(const font of ['Newsreader-Regular','Newsreader-Medium','Newsreader-Italic','DMSans-Regular','DMSans-Medium','DMSans-SemiBold','DMSans-Bold','IBMPlexMono-Regular','IBMPlexMono-Medium']) {
  const file=path.join(mobile,'assets/world-window/fonts',font+'.ttf');if(fs.existsSync(file))fontCss+=`@font-face{font-family:'${font}';src:url(data:font/ttf;base64,${fs.readFileSync(file).toString('base64')})}`;
}
const {chromium}=require('C:/Users/natha/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
(async()=>{const browser=await chromium.launch({headless:true,channel:'chrome'});const report=[];
try {for(width of [320,410])for(const kind of ['airports','airport-detail','country-detail','activity']) {
  const noop=()=>{},body=kind==='country-detail'?React.createElement(CountryArrivalDetail,{arrival:archive.arrivals.find(a=>a.country==='Singapore'),trips:[trip],onBack:noop,onOpenTrip:noop,width,year:'2025',onClearYear:noop}):kind==='activity'?React.createElement(native.View,{style:{padding:24}},React.createElement(ActivityChart,{years:[{year:2016,flights:4,miles:16000},{year:2020,flights:14,miles:38000},{year:2025,flights:31,miles:56000}],width:width-48,onYear:noop,latestDate:'2025-12-21'})):React.createElement(CollectionList,{kind:'airports',archive,onBack:noop,onSelectCountry:noop,onOpenTrip:noop,initialAirport:kind==='airport-detail'?'DFW':undefined,year:'2025',onClearYear:noop,backLabel:'Globe'});
  const name=kind+width;native.AppRegistry.registerComponent(name,()=>()=>React.createElement(native.View,{style:{width,height:900,backgroundColor:'#faf8f2'}},body));const app=native.AppRegistry.getApplication(name,{});
  const html='<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src data:; font-src data:; style-src \'unsafe-inline\'">'+server.renderToStaticMarkup(app.getStyleElement())+'<style>'+fontCss+'html,body{margin:0;background:#faf8f2}</style></head><body>'+server.renderToStaticMarkup(app.element)+'</body></html>';
  const page=await browser.newPage({viewport:{width,height:900},deviceScaleFactor:2});const requests=[];await page.route('**/*',r=>{requests.push(r.request().url());r.abort()});await page.setContent(html);await page.evaluate(()=>document.fonts.ready);await page.screenshot({path:path.join(out,`passport-experience-${kind}-${width}.png`)});
  assert.deepEqual(requests,[]);assert(await page.evaluate(()=>document.body.scrollWidth<=innerWidth),'Horizontal overflow');report.push({kind,width,requests:0});await page.close();
}}finally{await browser.close()}fs.writeFileSync(path.join(out,'passport-experience-layout-report.json'),JSON.stringify(report,null,2));console.log('Passport collection layout proof passed: 8 settled native-component fixtures, no network.');})().catch(e=>{console.error(e);process.exitCode=1});
