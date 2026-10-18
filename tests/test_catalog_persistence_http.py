"""Disposable HTTP observations of failed catalogue writes; no provider calls."""
import copy
import json
import unittest
from unittest.mock import patch

import test_dashboard_http as fixture

request = fixture.request


class CatalogPersistenceHttpTests(unittest.TestCase):
    setUp = fixture.DashboardHttpTests.setUp
    tearDown = fixture.DashboardHttpTests.tearDown

    def snapshot(self):
        code, value = request(self.base + '/api/state')
        self.assertEqual(code, 200)
        return value

    def fail_refresh(self, target):
        self.store.busy.add(target)
        with patch('server.os.replace', side_effect=OSError('synthetic disk full')):
            self.store._refresh_one(target)
        self.assertNotIn(target, self.store.busy)

    def test_prior_snapshot_survives_failed_write_and_later_success_recovers(self):
        old = {'models': [{'id': 'previous-saved', 'priceVerified': True}],
               'allModels': [{'id': 'previous-saved'}], 'updatedAt': '2026-10-01T10:00:00+00:00',
               'observedAt': '2026-10-01T09:00:00+00:00', 'sourceKind': 'synthetic-api'}
        self.store.state['catalogs']['openrouter'] = copy.deepcopy(old)
        self.store.state['favorites'] = ['keep-favorite']
        self.store.state['checks'] = {'keep': {'provider': 'openrouter', 'status': 'not_checked'}}
        self.store.save()
        before = self.store.path.read_bytes()
        unrelated = copy.deepcopy({k: self.store.state[k] for k in ['favorites', 'checks']})
        self.store.catalog_fetcher = lambda target: {'models': [{'id': 'new-unsaved'}], 'observedAt': '2026-10-18T04:00:00+00:00', 'sourceKind': 'new-unsaved-source'}
        with patch('server.credentials.revision', return_value='synthetic-revision'):
            self.fail_refresh('openrouter')
            value = self.snapshot()
            catalog = value['catalogs']['openrouter']
            for key, expected in old.items():
                self.assertEqual(catalog[key], expected)
            self.assertGreater(catalog['attemptedAt'], old['updatedAt'])
            self.assertEqual(value['connectionStatus']['openrouter']['refresh']['error']['category'], 'storage')
            self.assertEqual(value['connectionStatus']['openrouter']['refresh']['lastResult'], 'failed')
            self.assertEqual(self.store.path.read_bytes(), before)
            # An unrelated later save must not accidentally persist the rejected payload.
            self.store.save()
            disk = json.loads(self.store.path.read_bytes())
            self.assertEqual(disk['catalogs']['openrouter']['models'], old['models'])
            self.assertEqual({k: self.store.state[k] for k in unrelated}, unrelated)
            self.store.catalog_fetcher = lambda target: {'models': [{'id': 'recovered'}]}
            self.store.busy.add('openrouter')
            self.store._refresh_one('openrouter')
            recovered = self.snapshot()
            self.assertEqual(recovered['catalogs']['openrouter']['models'][0]['id'], 'recovered')
            self.assertEqual(recovered['connectionStatus']['openrouter']['refresh']['lastResult'], 'succeeded')
            self.assertIsNone(recovered['catalogs']['openrouter']['error'])
            self.assertEqual(json.loads(self.store.path.read_bytes())['catalogs']['openrouter'], self.store.state['catalogs']['openrouter'])
            self.assertNotIn('openrouter', self.store.busy)

    def test_no_prior_snapshot_stays_missing_after_failed_write(self):
        self.store.state['catalogs'].pop('openrouter', None)
        self.store.save()
        before = self.store.path.read_bytes()
        self.store.catalog_fetcher = lambda target: {'models': [{'id': 'never-saved'}], 'observedAt': '2026-10-18T04:00:00+00:00', 'sourceKind': 'new-unsaved-source'}
        with patch('server.credentials.revision', return_value='synthetic-revision'):
            self.fail_refresh('openrouter')
            value = self.snapshot()
        catalog = value['catalogs']['openrouter']
        self.assertEqual(catalog['models'], [])
        self.assertNotIn('updatedAt', catalog)
        self.assertNotIn('observedAt', catalog)
        self.assertNotIn('sourceKind', catalog)
        self.assertTrue(catalog['attemptedAt'])
        self.assertEqual(value['connectionStatus']['openrouter']['catalog']['state'], 'missing')
        self.assertEqual(self.store.path.read_bytes(), before)

    def test_codexbar_shared_write_path_keeps_previous_snapshot(self):
        old = {'updatedAt': '2026-10-01T10:00:00+00:00', 'providers': [{'id': 'old'}]}
        self.store.state['codexbar'] = copy.deepcopy(old)
        self.store.executable = 'synthetic-unused-path'
        self.store.bar_fetcher = lambda executable: {'providers': [{'id': 'unsaved'}]}
        self.store.save()
        before = self.store.path.read_bytes()
        self.fail_refresh('codexbar')
        value = self.snapshot()['codexbar']
        self.assertEqual(value['providers'], old['providers'])
        self.assertEqual(value['updatedAt'], old['updatedAt'])
        self.assertTrue(value['attemptedAt'])
        self.assertIn('не удалось сохранить', value['error'])
        self.assertEqual(self.store.path.read_bytes(), before)

    def test_failed_write_keeps_actual_account_auth_observation_separate_from_old_payload(self):
        from server import PROVIDERS
        old = {'models': [{'id': 'old'}], 'updatedAt': '2026-10-01T10:00:00+00:00',
               'authStatus': 'rejected', 'credentialRevision': 'old-revision'}
        self.store.state['catalogs']['openrouter'] = old
        self.store.save()
        self.store.catalog_fetcher = lambda target: {'models': [{'id': 'unsaved'}]}
        with patch.dict(PROVIDERS['openrouter'], {'accountCatalog': True}), \
             patch('server.credentials.key_available', return_value=True), \
             patch('server.credentials.revision', return_value='new-revision'):
            self.fail_refresh('openrouter')
            value = self.snapshot()
        row = value['connectionStatus']['openrouter']
        self.assertEqual(value['catalogs']['openrouter']['models'], old['models'])
        self.assertEqual(self.store.state['catalogs']['openrouter']['credentialRevision'], 'new-revision')
        self.assertEqual(row['authentication']['lastObservation']['status'], 'accepted')
        self.assertEqual(row['authentication']['lastObservation']['observedAt'], value['catalogs']['openrouter']['attemptedAt'])
        self.assertEqual(row['authentication']['state'], 'not_checked')
        self.assertEqual(row['refresh']['lastResult'], 'failed')

    def test_recent_prior_snapshot_does_not_turn_failed_attempt_into_success(self):
        old = {'models': [{'id': 'recent-saved'}], 'updatedAt': '2026-10-18T04:00:00+00:00'}
        self.store.state['catalogs']['openrouter'] = copy.deepcopy(old)
        self.store.save()
        self.store.catalog_fetcher = lambda target: {'models': [{'id': 'unsaved'}], 'observedAt': '2026-10-18T04:00:01+00:00'}
        with patch('server.now', return_value='2026-10-18T04:00:01+00:00'), \
             patch('server.credentials.revision', return_value='synthetic-revision'):
            self.fail_refresh('openrouter')
            value = self.snapshot()
        self.assertEqual(value['catalogs']['openrouter']['updatedAt'], old['updatedAt'])
        self.assertNotIn('observedAt', value['catalogs']['openrouter'])
        self.assertEqual(value['connectionStatus']['openrouter']['refresh']['lastResult'], 'failed')
        self.assertEqual(value['connectionStatus']['openrouter']['refresh']['error']['category'], 'storage')
