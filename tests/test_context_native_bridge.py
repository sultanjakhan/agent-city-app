"""Synthetic owner grants plus real HTTP handler behind the standalone native MCP adapter.

The adapter pipe is substituted here; real Windows pipe self-tests run in hosted CI.
"""
import copy
import json
from pathlib import Path
import unittest
import subprocess
import sys
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

import test_owner_session as owner_fixture
from tools import agent_mcp
from context_mcp import TOOLS


class ContextNativeBridgeTests(unittest.TestCase):
    setUp = owner_fixture.OwnerSessionHttpTests.setUp
    stop = owner_fixture.OwnerSessionHttpTests.stop
    call = owner_fixture.OwnerSessionHttpTests.call

    def invoke(self, name, arguments):
        outer = self
        class NativeDispatch:
            def call(self, request):
                outer.assertEqual(request['method'], 'GET')
                outer.assertIsNone(request['body'])
                token = outer.http.owner_sessions.issue_grant(**request)
                status, body, _ = outer.call(request['path'], headers={
                    'Host': outer.owner, 'X-Agent-City-Grant': token})
                return {'status': status, 'value': body}
        return agent_mcp.invoke('agent-city', NativeDispatch(), name, arguments)

    def grant_fixture(self):
        root = Path(self.temp.name) / 'documents'
        root.mkdir()
        (root / 'example.txt').write_bytes(b'Synthetic bounded file\n')
        (root / 'SKILL.md').write_text('---\nname: sample\ndescription: Synthetic skill\n---\n# Sample\n', encoding='utf-8')
        (root / 'credentials.json').write_text('Synthetic excluded content', encoding='utf-8')
        context = self.store.file_context
        context.grant(root, 'Synthetic', context.roots()['revision'])
        grant = context.roots()['roots'][0]
        return {'deviceId': grant['deviceId'], 'rootId': grant['id']}

    def test_frozen_dispatcher_resolves_standalone_context_entry(self):
        source = Path(__file__).resolve().parents[1]
        result = subprocess.run([sys.executable, str(source / 'desktop_backend.py'), '--internal-script', 'context_mcp.py', '--help'], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--port', result.stdout)

    def test_standalone_contract_matches_context_mcp_without_backend_imports(self):
        exposed = agent_mcp.tools_for('agent-city')
        for definition in TOOLS:
            self.assertEqual(next(item for item in exposed if item['name'] == definition['name']), definition)
        self.assertFalse(set(item['name'] for item in TOOLS) & set(item['name'] for item in agent_mcp.tools_for('cicada')))
        with patch.object(agent_mcp, 'tools_for', wraps=agent_mcp.tools_for):
            for name in ('grant-root', 'agent_city_grant_root', 'agent_city_revoke_root'):
                with self.assertRaises(ValueError): agent_mcp.invoke('agent-city', None, name, {})

    def test_exact_owner_delegation_search_read_revision_and_revoke(self):
        scope = self.grant_fixture()
        roots = self.invoke('agent_city_file_roots', {})
        self.assertEqual(roots['status'], 200)
        self.assertNotIn(str(Path(self.temp.name)), json.dumps(roots['value']))
        listing = self.invoke('agent_city_file_search', {**scope, 'extension': '.txt', 'limit': 1})
        self.assertEqual(listing['status'], 200)
        item = listing['value']['files'][0]
        args = {**scope, 'id': item['id'], 'revision': item['revision'], 'maxBytes': 32}
        read = self.invoke('agent_city_file_read', args)
        self.assertEqual(read['status'], 200)
        self.assertEqual(read['value']['content'], 'Synthetic bounded file\n')
        changed = self.invoke('agent_city_file_read', {**args, 'revision': '0' * 64})
        self.assertEqual(changed['status'], 409)
        self.store.file_context.revoke(scope['rootId'], self.store.file_context.roots()['revision'])
        self.assertNotEqual(self.invoke('agent_city_file_read', args)['status'], 200)
        self.assertNotEqual(self.invoke('agent_city_file_search', scope)['status'], 200)

    def test_foreign_invalid_paths_private_names_and_bad_arguments_denied(self):
        scope = self.grant_fixture()
        self.assertEqual(self.call('/api/v1/file-roots')[0], 401)
        self.assertEqual(self.call('/api/v1/file-roots', headers={'Host': self.owner})[0], 401)
        for extra in ({'path': '/synthetic/outside'}, {'rootId': '../outside'}, {'deviceId': 'foreign-device'}):
            args = {**scope, **extra}
            if 'path' in args:
                with self.assertRaises(ValueError): self.invoke('agent_city_file_search', args)
            else: self.assertNotEqual(self.invoke('agent_city_file_search', args)['status'], 200)
        found = self.invoke('agent_city_file_search', {**scope, 'q': 'credentials'})
        self.assertEqual(found['value']['files'], [])
        for args in ({**scope, 'limit': True}, {**scope, 'limit': -1}, {**scope, 'q': []}, {**scope, 'endpoint': 'http://foreign.invalid'}):
            with self.assertRaises(ValueError): self.invoke('agent_city_file_search', args)
        self.assertNotEqual(self.invoke('agent_city_file_read', {**scope, 'id': '../outside'})['status'], 200)

    def test_grant_binds_exact_query_and_cannot_authorize_mutations(self):
        route = '/api/v1/file-search?deviceId=synthetic&rootId=synthetic'
        token = self.http.owner_sessions.issue_grant('GET', route, None)
        headers = {'Host': self.owner, 'X-Agent-City-Grant': token}
        self.assertEqual(self.call(route + '&path=outside', headers=headers)[0], 401)
        self.assertNotEqual(self.call(route, headers=headers)[0], 401)
        self.assertEqual(self.call(route, headers=headers)[0], 401)
        for route in ('/api/v1/grant-root', '/api/v1/revoke-root', '/api/v1/file-read'):
            with self.assertRaises(ValueError): self.http.owner_sessions.issue_grant('POST', route, {})

    def test_skill_and_model_queries_keep_bounds_and_no_http_fallback(self):
        scope = self.grant_fixture()
        found = self.invoke('agent_city_skill_search', {**scope, 'limit': 1})
        self.assertEqual(found['status'], 200)
        item = found['value']['files'][0]
        read = self.invoke('agent_city_read_skill', {**scope, 'id': item['id'], 'revision': item['revision'], 'maxBytes': 32})
        self.assertEqual(read['status'], 200)
        request = agent_mcp.context_request('agent_city_models', {'limit': 1, 'tools': False, 'revision': 'synthetic'})
        self.assertEqual(parse_qs(urlsplit(request['path']).query), {'limit': ['1'], 'tools': ['false'], 'revision': ['synthetic']})
        class Down:
            def call(self, request): raise TimeoutError('synthetic unavailable')
        with patch('urllib.request.OpenerDirector.open') as http:
            with self.assertRaises(TimeoutError): agent_mcp.invoke('agent-city', Down(), 'agent_city_devices', {})
            http.assert_not_called()


if __name__ == '__main__': unittest.main()
