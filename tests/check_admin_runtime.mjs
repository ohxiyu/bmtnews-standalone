// Run with MINIFLARE_MODULE pointing to an installed Miniflare package.
// Uses ephemeral test keys, no production credentials or external requests.
import {createRequire} from 'node:module';
import {readFile} from 'node:fs/promises';
import assert from 'node:assert/strict';
const require=createRequire(import.meta.url);
const {Miniflare}=require(process.env.MINIFLARE_MODULE || 'miniflare');
const keys=await crypto.subtle.generateKey({name:'RSASSA-PKCS1-v1_5',modulusLength:2048,publicExponent:new Uint8Array([1,0,1]),hash:'SHA-256'},true,['sign','verify']);
const jwk={...await crypto.subtle.exportKey('jwk',keys.publicKey),kid:'test'};
const env={ADMIN_ACCESS_ISSUER:'https://example.cloudflareaccess.com',ADMIN_ACCESS_AUD:'test',ADMIN_ALLOWED_EMAIL:'test@example.com'};
const b=value=>Buffer.from(JSON.stringify(value)).toString('base64url');
const data=b({alg:'RS256',kid:'test'})+'.'+b({iss:env.ADMIN_ACCESS_ISSUER,aud:['test'],email:env.ADMIN_ALLOWED_EMAIL,iat:Math.floor(Date.now()/1000),exp:Math.floor(Date.now()/1000)+300});
const token=data+'.'+Buffer.from(await crypto.subtle.sign('RSASSA-PKCS1-v1_5',keys.privateKey,new TextEncoder().encode(data))).toString('base64url');
const source=await readFile(new URL('../docs/_worker.js',import.meta.url),'utf8');
const script=source.replace('export default {','const originalHandler = {')+`
export default {async fetch(req,env){
 try { await verifyAdmin(new Request('https://bmt.news/s/',{headers:req.headers}),env); return new Response('verified'); }
 catch(e){return new Response(e.code,{status:401});}
}}`;
let redirect=false;
const mf=new Miniflare({modules:true,compatibilityDate:'2026-07-29',script,bindings:env,
 outboundService:()=>redirect ? new Response(null,{status:302,headers:{Location:'https://untrusted.example'}}) : Response.json({keys:[jwk]})});
try {
 const headers={'Cf-Access-Jwt-Assertion':token};
 assert.equal((await mf.dispatchFetch('http://localhost/',{headers})).status,200);
 redirect=true;
 assert.equal((await mf.dispatchFetch('http://localhost/',{headers})).status,401);
 console.log('workerd: valid JWT accepted; redirected JWKS rejected');
} finally {await mf.dispose();}
