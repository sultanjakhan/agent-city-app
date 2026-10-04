"""Optional stateless API gateway for one configured app. No shared task database.

Bind loopback by default. A remote bind requires an explicitly configured TLS
certificate/key. Grants hold token environment-variable names, never tokens.
"""
import argparse
import copy
import hmac
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import ssl
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from task_connection import TaskConnection,TaskError,authorize,encode,strict,validate_config,SCOPES
from tools.agent_mcp import Bridge

class Gateway:
    def __init__(self,app,backend,grants,bridge=None):
        self.app=app;self.backend=backend;self.bridge=bridge;self.grants=[]
        for grant in grants:
            if type(grant)!=dict or set(grant)!={'tokenEnv','scopes','taskIds','sourceNamespace'}:raise ValueError('invalid grant')
            if not re.fullmatch('[A-Z][A-Z0-9_]{2,80}',grant['tokenEnv']):raise ValueError('invalid grant')
            token=os.environ.get(grant['tokenEnv'],'')
            if not re.fullmatch('[A-Za-z0-9_-]{32,512}',token):raise ValueError('missing grant credential')
            if type(grant['scopes'])!=list or not set(grant['scopes'])<=SCOPES:raise ValueError('invalid grant')
            config={**backend,**{k:copy.deepcopy(grant[k]) for k in ('scopes','taskIds','sourceNamespace')}}
            validate_config(config);self.grants.append((token,config))
        if not self.grants:raise ValueError('at least one scoped grant required')
    def dispatch(self,authorization,request):
        token=authorization[7:] if isinstance(authorization,str) and authorization.startswith('Bearer ') else ''
        config=next((c for secret,c in self.grants if hmac.compare_digest(token,secret)),None)
        if config is None:raise TaskError('task_authentication_rejected',401)
        if type(request)!=dict or set(request)!={'version','operationId','command','arguments'} or request['version']!=1 or type(request['arguments'])!=dict:raise TaskError('invalid_api_request')
        op=request['operationId'];command=request['command'];args=request['arguments']
        if not isinstance(op,str) or not re.fullmatch('[A-Za-z0-9_-]{8,100}',op):raise TaskError('invalid_task_operation')
        authorize(config,command,args)
        if self.app=='cicada':return TaskConnection(config,self.bridge).call(op,command,args)
        # Agent City is a projection editor: no implicit cross-app transaction.
        bridge=self.bridge or Bridge('agent-city',self.backend['profile'],self.backend['client'])
        value=bridge.call({'method':'GET','path':'/api/task-sync','body':None})
        if config['sourceNamespace'] and value['config']['sourceNamespace']!=config['sourceNamespace']:raise TaskError('task_namespace_changed',409)
        if command=='snapshot':
            tasks=[t for t in value['tasks'].values() if config['taskIds'] is None or t['id'] in config['taskIds']]
            return {'schemaVersion':1,'sourceNamespace':value['config']['sourceNamespace'],'tasks':tasks,'lastSuccess':value['lastSuccess'],'pending':len(value['outbox'])}
        if command in ('get','operation'):raise TaskError('unsupported_projection_command')
        return bridge.call({'method':'POST','path':'/api/task-sync/queue','body':request})
def server_for(gateway,host='127.0.0.1',port=0):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            status=200
            try:
                if self.path!='/commands' or self.headers.get('Content-Type')!='application/json':raise TaskError('invalid_api_route',404)
                count=int(self.headers.get('Content-Length','0'))
                if not 0<count<64*1024:raise TaskError('api_frame_limit',413)
                value=gateway.dispatch(self.headers.get('Authorization'),strict(self.rfile.read(count)))
            except TaskError as e:status=e.status;value={'isError':True,'status':status,'code':e.code,'current':e.current}
            except Exception:status=503;value={'isError':True,'status':503,'code':'application_unavailable_or_outcome_unknown'}
            raw=encode(value)
            if len(raw)>1024*1024:status=409;raw=encode({'isError':True,'status':409,'code':'task_response_capacity'})
            self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
    return ThreadingHTTPServer((host,port),Handler)
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--app',choices=['cicada','agent-city'],required=True);p.add_argument('--backend',type=Path,required=True);p.add_argument('--grants',type=Path,required=True);p.add_argument('--host',default='127.0.0.1');p.add_argument('--port',type=int,required=True);p.add_argument('--certificate',type=Path);p.add_argument('--tls-key',type=Path)
    a=p.parse_args()
    if a.host not in ('127.0.0.1','localhost','::1') and not (a.certificate and a.tls_key):p.error('remote bind requires TLS')
    if bool(a.certificate)!=bool(a.tls_key):p.error('certificate and TLS key required together')
    backend=validate_config(strict(a.backend.read_bytes()))
    if backend['transport']!='pipe':p.error('gateway backend must be the local application pipe')
    gateway=Gateway(a.app,backend,strict(a.grants.read_bytes()));server=server_for(gateway,a.host,a.port)
    if a.certificate:
        context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.minimum_version=ssl.TLSVersion.TLSv1_2;context.load_cert_chain(a.certificate,a.tls_key);server.socket=context.wrap_socket(server.socket,server_side=True)
    try:server.serve_forever()
    finally:server.server_close()
if __name__=='__main__':main()
