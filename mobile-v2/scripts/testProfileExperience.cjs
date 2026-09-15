const assert = require('node:assert/strict'), { test } = require('node:test');
const fs = require('node:fs'), path = require('node:path'), ts = require('typescript');
const root = path.resolve(__dirname, '../src'), noop = () => {};
const flush = async () => { for (let i = 0; i < 20; i++) await Promise.resolve(); };
function runtime(file, overrides = {}) {
  const slots = []; let cursor = 0, effects = [], args;
  const same = (a,b) => a && b && a.length === b.length && a.every((v,i) => v === b[i]);
  const react = {
    createElement: (type, props, ...children) => ({ type, props: { ...props, children } }),
    useState(initial) { const i=cursor++; if (!(i in slots)) slots[i]=typeof initial==='function'?initial():initial; return [slots[i], value => { slots[i]=typeof value==='function'?value(slots[i]):value; }]; },
    useRef(initial) { const i=cursor++; return slots[i]??=( {current:initial} ); },
    useMemo(fn,deps) { const i=cursor++; if (!slots[i] || !same(slots[i].deps,deps)) slots[i]={deps,value:fn()}; return slots[i].value; },
    useEffect(fn,deps) { const i=cursor++; if (!slots[i] || !same(slots[i].deps,deps)) { slots[i]?.cleanup?.(); slots[i]={deps}; effects.push(()=>{slots[i].cleanup=fn();}); } },
  };
  const tags='ActivityIndicator Image RefreshControl ScrollView Switch Text View'.split(' ');
  const defaults={
    react, 'react-native':{...Object.fromEntries(tags.map(v=>[v,v])),StyleSheet:{create:v=>v},useWindowDimensions:()=>({width:420,fontScale:1})},
    'react-native-safe-area-context':{useSafeAreaInsets:()=>({top:24,bottom:20})},
    '../components/trotter/TrotterKit':{BottomNav:'BottomNav'}, '../components/world-window/WorldWindowUI':{WWHeader:'WWHeader',WWIcon:'WWIcon'},
    '../components/world-window/motion':{PressFeedback:'Pressable'}, '../components/world-window/profile/TravelerCard':{TravelerCard:'TravelerCard'},
    '../components/world-window/profile/HomeAirportPicker':{HomeAirportPicker:'HomeAirportPicker'},
    '../theme/trotterTheme':{colors:{},fonts:{},layout:{bottomNavHeight:73}},
    '../utils/mobileLayout':{getMobileVisualWidth:width=>width},
    '../utils/experiencePreferences':{useExperiencePreferences:()=>({texture:'classic',haptics:true,setTexture:noop,setHaptics:noop}),selectionHaptic:noop},
    '../utils/travelerIdentity':{useTravelerIdentity:()=>({ready:true,setHomeAirport:async()=>{}})},
    '../services/travelTrips':{getApiBaseUrl:()=> 'https://synthetic.example',useTravelTrips:()=>({profile:{name:'Alex Morgan',firstFlightDate:'2016-01-01'},trips:[],accountId:1,accountEmail:'alex@example.test',status:'idle',gmailSyncStatus:'unknown',refresh:noop,syncFromGmail:noop,signOut:noop})},
  };
  const absolute=path.join(root,file), mod={exports:{}};
  const code=ts.transpileModule(fs.readFileSync(absolute,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.React,target:ts.ScriptTarget.ES2022,esModuleInterop:true}}).outputText;
  new Function('require','module','exports',code)(ref=>{
    if (ref in overrides) return overrides[ref]; if (ref in defaults) return defaults[ref];
    if (/\.json$/.test(ref)) return require(path.resolve(path.dirname(absolute),ref)); if (/\.jpg$/.test(ref)) return ref;
    throw Error('Unmocked '+ref);
  },mod,mod.exports);
  return { exports:mod.exports, render(fn,...next) { if(next.length) args=next; cursor=0;effects=[];const tree=fn(...(args||[]));effects.forEach(run=>run());return tree; }, dispose(){slots.forEach(slot=>slot?.cleanup?.());} };
}
function nodes(tree){return Array.isArray(tree)?tree.flatMap(nodes):tree&&typeof tree==='object'?[tree,...nodes(tree.props?.children)]:[];}
const find=(tree,type)=>nodes(tree).find(n=>n.type===type);
const button=(tree,label)=>nodes(tree).find(n=>n.props?.accessibilityLabel===label);
function text(tree){return Array.isArray(tree)?tree.map(text).join(' '):tree&&typeof tree==='object'?text(tree.props?.children):typeof tree==='string'?tree:'';}

