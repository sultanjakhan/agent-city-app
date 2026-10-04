from owner_client import authorize, headers as owner_headers
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.request import Request, build_opener, ProxyHandler
from urllib.error import HTTPError

import server


class LocalOnlyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        skills = root / 'skills'
        skills.mkdir()
        self.forbidden = []
        for module, name in [(server.credentials, 'read_key'), (server.credentials, 'info'), (server.credentials, 'revision'), (server.credentials, 'save_key'), (server.credentials, 'remove_key'), (server.access, 'key_available'), (server.CloudSync, '_profile'), (server.CloudSync, 'start')]:
            mocker = patch.object(module, name, side_effect=AssertionError('Protected operation reached'))
            self.forbidden.append(mocker.start())
            self.addCleanup(mocker.stop)
        self.store = server.Store(root / 'data', skills_root=skills, executable=False, local_only=True)
        self.store.state['checks']['synthetic'] = {'provider': 'openrouter', 'credentialRevision': 'synthetic-revision'}
        self.store.state['catalogs']['openrouter'] = {'models': [], 'credentialRevision': 'synthetic-revision'}
        self.http = server.Server(('127.0.0.1', 0), self.store)
        self.worker = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.worker.start(); authorize(self.http)
        self.base = f'http://127.0.0.1:{self.http.server_port}'

    def tearDown(self):
        self.http.shutdown()
        self.http.server_close()
        self.worker.join(3)
        for item in self.forbidden:
            item.assert_not_called()
        self.temp.cleanup()

    def get(self, route):
        with build_opener(ProxyHandler({})).open(Request(self.base + route,headers=owner_headers(self.base)), timeout=3) as response:
            return json.loads(response.read())

    def test_state_and_cloud_status_do_not_observe_secrets(self):
        state = self.get('/api/state')
        self.assertTrue(state['settings']['localOnly'])
        self.assertTrue(all(x is None for x in state['credentials'].values()))
        self.assertTrue(all(x['source'] == 'paused' and not x['canSave'] for x in state['credentialInfo'].values()))
        self.assertTrue(all(x['refresh']['state'] == 'paused' for x in state['connectionStatus'].values()))
        self.assertTrue(all(x['authentication']['state'] == 'paused' and x['entitlement'] == 'not_checked' for x in state['connectionStatus'].values()))
        providers = self.get('/api/v1/providers')['providers']
        self.assertTrue(all(x['connectionStatus']['authentication']['state'] == 'paused' for x in providers))
        self.assertEqual(self.get('/api/cloud')['state'], 'paused')
        self.assertTrue(self.get('/api/health')['localOnly'])

    def test_protected_routes_block_before_body_or_token_parsing(self):
        for route in ['/api/cloud/sync', '/api/cloud/profile', '/api/credential', '/api/refresh', '/api/check', '/api/check-pending']:
            req = Request(self.base + route, data=b'', headers=owner_headers(self.base,{'X-Agent-City': '1'}))
            with self.assertRaises(HTTPError) as caught:
                build_opener(ProxyHandler({})).open(req, timeout=3)
            self.assertEqual(caught.exception.code, 403)

    def test_local_writes_persist_without_protected_reads(self):
        self.store.state['catalogs']['openrouter']['models'] = [{'id': 'synthetic-model'}]
        self.store.favorite('synthetic-model', True)
        self.assertEqual(self.store.state['favorites'], ['synthetic-model'])
        self.assertEqual(json.loads(self.store.path.read_text('utf-8'))['favorites'], ['synthetic-model'])

    def test_direct_network_and_credential_methods_fail_closed(self):
        for method, args in [(self.store.refresh, ()), (self.store._refresh_one, ('openrouter',)), (self.store.check_pending, ()), (self.store.check, ('openrouter', 'synthetic')), (self.store.credential, ('openrouter',))]:
            with self.assertRaises(RuntimeError):
                method(*args)
