import copy
import ctypes
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch
from task_connection import TaskConnection,TaskError,default_config,validate_config,strict,encode
from task_sync import TaskSync
from tools.task_gateway import Gateway,server_for
from tools.shared_task_mcp import serve

ALL=['tasks:read','tasks:write','tasks:review','tasks:execute']
def configuration(root):
    return {**default_config(),'enabled':True,'transport':'pipe','endpoint':'','tokenEnv':'','profile':str(root/'cicada.db'),'client':str(root/'fixture-client'),'scopes':ALL}
def report(run,status,sequence):
    return dict(runId=run,sequence=sequence,taskKey=None,agent='codex',provider=None,model=None,stage=None,status=status,skillIds=[],mcpCalls=None,inputTokens=None,outputTokens=None)

class ConfigTests(unittest.TestCase):
    def test_pipe_transport_failure_is_never_treated_as_a_task_receipt(self):
        class Failure(RuntimeError):value={'ok':False,'error':'application_unavailable_or_outcome_unknown'}
        class Offline:
            def call(self,*args):raise Failure()
        with tempfile.TemporaryDirectory() as temp:
            client=TaskConnection(configuration(Path(temp)),Offline())
            with self.assertRaises(TaskError) as error:client.call('test-offline-001','create',{'title':'Synthetic','content':''})
            self.assertEqual(error.exception.status,503)
    def test_rejects_insecure_endpoints_and_secret_values(self):
        for endpoint in ['http://remote.example/commands','https://user:secret@example.com/commands','https://example.com/commands?token=secret']:
            with self.assertRaises(TaskError):validate_config({**default_config(),'endpoint':endpoint})
        with self.assertRaises(TaskError):validate_config({**default_config(),'tokenEnv':'secret value'})
        with self.assertRaises(TaskError):strict(b'{"key":1,"key":2}')
    def test_disabled_is_independent_and_has_no_worker(self):
        with tempfile.TemporaryDirectory() as temp:
            sync=TaskSync(temp);sync.start();self.assertIsNone(sync.worker)
            self.assertFalse(sync.snapshot()['config']['enabled']);self.assertEqual(sync.snapshot()['tasks'],{})
    def test_mcp_is_command_access_and_errors_do_not_echo_input(self):
        class Unavailable:
            config=default_config()
            def call(self,*args):raise RuntimeError('PRIVATE_CREDENTIAL_DO_NOT_PRINT')
        message={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'shared_task_command','arguments':{'operationId':'test-op-001','command':'snapshot','arguments':{}}}}
        output=io.BytesIO();serve(Unavailable(),io.BytesIO(encode(message)+b'\n'),output)
        self.assertNotIn(b'PRIVATE_CREDENTIAL',output.getvalue());self.assertTrue(json.loads(output.getvalue())['result']['isError'])

def synthetic_projection(task_id, title='Saved edit'):
    import hashlib
    ns='11111111-1111-4111-8111-111111111111'
    binding={'sourceNamespace':ns,'sourceType':'note','sourceId':task_id,
             'taskKey':'cicada-'+hashlib.sha256(ns.encode()).hexdigest()[:16]+'-'+task_id}
    return dict(id=task_id,version=8,binding=binding,title=title,content='',tags='',
                results=[],history=[],comments=[],intents=[],reports=[])

