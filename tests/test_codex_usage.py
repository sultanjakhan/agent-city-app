import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from codex_usage import read_turn, enrich_report, usage_for_turn, UsageError

SESSION = '11111111-1111-4111-8111-111111111111'
TURN = '22222222-2222-4222-8222-222222222222'


def event(kind, **data):
    return {'type': 'event_msg', 'payload': {'type': kind, **data}}


def usage(total, last):
    def counts(values):
        return dict(zip(('input_tokens', 'output_tokens', 'cached_input_tokens'), values))
    return event('token_count', info={'total_token_usage': counts(total), 'last_token_usage': counts(last)})


def turn_records():
    return [{'type': 'session_meta', 'payload': {'id': SESSION}},
            event('task_started', turn_id='old'), usage((100, 20, 60), (100, 20, 60)),
            event('task_complete', turn_id='old'), event('task_started', turn_id=TURN),
            {'type': 'turn_context', 'payload': {'model': 'gpt-test'}},
            usage((130, 25, 70), (30, 5, 10)), usage((130, 25, 70), (30, 5, 10)),
            usage((170, 33, 90), (40, 8, 20)), event('task_complete', turn_id=TURN),
            event('task_started', turn_id='later'), usage((200, 40, 100), (30, 7, 10))]


class CodexUsageTests(unittest.TestCase):
    def read(self, records, suffix=''):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'session.jsonl'
            path.write_text(''.join(json.dumps(r) + '\n' for r in records) + suffix, encoding='utf-8')
            return read_turn(path, SESSION, TURN)

    def test_uses_one_turn_deltas_not_previous_later_or_repeated_usage(self):
        result = self.read(turn_records())
        self.assertEqual((result['inputTokens'], result['outputTokens'], result['cachedInputTokens']), (70, 13, 30))
        self.assertEqual(result['requests'], 2)
        self.assertEqual(result['model'], 'gpt-test')

    def test_private_content_is_never_exported(self):
        records = turn_records()
        records.insert(7, {'type': 'response_item', 'payload': {'text': 'PRIVATE_SENTINEL'}})
        self.assertNotIn('PRIVATE_SENTINEL', json.dumps(self.read(records)))

    def test_reset_or_missing_request_is_rejected_instead_of_estimated(self):
        for replacement in [usage((20, 3, 10), (20, 3, 10)), usage((150, 25, 70), (30, 5, 10))]:
            rows = turn_records(); rows[6] = replacement
            with self.assertRaisesRegex(UsageError, 'reset or skip'):
                self.read(rows)

    def test_incomplete_aborted_unknown_and_wrong_identity_are_rejected(self):
        rows = turn_records()
        variants = [rows[:9], rows[:9] + [event('turn_aborted', turn_id=TURN)], rows[1:]]
        wrong = turn_records(); wrong[0]['payload']['id'] = 'other'; variants.append(wrong)
        for variant in variants:
            with self.assertRaises(UsageError): self.read(variant, '{"unfinished"')

    def test_first_turn_requires_zero_baseline_consistent_with_last_request(self):
        rows = turn_records(); del rows[1:4]
        with self.assertRaisesRegex(UsageError, 'reset or skip'): self.read(rows)
        rows = [rows[0], rows[1], rows[2], usage((30, 5, 10), (30, 5, 10)), event('task_complete', turn_id=TURN)]
        self.assertEqual(self.read(rows)['inputTokens'], 30)

    def test_mixed_model_and_invalid_counters_rejected(self):
        rows = turn_records(); rows.insert(8, {'type': 'turn_context', 'payload': {'model': 'other'}})
        with self.assertRaisesRegex(UsageError, 'single observed model'): self.read(rows)
        rows = turn_records(); rows[6]['payload']['info']['total_token_usage']['input_tokens'] = True
        with self.assertRaisesRegex(UsageError, 'invalid'): self.read(rows)

    def test_enrichment_requires_bound_model_and_preserves_report_identity(self):
        measured = self.read(turn_records())
        report = {'runId': 'one-run', 'agent': 'codex', 'model': 'gpt-test', 'status': 'done', 'inputTokens': None}
        enriched = enrich_report(report, measured)
        self.assertEqual(enriched['runId'], 'one-run'); self.assertEqual(enriched['inputTokens'], 70)
        self.assertNotIn('sessionId', enriched); self.assertNotIn('cachedInputTokens', enriched)
        self.assertIsNone(report['inputTokens'])
        for changes in [{'model': None}, {'status': 'running'}, {'inputTokens': 9}, {'agent': 'other'}]:
            with self.assertRaises(UsageError): enrich_report({**report, **changes}, measured)

    def test_path_is_selected_by_explicit_uuids_only(self):
        with self.assertRaises(UsageError): usage_for_turn('../../secret', TURN)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(UsageError, 'not found uniquely'): usage_for_turn(SESSION, TURN, tmp)


if __name__ == '__main__':
    unittest.main()
