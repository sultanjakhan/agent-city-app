"""Reusable command contract and transport. No task store, window or model launch."""
from __future__ import annotations
import copy
import json
import os
import re
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit

SCOPES = {'tasks:read','tasks:write','tasks:review','tasks:execute'}
COMMAND_SCOPE = {**{c:'tasks:read' for c in ('snapshot','get','operation')},
                 **{c:'tasks:write' for c in ('create','share','patch','comment','archive')},
                 'review':'tasks:review','submit_result':'tasks:execute','acknowledge':'tasks:execute'}
LIMIT = 1024 * 1024
class TaskError(ValueError):
    def __init__(self, code, status=400, current=None):
        self.code,self.status,self.current=code,status,copy.deepcopy(current)
        super().__init__(code)
class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs): return None
def strict(raw):
    def unique(pairs):
        obj={}
        for key,value in pairs:
            if key in obj:raise TaskError('invalid_task_response')
            obj[key]=value
        return obj
    if len(raw)>LIMIT:raise TaskError('task_response_capacity',409)
    try:return json.loads(raw,object_pairs_hook=unique,parse_constant=lambda _:(_ for _ in ()).throw(ValueError()))
    except (ValueError,UnicodeError):raise TaskError('invalid_task_response') from None
def encode(obj):return json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def validate_config(value):
    fields={'enabled','transport','endpoint','profile','client','tokenEnv','sourceNamespace','scopes','taskIds','staleAfterSeconds'}
    if type(value)!=dict or set(value)!=fields or type(value['enabled'])!=bool:raise TaskError('invalid_task_connection')
    if value['transport'] not in ('pipe','http'):raise TaskError('invalid_task_transport')
    if type(value['scopes'])!=list or not set(value['scopes'])<=SCOPES or 'tasks:read' not in value['scopes']:raise TaskError('invalid_task_scopes')
    if value['taskIds'] is not None and (type(value['taskIds'])!=list or len(value['taskIds'])>500 or any(not isinstance(s,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',s) for s in value['taskIds'])):raise TaskError('invalid_task_allowlist')
    if type(value['staleAfterSeconds'])!=int or not 30<=value['staleAfterSeconds']<=604800:raise TaskError('invalid_task_freshness')
    ns=value['sourceNamespace']
    if ns is not None and (type(ns)!=str or not re.fullmatch(r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}',ns)):raise TaskError('invalid_task_namespace')
    for field in ('endpoint','profile','client','tokenEnv'):
        if type(value[field])!=str or len(value[field])>4096 or any(ord(c)<32 for c in value[field]):raise TaskError('invalid_task_connection')
    if value['transport']=='pipe':
        if value['endpoint'] or value['tokenEnv']:raise TaskError('invalid_pipe_authentication')
        if not os.path.isabs(value['profile']) or not os.path.isabs(value['client']):raise TaskError('absolute_task_paths_required')
    else:
        try:parts=urlsplit(value['endpoint']);port=parts.port
        except ValueError:raise TaskError('invalid_task_endpoint') from None
        if not parts.hostname or parts.username or parts.password or parts.query or parts.fragment or parts.scheme not in ('http','https'):
            raise TaskError('invalid_task_endpoint')
        if parts.scheme=='http' and parts.hostname not in ('127.0.0.1','localhost','::1'):raise TaskError('tls_required')
        if value['profile'] or value['client'] or not re.fullmatch(r'[A-Z][A-Z0-9_]{2,80}',value['tokenEnv']):raise TaskError('invalid_http_authentication')
    result=copy.deepcopy(value);result['scopes']=sorted(set(result['scopes']))
    if result['taskIds'] is not None:result['taskIds']=sorted(set(result['taskIds']))
    return result
def default_config():
    return {'enabled':False,'transport':'http','endpoint':'http://127.0.0.1:47840/commands','profile':'','client':'',
            'tokenEnv':'CICADA_TASK_TOKEN','sourceNamespace':None,'scopes':['tasks:read'],'taskIds':None,'staleAfterSeconds':300}
def authorize(config,command,args):
    required=COMMAND_SCOPE.get(command)
    if required is None or required not in config['scopes']:raise TaskError('task_scope_denied',403)
    if config['taskIds'] is not None:
        if command=='create':raise TaskError('task_scope_denied',403)
        if 'taskId' in args and args['taskId'] not in config['taskIds']:raise TaskError('task_scope_denied',403)
        if command=='operation':raise TaskError('operation_scope_requires_task_identity',403)
class TaskConnection:
    def __init__(self,config,bridge=None):self.config=validate_config(config);self.bridge=bridge
    def call(self,operation_id,command,args):
        authorize(self.config,command,args)
        # Verify a pinned deployment before any write, rather than noticing a mismatch after mutation.
        if command not in ('snapshot','get','operation') and self.config['sourceNamespace']:
            self.call('verify-'+__import__('uuid').uuid4().hex,'snapshot',{})
        if self.config['transport']=='pipe':
            if self.bridge is None:
                from tools.agent_mcp import Bridge
                self.bridge=Bridge('cicada',self.config['profile'],self.config['client'])
            try:value=self.bridge.call({'version':1,'operation_id':operation_id,'action':'task-command','body':{'command':command,'arguments':args}})
            except Exception as error:
                value=getattr(error,'value',None)
                if not isinstance(value,dict) or value.get('isError') is not True:raise TaskError('task_connection_unavailable',503) from None
        else:
            token=os.environ.get(self.config['tokenEnv'],'')
            if not re.fullmatch(r'[A-Za-z0-9_-]{32,512}',token):raise TaskError('task_authentication_missing',401)
            request=Request(self.config['endpoint'],data=encode({'version':1,'operationId':operation_id,'command':command,'arguments':args}),
                            headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'},method='POST')
            try:
                with build_opener(ProxyHandler({}),NoRedirect()).open(request,timeout=15) as response:value=strict(response.read(LIMIT+1))
            except HTTPError as e:
                # Only a structurally validated bounded domain response may retain conflict state.
                if e.code in (400,403,404,409):
                    try:value=strict(e.read(LIMIT+1))
                    except Exception:raise TaskError('remote_task_command_rejected',e.code) from None
                    finally:e.close()
                else:
                    e.close()
                    raise TaskError({401:'task_authentication_rejected',403:'task_scope_denied',429:'task_rate_limit'}.get(e.code,'task_transport_failure'),e.code) from None
            except (OSError,URLError):raise TaskError('task_connection_unavailable',503) from None
        if type(value)!=dict:raise TaskError('invalid_task_response')
        if value.get('isError'):
            code=value.get('code','task_command_failed')
            if not isinstance(code,str) or not re.fullmatch('[a-z_]{1,100}',code):code='task_command_failed'
            raise TaskError(code,value.get('status',400),value.get('current'))
        if command=='snapshot':
            if self.config['sourceNamespace'] and value.get('sourceNamespace')!=self.config['sourceNamespace']:raise TaskError('task_namespace_changed',409)
            if self.config['taskIds'] is not None:
                ids=set(self.config['taskIds']);value=copy.deepcopy(value)
                value['tasks']=[t for t in value.get('tasks',[]) if t.get('id') in ids]
                value['tombstones']=[t for t in value.get('tombstones',[]) if t.get('binding',{}).get('sourceId') in ids]
        task=value.get('task',value if command=='get' else None)
        if isinstance(task,dict) and task.get('binding') and self.config['sourceNamespace'] and task['binding'].get('sourceNamespace')!=self.config['sourceNamespace']:
            raise TaskError('task_namespace_changed',409)
        return value
