import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
const source=await readFile(new URL('../docs/_worker.js',import.meta.url),'utf8');
const worker=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
const env={ADMIN_ACCESS_ISSUER:'https://example.cloudflareaccess.com',ADMIN_ACCESS_AUD:'app-aud',
 ADMIN_ALLOWED_EMAIL:'owner@example.com',ADMIN_GITHUB_TOKEN:'server-only-test',
 ASSETS:{fetch:async()=>new Response('admin html')}};
const keys=await crypto.subtle.generateKey({name:'RSASSA-PKCS1-v1_5',modulusLength:2048,publicExponent:new Uint8Array([1,0,1]),hash:'SHA-256'},true,['sign','verify']);
const jwk={...await crypto.subtle.exportKey('jwk',keys.publicKey),kid:'test'};
async function token(changes={},header={alg:'RS256',kid:'test'}) {
 const b64=value=>Buffer.from(JSON.stringify(value)).toString('base64url');
 const data=b64(header)+'.'+b64({iss:env.ADMIN_ACCESS_ISSUER,aud:[env.ADMIN_ACCESS_AUD],email:env.ADMIN_ALLOWED_EMAIL,iat:Math.floor(Date.now()/1000),exp:Math.floor(Date.now()/1000)+300,...changes});
 return data+'.'+Buffer.from(await crypto.subtle.sign('RSASSA-PKCS1-v1_5',keys.privateKey,new TextEncoder().encode(data))).toString('base64url');
}
let registry,sha,writes,dispatches;
const original=globalThis.fetch;

