import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import published_catalogs as published
import provider_catalogs
import server

class PublishedTests(unittest.TestCase):
    def test_parsers_ignore_prices_and_access(self):
        cases={'zen':'| Model | Model ID | Price |\n| --- | --- | --- |\n| Example | `test-model` | Free |', 'cerebras':'<table><tr><th>Model ID</th></tr><tr><td>test-model</td></tr></table>', 'groq':'<table><tr><th>Model ID</th></tr><tr><td>Example test-model</td></tr></table>'}
        for provider, text in cases.items():
            result=published.parse(provider,text)
            self.assertEqual(['test-model'],[m['id'] for m in result['models']])
            self.assertFalse(result['models'][0]['priceVerified'])
            self.assertEqual('unknown',result['accountAccess'])
            self.assertEqual(published.URLS[provider],result['sourceUrl'])
        with self.assertRaises(ValueError):published.parse('cerebras','<h1>Access denied</h1>')

    def test_native_adapters_unchanged_and_refresh_never_reads_keys(self):
        self.assertEqual('https://api.groq.com/openai/v1/models',provider_catalogs.SOURCES['groq']['url'])
        self.assertTrue(provider_catalogs.SOURCES['groq']['accountCatalog'])
        with patch.object(server.credentials,'read_key',side_effect=AssertionError('must not read key')),patch.object(published,'fetch',return_value={'models':[]}) as fetch:
            server.fetch_catalog('groq')
            fetch.assert_called_once_with('groq')

    def test_snapshot_is_dated_non_mutating_and_preserves_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory)/'skills').mkdir()
            store=server.Store(directory,skills_root=Path(directory)/'skills',repo_roots=[directory],codex_home=Path(directory)/'codex')
            store.state['catalogs']['groq']={'models':[],'error':'HTTP 403','attemptedAt':'failure-date'}
            before=json.dumps(store.state,sort_keys=True)
            first=store.snapshot()['catalogs']['groq'];second=store.snapshot()['catalogs']['groq']
            self.assertEqual(before,json.dumps(store.state,sort_keys=True))
            self.assertEqual(first['updatedAt'],second['updatedAt'])
            self.assertEqual('HTTP 403',first['error'])
            self.assertEqual('failure-date',first['attemptedAt'])
            self.assertEqual('official_docs_snapshot',first['sourceKind'])
            self.assertTrue(all(m['priceVerified'] is False for m in first['models']))
            sources={s['id']:s for s in store.snapshot()['sources']}
            for ident in ('openai','anthropic'):
                self.assertFalse(sources[ident]['keyEntrySupported'])
                self.assertFalse(sources[ident]['catalogSupported'])
                self.assertIsNone(store.snapshot()['credentials'][ident])
