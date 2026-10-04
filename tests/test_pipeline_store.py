import copy
import tempfile
import unittest
from pipeline_store import PipelineStore, preview, validate

def fixture():
    return {'schemaVersion':1,'id':'sample','name':'Synthetic pipeline','projectId':'project-test','limits':{'tokens':100,'retries':2},'stages':[
        {'id':'work','name':'Work','kind':'work','modelRefs':['fixture/model'],'skillRefs':[],'limits':{'tokens':50},'transitions':[{'when':'success','action':'next','target':'review'},{'when':'failure','action':'escalate','target':None}]},
        {'id':'review','name':'Review','kind':'review','modelRefs':[],'skillRefs':['fixture-skill'],'limits':{},'transitions':[{'when':'success','action':'stop','target':None}]}]}

class PipelineTests(unittest.TestCase):
    def test_policy_upper_bound_and_stage_inheritance(self):
        p=fixture();r=preview(p,{'schemaVersion':1,'projectId':'project-test','limits':{'tokens':80,'timeSeconds':10}})
        self.assertEqual(r['effectiveLimits']['tokens'],80)
        self.assertEqual(r['stageLimits']['work']['tokens'],50)
        self.assertEqual(r['stageLimits']['review']['timeSeconds'],10)
        self.assertIn('pipeline.tokens exceeds upper bound',r['conflicts'])
        self.assertFalse(r['canRun']);self.assertEqual(r['enforcement']['externalClient'],'unknown')
    def test_unreachable_review_and_unknown_policy(self):
        p=fixture();p['stages'][0]['transitions']=[];r=preview(p)
        self.assertTrue(r['conflicts']);self.assertTrue(any('policy unknown' in x for x in r['warnings']))
    def test_invalid_schemas_limits_and_targets(self):
        for mutate in [lambda p:p.update(taskPrompt='forbidden'),lambda p:p['limits'].update(tokens=True),lambda p:p['limits'].update(costUsd=float('nan')),lambda p:p['stages'][0]['transitions'][0].update(target='missing'),lambda p:p['stages'][1].update(kind='work')]:
            p=fixture();mutate(p)
            with self.assertRaises(ValueError):validate(p)
    def test_zero_inherits_correctly_and_relaxation_conflicts(self):
        p=fixture();p['limits']['retries']=0;r=preview(p)
        self.assertEqual(r['stageLimits']['review']['retries'],0)
        p['stages'][0]['limits']['retries']=1;self.assertTrue(preview(p)['conflicts'])
    def test_policy_identity(self):
        with self.assertRaises(ValueError):preview(fixture(),{'schemaVersion':1,'projectId':'different','limits':{}})
    def test_atomic_save_and_revision_conflict(self):
        with tempfile.TemporaryDirectory() as d:
            store=PipelineStore(d);revision=store.snapshot()['revision'];saved=store.save(fixture(),revision)
            self.assertEqual(saved['pipelines'],[fixture()]);self.assertTrue(store.path.exists())
            with self.assertRaises(RuntimeError):store.save(fixture(),revision)
            self.assertEqual(store.snapshot(),saved)
    def test_preview_read_only(self):
        p=fixture();original=copy.deepcopy(p);preview(p,model_ids=['fixture/model'],skill_ids=['fixture-skill']);self.assertEqual(p,original)

if __name__=='__main__':unittest.main()
