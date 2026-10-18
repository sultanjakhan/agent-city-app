import json
import os
from pathlib import Path
import tempfile
import subprocess
import unittest
import types
from unittest.mock import patch
import storage_migration as migration

class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.data=self.root/'data';self.panel=self.root/'external-panel'
        (self.data/'skills/example').mkdir(parents=True);self.panel.mkdir()
        (self.data/'skills/example/SKILL.md').write_text('preserve skill',encoding='utf-8')
        (self.panel/'task-sync.json').write_text('{"nativeId":"exact-original","revision":7}',encoding='utf-8')
        (self.panel/'cloud').mkdir();(self.panel/'cloud/profile.dpapi').write_bytes(b'opaque-user-encrypted-key')
        self.pointer=self.root/'connection.json'
        self.config={'schemaVersion':1,'dataRoot':str(self.data),'panelDirectory':str(self.panel),'repositoryRoots':[str(self.root/'repositories')]}
        self.pointer.write_text(json.dumps(self.config),encoding='utf-8');self.before=self.pointer.read_bytes()
        env={k:v for k,v in os.environ.items() if not k.startswith('AGENT_CITY_') and k!='CODEX_HOME'}
        env['AGENT_CITY_CONFIG']=str(self.pointer)
        self.environment=patch.dict(os.environ,env,clear=True);self.environment.start();self.addCleanup(self.environment.stop)

    def prepare(self):
        return migration.prepare(str(self.root/'new-data'),migration.digest(self.pointer))

    def test_verified_move_preserves_exact_ids_keys_external_references_and_source(self):
        self.assertEqual(self.prepare()['state'],'prepared')
        self.assertEqual(self.pointer.read_bytes(),self.before)
        result=migration.apply_prepared(self.pointer);self.assertEqual(result['state'],'complete')
        moved=json.loads(self.pointer.read_text('utf-8'))
        self.assertEqual(Path(moved['panelDirectory'],'task-sync.json').read_bytes(),(self.panel/'task-sync.json').read_bytes())
        self.assertEqual(Path(moved['panelDirectory'],'cloud/profile.dpapi').read_bytes(),b'opaque-user-encrypted-key')
        self.assertEqual(Path(moved['skillsDirectory'],'example/SKILL.md').read_text('utf-8'),'preserve skill')
        self.assertEqual([Path(p).resolve() for p in moved['repositoryRoots']],[Path(p).resolve() for p in self.config['repositoryRoots']])
        self.assertTrue((self.data/'skills/example/SKILL.md').exists())
        self.assertEqual(len(list(self.root.glob('connection.json.before-migration-*'))),1)

    def test_default_nested_panel_migrates_while_own_writer_lock_is_held(self):
        panel = self.data / 'panel'
        panel.mkdir()
        (panel / 'task-sync.json').write_text('{"nativeId":"nested-original","revision":7}', encoding='utf-8')
        config = {**self.config, 'panelDirectory': str(panel)}
        self.pointer.write_text(json.dumps(config), encoding='utf-8')
        self.assertEqual(self.prepare()['state'], 'prepared')
        result = migration.apply_prepared(self.pointer)
        self.assertEqual(result['state'], 'complete')
        moved = json.loads(self.pointer.read_text('utf-8'))
        self.assertEqual(Path(moved['panelDirectory'], 'task-sync.json').read_bytes(), (panel / 'task-sync.json').read_bytes())
        self.assertFalse(Path(moved['panelDirectory'], '.storage-writer.lock').exists())

    def test_no_merge_into_nonempty_or_overlapping_folder(self):
        destination=self.root/'existing';destination.mkdir();(destination/'foreign.txt').write_text('keep')
        for path in (destination,self.data/'nested',self.root):
            with self.assertRaises(migration.MigrationError):migration.prepare(str(path),migration.digest(self.pointer))
        self.assertEqual(self.pointer.read_bytes(),self.before)
        self.assertEqual((destination/'foreign.txt').read_text(),'keep')

    def test_stale_profile_and_cancel_do_not_switch_pointer(self):
        self.prepare();migration.cancel(migration.digest(self.pointer));self.assertEqual(migration.status()['state'],'idle')
        self.prepare();self.pointer.write_text(json.dumps({**self.config,'codexHome':str(self.root/'codex')}))
        changed=self.pointer.read_bytes()
        self.assertEqual(migration.apply_prepared(self.pointer)['state'],'error')
        self.assertEqual(self.pointer.read_bytes(),changed)

    def test_changed_source_during_copy_aborts_before_pointer_switch(self):
        self.prepare();original=migration.copy_file
        def mutate(source,target):
            original(source,target)
            if source.name=='task-sync.json':source.write_text('{"revision":8}',encoding='utf-8')
        with patch.object(migration,'copy_file',side_effect=mutate):
            self.assertEqual(migration.apply_prepared(self.pointer)['state'],'error')
        self.assertEqual(self.pointer.read_bytes(),self.before)
        self.assertFalse((self.root/'new-data').exists())

    def test_copy_failure_preserves_pointer_source_and_private_recovery(self):
        self.prepare()
        with patch.object(migration,'copy_file',side_effect=OSError('disk fault')):
            self.assertEqual(migration.apply_prepared(self.pointer)['state'],'error')
        self.assertEqual(self.pointer.read_bytes(),self.before)
        self.assertTrue((self.panel/'task-sync.json').exists())
        self.assertEqual(len(list(self.root.glob('.agent-city-migration-*'))),1)

    def test_pointer_commit_failure_keeps_original_active(self):
        self.prepare();write=migration.atomic_bytes
        def fail_pointer(path,raw):
            if Path(path)==self.pointer:raise OSError('pointer write denied')
            return write(path,raw)
        with patch.object(migration,'atomic_bytes',side_effect=fail_pointer):
            self.assertEqual(migration.apply_prepared(self.pointer)['state'],'error')
        self.assertEqual(self.pointer.read_bytes(),self.before)
        self.assertTrue((self.root/'new-data').exists())

    def test_live_writer_refuses_migration_then_releases_on_close(self):
        from storage_lock import StorageLock
        self.prepare()
        with StorageLock(self.panel):
            self.assertEqual(migration.apply_prepared(self.pointer)['state'],'busy')
            self.assertEqual(self.pointer.read_bytes(),self.before)
            self.assertEqual(migration.status()['state'],'prepared')
        self.assertEqual(migration.apply_prepared(self.pointer)['state'],'complete')

    def test_mac_keychain_alias_preserves_original_item_before_switch(self):
        from cloud_sync import PROFILE,b64
        profile=json.dumps(dict(profile=PROFILE,device='device-test-pc',endpoint='https://agent-city-sync-v1.example.workers.dev',token=b64(b't'*32),key=b64(b'k'*32)))
        marker=self.panel/'cloud/profile.json';marker.write_text('{"storage":"macOS Keychain"}')
        old_id=migration.hashlib.sha256(str((self.panel/'cloud').resolve()).encode()).hexdigest()
        items={old_id:profile}
        class Keyring:
            def get_password(self,service,key):return items.get(key)
            def set_password(self,service,key,value):items[key]=value
        self.prepare()
        with patch.object(migration.sys,'platform','darwin'),patch.dict('sys.modules',{'keyring.backends.macOS':types.SimpleNamespace(Keyring=Keyring)}):
            self.assertEqual(migration.apply_prepared(self.pointer)['state'],'complete')
        moved=json.loads(self.pointer.read_text('utf-8'))
        new_id=migration.hashlib.sha256(str((Path(moved['panelDirectory'])/'cloud').resolve()).encode()).hexdigest()
        self.assertEqual(items[old_id],profile);self.assertEqual(items[new_id],profile)

    def test_reparse_sources_rejected_without_config_mutation(self):
        link=self.panel/'linked'
        try:link.symlink_to(self.data,target_is_directory=True)
        except OSError:
            if os.name!='nt':raise
            quote=lambda path:"'"+str(path).replace("'","''")+"'"
            created=subprocess.run(['powershell','-NoProfile','-NonInteractive','-Command',
                'New-Item -ItemType Junction -Path '+quote(link)+' -Target '+quote(self.data)+' | Out-Null'],capture_output=True)
            if created.returncode:self.skipTest('OS does not permit a test junction')
        self.prepare();self.assertEqual(migration.apply_prepared(self.pointer)['state'],'error')
        self.assertEqual(self.pointer.read_bytes(),self.before)

if __name__=='__main__':unittest.main()
