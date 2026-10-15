"""One atomic projection/outbox document; Cicada remains task authority."""
from __future__ import annotations
import copy
from contextlib import contextmanager
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import threading
import uuid
from codex_controls import _atomic,_reject_redirects
from task_connection import TaskConnection,TaskError,COMMAND_SCOPE,default_config,validate_config,authorize,encode,strict

MAX_STORE=16*1024*1024
def now():return datetime.now(timezone.utc).isoformat()
_locks={};_guard=threading.Lock()
@contextmanager
def locked(path):
    with _guard:lock=_locks.setdefault(str(path),threading.RLock())
    with lock:
        _reject_redirects(path);path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('a+b') as stream:
            if os.name=='nt':
                import msvcrt
                stream.seek(0);stream.write(b'0');stream.flush();stream.seek(0)
                try:msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
                except OSError:raise TaskError('task_sync_busy',409) from None
            else:
                import fcntl
                fcntl.flock(stream,fcntl.LOCK_EX)
            try:yield
            finally:
                if os.name=='nt':stream.seek(0);msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
                else:fcntl.flock(stream,fcntl.LOCK_UN)
def validate_task(task,ns):
    from work_exchange import validate_binding
    if type(task)!=dict or type(task.get('id'))!=str or type(task.get('version'))!=int or task['version']<1:raise TaskError('invalid_task_projection')
    b=validate_binding(task.get('binding'))
    if b['sourceId']!=task['id'] or b['sourceNamespace']!=ns:raise TaskError('task_binding_mismatch',409)
    for k in ('title','content','tags'):
        if type(task.get(k))!=str:raise TaskError('invalid_task_projection')
    for k in ('results','history','comments','intents','reports'):
        if type(task.get(k))!=list:raise TaskError('invalid_task_projection')
    return copy.deepcopy(task)
