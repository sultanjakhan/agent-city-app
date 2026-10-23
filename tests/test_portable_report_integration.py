"""Cloud-only synthetic ingestion through existing guarded HTTP/MCP contracts."""
from contextlib import closing
import copy
import json
import sqlite3
import unittest
from unittest.mock import patch

import server
from agent_reporting import prepare_report
import test_work_exchange as exchange_tests
from test_work_exchange import binding, source_state
from tools.agent_mcp import invoke


class PortableReportIntegrationTests(unittest.TestCase):
    http_call = exchange_tests.ExchangeTests.http_call
    stop_http = exchange_tests.ExchangeTests.stop_http

    def setUp(self):
        exchange_tests.ExchangeTests.setUp(self)
        # A trusted native exchange receipt and personal task already exist.
        # The real connector authorizes them read-only; no authority is mocked.
        for path in (self.db, self.dev):
            with closing(sqlite3.connect(path)) as db, db:
                db.execute("UPDATE items SET tags=tags||',task-sphere:personal'")
        self.skill = 'skill-' + 'a' * 24
        self.inventory = patch.object(self.store.inventory, 'list', return_value=[{'id': self.skill, 'name': 'Synthetic applied skill'}])
        self.inventory.start(); self.addCleanup(self.inventory.stop)
        self.native_before = self.db.read_bytes()
        self.dev_before = self.dev.read_bytes()

    def prepare(self, **overrides):
        envelope = exchange_tests.ExchangeTests.envelope(self)
        envelope['report'].update(overrides)
        return prepare_report(json.dumps(envelope), context=self.store)

    def ingest(self, prepared, authenticated=True):
        envelope = prepared['envelope']
        # Existing MCP argument shape; no second importer or new endpoint.
        payload = {key: envelope[key] for key in ('binding', 'report')}
        return self.http_call('/api/agent/report', payload, authenticated)

    def state_bytes(self):
        return {str(path): path.read_bytes() if path.exists() else None
                for path in (self.store.runs.path, self.exchange.path)}

    def assert_rejected_unchanged(self, prepared, status=None):
        before = self.state_bytes()
        native = self.db.read_bytes(), self.dev.read_bytes()
        code, _ = self.ingest(prepared)
        self.assertIn(code, (400, 409))
        if status is not None: self.assertEqual(status, code)
        self.assertEqual(before, self.state_bytes())
        self.assertEqual(native, (self.db.read_bytes(), self.dev.read_bytes()))

    def dashboard(self):
        code, value = self.http_call('/api/dashboard')
        self.assertEqual(200, code)
        return value

    def test_prepared_mcp_report_is_task_visible_replay_updates_and_reopens(self):
        prepared = self.prepare(skillIds=[self.skill], inputTokens=17, outputTokens=3)
        self.assertEqual({str(self.store.runs.path): None, str(self.exchange.path): None}, self.state_bytes())
        test = self
        class SyntheticHttpTransport:
            def call(self, request):
                test.assertEqual('POST', request['method'])
                test.assertEqual('/api/agent/report', request['path'])
                code, result = test.http_call(request['path'], request['body'])
                test.assertEqual(200, code)
                return result
        payload = {key: prepared['envelope'][key] for key in ('binding', 'report')}
        first = invoke('agent-city', SyntheticHttpTransport(), 'agent_city_report_run', payload)
        before = self.state_bytes()
        self.assertEqual((200, first), self.ingest(prepared))
        self.assertEqual(before, self.state_bytes())
        value = self.dashboard()
        self.assertEqual(['task-1'], [task['sourceId'] for task in value['cicada']['tasks']])
        task = value['cicada']['tasks'][0]
        self.assertEqual(binding()['taskKey'], task['taskKey'])
        self.assertEqual(1, len(value['runs']))
        run = value['runs'][0]
        self.assertEqual(task['taskKey'], run['taskKey'])
        self.assertEqual((17, 3, [self.skill]), (run['inputTokens'], run['outputTokens'], run['skillIds']))
        newer = self.prepare(sequence=2, status='done', skillIds=[self.skill], inputTokens=23, outputTokens=5)
        self.assertEqual(200, self.ingest(newer)[0])
        run = self.dashboard()['runs'][0]
        self.assertEqual((2, 23, 5, 'done'), (run['sequence'], run['inputTokens'], run['outputTokens'], run['status']))
        self.assertEqual(first['run']['runId'], run['runId'])
        self.assertEqual(1, len(self.dashboard()['runs']))
        # Reopen the actual Store, not just its in-memory projection.
        reopened = server.Store(self.root/'panel', local_only=True, executable=False, skills_root=self.skills,
                               codex_home=self.root/'codex', repo_roots=[self.root/'repos'],
                               inventory_roots=[('worktree', self.skills)],
                               cicada_candidates=[{'id': 'production', 'profile': 'production', 'label': 'Synthetic production', 'path': str(self.db)},
                                                  {'id': 'dev', 'profile': 'dev', 'label': 'Synthetic DEV', 'path': str(self.dev)}])
        with patch.object(reopened.inventory, 'list', return_value=[{'id': self.skill, 'name': 'Synthetic applied skill'}]):
            value = reopened.dashboard()
        self.assertEqual(['task-1'], [task['sourceId'] for task in value['cicada']['tasks']])
        self.assertEqual([run], value['runs'])
        self.assertEqual(self.native_before, self.db.read_bytes())
        self.assertEqual(self.dev_before, self.dev.read_bytes())
        with closing(sqlite3.connect(self.db)) as db:
            self.assertEqual([('task-1', 0, 'task', 1)], db.execute('SELECT id,completed,status,version FROM items').fetchall())
            self.assertEqual([(1, 1, None)], db.execute('SELECT id,is_active,duration_seconds FROM timeline_blocks').fetchall())

    def test_missing_measurements_and_inventory_reads_remain_unknown_or_unapplied(self):
        self.store.inventory.list()
        prepared = self.prepare()
        self.assertEqual(200, self.ingest(prepared)[0])
        run = self.dashboard()['runs'][0]
        for key in ('inputTokens', 'outputTokens', 'mcpCalls', 'provider', 'model'):
            self.assertIsNone(run[key])
        self.assertEqual([], run['skillIds'])
        self.assertEqual([], run['skills'])
        for key in prepared['unavailableFields']:
            self.assertNotIn(key, run)
        self.assertIn('updatedAt', run)  # Receipt time only; no duration is invented.
        self.assertEqual(self.native_before, self.db.read_bytes())

    def test_stale_sequence_and_executor_or_task_drift_rejected_after_preparation(self):
        first = self.prepare()
        stale = self.prepare()
        self.assertEqual(200, self.ingest(first)[0])
        newer = self.prepare(sequence=2)
        self.assertEqual(200, self.ingest(newer)[0])
        self.assert_rejected_unchanged(stale, 409)
        for change in ({'agent': 'other'}, {'taskKey': binding(source_id='other-task')['taskKey']}):
            altered = copy.deepcopy(newer)
            altered['envelope']['report'].update(sequence=3, **change)
            self.assert_rejected_unchanged(altered, 400)

    def test_source_namespace_and_profile_drift_rejected_at_import(self):
        self.assertEqual(200, self.ingest(self.prepare())[0])
        prepared = self.prepare(sequence=2)
        self.store.cicada.select('dev', self.store.cicada.settings()['revision'])
        self.assert_rejected_unchanged(prepared, 400)
        self.store.cicada.select('production', self.store.cicada.settings()['revision'])
        state = source_state(); state['sourceNamespace'] = '22222222-2222-4222-8222-222222222222'
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("UPDATE ui_state SET value=? WHERE key='calendar_task_run_exchange_v1'", (json.dumps(state),))
        self.assert_rejected_unchanged(prepared, 400)

    def test_revoked_authority_after_prepare_never_pairs_or_writes_run(self):
        prepared = self.prepare()
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("UPDATE items SET tags='task-sphere:work'")
        self.assert_rejected_unchanged(prepared, 400)
        self.assertFalse(self.store.runs.path.exists())
        self.assertFalse(self.exchange.path.exists())

    def test_owner_csrf_and_existing_import_preview_revision_guards(self):
        prepared = self.prepare()
        before = self.state_bytes()
        self.assertEqual(403, self.ingest(prepared, authenticated=False)[0])
        self.assertEqual(before, self.state_bytes())
        # The nested v1 envelope also works unchanged via existing import,
        # after the report entry point has explicitly paired the native task.
        self.assertEqual(200, self.ingest(prepared)[0])
        envelope = self.prepare(sequence=2)['envelope']
        revision = self.exchange.snapshot()['revision']
        code, preview = self.http_call('/api/work-exchange/preview', {'document': json.dumps(envelope), 'revision': revision})
        self.assertEqual(200, code)
        before = self.state_bytes()
        self.assertEqual(409, self.http_call('/api/work-exchange/apply', {'previewToken': preview['previewToken'], 'revision': 'wrong'})[0])
        self.assertEqual(before, self.state_bytes())
        self.assertEqual(200, self.http_call('/api/work-exchange/apply', {'previewToken': preview['previewToken'], 'revision': revision})[0])
        self.assertEqual(2, self.dashboard()['runs'][0]['sequence'])
        self.assertEqual(1, len(self.dashboard()['runs']))
        # Applying rechecks native authority even after a successful preview.
        envelope['report']['sequence'] = 3
        code, preview = self.http_call('/api/work-exchange/preview', {'document': json.dumps(envelope), 'revision': revision})
        self.assertEqual(200, code)
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("UPDATE ui_state SET value=? WHERE key='calendar_task_run_exchange_v1'", (json.dumps(dict(source_state(), bindings={})),))
        before = self.state_bytes()
        self.assertEqual(400, self.http_call('/api/work-exchange/apply', {'previewToken': preview['previewToken'], 'revision': revision})[0])
        self.assertEqual(before, self.state_bytes())


if __name__ == '__main__': unittest.main()
