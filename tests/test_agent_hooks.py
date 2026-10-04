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
from agent_hooks import process


class Native:
    def __init__(self): self.receipts={}; self.created=0
    def call(self, request):
        if request['action']=='get': return {'version':1}
        op=request['operation_id']
        if op in self.receipts: return copy.deepcopy(self.receipts[op])
        body=request['body']; self.created+=int(request['action']=='begin' and body['taskId'] is None)
        report=dict(body['report'],taskKey='cicada-'+'a'*16+'-synthetic-task')
        result={'task':{'id':'synthetic-task','version':1},'binding':{'taskKey':report['taskKey']},'report':report}
        self.receipts[op]=result;return copy.deepcopy(result)


class City:
    def __init__(self):self.fail=True;self.reports=[]
    def call(self, request):
        if self.fail: raise RuntimeError('outcome_unknown')
        self.reports.append(request['body']['report']);return {'recorded':True}


class HookTests(unittest.TestCase):
    def test_real_tool_activity_refreshes_same_run_throttled_and_stop_uses_next_sequence(self):
        with tempfile.TemporaryDirectory() as root:
            config={'personalRoots':[root],'outbox':str(Path(root)/'outbox.db')}
            native=Native();city=City();city.fail=False
            event=dict(session_id='synthetic-session',turn_id='synthetic-turn',cwd=root,hook_event_name='UserPromptSubmit',model='observed-model')
            process(config,'codex',event,(native,city))
            for now in (1000,1001,1059,1060,1061,1120):
                with patch('agent_hooks.time.time',return_value=now):
                    process(config,'codex',dict(event,hook_event_name='PreToolUse'),(native,city))
            self.assertEqual(native.created,1)
            self.assertEqual([r['sequence'] for r in city.reports],[1,2,3])
            self.assertEqual(len({r['runId'] for r in city.reports}),1)
            process(config,'codex',dict(event,hook_event_name='Stop'),(native,city))
            self.assertEqual(city.reports[-1]['sequence'],4)
            self.assertEqual(city.reports[-1]['status'],'done')

    def test_pending_refresh_replays_exact_receipt_without_adding_more_during_outage(self):
        with tempfile.TemporaryDirectory() as root:
            config={'personalRoots':[root],'outbox':str(Path(root)/'outbox.db')}
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
            self.assertEqual(native.created,1)

    def test_outage_replays_start_before_stop_without_duplicate_and_preserves_no_text(self):
        with tempfile.TemporaryDirectory() as root:
            config={'personalRoots':[root],'outbox':str(Path(root)/'outbox.db')}
            native=Native();city=City()
            event=dict(session_id='synthetic-session',turn_id='synthetic-turn',cwd=root,hook_event_name='UserPromptSubmit',model='observed-model',prompt='SECRET_SENTINEL',transcript_path='SECRET_PATH')
            process(config,'codex',event,(native,city));self.assertEqual(native.created,0)
            with self.assertRaises(RuntimeError):process(config,'codex',dict(event,hook_event_name='PreToolUse'),(native,city))
            self.assertEqual(native.created,1)
            city.fail=False
            process(config,'codex',dict(event,hook_event_name='Stop'),(native,city))
            self.assertEqual(native.created,1);self.assertEqual([row['status'] for row in city.reports],['running','done'])
            self.assertEqual([row['sequence'] for row in city.reports],[1,2])
            self.assertNotIn(b'SECRET',Path(config['outbox']).read_bytes())
            with closing(sqlite3.connect(config['outbox'])) as db:self.assertEqual(db.execute('SELECT count(*) FROM outbox').fetchone()[0],0)
            process(config,'codex',dict(event,hook_event_name='Stop'),(native,city));self.assertEqual(len(city.reports),2)
    def test_unregistered_scope_never_creates_outbox_or_reports(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as foreign:
            config={'personalRoots':[root],'outbox':str(Path(root)/'outbox.db')}
            process(config,'codex',dict(cwd=foreign),())
            self.assertFalse(Path(config['outbox']).exists())
    def test_text_only_finished_turn_is_recorded_after_observed_completion(self):
        with tempfile.TemporaryDirectory() as root:
            config={'personalRoots':[root],'outbox':str(Path(root)/'outbox.db')};native=Native();city=City();city.fail=False
            event=dict(session_id='synthetic-session',turn_id='synthetic-turn',cwd=root,hook_event_name='UserPromptSubmit',model='observed-model')
            process(config,'codex',event,(native,city));self.assertEqual(native.created,0)
            process(config,'codex',dict(event,hook_event_name='Stop'),(native,city));self.assertEqual(native.created,1)
            self.assertEqual([r['status'] for r in city.reports],['running','done'])


if __name__=='__main__':unittest.main()
