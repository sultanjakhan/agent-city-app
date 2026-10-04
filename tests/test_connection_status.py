import copy
import json
import unittest

import connection_status as status


class ConnectionStatusTests(unittest.TestCase):
    def sample(self, catalog=None, local_only=False, account=False):
        return {'serverTime': '2026-10-02T12:00:00Z', 'settings': {'localOnly': local_only},
                'sources': [{'id': 'lab', 'catalogUrl': 'https://example.invalid/models',
                             'accountCatalog': account}], 'catalogs': {'lab': catalog or {}}, 'checks': {}}

    def test_saved_docs_and_403_do_not_claim_provider_or_account_access(self):
        snapshot = self.sample({'models': [{'id': 'old'}], 'catalogScope': 'published',
                                'sourceUrl': 'https://example.invalid/docs?token=redacted#fragment',
                                'observedAt': '2026-09-27T09:00:00Z', 'updatedAt': '2026-09-27T09:00:00Z',
                                'attemptedAt': '2026-10-02T11:00:00Z', 'error': 'HTTP 403 private-response',
                                'authStatus': 'forbidden'}, local_only=True)
        before = copy.deepcopy(snapshot)
        row = status.summarize(snapshot)['lab']
        self.assertEqual(row['catalog']['source'], 'published_docs')
        self.assertEqual(row['catalog']['sourceUrl'], 'https://example.invalid/docs')
        self.assertTrue(row['catalog']['stale'])
        self.assertEqual(row['refresh']['state'], 'paused')
        self.assertEqual(row['refresh']['error'], {'category': 'forbidden', 'httpStatus': 403})
        self.assertEqual(row['authentication'], {'state': 'paused', 'lastObservation': None, 'clientObservation': None})
        self.assertEqual(row['providerAvailability'], 'not_checked')
        self.assertEqual(row['entitlement'], 'not_checked')
        self.assertNotIn('private-response', json.dumps(row))
        self.assertEqual(snapshot, before)

    def test_missing_empty_and_paid_only_catalogues_are_distinct(self):
        missing = status.summarize(self.sample({'error': 'HTTP 403'}))['lab']
        self.assertEqual(missing['catalog']['state'], 'missing')
        self.assertEqual(missing['catalog']['source'], 'none')
        empty = status.summarize(self.sample({'models': [], 'allModels': [{'id': 'paid'}],
                                             'updatedAt': '2026-10-02T11:00:00Z'}))['lab']
        self.assertEqual(empty['catalog']['state'], 'saved')
        self.assertEqual(empty['catalog']['modelCount'], 1)
        self.assertEqual(empty['entitlement'], 'not_checked')

    def test_successful_account_catalogue_is_a_dated_prior_observation(self):
        snapshot = self.sample({'models': [], 'updatedAt': '2026-10-02T11:00:00Z',
                                'attemptedAt': '2026-10-02T11:00:00Z', 'authStatus': 'accepted'}, account=True)
        row = status.summarize(snapshot)['lab']
        self.assertEqual(row['refresh']['lastResult'], 'succeeded')
        self.assertEqual(row['authentication']['state'], 'not_checked')
        self.assertEqual(row['authentication']['lastObservation']['status'], 'accepted')
        self.assertEqual(row['entitlement'], 'not_checked')

    def test_old_snapshot_and_missing_key_are_not_a_successful_refresh(self):
        for auth in ['unverified', 'missing_key']:
            row = status.summarize(self.sample({'models': [], 'updatedAt': '2026-09-27T00:00:00Z',
                                               'attemptedAt': '2026-10-02T11:00:00Z', 'authStatus': auth}))['lab']
            self.assertEqual(row['refresh']['lastResult'], 'not_checked')

    def test_refresh_timestamps_can_cross_a_second_and_historical_api_keeps_api_url(self):
        snapshot = self.sample({'models': [], 'updatedAt': '2026-10-02T10:59:59Z',
                                'attemptedAt': '2026-10-02T11:00:00Z'})
        snapshot['sources'][0].update(catalogMode='published', catalogUrl='https://example.invalid/docs',
                                      apiCatalogUrl='https://example.invalid/api/models')
        row = status.summarize(snapshot)['lab']
        self.assertEqual(row['refresh']['lastResult'], 'succeeded')
        self.assertEqual(row['catalog']['source'], 'provider_api')
        self.assertEqual(row['catalog']['sourceUrl'], 'https://example.invalid/api/models')

    def test_error_classification_never_returns_raw_response(self):
        cases = [('HTTP 401', 'authentication'), ('HTTP 429', 'rate_limit'), ('HTTP 503', 'http'),
                 ('Источник не ответил вовремя.', 'timeout'), ('Не удалось прочитать формат', 'format'),
                 ('Не удалось подключиться', 'network'), ('Не удалось сохранить', 'storage'),
                 ('private arbitrary source body', 'unknown')]
        for raw, category in cases:
            with self.subTest(category=category):
                self.assertEqual(status.error_reason(raw)['category'], category)
                self.assertNotIn(raw, json.dumps(status.error_reason(raw)))

    def test_client_sign_in_and_completed_reply_remain_dated_not_entitlement(self):
        snapshot = self.sample(local_only=True)
        snapshot['providerRuntime'] = {'lab': {'client': 'codex', 'source': 'codex-login-status',
                                              'status': 'authenticated', 'auth': 'chatgpt',
                                              'checkedAt': '2026-10-01T11:00:00Z'}}
        snapshot['checks'] = {'one': {'provider': 'lab', 'status': 'ok', 'reply': 'synthetic',
                                      'finishReason': 'stop', 'attemptedAt': '2026-10-01T11:00:00Z'},
                              'two': {'provider': 'lab', 'status': 'ok', 'reply': 'incomplete',
                                      'finishReason': 'length', 'attemptedAt': '2026-10-02T11:00:00Z'}}
        row = status.summarize(snapshot)['lab']
        self.assertEqual(row['authentication']['state'], 'paused')
        self.assertEqual(row['authentication']['clientObservation']['observedAt'], '2026-10-01T11:00:00+00:00')
        self.assertEqual(row['inference']['state'], 'paused')
        self.assertEqual(row['inference']['lastCompletedReplyAt'], '2026-10-01T11:00:00+00:00')
        self.assertEqual(row['entitlement'], 'not_checked')

    def test_invalid_timestamps_and_sensitive_urls_are_not_exposed(self):
        for value in [None, 'invalid', '2026-10-02T11:00:00']:
            self.assertIsNone(status.stamp(value))
        for value in [None, 'http://example.invalid', 'https://user:password@example.invalid/docs']:
            self.assertIsNone(status.public_url(value))
