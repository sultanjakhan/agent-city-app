from owner_client import authorize, headers as owner_headers
from contextlib import closing
import copy
from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import threading
from urllib.error import HTTPError
from urllib.request import Request, build_opener, ProxyHandler
import unittest
from unittest.mock import patch

import server
from test_dashboard_http import make_cicada
from test_run_store import report
from work_exchange import (WorkExchange, ExchangeError, ExchangeConflict,
                           validate_registry, validate_binding, strict_json, freshness)

NS = '11111111-1111-4111-8111-111111111111'
OTHER_NS = '22222222-2222-4222-8222-222222222222'


def binding(ns=NS, source_id='task-1'):
    return {'sourceNamespace':ns, 'sourceType':'note', 'sourceId':source_id,
            'taskKey':'cicada-'+hashlib.sha256(ns.encode()).hexdigest()[:16]+'-'+source_id}


def fixture_snapshot():
    stamp = datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z')
    return {'schemaVersion':1,'kind':'work-registry-snapshot','snapshotId':'synthetic-snapshot',
            'sequence':1,'source':{'publisherId':'synthetic-parent','sourceNamespace':OTHER_NS,'mode':'published-snapshot'},
            'publishedAt':stamp,'staleAfterSeconds':60,'projects':[{'id':'engineering','title':'Synthetic project'}],
            'tasks':[{'id':'root','projectId':'engineering','parentTaskId':None,'title':'Synthetic task',
                      'relationship':'root','status':'checking','lastUpdated':stamp,
                      'provenance':{'kind':'parent-published','reference':'synthetic-fixture'},
                      'operation':'Checking locally','waitingFor':None,'result':None,'localBinding':binding()}],
            'runs':[]}


def source_state():
    b = binding()
    return {'version':1,'sourceNamespace':NS,'order':0,'bindings':{b['taskKey']:b},'runs':{}}


class ExchangeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.db = self.root/'production.db'; make_cicada(self.db)
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("INSERT INTO ui_state VALUES(?,?,?)", ('calendar_task_run_exchange_v1',json.dumps(source_state()),'now'))
        self.dev = self.root/'dev.db'; shutil.copyfile(self.db,self.dev)
        self.skills = self.root/'skills'; self.skills.mkdir(); (self.root/'repos').mkdir()
        for module,name in ((server.credentials,'read_key'),(server.credentials,'info'),(server.CloudSync,'_profile'),(server.CloudSync,'start')):
            guard=patch.object(module,name,side_effect=AssertionError('protected_operation'));guard.start();self.addCleanup(guard.stop)
        self.store = server.Store(self.root/'panel',local_only=True,executable=False,skills_root=self.skills,
                                 codex_home=self.root/'codex',repo_roots=[self.root/'repos'],inventory_roots=[('worktree',self.skills)],
                                 cicada_candidates=[{'id':'production','profile':'production','label':'Synthetic production','path':str(self.db)},
                                                    {'id':'dev','profile':'dev','label':'Synthetic DEV','path':str(self.dev)}])
        self.store.cicada.select('production',self.store.cicada.settings()['revision'])
        self.exchange=self.store.work_exchange

    def apply(self,doc):
        revision=self.exchange.snapshot()['revision']
        preview=self.exchange.preview(json.dumps(doc),revision)
        return self.exchange.apply(preview['previewToken'],revision)

    def pair(self):
        return self.apply({'schemaVersion':1,'kind':'cicada-task-binding','binding':binding()})

    def envelope(self,**kwargs):
        return {'schemaVersion':1,'kind':'cicada-run-report','binding':binding(),
                'report':report(taskKey=binding()['taskKey'],skillIds=[],mcpCalls=None,provider=None,model=None,**kwargs)}

    def http_call(self,route,body=None,authenticated=True):
        if not hasattr(self,'http'):
            self.http=server.Server(('127.0.0.1',0),self.store)
            self.worker=threading.Thread(target=self.http.serve_forever,daemon=True);self.worker.start(); authorize(self.http)
            self.addCleanup(self.stop_http)
        headers={'X-Agent-City':'1','Content-Type':'application/json'}
        if authenticated:headers['X-Agent-City-Token']=self.store.csrf_token
        req=Request(f'http://127.0.0.1:{self.http.server_port}'+route,data=json.dumps(body).encode() if body is not None else None,headers=owner_headers('http://127.0.0.1:'+str(self.http.server_port),headers))
        try:
            with build_opener(ProxyHandler({})).open(req,timeout=3) as response:return response.status,json.load(response)
        except HTTPError as response:return response.code,json.load(response)

    def stop_http(self):
        self.http.shutdown();self.http.server_close();self.worker.join(3)

    def test_local_only_blocks_codex_mutations_with_owner_session_and_csrf_token(self):
        with patch.object(self.store.codex, 'connect_bridge', side_effect=AssertionError('must_not_write')), patch.object(self.store.codex, 'set_enabled', side_effect=AssertionError('must_not_write')):
            status, state = self.http_call('/api/state')
            self.assertEqual(200, status)
            self.assertIn('csrfToken', state)  # CSRF is available only after the owner-session handshake.
            for route in ('connect', 'skill'):
                status, body = self.http_call('/api/codex-controls/'+route, {'revision':'none'})
                self.assertEqual(403, status)
                self.assertIn('disabled', body['error'])
        self.assertFalse((self.root/'codex'/'AGENTS.md').exists())

    def test_wrong_status_and_agent_types_fail_closed_without_hangup(self):
        self.store.runs.report(report(skillIds=[]))
        original = self.store.runs.path.read_bytes()
        cases=[]
        for key in ('status','agent'):
            cases += [('run',key,x) for x in ([],{},None,7,True,float('nan'),float('inf'))]
        cases += [('history','status',x) for x in ([],{},None,7,True,float('nan'),float('inf'))]
        for key in ('inputTokens','outputTokens'):
            cases += [('run',key,x) for x in ([],{},True,-1,1.5,float('nan'),float('inf'))]
        self.assertEqual(35,len(cases))
        for location,key,wrong in cases:
            value=json.loads(original);row=value['runs']['run-00000001']
            (row if location=='run' else row['history'][0])[key]=wrong
            invalid=json.dumps(value).encode();self.store.runs.path.write_bytes(invalid)
            with self.subTest(key=key,wrongType=type(wrong).__name__,location=location):
                status,body=self.http_call('/api/dashboard');self.assertEqual(400,status)
                with self.assertRaises(ValueError): self.store.cloud_reports()
                self.assertEqual(invalid,self.store.runs.path.read_bytes())
        self.store.runs.path.write_bytes(original)

    def test_private_saved_run_fields_never_reach_dashboard_or_cloud(self):
        self.store.runs.report(report(skillIds=[]))
        original = self.store.runs.path.read_bytes()
        value = json.loads(original)
        value['runs']['run-00000001']['arguments'] = 'synthetic-private-marker'
        invalid = json.dumps(value).encode()
        self.store.runs.path.write_bytes(invalid)
        status, body = self.http_call('/api/dashboard')
        self.assertEqual(400, status)
        self.assertNotIn('synthetic-private-marker', json.dumps(body))
        with self.assertRaises(ValueError): self.store.cloud_reports()
        self.assertEqual(invalid, self.store.runs.path.read_bytes())
        self.store.runs.path.write_bytes(original)
        self.assertEqual(1, len(self.store.runs.snapshot()))
        value = json.loads(original)
        value['runs']['run-00000001']['history'][0]['arguments'] = 'synthetic-private-marker'
        self.store.runs.path.write_text(json.dumps(value), 'utf8')
        with self.assertRaises(ValueError): self.store.runs.snapshot()

    def test_redirect_failure_is_sanitized_without_storage_write(self):
        from codex_controls import CodexControlsError
        with patch('work_exchange._reject_redirects', side_effect=CodexControlsError('synthetic path')):
            status, body = self.http_call('/api/work-exchange')
            self.assertEqual(400, status)
            self.assertNotIn('synthetic path', json.dumps(body))
        self.assertFalse(self.exchange.path.exists())

    def test_http_preview_token_sequence_conflict_and_no_protected_hooks(self):
        payload={'document':json.dumps(fixture_snapshot()),'revision':'none'}
        status,_=self.http_call('/api/work-exchange/preview',payload,False);self.assertEqual(403,status)
        self.assertFalse(self.exchange.path.exists())
        status,preview=self.http_call('/api/work-exchange/preview',payload);self.assertEqual(200,status)
        status,_=self.http_call('/api/work-exchange/apply',{'previewToken':preview['previewToken'],'revision':'none'});self.assertEqual(200,status)
        before=self.exchange.path.read_bytes();doc=fixture_snapshot();doc['tasks'][0]['status']='done'
        payload={'document':json.dumps(doc),'revision':self.exchange.snapshot()['revision']}
        status,error=self.http_call('/api/work-exchange/preview',payload);self.assertEqual(409,status)
        self.assertEqual('exchange_conflict',error['error']);self.assertEqual(before,self.exchange.path.read_bytes())
        status,_=self.http_call('/api/refresh',{'target':'all'});self.assertEqual(403,status)

    def test_http_strict_envelope_import_report_export_and_dynamic_dashboard(self):
        self.pair();doc=self.envelope(status='waiting')
        status,preview=self.http_call('/api/work-exchange/preview',{'document':json.dumps(doc),'revision':self.exchange.snapshot()['revision']});self.assertEqual(200,status)
        self.assertFalse(self.store.runs.path.exists())
        status,result=self.http_call('/api/work-exchange/apply',{'previewToken':preview['previewToken'],'revision':preview['revision']});self.assertEqual(200,status)
        self.assertFalse(result['executionSupported'])
        status,exported=self.http_call('/api/work-exchange/export-report',{'runId':doc['report']['runId']});self.assertEqual(200,status)
        self.assertEqual(binding(),exported['binding']);self.assertEqual('waiting',exported['report']['status'])
        status,dashboard=self.http_call('/api/dashboard');self.assertEqual(200,status)
        self.assertEqual(binding()['taskKey'],dashboard['cicada']['tasks'][0]['taskKey'])
        self.assertIsNone(dashboard['runs'][0]['inputTokens'])
        bad=copy.deepcopy(doc);bad['report']['arguments']={'private':'never expose'}
        status,error=self.http_call('/api/work-exchange/preview',{'document':json.dumps(bad),'revision':preview['revision']});self.assertEqual(400,status)
        self.assertNotIn('never expose',json.dumps(error))

    def test_pair_is_explicit_readonly_native_and_survives_reopen(self):
        native_before=self.db.read_bytes(); legacy=self.store.dashboard()['cicada']['tasks'][0]['taskKey']
        preview=self.exchange.preview(json.dumps({'schemaVersion':1,'kind':'cicada-task-binding','binding':binding()}),'none')
        self.assertFalse(self.exchange.path.exists());self.assertEqual(legacy,self.store.dashboard()['cicada']['tasks'][0]['taskKey'])
        self.exchange.apply(preview['previewToken'],'none')
        task=self.store.dashboard()['cicada']['tasks'][0]
        self.assertEqual(binding()['taskKey'],task['taskKey']);self.assertEqual(legacy,task['legacyTaskKey'])
        self.assertEqual([task['taskKey'],legacy],task['runTaskKeys']);self.assertEqual(native_before,self.db.read_bytes())
        reopened=WorkExchange(self.root/'panel',self.store.cicada,self.store.runs)
        self.assertEqual(self.exchange.bindings(),reopened.bindings());self.assertFalse(reopened.snapshot()['executionSupported'])

    def test_unknown_namespace_or_binding_never_registers_itself(self):
        for value in (binding(OTHER_NS),binding(source_id='missing')):
            with self.assertRaises(ExchangeError):self.apply({'schemaVersion':1,'kind':'cicada-task-binding','binding':value})
        self.assertFalse(self.exchange.path.exists())
        with self.assertRaisesRegex(ExchangeError,'binding_not_paired'):self.apply(self.envelope())
        self.assertFalse(self.store.runs.path.exists())

    def test_clone_profile_does_not_inherit_pair_and_apply_revalidates_source(self):
        self.pair(); preview=self.exchange.preview(json.dumps(self.envelope()),self.exchange.snapshot()['revision'])
        self.store.cicada.select('dev',self.store.cicada.settings()['revision'])
        task=self.store.dashboard()['cicada']['tasks'][0]
        self.assertNotEqual(binding()['taskKey'],task['taskKey'])
        with self.assertRaises(ExchangeConflict):self.exchange.apply(preview['previewToken'],preview['revision'])
        with self.assertRaises(ExchangeConflict):self.apply(self.envelope())
        self.assertFalse(self.store.runs.path.exists())

    def test_report_sequence_usage_export_and_done_never_complete_native_task(self):
        self.pair();self.apply(self.envelope(status='done',sequence=1,inputTokens=7,outputTokens=0))
        before=self.store.runs.path.read_bytes();self.apply(self.envelope(status='done',sequence=1,inputTokens=7,outputTokens=0))
        self.assertEqual(before,self.store.runs.path.read_bytes())
        with self.assertRaises(ValueError):self.apply(self.envelope(status='done',sequence=1,inputTokens=8,outputTokens=0))
        with self.assertRaises(ValueError):self.apply(self.envelope(status='done',sequence=2,inputTokens=6,outputTokens=0))
        exported=self.exchange.export_report('run-00000001');self.assertEqual(set(exported),{'schemaVersion','kind','binding','report'})
        self.assertEqual(binding(),exported['binding']);self.assertNotIn('updatedAt',exported['report'])
        with closing(sqlite3.connect(self.db)) as db:self.assertEqual(0,db.execute('SELECT completed FROM items').fetchone()[0])
        self.assertFalse(self.exchange.path.read_bytes().find(b'private')>=0)

    def test_registry_preview_replacement_idempotence_and_publisher_isolation(self):
        doc=fixture_snapshot(); preview=self.exchange.preview(json.dumps(doc),'none')
        self.assertFalse(self.exchange.path.exists());self.assertFalse(self.store.runs.path.exists())
        self.exchange.apply(preview['previewToken'],'none');before=self.exchange.path.read_bytes()
        self.assertFalse(self.apply(doc)['changed']);self.assertEqual(before,self.exchange.path.read_bytes())
        conflicting=copy.deepcopy(doc);conflicting['tasks'][0]['status']='done'
        with self.assertRaises(ExchangeConflict):self.apply(conflicting)
        second=copy.deepcopy(doc);second['source']['publisherId']='other';self.apply(second)
        doc['sequence']=2;doc['tasks']=[];self.apply(doc)
        all=self.exchange.snapshot()['publishers'];self.assertEqual(2,len(all));self.assertEqual([],all[self.exchange.publisher_key(doc)]['snapshot']['tasks'])
        self.assertEqual(1,len(all[self.exchange.publisher_key(second)]['snapshot']['tasks']))
        self.assertFalse(self.store.runs.path.exists())
        with closing(sqlite3.connect(self.db)) as db:self.assertEqual(1,db.execute('SELECT COUNT(*) FROM items').fetchone()[0])

    def test_conflicting_revision_preserves_snapshot_and_draft_can_repreview(self):
        doc=fixture_snapshot();first=self.exchange.preview(json.dumps(doc),'none');other=copy.deepcopy(doc);other['source']['publisherId']='second';self.apply(other)
        before=self.exchange.path.read_bytes()
        with self.assertRaises(ExchangeConflict):self.exchange.apply(first['previewToken'],'none')
        self.assertEqual(before,self.exchange.path.read_bytes());self.apply(doc)

    def test_legacy_reports_and_task_titles_remain_available(self):
        legacy=self.store.dashboard()['cicada']['tasks'][0]['taskKey'];self.store.runs.report(report(taskKey=legacy,skillIds=[]))
        self.pair();value=self.store.dashboard();self.assertEqual(legacy,value['runs'][0]['taskKey'])
        self.assertIn(legacy,value['cicada']['tasks'][0]['runTaskKeys'])
        with closing(sqlite3.connect(self.db)) as db,db:db.execute("UPDATE items SET title='Synthetic changed title'")
        self.assertEqual('Synthetic changed title',self.store.dashboard()['cicada']['tasks'][0]['title'])

    def test_invalid_optional_exchange_retains_legacy_native_view_but_blocks_pairing(self):
        with closing(sqlite3.connect(self.db)) as db,db:db.execute("UPDATE ui_state SET value='invalid' WHERE key='calendar_task_run_exchange_v1'")
        value=self.store.dashboard()['cicada'];self.assertEqual('connected',value['status']);self.assertEqual('invalid',value['source']['exchangeStatus']);self.assertEqual(1,len(value['tasks']))
        with self.assertRaises(ExchangeError):self.pair()


