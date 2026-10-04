import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cloud_sync import CloudSync, SyncError, PROFILE, b64, clean_runs, seal, unseal
from run_store import RunStore
from test_run_store import report


def profile(device='device-pc-01', key=b'k'*32):
    return dict(profile=PROFILE, endpoint='https://agent-city-sync-v1.example.workers.dev', device=device, token=b64(b't'*32), key=b64(key))


class Relay:
    def __init__(self): self.rows={}; self.lose_ack=False; self.offline=False; self.puts=[]
    def __call__(self,p,method,body=None):
        if self.offline: raise SyncError('cloud_unavailable')
        if method=='GET': return dict(schemaVersion=1,device=p['device'],records=copy.deepcopy(list(self.rows.values())))
        self.puts.append(copy.deepcopy(body))
        old=self.rows.get(p['device'])
        if old and old['revision']==body['revision'] and old['envelope']==body['envelope']: return {'revision':old['revision']}
        if body['revision']!=(old['revision'] if old else 0)+1: raise SyncError('revision_conflict')
        self.rows[p['device']]=dict(body,device=p['device'])
        if self.lose_ack: self.lose_ack=False; raise SyncError('cloud_unavailable')
        return {'revision':body['revision']}


class MemoryProfile(CloudSync):
    def __init__(self,path,source,relay,p): super().__init__(path,source,relay); self.test_profile=p
    def _profile(self): return self.test_profile


class CloudSyncTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.root=Path(self.temp.name)
        self.runs=RunStore(self.root/'runs'); (self.root/'runs').mkdir()
        self.runs.report(report(mcpCalls=[dict(server='docs',tool='search',calls=1)]))
        self.relay=Relay()
        self.pc=MemoryProfile(self.root/'pc',self.runs.snapshot,self.relay,profile())
        self.mac=MemoryProfile(self.root/'mac',lambda:[],self.relay,profile('device-mac-01'))
    def tearDown(self): self.temp.cleanup()

    def test_two_devices_receive_decrypt_and_keep_original_timestamps(self):
        self.pc.sync(); self.mac.sync(); self.pc.sync()
        self.assertIsNone(self.pc.error); self.assertIsNone(self.mac.error)
        self.assertEqual(self.pc.status()['remoteDevices'],['device-mac-01'])
        row=self.mac.remote[0]
        self.assertEqual(row['updatedAt'],self.runs.snapshot()[0]['updatedAt'])
        self.assertEqual(row['mcpCalls'][0]['calls'],1)
        self.assertEqual(row['originDevice'],'device-pc-01'); self.assertTrue(row['readOnly'])
        self.assertNotIn('model-a',json.dumps(self.relay.rows))
        self.assertNotIn('model-a',self.mac.cache_path.read_text())
        self.assertEqual(len(self.relay.puts),2)  # unchanged snapshots are not re-uploaded

    def test_lost_ack_retries_exact_ciphertext_after_restart(self):
        self.relay.lose_ack=True; self.pc.sync()
        self.assertTrue(self.pc.pending_path.exists()); self.assertEqual(self.pc.error,'cloud_unavailable')
        pending=json.loads(self.pc.pending_path.read_text())
        restarted=MemoryProfile(self.root/'pc',self.runs.snapshot,self.relay,profile()); restarted.sync()
        self.assertIsNone(restarted.error); self.assertFalse(restarted.pending_path.exists())
        self.assertEqual(self.relay.puts[0],self.relay.puts[1]); self.assertEqual(pending['body'],self.relay.puts[1])

    def test_offline_restart_reads_encrypted_cache_without_refreshing_event_time(self):
        self.pc.sync(); self.mac.sync(); stamp=self.mac.remote[0]['updatedAt']; last=self.mac.last_sync
        self.relay.offline=True
        restarted=MemoryProfile(self.root/'mac',lambda:[],self.relay,profile('device-mac-01')); restarted.sync()
        self.assertEqual(restarted.error,'cloud_unavailable'); self.assertEqual(restarted.remote[0]['updatedAt'],stamp)
        self.assertEqual(restarted.last_sync,last)

    def test_authentication_binds_ciphertext_to_device_revision_endpoint_and_key(self):
        p=profile(); snapshot=dict(schemaVersion=1,device=p['device'],runs=clean_runs(self.runs.snapshot()))
        record=dict(device=p['device'],revision=1,envelope=seal(p,1,snapshot))
        self.assertEqual(unseal(p,record)[0]['model'],'model-a')
        for override in [dict(device='device-other'),dict(revision=2)]:
            with self.assertRaises(Exception): unseal(p,dict(record,**override))
        with self.assertRaises(Exception): unseal(profile(key=b'x'*32),record)
        with self.assertRaises(Exception): unseal(dict(p,endpoint=p['endpoint']+'/other'),record)

    def test_allowlist_removes_task_content_and_rejects_duplicate_runs(self):
        rows=self.runs.snapshot(); rows[0].update(title='PRIVATE',notes='PRIVATE',apiKey='PRIVATE')
        self.assertNotIn('PRIVATE',json.dumps(clean_runs(rows)))
        with self.assertRaises(SyncError): clean_runs(rows+rows)
        rows[0]['history'][0].pop('mcpCalls')
        self.assertIsNone(clean_runs(rows)[0]['history'][0]['mcpCalls'])

    def test_old_cloud_revision_and_lower_run_sequence_are_rejected(self):
        self.pc.sync(); self.mac.sync(); old=copy.deepcopy(self.relay.rows['device-pc-01'])
        self.runs.report(report(sequence=2,mcpCalls=[dict(server='docs',tool='search',calls=2)]))
        self.pc.sync(); self.mac.sync(); self.assertEqual(self.mac.remote[0]['sequence'],2)
        self.relay.rows['device-pc-01']=old; self.mac.sync(); self.assertEqual(self.mac.error,'remote_rollback')
        p=profile(); rows=self.runs.snapshot(); rows[0]['sequence']=1
        self.relay.rows[p['device']]=dict(device=p['device'],revision=3,envelope=seal(p,3,dict(schemaVersion=1,device=p['device'],runs=rows)))
        self.mac.sync(); self.assertEqual(self.mac.error,'run_rollback')
        self.assertEqual(self.mac.remote[0]['sequence'],2)

    def test_lost_local_state_does_not_overwrite_cloud(self):
        self.pc.sync(); other=MemoryProfile(self.root/'other',lambda:[],self.relay,profile()); other.sync()
        self.assertEqual(other.error,'revision_conflict'); self.assertEqual(len(self.relay.puts),1)

    def test_malformed_cloud_response_does_not_trigger_upload(self):
        self.pc.transport=lambda *args:dict(schemaVersion=1,device='wrong-device',records=[])
        self.pc.sync(); self.assertEqual(self.pc.error,'invalid_cloud_response'); self.assertFalse(self.pc.pending_path.exists())

    def test_status_never_exposes_token_or_key(self):
        status=json.dumps(self.pc.status())
        self.assertNotIn(profile()['token'],status); self.assertNotIn(profile()['key'],status)

    def test_expansion_limit_rejects_compression_bomb(self):
        p=profile(); record=dict(device=p['device'],revision=1,envelope=seal(p,1,dict(schemaVersion=1,device=p['device'],runs=clean_runs(self.runs.snapshot()))))
        with patch('cloud_sync.MAX_PLAIN',10):
            with self.assertRaises(SyncError): unseal(p,record)


if __name__=='__main__': unittest.main()