test('Profile replaces repeated archive blocks with identity and meaningful account controls',()=>{
  const host=runtime('screens/ProfileScreen.tsx'), tree=host.render(host.exports.ProfileScreen,{active:'profile',onChange:noop});
  assert(find(tree,'TravelerCard'));assert(find(tree,'WWHeader'));assert(button(tree,'Scan Gmail for flights'));
  for(const duplicate of ['Trip archive','Country stamps','Latest recorded flight','Most visited airport','Refresh archive','Not checked']) assert(!text(tree).includes(duplicate),duplicate);
  assert(text(tree).includes('Ready to scan for flights'));assert(text(tree).includes('alex@example.test'));host.dispose();
});
test('Globe and haptic preferences control the same store used by Home',()=>{
  const changed=[],haptics=[];const host=runtime('screens/ProfileScreen.tsx',{'../utils/experiencePreferences':{useExperiencePreferences:()=>({texture:'nasa',haptics:false,setTexture:v=>changed.push(v),setHaptics:v=>haptics.push(v)}),selectionHaptic:noop}});
  const tree=host.render(host.exports.ProfileScreen,{active:'profile',onChange:noop});
  assert.equal(button(tree,'NASA globe').props.accessibilityState.selected,true);button(tree,'Classic globe').props.onPress();assert.deepEqual(changed,['classic']);
  find(tree,'Switch').props.onValueChange(true);assert.deepEqual(haptics,[true]);host.dispose();
});
test('Personal route graphic excludes future/invalid flights and does not infer a home',()=>{
  const past={id:'one',depTime:'2020-02-02'},future={id:'future',depTime:'2099-02-02'},invalid={id:'invalid',depTime:'bad'};
  const host=runtime('screens/ProfileScreen.tsx',{'../services/travelTrips':{getApiBaseUrl:()=> 'https://synthetic.example',useTravelTrips:()=>({profile:{name:'Alex'},trips:[{segments:[past,future,invalid,past]}],accountId:1,status:'idle'})}});
  const tree=host.render(host.exports.ProfileScreen,{active:'profile',onChange:noop}),card=find(tree,'TravelerCard');
  assert.deepEqual(card.props.segments,[past]);assert.equal(card.props.homeAirport,undefined);host.dispose();
});
test('Home airport opens a purposeful editor, saves explicit choice, and closes',async()=>{
  const saved=[];let owner;
  const host=runtime('screens/ProfileScreen.tsx',{'../utils/travelerIdentity':{useTravelerIdentity:value=>{owner=value;return{ready:true,setHomeAirport:async code=>saved.push(code)};}}});
  let tree=host.render(host.exports.ProfileScreen,{active:'profile',onChange:noop});find(tree,'TravelerCard').props.onChooseHome();tree=host.render(host.exports.ProfileScreen);
  const picker=find(tree,'HomeAirportPicker');assert(picker);await picker.props.onSave('IAH');picker.props.onClose();tree=host.render(host.exports.ProfileScreen);
  assert.deepEqual(saved,['IAH']);assert.equal(find(tree,'HomeAirportPicker'),undefined);assert.equal(owner,'https://synthetic.example/1');host.dispose();
});
test('Scanning shows progress and disables repeated scans while leaving navigation available',()=>{
  const host=runtime('screens/ProfileScreen.tsx',{'../services/travelTrips':{getApiBaseUrl:()=> 'https://synthetic.example',useTravelTrips:()=>({profile:{name:'Alex'},trips:[],accountId:1,status:'syncing',gmailSyncStatus:'syncing'})}});
  const tree=host.render(host.exports.ProfileScreen,{active:'profile',onChange:noop});assert.equal(button(tree,'Scan Gmail for flights').props.disabled,true);
  assert(text(tree).includes('Your scan continues'));assert(find(tree,'BottomNav'));host.dispose();
});
test('Home airport persistence is isolated by account and server and rejects invalid input',async()=>{
  const storage=new Map(), host=runtime('utils/travelerIdentity.ts',{'@react-native-async-storage/async-storage':{getItem:async key=>storage.get(key),setItem:async(key,value)=>storage.set(key,value)}}),api=host.exports;
  await api.writeHomeAirport('prod/1','IAH');await api.writeHomeAirport('prod/2','LHR');await api.writeHomeAirport('dev/1','ACT');
  assert.equal(await api.readHomeAirport('prod/1'),'IAH');assert.equal(await api.readHomeAirport('prod/2'),'LHR');assert.equal(await api.readHomeAirport('dev/1'),'ACT');
  await assert.rejects(api.writeHomeAirport('prod/1','bad input'));assert.equal(await api.readHomeAirport('prod/1'),'IAH');await api.writeHomeAirport('prod/1');assert.equal(await api.readHomeAirport('prod/1'),undefined);
});
test('Account switches discard stale home-airport reads and never display a previous owner choice',async()=>{
  const pending=new Map(), host=runtime('utils/travelerIdentity.ts',{'@react-native-async-storage/async-storage':{getItem:key=>new Promise(resolve=>pending.set(key,resolve)),setItem:async()=>{}}});
  let identity=host.render(host.exports.useTravelerIdentity,'owner-a');await flush();identity=host.render(host.exports.useTravelerIdentity,'owner-b');await flush();assert.equal(identity.homeAirport,undefined);assert.equal(identity.ready,false);
  pending.get('trotter.traveler-identity.v1.owner-b')(JSON.stringify({homeAirport:'ACT'}));await flush();identity=host.render(host.exports.useTravelerIdentity);assert.equal(identity.homeAirport,'ACT');
  pending.get('trotter.traveler-identity.v1.owner-a')(JSON.stringify({homeAirport:'IAH'}));await flush();identity=host.render(host.exports.useTravelerIdentity);assert.equal(identity.homeAirport,'ACT');host.dispose();
});
