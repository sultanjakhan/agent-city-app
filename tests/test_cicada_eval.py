import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import evaluate_cicada as evaluation


class EvalTests(unittest.TestCase):
    def test_exact_schema_and_unknowns(self):
        self.assertEqual(sorted(i for group in evaluation.BATCHES for i in group), list(range(20)))
        rows = [{'id': i, 'sphere': c[1], 'minutes': c[2], 'date': c[3]} for i, c in enumerate(evaluation.CASES)]
        self.assertEqual(evaluation.score(json.dumps(rows))['passed'], 20)
        rows[0]['id'] = False
        rows[5]['date'] = '2026-09-27'
        self.assertEqual(evaluation.score(json.dumps(rows))['failures'], [0, 5])
        self.assertFalse(evaluation.score('```json\n[]\n```')['validJson'])

    def test_price_unknown_never_sends(self):
        with patch.object(evaluation, 'fetch_catalog', return_value={'models': [{'id': 'x', 'priceVerified': False}]}), patch.object(evaluation, 'build_opener') as network:
            self.assertEqual(evaluation.run('openrouter', 'x')['status'], 'price_unverified')
            network.assert_not_called()
