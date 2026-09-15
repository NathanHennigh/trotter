// Regression tests exercise production component hooks with a synthetic archive.
// Native painting and platform Back delivery are verified separately on device.
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), ts = require('typescript');
const modules = new Map();
function pure(file) {
  const absolute = path.resolve(__dirname, "..", file);
  if (modules.has(absolute)) return modules.get(absolute);
  // Carrier branding is outside navigation; all catalog/progress/filter logic remains production code.
  if (absolute.endsWith(path.join("world-window", "AirlineLogo.tsx"))) return { airlineName: code => code };
  if (absolute.endsWith(".json")) return JSON.parse(fs.readFileSync(absolute, "utf8"));
  const source = fs.readFileSync(absolute, "utf8");
  const code = ts.transpileModule(source, {compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,esModuleInterop:true}}).outputText;
  const mod = { exports: {} }; modules.set(absolute, mod.exports);
  const resolve = ref => {
    const base=path.resolve(path.dirname(absolute), ref);
    const found=[base,base+".ts",base+".tsx",base+".json"].find(p=>fs.existsSync(p)&&fs.statSync(p).isFile());
    if (!found) throw Error("Missing pure module: "+ref);
    return pure(path.relative(path.resolve(__dirname,".."),found));
  };
  new Function("require","module","exports",code)(resolve,mod,mod.exports);
  modules.set(absolute,mod.exports); return mod.exports;
}

function hookHost() {
  const slots = [];
  let cursor = 0, pending = [], dirty = false, component, props, tree;
  const same = (a, b) => a && b && a.length === b.length && a.every((v, i) => Object.is(v, b[i]));
  const React = {
    Fragment: "Fragment",
    createElement: (type, props, ...children) => ({ type, props: { ...props, children } }),
    useState(initial) {
      const i = cursor++;
      if (!slots[i]) slots[i] = { value: typeof initial === "function" ? initial() : initial };
      return [slots[i].value, value => {
        const next = typeof value === "function" ? value(slots[i].value) : value;
        if (!Object.is(next, slots[i].value)) { slots[i].value = next; dirty = true; }
      }];
    },
    useRef(value) {
      const i = cursor++;
      return (slots[i] ??= { current: value });
    },
    useMemo(make, deps) {
      const i = cursor++;
      if (!slots[i] || !same(slots[i].deps, deps)) slots[i] = { deps, value: make() };
      return slots[i].value;
    },
    useCallback(fn, deps) { return React.useMemo(() => fn, deps); },
    useEffect(fn, deps) {
      const i = cursor++;
      if (!slots[i] || !same(slots[i].deps, deps)) {
        pending.push(() => { slots[i]?.cleanup?.(); slots[i] = { deps, cleanup: fn() }; });
      }
    },
  };
  return {
    React,
    setComponent(fn) { component = fn; },
    render(nextProps = props) {
      props = nextProps;
      for (let i = 0; i < 10; i++) {
        cursor = 0; pending = []; dirty = false;
        tree = component(props);
        pending.forEach(fn => fn());
        if (!dirty) return tree;
      }
      throw Error("Component did not settle after effects");
    },
    unmount() { slots.forEach(slot => slot?.cleanup?.()); },
  };
}

