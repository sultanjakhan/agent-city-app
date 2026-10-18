import copy
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from agent_hooks import process, digest

TASK = "00000000-0000-4000-8000-000000000001"
SESSION_KEY = "codex-" + digest("synthetic-session")

def bound_config(root):
    return {"personalRoots":[root],"outbox":str(Path(root)/"outbox.db"),"taskBindings":{SESSION_KEY:TASK}}


class Native:
    def __init__(self): self.receipts={}; self.created=0; self.requests=[]
    def call(self, request):
        self.requests.append(copy.deepcopy(request))
        if request['action']=='get': return {'version':1}
        op=request['operation_id']
        if op in self.receipts: return copy.deepcopy(self.receipts[op])
        body=request['body']; self.created+=int(request['action']=='begin' and body['taskId'] is None)
        report=dict(body['report'],taskKey='cicada-'+'a'*16+'-synthetic-task')
        result={'task':{'id':TASK,'version':1},'binding':{'taskKey':report['taskKey']},'report':report}
        self.receipts[op]=result;return copy.deepcopy(result)


class City:
    def __init__(self):self.fail=True;self.reports=[]
    def call(self, request):
        if self.fail: raise RuntimeError('outcome_unknown')
        self.reports.append(request['body']['report']);return {'recorded':True}