class TaskSync:
    def __init__(self,directory,connection_factory=TaskConnection):
        self.path=Path(directory)/'task-sync.json';self.lock_path=self.path.with_suffix('.lock');self.factory=connection_factory
        self.stop=threading.Event();self.worker=None;self.exchange_lock=threading.Lock()
    def _read(self):
        _reject_redirects(self.path)
        if not self.path.exists():return {'schemaVersion':1,'revision':0,'config':default_config(),'tasks':{},'outbox':{},'receipts':{},'nextQueueOrder':1,'lastSuccess':None,'lastAttempt':None,'failure':None}
        raw=self.path.read_bytes()
        if len(raw)>MAX_STORE:raise TaskError('task_sync_capacity',409)
        # Stored content has a larger bounded limit than one wire response.
        try:value=json.loads(raw)
        except (ValueError,UnicodeError):raise TaskError('invalid_task_sync_storage') from None
        if type(value)!=dict or value.get('schemaVersion')!=1 or any(type(value.get(k))!=dict for k in ('tasks','outbox','receipts')):raise TaskError('invalid_task_sync_storage')
        validate_config(value['config'])
        # Older documents have only queuedAt. Recover their chronological order
        # once, preserving stored order for indistinguishable legacy timestamps.
        # New entries use an ordinal: JSON key sorting and clock precision must
        # never change the order of commands or unknown-outcome retries.
        items=list(value['outbox'].values())+list(value['receipts'].values())
        assigned=set();legacy=[]
        for item in items:
            if type(item)!=dict:raise TaskError('invalid_task_sync_storage')
            order=item.get('queueOrder')
            if order is None:
                if type(item.get('queuedAt'))!=str:raise TaskError('invalid_task_sync_storage')
                try:queued=datetime.fromisoformat(item['queuedAt']).timestamp()
                except (ValueError,OverflowError,OSError):raise TaskError('invalid_task_sync_storage') from None
                legacy.append((queued,item))
            elif type(order)!=int or order<1 or order in assigned:raise TaskError('invalid_task_sync_storage')
            else:assigned.add(order)
        next_order=value.get('nextQueueOrder',1)
        if type(next_order)!=int or next_order<1:raise TaskError('invalid_task_sync_storage')
        next_order=max(next_order,max(assigned,default=0)+1)
        for _,item in sorted(legacy,key=lambda entry:entry[0]):
            item['queueOrder']=next_order;next_order+=1
        value['nextQueueOrder']=next_order
        return value
    def _write(self,state):
        state['revision']+=1;raw=encode(state)
        if len(raw)>MAX_STORE:raise TaskError('task_sync_capacity',409)
        _atomic(self.path,raw)
    def snapshot(self):
        with locked(self.lock_path):value=copy.deepcopy(self._read())
        current=datetime.now(timezone.utc)
        for task in value['tasks'].values():
            try:age=(current-datetime.fromisoformat(value['lastSuccess'])).total_seconds();fresh=0<=age<=value['config']['staleAfterSeconds']
            except (ValueError,TypeError):fresh=False
            task['freshness']='fresh' if fresh else 'stale' if value['lastSuccess'] else 'unknown'
        return value
    def configure(self,config,revision):
        config=validate_config(config)
        with locked(self.lock_path):
            state=self._read()
            if revision!=state['revision']:raise TaskError('task_settings_conflict',409)
            identity=lambda c:(c['transport'],c['endpoint'],c['profile'],c['sourceNamespace'],c['taskIds'])
            if identity(config)!=identity(state['config']):
                if state['outbox'] or state['tasks']:raise TaskError('task_source_change_requires_separate_profile',409)
            state['config']=config;state['failure']=None;self._write(state)
        if config['enabled']:self.start()
        return self.snapshot()
    def enqueue(self,operation_id,command,args):
        if command not in COMMAND_SCOPE or command in ('get','snapshot','operation'):raise TaskError('invalid_queued_command')
        if not isinstance(operation_id,str) or not __import__('re').fullmatch('[A-Za-z0-9_-]{8,100}',operation_id) or type(args)!=dict:raise TaskError('invalid_task_operation')
        request={'operationId':operation_id,'command':command,'arguments':copy.deepcopy(args)}
        digest=hashlib.sha256(encode(request)).hexdigest()
        with locked(self.lock_path):
            state=self._read();authorize(state['config'],command,args)
            old=state['outbox'].get(operation_id) or state['receipts'].get(operation_id)
            if old:
                if old['digest']!=digest:raise TaskError('operation_payload_conflict',409)
                return copy.deepcopy(old)
            if len(state['outbox'])>=500 or len(state['receipts'])>=5000:raise TaskError('task_sync_capacity',409)
            item={'request':request,'digest':digest,'state':'pending','queuedAt':now(),'queueOrder':state['nextQueueOrder'],'conflict':None}
            state['nextQueueOrder']+=1
            # A draft lives atomically with its immutable outbox request. Confirmed fields stay separate.
            state['outbox'][operation_id]=item;self._write(state)
        return copy.deepcopy(item)
    def resolve(self,operation_id,revision):
        # Retire a conflicted draft explicitly; the original receipt/conflict remains in history.
        with locked(self.lock_path):
            state=self._read()
            if state['revision']!=revision:raise TaskError('task_settings_conflict',409)
            item=state['outbox'].get(operation_id)
            if not item or item['state'] not in ('conflict','rejected'):raise TaskError('task_conflict_not_found',404)
            state['receipts'][operation_id]={**item,'state':'resolved'};del state['outbox'][operation_id];self._write(state)
        return self.snapshot()
    def exchange(self):
        if not self.exchange_lock.acquire(False):return self.snapshot()
        try:
            # One exchange owns the profile across processes; enqueue/read remain independently available.
            with locked(self.path.with_suffix('.exchange.lock')):return self._exchange()
        except TaskError as error:
            if error.code=='task_sync_busy':return self.snapshot()
            raise
        finally:self.exchange_lock.release()
    def _check_connection(self,config):
        with locked(self.lock_path):
            live=self._read()
            if not live['config']['enabled'] or live['config']!=config:raise TaskError('task_connection_changed',409)
            return live
    def _exchange(self):
        with locked(self.lock_path):
            state=self._read();config=copy.deepcopy(state['config']);state['lastAttempt']=now();self._write(state)
        if not config['enabled']:return self.snapshot()
        client=self.factory(config)
        try:
            # Process one pending edit per existing task per exchange; do not silently chain stale edits.
            seen=set()
            for op,item in sorted(state['outbox'].items(),key=lambda entry:entry[1]['queueOrder']):
                if item['state']!='pending':continue
                request=item['request'];args=request['arguments'];task_id=args.get('taskId')
                if task_id is not None and task_id in seen:continue
                seen.add(task_id)
                live=self._check_connection(config)
                pending=live['outbox'].get(op)
                if not pending or pending['state']!='pending' or pending['digest']!=item['digest']:raise TaskError('task_outbox_changed',409)
                try:authorize(live['config'],request['command'],args)
                except TaskError as error:
                    # Revoking local permission must retain the immutable draft,
                    # while read-only exchanges can still refresh projections.
                    if error.status==403:continue
                    raise
                try:receipt=client.call(op,request['command'],args)
                except TaskError as error:
                    if error.status in (400,403,404,409):
                        with locked(self.lock_path):
                            live=self._read();pending=live['outbox'].get(op)
                            if pending and pending['digest']==item['digest']:
                                pending.update(state='conflict' if error.status==409 else 'rejected',conflict={'code':error.code,'current':error.current});self._write(live)
                        continue
                    raise
                if receipt.get('operationId')!=op or receipt.get('acknowledged') is not True:raise TaskError('unconfirmed_task_receipt')
                with locked(self.lock_path):
                    live=self._read();pending=live['outbox'].get(op)
                    if not pending or pending['digest']!=item['digest']:raise TaskError('task_outbox_changed',409)
                    task=receipt.get('task')
                    if not isinstance(task,dict):raise TaskError('invalid_task_receipt')
                    if task.get('deleted') is True:live['tasks'].pop(task['id'],None)
                    else:
                        ns=task.get('binding',{}).get('sourceNamespace')
                        if live['config']['sourceNamespace'] and ns!=live['config']['sourceNamespace']:raise TaskError('task_namespace_changed',409)
                        confirmed=validate_task(task,ns);live['config']['sourceNamespace']=ns
                        config['sourceNamespace']=ns;client.config['sourceNamespace']=ns
                        prior=live['tasks'].get(task['id'])
                        if prior is None or prior['version']<task['version']:live['tasks'][task['id']]=confirmed
                    live['receipts'][op]={**pending,'state':'acknowledged','receipt':receipt};del live['outbox'][op];self._write(live)
            self._check_connection(config)
            snapshot=client.call('snapshot-'+uuid.uuid4().hex,'snapshot',{})
            ns=snapshot.get('sourceNamespace')
            if snapshot.get('schemaVersion')!=1 or snapshot.get('complete') is not True or type(snapshot.get('tasks'))!=list or type(snapshot.get('tombstones'))!=list:raise TaskError('incomplete_task_snapshot')
            tasks={}
            for row in snapshot['tasks']:
                task=validate_task(row,ns)
                if task['id'] in tasks:raise TaskError('duplicate_shared_task')
                tasks[task['id']]=task
            for tomb in snapshot['tombstones']:
                from work_exchange import validate_binding
                b=validate_binding(tomb['binding'])
                if b['sourceNamespace']!=ns or b['sourceId'] in tasks:raise TaskError('conflicting_task_tombstone',409)
            with locked(self.lock_path):
                live=self._read()
                if live['config']!=config:raise TaskError('task_connection_changed',409)
                if config['sourceNamespace'] and ns!=config['sourceNamespace']:raise TaskError('task_namespace_changed',409)
                live['config']['sourceNamespace']=ns;live['tasks']=tasks;live['lastSuccess']=now();live['failure']=None;self._write(live)
        except Exception as error:
            category=error.code if isinstance(error,TaskError) else 'task_exchange_failed'
            with locked(self.lock_path):
                live=self._read();live['failure']={'code':category,'at':now()};self._write(live)
        return self.snapshot()
    def start(self):
        if self.worker:return
        if not self.path.exists() or not self._read()['config']['enabled']:return
        def loop():
            while not self.stop.wait(10):
                try:
                    with locked(self.lock_path):enabled=self._read()['config']['enabled']
                    if enabled:self.exchange()
                except Exception:pass # Failure is persisted by exchange; never log payloads/secrets.
        self.worker=threading.Thread(target=loop,daemon=True,name='task-sync');self.worker.start()
