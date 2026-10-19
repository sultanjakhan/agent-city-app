import hashlib
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import time
import unittest
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, build_opener, ProxyHandler

from file_context import FileContext, ContextError, config_lock
from text_reader import canonical, handle_path
from model_query import page_models

APP = Path(__file__).resolve().parents[1]
SKILL = '---\nname: synthetic-skill\ndescription: Safe fixture for scoped reading.\n---\n# Example\nRead only.\n'


class ContextTransportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.skills = self.base / 'skills'
        self.skills.mkdir()
        (self.skills / 'demo').mkdir()
        (self.skills / 'demo' / 'SKILL.md').write_text(SKILL, encoding='utf-8')
        (self.skills / 'example.md').write_text('ordinary Windows text\n', encoding='utf-8')
        (self.skills / 'long.txt').write_text('Я' * 40000, encoding='utf-8')
        self.repo = self.base / 'repos' / 'fixture-repo'
        (self.repo / '.git').mkdir(parents=True)
        (self.repo / '.git' / 'HEAD').write_text('ref: refs/heads/main\n', encoding='utf-8')
        self.data = self.base / 'data'
        self.context = FileContext(self.data)
        self.grant(self.skills)
        self.children, self.junctions = [], []
        self.start()

    def grant(self, path):
        self.context.grant(path, 'Fixture', self.context.roots()['revision'])
        self.root = self.context.roots()['roots'][-1]
        self.scope = {'deviceId': self.root['deviceId'], 'rootId': self.root['id']}

    def start(self, legacy=False):
        args = [sys.executable, '-X', 'utf8', str(APP / 'tests/context_fixture.py'), '--data', str(self.data), '--skills', str(self.skills)]
        if legacy:
            args.append('--legacy-models')
        child = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8',
                                 **({'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}))
        self.children.append(child)
        raw = child.stdout.readline()
        if not raw:
            self.fail('isolated backend startup: ' + child.stderr.read()[:1000])
        config = json.loads(raw)
        self.port = config['port']
        self.url = f'http://127.0.0.1:{self.port}'
        self.headers = {'Host': config['ownerHost'], 'Origin': 'http://' + config['ownerHost']}
        req = Request(self.url + '/api/owner-bootstrap',
                      data=json.dumps({'capability': config['bootstrap']}).encode(),
                      headers={**self.headers, 'Content-Type': 'application/json', 'X-Agent-City': '1'})
        with build_opener(ProxyHandler({})).open(req, timeout=5) as response:
            self.headers['Cookie'] = response.headers['Set-Cookie'].split(';', 1)[0]

    def tearDown(self):
        for child in self.children:
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    child.kill(); child.wait(timeout=3)
            child.stdout.close(); child.stderr.close()
        for path in self.junctions:
            if path.exists():
                os.rmdir(path)
        self.temp.cleanup()

    def http(self, resource, values=None):
        opener = build_opener(ProxyHandler({}))
        url = self.url + resource + ('?' + urlencode(values) if values else '')
        try:
            with opener.open(Request(url, headers=self.headers), timeout=15) as response:
                raw = response.read()
                return response.status, json.loads(raw), len(raw)
        except HTTPError as exc:
            raw = exc.read()
            return exc.code, json.loads(raw), len(raw)

    def mcp(self, name, values=None):
        messages = [dict(jsonrpc='2.0', id=1, method='initialize', params={'protocolVersion': '2025-03-26'}),
                    dict(jsonrpc='2.0', id=2, method='tools/call', params={'name': name, 'arguments': values or {}})]
        child = subprocess.run([sys.executable, '-X', 'utf8', str(APP / 'tests/context_stdio_fixture.py'), '--port', str(self.port)],
            input=json.dumps(self.headers) + '\n' + ''.join(json.dumps(m, ensure_ascii=False) + '\n' for m in messages), capture_output=True,
            text=True, encoding='utf-8', timeout=20,
            **({'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}))
        self.assertEqual(child.returncode, 0, child.stderr[:500])
        return json.loads(child.stdout.splitlines()[-1])['result']

    def search(self, **values):
        status, answer, _ = self.http('/api/v1/file-search', {**self.scope, **values})
        self.assertEqual(status, 200, answer)
        return answer

    def test_owner_session_and_scope_are_required_at_http_and_mcp_entries(self):
        for path in ('/api/v1/devices', '/api/v1/file-roots', '/api/v1/file-search', '/api/v1/file-read', '/api/v1/models'):
            with self.subTest(path=path), self.assertRaises(HTTPError) as error:
                build_opener(ProxyHandler({})).open(self.url + path, timeout=5)
            self.assertEqual(error.exception.code, 401)
            error.exception.close()
        # Explicit HTTP MCP cannot manufacture owner authentication.
        from context_mcp import LocalAPI
        denied = LocalAPI(self.port).call('agent_city_file_roots', {})
        self.assertTrue(denied['isError'])
        self.assertEqual(denied['structuredContent']['error'], 'owner_session_required')
        for path in ('/api/skill-inventory', '/api/v1/skill-inventory'):
            for values in ({'rootId': self.root['id']}, {'deviceId': 'foreign', 'rootId': self.root['id']}):
                self.assertEqual(self.http(path, values)[0], 404)
        self.assertEqual(self.http('/api/v1/file-search', {**self.scope, 'limit': 51})[0], 400)
        for values in ({'endLine': 201}, {'maxBytes': 32769}):
            item = self.search(q='example.md')['files'][0]
            self.assertEqual(self.http('/api/v1/file-read', {**self.scope, 'id': item['id'], **values})[0], 400)

    def test_symlink_escape_hardlink_and_retargeted_root_denied(self):
        outside = self.base / 'outside'
        outside.mkdir()
        secret = outside / 'outside.md'
        secret.write_text('Synthetic outside grant', encoding='utf-8')
        (self.skills / 'escape').symlink_to(outside, target_is_directory=True)
        (self.skills / 'linked.md').symlink_to(secret)
        os.link(secret, self.skills / 'hardlink.md')
        self.assertEqual(self.search(q='outside')['total'], 0)
        self.assertEqual(self.search(q='linked')['total'], 0)
        self.assertEqual(self.search(q='hardlink')['total'], 0)
        item = self.search(q='example.md')['files'][0]
        original = self.skills / 'example.md'
        original.unlink()
        original.symlink_to(secret)
        self.assertEqual(self.http('/api/v1/file-read', {**self.scope, 'id': item['id']})[0], 403)
        alias = self.base / 'root-alias'
        alias.symlink_to(self.skills, target_is_directory=True)
        self.grant(alias)
        self.assertEqual(self.search(q='demo', kind='skill')['total'], 1)
        alias.unlink()
        alias.symlink_to(outside, target_is_directory=True)
        status, error, _ = self.http('/api/v1/file-search', self.scope)
        self.assertEqual((status, error['error']), (403, 'root_redirected'))

    def test_public_roots_omit_private_paths_but_keep_authority(self):
        private_before, grants_revision = self.context.config()
        private_root = next(root for root in private_before['roots'] if root['id'] == self.root['id'])
        self.assertEqual(private_root['path'], str(self.skills.absolute()))
        self.assertEqual(private_root['canonicalPath'], canonical(self.skills))
        status, public, _ = self.http('/api/v1/file-roots')
        self.assertEqual(status, 200, public)
        answer = self.mcp('agent_city_file_roots')
        self.assertFalse(answer['isError'], answer)
        self.assertEqual(answer['structuredContent'], public)
        for document in (public, answer):
            wire = json.dumps(document, ensure_ascii=False)
            self.assertNotIn(json.dumps(str(self.skills), ensure_ascii=False), wire)
            self.assertNotIn(json.dumps(private_root['canonicalPath'], ensure_ascii=False), wire)
            self.assertNotIn(json.dumps(str(self.repo), ensure_ascii=False), wire)
            self.assertNotIn('"path"', wire)
            self.assertNotIn('"canonicalPath"', wire)
        public_root = next(root for root in public['roots'] if root['id'] == private_root['id'])
        self.assertEqual(set(public_root), {'id', 'deviceId', 'label', 'source', 'representation',
                                          'canonicalRootId', 'grantedAt', 'enabled'})
        self.assertTrue(public['suggestions'])
        self.assertTrue(any(suggestion.get('source') == 'repository' and suggestion['label'] == 'fixture-repo'
                            for suggestion in public['suggestions']))
        self.assertEqual(self.context.config(), (private_before, grants_revision))
        item = self.search(q='example.md')['files'][0]
        values = {**self.scope, 'id': item['id'], 'revision': item['revision']}
        self.assertEqual(self.http('/api/v1/file-read', values)[0], 200)
        self.context.revoke(self.root['id'], grants_revision)
        self.assertEqual(self.http('/api/v1/file-read', values)[0], 403)
        persisted, _ = self.context.config()
        self.assertEqual(persisted['roots'][0]['path'], private_root['path'])
        self.assertEqual(persisted['roots'][0]['canonicalPath'], private_root['canonicalPath'])

    def test_actual_skill_http_mcp_existing_reader_and_restart(self):
        result = self.search(q='synthetic', kind='skill', limit=1)
        self.assertEqual(result['total'], 1)
        skill = result['files'][0]
        self.assertTrue(skill['id'].startswith('skill-'))
        values = {**self.scope, 'id': skill['id'], 'revision': skill['revision'], 'startLine': 1, 'endLine': 4, 'maxBytes': 200}
        status, document, _ = self.http('/api/skill-inventory', values)
        self.assertEqual(status, 200, document)
        self.assertEqual(document['skillId'], skill['id'])
        answer = self.mcp('agent_city_read_skill', values)
        self.assertFalse(answer['isError'], answer)
        self.assertEqual(answer['structuredContent']['content'], document['content'])
        previous = self.children[-1]
        previous.terminate(); previous.wait(timeout=3)
        self.start()
        status, again, _ = self.http('/api/skill-inventory', values)
        self.assertEqual(status, 200, again)
        self.assertEqual(again['revision'], document['revision'])
        self.assertEqual(self.http('/api/v1/file-roots')[1]['revision'], self.context.roots()['revision'])

    def test_file_change_missing_revoke_and_no_paths(self):
        item = self.search(q='example.md')['files'][0]
        values = {**self.scope, 'id': item['id'], 'revision': item['revision']}
        path = self.skills / 'example.md'
        path.write_text('new text\n', encoding='utf-8')
        status, answer, _ = self.http('/api/v1/file-read', values)
        self.assertEqual((status, answer['error']), (409, 'file_changed'))
        changed = self.search(q='example.md')['files'][0]
        self.assertNotEqual(item['revision'], changed['revision'])
        self.assertEqual(self.http('/api/v1/file-search', {**self.scope, 'path': str(path)})[0], 400)
        self.assertTrue(self.mcp('agent_city_file_read', {**values, 'path': '../outside'})['isError'])
        self.assertEqual(self.http('/api/v1/file-read', {**self.scope, 'id': '../../outside'})[0], 404)
        path.unlink()
        status, answer, _ = self.http('/api/v1/file-read', values)
        self.assertEqual((status, answer['error']), (410, 'file_missing'))
        old = self.context.roots()['revision']
        self.context.revoke(self.root['id'], old)
        self.assertEqual(self.http('/api/v1/file-search', self.scope)[0], 403)
        self.assertEqual(self.http('/api/v1/file-read', values)[0], 403)
        self.assertTrue(self.mcp('agent_city_file_read', values)['isError'])
        with self.assertRaises(ContextError):
            self.context.grant(self.skills, 'Stale', old)

    def test_long_utf8_line_has_finite_continuation(self):
        item = self.search(q='long.txt')['files'][0]
        chunks, offset = [], 0
        for _ in range(5):
            status, answer, _ = self.http('/api/v1/file-read', {**self.scope, 'id': item['id'], 'startLine': 1, 'endLine': 1, 'maxBytes': 32768, 'byteOffset': offset})
            self.assertEqual(status, 200, answer)
            chunks.append(answer['content'])
            if answer['nextByteOffset'] is None:
                break
            self.assertGreater(answer['nextByteOffset'], offset)
            offset = answer['nextByteOffset']
        else:
            self.fail('continuation did not complete')
        self.assertEqual(''.join(chunks), 'Я' * 40000)
        self.assertEqual(self.http('/api/v1/file-read', {**self.scope, 'id': item['id'], 'maxBytes': 1})[0], 400)

    def test_two_http_and_mcp_model_pages_keep_revision(self):
        status, first, _ = self.http('/api/v1/models', {'limit': 1, 'tools': 'true'})
        self.assertEqual(status, 200)
        time.sleep(0.02)
        status, second, _ = self.http('/api/v1/models', {'limit': 1, 'offset': 1, 'tools': 'true', 'revision': first['revision']})
        self.assertEqual(status, 200, second)
        self.assertEqual(first['revision'], second['revision'])
        a = self.mcp('agent_city_models', {'limit': 1})
        b = self.mcp('agent_city_models', {'limit': 1, 'offset': 1, 'revision': a['structuredContent']['revision']})
        self.assertFalse(a['isError']); self.assertFalse(b['isError'], b)
        self.assertNotEqual(a['structuredContent']['routes'][0]['id'], b['structuredContent']['routes'][0]['id'])
        self.assertEqual(self.http('/api/v1/models', {'limit': 51})[0], 400)
        self.assertEqual(self.http('/api/v1/models', {'revision': 'stale'})[0], 409)

    @unittest.skipUnless(os.name == 'nt', 'Windows junction regression')
    def test_junction_alias_root_pinned_and_descendant_escape_denied(self):
        outside = self.base / 'outside'
        outside.mkdir()
        (outside / 'outside.md').write_text('synthetic outside grant\n', encoding='utf-8')
        alias = self.base / 'alias'
        nested = self.skills / 'redirect'
        for name, target in ((alias, self.skills), (nested, outside)):
            subprocess.run(['cmd', '/c', 'mklink', '/J', str(name), str(target)], check=True, capture_output=True)
            self.junctions.append(name)
        result = self.search(q='outside')
        self.assertEqual(result['total'], 0)
        self.grant(alias)
        self.assertEqual(self.search(q='example')['total'], 1)
        os.rmdir(alias)
        subprocess.run(['cmd', '/c', 'mklink', '/J', str(alias), str(outside)], check=True, capture_output=True)
        status, answer, _ = self.http('/api/v1/file-search', self.scope)
        self.assertEqual((status, answer['error']), (403, 'root_redirected'))


class ContextProtocolTests(unittest.TestCase):
    def test_invalid_messages_preserve_stdio_process_for_next_ping(self):
        messages = [None, [], {'jsonrpc': '2.0', 'id': 12, 'method': 42},
                    {'jsonrpc': '2.0', 'id': 14, 'method': 'initialize', 'params': None},
                    {'jsonrpc': '2.0', 'id': 15, 'method': 'initialize', 'params': []},
                    {'jsonrpc': '2.0', 'id': 13, 'method': 'ping'}]
        excessive_nesting = '{"jsonrpc":"2.0","id":16,"method":"ping","params":{"value":' + '[' * 1100 + '0' + ']' * 1100 + '}}\n'
        child = subprocess.run([sys.executable, '-X', 'utf8', str(APP / 'context_mcp.py'), '--port', '9'],
            input=excessive_nesting + ''.join(json.dumps(message) + '\n' for message in messages), capture_output=True,
            text=True, encoding='utf-8', timeout=5,
            **({'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}))
        self.assertEqual(child.returncode, 0, child.stderr)
        answers = [json.loads(line) for line in child.stdout.splitlines()]
        self.assertEqual(len(answers), 7)
        self.assertEqual([answer['id'] for answer in answers], [None, None, None, 12, 14, 15, 13])
        self.assertEqual([answer['error']['code'] for answer in answers[:-1]], [-32600] * 6)
        self.assertEqual(answers[-1]['result'], {})


if __name__ == '__main__':
    unittest.main()