class HookTests(unittest.TestCase):
    def test_real_tool_activity_refreshes_same_run_throttled_and_stop_uses_next_sequence(self):
        with tempfile.TemporaryDirectory() as root:
            config=bound_config(root)
            native=Native();city=City();city.fail=False
            event=dict(session_id='synthetic-session',turn_id='synthetic-turn',cwd=root,hook_event_name='UserPromptSubmit',model='observed-model')
            process(config,'codex',event,(native,city))
            for now in (1000,1001,1059,1060,1061,1120):
                with patch('agent_hooks.time.time',return_value=now):
                    process(config,'codex',dict(event,hook_event_name='PreToolUse'),(native,city))
            self.assertEqual(native.created,0)
            self.assertEqual([r['sequence'] for r in city.reports],[1,2,3])
            self.assertEqual(len({r['runId'] for r in city.reports}),1)
            process(config,'codex',dict(event,hook_event_name='Stop'),(native,city))
            self.assertEqual(city.reports[-1]['sequence'],4)
            self.assertEqual(city.reports[-1]['status'],'done')

    def test_pending_refresh_replays_exact_receipt_without_adding_more_during_outage(self):
        with tempfile.TemporaryDirectory() as root:
            config=bound_config(root)
            native=Native();city=City();city.fail=False
            event=dict(session_id='synthetic-session',turn_id='synthetic-turn',cwd=root,hook_event_name='UserPromptSubmit',model='observed-model')
            process(config,'codex',event,(native,city))
            with patch('agent_hooks.time.time',return_value=1000):
                process(config,'codex',dict(event,hook_event_name='PreToolUse'),(native,city))
            city.fail=True
            for now in (1060,1120):
                with patch('agent_hooks.time.time',return_value=now),self.assertRaises(RuntimeError):
                    process(config,'codex',dict(event,hook_event_name='PreToolUse'),(native,city))
            with closing(sqlite3.connect(config['outbox'])) as db:
                self.assertEqual(db.execute('SELECT count(*) FROM outbox').fetchone()[0],1)
            self.assertEqual(len(native.receipts),2)
            city.fail=False
            process(config,'codex',dict(event,hook_event_name='Stop'),(native,city))
            self.assertEqual([r['sequence'] for r in city.reports],[1,2,3])
            self.assertEqual([r['status'] for r in city.reports],['running','running','done'])
            self.assertEqual(native.created,0)

    def test_outage_replays_start_before_stop_without_duplicate_and_preserves_no_text(self):
        with tempfile.TemporaryDirectory() as root:
            config=bound_config(root)
            native=Native();city=City()
            event=dict(session_id='synthetic-session',turn_id='synthetic-turn',cwd=root,hook_event_name='UserPromptSubmit',model='observed-model',prompt='SECRET_SENTINEL',transcript_path='SECRET_PATH')
            process(config,'codex',event,(native,city));self.assertEqual(native.created,0)
            with self.assertRaises(RuntimeError):process(config,'codex',dict(event,hook_event_name='PreToolUse'),(native,city))
            self.assertEqual(native.created,0)
            city.fail=False
            process(config,'codex',dict(event,hook_event_name='Stop'),(native,city))
            self.assertEqual(native.created,0);self.assertEqual([row['status'] for row in city.reports],['running','done'])
            self.assertEqual([row['sequence'] for row in city.reports],[1,2])
            self.assertNotIn(b'SECRET',Path(config['outbox']).read_bytes())
            with closing(sqlite3.connect(config['outbox'])) as db:self.assertEqual(db.execute('SELECT count(*) FROM outbox').fetchone()[0],0)
            process(config,'codex',dict(event,hook_event_name='Stop'),(native,city));self.assertEqual(len(city.reports),2)
    def test_unregistered_scope_never_creates_outbox_or_reports(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as foreign:
            config=bound_config(root)
            process(config,'codex',dict(cwd=foreign),())
            self.assertFalse(Path(config['outbox']).exists())
    def test_unbound_tool_and_text_only_stop_never_register_business_work(self):
        for client in ('codex','claude'):
            for end in ('PreToolUse','Stop','Interrupt','StopFailure'):
                with self.subTest(client=client,end=end), tempfile.TemporaryDirectory() as root:
                    config={'personalRoots':[root],'outbox':str(Path(root)/'outbox.db')}
                    native=Native();city=City();city.fail=False
                    event=dict(session_id='synthetic-session',turn_id='synthetic-turn',cwd=root,hook_event_name='UserPromptSubmit',prompt='SECRET_SENTINEL')
                    process(config,client,event,(native,city))
                    process(config,client,dict(event,hook_event_name=end),(native,city))
                    self.assertEqual(native.requests,[]);self.assertEqual(city.reports,[])
                    with closing(sqlite3.connect(config['outbox'])) as db:
                        self.assertEqual(db.execute('SELECT count(*) FROM outbox').fetchone()[0],0)
                        self.assertEqual(db.execute('SELECT count(*) FROM sessions').fetchone()[0],0)
                    self.assertNotIn(b'SECRET',Path(config['outbox']).read_bytes())

    def test_unknown_native_outcome_replays_exact_bound_request(self):
        class LostReply(Native):
            def call(self,request):
                result=super().call(request)
                if request['action']=='begin' and not getattr(self,'lost',False):
                    self.lost=True;raise RuntimeError('outcome_unknown')
                return result
        with tempfile.TemporaryDirectory() as root:
            config=bound_config(root);native=LostReply();city=City();city.fail=False
            event=dict(session_id='synthetic-session',turn_id='synthetic-turn',cwd=root,hook_event_name='UserPromptSubmit')
            process(config,'codex',event,(native,city))
            with self.assertRaises(RuntimeError):process(config,'codex',dict(event,hook_event_name='PreToolUse'),(native,city))
            process(config,'codex',dict(event,hook_event_name='PreToolUse'),(native,city))
            begins=[r for r in native.requests if r['action']=='begin']
            self.assertEqual(len(begins),2);self.assertEqual(begins[0],begins[1])
            self.assertEqual(begins[0]['body']['taskId'],TASK)
            self.assertEqual(native.created,0);self.assertEqual(len(native.receipts),1)

    def test_legacy_unbound_requests_are_retained_withheld_and_do_not_block_bound_work(self):
        with tempfile.TemporaryDirectory() as root:
            config=bound_config(root);native=Native();city=City();city.fail=False
            event=dict(session_id='synthetic-session',turn_id='synthetic-turn',cwd=root,hook_event_name='UserPromptSubmit')
            process(config,'codex',event,(native,city))
            old_key='codex-'+digest('old-session')
            payload={'operationId':'old-operation','taskId':None,'expectedVersion':None,'title':'Codex · чат deadbeef','content':'','projects':['ai'],'report':{}}
            old={'session':old_key,'operationId':'old-operation','action':'begin','report':{},'payload':payload,'native':None}
            with closing(sqlite3.connect(config['outbox'])) as db:
                db.execute('INSERT INTO sessions VALUES(?,?)',(old_key,json.dumps({'taskId':None})))
                db.execute('INSERT INTO outbox(value) VALUES(?)',(json.dumps(old),))
                follow=dict(old,operationId='old-stop',action='report',payload=None)
                db.execute('INSERT INTO outbox(value) VALUES(?)',(json.dumps(follow),));db.commit()
            for _ in range(3):process(config,'codex',dict(event,hook_event_name='PreToolUse'),(native,city))
            with closing(sqlite3.connect(config['outbox'])) as db:
                saved=[json.loads(row[0]) for row in db.execute('SELECT value FROM outbox ORDER BY id')]
                self.assertEqual(len(saved),2)
                for row in saved:self.assertEqual(row['withheld'],'unbound-native-registration')
                self.assertEqual(saved[0]['payload'],payload)
                self.assertEqual(saved[0]['operationId'],'old-operation')
            self.assertEqual(native.created,0)
            self.assertTrue(all(r['body'].get('taskId')==TASK for r in native.requests))
            self.assertEqual(len(city.reports),1)

    def test_saved_native_receipt_is_delivered_without_reissuing_legacy_create(self):
        with tempfile.TemporaryDirectory() as root:
            config=bound_config(root);native=Native();city=City();city.fail=False
            event=dict(session_id='synthetic-session',turn_id='synthetic-turn',cwd=root,hook_event_name='UserPromptSubmit')
            process(config,'codex',event,(native,city))
            receipt={'task':{'id':TASK},'binding':{'taskKey':'saved-key'},'report':{'runId':'saved-run','status':'running'}}
            message={'session':SESSION_KEY,'operationId':'saved-operation','action':'begin','report':receipt['report'],'payload':{'taskId':None},'native':receipt}
            with closing(sqlite3.connect(config['outbox'])) as db:
                db.execute('INSERT INTO outbox(value) VALUES(?)',(json.dumps(message),));db.commit()
            process(config,'codex',dict(event,hook_event_name='OtherEvent'),(native,city))
            self.assertEqual(native.requests,[]);self.assertEqual(city.reports,[receipt['report']])
            with closing(sqlite3.connect(config['outbox'])) as db:
                self.assertEqual(db.execute('SELECT count(*) FROM outbox').fetchone()[0],0)

    def test_existing_session_binding_survives_missing_config_and_rebinding_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            config=bound_config(root);native=Native();city=City();city.fail=False
            event=dict(session_id='synthetic-session',turn_id='synthetic-turn',cwd=root,hook_event_name='UserPromptSubmit')
            process(config,'codex',event,(native,city))
            config.pop('taskBindings')
            process(config,'codex',dict(event,hook_event_name='PreToolUse'),(native,city))
            self.assertTrue(all(r['body'].get('taskId')==TASK for r in native.requests))
            config['taskBindings']={SESSION_KEY:'00000000-0000-4000-8000-000000000002'}
            with self.assertRaisesRegex(ValueError,'binding conflict'):
                process(config,'codex',dict(event,hook_event_name='Stop'),(native,city))
            self.assertEqual(city.reports[-1]['status'],'running')

    def test_text_only_finished_turn_is_recorded_after_observed_completion(self):
        with tempfile.TemporaryDirectory() as root:
            config=bound_config(root);native=Native();city=City();city.fail=False
            event=dict(session_id='synthetic-session',turn_id='synthetic-turn',cwd=root,hook_event_name='UserPromptSubmit',model='observed-model')
            process(config,'codex',event,(native,city));self.assertEqual(native.created,0)
            process(config,'codex',dict(event,hook_event_name='Stop'),(native,city));self.assertEqual(native.created,0)
            self.assertEqual([r['status'] for r in city.reports],['running','done'])


if __name__=='__main__':unittest.main()
