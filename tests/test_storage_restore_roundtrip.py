"""One isolated owner-data round trip; never opens installed profiles or keys."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from cloud_sync import atomic_bytes
import storage_migration as migration
from storage_config import APP_ROOT, load_storage
from test_dashboard_http import make_cicada
from cicada_connector import CicadaConnector


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def user_files(root):
    return {p.relative_to(root).as_posix(): sha(p) for p in root.rglob('*')
            if p.is_file() and p.name != '.storage-writer.lock'}


class StorageRestoreRoundTripTests(unittest.TestCase):
    def test_preserved_pointer_restores_canonical_data_skills_and_cicada_references(self):
        source_revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=APP_ROOT, text=True).strip()
        tracked = subprocess.check_output(['git', 'ls-files', '-z'], cwd=APP_ROOT).decode().split('\0')
        code_before = {name: sha(APP_ROOT / name) for name in tracked if name}
        with tempfile.TemporaryDirectory(prefix='agent-city-restore-') as temporary:
            root = Path(temporary)
            data, skills, credentials = root/'data', root/'separate-skills', root/'separate-credentials'
            panel = data/'panel'
            for folder in (panel, skills/'sample', credentials, root/'repository-reference', root/'codex-reference', root/'cicada-data'):
                folder.mkdir(parents=True, exist_ok=True)
            (panel/'state.json').write_text(json.dumps({'schemaVersion': 1, 'favorites': ['synthetic-model'], 'catalogs': {}}))
            (panel/'task-identities.json').write_text('{"nativeId":"preserved-native-id","revision":7}')
            (skills/'sample/SKILL.md').write_text('---\nname: sample\ndescription: Synthetic fixture\n---\nPreserved instructions.\n')
            (credentials/'opaque-fixture.bin').write_bytes(b'synthetic-encrypted-bytes-not-a-real-key')
            (root/'repository-reference/README.md').write_text('External repository reference; never copied.')
            (root/'codex-reference/AGENTS.md').write_text('Synthetic external instructions; never replaced.')
            db = root/'cicada-data/cicada.db'
            make_cicada(db)
            pointer = root/'connection.json'
            config = {'schemaVersion': 1, 'dataRoot': str(data), 'skillsDirectory': str(skills),
                      'credentialsDirectory': str(credentials), 'codexHome': str(root/'codex-reference'),
                      'repositoryRoots': [str(root/'repository-reference')],
                      'skillInventoryRoots': [{'origin': 'synthetic', 'path': str(skills)}],
                      'cicadaSources': [{'id': 'production', 'label': 'Synthetic Cicada', 'profile': 'production', 'path': str(db)}]}
            pointer.write_text(json.dumps(config))
            before_pointer = pointer.read_bytes()
            before = {label: user_files(folder) for label, folder in [('data', data), ('skills', skills), ('credentials', credentials)]}
            panel_before = user_files(panel)
            db_before = sha(db)
            reference_before = sha(root/'repository-reference/README.md')
            codex_before = sha(root/'codex-reference/AGENTS.md')
            env = {k: v for k, v in os.environ.items() if not k.startswith('AGENT_CITY_') and k != 'CODEX_HOME'}
            env['AGENT_CITY_CONFIG'] = str(pointer)
            with patch.dict(os.environ, env, clear=True):
                original = load_storage()
                original_rows = CicadaConnector(original.panel).snapshot()['tasks']
                self.assertEqual(len(original_rows), 1)
                original_identity = (original_rows[0]['sourceId'], original_rows[0]['taskKey'])
                self.assertEqual(migration.prepare(str(root/'moved'), migration.digest(pointer))['state'], 'prepared')
                applied = migration.apply_prepared(pointer)
                self.assertEqual(applied['state'], 'complete')
                moved = load_storage()
                self.assertEqual(user_files(moved.panel), panel_before)
                self.assertEqual(user_files(moved.skills), before['skills'])
                self.assertEqual(user_files(moved.credentials), before['credentials'])
                self.assertEqual(moved.repository_roots, original.repository_roots)
                self.assertEqual(moved.cicada_candidates, original.cicada_candidates)
                self.assertEqual(moved.codex_home, original.codex_home)
                self.assertEqual(moved.skill_inventory_roots, [('synthetic', moved.skills)])
                self.assertFalse((root/'moved/repository-reference').exists())
                backups = list(root.glob('connection.json.before-migration-*'))
                self.assertEqual(len(backups), 1)
                self.assertEqual(backups[0].read_bytes(), before_pointer)
                # Disposable recovery uses the exact preserved stable pointer and original folders.
                atomic_bytes(pointer, backups[0].read_bytes())
                restored = load_storage()
                self.assertEqual(restored, original)
                self.assertEqual(pointer.read_bytes(), before_pointer)
                rows = CicadaConnector(restored.panel).snapshot()['tasks']
                self.assertEqual((rows[0]['sourceId'], rows[0]['taskKey']), original_identity)
                for label, folder in [('data', data), ('skills', skills), ('credentials', credentials)]:
                    self.assertEqual(user_files(folder), before[label])
                # A fresh process resolves the restored pointer, rather than cached Python state.
                observed = json.loads(subprocess.check_output([sys.executable, '-c',
                    'import json;from storage_config import load_storage;from cicada_connector import CicadaConnector;'
                    's=load_storage();t=CicadaConnector(s.panel).snapshot()["tasks"][0];'
                    'print(json.dumps({"root":str(s.root),"panel":str(s.panel),"skills":str(s.skills),"id":t["sourceId"],"key":t["taskKey"]}))'],
                    cwd=APP_ROOT, env=env, text=True))
                self.assertEqual((observed['root'], observed['panel'], observed['skills']),
                                 (str(original.root), str(original.panel), str(original.skills)))
                self.assertEqual((observed['id'], observed['key']), original_identity)
                self.assertTrue(moved.root.exists())
            self.assertEqual(sha(db), db_before)
            self.assertEqual(sha(root/'repository-reference/README.md'), reference_before)
            self.assertEqual(sha(root/'codex-reference/AGENTS.md'), codex_before)
        self.assertEqual({name: sha(APP_ROOT/name) for name in tracked if name}, code_before)
        print(json.dumps({'storageRoundTrip': 'PASS', 'source': source_revision,
                          'canonicalPathsRestored': True, 'userFileHashesPreserved': True,
                          'freshProcessReadback': True, 'cicadaReferenceAndNativeIdentityPreserved': True,
                          'syntheticCicadaDatabaseUnchanged': True, 'trackedApplicationFilesUnchanged': True,
                          'productionMigration': False, 'cicadaInstalledAcceptance': False}))
