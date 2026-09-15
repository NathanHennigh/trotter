const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),ts=require('typescript');
const {test}=require('node:test');
const build=require('./generateCollectionCatalogs.cjs');
const folder=path.join(__dirname,'../src/data/collections');
const countries=require(path.join(folder,'countries.json')),airports=require(path.join(folder,'airports.json')),airlines=require(path.join(folder,'airlines.json'));
const output=ts.transpileModule(fs.readFileSync(path.join(__dirname,'../src/components/world-window/collections/catalogProgress.ts'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
const mod={exports:{}};new Function('module','exports',output)(mod,mod.exports);
const {resolveCatalogKey,collectionProgress}=mod.exports;

test('pinned snapshots reproduce every catalogue without network and with source integrity',()=>{
  for(const [file,value] of Object.entries(build.generate()))assert.deepEqual(JSON.parse(fs.readFileSync(path.join(folder,file),'utf8')),value);
  for(const catalog of [countries,airports,airlines]){
    assert.equal(catalog.metadata.total,catalog.entries.length);assert.equal(new Set(catalog.entries.map(row=>row.key)).size,catalog.entries.length);
    assert(catalog.metadata.sources.every(source=>/^[a-f0-9]{64}$/.test(source.sha256)&&source.url.startsWith('https://')));
  }
});
test('country universe includes territories and independent Somaliland identity without counting unknown/geographic extensions',()=>{
  assert.equal(countries.entries.length,251);
  for(const key of ['AX','BV','SJ','XK','X-SOMALILAND','SO','PS','TW','HK','PF','PR'])assert(countries.entries.some(row=>row.key===key),key);
  for(const key of ['XP','ZZ'])assert(!countries.entries.some(row=>row.key===key));
  for(const [value,key] of [['Somaliland','X-SOMALILAND'],['UAE','AE'],['uk','GB'],['Côte d’Ivoire','CI'],['United States of America','US'],['Vatican','VA']])assert.equal(resolveCatalogKey(countries,value),key);
});
test('CSV reader preserves quoted commas, quotes, Unicode, newlines and empty final fields',()=>{
  assert.deepEqual(build.parseCsv('a,b,c\r\n"Café, Nord","A ""B""\nC",\r\n'),[['a','b','c'],['Café, Nord','A "B"\nC','']]);
  assert.throws(()=>build.parseCsv('"unfinished'),/Unterminated/);
  assert.throws(()=>build.csvObjects('a,b\n1\n'),/column count/);
});
test('airport universe admits scheduled seaplanes but rejects closed, unscheduled, malformed and invalid-coordinate records',()=>{
  const base={id:'1',ident:'KAAA',iata_code:'AAA',name:'Airport',municipality:'City',scheduled_service:'yes',type:'small_airport',latitude_deg:'0',longitude_deg:'0',iso_country:'US',continent:'NA'};
  const rows=[base,{...base,iata_code:'BBB',type:'seaplane_base'},...[
    {iata_code:'CCC',type:'closed_airport'},{iata_code:'DDD',type:'heliport'},{iata_code:'EEE',scheduled_service:'no'},
    {iata_code:'12A'},{iata_code:'FFF',latitude_deg:''},{iata_code:'GGG',latitude_deg:'NaN'},{iata_code:'HHH',longitude_deg:'181'},
  ].map(change=>({...base,...change}))];
  assert.deepEqual(build.buildAirports(rows,countries.entries).map(row=>row.key),['AAA','BBB']);
  assert.throws(()=>build.buildAirports([base,base],countries.entries),/Ambiguous/);
  for(const code of ['HGA','BBO'])assert.equal(build.buildAirports([{...base,iata_code:code,iso_country:'SO'}],countries.entries)[0].country,'X-SOMALILAND');
});
const binding=row=>Object.fromEntries(Object.entries(row).map(([key,value])=>[key,{value}]));
test('airline catalogue retains all source operators under shared codes and never treats historical/unknown data as new members',()=>{
  const base={airline:'http://www.wikidata.org/entity/Q1',airlineLabel:'Carrier',iata:'AA',icao:'AAA',iso:'US'};
  const rows=[base,{...base,airline:'http://www.wikidata.org/entity/Q2',airlineLabel:'Shared operator'},
    {...base,airline:'http://www.wikidata.org/entity/Q3',iata:'ZZ',dissolved:'2020-01-01T00:00:00Z'},
    {...base,airline:'http://www.wikidata.org/entity/Q4',iata:'YY',codeEnd:'2025-01-01T00:00:00Z'},
    {...base,airline:'http://www.wikidata.org/entity/Q5',iata:'--'},
    {...base,airline:'http://www.wikidata.org/entity/Q6',iata:'XX',iso:'ZZ'}];
  const result=build.buildAirlines(rows.map(binding),countries.entries,'2026-09-15');
  assert.equal(result.entries.length,1);assert.equal(result.entries[0].key,'AA');assert.equal(result.entries[0].operators.length,2);assert.equal(result.entries[0].sharedCode,true);
  assert.deepEqual(build.buildAirlines([...rows].reverse().map(binding),countries.entries,'2026-09-15').entries,result.entries);
  for(const key of ['AA','UA','WN','DL','NH','EK','KL','LH'])assert(airlines.entries.some(row=>row.key===key),key);
});
test('progress deduplicates canonical identities, preserves outside observations and does not mutate records',()=>{
  const visits=['US',' usa ','United States of America','Somaliland','X-SOMALILAND','ZZ','zz',null,''];
  const original=[...visits],result=collectionProgress(countries,visits);
  assert.equal(result.collected,2);assert.equal(result.total,251);assert.equal(result.remaining,249);assert.equal(result.percent,2/251*100);
  assert.deepEqual(result.collectedKeys,['US','X-SOMALILAND']);assert.deepEqual(result.outsideCatalogKeys,['ZZ']);assert.deepEqual(visits,original);
  const all=collectionProgress(airports,[...airports.entries.map(row=>row.key),'OLD','MISSING']);assert.equal(all.percent,100);assert.equal(all.collected,airports.entries.length);assert.deepEqual(all.outsideCatalogKeys,['MISSING','OLD']);
});
test('empty catalogues remain finite; duplicate display names never resolve arbitrarily',()=>{
  const catalog={entries:[{key:'A',name:'Same',aliases:['Both']},{key:'B',name:'Same',aliases:['Both']}]};
  assert.equal(resolveCatalogKey(catalog,'Same'),undefined);assert.equal(resolveCatalogKey(catalog,'Both'),undefined);assert.equal(resolveCatalogKey(catalog,'A'),'A');
  const result=collectionProgress({entries:[]},['A']);assert.equal(result.percent,0);assert.equal(result.total,0);assert.deepEqual(result.outsideCatalogKeys,['A']);
});
