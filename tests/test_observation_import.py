"""Synthetic personal task only; no native executor binding or timer changes."""
from contextlib import closing
import copy
import hashlib
import json
import sqlite3
import unittest
from unittest.mock import patch

import server
import test_work_exchange as fixtures
from observation_store import FIELDS, ObservationError, ObservationStore, validate
from tools.agent_mcp import invoke


STAMP = '2026-01-01T10:00:00Z'


def field(value=None, source='synthetic-executor-event', at=STAMP):
    return {'value': value, 'source': source if value is not None else None,
            'observedAt': at if value is not None else None}


def bundle(task):
    return {'schemaVersion': 1, 'kind': 'task-observation-bundle', 'observationId': 'synthetic-observation-1',
            'sequence': 1, 'task': task, 'exporter': {'id': 'synthetic-exporter', 'source': 'synthetic-event-stream'},
            'observedAt': STAMP, 'exportedAt': STAMP,
            'coverage': {'kind':'attempt','attemptId':'synthetic-attempt-1','startedAt':None,'endedAt':None,'source':'synthetic-attempt-event'},
            'fields': {key: field() for key in FIELDS},
            'skillApplications': None}


class ObservationIntegrationTests(unittest.TestCase):
    http_call = fixtures.ExchangeTests.http_call
    stop_http = fixtures.ExchangeTests.stop_http

    def setUp(self):
        fixtures.ExchangeTests.setUp(self)
        # Remove the native exchange receipt altogether: observations need none.
        for path in (self.db, self.dev):
            with closing(sqlite3.connect(path)) as db, db:
                db.execute('DELETE FROM ui_state')
                db.execute("UPDATE items SET tags='task-sphere:personal'")
                db.execute('DELETE FROM timeline_blocks')
        key = hashlib.sha256(str(self.db.resolve()).encode()).hexdigest()[:16]
        self.task = {'profile': 'production', 'sourceKey': key, 'sourceId': 'task-1', 'taskKey': 'cicada-' + key + '-task-1'}
        self.doc = bundle(self.task)
        self.source_before = self.db.read_bytes(), self.dev.read_bytes()
        # Any accidental routing through execution-authoritative code fails.
        for target, method in ((self.store.runs, 'report'), (self.store.work_exchange, 'apply'), (self.store.cicada, 'authorize_binding')):
            guard = patch.object(target, method, side_effect=AssertionError('execution_path_forbidden'))
            guard.start(); self.addCleanup(guard.stop)

    def preview(self, doc=None, raw=None):
        return self.http_call('/api/observations/preview', {'document': raw if raw is not None else json.dumps(doc if doc is not None else self.doc)})

    def approve(self, preview):
        return self.http_call('/api/observations/import', {key: preview[key] for key in ('previewToken', 'revision')})

    def ingest(self, doc=None):
        code, preview = self.preview(doc); self.assertEqual(200, code, preview)
        code, result = self.approve(preview); self.assertEqual(200, code, result)
        return result

    def projection(self):
        code, result = self.http_call('/api/dashboard'); self.assertEqual(200, code)
        self.assertEqual([], result['runs'])
        self.assertFalse(self.store.runs.path.exists()); self.assertFalse(self.exchange.path.exists())
        return result['importedObservations']

    def test_owner_import_dashboard_update_replay_reopen_and_source_unchanged(self):
        doc = copy.deepcopy(self.doc)
        doc['fields'].update(sessionId=field('synthetic-session'), parentSessionId=field('synthetic-parent'),
                             model=field('synthetic-model'), inputTokens=field(123), outputTokens=field(12),
                             startedAt=field('2026-01-01T09:59:00Z'), endedAt=field(STAMP), durationMs=field(60000))
        doc['skillApplications'] = [{'skillId': 'synthetic-skill', 'evidenceId': 'synthetic-application-event', 'source': 'synthetic-apply-hook', 'observedAt': STAMP, 'kind': 'applied'}]
        raw = json.dumps(doc)
        code, preview = self.preview(raw=raw); self.assertEqual(200, code)
        self.assertFalse(self.store.observations.path.exists())
        self.assertEqual(200, self.approve(preview)[0])
        rows = self.projection()['rows']; self.assertEqual(1, len(rows))
        row = rows[0]
        self.assertEqual('task-1', row['task']['sourceId'])
        self.assertEqual(self.task, row['bundle']['task'])
        self.assertEqual(doc['fields'], row['bundle']['fields'])
        self.assertEqual(doc['skillApplications'], row['bundle']['skillApplications'])
        self.assertEqual(hashlib.sha256(raw.encode()).hexdigest(), row['bundleHash'])
        self.assertEqual(('imported', True, False), (row['origin'], row['readOnly'], row['independentlyVerified']))
        before = self.store.observations.path.read_bytes()
        self.assertFalse(self.ingest(doc)['changed']); self.assertEqual(before, self.store.observations.path.read_bytes())
        newer = copy.deepcopy(doc); newer['sequence'] = 2; newer['fields']['inputTokens'] = field(140)
        self.ingest(newer)
        # Historical exact replay is a no-op, not a rollback.
        before = self.store.observations.path.read_bytes(); self.assertFalse(self.ingest(doc)['changed'])
        self.assertEqual(before, self.store.observations.path.read_bytes())
        rows = self.projection()['rows']; self.assertEqual(1, len(rows)); self.assertEqual(140, rows[0]['bundle']['fields']['inputTokens']['value'])
        self.assertEqual(2, len(rows[0]['receipts']))
        reopened = server.Store(self.root/'panel', local_only=True, executable=False, skills_root=self.skills,
                                codex_home=self.root/'codex', repo_roots=[self.root/'repos'],
                                inventory_roots=[('worktree', self.skills)],
                                cicada_candidates=[{'id':'production','profile':'production','label':'Synthetic production','path':str(self.db)},
                                                   {'id':'dev','profile':'dev','label':'Synthetic DEV','path':str(self.dev)}])
        self.assertEqual(self.projection(), reopened.dashboard()['importedObservations'])
        self.assertEqual(self.source_before, (self.db.read_bytes(), self.dev.read_bytes()))
        with closing(sqlite3.connect(self.db)) as db:
            self.assertEqual([('task-1', 0, 1, 'task')], db.execute('SELECT id,completed,version,status FROM items').fetchall())
            self.assertEqual([], db.execute('SELECT * FROM timeline_blocks').fetchall())

    def test_missing_measurements_never_become_zero_or_inventory_applications(self):
        self.store.inventory.list()
        self.ingest()
        row = self.projection()['rows'][0]
        self.assertEqual({key: field() for key in FIELDS}, row['bundle']['fields'])
        self.assertIsNone(row['bundle']['skillApplications'])
        self.assertIsNotNone(row['importedAt'])
        self.assertIsNone(row['bundle']['fields']['durationMs']['value'])
        self.assertEqual(self.source_before, (self.db.read_bytes(), self.dev.read_bytes()))

    def test_source_task_profile_mismatch_and_personal_scope_rejected_without_writes(self):
        for changes in ({'profile': 'dev'}, {'sourceKey': '0'*16, 'taskKey': 'cicada-'+'0'*16+'-task-1'},
                        {'sourceId': 'unknown-task', 'taskKey': 'cicada-'+self.task['sourceKey']+'-unknown-task'}, {'taskKey': 'bad'}):
            doc = copy.deepcopy(self.doc); doc['task'].update(changes)
            self.assertEqual(400, self.preview(doc)[0])
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("UPDATE items SET tags='task-sphere:work'")
        self.assertEqual(400, self.preview()[0])
        self.assertFalse(self.store.observations.path.exists())

    def test_out_of_order_counter_and_identity_changes_conflict_without_writes(self):
        self.ingest()
        newer = copy.deepcopy(self.doc); newer['sequence'] = 3; newer['fields']['inputTokens'] = field(9)
        self.ingest(newer); before = self.store.observations.path.read_bytes()
        for change in ('stale', 'counter', 'exporter', 'task'):
            doc = copy.deepcopy(newer); doc['sequence'] = 4
            if change == 'stale': doc['sequence'] = 2
            elif change == 'counter': doc['fields']['inputTokens'] = field(8)
            elif change == 'exporter': doc['exporter']['id'] = 'other-exporter'
            else:
                with closing(sqlite3.connect(self.db)) as db, db:
                    db.execute("UPDATE items SET id='other-task'")
                doc['task'].update(sourceId='other-task', taskKey='cicada-'+self.task['sourceKey']+'-other-task')
            self.assertEqual(409, self.preview(doc)[0])
            self.assertEqual(before, self.store.observations.path.read_bytes())

    def test_apply_rechecks_personal_source_and_revision_and_requires_owner(self):
        code, preview = self.preview(); self.assertEqual(200, code)
        self.assertEqual(403, self.http_call('/api/observations/import', {key: preview[key] for key in ('previewToken','revision')}, authenticated=False)[0])
        self.assertEqual(409, self.http_call('/api/observations/import', {'previewToken': preview['previewToken'], 'revision': 'wrong'})[0])
        self.store.cicada.select('dev', self.store.cicada.settings()['revision'])
        self.assertEqual(400, self.approve(preview)[0])
        self.store.cicada.select('production', self.store.cicada.settings()['revision'])
        with closing(sqlite3.connect(self.db)) as db, db: db.execute("UPDATE items SET tags='task-sphere:work'")
        self.assertEqual(400, self.approve(preview)[0])
        self.assertFalse(self.store.observations.path.exists())
        # Import paths are intentionally absent from agent grant/MCP allowlists.
        with self.assertRaises(ValueError): self.http.owner_sessions.issue_grant('POST', '/api/observations/import', {})
        with self.assertRaises(ValueError): invoke('agent-city', None, 'agent_city_import_observations', {})

    def test_saved_observation_is_unavailable_after_source_or_personal_scope_changes(self):
        self.ingest(); before = self.store.observations.path.read_bytes()
        self.store.cicada.select('dev', self.store.cicada.settings()['revision'])
        projection = self.projection()
        self.assertEqual([], projection['rows']); self.assertEqual(1, projection['unavailableCount'])
        self.store.cicada.select('production', self.store.cicada.settings()['revision'])
        self.assertEqual(1, len(self.projection()['rows']))
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("UPDATE items SET tags='task-sphere:work'")
        projection = self.projection()
        self.assertEqual([], projection['rows']); self.assertEqual(1, projection['unavailableCount'])
        self.assertEqual(before, self.store.observations.path.read_bytes())

    def test_bounded_coverage_rejects_thread_totals_and_preserves_multiple_attempts(self):
        snapshot = copy.deepcopy(self.doc)
        snapshot['coverage'] = {'kind':'metadata-snapshot','attemptId':None,'startedAt':None,'endedAt':None,'source':'synthetic-runtime-snapshot'}
        snapshot['fields']['sessionId'] = field('synthetic-session')
        self.ingest(snapshot)
        attributed = copy.deepcopy(snapshot); attributed['sequence'] = 2
        attributed['fields']['inputTokens'] = field(9999, source='synthetic-thread-total')
        self.assertEqual(400, self.preview(attributed)[0])
        other = copy.deepcopy(self.doc); other['observationId'] = 'synthetic-observation-2'
        other['coverage']['attemptId'] = 'synthetic-attempt-2'
        other['fields']['sessionId'] = field('synthetic-subagent-session')
        self.ingest(other)
        rows = self.projection()['rows']; self.assertEqual(2, len(rows))
        self.assertEqual({'task-1'}, {row['bundle']['task']['sourceId'] for row in rows})
        self.assertEqual(self.source_before, (self.db.read_bytes(), self.dev.read_bytes()))
        unscoped = copy.deepcopy(self.doc); del unscoped['coverage']
        self.assertEqual(400, self.preview(unscoped)[0])

    def test_original_bytes_hash_tamper_and_stale_preview_fail_closed(self):
        code, first = self.preview(); self.assertEqual(200, code)
        self.ingest()
        before = self.store.observations.path.read_bytes()
        self.assertEqual(409, self.approve(first)[0])
        self.assertEqual(before, self.store.observations.path.read_bytes())
        # Same semantic content with different original bytes is not exact replay.
        self.assertEqual(409, self.preview(raw=json.dumps(self.doc, indent=2))[0])
        data = json.loads(before)
        data['receipts'][0]['bundleHash'] = '0'*64
        self.store.observations.path.write_text(json.dumps(data))
        with self.assertRaises(ObservationError): self.store.observations.projection()
        self.store.observations.path.write_bytes(before)
        self.assertEqual(1, len(self.projection()['rows']))

    def test_strict_bundle_bounded_metadata_and_application_evidence(self):
        for key in ('prompts', 'messages', 'reasoning', 'toolArguments', 'credentials', 'logs', 'tasks'):
            doc = copy.deepcopy(self.doc); doc[key] = 'forbidden'
            self.assertEqual(400, self.preview(doc)[0])
        for mutate in (lambda d: d['fields']['inputTokens'].update(value=True,source='synthetic',observedAt=STAMP),
                       lambda d: d['fields']['sessionId'].update(value='../path',source='synthetic',observedAt=STAMP),
                       lambda d: d.update(skillApplications=[{'skillId':'s','evidenceId':'e','source':'inventory','observedAt':STAMP,'kind':'read'}])):
            doc = copy.deepcopy(self.doc); mutate(doc); self.assertEqual(400, self.preview(doc)[0])
        for raw in ('{"schemaVersion":1,"schemaVersion":1}', '{"x":NaN}', ' ' * 32769):
            self.assertEqual(400, self.preview(raw=raw)[0])
        self.assertFalse(self.store.observations.path.exists())


if __name__ == '__main__': unittest.main()
