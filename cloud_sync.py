"""Encrypted, per-device Agent City snapshots. Local caches contain ciphertext only."""
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import threading
import tempfile
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, ProxyHandler
from urllib.parse import urlsplit
import zlib
from run_store import validate, FIELDS
from provider_catalogs import _NoRedirect
from cicada_connector import _has_reparse

PROFILE='agent-city-activity-v1'
MAX_PLAIN=4*1024*1024
MAX_WIRE=512*1024


class SyncError(ValueError): pass


def b64(raw): return base64.urlsafe_b64encode(raw).decode().rstrip('=')
def unb64(value): return base64.urlsafe_b64decode(value+'='*(-len(value)%4))


def profile_check(value):
    if not isinstance(value,dict) or set(value)!={'profile','endpoint','device','token','key'} or value['profile']!=PROFILE:
        raise SyncError('invalid_profile')
    if not all(isinstance(value[k],str) for k in value): raise SyncError('invalid_profile')
    url=urlsplit(value['endpoint'])
    if url.scheme!='https' or not re.fullmatch(r'agent-city-sync-v1\.[a-z0-9-]+\.workers\.dev',url.netloc) or url.path not in ('','/') or url.query or url.fragment:
        raise SyncError('invalid_endpoint')
    if not re.fullmatch(r'[A-Za-z0-9_-]{8,64}',value['device']): raise SyncError('invalid_device')
    for name in ('token','key'):
        if not isinstance(value[name],str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}',value[name]) or len(unb64(value[name]))!=32 or b64(unb64(value[name]))!=value[name]:
            raise SyncError('invalid_secret')
    return {**value,'endpoint':value['endpoint'].rstrip('/')}


def atomic_bytes(path,raw):
    if _has_reparse(path): raise SyncError('redirected_storage')
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    fd,name=tempfile.mkstemp(dir=path.parent,prefix='.sync-')
    temp=Path(name)
    try:
        with os.fdopen(fd,'wb') as stream:
            stream.write(raw);stream.flush();os.fsync(stream.fileno())
        os.replace(temp,path)
    finally:
        temp.unlink(missing_ok=True)


def atomic(path,value):
    atomic_bytes(path,json.dumps(value,ensure_ascii=False,allow_nan=False).encode())


def clean_runs(rows):
    if not isinstance(rows,list) or len(rows)>500: raise SyncError('invalid_runs')
    result=[];seen=set()
    for raw in rows:
        if not isinstance(raw,dict): raise SyncError('invalid_runs')
        row=validate({key:raw.get(key) for key in FIELDS})
        if row['runId'] in seen: raise SyncError('duplicate_run')
        seen.add(row['runId'])
        for name in ('updatedAt','firstReportedAt'):
            stamp=raw.get(name)
            if not isinstance(stamp,str) or len(stamp)>40 or datetime.fromisoformat(stamp).tzinfo is None: raise SyncError('invalid_timestamp')
            row[name]=stamp
        history=raw.get('history',[])
        if not isinstance(history,list) or len(history)>30: raise SyncError('invalid_history')
        row['history']=[]
        for entry in history:
            checked=validate({**{key:row[key] for key in FIELDS},**{key:entry.get(key) for key in ('stage','status','skillIds','mcpCalls','inputTokens','outputTokens')}})
            stamp=entry['reportedAt']
            if len(stamp)>40 or datetime.fromisoformat(stamp).tzinfo is None: raise SyncError('invalid_timestamp')
            row['history'].append({**{key:checked[key] for key in ('stage','status','skillIds','mcpCalls','inputTokens','outputTokens')},'reportedAt':stamp})
        binding=raw.get('taskBinding')
        if binding is not None:
            if not isinstance(binding,dict) or set(binding)!={'profile','sourceId'} or binding['profile']!='production' or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',binding['sourceId']): raise SyncError('invalid_binding')
            row['taskBinding']=binding
        names=raw.get('skillNames',{})
        if not isinstance(names,dict) or set(names)-set(row['skillIds']) or any(not isinstance(v,str) or not 1<=len(v)<=120 or any(ord(c)<32 for c in v) for v in names.values()): raise SyncError('invalid_skill_names')
        row['skillNames']=names
        result.append(row)
    return result


