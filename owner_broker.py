"""Trusted controller of its own child, with no public grant-discovery service."""
import json
import os
from pathlib import Path
import queue
import secrets
import subprocess
import sys
import threading
import uuid
import time
from owner_transport import write_pipe, remaining, ControlDeadline, spawn_owned
MAX_MESSAGE=16384
RECOVERY_SECONDS=30  # Total revoke/bootstrap plus cold native handoff; not a user preference.

def script_command(root, script, args):
    if script not in {"server.py", "city.py"}:
        raise ValueError("unsupported owned script")
    if getattr(sys, "frozen", False):
        return [sys.executable, "--internal-script", script, *args]
    return [sys.executable, str(Path(root) / script), *args]


class BrokerError(ValueError):pass

class OwnerBroker:
    def __init__(self,root,port,environment,browser_open,*,local_only=True):
        if type(local_only) is not bool:raise ValueError("runtime mode must be explicit boolean")
        self.local_only=local_only
        self.root=Path(root).resolve();self.port=port;self.environment=dict(environment);self.browser_open=browser_open;self.browser_deadline_open=None
        self.child=None;self.epoch=None;self.owner_host=None;self.responses=queue.Queue(maxsize=8);self.rpc_lock=threading.Lock();self.sequence=0;self.channel_failed=False
    def start(self,deadline=None):
        deadline=deadline if deadline is not None else time.monotonic()+15
        remaining(deadline)
        if self.child is not None:raise BrokerError('child already assigned')
        self.epoch=secrets.token_hex(16);self.owner_host='agent-city-'+secrets.token_hex(16)+'.localhost';self.responses=queue.Queue(maxsize=8);self.sequence=0;self.channel_failed=False
        env=dict(self.environment);env.pop('AGENT_CITY_OWNER_BOOTSTRAP',None)
        env.update(AGENT_CITY_OWNER_INSTANCE=self.epoch,AGENT_CITY_OWNER_HOST=self.owner_host)
        flags={'creationflags':subprocess.CREATE_NO_WINDOW} if sys.platform=='win32' else {'start_new_session':True}
        # Diagnostics are discarded; stdout is exclusively the inherited private channel.
        self.child=spawn_owned(script_command(self.root,'server.py',['--port',str(self.port),'--no-refresh','--owner-control-stdin']+(['--local-only'] if self.local_only else [])),deadline,cwd=self.root,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,bufsize=0,**flags)
        child=self.child;response_queue=self.responses
        def read():
            try:
                while True:
                    raw=child.stdout.readline(MAX_MESSAGE+1)
                    if not raw:break
                    if len(raw)>MAX_MESSAGE or not raw.endswith(b'\n'):break
                    value=json.loads(raw)
                    if not isinstance(value,dict):break
                    response_queue.put_nowait(value)
            except (OSError,ValueError,queue.Full):pass
            finally:
                try:response_queue.put_nowait(None)
                except queue.Full:pass
        threading.Thread(target=read,daemon=True,name='owner-child-replies').start()
        try:ready=self.responses.get(timeout=remaining(deadline))
        except (queue.Empty,ControlDeadline):ready=None
        if not isinstance(ready,dict) or ready.get('version')!=1 or ready.get('kind')!='ready' or ready.get('instance')!=self.epoch or ready.get('pid')!=child.pid or ready.get('appRoot')!=str(self.root) or ready.get('ownerHost')!=self.owner_host or type(ready.get('port')) is not int or not 1<=ready['port']<=65535 or (self.port!=0 and ready['port']!=self.port) or ready.get('localOnly') is not self.local_only:
            self._terminate_own_child(deadline=deadline);raise BrokerError('owned child readiness failed')
        self.port=ready['port']
        return {'instance':self.epoch,'pid':child.pid,'port':self.port,'localOnly':self.local_only}
    def rpc(self,action,args=None,deadline=None):
        deadline=deadline if deadline is not None else time.monotonic()+10
        if not self.rpc_lock.acquire(timeout=remaining(deadline)):raise BrokerError("owner control busy deadline")
        try:
            if self.channel_failed or not self.child or self.child.poll() is not None:raise BrokerError('owned child unavailable')
            ident=uuid.uuid4().hex;next_sequence=self.sequence+1;message={'version':1,'id':ident,'sequence':next_sequence,'action':action,'args':args or {}}
            raw=json.dumps(message,separators=(',',':'),allow_nan=False).encode()+b'\n'
            if len(raw)>MAX_MESSAGE:raise BrokerError('control message limit')
            try:
                write_pipe(self.child.stdin,raw,deadline);self.sequence=next_sequence;reply=self.responses.get(timeout=remaining(deadline))
            except (OSError,queue.Empty,ControlDeadline):
                self._retire_channel();raise BrokerError('private control unavailable') from None
            if not isinstance(reply,dict) or reply.get('version')!=1 or reply.get('id')!=ident or type(reply.get('ok')) is not bool:
                self._retire_channel();raise BrokerError('private control invalid reply')
            if reply['ok'] is False:raise BrokerError('owner control rejected')
            if not isinstance(reply.get('result'),dict):
                self._retire_channel();raise BrokerError('private control invalid reply')
            remaining(deadline)
            return reply['result']
        except ControlDeadline:
            self._retire_channel();raise BrokerError('private control deadline') from None
        finally:self.rpc_lock.release()
    def _retire_channel(self):
        # Ambiguous delivery cannot be retried as a fresh command. Closing only
        # our inherited pipe lets the child fence/drain writes and revoke on EOF.
        self.channel_failed=True
        try:
            if self.child and self.child.stdin:self.child.stdin.close()
        except OSError:pass
    def recover_browser(self,revoke=True,deadline=None):
        deadline=deadline if deadline is not None else time.monotonic()+RECOVERY_SECONDS
        if revoke:self.rpc('revoke',deadline=deadline)
        capability=self.rpc('bootstrap',deadline=deadline)['capability']
        remaining(deadline)
        # Only the controller hands this URL to its explicit browser callback.
        url='http://'+self.owner_host+':'+str(self.port)+'/#owner-bootstrap='+capability
        if self.browser_deadline_open:self.browser_deadline_open(url,self.epoch,deadline=deadline)
        else:self.browser_open(url,self.epoch)
        remaining(deadline)
        return {'opened':True,'instance':self.epoch}
    def grant(self,method,path,body=None,deadline=None):return self.rpc('delegate',{'method':method,'path':path,'body':body},deadline=deadline)['grant']
    def run_cli(self,method,path,body=None,deadline=None):
        deadline=deadline if deadline is not None else time.monotonic()+20
        grant=self.grant(method,path,body,deadline=deadline)
        payload={'version':1,'port':self.port,'ownerHost':self.owner_host,'method':method,'path':path,'body':body,'grant':grant}
        raw=json.dumps(payload,separators=(',',':'),allow_nan=False).encode()
        flags={'creationflags':subprocess.CREATE_NO_WINDOW} if sys.platform=='win32' else {}
        child=spawn_owned(script_command(self.root,'city.py',['--owner-delegated-stdin']),deadline,cwd=self.root,env=self.environment,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,**flags)
        try:output,error=child.communicate(raw,timeout=remaining(deadline))
        except (subprocess.TimeoutExpired,ControlDeadline):
            child.kill();threading.Thread(target=child.communicate,daemon=True).start();raise BrokerError('owned CLI timed out') from None
        if child.returncode or len(output)>8*1024*1024:raise BrokerError('owned CLI rejected')
        return json.loads(output)
    def restart(self,drafts_closed=False,deadline=None):
        deadline=deadline if deadline is not None else time.monotonic()+30
        if drafts_closed is not True:raise BrokerError('explicit draft closure required')
        status=self.rpc('restart-ready',deadline=deadline)
        if status.get('quiescent') is not True or status.get('localOnly') is not self.local_only:raise BrokerError('restart not quiescent')
        self.rpc('shutdown',deadline=deadline);self.child.wait(timeout=remaining(deadline));self._close_streams();self.child=None
        self.start(deadline=deadline);self.recover_browser(deadline=deadline);return {'restarted':True,'instance':self.epoch}
    def stop(self,drafts_closed=False,deadline=None):
        deadline=deadline if deadline is not None else time.monotonic()+20
        if drafts_closed is not True:raise BrokerError('explicit draft closure required')
        self.rpc('restart-ready',deadline=deadline);self.rpc('shutdown',deadline=deadline);self.child.wait(timeout=remaining(deadline));self._close_streams();self.child=None
    def _close_streams(self):
        for stream in (self.child.stdin,self.child.stdout):
            if stream:stream.close()
    def _terminate_own_child(self,deadline=None):
        # Popen's retained process handle identifies this child, not a discovered PID.
        if self.child and self.child.poll() is None:
            child=self.child;child.terminate()
            if deadline is not None and deadline<=time.monotonic():threading.Thread(target=child.wait,daemon=True).start()
            else:child.wait(timeout=min(10,remaining(deadline)) if deadline is not None else 10)
        if self.child:self._close_streams()
        self.child=None
