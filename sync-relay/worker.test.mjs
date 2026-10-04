import {test,after} from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {fileURLToPath} from 'node:url';
const {Miniflare,convertV4MiniflareOptions}=await import(process.env.AGENT_CITY_MINIFLARE_MODULE||'miniflare');
const token=Buffer.alloc(32,1).toString('base64url'),otherToken=Buffer.alloc(32,2).toString('base64url');
const hash=v=>createHash('sha256').update(v).digest('hex');
const mf=new Miniflare(convertV4MiniflareOptions({name:'test-relay',modules:true,scriptPath:fileURLToPath(new URL('./worker.mjs',import.meta.url)),compatibilityDate:'2026-09-10',durableObjects:{SYNC:{className:'Sync',useSQLite:true}},bindings:{DEVICE_HASHES:JSON.stringify({[hash(token)]:'device-pc-01',[hash(otherToken)]:'device-mac-01'})}}));
after(()=>mf.dispose());
const envelope=n=>({v:1,nonce:Buffer.alloc(12,n).toString('base64url'),ciphertext:Buffer.alloc(32,n).toString('base64url')});
const request=(method='GET',body,headers={})=>mf.dispatchFetch('https://example.test/v1/state',{method,headers:{Authorization:'Bearer '+token,...headers},...(body?{body:JSON.stringify(body)}:{})});
test('authorization, browser rejection and verified device cannot be forged',async()=>{
 assert.equal((await request('GET',null,{Authorization:'Bearer invalid'})).status,401);
 assert.equal((await request('GET',null,{Origin:'https://example.test'})).status,403);
 const response=await request('GET',null,{'X-Verified-Device':'device-forged'});
 assert.equal(response.status,200);assert.equal((await response.json()).device,'device-pc-01');
});
test('CAS is atomic, retry idempotent and another device cannot replace this row',async()=>{
 const a={revision:1,envelope:envelope(1)};
 assert.equal((await request('PUT',a)).status,200);
 assert.equal((await (await request('PUT',a)).json()).duplicate,true);
 assert.equal((await request('PUT',{...a,envelope:envelope(2)})).status,409);
 assert.equal((await request('PUT',{revision:3,envelope:envelope(3)})).status,409);
 const responses=await Promise.all([2,3].map(n=>request('PUT',{revision:2,envelope:envelope(n)})));
 assert.deepEqual(responses.map(r=>r.status).sort(),[200,409]);
 assert.equal((await request('PUT',a,{Authorization:'Bearer '+otherToken})).status,200);
 const state=await (await request()).json();assert.equal(state.records.length,2);
 assert.equal(state.records.find(r=>r.device==='device-pc-01').revision,2);
 assert.ok(state.records.every(r=>Object.keys(r.envelope).sort().join(',')==='ciphertext,nonce,v'));
});
test('plaintext fields and oversized bodies are rejected',async()=>{
 assert.equal((await request('PUT',{revision:3,envelope:envelope(3),title:'private'})).status,400);
 assert.equal((await request('PUT',{revision:3,envelope:{...envelope(3),key:'secret'}})).status,400);
 assert.equal((await request('PUT',{revision:3,envelope:{...envelope(3),ciphertext:'A'.repeat(600000)}})).status,413);
});
