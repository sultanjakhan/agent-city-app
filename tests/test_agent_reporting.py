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


if __name__=='__main__': unittest.main()
