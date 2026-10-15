import json
import copy
import tempfile
import threading
import unittest
from pathlib import Path

from run_store import RunConflict, RunError, RunStore


def report(**overrides):
    value = {
        "runId": "run-00000001",
        "sequence": 1,
        "taskKey": "cicada-0123456789abcdef-task",
        "agent": "codex",
        "model": "model-a",
        "provider": "provider-a",
        "stage": "planning",
        "status": "running",
        "skillIds": ["skill-0123456789abcdef01234567"],
        "inputTokens": None,
        "outputTokens": None,
    }
    value.update(overrides)
    return value


class RunStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = RunStore(Path(self.temp.name))

    def tearDown(self):
        self.temp.cleanup()

    def test_unknown_token_counts_remain_null_and_are_not_inferred_as_zero(self):
        saved = self.store.report(report())
        self.assertIsNone(saved["inputTokens"])
        self.assertIsNone(saved["outputTokens"])
        self.assertIsNone(self.store.snapshot()[0]["inputTokens"])

    def test_legacy_v1_reports_load_without_rewriting_or_inventing_past_usage(self):
        self.store.report(report(inputTokens=12, outputTokens=3))
        data = json.loads(self.store.path.read_bytes())
        row = data['runs']['run-00000001']
        del row['mcpCalls']
        row['history'] = [{key: row['history'][0][key] for key in ('stage', 'status', 'reportedAt')}]
        raw = json.dumps(data).encode()
        self.store.path.write_bytes(raw)
        saved = self.store.snapshot()[0]
        self.assertEqual(raw, self.store.path.read_bytes())
        self.assertEqual((12, 3), (saved['inputTokens'], saved['outputTokens']))
        self.assertIsNone(saved['mcpCalls'])
        self.assertIsNone(saved['history'][0]['inputTokens'])
        self.assertIsNone(saved['history'][0]['outputTokens'])
        self.assertEqual([], saved['history'][0]['skillIds'])
        self.store.report(report(sequence=2, status='done', inputTokens=15, outputTokens=4))
        loaded = RunStore(self.temp.name).snapshot()[0]
        self.assertEqual(2, loaded['sequence'])
        self.assertEqual(2, len(loaded['history']))
        self.assertIsNone(loaded['history'][0]['inputTokens'])

    def test_legacy_compatibility_still_rejects_missing_required_or_unknown_fields(self):
        self.store.report(report())
        original = json.loads(self.store.path.read_bytes())
        for field in ('stage', 'sequence', 'updatedAt'):
            changed = copy.deepcopy(original)
            del changed['runs']['run-00000001'][field]
            self.store.path.write_text(json.dumps(changed))
            with self.assertRaises(RunError):
                self.store.snapshot()
        changed = copy.deepcopy(original)
        changed['runs']['run-00000001']['secret'] = 'not-accepted'
        self.store.path.write_text(json.dumps(changed))
        with self.assertRaises(RunError):
            self.store.snapshot()

    def test_mcp_and_skill_usage_changes_create_bounded_metadata_events(self):
        self.store.report(report(skillIds=[]))
        calls=[{'server':'docs','tool':'search','calls':1}]
        row=self.store.report(report(sequence=2,mcpCalls=calls,inputTokens=0))
        self.assertEqual(len(row['history']),2)
        self.assertEqual(row['history'][-1]['mcpCalls'],calls)
        self.assertIsNone(row['history'][-1]['outputTokens'])
        self.assertEqual(row['history'][-1]['inputTokens'],0)
        with self.assertRaises(RunError):
            self.store.report(report(sequence=3,mcpCalls=[dict(calls[0],arguments='private')]))
        with self.assertRaises(RunError):
            self.store.report(report(sequence=3,mcpCalls=[dict(calls[0],calls=0)]))
        self.assertEqual(self.store.report(report(sequence=2,mcpCalls=calls,inputTokens=0)),row)

    def test_totals_are_monotonic_and_same_executor_task_is_required(self):
        self.store.report(report(inputTokens=10, outputTokens=2))
        self.store.report(report(sequence=2, inputTokens=11, outputTokens=2))
        with self.assertRaises(RunError):
            self.store.report(report(sequence=3, inputTokens=10, outputTokens=3))
        with self.assertRaises(RunError):
            self.store.report(report(sequence=3, taskKey="cicada-fedcba9876543210-other"))
        with self.assertRaises(RunError):
            self.store.report(report(sequence=3, provider="other-provider"))

    def test_duplicate_sequence_is_idempotent_and_stale_sequence_conflicts(self):
        first = self.store.report(report())
        duplicate = self.store.report(report())
        self.assertEqual(duplicate, first)
        with self.assertRaises(RunConflict):
            self.store.report(report(sequence=1, status="done"))

    def test_stage_status_history_is_bounded_and_records_changes(self):
        self.store.report(report())
        for sequence in range(2, 38):
            self.store.report(report(sequence=sequence, stage=f"stage-{sequence}", status="waiting"))
        row = self.store.snapshot()[0]
        self.assertEqual(len(row["history"]), 30)
        self.assertEqual(row["history"][-1]["stage"], "stage-37")
        self.assertEqual(row["history"][-1]["status"], "waiting")

    def test_atomic_file_reloads_and_unknown_fields_or_secret_payloads_are_rejected(self):
        self.store.report(report())
        reloaded = RunStore(Path(self.temp.name))
        self.assertEqual(reloaded.snapshot()[0]["runId"], "run-00000001")
        with self.assertRaises(RunError):
            self.store.report(report(apiKey="secret"))
        with self.assertRaises(RunError):
            self.store.report(report(sequence=2, password="secret"))

    def test_concurrent_valid_reports_leave_highest_sequence_and_safe_history(self):
        self.store.report(report())
        barrier = threading.Barrier(3)
        outcomes = []

        def publish(sequence):
            barrier.wait()
            try:
                self.store.report(report(sequence=sequence, stage=f"stage-{sequence}"))
                outcomes.append("saved")
            except RunConflict:
                outcomes.append("conflict")

        workers = [threading.Thread(target=publish, args=(sequence,)) for sequence in (2, 3)]
        for worker in workers:
            worker.start()
        barrier.wait()
        for worker in workers:
            worker.join()
        row = self.store.snapshot()[0]
        self.assertEqual(row["sequence"], 3)
        self.assertEqual(row["stage"], "stage-3")
        self.assertTrue(all(outcome in {"saved", "conflict"} for outcome in outcomes))
        self.assertIn("saved", outcomes)

    def test_two_store_instances_cannot_replace_a_newer_accepted_report(self):
        self.store.report(report())
        second = RunStore(self.temp.name)
        read, release, second_done = threading.Event(), threading.Event(), threading.Event()
        original_read = self.store._read
        outcomes = []

        def paused_read():
            value = original_read()
            read.set()
            if not release.wait(3):
                raise AssertionError('report read was not released')
            return value

        def publish(store, sequence):
            try:
                store.report(report(sequence=sequence, stage=f'stage-{sequence}'))
                outcomes.append('saved')
            except RunConflict:
                outcomes.append('conflict')
            except Exception as error:
                outcomes.append(error)
            finally:
                if store is second:
                    second_done.set()

        self.store._read = paused_read
        first_worker = threading.Thread(target=publish, args=(self.store, 2))
        second_worker = threading.Thread(target=publish, args=(second, 3))
        first_worker.start()
        try:
            self.assertTrue(read.wait(3))
            second_worker.start()
            # Without the shared transaction lock, sequence 3 is accepted here
            # and then silently replaced by the first writer's sequence 2.
            second_done.wait(.1)
        finally:
            release.set()
            first_worker.join(3)
            if second_worker.ident is not None:
                second_worker.join(3)
        self.assertFalse(first_worker.is_alive())
        self.assertFalse(second_worker.is_alive())
        self.assertCountEqual(outcomes, ['saved', 'saved'])
        self.assertEqual(second.snapshot()[0]['sequence'], 3)
        self.assertEqual([item['stage'] for item in second.snapshot()[0]['history']],
                         ['planning', 'stage-2', 'stage-3'])


