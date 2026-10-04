// Private workspace relay. It stores encrypted snapshots, never decryption keys.
import { DurableObject } from 'cloudflare:workers';
const LIMIT=512*1024, ID=/^[a-zA-Z0-9_-]{8,64}$/, B64=/^[A-Za-z0-9_-]+$/;
function json(value,status=200){return Response.json(value,{status,headers:{'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'}});}
async function sha(value){return [...new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(value)))].map(x=>x.toString(16).padStart(2,'0')).join('');}
function validEnvelope(e){return e&&Object.keys(e).sort().join(',')==='ciphertext,nonce,v'&&e.v===1&&typeof e.nonce==='string'&&e.nonce.length===16&&B64.test(e.nonce)&&typeof e.ciphertext==='string'&&e.ciphertext.length>=22&&e.ciphertext.length<LIMIT&&B64.test(e.ciphertext);}
export default {
 async fetch(request,env){
  const url=new URL(request.url);
  if(url.protocol!=='https:'||url.search||url.pathname!=='/v1/state'||!['GET','PUT'].includes(request.method))return json({error:'not_found'},404);
  if(request.headers.has('Origin'))return json({error:'native_client_required'},403);
  const token=request.headers.get('Authorization')?.match(/^Bearer ([A-Za-z0-9_-]{43})$/)?.[1];
  if(!token)return json({error:'unauthorized'},401);
  let devices;try{devices=JSON.parse(env.DEVICE_HASHES||'{}');}catch{return json({error:'not_configured'},503);}
  const device=devices[await sha(token)];
  if(!device||!ID.test(device)||Object.keys(devices).length>8)return json({error:'unauthorized'},401);
  // One isolated workspace per deployed service; all its enrolled devices share the key.
  const headers=new Headers(request.headers);headers.delete('Authorization');headers.delete('Cookie');headers.set('X-Verified-Device',device);
  return env.SYNC.getByName('agent-city-workspace-v1').fetch(new Request(request,{headers}));
 }
};
export class Sync extends DurableObject {
 constructor(ctx,env){super(ctx,env);this.sql=ctx.storage.sql;this.sql.exec('CREATE TABLE IF NOT EXISTS snapshots(device TEXT PRIMARY KEY, revision INTEGER NOT NULL, envelope TEXT NOT NULL, updated_at TEXT NOT NULL)');}
 async fetch(request){
  const device=request.headers.get('X-Verified-Device');
  if(!ID.test(device||''))return json({error:'unauthorized'},401);
  if(request.method==='GET')return json({schemaVersion:1,device,records:this.sql.exec('SELECT device,revision,envelope,updated_at AS updatedAt FROM snapshots ORDER BY device').toArray().map(r=>({...r,envelope:JSON.parse(r.envelope)}))});
  if(Number(request.headers.get('Content-Length'))>LIMIT)return json({error:'too_large'},413);
  const reader=request.body?.getReader();if(!reader)return json({error:'invalid_body'},400);
  const chunks=[];let size=0;
  for(;;){const {done,value}=await reader.read();if(done)break;size+=value.length;if(size>LIMIT){await reader.cancel();return json({error:'too_large'},413);}chunks.push(value);}
  const bytes=new Uint8Array(size);let offset=0;for(const chunk of chunks){bytes.set(chunk,offset);offset+=chunk.length;}
  let body;try{body=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(bytes));}catch{return json({error:'invalid_body'},400);}
  if(!body||Object.keys(body).sort().join(',')!=='envelope,revision'||!Number.isSafeInteger(body.revision)||body.revision<1||!validEnvelope(body.envelope))return json({error:'invalid_envelope'},400);
  const envelope=JSON.stringify({v:1,nonce:body.envelope.nonce,ciphertext:body.envelope.ciphertext});
  // No await between CAS read and write: one synchronous SQLite transaction.
  return this.ctx.storage.transactionSync(()=>{
   const old=this.sql.exec('SELECT revision,envelope,updated_at FROM snapshots WHERE device=?',device).toArray()[0];
   if(old?.revision===body.revision&&old.envelope===envelope)return json({revision:old.revision,duplicate:true});
   if(body.revision!==(old?.revision||0)+1)return json({error:'revision_conflict',revision:old?.revision||0},409);
   if(!old&&this.sql.exec('SELECT count(*) AS n FROM snapshots').one().n>=8)return json({error:'device_limit'},409);
   this.sql.exec('INSERT INTO snapshots VALUES(?,?,?,?) ON CONFLICT(device) DO UPDATE SET revision=excluded.revision,envelope=excluded.envelope,updated_at=excluded.updated_at',device,body.revision,envelope,new Date().toISOString());
   return json({revision:body.revision,duplicate:false});
  });
 }
}
