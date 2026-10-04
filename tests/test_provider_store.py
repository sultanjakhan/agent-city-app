from owner_client import authorize, owner_urlopen
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from provider_store import ProviderStore, ProviderError, ProviderConflict, website
from server import Store, Server, PROVIDERS
import server as server_module
import panel_keys as credentials


class ProviderStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = ProviderStore(self.root, PROVIDERS)

    def change(self, action, **payload):
        return self.store.change(action, payload, self.store.snapshot()['revision'])

    def test_unknown_website_persists_as_reference_without_endpoint(self):
        self.change('add', website='https://lab.example/docs/')
        reopened = ProviderStore(self.root, PROVIDERS)
        source = next(row for row in reopened.sources().values() if not row['supported'])
        self.assertEqual('https://lab.example/docs', source['website'])
        self.assertIsNone(source['url'])
        self.assertFalse(source['keyRequired'])
        self.change('remove', id=source['id'])
        self.assertFalse(any(not row['supported'] for row in ProviderStore(self.root, PROVIDERS).sources().values()))

    def test_known_provider_remove_restore_preserves_other_data(self):
        data = self.root / 'state.json'
        data.write_text('private snapshot', encoding='utf-8')
        self.change('remove', id='openrouter')
        self.assertNotIn('openrouter', ProviderStore(self.root, PROVIDERS).sources())
        self.change('add', website='https://openrouter.ai')
        self.assertIn('openrouter', self.store.sources())
        self.assertEqual('private snapshot', data.read_text(encoding='utf-8'))

    def test_duplicates_and_stale_revision_do_not_write(self):
        before = self.store.snapshot()['revision']
        self.change('add', website='https://lab.example')
        raw = self.store.path.read_bytes()
        with self.assertRaises(ProviderConflict):
            self.store.change('add', {'website': 'https://lab.example'}, before)
        with self.assertRaises(ProviderError):
            self.change('add', website='https://www.lab.example/another-page')
        with self.assertRaises(ProviderError):
            self.change('add', website='https://openrouter.ai')
        self.assertEqual(raw, self.store.path.read_bytes())

    def test_bad_links_rejected_without_network_or_file(self):
        for url in ('http://lab.example', 'https://localhost', 'https://127.0.0.1', 'https://[::1]',
                    'https://user:secret@lab.example', 'https://lab.example/?token=secret',
                    'https://lab.example/#token', 'https://lab.example:8443', 'https://lab.local', 'javascript:alert(1)'):
            with self.subTest(url=url), self.assertRaises(ProviderError):
                website(url)
        self.assertFalse(self.store.path.exists())

    def test_failed_write_keeps_original_and_retry_works(self):
        self.change('add', website='https://first.example')
        raw = self.store.path.read_bytes()
        with patch('provider_store.os.replace', side_effect=OSError('synthetic disk error')):
            with self.assertRaises(OSError):
                self.change('add', website='https://second.example')
        self.assertEqual(raw, self.store.path.read_bytes())
        self.assertEqual([], list(self.root.glob('.providers-*')))
        self.change('add', website='https://second.example')

    def test_corrupt_file_is_not_overwritten(self):
        self.store.path.write_text('{broken', encoding='utf-8')
        with self.assertRaises(ProviderError):
            self.store.change('add', {'website': 'https://lab.example'}, '')
        self.assertEqual('{broken', self.store.path.read_text(encoding='utf-8'))


class ProviderHttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        skills = root / 'skills'
        skills.mkdir()
        self.key_patch = patch.object(credentials, 'SECRET_ROOT', root / 'keys')
        self.key_patch.start()
        self.store = Store(root / 'data', skills_root=skills, executable=False, inventory_roots=[], repo_roots=[root], catalog_fetcher=lambda _: self.fail('unexpected fetch'))
        self.http = Server(('127.0.0.1', 0), self.store)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        authorize(self.http)
        self.base = f'http://127.0.0.1:{self.http.server_port}'

    def tearDown(self):
        self.http.shutdown(); self.http.server_close(); self.thread.join()
        self.key_patch.stop(); self.temp.cleanup()

    def post(self, action, payload, token=True):
        return self.post_path('/api/providers/' + action, payload, token)

    def post_path(self, path, payload, token=True):
        headers = {'Content-Type': 'application/json', 'X-Agent-City': '1'}
        if token:
            headers['X-Agent-City-Token'] = self.store.csrf_token
        req = Request(self.base + path, json.dumps(payload).encode(), headers=headers)
        try:
            with owner_urlopen(req, timeout=3) as response:
                return response.status, json.load(response)
        except HTTPError as exc:
            return exc.code, json.load(exc)

    def test_resolve_is_read_only_csrf_protected_and_never_accepts_unknown_key_route(self):
        revision = self.store.providers.snapshot()['revision']
        self.assertEqual(403, self.post('resolve', {'website': 'https://groq.com'}, token=False)[0])
        for site, supported, ident, key_supported in [('https://groq.com', True, 'groq', True),
                ('https://kilo.ai', True, 'kilo', False), ('https://unknown.example', False, None, False)]:
            status, result = self.post('resolve', {'website': site})
            self.assertEqual(200, status)
            self.assertEqual((supported, ident, key_supported), (result['supported'], result['id'], result['keySupported']))
        self.assertEqual(revision, self.store.providers.snapshot()['revision'])
        self.assertEqual(400, self.post('resolve', {'website': 'https://groq.com/?token=synthetic-secret'})[0])
        self.assertFalse(self.store.busy)

    def test_zen_groq_cerebras_already_present_add_is_not_a_storage_error(self):
        for ident, site in [('zen', 'https://opencode.ai'), ('groq', 'https://groq.com'), ('cerebras', 'https://cerebras.ai')]:
            with self.subTest(provider=ident):
                status, body = self.post('add', {'website': site, 'revision': self.store.providers.snapshot()['revision']})
                self.assertEqual(400, status)
                self.assertEqual('Этот провайдер уже добавлен.', body['error'])
                self.assertIn(ident, self.store.providers.sources())

    def test_csrf_revision_busy_and_catalog_visibility(self):
        self.store.state['catalogs']['openrouter'] = {'models': [{'id': 'demo', 'priceVerified': True}]}
        revision = self.store.providers.snapshot()['revision']
        payload = {'id': 'openrouter', 'revision': revision}
        self.assertEqual(403, self.post('remove', payload, token=False)[0])
        self.store.busy.add('openrouter')
        self.assertEqual(409, self.post('remove', payload)[0])
        self.store.busy.clear()
        status, snapshot = self.post('remove', payload)
        self.assertEqual(200, status)
        self.assertNotIn('openrouter', [row['id'] for row in snapshot['sources']])
        self.assertNotIn('openrouter', snapshot['catalogs'])
        self.assertIn('openrouter', self.store.state['catalogs'])
        self.assertEqual(409, self.post('remove', payload)[0])
        self.assertEqual(200, self.post('add', {'website': 'https://openrouter.ai', 'revision': snapshot['providerRegistry']['revision']})[0])
        self.assertIn('openrouter', self.store.snapshot()['catalogs'])
        self.assertFalse(self.store.busy)

    def test_unknown_website_never_refreshes_or_accepts_custom_api_url(self):
        status, snapshot = self.post('add', {'website': 'https://mock-lab.example', 'revision': self.store.providers.snapshot()['revision']})
        self.assertEqual(200, status)
        reference = next(row for row in snapshot['sources'] if row['supported'] is False)
        self.assertIsNone(reference['catalogUrl'])
        self.assertNotIn('keyUrl', reference)
        with self.assertRaises(ValueError):
            self.store.refresh(reference['id'])
        self.assertFalse(self.store.busy)

    def test_corrupt_registry_returns_read_error_and_does_not_reset_data(self):
        self.store.providers.path.write_text('{broken', encoding='utf-8')
        for path in ('/api/state', '/api/v1/providers'):
            with self.subTest(path=path), self.assertRaises(HTTPError) as caught:
                owner_urlopen(self.base + path, timeout=3)
            self.assertEqual(500, caught.exception.code)
            self.assertIn('Файл сохранён', json.load(caught.exception)['error'])
        self.assertEqual('{broken', self.store.providers.path.read_text(encoding='utf-8'))

    def test_legacy_cline_cache_is_not_relabelled_free_or_rewritten(self):
        self.store.state['catalogs']['cline'] = {'models': [{'id': 'trial', 'priceVerified': True}]}
        self.assertFalse(self.store.snapshot()['catalogs']['cline']['models'][0]['priceVerified'])
        self.assertTrue(self.store.state['catalogs']['cline']['models'][0]['priceVerified'])

    def test_deleted_provider_rejects_stale_check_and_key_form_without_side_effects(self):
        self.store.state['catalogs']['openrouter'] = {'models': [{'id': 'cached', 'priceVerified': True}]}
        self.store.providers.change('remove', {'id': 'openrouter'}, self.store.providers.snapshot()['revision'])
        with patch.object(server_module.threading, 'Thread') as worker:
            with self.assertRaises(ValueError):
                self.store.check('openrouter', 'cached')
            worker.assert_not_called()
        with patch.object(credentials, 'save_key') as save:
            with self.assertRaises(ValueError):
                self.store.credential('openrouter', 'synthetic-key', False)
            save.assert_not_called()

    def test_refresh_waiting_on_store_lock_does_not_fetch_a_deleted_provider(self):
        read = threading.Event()
        fetched = threading.Event()
        original_sources = self.store.providers.sources
        errors = []
        def sources():
            result = original_sources()
            read.set()
            return result
        def catalog(_provider):
            fetched.set()
            return {'models': []}
        def refresh():
            try:
                self.store.refresh('openrouter')
            except ValueError:
                pass
            except Exception as exc:
                errors.append(exc)
        self.store.catalog_fetcher = catalog
        with patch.object(self.store.providers, 'sources', side_effect=sources):
            with self.store.lock:
                worker = threading.Thread(target=refresh)
                worker.start()
                read.wait(0.2)
                self.store.providers.change('remove', {'id': 'openrouter'}, self.store.providers.snapshot()['revision'])
            worker.join(2)
            self.assertFalse(worker.is_alive())
            self.assertFalse(fetched.wait(0.2))
        self.assertEqual([], errors)

    def test_zen_groq_cerebras_restore_refresh_and_reopen_preserve_catalog(self):
        calls = []
        def catalog(provider):
            calls.append(provider)
            return {'models': [{'id': provider + '/unpriced', 'name': 'Synthetic catalog entry', 'priceVerified': False}]}
        self.store.catalog_fetcher = catalog
        with patch.object(credentials, 'key_available', return_value=True), patch.object(credentials, 'revision', return_value='fixture'):
            for ident, site in [('zen', 'https://opencode.ai'), ('groq', 'https://groq.com'), ('cerebras', 'https://cerebras.ai')]:
                with self.subTest(provider=ident):
                    self.store.last_attempt[ident] = time.monotonic()
                    self.assertEqual(200, self.post('remove', {'id': ident, 'revision': self.store.providers.snapshot()['revision']})[0])
                    self.assertEqual(200, self.post('add', {'website': site, 'revision': self.store.providers.snapshot()['revision']})[0])
                    self.assertEqual(200, self.post_path('/api/refresh', {'target': ident})[0])
                    deadline = time.monotonic() + 2
                    while ident in self.store.busy and time.monotonic() < deadline:
                        time.sleep(0.005)
                    self.assertNotIn(ident, self.store.busy)
                    self.assertIn(ident, calls)
                    reopened = Store(self.store.directory, skills_root=self.store.skills.root, executable=False,
                                     inventory_roots=[], repo_roots=[self.store.directory.parent], catalog_fetcher=catalog)
                    self.assertIn(ident, reopened.providers.sources())
                    self.assertEqual(ident + '/unpriced', reopened.state['catalogs'][ident]['models'][0]['id'])
                    self.assertIsNotNone(reopened.state['catalogs'][ident]['updatedAt'])

    def test_http_403_is_catalog_failure_without_proving_public_key_rejection(self):
        self.store.catalog_fetcher = lambda _: (_ for _ in ()).throw(HTTPError('https://fixture.example/models', 403, 'Forbidden', {}, None))
        with patch.object(credentials, 'key_available', return_value=True), patch.object(credentials, 'revision', return_value='fixture'):
            for ident in ('zen', 'groq', 'cerebras'):
                with self.subTest(provider=ident):
                    previous = {'models': [{'id': 'cached', 'priceVerified': False}], 'updatedAt': '2026-09-27T00:00:00Z'}
                    self.store.state['catalogs'][ident] = previous.copy()
                    self.store._refresh_one(ident)
                    current = self.store.state['catalogs'][ident]
                    self.assertEqual(previous['models'], current['models'])
                    self.assertEqual(previous['updatedAt'], current['updatedAt'])
                    self.assertIn('HTTP 403', current['error'])
                    self.assertIsNotNone(current['attemptedAt'])
                    self.assertEqual('unverified', current['authStatus'])

    def test_paid_only_or_unavailable_catalog_does_not_block_provider_records(self):
        self.assertEqual(200, self.post('add', {'website': 'https://subscription-only.example', 'revision': self.store.providers.snapshot()['revision']})[0])
        self.store.state['catalogs']['openrouter'] = {'models': [], 'updatedAt': '2026-10-01T00:00:00Z',
                                                    'pricingSummary': {'confirmedFree': 0, 'knownPaid': 3, 'unknown': 0, 'complete': True}}
        self.assertEqual(200, self.post('remove', {'id': 'openrouter', 'revision': self.store.providers.snapshot()['revision']})[0])
        status, snapshot = self.post('add', {'website': 'https://openrouter.ai', 'revision': self.store.providers.snapshot()['revision']})
        self.assertEqual(200, status)
        self.assertIn('openrouter', [row['id'] for row in snapshot['sources']])
        self.assertEqual([], snapshot['catalogs']['openrouter']['models'])
        self.assertTrue(any(row['name'] == 'subscription-only.example' for row in snapshot['sources']))
        self.assertFalse(self.store.busy)

    def test_old_public_403_does_not_imply_key_rejection_or_rewrite_cache(self):
        for ident in ('zen', 'groq', 'cerebras'):
            self.store.state['catalogs'][ident] = {'models': [], 'authStatus': 'forbidden', 'error': 'Доступ отклонён · HTTP 403'}
        snapshot = self.store.snapshot()
        self.assertEqual('unverified', snapshot['catalogs']['zen']['authStatus'])
        self.assertEqual('unverified', snapshot['catalogs']['cerebras']['authStatus'])
        self.assertEqual('unverified', snapshot['catalogs']['groq']['authStatus'])
        self.assertEqual('forbidden', self.store.state['catalogs']['cerebras']['authStatus'])
