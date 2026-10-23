import json
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent_reporting import report
from run_store import RunStore, RunError
from work_exchange import ExchangeError, WorkExchange
import desktop_bridge


class AgentReportingTests(unittest.TestCase):
    def test_exact_binding_authority_replay_and_terminal_guard(self):
        with tempfile.TemporaryDirectory() as directory:
            import hashlib
            ns='00000000-0000-4000-8000-000000000001'
            key='cicada-'+hashlib.sha256(ns.encode()).hexdigest()[:16]+'-native-task'
            binding={'sourceNamespace':ns,'sourceType':'note','sourceId':'native-task','taskKey':key}
            row={'runId':'test-run-001','sequence':1,'taskKey':key,'agent':'codex','status':'running',
                 'model':None,'provider':None,'stage':None,'inputTokens':None,'outputTokens':None,'skillIds':[],'mcpCalls':None}
            store=SimpleNamespace(cicada=SimpleNamespace(authorize_binding=Mock()),inventory=SimpleNamespace(list=lambda:[]),runs=RunStore(directory))
            store.cicada.authorize_binding.return_value={'selectedId':'production','profile':'production','sourceNamespace':ns}
            store.work_exchange=WorkExchange(directory,store.cicada,store.runs)
            payload={'binding':binding,'report':row}
            first=report(store,payload);before=store.runs.path.read_bytes()
            self.assertEqual(report(store,payload),first);self.assertEqual(before,store.runs.path.read_bytes())
            self.assertGreaterEqual(store.cicada.authorize_binding.call_count,2)
            row=dict(row,sequence=2,status='done');report(store,dict(payload,report=row))
            with self.assertRaises(RunError):report(store,dict(payload,report=dict(row,sequence=3,status='running')))
            store.cicada.authorize_binding.side_effect=ExchangeError('unknown_source_binding')
            with self.assertRaises(ExchangeError):report(store,payload)
            self.assertEqual(len(store.runs.snapshot()),1)

    def test_private_frame_does_not_expand_lifecycle_or_accept_unknown_request_fields(self):
        good={'version':1,'id':1,'action':'agent-request','draftsClosed':False,'request':{'method':'GET','path':'/api/dashboard','body':None}}
        self.assertEqual(desktop_bridge.request((json.dumps(good)+'\n').encode(),1),good)
        with self.assertRaises(ValueError):desktop_bridge.request((json.dumps(dict(good,owner='invented'))+'\n').encode(),1)
        with self.assertRaises(ValueError):desktop_bridge.request((json.dumps(dict(good,action='restart'))+'\n').encode(),1)


