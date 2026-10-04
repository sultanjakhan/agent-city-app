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
from tools.agent_mcp import Bridge
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

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,required=True);p.add_argument('--cicada',type=Path,required=True);p.add_argument('--client',type=Path,required=True);p.add_argument('--city-backend',type=Path);a=p.parse_args()
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
        city=CityBackend(config,a.city_backend)
        def queued(op,command,args):
            value=city.call('POST','/api/task-sync/queue',{'version':1,'operationId':op,'command':command,'arguments':args});assert value['state'] in ('pending','acknowledged');return value
        def exchange():
            state=city.call('POST','/api/task-sync/exchange',{});assert state['failure'] is None,state['failure'];return state
        queued('runtime-create-001','create',{'title':'Synthetic runtime task','content':'Synthetic preserved description'});state=exchange();assert len(state['tasks'])==1
        t=next(iter(state['tasks'].values()));id=t['id'];assert t['binding']['sourceId']==id
        queued('runtime-create-001','create',{'title':'Synthetic runtime task','content':'Synthetic preserved description'});assert len(exchange()['tasks'])==1
        queued('runtime-stage-001','patch',{'taskId':id,'expectedVersion':1,'patch':{'stage':'requirements','process':'system-analysis'}});t=exchange()['tasks'][id]
        assert client.call('runtime-read-001','get',{'taskId':id})['stage']=='requirements'
        bridge=Bridge('cicada',str(cicada),str(a.client.absolute()))
        bridge.call({'version':1,'operation_id':'runtime-begin-001','action':'begin','body':{'title':'Unused','content':'','taskId':id,'expectedVersion':2,'projects':[],'report':report('runtime-run-001','running',1)}})
        bridge.call({'version':1,'operation_id':'runtime-done-001','action':'report','body':{'taskId':id,'expectedVersion':2,'report':report('runtime-run-001','done',2)}})
        queued('runtime-result-001','submit_result',{'taskId':id,'expectedVersion':2,'runId':'runtime-run-001','content':'First runtime result'});assert exchange()['tasks'][id]['review']['state']=='awaiting_review'
        queued('runtime-rework-001','review',{'taskId':id,'expectedVersion':3,'resultVersion':1,'decision':'rework','comment':'Synthetic preserved feedback'});assert exchange()['tasks'][id]['review']['state']=='awaiting_dispatch'
        queued('runtime-ack-001','acknowledge',{'taskId':id,'expectedVersion':4,'intentId':'runtime-rework-001','report':report('runtime-run-002','running',1)});assert exchange()['tasks'][id]['review']['state']=='running'
        bridge.call({'version':1,'operation_id':'runtime-done-002','action':'report','body':{'taskId':id,'expectedVersion':5,'report':report('runtime-run-002','done',2)}})
        queued('runtime-result-002','submit_result',{'taskId':id,'expectedVersion':5,'runId':'runtime-run-002','content':'Second runtime result'});exchange()
        queued('runtime-accept-002','review',{'taskId':id,'expectedVersion':6,'resultVersion':2,'decision':'accept'});t=exchange()['tasks'][id];assert t['completed'] and len(t['results'])==2 and not t['humanTimerActive']
        native.terminate();native.wait(timeout=10);native=None
        queued('runtime-offline-001','comment',{'taskId':id,'expectedVersion':7,'comment':'Offline survives reconnect'})
        state=city.call('POST','/api/task-sync/exchange',{});assert state['failure'] and 'runtime-offline-001' in state['outbox']
        native=launch();state=exchange();assert 'runtime-offline-001' not in state['outbox'];assert state['tasks'][id]['comments'][0]['content']=='Offline survives reconnect'
        queued('runtime-conflict-001','comment',{'taskId':id,'expectedVersion':7,'comment':'Stale retained draft'});state=exchange();assert state['outbox']['runtime-conflict-001']['state']=='conflict'
        # Frozen CLI startup can cross a background exchange. Re-read after a
        # rejected retirement; never suppress a failure on the same revision.
        conflict_id='runtime-conflict-001'
        for attempt in range(3):
            current=city.call('GET','/api/task-sync')
            if conflict_id not in current['outbox']:break
            try:city.call('POST','/api/task-sync/resolve',{'operationId':conflict_id,'revision':current['revision']})
            except AssertionError:
                after=city.call('GET','/api/task-sync')
                assert after['revision']!=current['revision'],'retirement failed without concurrent exchange'
                continue
            break
        final=city.call('GET','/api/task-sync')
        assert conflict_id not in final['outbox'] and final['receipts'][conflict_id]['state']=='resolved'
        assert final['receipts'][conflict_id]['request']['arguments']['comment']=='Stale retained draft'
        assert foreground==ctypes.windll.user32.GetForegroundWindow(),'foreground changed during background-only acceptance'
        result={'syntheticOnly':True,'nativeCicadaPipe':True,'ownedAgentCityBackend':True,'sameNativeId':id,'stages':True,'resultsReviewRework':True,'retryNoDuplicates':True,'disconnectReconnect':True,'revisionConflict':True,'foregroundUnchanged':True,'installed':False}
        (root/'acceptance.json').write_bytes(encode(result));print(json.dumps(result))
    finally:
        if city:city.close()
        if native and native.poll() is None:native.terminate();native.wait(timeout=10)
        native_log.close()
if __name__=='__main__':main()