class ReceiptIdentityTests(unittest.TestCase):
    def test_wrong_task_ack_retains_original_draft_and_replays_exact_request(self):
        for deleted in (False, True):
            with self.subTest(deleted=deleted), tempfile.TemporaryDirectory() as temp:
                op='synthetic-patch-001'
                args={'taskId':'original-task','expectedVersion':7,'patch':{'title':'Unsaved edit'}}
                calls=[]
                class Client:
                    def __init__(self, config):self.config=config
                    def call(self, operation, command, arguments):
                        calls.append((operation,command,copy.deepcopy(arguments)))
                        return {'operationId':operation,'acknowledged':True,
                                'task':{**synthetic_projection('different-task'),'deleted':deleted}}
                sync=TaskSync(temp,Client);sync.stop.set()
                sync.configure(configuration(Path(temp)),0)
                queued=sync.enqueue(op,'patch',args)
                state=sync.exchange()
                self.assertEqual(state['failure']['code'],'task_receipt_identity_mismatch')
                self.assertEqual(state['outbox'][op],queued)
                self.assertNotIn(op,state['receipts'])
                self.assertEqual(state['tasks'],{})
                restarted=TaskSync(temp,Client)
                restarted.exchange()
                self.assertEqual(calls,[(op,'patch',args),(op,'patch',args)])

    def test_unknown_ack_stays_pending_then_exact_replay_is_confirmed_once(self):
        task_id='original-task'
        task=synthetic_projection(task_id)
        ns=task['binding']['sourceNamespace']
        calls=[]
        class Client:
            def __init__(self, config):self.config=config
            def call(self, operation, command, arguments):
                if command=='snapshot':
                    return dict(schemaVersion=1,complete=True,sourceNamespace=ns,tasks=[task],tombstones=[])
                calls.append((operation,command,copy.deepcopy(arguments)))
                return dict(operationId=operation,acknowledged=len(calls)>1,task=task)
        with tempfile.TemporaryDirectory() as temp:
            sync=TaskSync(temp,Client);sync.stop.set();sync.configure(configuration(Path(temp)),0)
            args={'taskId':task_id,'expectedVersion':7,'patch':{'title':'Saved edit'}}
            queued=sync.enqueue('synthetic-patch-002','patch',args)
            first=sync.exchange()
            self.assertEqual(first['outbox']['synthetic-patch-002'],queued)
            self.assertEqual(first['failure']['code'],'unconfirmed_task_receipt')
            state=sync.exchange()
            self.assertEqual(state['outbox'],{})
            self.assertEqual(state['receipts']['synthetic-patch-002']['state'],'acknowledged')
            self.assertEqual(state['tasks'][task_id]['title'],'Saved edit')
            sync.exchange()
            self.assertEqual(calls,[('synthetic-patch-002','patch',args)]*2)