class RegistryValidationTests(unittest.TestCase):
    def test_hierarchy_duplicates_cycles_unpublished_fields_and_runs_rejected(self):
        valid=fixture_snapshot();self.assertEqual(valid,validate_registry(valid))
        def cycle(d):d['tasks'][0].update(parentTaskId='root',relationship='parallel')
        mutations=[cycle,lambda d:d['tasks'].append(copy.deepcopy(d['tasks'][0])),lambda d:d['tasks'][0].update(projectId='missing'),
                   lambda d:d['tasks'][0].update(prompt='private'),lambda d:d.update(runs=[{}]),lambda d:d.update(schemaVersion=True),
                   lambda d:d['tasks'][0]['localBinding'].update(taskKey='cicada-'+'0'*16+'-task-1')]
        for mutate in mutations:
            value=fixture_snapshot();mutate(value)
            with self.assertRaises(ExchangeError):validate_registry(value)

    def test_raw_duplicate_depth_size_and_nonfinite_rejected(self):
        for value in ['{"id":1,"id":2}','['*17+'0'+']'*17,'{"n":1e999}',' '*(1024*1024+1)]:
            with self.assertRaises(ExchangeError):strict_json(value)

    def test_freshness_is_separate_from_recorded_status(self):
        doc=fixture_snapshot();task=doc['tasks'][0];now=datetime.fromisoformat(doc['publishedAt'].replace('Z','+00:00'))
        self.assertEqual('fresh',freshness(doc,task,now));self.assertEqual('stale',freshness(doc,task,now+timedelta(seconds=61)))
        self.assertEqual('unknown',freshness(doc,task,now-timedelta(seconds=1)));self.assertEqual('checking',task['status'])
