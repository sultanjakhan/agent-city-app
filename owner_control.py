"""Bounded RPC only over the broker's inherited anonymous stdin/stdout pipes."""
import json
import hashlib
import os
import re
import stat
import sys
import threading
from pathlib import Path
MAX_MESSAGE=16384

def start_control(server,instance):
    if not isinstance(instance,str) or not re.fullmatch('[a-f0-9]{32}',instance) or not stat.S_ISFIFO(os.fstat(sys.stdin.fileno()).st_mode):
        raise ValueError('private owner channel required')
    def send(value):
        raw=json.dumps(value,separators=(',',':'),allow_nan=False).encode()+b'\n'
        if len(raw)>MAX_MESSAGE:raise ValueError('control response limit')
        sys.stdout.buffer.write(raw);sys.stdout.buffer.flush()
    def loop():
        send({'version':1,'kind':'ready','instance':instance,'pid':os.getpid(),'appRoot':str(Path(__file__).resolve().parent),'port':server.server_port,'ownerHost':server.owner_host,'localOnly':server.store.local_only})
        sequence=0;last_digest=None;last_reply=None
        try:
            while True:
                raw=sys.stdin.buffer.readline(MAX_MESSAGE+1)
                if not raw:break
                ident=None
                try:
                    if len(raw)>MAX_MESSAGE or not raw.endswith(b'\n'):raise ValueError()
                    message=json.loads(raw)
                    if not isinstance(message,dict) or set(message)!={'version','id','sequence','action','args'} or message['version']!=1 or not isinstance(message['id'],str) or not re.fullmatch('[a-f0-9]{32}',message['id']) or not isinstance(message['args'],dict) or type(message['sequence']) is not int:raise ValueError()
                    ident=message['id'];digest=hashlib.sha256(raw).digest()
                    if message['sequence']==sequence and digest==last_digest and last_reply is not None:send(last_reply);continue
                    if message['sequence']!=sequence+1:raise ValueError()
                    sequence=message['sequence'];last_digest=digest;last_reply=None
                    action=message['action'];args=message['args'];result={}
                    if action=='bootstrap' and not args:result={'capability':server.owner_sessions.issue_bootstrap()}
                    elif action=='revoke' and not args:server.owner_sessions.revoke_all();result={'revoked':True}
                    elif action=='delegate' and set(args)=={'method','path','body'}:result={'grant':server.owner_sessions.issue_grant(args['method'],args['path'],args['body'])}
                    elif action=='restart-ready' and not args:
                        with server.owner_write_condition,server.store.lock:
                            if server.owner_active_writes or server.store.busy or server.store.batch.get('running'):raise ValueError()
                            server.owner_mutation_fenced=True
                        result={'quiescent':True,'dataRoot':str(server.store.directory),'localOnly':server.store.local_only}
                    elif action=='resume' and not args:
                        with server.owner_write_condition:server.owner_mutation_fenced=False
                        result={'resumed':True}
                    elif action=='shutdown' and not args:
                        if not server.owner_mutation_fenced:raise ValueError()
                        server.owner_sessions.revoke_all();send({'version':1,'id':ident,'ok':True,'result':{'stopping':True}});server.shutdown();return
                    else:raise ValueError()
                    last_reply={'version':1,'id':ident,'ok':True,'result':result};send(last_reply)
                except (ValueError,TypeError,KeyError,OSError):
                    reply={'version':1,'id':ident,'ok':False,'error':'owner_control_rejected'}
                    if last_digest==hashlib.sha256(raw).digest():last_reply=reply
                    send(reply)
        finally:
            server.owner_sessions.revoke_all()
            with server.owner_write_condition:
                server.owner_mutation_fenced=True
                while server.owner_active_writes:server.owner_write_condition.wait(timeout=.25)
            server.shutdown()
    threading.Thread(target=loop,daemon=True,name='private-owner-control').start()
