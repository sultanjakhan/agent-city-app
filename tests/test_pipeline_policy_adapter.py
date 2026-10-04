import importlib.util
import os
from pathlib import Path
import unittest
from pipeline_policy_adapter import preview_repository_pipeline
from test_pipeline_store import fixture

class ProfileFixture:
    def __init__(self,policy):self.policy=policy;self.read_ids=[]
    def read(self,ident):
        self.read_ids.append(ident)
        return {'repoId':ident,'revision':'synthetic-revision','policy':self.policy}

class AdapterTests(unittest.TestCase):
    def test_missing_policy_has_no_default(self):
        profiles=ProfileFixture(None)
        r=preview_repository_pipeline(fixture(),profiles,lambda *_:self.fail('must not invent policy'))
        self.assertIsNone(r['projectPolicy']);self.assertFalse(r['canRun'])
        self.assertEqual(profiles.read_ids,['project-test'])
    def test_actual_fc5a51a_policy_function(self):
        import project_policy as module
        profiles=ProfileFixture({'schemaVersion':1,'sourceIds':['source-a'],'allowedActions':['read','write'],'deniedActions':['write'],'defaultPipelineId':None})
        r=preview_repository_pipeline(fixture(),profiles,module.preview_policy,
                                     {'sourceIds':['source-a','source-b'],'allowedActions':['read','write']},
                                     {'work':{'allowedActions':[]}})
        self.assertEqual(r['projectPolicy']['pipeline']['sourceIds'],['source-a'])
        self.assertEqual(r['projectPolicy']['pipeline']['allowedActions'],['read'])
        self.assertEqual(r['projectPolicy']['stages']['work']['allowedActions'],[])
        self.assertTrue(r['conflicts']);self.assertEqual(r['projectBudgetSupport'],'unknown')
        self.assertFalse(r['projectPolicy']['pipeline']['runtimeEnforced']);self.assertFalse(r['canRun'])
        self.assertEqual(profiles.policy['sourceIds'],['source-a'])