class NativeBridge:
    def __init__(self,exe,db):
        env=dict(os.environ,CICADA_SYNTHETIC_TEST_DB=str(db))
        flags={'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {}
        self.process=subprocess.Popen([exe,'shared_tasks::tests::stdio_fixture','--exact','--ignored','--nocapture'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env,**flags)
        self.available=True;self.drop=False;self.calls=0
    def direct(self,value):
        self.process.stdin.write(encode(value)+b'\n');self.process.stdin.flush()
        while True:
            line=self.process.stdout.readline()
            if not line:raise RuntimeError('native_fixture_stopped')
            at=line.find(b'CICADA_FIXTURE:')
            if at>=0:return strict(line[at+15:])
    def call(self,value):
        self.calls+=1
        if not self.available:raise TaskError('task_connection_unavailable',503)
        result=self.direct(value)
        if self.drop and value['body']['command']!='snapshot':
            self.drop=False;raise TaskError('task_connection_unavailable',503)
        return result
    def command(self,op,command,args):
        return self.direct({'operationId':op,'command':command,'arguments':args})
    def close(self):
        self.process.stdin.close();self.process.wait(timeout=10);self.process.stdout.close();self.process.stderr.close()

@unittest.skipUnless(os.environ.get('CICADA_NATIVE_TEST_EXE'),'requires freshly built native test harness')
class NativeIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.native=NativeBridge(os.environ['CICADA_NATIVE_TEST_EXE'],self.root/'cicada.db');self.addCleanup(self.native.close)
        self.sync=TaskSync(self.root/'city',lambda cfg:TaskConnection(cfg,self.native));self.sync.stop.set()
        self.config=configuration(self.root);self.sync.configure(self.config,0)
    def create(self,op='integration-create-001'):
        self.sync.enqueue(op,'create',{'title':'Synthetic Ж 文','content':'Original description'});state=self.sync.exchange();self.assertIsNone(state['failure'],state)
        return next(iter(state['tasks'].values()))
    def test_same_id_stage_result_review_rework_and_history(self):
        t=self.create();id=t['id'];self.assertEqual(t['binding']['sourceId'],id)
        self.sync.enqueue('integration-stage-001','patch',{'taskId':id,'expectedVersion':1,'patch':{'stage':'requirements','process':'system-analysis'}})
        t=self.sync.exchange()['tasks'][id];self.assertEqual(t['stage'],'requirements');self.assertEqual(t['content'],'Original description')
        self.assertEqual(self.native.command('integration-read-001','get',{'taskId':id}),{k:v for k,v in t.items() if k!='freshness'})
        begin={'version':1,'operation_id':'integration-begin-001','action':'begin','body':{'title':'Unused','content':'','taskId':id,'expectedVersion':2,'projects':[],'report':report('integration-run-001','running',1)}}
        self.native.direct(begin);done=copy.deepcopy(begin);done.update(operation_id='integration-done-001',action='report');done['body']={'taskId':id,'expectedVersion':2,'report':report('integration-run-001','done',2)};self.native.direct(done)
        self.sync.enqueue('integration-result-001','submit_result',{'taskId':id,'expectedVersion':2,'runId':'integration-run-001','content':'First result'})
        t=self.sync.exchange()['tasks'][id];self.assertEqual(t['review']['state'],'awaiting_review');self.assertFalse(t['completed']);self.assertFalse(t['humanTimerActive']);self.assertIsNotNone(t['reports'][0]['receivedAt']);self.assertIsNone(t['reports'][0]['model'])
        self.sync.enqueue('integration-rework-001','review',{'taskId':id,'expectedVersion':3,'resultVersion':1,'decision':'rework','comment':'Preserved feedback'})
        t=self.sync.exchange()['tasks'][id];self.assertEqual(t['review']['state'],'awaiting_dispatch');self.assertEqual(t['results'][0]['content'],'First result')
        self.assertEqual(len(t['intents']),1)
        self.sync.enqueue('integration-ack-001','acknowledge',{'taskId':id,'expectedVersion':4,'intentId':'integration-rework-001','report':report('integration-run-002','running',1)})
        t=self.sync.exchange()['tasks'][id];self.assertEqual(t['review']['state'],'running')
        self.native.direct({'version':1,'operation_id':'integration-done-002','action':'report','body':{'taskId':id,'expectedVersion':5,'report':report('integration-run-002','done',2)}})
        self.sync.enqueue('integration-result-002','submit_result',{'taskId':id,'expectedVersion':5,'runId':'integration-run-002','content':'Second result'});self.sync.exchange()
        self.sync.enqueue('integration-accept-002','review',{'taskId':id,'expectedVersion':6,'resultVersion':2,'decision':'accept'})
        t=self.sync.exchange()['tasks'][id];self.assertTrue(t['completed']);self.assertEqual(t['review']['state'],'accepted');self.assertEqual(len(t['results']),2);self.assertEqual(t['history'][1]['comment'],'Preserved feedback')
    def test_unknown_outcome_retry_offline_restart_conflict_and_reconnect(self):
        self.native.drop=True;self.sync.enqueue('integration-lost-001','create',{'title':'Synthetic retry','content':'Kept'})
        state=self.sync.exchange();self.assertEqual(len(state['outbox']),1);self.assertEqual(len(state['tasks']),0)
        state=self.sync.exchange();self.assertEqual(len(state['tasks']),1);self.assertEqual(len(state['outbox']),0)
        t=next(iter(state['tasks'].values()));id=t['id'];self.native.available=False
        args={'taskId':id,'expectedVersion':1,'patch':{'title':'Offline draft'}};self.sync.enqueue('integration-offline-001','patch',args)
        self.sync.exchange();restarted=TaskSync(self.root/'city',lambda cfg:TaskConnection(cfg,self.native));self.assertEqual(restarted.snapshot()['outbox']['integration-offline-001']['request']['arguments'],args)
        self.native.available=True;native=self.native.command('integration-concurrent-001','patch',{'taskId':id,'expectedVersion':1,'patch':{'title':'Other app edit'}});self.assertTrue(native['acknowledged'])
        state=restarted.exchange();self.assertEqual(state['tasks'][id]['title'],'Other app edit');self.assertEqual(state['outbox']['integration-offline-001']['state'],'conflict');self.assertEqual(state['outbox']['integration-offline-001']['conflict']['current']['title'],'Other app edit')
        with self.assertRaises(TaskError):restarted.enqueue('integration-offline-001','patch',{**args,'patch':{'title':'Changed retry'}})
        restarted.resolve('integration-offline-001',state['revision']);restarted.enqueue('integration-merged-001','patch',{'taskId':id,'expectedVersion':2,'patch':{'title':'Explicitly reconciled'}})
        self.assertEqual(restarted.exchange()['tasks'][id]['title'],'Explicitly reconciled')
    def test_scoped_authenticated_http_and_wrong_namespace_before_mutation(self):
        t=self.create();id=t['id'];cfg={**configuration(self.root),'sourceNamespace':t['binding']['sourceNamespace']}
        token='a'*48
        with patch.dict(os.environ,TEST_TASK_AUTH=token):
            gateway=Gateway('cicada',cfg,[{'tokenEnv':'TEST_TASK_AUTH','scopes':['tasks:read'],'taskIds':[id],'sourceNamespace':cfg['sourceNamespace']}],self.native)
            http=server_for(gateway);worker=threading.Thread(target=http.serve_forever,daemon=True);worker.start()
            try:
                connection=TaskConnection({**default_config(),'enabled':True,'endpoint':f'http://127.0.0.1:{http.server_port}/commands','tokenEnv':'TEST_TASK_AUTH'})
                self.assertEqual(connection.call('integration-http-001','snapshot',{})['tasks'][0]['id'],id)
                with self.assertRaises(TaskError) as err:
                    # Client advertises write but server grant denies it.
                    TaskConnection({**connection.config,'scopes':ALL}).call('integration-denied-001','patch',{'taskId':id,'expectedVersion':1,'patch':{'title':'Forbidden'}})
                self.assertEqual(err.exception.status,403)
                with patch.dict(os.environ,TEST_TASK_AUTH='b'*48):
                    with self.assertRaises(TaskError) as err:connection.call('integration-auth-001','snapshot',{})
                    self.assertEqual(err.exception.status,401)
            finally:http.shutdown();http.server_close();worker.join()
        wrong=TaskConnection({**cfg,'sourceNamespace':'22222222-2222-4222-8222-222222222222'},self.native)
        with self.assertRaises(TaskError):wrong.call('integration-wrong-001','patch',{'taskId':id,'expectedVersion':1,'patch':{'title':'Wrong deployment'}})
        self.assertEqual(self.native.command('integration-check-001','get',{'taskId':id})['title'],t['title'])
    def test_background_commands_preserve_foreground_window(self):
        before=ctypes.windll.user32.GetForegroundWindow() if os.name=='nt' else None
        self.create();self.sync.exchange()
        if os.name=='nt':self.assertEqual(before,ctypes.windll.user32.GetForegroundWindow())
    def test_confirmed_receipt_and_pending_survive_restart(self):
        t=self.create();id=t['id'];args={'taskId':id,'expectedVersion':1,'comment':'Saved comment'}
        self.sync.enqueue('integration-comment-001','comment',args);self.sync.exchange()
        restarted=TaskSync(self.root/'city',lambda cfg:TaskConnection(cfg,self.native));receipt=restarted.enqueue('integration-comment-001','comment',args)
        self.assertEqual(receipt['state'],'acknowledged');self.assertEqual(len(restarted.exchange()['tasks'][id]['comments']),1)

if __name__=='__main__':unittest.main()
