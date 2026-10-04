import copy
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from agent_hooks import process, outbox_status, resolve_attempt
from agent_mcp import NativeTaskError


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


class IsolatedNative(Native):
    def __init__(self, reject_codes=()):
        super().__init__(); self.reject_codes=list(reject_codes); self.calls=[]; self.current_version=1
    def call(self, request):
        self.calls.append(copy.deepcopy(request))
        if request['action'] == 'get': return {'version':self.current_version}
        if self.reject_codes and request['action'] in ('begin','report'):
            code=self.reject_codes.pop(0)
            raise NativeTaskError({'error':code})
        return super().call(request)


class AmbiguousNative(Native):
    def __init__(self):
        super().__init__(); self.first=True; self.calls=[]
    def call(self, request):
        if request['action'] == 'begin':
            self.calls.append(copy.deepcopy(request))
            result=super().call(request)
            if self.first:
                self.first=False
                raise RuntimeError('outcome_unknown')
            return result
        return super().call(request)


class FirstTransientNative(Native):
    def __init__(self):
        super().__init__(); self.calls=[]
    def call(self, request):
        self.calls.append(copy.deepcopy(request))
        if request['action'] == 'begin' and request['body']['report']['runId'] == 'codex-' + hashlib.sha256('first:t1'.encode()).hexdigest()[:32]:
            raise RuntimeError('outcome_unknown')
        return super().call(request)


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

    def test_definite_rejection_does_not_block_another_session_and_blocks_followup(self):
        with tempfile.TemporaryDirectory() as root:
            config={'personalRoots':[root],'outbox':str(Path(root)/'outbox.db')}
            native=IsolatedNative(['task_archived']); city=City(); city.fail=False; first=dict(session_id='first',turn_id='t1',cwd=root,hook_event_name='UserPromptSubmit',model='m')
            process(config,'codex',first,(native,city)); process(config,'codex',dict(first,hook_event_name='PreToolUse'),(native,city))
            process(config,'codex',dict(first,hook_event_name='PreToolUse'),(native,city))
            second=dict(session_id='second',turn_id='t2',cwd=root,hook_event_name='UserPromptSubmit',model='m')
            process(config,'codex',second,(native,city)); process(config,'codex',dict(second,hook_event_name='PreToolUse'),(native,city))
            self.assertEqual([r['runId'].split('-',1)[0] for r in city.reports],['codex'])
            rows=outbox_status(config); self.assertEqual([r['state'] for r in rows],['rejected'])
            self.assertEqual(rows[0]['error']['code'],'task_archived')
            with self.assertRaisesRegex(ValueError,'restore_original_task_required'):
                resolve_attempt(config,rows[0]['operationId'],(native,city))
            self.assertEqual(len(city.reports),1)
            with closing(sqlite3.connect(config['outbox'])) as db:
                self.assertEqual(db.execute('SELECT count(*) FROM outbox').fetchone()[0],0)
                self.assertEqual(db.execute('SELECT count(*) FROM outbox_history').fetchone()[0],1)

    def test_transient_failure_is_retried_later_but_other_session_still_drains(self):
        with tempfile.TemporaryDirectory() as root:
            config={'personalRoots':[root],'outbox':str(Path(root)/'outbox.db')}
            native=FirstTransientNative(); city=City(); city.fail=False; first=dict(session_id='first',turn_id='t1',cwd=root,hook_event_name='UserPromptSubmit',model='m')
            process(config,'codex',first,(native,city))
            with self.assertRaises(RuntimeError):
                process(config,'codex',dict(first,hook_event_name='PreToolUse'),(native,city))
            second=dict(session_id='second',turn_id='t2',cwd=root,hook_event_name='UserPromptSubmit',model='m')
            with self.assertRaises(RuntimeError):
                process(config,'codex',second,(native,city))
            with self.assertRaises(RuntimeError):
                process(config,'codex',dict(second,hook_event_name='PreToolUse'),(native,city))
            self.assertEqual(len(city.reports),1)
            self.assertEqual(city.reports[0]['runId'], 'codex-' + hashlib.sha256('second:t2'.encode()).hexdigest()[:32])

    def test_task_version_conflict_resolution_refreshes_version_and_keeps_history(self):
        with tempfile.TemporaryDirectory() as root:
            config={'personalRoots':[root],'outbox':str(Path(root)/'outbox.db')}
            native=IsolatedNative(); city=City(); city.fail=False; event=dict(session_id='session',turn_id='turn',cwd=root,hook_event_name='UserPromptSubmit',model='m')
            process(config,'codex',event,(native,city))
            with patch('agent_hooks.time.time',return_value=1000):
                process(config,'codex',dict(event,hook_event_name='PreToolUse'),(native,city))
            native.reject_codes=['task_version_conflict']
            with patch('agent_hooks.time.time',return_value=1060):
                process(config,'codex',dict(event,hook_event_name='PreToolUse'),(native,city))
            # The first begin is the definite conflict and remains immutable.
            conflict=outbox_status(config)[0]['operationId']; native.current_version=7
            with closing(sqlite3.connect(config['outbox'])) as db:
                failed=json.loads(db.execute('SELECT value FROM outbox_history').fetchone()[0])
                later=dict(failed, operationId='later-operation', state='pending',
                           report=dict(failed['report'], sequence=3), payload=None, native=None)
                db.execute('INSERT INTO outbox(id,value) VALUES(?,?)', (3,json.dumps(later)))
                db.commit()
            replacement=resolve_attempt(config,conflict,(native,city))
            self.assertNotEqual(conflict,replacement)
            pending=outbox_status(config); self.assertEqual([r['state'] for r in pending],['conflict','pending','pending'])
            with closing(sqlite3.connect(config['outbox'])) as db:
                queued=[json.loads(raw) for (raw,) in db.execute('SELECT value FROM outbox_history ORDER BY queue_id')]
                queued += [json.loads(raw) for (raw,) in db.execute('SELECT value FROM outbox ORDER BY id')]
            replacement_row=next(row for row in queued if row['operationId']==replacement)
            self.assertEqual(replacement_row['payload']['expectedVersion'],7)
            with patch('agent_hooks.time.time',return_value=1120):
                process(config,'codex',dict(event,hook_event_name='PreToolUse'),(native,city))
            self.assertEqual([r['sequence'] for r in city.reports],[1,2,3])
            with closing(sqlite3.connect(config['outbox'])) as db:
                rows=[json.loads(raw) for (raw,) in db.execute('SELECT value FROM outbox_history ORDER BY queue_id')]
            self.assertEqual(rows[0]['operationId'],conflict); self.assertEqual(rows[0]['state'],'conflict')
            with self.assertRaises(ValueError):
                resolve_attempt(config,conflict,(native,city))

    def test_missing_configured_root_does_not_hide_valid_root(self):
        with tempfile.TemporaryDirectory() as root:
            config={'personalRoots':[str(Path(root)/'removed'),root],'outbox':str(Path(root)/'outbox.db')}
            native=Native(); city=City(); city.fail=False; event=dict(session_id='session',turn_id='turn',cwd=root,hook_event_name='UserPromptSubmit',model='m')
            process(config,'codex',event,(native,city)); process(config,'codex',dict(event,hook_event_name='PreToolUse'),(native,city))
            self.assertEqual(len(city.reports),1)

    def test_ambiguous_native_replay_keeps_exact_operation_and_payload(self):
        with tempfile.TemporaryDirectory() as root:
            config={'personalRoots':[root],'outbox':str(Path(root)/'outbox.db')}
            native=AmbiguousNative(); city=City(); city.fail=False; event=dict(session_id='session',turn_id='turn',cwd=root,hook_event_name='UserPromptSubmit',model='m')
            process(config,'codex',event,(native,city))
            with self.assertRaises(RuntimeError):
                process(config,'codex',dict(event,hook_event_name='PreToolUse'),(native,city))
            with closing(sqlite3.connect(config['outbox'])) as db:
                before=json.loads(db.execute('SELECT value FROM outbox').fetchone()[0])
            process(config,'codex',dict(event,hook_event_name='PreToolUse'),(native,city))
            self.assertEqual(len(native.calls),2)
            self.assertEqual(native.calls[0]['operation_id'],native.calls[1]['operation_id'])
            self.assertEqual(native.calls[0]['body'],native.calls[1]['body'])
            self.assertEqual(before['operationId'],native.calls[0]['operation_id'])


if __name__=='__main__':unittest.main()
