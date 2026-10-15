import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import server


class CatalogStateRegressions(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.panel = self.root / 'panel'
        self.skills = self.root / 'skills'
        self.repos = self.root / 'repos'
        for directory in (self.panel, self.skills, self.repos):
            directory.mkdir()
        pointer = self.root / 'storage.json'
        pointer.write_text(json.dumps({'schemaVersion': 1, 'dataRoot': str(self.root / 'data'),
            'panelDirectory': str(self.panel), 'skillsDirectory': str(self.skills),
            'repositoryRoots': [str(self.repos)], 'codexHome': str(self.root / 'codex')}), encoding='utf-8')
        for item in (patch.dict(os.environ, {'AGENT_CITY_CONFIG': str(pointer)}),
                     patch.object(server.access, 'clients', return_value=[]),
                     patch.object(server.credentials, 'revision', return_value=None),
                     patch.object(server.credentials, 'key_available', return_value=False)):
            item.start()
            self.addCleanup(item.stop)
        self.store = self.make_store()

    def make_store(self):
        return server.Store(self.panel, skills_root=self.skills, repo_roots=[self.repos],
            inventory_roots=[('synthetic', self.skills)], codex_home=self.root / 'codex',
            local_only=True, executable=False)

    @staticmethod
    def catalogue_payload(count=2000):
        return {'data': [{'id': 'dev/' + str(index).zfill(4) + 'x' * 185 + ':free',
            'name': 'Model ' + 'x' * 174, 'pricing': {'prompt': '0', 'completion': '0'},
            'architecture': {'input_modalities': ['text'], 'output_modalities': ['text']}}
            for index in range(count)]}

    def test_seed_model_can_be_favorited_and_survives_restart_without_catalog_refresh(self):
        snapshot = self.store.snapshot()
        model = snapshot['catalogs']['zen']['models'][0]
        self.assertFalse(model['priceVerified'])
        self.assertNotIn('zen', self.store.state['catalogs'])
        self.store.favorite(model['id'], True)
        restarted = self.make_store()
        self.assertEqual([model['id']], restarted.state['favorites'])
        self.assertNotIn('zen', restarted.state['catalogs'])
        self.assertFalse(restarted.snapshot()['catalogs']['zen']['models'][0]['priceVerified'])

    def test_unknown_or_hidden_catalogue_model_cannot_be_added(self):
        with self.assertRaises(ValueError):
            self.store.favorite('synthetic-unknown-model', True)
        self.assertFalse(self.store.path.exists())
        self.store.state['catalogs']['openrouter'] = {'models': [{'id': 'synthetic-hidden-model'}]}
        registry = self.store.providers.snapshot()
        self.store.providers.change('remove', {'id': 'openrouter'}, registry['revision'])
        with self.assertRaises(ValueError):
            self.store.favorite('synthetic-hidden-model', True)
        self.assertNotIn('openrouter', self.store.snapshot()['catalogs'])

    def test_paid_catalogue_favorites_and_snapshot_price_flags_are_preserved(self):
        self.store.state['catalogs']['openrouter'] = {'models': [], 'allModels': [
            {'id': 'synthetic-paid', 'priceVerified': False, 'priceStatus': 'paid'}]}
        self.store.state['catalogs']['cline'] = {'models': [
            {'id': 'synthetic-legacy-free', 'priceVerified': True}]}
        original = copy.deepcopy(self.store.state['catalogs'])
        self.store.favorite('synthetic-paid', True)
        snapshot = self.store.snapshot()
        self.assertEqual(original, self.store.state['catalogs'])
        self.assertEqual('paid', snapshot['catalogs']['openrouter']['allModels'][0]['priceStatus'])
        self.assertFalse(snapshot['catalogs']['cline']['models'][0]['priceVerified'])

    def test_valid_aggregate_catalogues_over_old_four_mib_limit_survive_restart(self):
        payload = self.catalogue_payload()
        self.assertLess(len(json.dumps(payload).encode('utf-8')), server.MAX_JSON)
        self.store.catalog_fetcher = lambda provider: server.normalize_catalog(provider, payload)
        self.store.local_only = False
        for provider in ('openrouter', 'kilo'):
            self.store._refresh_one(provider)
        model_id = payload['data'][0]['id']
        self.store.favorite(model_id, True)
        self.assertGreater(self.store.path.stat().st_size, server.MAX_JSON)
        restarted = self.make_store()
        self.assertEqual([model_id], restarted.state['favorites'])
        for provider in ('openrouter', 'kilo'):
            self.assertEqual(2000, len(restarted.state['catalogs'][provider]['models']))
            self.assertEqual(2000, len(restarted.state['catalogs'][provider]['allModels']))

    def test_existing_large_legacy_state_and_all_saved_favorites_are_recovered(self):
        favorites = ['synthetic-favorite-' + str(index) for index in range(2001)]
        legacy = {**self.store.state, 'favorites': favorites,
                  'directory': {'cached': 'x' * (server.MAX_JSON + 1)}}
        self.store.path.write_text(json.dumps(legacy), encoding='utf-8')
        restarted = self.make_store()
        self.assertEqual(favorites, restarted.state['favorites'])
        restarted.save()
        self.assertEqual(favorites, self.make_store().state['favorites'])

    def test_invalid_existing_state_fails_explicitly_and_preserves_original(self):
        for raw in (b'{"favorites": ["private-original"],',
                    b'{"schemaVersion": 2, "favorites": ["private-original"]}',
                    b'{"schemaVersion": 1, "favorites": "private-original"}'):
            with self.subTest(raw=raw):
                self.store.path.write_bytes(raw)
                with self.assertRaises(OSError) as caught:
                    self.make_store()
                self.assertNotIn('private-original', str(caught.exception))
                self.assertEqual(raw, self.store.path.read_bytes())

    def test_state_above_aggregate_read_limit_is_preserved_with_explicit_error(self):
        raw = b' ' * 257
        self.store.path.write_bytes(raw)
        with patch.object(server, 'MAX_STATE_BYTES', 256), self.assertRaises(OSError):
            self.make_store()
        self.assertEqual(raw, self.store.path.read_bytes())

    def test_save_size_failure_keeps_disk_state_and_rolls_back_favorite(self):
        self.store.save()
        original = self.store.path.read_bytes()
        model_id = self.store.snapshot()['catalogs']['zen']['models'][0]['id']
        self.store.state['directory'] = {'cached': 'x' * 4096}
        with patch.object(server, 'MAX_STATE_BYTES', len(original) + 100), self.assertRaises(OSError):
            self.store.favorite(model_id, True)
        self.assertEqual([], self.store.state['favorites'])
        self.assertEqual(original, self.store.path.read_bytes())
        self.assertEqual([], list(self.panel.glob('.state-*.tmp')))

    def test_refresh_size_failure_preserves_last_saved_preferences_and_clears_busy(self):
        self.store.state['catalogs']['openrouter'] = {'models': [{'id': 'synthetic-original'}]}
        self.store.favorite('synthetic-original', True)
        original = self.store.path.read_bytes()
        payload = self.catalogue_payload(20)
        self.store.catalog_fetcher = lambda provider: server.normalize_catalog(provider, payload)
        self.store.local_only = False
        self.store.busy.add('openrouter')
        with patch.object(server, 'MAX_STATE_BYTES', len(original) + 100):
            self.store._refresh_one('openrouter')
        self.assertEqual(original, self.store.path.read_bytes())
        self.assertEqual(['synthetic-original'], self.make_store().state['favorites'])
        self.assertIn('не удалось сохранить', self.store.state['catalogs']['openrouter']['error'])
        self.assertNotIn('openrouter', self.store.busy)
        self.assertEqual([], list(self.panel.glob('.state-*.tmp')))

    def test_matching_read_and_write_limits_accept_exact_boundary(self):
        expected_size = len(json.dumps(self.store.state, ensure_ascii=False, allow_nan=False).encode('utf-8'))
        with patch.object(server, 'MAX_STATE_BYTES', expected_size):
            self.store.save()
            self.assertEqual(expected_size, self.store.path.stat().st_size)
            self.assertEqual(self.store.state, self.make_store().state)


if __name__ == '__main__':
    unittest.main()
