// Actual ProfileScreen/TravelerCard projected through RN-web; native motion is
// not asserted here. Data and device-local preferences use explicit fixtures.
const fs=require('node:fs'),path=require('node:path'),Module=require('node:module'),assert=require('node:assert/strict');
const mobile=path.resolve(__dirname,'..'),from=Module.createRequire(path.join(mobile,'package.json'));
const ts=from('typescript'),React=from('react'),RN=from('react-native-web'),server=from('react-dom/server');
const out=path.resolve(mobile,'../artifacts/profile-proof-20260915');fs.mkdirSync(out,{recursive:true});
let width=420,fontScale=1,kind='set';
const noOp=()=>{},asyncNoOp=async()=>{};
const points={DFW:{code:'DFW',city:'Dallas–Fort Worth',lat:32.8968,lon:-97.038},LHR:{code:'LHR',city:'London',lat:51.47,lon:-.4543},SFO:{code:'SFO',city:'San Francisco',lat:37.6213,lon:-122.379},MEX:{code:'MEX',city:'Mexico City',lat:19.4361,lon:-99.0719}};
const segments=['LHR','SFO','MEX'].map((code,index)=>({id:`p${index}`,depAirport:'DFW',arrAirport:code,depPoint:points.DFW,arrPoint:points[code],depTime:`2025-04-0${index+1}T12:00:00Z`,arrTime:`2025-04-0${index+1}T20:00:00Z`,airline:'AA',flightNumber:'100',distanceMiles:1000}));
function ScaledText({style,...props}){const original=RN.StyleSheet.flatten(style)||{},scaled={},multiplier=props.allowFontScaling===false?1:Math.min(fontScale,props.maxFontSizeMultiplier||fontScale);if(original.fontSize)scaled.fontSize=original.fontSize*multiplier;if(original.lineHeight)scaled.lineHeight=original.lineHeight*multiplier;return React.createElement(RN.Text,{...props,style:[style,scaled]});}
const load=Module._load;Module._load=function(request,parent,isMain){
 if(request==='react-native')return {...RN,Text:ScaledText,useWindowDimensions:()=>({width,height:920,scale:1,fontScale})};
 if(request==='react-native-svg')return from('react-native-svg/lib/commonjs/elements.web');
 if(request==='react-native-safe-area-context')return {useSafeAreaInsets:()=>({top:28,bottom:22,left:0,right:0})};
 if(request.endsWith('/services/travelTrips'))return {getApiBaseUrl:()=> 'https://fixture.invalid',useTravelTrips:()=>({profile:{name:'Nathan Hennigh',flights:kind==='empty'?0:163,firstFlightDate:kind==='empty'?undefined:'2016-01-01'},trips:kind==='empty'?[]:[{segments}],status:'idle',accountId:'fixture',accountEmail:'nathanhennigh@gmail.com',gmailSyncStatus:kind==='empty'?'unknown':'synced',lastGmailSyncedAt:kind==='empty'?undefined:'2026-09-15T15:00:00Z',lastSyncedAt:'2026-09-15T15:01:00Z',refresh:asyncNoOp,syncFromGmail:asyncNoOp,signOut:asyncNoOp})};
 if(request.endsWith('/utils/travelerIdentity'))return {useTravelerIdentity:()=>({homeAirport:kind==='set'?'DFW':undefined,ready:kind!=='loading',setHomeAirport:asyncNoOp})};
 if(request.endsWith('/utils/experiencePreferences'))return {useExperiencePreferences:()=>({haptics:true,texture:'classic',setHaptics:noOp,setTexture:noOp}),selectionHaptic:noOp};
 if(request.endsWith('/stamps/PngStamp'))return {PngStamp:()=>null};
 return load.call(this,request,parent,isMain);
};
for(const ext of ['.tsx','.ts'])require.extensions[ext]=(module,file)=>module._compile(ts.transpileModule(fs.readFileSync(file,'utf8'),{fileName:file,compilerOptions:{jsx:ts.JsxEmit.ReactJSX,module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,esModuleInterop:true}}).outputText,file);
for(const ext of ['.png','.jpg'])require.extensions[ext]=(module,file)=>module.exports={uri:`data:image/${ext==='.jpg'?'jpeg':'png'};base64,${fs.readFileSync(file).toString('base64')}`};
const {ProfileScreen}=require(path.join(mobile,'src/screens/ProfileScreen.tsx'));
let fonts='';for(const name of fs.readdirSync(path.join(mobile,'assets/world-window/fonts')).filter(name=>name.endsWith('.ttf')))fonts+=`@font-face{font-family:'${name.slice(0,-4)}';src:url(data:font/ttf;base64,${fs.readFileSync(path.join(mobile,'assets/world-window/fonts',name)).toString('base64')})}`;
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||path.join(require('node:os').homedir(),'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'));
(async()=>{const browser=await chromium.launch({headless:true,channel:'chrome'}),cases=[];try{
 for(const w of [320,420])for(const scale of [1,2])for(const state of ['set','unset','empty','loading']){
  width=w;fontScale=scale;kind=state;const name=`${state}-${w}-font${scale}`;
  RN.AppRegistry.registerComponent(name,()=>()=>React.createElement(RN.View,{style:{width,minHeight:920}},React.createElement(ProfileScreen,{active:'profile',onChange:noOp,onOpenAirport:noOp})));
  const app=RN.AppRegistry.getApplication(name,{}),page=await browser.newPage({viewport:{width,height:920}}),record={name,width,fontScale,requests:[],errors:[]};
  page.on('pageerror',error=>record.errors.push(error.message));await page.route('**/*',route=>{record.requests.push(route.request().url());route.abort();});
  await page.setContent('<!doctype html><html><head><meta charset="utf-8">'+server.renderToStaticMarkup(app.getStyleElement())+'<style>'+fonts+'html,body{margin:0;background:#FAF8F2}</style></head><body>'+server.renderToStaticMarkup(app.element)+'</body></html>');
  await page.evaluate(()=>document.fonts.ready);
  record.layout=await page.evaluate(()=>{const overflow=[];for(const element of document.querySelectorAll('*')){if(element.namespaceURI.includes('svg')||![...element.childNodes].some(node=>node.nodeType===3&&node.textContent.trim()))continue;const box=element.getBoundingClientRect(),parent=element.parentElement?.getBoundingClientRect();if(box.left<-.5||box.right>innerWidth+.5||element.scrollWidth>element.clientWidth+1||(parent&&(box.left<parent.left-1||box.right>parent.right+1)))overflow.push({text:element.textContent,box:box.toJSON(),parent:parent?.toJSON(),scrollWidth:element.scrollWidth,clientWidth:element.clientWidth});}return {width:document.body.scrollWidth,overflow,text:document.body.textContent,card:document.querySelector('[data-testid="traveler-card"]')?.getBoundingClientRect().toJSON()};});
  assert(record.layout.text.includes('Nathan Hennigh'));
  if(state==='set')assert(record.layout.text.includes('DFW'));else assert(!record.layout.text.includes('DFW'),'No inferred home');
  if(state==='empty')assert(!record.layout.text.includes('First flight'));
  await page.screenshot({path:path.join(out,name+'.png'),fullPage:true});cases.push(record);await page.close();
 }
 }finally{await browser.close();fs.writeFileSync(path.join(out,'layout-proof.json'),JSON.stringify({scope:'Shipping ProfileScreen, TravelerCard, WorldWindowUI and BottomNav with bundled fonts; RN-web static projection at320/420 and1x/2x text. Explicit set/unset/empty/loading fixtures. No native motion or storage assertion.',cases},null,2));}
 const failures=cases.filter(record=>record.errors.length||record.requests.length||record.layout.overflow.length||record.layout.width>record.width);console.log(JSON.stringify({cases:cases.length,failures:failures.map(record=>({name:record.name,overflow:record.layout.overflow.map(item=>item.text),errors:record.errors,requests:record.requests.length}))},null,2));
 assert.equal(failures.length,0,'Profile overflow/runtime failure; inspect layout-proof.json');
})().catch(error=>{console.error(error);process.exitCode=1;});
