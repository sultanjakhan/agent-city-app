"""Synthetic frozen collector interface plus actual read-only SQLite connector."""
import copy
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from cicada_connector import CicadaConnector
from passive_attempts import BoundLiveSessions, BindingError, validate
from test_dashboard_http import make_cicada

AT='2026-01-01T10:00:00Z'


class PassiveAttemptTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.db=self.root/'source.db';make_cicada(self.db)
        with closing(sqlite3.connect(self.db)) as db,db:
            db.execute("UPDATE items SET tags='task-sphere:personal'")
            db.execute('DELETE FROM timeline_blocks')
        key=hashlib.sha256(str(self.db.resolve()).encode()).hexdigest()[:16]
        self.task={'profile':'production','sourceKey':key,'sourceId':'task-1','taskKey':'cicada-'+key+'-task-1'}
        self.connector=CicadaConnector(self.root,[{'id':'production','profile':'production','label':'Synthetic','path':str(self.db)}])
        self.binding={'schemaVersion':1,'kind':'passive-attempt-binding','bindingId':'synthetic-owner-approval',
                      'sessionId':'synthetic-session','turnId':'current-turn','task':self.task,
                      'nativeTaskKey':'cicada-'+'f'*16+'-task-1','approvedAt':AT,'appliedSkills':None}
        self.data={'source':{'status':'connected'},'sessions':[{'id':'synthetic-session','projectId':'synthetic-project','agentId':'synthetic-agent',
                   'task':'OLD THREAD GOAL','result':'OLD RESULT','model':'old-session-model','usage':{'total':99999},
                   'tokens':99999,'skills':['read-only-skill'],'stages':[
                       {'id':'past-turn','usage':{'total':88888},'model':'past-model'},
                       {'id':'current-turn','startedAt':AT,'endedAt':None,'durationMs':None,'status':'running',
                        'usage':{'input':7,'output':None,'total':None},'events':[{'id':'read-event','kind':'read','skill':'read-only-skill','detail':'must-not-be-copied'}]}]},
                       {'id':'unrelated-session','usage':{'total':42},'stages':[]}]}
        data=self.data
        class Collector:
            def snapshot(self):return copy.deepcopy(data)
        self.wrapper=BoundLiveSessions(Collector(),self.connector,self.root,sessions_path=('sessions',),identity_fields=('projectId','agentId'))
        self.before=self.db.read_bytes()

    def save(self):
        (self.root/'passive-attempt-binding.json').write_text(json.dumps(self.binding))

    def test_exact_turn_task_identity_no_thread_totals_and_unrelated_rows_unchanged(self):
        self.save();result=self.wrapper.snapshot();row=result['sessions'][0]
        self.assertEqual('bound',result['attemptBinding']['status'])
        self.assertEqual(['current-turn'],[s['id'] for s in row['stages']])
        self.assertEqual({'input':7,'output':None,'total':None,'cachedInput':None,'reasoningOutput':None},row['usage'])
        self.assertIsNone(row['model']);self.assertNotIn('tokens',row)
        self.assertEqual([],row['skills']);self.assertEqual([],row['stages'][0]['events'])
        self.assertFalse(row['attemptBinding']['skillsKnown'])
        for key,value in self.task.items():self.assertIn(value,row['task'])
        self.assertEqual(self.binding['nativeTaskKey'],row['attemptBinding']['nativeTaskKey'])
        self.assertNotEqual(self.task['taskKey'],row['attemptBinding']['nativeTaskKey'])
        self.assertEqual(self.data['sessions'][1],result['sessions'][1])
        self.assertEqual('OLD THREAD GOAL',self.data['sessions'][0]['task'])
        self.assertEqual(self.before,self.db.read_bytes())
        self.assertEqual(self.wrapper.snapshot(),result)

    def test_explicit_application_is_executor_reported_never_a_read(self):
        self.binding['appliedSkills']=[{'id':'synthetic-applied','turnId':'current-turn','skill':'Synthetic skill','at':AT,'kind':'applied','source':'executor-reported'}]
        self.save();row=self.wrapper.snapshot()['sessions'][0]
        self.assertEqual(['Synthetic skill (executor reported)'],row['skills'])
        event=row['stages'][0]['events'][0]
        self.assertEqual('executor-reported',event['source']);self.assertIn('not independently verified',event['detail'])
        self.assertFalse(row['attemptBinding']['independentlyVerified'])
        self.binding['appliedSkills'][0]['kind']='read'
        with self.assertRaises(BindingError):validate(self.binding)

    def test_revalidate_source_task_personal_scope_and_exact_turn_every_read(self):
        self.save();self.assertEqual('bound',self.wrapper.snapshot()['attemptBinding']['status'])
        self.data['sessions'][0]['stages'][1]['id']='other-turn'
        self.assertEqual('unavailable',self.wrapper.snapshot()['attemptBinding']['status'])
        self.data['sessions'][0]['stages'][1]['id']='current-turn'
        with closing(sqlite3.connect(self.db)) as db,db:db.execute("UPDATE items SET tags='task-sphere:work'")
        result=self.wrapper.snapshot()
        self.assertEqual('unavailable',result['attemptBinding']['status'])
        self.assertEqual(self.data['sessions'],result['sessions'])

    def test_ending_chat_never_completes_or_starts_native_task_and_no_duration_invention(self):
        self.save();stage=self.data['sessions'][0]['stages'][1]
        stage.update(status='completed',endedAt='2026-01-01T10:01:00Z')
        row=self.wrapper.snapshot()['sessions'][0]
        self.assertIsNone(row['durationMs']);self.assertIsNone(row['attemptBinding']['runningElapsedSource'])
        self.assertEqual(self.before,self.db.read_bytes())
        with closing(sqlite3.connect(self.db)) as db:
            self.assertEqual((0,'task'),db.execute('SELECT completed,status FROM items').fetchone())
            self.assertEqual(0,db.execute('SELECT count(*) FROM timeline_blocks').fetchone()[0])

    def test_missing_binding_no_write_and_unknown_shape_or_duplicate_turn_fail_closed(self):
        self.assertEqual(self.data,self.wrapper.snapshot())
        self.save();self.data['sessions'][0]['stages'].append(copy.deepcopy(self.data['sessions'][0]['stages'][1]))
        self.assertEqual('unavailable',self.wrapper.snapshot()['attemptBinding']['status'])
        self.wrapper.sessions_path=('missing',)
        self.assertEqual('unavailable',self.wrapper.snapshot()['attemptBinding']['status'])
        self.assertEqual(self.before,self.db.read_bytes())


if __name__=='__main__':unittest.main()
