// Regression tests exercise production component hooks with a synthetic archive.
// Native painting and platform Back delivery are verified separately on device.
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), ts = require('typescript');
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
 const styles=ast.statements.find(n=>ts.isVariableStatement(n)&&n.declarationList.declarations.some(d=>d.name.getText(ast)==='styles'));
 assert(declaration);
 const styleText=file.endsWith('TrotterKit.tsx') ? 'const styles=StyleSheet.create({'+styles.declarationList.declarations[0].initializer.arguments[0].properties.filter(p=>/^(bottomNav|nav)/.test(p.name.getText(ast))).map(p=>p.getText(ast)).join(',')+'});' : styles?.getText(ast)||'';
 const compiled=ts.transpileModule(declaration.getText(ast)+'\n'+styleText,{compilerOptions:{jsx:ts.JsxEmit.React,module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
 const tags='View Text Pressable ScrollView RefreshControl BottomNav WWHeader WWButton WWIcon PassportBook ActivityChart CollectionButtons CollectionList CountryArrivalDetail CountryIndex CollectionHeading CollectionTitle CroppedPassportStamp TripRows'.split(' ');
 const globals={...Object.fromEntries(tags.map(tag=>[tag,tag])),React:host.React,StyleSheet:{create:x=>x,absoluteFillObject:{}},useSafeAreaInsets:()=>({top:24,bottom:20}),useWindowDimensions:()=>({width:320,height:800,fontScale:1}),getMobileVisualWidth:x=>x,colors:{},fonts:{},layout:{bottomNavHeight:73},useTravelTrips:()=>({trips:[trip],profile:{},status:'ready',refresh:noOp}),buildPassportArchive:()=>archive,buildPassportArrivals:()=>[arrival],tripsForCountry:()=>[trip],readableDate:x=>x,Platform:{OS:'android'},...overrides};
 const mod={exports:{}};new Function('module','exports',...Object.keys(globals),compiled)(mod,mod.exports,...Object.values(globals));host.setComponent(mod.exports[name]);return host;
}
function nodes(tree){if(Array.isArray(tree))return tree.flatMap(nodes);if(!tree||typeof tree!=='object')return [];return[tree,...nodes(tree.props?.children)];}
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
 find(tree,'WWButton').props.onPress();tree=host.render();assert(find(tree,'TripRows'));assert.equal(handler(),true);tree=host.render();assert(!find(tree,'TripRows'));assert.equal(backCalls,0,'Hardware Back from country trips returns to its stamp');
 find(tree,'CollectionTitle').props.onBack();assert.equal(backCalls,1,'Visible Back from stamp calls its parent');host.unmount();assert.equal(handler,null);
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
