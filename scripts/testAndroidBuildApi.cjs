const {test}=require('node:test');
const assert=require('node:assert/strict');
const {parseOrigin,checkReadiness,artifactMetadata}=require('./android-build-api.cjs');
const api='https://trotter-api.thehennighs.com';
const healthy={status:'ready',checks:{database:true,redis:true}};
const response=(body=healthy,changes={})=>({status:200,headers:new Headers({'content-type':'application/json'}),json:async()=>body,url:`${api}/ready`,...changes});
test('requires explicit origin and rejects paths, credentials and fragments',()=>{
  assert.equal(parseOrigin(`${api}/`),api);
  for(const bad of ['',`${api}/auth`,`${api}?host=other`,`${api}#other`,'https://user:pass@example.com','file:///tmp/api'])assert.throws(()=>parseOrigin(bad));
});
test('checks selected endpoint without accepting redirects',async()=>{
  const result=await checkReadiness(api,async(url,options)=>{
    assert.equal(url,`${api}/ready`);assert.equal(options.redirect,'error');assert.ok(options.signal);return response();
  });assert.equal(result.api_origin,api);assert.deepEqual(result.readiness,healthy);
});
test('rejects HTTP, HTML, unhealthy or redirected readiness',async()=>{
  for(const reply of [response(healthy,{status:503}),response(healthy,{headers:new Headers({'content-type':'text/html'})}),response({status:'ready',checks:{database:true,redis:false}}),response({status:'ok'}),response(healthy,{url:'https://other.invalid/ready'})])await assert.rejects(checkReadiness(api,async()=>reply));
});
test('rejects unreachable endpoints instead of building',async()=>{
  await assert.rejects(checkReadiness(api,async()=>{throw new Error('DNS failure');}),/DNS failure/);
});
test('metadata binds artifact hash and verified bundled origin',()=>{
  const fields={artifact:Buffer.from('test APK'),bundle:Buffer.from(`compiled ${api}`),readiness:{api_origin:api,readiness:healthy},commit:'a'.repeat(40),versionCode:5,channel:'development'};
  const result=artifactMetadata(fields);assert.equal(result.api_origin,api);assert.equal(result.version_code,5);assert.equal(result.sha256.length,64);assert.equal(result.bundle_origin_verified,true);
  assert.throws(()=>artifactMetadata({...fields,bundle:Buffer.from('https://api.thehennighs.com')}),/refusing to publish/);
});