class PortablePreparationTests(unittest.TestCase):
    def setUp(self):
        import hashlib
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.ns = '00000000-0000-4000-8000-000000000001'
        self.binding = {'sourceNamespace': self.ns, 'sourceType': 'note', 'sourceId': 'synthetic-task',
                        'taskKey': 'cicada-' + hashlib.sha256(self.ns.encode()).hexdigest()[:16] + '-synthetic-task'}
        self.source = {'selectedId': 'production', 'profile': 'production', 'sourceNamespace': self.ns}
        self.skill = 'skill-' + 'a' * 24
        self.row = {'runId': 'synthetic-run-001', 'sequence': 1, 'taskKey': self.binding['taskKey'],
                    'agent': 'codex', 'status': 'running'}
        def authorize(binding, *, personal_only=False):
            self.assertTrue(personal_only)
            if binding != self.binding:
                raise ExchangeError('unknown_source_binding')
            return dict(self.source)
        self.context = SimpleNamespace(cicada=SimpleNamespace(authorize_binding=authorize),
                                       inventory=SimpleNamespace(list=lambda: [{'id': self.skill}]),
                                       runs=RunStore(self.temp.name))
        self.context.work_exchange = WorkExchange(self.temp.name, self.context.cicada, self.context.runs)

    def prepare(self, row=None, binding=None, context=True):
        from agent_reporting import prepare_report
        return prepare_report(json.dumps({'schemaVersion': 1, 'kind': 'cicada-run-report',
                              'binding': self.binding if binding is None else binding,
                              'report': self.row if row is None else row}),
                              context=self.context if context else None)

    def test_explicit_binding_preparation_does_not_write_and_missing_usage_is_unknown(self):
        result = self.prepare()
        self.assertTrue(result['contextChecked'])
        self.assertTrue(result['changed'])
        self.assertFalse(result['deliverySupported'])
        row = result['envelope']['report']
        for field in ('inputTokens', 'outputTokens', 'model', 'provider', 'mcpCalls'):
            self.assertIsNone(row[field])
        self.assertFalse(self.context.runs.path.exists())
        self.assertFalse(self.context.work_exchange.path.exists())
        self.assertEqual([], list(Path(self.temp.name).iterdir()))

    def test_parser_only_never_claims_native_or_sequence_checks(self):
        result = self.prepare(context=False)
        self.assertFalse(result['contextChecked'])
        self.assertIsNone(result['changed'])
        self.assertEqual(self.binding, result['envelope']['binding'])

    def test_unknown_task_source_absent_and_mismatched_bindings_rejected(self):
        import hashlib
        for ns, ident in ((self.ns, 'unknown-task'), ('00000000-0000-4000-8000-000000000002', 'synthetic-task')):
            binding = dict(self.binding, sourceNamespace=ns, sourceId=ident,
                           taskKey='cicada-' + hashlib.sha256(ns.encode()).hexdigest()[:16] + '-' + ident)
            with self.assertRaises(ExchangeError):
                self.prepare(dict(self.row, taskKey=binding['taskKey']), binding)
        for binding in ({}, dict(self.binding, taskKey='invalid')):
            with self.assertRaises(ExchangeError): self.prepare(binding=binding)
        with self.assertRaises(ExchangeError): self.prepare(dict(self.row, taskKey=None))

    def test_replay_and_monotonic_identity_rules_use_existing_run_receipt(self):
        prepared = self.prepare()['envelope']['report']
        self.context.runs.report(prepared)  # Synthetic receipt, never production.
        before = self.context.runs.path.read_bytes()
        self.assertFalse(self.prepare()['changed'])
        self.assertEqual(before, self.context.runs.path.read_bytes())
        with self.assertRaises(RunError): self.prepare(dict(self.row, status='waiting'))
        self.context.runs.report(dict(prepared, sequence=2, inputTokens=10,
                                     mcpCalls=[{'server': 'docs', 'tool': 'search', 'calls': 2}]))
        for row in (self.row, dict(self.row, sequence=3, agent='other'),
                    dict(self.row, sequence=3, model='changed'),
                    dict(self.row, sequence=3, inputTokens=9),
                    dict(self.row, sequence=3, inputTokens=10, mcpCalls=[])):
            with self.assertRaises(RunError): self.prepare(row)
        other = dict(self.binding, sourceId='other-task', taskKey=self.binding['taskKey'].replace('synthetic-task', 'other-task'))
        self.context.cicada.authorize_binding = lambda binding, **kw: dict(self.source)
        with self.assertRaises(RunError):
            self.prepare(dict(self.row, sequence=3, taskKey=other['taskKey']), other)

    def test_selected_source_receipt_cannot_change_after_pairing(self):
        original = dict(self.source)
        self.context.work_exchange.bindings = lambda: {self.binding['taskKey']: {'binding': self.binding, 'source': original}}
        self.source.update(selectedId='dev', profile='dev')
        with self.assertRaises(ExchangeError): self.prepare()
        self.source['sourceNamespace'] = '00000000-0000-4000-8000-000000000002'
        with self.assertRaises(ExchangeError): self.prepare()

    def test_skill_discovery_and_reads_are_not_applications(self):
        self.context.inventory.list()  # Read/discovering a skill does not apply it.
        self.assertEqual([], self.prepare()['envelope']['report']['skillIds'])
        self.assertEqual([self.skill], self.prepare(dict(self.row, skillIds=[self.skill]))['envelope']['report']['skillIds'])
        with self.assertRaises(RunError): self.prepare(dict(self.row, skillIds=['skill-' + 'b' * 24]))
        with self.assertRaises(ExchangeError): self.prepare(dict(self.row, skillReads=[self.skill]))

    def test_strict_ids_extensions_json_and_kind(self):
        from agent_reporting import prepare_report
        for row in (dict(self.row, runId='../invalid'), dict(self.row, durationMs=10),
                    dict(self.row, sessionId='session'), dict(self.row, skillIds=['bad']),
                    dict(self.row, inputTokens=True)):
            with self.assertRaises(ExchangeError): self.prepare(row)
        for raw in ('{"schemaVersion":1,"schemaVersion":1}', '{"n":NaN}', ' ' * (1024 * 1024 + 1),
                    json.dumps({'schemaVersion': 1, 'kind': 'cicada-task-binding', 'binding': self.binding})):
            with self.assertRaises(ExchangeError): prepare_report(raw)


if __name__ == '__main__': unittest.main()