const noOp=()=>{}, arrival={country:'Singapore',travelCountryKey:'SG',airportCode:'SIN',firstVisitDate:'2024-05-03'}, trip={id:'one',country:'Singapore',city:'Singapore',title:'Singapore',segments:[]};
const archive={arrivals:[arrival],airports:[],airlines:[],years:[],records:[]};
function load(file,name,overrides={}){
 const host=hookHost(),source=fs.readFileSync(path.resolve(__dirname,'../',file),'utf8');
 const ast=ts.createSourceFile(file,source,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
 const declaration=ast.statements.find(n=>ts.isFunctionDeclaration(n)&&n.name?.text===name);
 const styles=ast.statements.find(n=>ts.isVariableStatement(n)&&n.declarationList.declarations.some(d=>['styles','s'].includes(d.name.getText(ast))));
 assert(declaration);
 const styleText=file.endsWith('TrotterKit.tsx') ? 'const styles=StyleSheet.create({'+styles.declarationList.declarations[0].initializer.arguments[0].properties.filter(p=>/^(bottomNav|nav)/.test(p.name.getText(ast))).map(p=>p.getText(ast)).join(',')+'});' : styles?.getText(ast)||'';
 const compiled=ts.transpileModule(declaration.getText(ast)+'\n'+styleText,{compilerOptions:{jsx:ts.JsxEmit.React,module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
 const tags='FlatList TransportCollectionIndex AirportLuggageLabel View Text Pressable PressFeedback PaperReveal ScrollView RefreshControl BottomNav WWHeader WWButton WWIcon PassportBook ActivityChart CollectionButtons CollectionList CollectionScope CollectionBack CountryArrivalDetail CountryIndex CollectionHeading CollectionTitle CroppedPassportStamp TripRows AirportRouteFan AirlineLogo'.split(' ');
 const globals={...Object.fromEntries(tags.map(tag=>[tag,tag])),React:host.React,useState:host.React.useState,...pure('src/data/collections/catalogs.ts'),...pure('src/components/world-window/collections/catalogProgress.ts'),...pure('src/components/world-window/collections/transportCollectionModel.ts'),StyleSheet:{create:x=>x,absoluteFillObject:{}},useSafeAreaInsets:()=>({top:24,bottom:20}),useWindowDimensions:()=>({width:320,height:800,fontScale:1}),getMobileVisualWidth:x=>x,colors:{},fonts:{},layout:{bottomNavHeight:73},useTravelTrips:()=>({trips:[trip],profile:{},status:'idle',refresh:noOp}),buildPassportArchive:()=>archive,scopedPassportArchive:()=>archive,buildPassportArrivals:()=>[arrival],passportScope:()=>({trips:[trip],arrivals:[arrival],lifetimeArrivals:[arrival]}),scopeTripsToYear:t=>t,normalizeTravelYear:y=>/^\d{4}$/.test(y||'')?y:undefined,earnedCountries:()=>[],tripsForCountry:()=>[trip],readableDate:x=>x,airlineName:x=>x,Platform:{OS:'android'},...overrides};
 const mod={exports:{}};new Function('module','exports',...Object.keys(globals),compiled)(mod,mod.exports,...Object.values(globals));host.setComponent(mod.exports[name]);return host;
}
function nodes(tree){if(Array.isArray(tree))return tree.flatMap(nodes);if(!tree||typeof tree!=='object')return [];return[tree,...nodes(tree.props?.children),...nodes(tree.props?.header),...nodes(tree.props?.ListHeaderComponent),...nodes(tree.props?.ListEmptyComponent)];}
const find=(tree,type)=>nodes(tree).find(n=>n.type===type);
{
 const host=load('src/screens/CountryStampCollectionScreen.tsx','CountryStampCollectionScreen');let handler=null,closed=0;
 const props={active:'passport',onChange:noOp,onBack:()=>closed++,onBackHandlerChange:value=>handler=value};
 let tree=host.render(props);find(tree,'CountryIndex').props.onSelect(arrival);tree=host.render();
 assert(find(tree,'CountryIndex'),'Country list remains mounted behind its detail to preserve scroll');
 const detail=find(tree,'CountryArrivalDetail');assert.equal(detail.props.backLabel,'Countries');
 let nested=true;detail.props.onBackHandlerChange(()=>{if(!nested)return false;nested=false;return true;});
 assert.equal(handler(),true,'Nested trips back is consumed before leaving the country');tree=host.render();assert(find(tree,'CountryArrivalDetail'));assert.equal(closed,0);
 assert.equal(handler(),true,'Next Back returns the country index');tree=host.render();assert(!find(tree,'CountryArrivalDetail'));assert.equal(handler(),false,'Index delegates Back to its screen origin');
 tree=host.render({...props,initialCountry:'SG',backLabel:'Globe'});assert.equal(find(tree,'CountryArrivalDetail').props.backLabel,'Globe');
 tree=host.render({...props,initialCountry:'SG',backLabel:'Globe',visible:false});assert.equal(handler,null,'Inactive collection cannot intercept Back');
 tree=host.render({...props,initialCountry:'SG',backLabel:'Globe',visible:true});assert(find(tree,'CountryArrivalDetail'),'Returning from trip retains direct-country detail');assert.equal(handler(),false,'Direct-country Back delegates to the real Globe origin');
 host.unmount();assert.equal(handler,null);
}
{
 const host=load('src/components/world-window/passport/PassportCollections.tsx','CountryArrivalDetail');let handler=null,backCalls=0;
 let tree=host.render({arrival,trips:[trip],width:320,onBack:()=>backCalls++,onOpenTrip:noOp,onBackHandlerChange:value=>handler=value});
 assert(find(tree,'TripRows'),'Country journeys are inline beneath the stamp'); assert(!find(tree,'WWButton'),'There is no extra View trips mode'); assert.equal(handler(),false,'Country detail delegates Back directly to its origin');assert.equal(backCalls,0);
 find(tree,'CollectionTitle').props.onBack();assert.equal(backCalls,1,'Visible Back from stamp calls its parent');host.unmount();assert.equal(handler,null);
}
{
 const airport={code:'DFW',city:'Dallas',flights:2,trips:[trip]},a={...archive,airports:[airport]};
 const host=load('src/components/world-window/passport/PassportCollections.tsx','CollectionList'); let handler;
 let tree=host.render({kind:'airports',archive:a,onBack:noOp,onSelectCountry:noOp,onOpenTrip:noOp,onBackHandlerChange:h=>handler=h});
 find(tree,'CollectionHeading').props.setQuery('DFW');tree=host.render();
 const index=load('src/components/world-window/collections/TransportCollectionIndex.tsx','TransportCollectionIndex');
 const indexTree=index.render(find(tree,'TransportCollectionIndex').props),airportList=find(indexTree,'FlatList');
 assert.deepEqual(airportList.props.data.map(entry=>entry.key),['DFW'],'Query filters the actual transport index');
 find(airportList.props.renderItem({item:airportList.props.data[0]}),'PressFeedback').props.onPress(); tree=host.render();
 assert(find(tree,'CollectionHeading'),'Index stays mounted behind the airport detail');assert(find(tree,'AirportRouteFan'));
 assert(nodes(tree).some(n=>n.type==='View'&&n.props.importantForAccessibility==='no-hide-descendants'),'Hidden index is excluded from accessibility');
 assert.equal(handler(),true);tree=host.render();assert.equal(find(tree,'CollectionHeading').props.query,'DFW');assert(!find(tree,'AirportRouteFan'));
 tree=host.render({kind:'airports',archive:a,onBack:noOp,onSelectCountry:noOp,initialAirport:'DFW',scopeEpoch:1,backLabel:'Profile',onBackHandlerChange:h=>handler=h});assert(find(tree,'AirportRouteFan'),'Profile can open its actual airport directly');assert.equal(find(tree,'CollectionTitle').props.backLabel,'Profile');assert.equal(handler(),false,'Direct airport delegates Back to its actual Profile origin');index.unmount();host.unmount();
}
for (const kind of ['airports', 'airlines']) {
 const code=kind==='airports'?'DFW':'UA', first='2024-05-03T10:00:00Z';
 const historicalTrip={...trip,segments:[{id:'historic',depAirport:'DFW',arrAirport:'SIN',depTime:first,arrTime:'2024-05-04T10:00:00Z',airline:'UA'}]};
 const record=kind==='airports'?{code,city:'Dallas',country:'United States',flights:1,trips:[historicalTrip]}:{code,flights:1,miles:100,trips:[historicalTrip]};
 const lifetime={...archive,[kind]:[record]}, scoped={...archive,airports:[],airlines:[]};
 const host=load('src/components/world-window/passport/PassportCollections.tsx','CollectionList'),index=load('src/components/world-window/collections/TransportCollectionIndex.tsx','TransportCollectionIndex');
 let handler,clears=0;
 const props={kind,archive:scoped,lifetimeArchive:lifetime,year:'2026',onBack:noOp,onSelectCountry:noOp,onClearYear:()=>clears++,onBackHandlerChange:h=>handler=h};
 let tree=host.render(props);find(tree,'CollectionHeading').props.setQuery(code);tree=host.render();
 const item=find(tree,'TransportCollectionIndex').props.entries.find(entry=>entry.key===code);
 assert.equal(item.record,undefined,'Lifetime travel must not be counted as a flight in the selected year');assert.strictEqual(item.lifetimeRecord,record);assert.equal(item.firstVisit,first);
 let indexTree=index.render(find(tree,'TransportCollectionIndex').props);
 assert.equal(find(indexTree,'FlatList').props.data.length,0,'Visited/Flown excludes an entry without selected-year flights');
 const allTab=nodes(indexTree).find(node=>node.type==='PressFeedback'&&node.props.accessibilityRole==='tab'&&nodes(node).some(text=>text.type==='Text'&&text.props.children.includes('All')));
 allTab.props.onPress();indexTree=index.render();
 const rows=find(indexTree,'FlatList');assert(rows.props.data.some(entry=>entry.key===code),'All includes lifetime-only entries');
 find(rows.props.renderItem({item:rows.props.data.find(entry=>entry.key===code)}),'PressFeedback').props.onPress();tree=host.render();
 assert(find(tree,'CollectionTitle'));assert(!find(tree,'AirportRouteFan'));assert(!find(tree,'TripRows'),'No historical trips leak into a year-filtered detail');
 const labels=nodes(tree).filter(node=>node.type==='Text').flatMap(node=>node.props.children).filter(value=>typeof value==='string');
 assert(labels.some(value=>value.includes('No recorded flights')&&value.includes('2026')),'Detail explains that this year has no flights');
 if(kind==='airports')assert(labels.includes(first),'Lifetime first visit remains available in a year-filtered airport detail');
 assert.equal(handler(),true);tree=host.render();assert.equal(find(tree,'CollectionHeading').props.query,code,'Back keeps the transport search');
 indexTree=index.render(find(tree,'TransportCollectionIndex').props);assert(find(indexTree,'FlatList').props.data.some(entry=>entry.key===code),'Retained index stays on All after closing detail');
 find(tree,'CollectionScope').props.onClear();assert.equal(clears,1);
 tree=host.render({...props,archive:lifetime,year:undefined});assert.strictEqual(find(tree,'TransportCollectionIndex').props.entries.find(entry=>entry.key===code).record,record,'All years restores the real lifetime record');
 index.unmount();host.unmount();
}
{
 const host=load('src/screens/PassportStatsScreen.tsx','PassportStatsScreen');let cleared=0;
 let tree=host.render({active:'passport',onChange:noOp,initialYear:'2025',scopeEpoch:1,onClearYear:()=>cleared++});
 assert.equal(find(tree,'CollectionScope').props.year,'2025');find(tree,'CollectionScope').props.onClear();tree=host.render();assert.equal(find(tree,'CollectionScope').props.year,undefined);assert.equal(cleared,1);
 tree=host.render({active:'passport',onChange:noOp,initialYear:'2024',scopeEpoch:2});assert.equal(find(tree,'CollectionScope').props.year,'2024');host.unmount();
}
{
 const host=load('src/screens/PassportStatsScreen.tsx','PassportStatsScreen');let handler=null,opened=null,tab=null;
 const props={active:'passport',onChange:value=>tab=value,onOpenTrip:value=>opened=value,onBackHandlerChange:value=>handler=value};
 let tree=host.render(props);find(tree,'CollectionButtons').props.onOpen('airports');tree=host.render();const list=find(tree,'CollectionList');
 assert.equal(nodes(tree).filter(n=>n.type==='BottomNav').length,1,'Collection pages share the single parent bottom navigation');
 list.props.onOpenTrip(trip);tree=host.render();assert.equal(opened,trip);assert(find(tree,'CollectionList'),'Opening a trip preserves collection state for return');
 tree=host.render({...props,visible:false});assert.equal(handler,null);tree=host.render({...props,visible:true});
 let airportDetail=true;find(tree,'CollectionList').props.onBackHandlerChange(()=>{if(!airportDetail)return false;airportDetail=false;return true;});
 assert.equal(handler(),true);tree=host.render();assert(find(tree,'CollectionList'),'First Back returns from airport detail to airport index');
 find(tree,'CollectionList').props.onSelectCountry(arrival);tree=host.render();assert(find(tree,'CollectionList'),'Country overlay retains its underlying collection');assert(find(tree,'CountryArrivalDetail'));
 assert.equal(handler(),true);tree=host.render();assert(!find(tree,'CountryArrivalDetail'));assert(find(tree,'CollectionList'));
 assert.equal(handler(),true);tree=host.render();assert(!find(tree,'CollectionList'));assert.equal(handler(),false,'Back at the book delegates to App');
 find(tree,'CollectionButtons').props.onOpen('airlines');tree=host.render();find(tree,'BottomNav').props.onChange('dreams');tree=host.render();assert.equal(tab,'dreams');assert(!find(tree,'CollectionList'),'Explicit tab navigation clears passport overlay');host.unmount();assert.equal(handler,null);
}
for(const width of [320,420])for(const fontScale of [1,2]){
 const host=load('src/components/trotter/TrotterKit.tsx','BottomNav',{useWindowDimensions:()=>({width,height:800,fontScale})});
 const tree=host.render({active:'passport',onChange:noOp});
 const tabs=nodes(tree).filter(n=>n.type==='Pressable');assert.deepEqual(tabs.map(n=>n.props.accessibilityLabel),['Globe','Trips','Passport','Dreams','Profile']);
 for(const tab of tabs){const label=find(tab,'Text');assert.notEqual(label.props.allowFontScaling,false,'Persistent navigation enables bounded scaling');assert.equal(label.props.maxFontSizeMultiplier,1.25);assert.equal(label.props.children[0],tab.props.accessibilityLabel,'No visible tab labels are abbreviated');assert(tab.props.style[0].minHeight>=44);assert(tab.props.style[1].width>=44);}
 host.unmount();
}
console.log('Passport navigation passed: nested Back order, direct-country origins, inactive registration, preserved trip-return layers, and single bottom navigation.');
