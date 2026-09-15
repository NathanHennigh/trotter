// Production filtering and hook/navigation behavior; synthetic data only.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),ts=require('typescript');
const mobile=path.resolve(__dirname,'..'),noop=()=>{};
for(const ext of ['.ts','.tsx'])require.extensions[ext]=(m,file)=>m._compile(ts.transpileModule(fs.readFileSync(file,'utf8'),{fileName:file,compilerOptions:{jsx:ts.JsxEmit.React,module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,esModuleInterop:true}}).outputText,file);
const {countryCatalog}=require('../src/data/collections/catalogs.ts');
const progress=require('../src/components/world-window/collections/catalogProgress.ts');
// Reuse the small existing React hook host, without running unrelated suites.
const hostSource=fs.readFileSync(path.join(__dirname,'testPassportNavigation.cjs'),'utf8');
const hostAst=ts.createSourceFile('host.cjs',hostSource,ts.ScriptTarget.Latest,true);
const hookHost=new Function('return ('+hostAst.statements.find(n=>ts.isFunctionDeclaration(n)&&n.name.text==='hookHost').getText(hostAst)+')')();
const styles={create:x=>x,absoluteFillObject:{}},tags=Object.fromEntries('View ScrollView Text TextInput PressFeedback WWIcon CroppedPassportStamp RefreshControl BottomNav CountryIndex CountryArrivalDetail UnvisitedCountryRecord'.split(' ').map(n=>[n,n]));
let width=320,fontScale=1;
const modules={
 'react-native':{...tags,StyleSheet:styles,useWindowDimensions:()=>({width,height:900,fontScale})},
 '../motion':{PressFeedback:'PressFeedback'},'../WorldWindowUI':{WWIcon:'WWIcon'},'./PassportStamp':{CroppedPassportStamp:'CroppedPassportStamp'},
 './passport-model':{readableDate:x=>x},'../../../theme/trotterTheme':{colors:{},fonts:{}},
 '../../../data/collections/catalogs':{countryCatalog},'../collections/catalogProgress':progress,
 '../collections/CollectionIndexHeader':{CollectionIndexHeader:'CollectionIndexHeader',CollectionProgress:'CollectionProgress'},
};
function loadIndex(){const host=hookHost(),file=path.join(mobile,'src/components/world-window/passport/CountryCollectionIndex.tsx'),mod={exports:{}};
 const compiled=ts.transpileModule(fs.readFileSync(file,'utf8'),{compilerOptions:{jsx:ts.JsxEmit.React,module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,esModuleInterop:true}}).outputText;
 new Function('require','module','exports',compiled)(name=>name==='react'?host.React:modules[name]??assert.fail('Unhandled dependency '+name),mod,mod.exports);
 host.setComponent(mod.exports.CountryCollectionIndex);return {host,...mod.exports};
}
const arrival=(country,key,airport,date)=>({country,travelCountryKey:key,airportCode:airport,firstVisitDate:date,airportCount:1,tripCount:2,stamp:{country,date,airportCode:airport,shape:'shieldBadgeRounded',color:'#52745A'}});
const singapore=arrival('Singapore','SG','SIN','2024-06-22'),japan=arrival('Japan','JP','NRT','2020-05-01'),uae=arrival('United Arab Emirates','AE','DXB','2022-01-17'),somaliland=arrival('Somaliland','X-SOMALILAND','HGA','2019-09-13'),tunisia=arrival('Tunisia','TN','TUN','2021-06-21'),unknown=arrival('Imported historic territory','PRIVATE-OLD','OLD','2018-01-01');
const lifetime=[singapore,japan,uae,somaliland,tunisia,unknown];
function nodes(tree){if(Array.isArray(tree))return tree.flatMap(nodes);if(!tree||typeof tree!=='object')return [];return [tree,...nodes(tree.props?.children)];}
function copy(tree){if(Array.isArray(tree))return tree.map(copy).join('');return tree&&typeof tree==='object'?copy(tree.props?.children):tree??'';}
const find=(tree,type)=>nodes(tree).find(n=>n.type===type),button=(tree,label)=>nodes(tree).find(n=>n.type==='PressFeedback'&&(n.props.accessibilityLabel===label||copy(n)===label));
const flattenStyle=style=>Object.assign({},...(Array.isArray(style)?style:[style]).filter(Boolean));
{
 const {countryCollectionRows:rows,countryCollectionGroups:groups}=loadIndex();
 const all=rows(lifetime,lifetime);assert.equal(all.length,countryCatalog.entries.length+1);
 assert.equal(all.find(r=>r.entry.key==='SG').arrival,singapore,'First-entry object is passed through, never reconstructed from catalogue');
 const laterAlias={...singapore,travelCountryKey:'Singapore',firstVisitDate:'2025-02-01'};
 assert.equal(rows([singapore,laterAlias],[singapore,laterAlias]).find(r=>r.entry.key==='SG').arrival,singapore,'Legacy aliases keep the original first-entry stamp');
 assert.equal(all.find(r=>r.entry.key==='X-SOMALILAND').arrival,somaliland,'Somaliland remains distinct');
 assert.equal(all.find(r=>r.entry.key==='SO').arrival,undefined,'Somaliland does not earn Somalia');
 assert.equal(all.find(r=>r.entry.key==='PRIVATE-OLD').arrival,unknown,'Out-of-catalogue arrivals are retained');
 assert.deepEqual(groups(all,'visited','','Africa')[0].earned.map(r=>r.arrival),[somaliland,tunisia],'Regional first entries are chronological regardless source order');
 assert.deepEqual(groups(all,'visited','dxB','All regions').flatMap(g=>g.earned).map(r=>r.arrival),[uae],'Connections can be searched by their actual entry airport');
 assert.equal(groups(all,'all','Réunion','All regions').flatMap(g=>g.remaining)[0].entry.key,'RE','Accent-insensitive country search');
 assert.equal(groups(all,'all','somaliland','Africa')[0].earned[0].arrival,somaliland);
 assert.equal(groups(all,'visited','no-such-country','All regions').length,0);
 const scoped=rows([singapore],lifetime),remaining=groups(scoped,'all','united arab','Asia')[0].remaining[0];
 assert.equal(remaining.arrival,undefined);assert.equal(remaining.lifetimeArrival,uae,'Year filtering retains the real lifetime arrival instead of labelling it unvisited');
 assert.equal(groups(scoped,'visited','united arab','Asia').length,0);
 assert.equal(progress.collectionProgress(countryCatalog,lifetime.map(a=>a.travelCountryKey)).collected,5);
}
{
 const {host}=loadIndex();let selected=null,unvisited=null,query='';
 const props={arrivals:[singapore],lifetimeArrivals:lifetime,width,onBack:noop,backLabel:'Passport',year:'2024',onClearYear:noop,query,setQuery:q=>query=q,onSelect:a=>selected=a,onSelectUnvisited:a=>unvisited=a};
 let tree=host.render(props);assert.equal(nodes(tree).filter(n=>n.type==='CroppedPassportStamp').length,1);
 button(tree,'All countries').props.onPress();tree=host.render({...props,query:'United Arab'});
 assert.equal(nodes(tree).filter(n=>n.type==='CroppedPassportStamp').length,0,'All-country directory never creates fake earned stamps');
 button(tree,'United Arab Emirates, visited in another year').props.onPress();assert.equal(selected,uae,'Existing out-of-year visit opens its real detail');
 tree=host.render({...props,query:'Guinea-Bissau'});button(tree,'Guinea-Bissau, not yet visited').props.onPress();assert.equal(unvisited.key,'GW');
 tree=host.render({...props,query:'does not exist'});button(tree,'Browse all countries').props.onPress();assert.equal(query,'');
 host.unmount();
}
for(const w of [320,410])for(const scale of [1,2]){
 width=w;fontScale=scale;const {host}=loadIndex();const tree=host.render({arrivals:lifetime,lifetimeArrivals:lifetime,query:'',setQuery:noop,width,onBack:noop,backLabel:'Passport',onSelect:noop,onSelectUnvisited:noop,onClearYear:noop});
 const stampCards=nodes(tree).filter(n=>n.type==='PressFeedback'&&find(n,'CroppedPassportStamp'));
 assert(stampCards.every(c=>flattenStyle(c.props.style).width===(scale>=1.35?w-40:(w-58)/2)),'Large text switches earned stamps to one full-width column');
 assert(stampCards.every(c=>find(c,'CroppedPassportStamp').props.width<flattenStyle(c.props.style).width),'Stamp impression fits inside its column');host.unmount();
}
{
 // Exercise the actual screen callback/Back hooks with the index/detail child
 // boundaries stubbed; native painting is covered by the separate layout proof.
 const host=hookHost(),file=path.join(mobile,'src/screens/CountryStampCollectionScreen.tsx'),source=fs.readFileSync(file,'utf8'),ast=ts.createSourceFile(file,source,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
 const declarations=ast.statements.filter(n=>ts.isFunctionDeclaration(n)&&n.name?.text==='CountryStampCollectionScreen'||ts.isVariableStatement(n)&&n.declarationList.declarations.some(d=>d.name.getText(ast)==='styles'));
 const compiled=ts.transpileModule(declarations.map(d=>d.getText(ast)).join('\n'),{compilerOptions:{jsx:ts.JsxEmit.React,module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
 const trip={id:'actual-trip'},globals={...tags,React:host.React,StyleSheet:styles,colors:{},layout:{bottomNavHeight:73},useSafeAreaInsets:()=>({top:24,bottom:20}),useWindowDimensions:()=>({width:320,fontScale:1}),getMobileVisualWidth:x=>x,useTravelTrips:()=>({trips:[trip],status:'idle',refresh:noop}),normalizeTravelYear:x=>x,passportScope:()=>({arrivals:[singapore],lifetimeArrivals:lifetime,trips:[trip]})};
 const mod={exports:{}};new Function('module','exports',...Object.keys(globals),compiled)(mod,mod.exports,...Object.values(globals));host.setComponent(mod.exports.CountryStampCollectionScreen);
 let handler,closed=0;const props={active:'passport',onChange:noop,onBack:()=>closed++,onBackHandlerChange:h=>handler=h};
 let tree=host.render(props);find(tree,'CountryIndex').props.setQuery('Guinea');tree=host.render();find(tree,'CountryIndex').props.onSelectUnvisited({key:'GW',name:'Guinea-Bissau',region:'Africa'});tree=host.render();
 assert(find(tree,'CountryIndex'),'Directory remains mounted behind detail');assert(find(tree,'UnvisitedCountryRecord'));
 assert(nodes(tree).some(n=>n.props.importantForAccessibility==='no-hide-descendants'),'Covered directory is hidden from accessibility');
 find(tree,'UnvisitedCountryRecord').props.onBack();tree=host.render();assert(!find(tree,'UnvisitedCountryRecord'));assert.equal(find(tree,'CountryIndex').props.query,'Guinea');assert.equal(closed,0);
 find(tree,'CountryIndex').props.onSelectUnvisited({key:'GW',name:'Guinea-Bissau'});tree=host.render();assert.equal(handler(),true);tree=host.render();assert.equal(handler(),false,'Back at index delegates to its parent');
 find(tree,'CountryIndex').props.onSelect(somaliland);tree=host.render();assert.equal(find(tree,'CountryArrivalDetail').props.arrival,somaliland);
 tree=host.render({...props,visible:false});assert.equal(handler,null);tree=host.render(props);assert(find(tree,'CountryArrivalDetail'),'Trip return restores the country detail');
 tree=host.render({...props,initialCountry:'SG',backLabel:'Globe',scopeEpoch:1});assert.equal(find(tree,'CountryArrivalDetail').props.backLabel,'Globe');assert.equal(handler(),false,'Direct globe entry preserves Globe as Back origin');host.unmount();
}
console.log('Country collection passed: catalogue membership, chronological original stamps, Somaliland, connection-airport search, scoped/all browsing, unvisited detail, preserved index state, Back origins and large-text columns.');
