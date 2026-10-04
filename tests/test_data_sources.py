from owner_client import authorize, headers as owner_headers
import copy
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, build_opener, ProxyHandler

import data_sources as sources
import server


class PortableJSONTests(unittest.TestCase):
    def test_strict_parser_rejects_duplicates_depth_encoding_size_and_constants(self):
        invalid = [b'{"schemaVersion":1,"schemaVersion":1}',
                   b'{"nested":{"id":1,"id":2}}',
                   b'[' * 17 + b'0' + b']' * 17,
                   b'{"id":"\xff"}', b' ' * (sources.MAX_CONFIG + 1),
                   b'{"id":1e999}', b'{"id":NaN}', b'{"id":Infinity}', b'{"id":-Infinity}']
        for raw in invalid:
            with self.subTest(category=invalid.index(raw)):
                with self.assertRaisesRegex(sources.SourceError, '^Invalid portable JSON$'):
                    sources.parse_portable_json(raw)

    def test_strict_parser_allows_valid_json_and_escaped_brackets(self):
        value = {"schemaVersion": 1, "label": 'escaped "[' * 20}
        self.assertEqual(value, sources.parse_portable_json(json.dumps(value)))
        self.assertEqual({}, sources.parse_portable_json(b'{}'))


class DataSourcesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = sources.DataSources(self.root / 'runtime')
        self.city = self.root / 'city'
        (self.city / 'panel').mkdir(parents=True)
        (self.city / 'panel/projects.json').write_text(json.dumps({'projects': [{'name': 'private synthetic name'}]}), encoding='utf-8')
        (self.city / 'panel/agent-runs.json').write_text(json.dumps({'runs': {'one': {'reply': 'private synthetic reply'}}}), encoding='utf-8')
        (self.city / 'skills/example').mkdir(parents=True)
        (self.city / 'skills/example/SKILL.md').write_text('private synthetic skill body', encoding='utf-8')
        self.cicada = self.root / 'cicada'
        (self.cicada / 'profiles/production').mkdir(parents=True)
        with closing(sqlite3.connect(self.cicada / 'profiles/production/calendar.db')) as db:
            db.execute('CREATE TABLE items(id TEXT, kind TEXT, title TEXT)')
            db.execute("INSERT INTO items VALUES ('one','task','private synthetic task')")
            db.commit()
        self.manifest = sources.default_manifest()
        self.bindings = {'city': str(self.city), 'cicada': str(self.cicada)}

    def hashes(self):
        return {p.relative_to(self.root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in self.root.rglob('*') if p.is_file()}

    def test_preview_is_read_only_and_returns_counts_not_private_content(self):
        before = self.hashes()
        preview = self.store.preview(self.manifest, self.bindings, 'none')
        self.assertEqual({row['id']: row['count'] for row in preview['sections']},
                         {'projects': 1, 'skills': 1, 'runs': 1, 'tasks-production': 1, 'tasks-dev': None})
        self.assertNotIn('private synthetic', json.dumps(preview))
        self.assertEqual(before, self.hashes())
        self.assertFalse(self.store.path.exists())

    def test_apply_only_saves_local_profile_and_export_excludes_machine_bindings(self):
        before = self.hashes()
        preview = self.store.preview(self.manifest, self.bindings, 'none')
        result = self.store.apply(self.manifest, self.bindings, 'none', preview['previewToken'])
        self.assertNotEqual(result['revision'], 'none')
        after = self.hashes()
        self.assertEqual({key: after[key] for key in before}, before)
        self.assertEqual(set(after) - set(before), {'runtime/data-sources.local.json'})
        exported = self.store.export()
        self.assertEqual(sources.import_document(exported), self.manifest)
        self.assertTrue(all(profile['config']['source']['path'] is None for profile in exported['profiles']))
        self.assertNotIn(str(self.root), json.dumps(exported))
        reopened = sources.DataSources(self.root / 'runtime').snapshot()
        self.assertEqual(reopened['bindings'], {key: str(Path(value).resolve()) for key, value in self.bindings.items()})

    def test_changed_selection_invalidates_preview_and_conflicts_keep_new_profile(self):
        first = self.store.preview(self.manifest, self.bindings, 'none')
        changed = dict(self.bindings, city=str(self.root / 'another'))
        with self.assertRaises(sources.SourceError):
            self.store.apply(self.manifest, changed, 'none', first['previewToken'])
        other = sources.DataSources(self.root / 'runtime')
        second = other.preview(self.manifest, changed, 'none')
        other.apply(self.manifest, changed, 'none', second['previewToken'])
        with self.assertRaises(sources.SourceConflict):
            self.store.apply(self.manifest, self.bindings, 'none', first['previewToken'])
        self.assertEqual(self.store.snapshot()['bindings'], {key: str(Path(value).resolve()) for key, value in changed.items()})

    def test_structure_requires_matching_preview_and_preserves_existing_files(self):
        new_root = self.root / 'new-city'
        bindings = {'city': str(new_root)}
        with self.assertRaises(sources.SourceError):
            self.store.create_structure('city', self.manifest, bindings, 'none', None)
        self.assertFalse(new_root.exists())
        preview = self.store.preview(self.manifest, bindings, 'none')
        result = self.store.create_structure('city', self.manifest, bindings, 'none', preview['previewToken'])
        self.assertFalse(result['dataCopied']); self.assertFalse(result['gitCreated'])
        self.assertTrue((new_root / 'panel').is_dir())
        self.assertFalse(self.store.path.exists())
        self.assertFalse(list(new_root.rglob('*.db')))
        original = (self.city / 'panel/projects.json').read_bytes()
        preview = self.store.preview(self.manifest, self.bindings, 'none')
        self.store.create_structure('city', self.manifest, self.bindings, 'none', preview['previewToken'])
        self.assertEqual((self.city / 'panel/projects.json').read_bytes(), original)

    def test_structure_validates_all_targets_before_creation(self):
        root = self.root / 'conflicting'
        root.mkdir(); (root / 'skills').write_text('keep', encoding='utf-8')
        bindings = {'city': str(root)}
        preview = self.store.preview(self.manifest, bindings, 'none')
        with self.assertRaises(sources.SourceError):
            self.store.create_structure('city', self.manifest, bindings, 'none', preview['previewToken'])
        self.assertFalse((root / 'panel').exists())
        self.assertEqual((root / 'skills').read_text('utf-8'), 'keep')

    def test_protected_code_network_and_traversal_paths_are_rejected(self):
        values = [str(sources.APP_ROOT), str(sources.APP_ROOT / 'private'),
                  str(self.root / '.codex'), str(self.root / 'credentials'),
                  str(self.root / 'sessions'), str(self.root / 'city/../elsewhere'),
                  '//remote/private', 'relative-folder']
        for value in values:
            with self.subTest(value=value), self.assertRaises(sources.SourceError):
                sources.local_root(value)

    def test_reparse_points_are_rejected_before_resolution(self):
        from types import SimpleNamespace
        import stat
        with patch.object(Path, 'lstat', return_value=SimpleNamespace(st_file_attributes=0x400, st_mode=stat.S_IFDIR)):
            with self.assertRaises(sources.SourceError): sources.no_redirect(self.city)

    def test_manifest_rejects_secrets_unknown_fields_write_mode_and_arbitrary_paths(self):
        variants = []
        for key in ['credentials', 'sessions', 'token', 'bindings']:
            item = copy.deepcopy(self.manifest); item[key] = {}; variants.append(item)
        item = copy.deepcopy(self.manifest); item['sources'][0]['mode'] = 'write'; variants.append(item)
        item = copy.deepcopy(self.manifest); item['sources'][0]['root'] = str(self.city); variants.append(item)
        item = copy.deepcopy(self.manifest); item['sections'][0]['path'] = '../credentials/profile.json'; variants.append(item)
        item = copy.deepcopy(self.manifest); item['schemaVersion'] = True; variants.append(item)
        for item in variants:
            with self.assertRaises(sources.SourceError): sources.validate_manifest(item)

    def test_hidden_sections_are_not_read(self):
        manifest = copy.deepcopy(self.manifest)
        for row in manifest['sections']: row['visible'] = False
        with patch.object(Path, 'read_text', side_effect=AssertionError('Hidden data read')), patch('data_sources.sqlite3.connect', side_effect=AssertionError('Hidden DB read')):
            result = self.store.inspect(manifest, self.bindings)
        self.assertTrue(all(row['state'] == 'hidden' for row in result['sections']))

    def test_wal_and_invalid_formats_report_errors_without_writes_or_raw_content(self):
        (self.cicada / 'profiles/production/calendar.db-wal').write_bytes(b'')
        (self.city / 'panel/projects.json').write_text('private malformed text', encoding='utf-8')
        before = self.hashes()
        with patch('data_sources.sqlite3.connect', side_effect=AssertionError('WAL DB opened')):
            result = self.store.inspect(self.manifest, self.bindings)
        rows = {row['id']: row for row in result['sections']}
        self.assertEqual(rows['tasks-production']['state'], 'busy')
        self.assertEqual(rows['projects']['state'], 'error')
        self.assertNotIn('private malformed', json.dumps(result))
        self.assertEqual(before, self.hashes())

    def test_onboarding_only_for_new_profile_and_skip_persists_without_import(self):
        self.assertFalse(self.store.snapshot()['needsOnboarding'])
        fresh = sources.DataSources(self.root / 'fresh', new_profile=True)
        self.assertTrue(fresh.snapshot()['needsOnboarding'])
        result = fresh.dismiss_onboarding()
        self.assertEqual(result['bindings'], {})
        self.assertFalse(sources.DataSources(self.root / 'fresh', new_profile=True).snapshot()['needsOnboarding'])
        self.assertEqual(list((self.root / 'fresh').iterdir()), [fresh.path])


class DataSourcesHttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); skills = self.root / 'skills'; skills.mkdir()
        for module, name in [(server.credentials, 'read_key'), (server.credentials, 'info'),
                             (server.CloudSync, '_profile'), (server.CloudSync, 'start')]:
            guard = patch.object(module, name, side_effect=AssertionError('Protected operation'))
            guard.start(); self.addCleanup(guard.stop)
        self.store = server.Store(self.root / 'runtime', skills_root=skills, local_only=True, executable=False)
        self.http = server.Server(('127.0.0.1', 0), self.store)
        self.worker = threading.Thread(target=self.http.serve_forever, daemon=True); self.worker.start(); authorize(self.http)
        self.base = f'http://127.0.0.1:{self.http.server_port}'
        self.opener = build_opener(ProxyHandler({}))

    def tearDown(self):
        self.http.shutdown(); self.http.server_close(); self.worker.join(3)

    def call(self, route, payload=None, authenticated=True):
        headers = {'X-Agent-City': '1', 'Content-Type': 'application/json'}
        if authenticated: headers['X-Agent-City-Token'] = self.store.csrf_token
        req = Request(self.base + route, data=json.dumps(payload).encode() if payload is not None else None, headers=owner_headers('http://127.0.0.1:'+str(self.http.server_port),headers))
        try:
            with self.opener.open(req, timeout=3) as response: return response.status, json.loads(response.read())
        except HTTPError as response: return response.code, json.loads(response.read())

    def test_raw_portable_import_rejects_duplicate_and_deep_json_without_activation(self):
        before = self.store.data_sources.snapshot()
        for document in ['{"schemaVersion":1,"schemaVersion":1}', '[' * 17 + '0' + ']' * 17]:
            status, body = self.call('/api/data-sources/validate', {'document': document})
            self.assertEqual(400, status); self.assertEqual('Invalid portable JSON', body['error'])
        status, document = self.call('/api/data-sources/export')
        self.assertEqual(200, status)
        status, result = self.call('/api/data-sources/validate', {'document': json.dumps(document)})
        self.assertEqual(200, status); self.assertIn('manifest', result)
        self.assertEqual(before, self.store.data_sources.snapshot())
        self.assertFalse(self.store.data_sources.path.exists())

    def test_preview_apply_and_structure_work_locally_and_require_csrf(self):
        manifest = sources.default_manifest(); folder = self.root / 'new-data'
        body = {'manifest': manifest, 'bindings': {'city': str(folder)}, 'revision': 'none'}
        self.assertEqual(self.call('/api/data-sources/preview', body, False)[0], 403)
        self.assertFalse(folder.exists()); self.assertFalse(self.store.data_sources.path.exists())
        code, preview = self.call('/api/data-sources/preview', body); self.assertEqual(code, 200)
        self.assertFalse(folder.exists())
        code, created = self.call('/api/data-sources/create', {**body, 'previewToken': preview['previewToken'], 'sourceId': 'city'})
        self.assertEqual(code, 200); self.assertFalse(created['gitCreated'])
        _, preview = self.call('/api/data-sources/preview', body)
        self.assertEqual(self.call('/api/data-sources/apply', {**body, 'previewToken': preview['previewToken']})[0], 200)
        _, exported = self.call('/api/data-sources/export')
        self.assertNotIn(str(folder), json.dumps(exported))
        self.assertEqual(self.call('/api/cloud')[1]['state'], 'paused')

    def test_new_profile_prompts_existing_runtime_does_not_and_reads_create_nothing(self):
        self.assertTrue(self.call('/api/state')[1]['dataSourcesOnboarding'])
        self.call('/api/data-sources'); self.call('/api/data-sources/status')
        self.assertFalse(self.store.data_sources.path.exists())
        self.assertEqual(self.call('/api/data-sources/dismiss', {})[0], 200)
        self.assertFalse(self.call('/api/state')[1]['dataSourcesOnboarding'])
        existing = self.root / 'existing'; existing.mkdir()
        (existing / 'state.json').write_text('{"schemaVersion":1}', encoding='utf-8')
        other = server.Store(existing, skills_root=self.root / 'skills', local_only=True, executable=False)
        self.assertFalse(other.snapshot()['dataSourcesOnboarding'])
        self.assertFalse(other.data_sources.path.exists())
