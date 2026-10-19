"""Focused reconciliation boundaries; all state and authority are synthetic."""
import json
import contextlib
import io
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from context_mcp import LocalAPI
from file_context import FileContext, ContextError


class ReconciliationTests(unittest.TestCase):
    def test_redirected_index_cannot_write_outside_private_profile(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            profile = root / 'profile'
            profile.mkdir()
            outside = root / 'outside.sqlite3'
            (profile / 'context-index.sqlite3').symlink_to(outside)
            with self.assertRaises(ValueError):
                FileContext(profile)
            self.assertFalse(outside.exists())

    def test_native_model_query_and_skill_read_keep_exact_route_without_http_fallback(self):
        with patch('city.native_request', return_value={'schemaVersion': 1}) as native:
            api = LocalAPI()
            api.call('agent_city_models', {'limit': 1, 'revision': 'synthetic-revision'})
            self.assertEqual(native.call_args.args, ('/api/v1/models?limit=1&revision=synthetic-revision',))
            api.call('agent_city_read_skill', {'deviceId': 'synthetic-device', 'rootId': 'synthetic-root', 'id': 'synthetic-skill'})
            self.assertTrue(native.call_args.args[0].startswith('/api/v1/skill-inventory?'))
        with patch('city.native_request', return_value=None), patch('urllib.request.OpenerDirector.open') as http:
            with self.assertRaisesRegex(ValueError, 'native_authority_unavailable'):
                LocalAPI().call('agent_city_file_roots', {})
            http.assert_not_called()

    def test_metadata_cache_rebuild_retains_exact_grants_and_revisioned_reads(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            documents = root / 'documents'
            documents.mkdir()
            (documents / 'example.txt').write_text('Synthetic document body', encoding='utf-8')
            context = FileContext(root / 'profile')
            context.grant(documents, 'Synthetic', context.roots()['revision'])
            original = context.path.read_bytes()
            grant = context.roots()['roots'][0]
            scope = {'deviceId': grant['deviceId'], 'rootId': grant['id']}
            item = context.search(scope)['files'][0]
            with context._db() as db:
                columns = [row[1] for row in db.execute('PRAGMA table_info(files)')]
            self.assertNotIn('content', columns)
            self.assertNotIn('body', columns)
            context.db_path.unlink()
            with self.assertRaises(ContextError):
                context.read({**scope, 'id': item['id']})
            rebuilt = context.search(scope)['files'][0]
            self.assertEqual((rebuilt['id'], rebuilt['revision']), (item['id'], item['revision']))
            self.assertEqual(context.read({**scope, 'id': item['id'], 'revision': item['revision']})['content'], 'Synthetic document body')
            self.assertEqual(context.path.read_bytes(), original)

    def test_cli_scoped_query_keeps_native_transport_and_host_paths_off_wire(self):
        import city
        args = ['city.py', 'file-read', '--device-id', 'synthetic-device', '--root-id', 'synthetic-root',
                '--id', 'synthetic-file', '--revision', 'synthetic-revision', '--max-bytes', '32']
        with patch.object(sys, 'argv', args), patch.object(city, 'native_request', return_value={'schemaVersion': 1}) as native:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(city.main(), 0)
            from urllib.parse import urlsplit, parse_qs
            path = native.call_args.args[0]
            self.assertEqual(urlsplit(path).path, '/api/v1/file-read')
            self.assertEqual(parse_qs(urlsplit(path).query), dict(deviceId=['synthetic-device'], rootId=['synthetic-root'],
                             id=['synthetic-file'], revision=['synthetic-revision'], maxBytes=['32']))
        with patch.object(sys, 'argv', ['city.py', 'file-read', '--path', '/synthetic/forbidden']), patch.object(city, 'native_request') as native:
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                city.main()
            native.assert_not_called()
