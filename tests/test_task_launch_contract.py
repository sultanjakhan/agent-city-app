import unittest
import uuid
from task_launch_contract import prepare_intent

class LaunchContractTests(unittest.TestCase):
    def test_two_entrances_share_identity_and_retry(self):
        task,request=str(uuid.uuid4()),str(uuid.uuid4())
        a=prepare_intent('cicada',task,request,'pipeline')
        b=prepare_intent('agent-city',task,request,'pipeline')
        self.assertEqual(a['taskId'],b['taskId']);self.assertEqual(a['runId'],b['runId'])
        self.assertFalse(a['executionSupported']);self.assertEqual(a['status'],'prepared')
        self.assertNotEqual(a['runId'],prepare_intent('agent-city',task,str(uuid.uuid4()),'pipeline')['runId'])
    def test_no_title_based_identity(self):
        with self.assertRaises(ValueError):prepare_intent('cicada','Task title',str(uuid.uuid4()),'pipeline')
    def test_no_other_entrance(self):
        with self.assertRaises(ValueError):prepare_intent('external',str(uuid.uuid4()),str(uuid.uuid4()),'pipeline')

    def test_snapshot_is_detached_and_hash_identifies_revision(self):
        from task_launch_contract import prepare_pipeline_intent
        from test_pipeline_store import fixture
        p=fixture();task,request=str(uuid.uuid4()),str(uuid.uuid4())
        a=prepare_pipeline_intent('agent-city',task,request,p)
        p['stages'][0]['name']='Changed later'
        self.assertEqual(a['pipelineSnapshot']['stages'][0]['name'],'Work')
        b=prepare_pipeline_intent('cicada',task,request,p)
        self.assertEqual(a['runId'],b['runId'])
        self.assertNotEqual(a['pipelineSnapshotHash'],b['pipelineSnapshotHash'])
        # Registry must reject the differing payload under an existing requestId.