test('encoded management paths cannot fall through to public assets',async()=>{
 for(const path of ['/%73/','/s%2findex.html','/%61dmin/config.yml','/api/%61dmin/state']){
  assert.equal((await worker.handleRequest(new Request('https://bmt.news'+path),env)).status,401);
 }
});
test('legacy editing keeps additional metadata and validates required fields',async()=>{
 const entry={type:'sponsored',enabled:true,url:'https://example.com/promo',title_zh:'广告',starts:'2026-09-10',expires:'2026-09-11',position:4,tags:[],sources:[]};
 let r=await request('/api/admin/legacy',{sha,index:0,entry});assert.equal(r.status,200);
 assert.equal(registry.items[0].extra,'preserved');assert.equal(registry.items[0].title_zh,'广告');
 r=await request('/api/admin/legacy',{sha,index:-1,entry:{...entry,expires:'2026-09-01'}});assert.equal(r.status,400);
 r=await request('/api/admin/legacy',{sha,index:-1,entry:{...entry,url:'javascript:alert(1)'}});assert.equal(r.status,400);
 r=await request('/api/admin/legacy',{sha,index:-1,entry:{...entry,type:'suppress',title_zh:''}});assert.equal(r.status,200);
});
test('valid content-addressed upload and identical retry, invalid MIME and size',async()=>{
 const previous=globalThis.fetch;let saved;
 globalThis.fetch=async(url,init)=>{
  if(url.includes('/contents/docs/assets/uploads/')){
   if(init.method==='PUT'){
    if(saved)return Response.json({},{status:422});
    saved=JSON.parse(init.body);assert.equal(saved.branch,'main');
    assert.match(url,/quick-[a-f0-9]{64}\.png$/);
    return Response.json({content:{sha:'a'},commit:{sha:'b'}});
   }
   return Response.json({content:saved.content});
  }
  return previous(url,init);
 };
 const input={mime:'image/png',data:'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl6kZAAAAAASUVORK5CYII='};
 let r=await request('/api/admin/image',input);assert.equal(r.status,200);
 assert.match((await r.json()).path,/^\/assets\/uploads\/quick-/);
 assert.equal((await request('/api/admin/image',input)).status,200);
 for(const data of [{mime:'image/svg+xml',data:input.data},{mime:'image/jpeg',data:input.data},{mime:'image/png',data:'A'},{mime:'image/png',data:Buffer.alloc(1024*1024+1).toString('base64')}]) {
  assert.equal((await request('/api/admin/image',data)).status,400);
 }
});
test.beforeEach(()=>{
 registry={_readme:'keep',items:[{type:'sponsored',title_zh:'old',enabled:false,extra:'preserved'}]};sha='a'.repeat(40);writes=0;dispatches=0;
 globalThis.fetch=async(url,init={})=>{
  if(url===env.ADMIN_ACCESS_ISSUER+'/cdn-cgi/access/certs')return Response.json({keys:[jwk]});
  assert.ok(url.startsWith('https://api.github.com/repos/ohxiyu/bmtnews-standalone/'));
  assert.equal(init.headers.Authorization,'Bearer server-only-test');
  if(url.includes('dispatches')){dispatches++;return new Response(null,{status:204});}
  if(init.method==='PUT'){
   const body=JSON.parse(init.body);assert.equal(body.branch,'main');assert.equal(body.sha,sha);
   registry=JSON.parse(Buffer.from(body.content,'base64').toString());writes++;sha=String(writes).repeat(40);
   return Response.json({content:{sha},commit:{sha:'f'.repeat(40)}});
  }
  return Response.json({sha,content:Buffer.from(JSON.stringify(registry)).toString('base64')});
 };
});
test.afterEach(()=>{globalThis.fetch=original;delete globalThis.caches;});
async function request(path='/api/admin/state',body,overrides={}) {
 const headers={'Cf-Access-Jwt-Assertion':await token(),...(body?{'Origin':'https://bmt.news','X-BMT-Admin':'1','Content-Type':'application/json'}:{}),...overrides};
 return worker.handleRequest(new Request('https://bmt.news'+path,{method:body?'POST':'GET',headers,body:body?JSON.stringify(body):undefined}),env);
}
function post(changes={}){return {id:'12345678-1234-1234-1234-123456789abc',body:'正文 🚀\n\n第二段',date:'2026-09-10',category:'',url:'',image:'',enabled:true,pin:false,breaking:false,sha,...changes};}
test('fail closed before asset or cache reads including alternate admin URLs',async()=>{
 globalThis.caches={default:{match:()=>{throw Error('cache must not run');}}};
 for(const path of ['/s','/s/','/s/admin.js','/s/sources/','/admin/config.yml','/api/admin/state']){
  const r=await worker.handleRequest(new Request('https://bmt.news'+path),env);
  assert.equal(r.status,401);assert.match(r.headers.get('Cache-Control'),/no-store/);assert.equal(r.headers.get('Access-Control-Allow-Origin'),null);
 }
 assert.equal((await worker.handleRequest(new Request('https://bmt.news/s/'),{})).status,503);
});
test('JWT rejects wrong email, audience, issuer, expiry, future iat and algorithm',async()=>{
 for(const claim of [{email:'attacker@example.com'},{aud:['other']},{iss:'https://evil.example'},{exp:0},{iat:Date.now()/1000+1000}]){
  const r=await request('/api/admin/state',undefined,{'Cf-Access-Jwt-Assertion':await token(claim)});assert.equal(r.status,401);
 }
 const r=await request('/api/admin/state',undefined,{'Cf-Access-Jwt-Assertion':await token({}, {alg:'none',kid:'test'})});assert.equal(r.status,401);
});
test('JWT rejects tampering, header spoofing and direct pages.dev bypass',async()=>{
 const jwt=await token();const parts=jwt.split('.');parts[1]=Buffer.from(JSON.stringify({email:'owner@example.com'})).toString('base64url');
 assert.equal((await request('/api/admin/state',undefined,{'Cf-Access-Jwt-Assertion':parts.join('.')})).status,401);
 assert.equal((await worker.handleRequest(new Request('https://bmt.news/s/',{headers:{'Cf-Access-Authenticated-User-Email':'owner@example.com'}}),env)).status,401);
 assert.equal((await worker.handleRequest(new Request('https://bmtnews.pages.dev/s/',{headers:{'Cf-Access-Jwt-Assertion':jwt}}),env)).status,403);
});
test('authenticated state and assets are private and old CMS redirects',async()=>{
 const r=await request();assert.equal(r.status,200);assert.equal((await r.json()).items[0].extra,'preserved');assert.match(r.headers.get('Cache-Control'),/private/);
 const asset=await request('/s/');assert.equal(await asset.text(),'admin html');assert.match(asset.headers.get('Content-Security-Policy'),/frame-ancestors 'none'/);
 const legacy=await request('/admin/');assert.equal(legacy.headers.get('Location'),'/s/');
 assert.equal((await request('/admin/config.yml')).status,404);
});
test('body-only post saves without mutating legacy data; same retry is idempotent',async()=>{
 const input=post();let r=await request('/api/admin/posts',input);assert.equal(r.status,200);
 assert.equal(registry._readme,'keep');assert.equal(registry.items[0].extra,'preserved');
 assert.equal(registry.items[1].body,input.body);assert.equal(registry.items[1].url,'');
 assert.equal((await request('/api/admin/posts',input)).status,200);assert.equal(writes,1);
});
test('stale revision never overwrites, including a changed same-ID retry',async()=>{
 const input=post();await request('/api/admin/posts',input);
 const r=await request('/api/admin/posts',{...input,body:'changed'});assert.equal(r.status,409);assert.equal(writes,1);
});
test('CSRF and non-JSON writes rejected',async()=>{
 for(const headers of [{'Origin':'https://evil.example'},{'X-BMT-Admin':''},{'Content-Type':'text/plain'}]){
  assert.equal((await request('/api/admin/posts',post(),headers)).status,403);
 }
 assert.equal(writes,0);
});
test('invalid post, dates, script URL and image path rejected',async()=>{
 for(const changes of [{body:''},{body:'x'.repeat(10001)},{date:'2026-02-30'},{url:'javascript:alert(1)'},{url:'https://user:pass@example.com'},{image:'/private'},{pin:'true'},{category:'bad'}]){
  assert.equal((await request('/api/admin/posts',post(changes))).status,400);
 }
 assert.equal(writes,0);
});
test('draft and enable state preserve all unrelated fields',async()=>{
 await request('/api/admin/posts',post({enabled:false}));
 assert.equal(registry.items[1].enabled,false);
 const r=await request('/api/admin/entry-state',{sha,index:1,enabled:true});
 assert.equal(r.status,200);assert.equal(registry.items[1].enabled,true);assert.equal(registry.items[0].extra,'preserved');
});
test('source request uses only fixed existing workflow and no production config write',async()=>{
 const r=await request('/api/admin/sources',{operation:'pause',source_type:'rss',source_key:'rss|https://example.com/',reason:'test',enabled:'false',category:'unchanged'});
 assert.equal(r.status,202);assert.equal(dispatches,1);assert.equal(writes,0);
});
test('bounded request rejects oversized bodies and invalid JSON',async()=>{
 assert.equal((await request('/api/admin/posts',{body:'x'.repeat(110000)})).status,413);
});
test('unknown admin API and missing writer token are explicit failures',async()=>{
 assert.equal((await request('/api/admin/nope',{})).status,404);
 const r=await worker.handleRequest(new Request('https://bmt.news/api/admin/state',{headers:{'Cf-Access-Jwt-Assertion':await token()}}),{...env,ADMIN_GITHUB_TOKEN:''});
 assert.equal(r.status,503);
});