class PersistedWrongTypeTests(unittest.TestCase):
    def test_full_35_case_matrix_fails_closed_and_preserves_file(self):
        with tempfile.TemporaryDirectory() as directory:
            store = RunStore(directory);store.report(report())
            original = store.path.read_bytes();valid = json.loads(original)
            cases = []
            for field in ('status', 'agent'):
                cases += [('run',field,x) for x in ([],{},None,True,7,float('nan'),float('inf'))]
            cases += [('history','status',x) for x in ([],{},None,True,7,float('nan'),float('inf'))]
            for field in ('inputTokens','outputTokens'):
                cases += [('run',field,x) for x in ([],{},True,-1,1.5,float('nan'),float('inf'))]
            self.assertEqual(35,len(cases))
            for location,field,value in cases:
                changed = copy.deepcopy(valid);row = changed['runs']['run-00000001']
                (row if location=='run' else row['history'][0])[field]=value
                raw=json.dumps(changed).encode();store.path.write_bytes(raw)
                with self.subTest(location=location,field=field,type=type(value).__name__):
                    with self.assertRaises(RunError): store.snapshot()
                    self.assertEqual(raw,store.path.read_bytes())
            store.path.write_bytes(original);self.assertEqual(1,len(store.snapshot()))


if __name__ == "__main__":
    unittest.main()
