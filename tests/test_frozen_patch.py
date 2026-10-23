"""Assemble complete files from exact frozen substrings; execute changed paths."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from compat.frozen_fragments import (PASSIVE_ASSIGNMENT, STAGE_RETURN, PATCH_METRICS,
                                     STAGE_METRICS, CONNECTOR_INIT, CONNECTOR_TOKS, CONNECTOR_RETURN, LIVE_SCRIPT)
from compat.frozen_patch import patch_text, check_sources

ROOT=Path(__file__).resolve().parents[1]


class FrozenPatchTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.app=self.root/'native/agent-system/app';(self.app/'static').mkdir(parents=True)
        (self.root/'passive_server.py').write_text('def build_store(value, store):\n'+PASSIVE_ASSIGNMENT+'    return store\n')
        collector="""from datetime import datetime
class Collector:
    def stage(self, turn, measured):
        stages, coverages = [], ['partial']
        for index, turn in enumerate([turn], 1):
            duration = turn['duration']
            if duration is None and turn['start'] and turn['end']:
                duration = max(0, round((datetime.fromisoformat(turn['end']) - datetime.fromisoformat(turn['start'])).total_seconds() * 1000))
"""+STAGE_RETURN+'        return stages[0]\n'
        (self.app/'live_sessions.py').write_text(collector)
        connector='class Connector:\n    def view(self, rows):\n        if True:\n'+CONNECTOR_INIT+"            for ident, tags in rows:\n"+CONNECTOR_TOKS+"                result.append({'sourceId':str(ident)})\n"+CONNECTOR_RETURN
        (self.app/'cicada_connector.py').write_text(connector)
        renderer=PATCH_METRICS+'\n  function updateStageNode(stage, summary, stageDuration) {\n'+STAGE_METRICS+'  }\n'
        (self.app/'static/live-sessions.js').write_text(renderer)
        self.html='<!doctype html><html><body>'+LIVE_SCRIPT+'<script src="/app.js" defer></script></body></html>'
        (self.app/'static/index.html').write_text(self.html)
        self.assertIn(r'\u00b7', renderer)
        self.assertNotIn(' · ', PATCH_METRICS)
        patch=(ROOT/'compat/frozen-exact-turn.patch').read_text()
        self.assertEqual(patch_text(ROOT),patch)
        expected=check_sources(self.root,ROOT)
        before={path:path.read_bytes() for path in self.root.rglob('*') if path.is_file()}
        result=subprocess.run(['python','-m','compat.frozen_patch','--check-root',str(self.root),'--planned-files-json'],cwd=ROOT,capture_output=True,text=True,check=True)
        self.assertEqual(expected,json.loads(result.stdout))
        self.assertEqual(before,{path:path.read_bytes() for path in self.root.rglob('*') if path.is_file()})
        self.original_files=before
        # Synthetic private-assembler equivalent: only complete planned files.
        for name,content in expected.items():
            (self.root/name).write_bytes(content.encode('utf-8'))
        for name,content in expected.items():self.assertEqual(content,(self.root/name).read_text())

    def test_missing_or_duplicate_anchor_rejected_without_writes(self):
        for name in ('passive_attempts.py','static/passive-attempt-view.js'):(self.app/name).unlink()
        for path,content in self.original_files.items():path.write_bytes(content)
        path=self.app/'static/live-sessions.js'
        original=path.read_bytes()
        for text in ('missing anchor', original.decode()+PATCH_METRICS):
            path.write_text(text)
            before=path.read_bytes()
            with self.assertRaisesRegex(ValueError,'anchor absent or ambiguous'):
                check_sources(self.root,ROOT)
            self.assertEqual(before,path.read_bytes())
        path.write_bytes(original)

    def test_applied_collector_singular_models_efforts_only_existing_measured_counters(self):
        scope={};exec((self.app/'live_sessions.py').read_text(),scope)
        turn={'id':'synthetic-current-turn','models':{'turn-model'},'efforts':{'turn-effort'},'status':'working',
              'start':'2026-01-01T10:00:00.000+00:00','first':'2026-01-01T09:00:00.000+00:00','end':None,'duration':None,
              'events':{'e':{'id':'synthetic-event','at':'2026-01-01T10:00:01.000+00:00','kind':'activity'}}}
        measured={'input':7,'output':None,'total':None,'cachedInput':2,'reasoningOutput':None}
        stage=scope['Collector']().stage(turn,measured)
        self.assertEqual(('turn-model','turn-effort'),(stage['model'],stage['effort']))
        self.assertEqual(2,stage['usage']['cachedInput']);self.assertNotIn('reasoningOutput',stage['usage'])
        self.assertEqual(turn['start'],stage['observedStartedAt'])
        turn['models'].add('another');turn['efforts'].add('another');turn['start']=None
        stage=scope['Collector']().stage(turn,measured)
        self.assertIsNone(stage['model']);self.assertIsNone(stage['effort']);self.assertIsNone(stage['observedStartedAt'])

    def test_applied_connector_projects_only_exact_personal_boolean_and_entry_wires_wrapper(self):
        scope={};exec((self.app/'cicada_connector.py').read_text(),scope)
        rows=[('synthetic-personal','task-sphere:personal'),('synthetic-work','task-sphere:personal,TASK-SPHERE:WORK'),
              ('synthetic-jira','task-sphere:personal,JIRA:issue'),('synthetic-case','TASK-SPHERE:PERSONAL')]
        result,_=scope['Connector']().view(rows)
        self.assertEqual([True,False,False,False],[x['personalEligible'] for x in result])
        self.assertTrue(all(set(row)=={'sourceId','personalEligible'} for row in result))
        entry=(self.root/'passive_server.py').read_text()
        self.assertIn("sessions_path=('sessions',)",entry)
        self.assertIn("identity_fields=('projectId', 'agentId', 'parentId')",entry)
        self.assertNotIn('do_POST',entry)
        html=(self.app/'static/index.html').read_text()
        self.assertEqual(self.html.replace(LIVE_SCRIPT,'<script src="/passive-attempt-view.js" defer></script>'+LIVE_SCRIPT),html)
        self.assertNotIn('\n',html)
        self.assertEqual((ROOT/'passive_attempts.py').read_text(),(self.app/'passive_attempts.py').read_text())

    def test_applied_exact_patchMetrics_executes_helper_and_leaves_unbound_path(self):
        script=r"""
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const dir=process.argv[1],nodes={};
const metricNode=k=>nodes[k]??={v:{},n:{},querySelector:s=>s==='.ls-metric-value'?nodes[k].v:nodes[k].n};
const scope={metricNode,formatDuration:String,formatNumber:String,text:String,formatDateTime:String,sessionDuration:()=>99999};
vm.runInNewContext(fs.readFileSync(path.join(dir,'passive-attempt-view.js'),'utf8'),scope);
vm.runInNewContext(fs.readFileSync(path.join(dir,'live-sessions.js'),'utf8'),scope);
scope.patchMetrics({attemptBinding:{},status:'completed',startedAt:'2026-01-01T10:00:00Z',endedAt:'2026-01-01T10:01:00Z',durationMs:null,model:null,effort:null,usage:{input:7,output:null,total:null}});
const bound=JSON.parse(JSON.stringify(nodes));
scope.patchMetrics({startedAt:'legacy',model:'session-model',effort:'legacy-effort',usage:{total:88888}});
console.log(JSON.stringify({bound,unbound:nodes}));
"""
        result=subprocess.run(['node','-e',script,str(self.app/'static')],capture_output=True,text=True,check=True)
        output=json.loads(result.stdout)
        self.assertEqual('Unknown',output['bound']['time']['v']['textContent'])
        self.assertEqual('Unknown',output['bound']['tokens']['v']['textContent'])
        self.assertEqual('Unknown',output['bound']['model']['v']['textContent'])
        self.assertEqual('99999',output['unbound']['time']['v']['textContent'])
        self.assertEqual('88888',output['unbound']['tokens']['v']['textContent'])


if __name__=='__main__':unittest.main()
