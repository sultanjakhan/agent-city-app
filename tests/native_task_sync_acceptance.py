"""Explicit synthetic runtime acceptance: real Cicada pipe + owned City backend.

Run manually with freshly built --cicada and --client binaries and an absent
--root outside application/production storage. Opens no owner window.
"""
import argparse
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from task_connection import TaskConnection,default_config,encode
from task_sync import TaskSync
from tools.agent_mcp import Bridge,NativeTaskError
from test_task_sync import report

class CityBackend:
    def __init__(self,config,executable=None):
        self.sequence=0
        command=[str(executable.resolve())] if executable else [sys.executable,'desktop_backend.py']
        self.process=subprocess.Popen(command+['--config',str(config),'--runtime','local-only'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=subprocess.CREATE_NO_WINDOW)
        ready=json.loads(self.process.stdout.readline());assert ready['kind']=='ready' and ready['localOnly'] is True
    def rpc(self,action,request=None):
        self.sequence+=1;value={'version':1,'id':self.sequence,'action':action,'draftsClosed':action=='stop'}
        if request is not None:value['request']=request
        self.process.stdin.write(encode(value)+b'\n');self.process.stdin.flush();reply=json.loads(self.process.stdout.readline());assert reply.get('ok') is True,reply
        result=reply['result'];assert not result.get('isError'),result;return result
    def call(self,method,path,body=None):return self.rpc('agent-request',{'method':method,'path':path,'body':body})
    def close(self):
        try:self.rpc('stop');self.process.wait(timeout=35)
        finally:
            self.process.stdin.close();self.process.stdout.close();self.process.stderr.close()

class CityNativeHost:
    """Exercise native framing without displaying or touching an owner window."""
    def __init__(self,config,executable,client,root):
        import pywintypes,win32con,win32file,win32job,win32process,win32service,uuid
        self.desktop_name='CityTaskQA-'+uuid.uuid4().hex
        self.desktop=win32service.CreateDesktop(self.desktop_name,0,win32con.GENERIC_ALL,None)
        self.job=win32job.CreateJobObject(None,'');self.handles=[]
        limits=win32job.QueryInformationJobObject(self.job,win32job.JobObjectExtendedLimitInformation)
        limits['BasicLimitInformation']['LimitFlags']|=win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        win32job.SetInformationJobObject(self.job,win32job.JobObjectExtendedLimitInformation,limits)
        try:
            attrs=pywintypes.SECURITY_ATTRIBUTES();attrs.bInheritHandle=True
            log=win32file.CreateFile(str(root/'city-host.log'),win32con.GENERIC_WRITE,win32con.FILE_SHARE_READ,attrs,win32con.CREATE_ALWAYS,0,None)
            inp=win32file.CreateFile('NUL',win32con.GENERIC_READ,win32con.FILE_SHARE_READ|win32con.FILE_SHARE_WRITE,attrs,win32con.OPEN_EXISTING,0,None)
            try:
                startup=win32process.STARTUPINFO();startup.lpDesktop='WinSta0\\'+self.desktop_name
                startup.dwFlags=win32con.STARTF_USESHOWWINDOW|win32con.STARTF_USESTDHANDLES;startup.wShowWindow=win32con.SW_SHOWNOACTIVATE
                startup.hStdOutput=startup.hStdError=log;startup.hStdInput=inp
                env={k:v for k,v in os.environ.items() if not k.startswith('AGENT_CITY_') and not k.endswith('_API_KEY')}
                command=subprocess.list2cmdline([str(executable.resolve()),'--background','--local-only','--config',str(config)])
                process,thread,self.pid,_=win32process.CreateProcess(str(executable.resolve()),command,None,None,True,win32con.CREATE_SUSPENDED|win32con.CREATE_UNICODE_ENVIRONMENT|win32con.CREATE_NO_WINDOW,env,str(executable.parent),startup)
                self.handles.extend([process,thread]);self.process=process
                win32job.AssignProcessToJobObject(self.job,process);win32process.ResumeThread(thread)
            finally:log.Close();inp.Close()
            self.bridge=Bridge('agent-city',str(config),str(client.resolve()));deadline=time.monotonic()+45
            while True:
                try:self.call('GET','/api/task-sync');break
                except Exception:
                    assert win32process.GetExitCodeProcess(process)==win32con.STILL_ACTIVE,'isolated City host exited'
                    assert time.monotonic()<deadline,'isolated City command endpoint unavailable'
                    time.sleep(.2)
        except BaseException:self.dispose();raise
    def call(self,method,path,body=None):
        return self.bridge.call({'method':method,'path':path,'body':body})
    def dispose(self):
        import win32job
        win32job.TerminateJobObject(self.job,0)
        for handle in self.handles:handle.Close()
        self.job.Close();self.desktop.CloseDesktop()
    def close(self):
        import win32con,win32event,win32gui,win32process
        try:
            windows=[int(w) for w in self.desktop.EnumDesktopWindows() if win32process.GetWindowThreadProcessId(int(w))[1]==self.pid and win32gui.GetWindowText(int(w))=='Agent City']
            assert len(windows)==1
            assert win32gui.GetWindowPlacement(windows[0])[1]==win32con.SW_SHOWMINIMIZED
            win32gui.PostMessage(windows[0],win32con.WM_CLOSE,0,0)
            assert win32event.WaitForSingleObject(self.process,35000)==win32con.WAIT_OBJECT_0,'isolated clean City close blocked'
            assert win32process.GetExitCodeProcess(self.process)==0
        finally:self.dispose()

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,required=True);p.add_argument('--cicada',type=Path,required=True);p.add_argument('--client',type=Path,required=True)
    city_mode=p.add_mutually_exclusive_group();city_mode.add_argument('--city-backend',type=Path);city_mode.add_argument('--city-native',type=Path);a=p.parse_args()
    root=a.root.resolve();assert not root.exists(),'use a new isolated root'
    for name in ('APPDATA','LOCALAPPDATA'):
        if os.environ.get(name):assert not root.is_relative_to(Path(os.environ[name]).resolve()),'production storage is forbidden'
    root.mkdir(parents=True)
    cicada=root/'cicada';cicada.mkdir();(cicada/'cicada-isolated-test.json').write_bytes(encode({'schemaVersion':1,'application':'app.hanni.mvp','purpose':'isolated-release-test'}))
    panel=root/'city-panel';data=root/'city-data';skills=root/'skills';repos=root/'repos'
    for path in (panel,data,skills,repos,root/'credentials',root/'codex'):path.mkdir()
    config=root/'city-storage.json';config.write_bytes(encode({'schemaVersion':1,'dataRoot':str(data),'panelDirectory':str(panel),'skillsDirectory':str(skills),'credentialsDirectory':str(root/'credentials'),'codexHome':str(root/'codex'),'repositoryRoots':[str(repos)],'cicadaSources':[],'skillInventoryRoots':[{'origin':'worktree','path':str(skills)}]}))
    connection={**default_config(),'enabled':True,'transport':'pipe','endpoint':'','tokenEnv':'','profile':str(cicada),'client':str(a.client.absolute()),'scopes':['tasks:read','tasks:write','tasks:review','tasks:execute']}
    setup=TaskSync(panel);setup.stop.set();setup.configure(connection,0)
    foreground=ctypes.windll.user32.GetForegroundWindow();env=dict(os.environ);env.pop('HANNI_MVP_DATA_DIR',None);env.pop('WEBVIEW2_USER_DATA_FOLDER',None)
    native=None;city=None
    native_log=(root/'native.stderr.log').open('wb')
    def launch():return subprocess.Popen([str(a.cicada.absolute()),'--isolated-test-root',str(cicada),'--background'],env=env,stdout=subprocess.DEVNULL,stderr=native_log,creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        native=launch();client=TaskConnection(connection)
        for attempt in range(8):
            try:client.call('runtime-ready-001','snapshot',{});break
            except Exception:
                assert native.poll() is None,'isolated Cicada exited';time.sleep(.1)
        else:raise AssertionError('Cicada private endpoint unavailable')
        city=CityNativeHost(config,a.city_native,a.client,root) if a.city_native else CityBackend(config,a.city_backend)
        def queued(op,command,args):
            body={'version':1,'operationId':op,'command':command,'arguments':args}
            drafts=root/'requests';drafts.mkdir(exist_ok=True);request_file=drafts/(op+'.json');raw=encode(body)
            if request_file.exists():assert request_file.read_bytes()==raw,'retry payload changed'
            else:request_file.write_bytes(raw)
            value=city.call('POST','/api/task-sync/queue',body);assert value['state'] in ('pending','acknowledged');return value
        def exchange():
            before=city.call('GET','/api/task-sync')['lastSuccess'];until=time.monotonic()+60
            while True:
                state=city.call('POST','/api/task-sync/exchange',{})
                pending=any(item['state']=='pending' for item in state['outbox'].values())
                if state['failure'] is None and state['lastSuccess']!=before and not pending:return state
                if state['failure'] and state['failure']['code'] not in ('task_connection_unavailable','task_sync_busy'):raise AssertionError(state['failure'])
                assert time.monotonic()<until,'exchange did not acknowledge queued operations after reconnect'
                time.sleep(.2)
        queued('runtime-create-001','create',{'title':'Synthetic runtime task','content':'Synthetic preserved description'});state=exchange();assert len(state['tasks'])==1
        t=next(iter(state['tasks'].values()));id=t['id'];assert t['binding']['sourceId']==id
        queued('runtime-create-001','create',{'title':'Synthetic runtime task','content':'Synthetic preserved description'});assert len(exchange()['tasks'])==1
        queued('runtime-stage-001','patch',{'taskId':id,'expectedVersion':1,'patch':{'stage':'requirements','process':'system-analysis'}});t=exchange()['tasks'][id]
        assert client.call('runtime-read-001','get',{'taskId':id})['stage']=='requirements'
        bridge=Bridge('cicada',str(cicada),str(a.client.absolute()))
        bridge.call({'version':1,'operation_id':'runtime-begin-001','action':'begin','body':{'title':'Unused','content':'','taskId':id,'expectedVersion':2,'projects':[],'report':report('runtime-run-001','running',1)}})
        bridge.call({'version':1,'operation_id':'runtime-done-001','action':'report','body':{'taskId':id,'expectedVersion':2,'report':report('runtime-run-001','done',2)}})
        # Exactly the native 8000 UTF-8-byte result limit; quotes/backslashes
        # exercise JSON expansion without changing the domain content limit.
        result_text='Р'*3500+(chr(92)+chr(34))*500
        assert len(result_text.encode('utf-8'))==8000
        result_args={'taskId':id,'expectedVersion':2,'runId':'runtime-run-001','content':result_text}
        queued('runtime-result-001','submit_result',result_args)
        t=exchange()['tasks'][id];assert t['review']['state']=='awaiting_review'
        assert t['results'][0]['content']==result_text
        queued('runtime-result-001','submit_result',result_args)
        t=exchange()['tasks'][id];assert len(t['results'])==1 and t['version']==3
        queued('runtime-rework-001','review',{'taskId':id,'expectedVersion':3,'resultVersion':1,'decision':'rework','comment':'Synthetic preserved feedback'});assert exchange()['tasks'][id]['review']['state']=='awaiting_dispatch'
        queued('runtime-ack-001','acknowledge',{'taskId':id,'expectedVersion':4,'intentId':'runtime-rework-001','report':report('runtime-run-002','running',1)});assert exchange()['tasks'][id]['review']['state']=='running'
        bridge.call({'version':1,'operation_id':'runtime-foreign-begin-001','action':'begin','body':{'title':'Unused','content':'','taskId':id,'expectedVersion':5,'projects':[],'report':report('runtime-foreign-run-001','running',1)}})
        bridge.call({'version':1,'operation_id':'runtime-foreign-done-001','action':'report','body':{'taskId':id,'expectedVersion':5,'report':report('runtime-foreign-run-001','done',2)}})
        queued('runtime-foreign-result-001','submit_result',{'taskId':id,'expectedVersion':5,'runId':'runtime-foreign-run-001','content':'Foreign draft must not finish this rework'})
        state=exchange();foreign=state['outbox']['runtime-foreign-result-001'];t=state['tasks'][id]
        assert foreign['state']=='conflict' and foreign['conflict']['code']=='execution_run_mismatch'
        assert t['review']['state']=='running' and t['review']['intentId']=='runtime-rework-001' and len(t['results'])==1 and t['version']==5
        bridge.call({'version':1,'operation_id':'runtime-done-002','action':'report','body':{'taskId':id,'expectedVersion':5,'report':report('runtime-run-002','done',2)}})
        escaped_result=chr(92)*4000+chr(34)*4000
        assert len(escaped_result.encode('utf-8'))==8000
        queued('runtime-result-002','submit_result',{'taskId':id,'expectedVersion':5,'runId':'runtime-run-002','content':escaped_result});exchange()
        queued('runtime-accept-002','review',{'taskId':id,'expectedVersion':6,'resultVersion':2,'decision':'accept'});t=exchange()['tasks'][id];assert t['completed'] and len(t['results'])==2 and not t['humanTimerActive']
        assert t['results'][0]['content']==result_text and t['results'][1]['content']==escaped_result
        native.terminate();native.wait(timeout=10);native=None
        queued('runtime-offline-001','comment',{'taskId':id,'expectedVersion':7,'comment':'Offline survives reconnect'})
        # exchange() can return the last snapshot while the periodic worker
        # owns an exchange. Observe its unavailable receipt, not a busy read.
        until=time.monotonic()+45
        while True:
            state=city.call('POST','/api/task-sync/exchange',{})
            assert 'runtime-offline-001' in state['outbox'],'offline draft was lost'
            if state['failure']:break
            assert time.monotonic()<until,'offline transport failure never became observable'
            time.sleep(.2)
        native=launch()
        until=time.monotonic()+45
        while True:
            try:client.call('runtime-reconnected-001','snapshot',{});break
            except Exception:
                assert native.poll() is None,'reconnected isolated Cicada exited'
                assert time.monotonic()<until,'reconnected Cicada did not acknowledge readiness'
                time.sleep(.2)
        state=exchange();assert 'runtime-offline-001' not in state['outbox'];assert state['tasks'][id]['comments'][0]['content']=='Offline survives reconnect'
        queued('runtime-conflict-001','comment',{'taskId':id,'expectedVersion':7,'comment':'Stale retained draft'});state=exchange();assert state['outbox']['runtime-conflict-001']['state']=='conflict'
        # Frozen CLI startup can cross a background exchange. Re-read after a
        # rejected retirement; never suppress a failure on the same revision.
        for conflict_id in ('runtime-conflict-001','runtime-foreign-result-001'):
            for attempt in range(3):
                current=city.call('GET','/api/task-sync')
                if conflict_id not in current['outbox']:break
                try:city.call('POST','/api/task-sync/resolve',{'operationId':conflict_id,'revision':current['revision']})
                except (AssertionError,NativeTaskError):
                    after=city.call('GET','/api/task-sync')
                    assert after['revision']!=current['revision'],'retirement failed without concurrent exchange'
                    continue
                break
        final=city.call('GET','/api/task-sync')
        assert not any(op in final['outbox'] for op in ('runtime-conflict-001','runtime-foreign-result-001'))
        assert final['receipts']['runtime-conflict-001']['state']=='resolved'
        assert final['receipts']['runtime-conflict-001']['request']['arguments']['comment']=='Stale retained draft'
        assert final['receipts']['runtime-foreign-result-001']['request']['arguments']['content']=='Foreign draft must not finish this rework'
        closing=city;city=None;closing.close()
        assert foreground==ctypes.windll.user32.GetForegroundWindow(),'foreground changed during background-only acceptance'
        result={'syntheticOnly':True,'nativeCicadaPipe':True,'ownedAgentCityBackend':True,'nativeCityCommandPath':a.city_native is not None,'inactiveDesktop':a.city_native is not None,'sameNativeId':id,'stages':True,'resultsReviewRework':True,'fullLimitUtf8ResultPreserved':True,'fullLimitEscapedResultPreserved':True,'foreignRunCannotFinishRework':True,'retryNoDuplicates':True,'disconnectReconnect':True,'revisionConflict':True,'foregroundUnchanged':True,'installed':False}
        (root/'acceptance.json').write_bytes(encode(result));print(json.dumps(result))
    finally:
        if city:city.close()
        if native and native.poll() is None:native.terminate();native.wait(timeout=10)
        native_log.close()
if __name__=='__main__':main()