def seal(profile,revision,snapshot):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    plain=json.dumps(snapshot,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
    if len(plain)>MAX_PLAIN: raise SyncError('snapshot_too_large')
    nonce=os.urandom(12)
    aad=f"{PROFILE}|{profile['endpoint']}|{profile['device']}|{revision}".encode()
    ciphertext=AESGCM(unb64(profile['key'])).encrypt(nonce,zlib.compress(plain),aad)
    envelope={'v':1,'nonce':b64(nonce),'ciphertext':b64(ciphertext)}
    if len(json.dumps(envelope))>MAX_WIRE-256: raise SyncError('snapshot_too_large')
    return envelope


def unseal(profile,record):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    envelope=record['envelope']
    if set(envelope)!={'v','nonce','ciphertext'} or envelope['v']!=1 or len(envelope['ciphertext'])>MAX_WIRE: raise SyncError('invalid_envelope')
    aad=f"{PROFILE}|{profile['endpoint']}|{record['device']}|{record['revision']}".encode()
    compressed=AESGCM(unb64(profile['key'])).decrypt(unb64(envelope['nonce']),unb64(envelope['ciphertext']),aad)
    decoder=zlib.decompressobj();plain=decoder.decompress(compressed,MAX_PLAIN+1)
    if len(plain)>MAX_PLAIN or not decoder.eof or decoder.unused_data: raise SyncError('invalid_snapshot_size')
    body=json.loads(plain)
    if not isinstance(body,dict) or set(body)!={'schemaVersion','device','runs'} or body['schemaVersion']!=1 or body['device']!=record['device']: raise SyncError('invalid_snapshot')
    return clean_runs(body['runs'])


def check_remote(profile,remote):
    if not isinstance(remote,dict) or remote.get('schemaVersion')!=1 or remote.get('device')!=profile['device'] or not isinstance(remote.get('records'),list) or len(remote['records'])>8: raise SyncError('invalid_cloud_response')
    seen=set()
    for r in remote['records']:
        if not isinstance(r,dict) or not isinstance(r.get('device'),str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,64}',r['device']) or r['device'] in seen or type(r.get('revision')) is not int or not 1<=r['revision']<=2**53-1: raise SyncError('invalid_cloud_response')
        seen.add(r['device'])
    return remote


class CloudSync:
    def __init__(self,directory,source,transport=None):
        self.directory=Path(directory)/'cloud';self.source=source;self.transport=transport or self._request
        self.lock=threading.Lock();self.error=None;self.last_sync=None;self.remote=[];self.devices=[]
        self.profile_path=self.directory/('profile.dpapi' if os.name=='nt' else 'profile.json')
        self.state_path=self.directory/'state.json';self.pending_path=self.directory/'pending.json';self.cache_path=self.directory/'cache.json'

    def _profile(self):
        if sys.platform=='darwin':
            if not self.profile_path.exists(): return None
            from keyring.backends.macOS import Keyring
            raw=Keyring().get_password('Agent City Cloud',hashlib.sha256(str(self.directory.resolve()).encode()).hexdigest())
            if not raw: raise SyncError('profile_unavailable')
            return profile_check(json.loads(raw))
        if not self.profile_path.exists(): return None
        if os.name!='nt': raise SyncError('secure_storage_unavailable')
        if _has_reparse(self.profile_path): raise SyncError('redirected_storage')
        raw=self.profile_path.read_bytes()
        if len(raw)>16384: raise SyncError('invalid_profile')
        if os.name=='nt':
            import panel_keys
            raw=panel_keys._unprotect(raw)
        return profile_check(json.loads(raw))

    def configure(self,value):
        profile=profile_check(value)
        with self.lock:
            old=self._profile()
            if old and old!=profile: raise SyncError('profile_already_configured')
            raw=json.dumps(profile).encode()
            if os.name=='nt':
                import panel_keys
                raw=panel_keys._protect(raw.decode())
                atomic_bytes(self.profile_path,raw)
            elif sys.platform=='darwin':
                try:
                    from keyring.backends.macOS import Keyring
                except ImportError as exc: raise SyncError('dependency_missing') from exc
                Keyring().set_password('Agent City Cloud',hashlib.sha256(str(self.directory.resolve()).encode()).hexdigest(),raw.decode())
                atomic(self.profile_path,{'storage':'macOS Keychain'})
            else: raise SyncError('secure_storage_unavailable')
        return self.status()

    def status(self):
        try: p=self._profile()
        except Exception: return {'configured':False,'state':'error','error':'profile_unavailable'}
        return {'configured':bool(p),'state':'error' if self.error else 'connected' if self.last_sync else 'pending' if p else 'not_configured','endpoint':p['endpoint'] if p else None,'device':p['device'] if p else None,'lastSync':self.last_sync,'error':self.error,'remoteDevices':self.devices}

    @staticmethod
    def _request(profile,method,body=None):
        data=json.dumps(body).encode() if body is not None else None
        req=Request(profile['endpoint']+'/v1/state',data=data,method=method,headers={'Authorization':'Bearer '+profile['token'],'Content-Type':'application/json','User-Agent':'AgentCitySync/1.0'})
        try:
            with build_opener(ProxyHandler({}),_NoRedirect()).open(req,timeout=12) as response: raw=response.read(8*MAX_WIRE+8193)
        except HTTPError as exc:
            raise SyncError({401:'unauthorized',409:'revision_conflict',413:'snapshot_too_large'}.get(exc.code,'cloud_unavailable')) from exc
        except (URLError,TimeoutError,OSError) as exc: raise SyncError('cloud_unavailable') from exc
        if len(raw)>8*MAX_WIRE+8192: raise SyncError('response_too_large')
        return json.loads(raw)

    @staticmethod
    def _read(path,default):
        if _has_reparse(path): raise SyncError('redirected_storage')
        if not path.exists(): return default
        if path.stat().st_size>8*MAX_WIRE+8192: raise SyncError('state_too_large')
        return json.loads(path.read_text(encoding='utf-8'))

    @staticmethod
    def _import(profile,remote,state,previous=None):
        check_remote(profile,remote)
        imported=[]
        old={(r['originDevice'],r['runId']):r for r in previous or []}
        for record in remote['records']:
            if record['device']==profile['device']: continue
            seen=state['seen'].get(record['device'],{})
            digest=hashlib.sha256(json.dumps(record['envelope'],sort_keys=True).encode()).hexdigest()
            if record['revision']<seen.get('revision',0) or record['revision']==seen.get('revision') and digest!=seen.get('digest'): raise SyncError('remote_rollback')
            for row in unseal(profile,record):
                before=old.get((record['device'],row['runId']))
                if before and (row['sequence']<before['sequence'] or row['sequence']==before['sequence'] and any(row.get(k)!=before.get(k) for k in FIELDS)): raise SyncError('run_rollback')
                imported.append({**row,'originDevice':record['device'],'readOnly':True})
            state['seen'][record['device']]={'revision':record['revision'],'digest':digest}
        return imported

    def sync(self):
        if not self.lock.acquire(blocking=False): return
        try:
            profile=self._profile()
            if not profile: return
            state=self._read(self.state_path,{'revision':0,'digest':None,'seen':{}})
            cached=self._read(self.cache_path,None)
            if cached and not self.remote:
                self.remote=self._import(profile,cached,state)
                self.devices=sorted(r['device'] for r in cached['records'] if r['device']!=profile['device'])
                self.last_sync=state.get('lastSync')
            pending=self._read(self.pending_path,None)
            remote=check_remote(profile,self.transport(profile,'GET'))
            own=next((r for r in remote['records'] if r['device']==profile['device']),None)
            if not pending and (own['revision'] if own else 0)!=state['revision']: raise SyncError('revision_conflict')
            rows=clean_runs(self.source())
            snapshot={'schemaVersion':1,'device':profile['device'],'runs':rows}
            digest=hashlib.sha256(json.dumps(snapshot,sort_keys=True).encode()).hexdigest()
            if not pending and digest!=state['digest']:
                revision=state['revision']+1
                pending={'digest':digest,'body':{'revision':revision,'envelope':seal(profile,revision,snapshot)}}
                atomic(self.pending_path,pending)
            if pending:
                ack=self.transport(profile,'PUT',pending['body'])
                if ack['revision']!=pending['body']['revision']: raise SyncError('invalid_ack')
                state.update(revision=ack['revision'],digest=pending['digest']);atomic(self.state_path,state)
                self.pending_path.unlink()
                remote=self.transport(profile,'GET')
            imported=self._import(profile,remote,state,self.remote)
            state['lastSync']=datetime.now(timezone.utc).isoformat(timespec='seconds')
            atomic(self.cache_path,remote);atomic(self.state_path,state)
            self.remote=imported;self.last_sync=state['lastSync'];self.error=None
            self.devices=sorted(r['device'] for r in remote['records'] if r['device']!=profile['device'])
        except ImportError:
            self.error='dependency_missing'
        except Exception as exc:
            self.error=str(exc) if isinstance(exc,SyncError) else 'sync_failed'
        finally: self.lock.release()

    def start(self):
        def loop():
            while True:
                self.sync()
                threading.Event().wait(30)
        threading.Thread(target=loop,name='agent-city-cloud',daemon=True).start()
