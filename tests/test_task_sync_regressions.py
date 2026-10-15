"""Durable queue ordering and live connection fences, using a synthetic authority."""
import copy
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from task_connection import TaskError, default_config, encode
from task_sync import TaskSync


NAMESPACE = '11111111-1111-4111-8111-111111111111'
SAME_TIME = '2026-10-15T06:00:00+00:00'


def projection(ident, version=1, content='original'):
    return {
        'id': ident, 'version': version, 'title': ident, 'content': content, 'tags': '',
        'binding': {
            'sourceNamespace': NAMESPACE, 'sourceType': 'note', 'sourceId': ident,
            'taskKey': 'cicada-' + hashlib.sha256(NAMESPACE.encode()).hexdigest()[:16] + '-' + ident,
        },
        'results': [], 'history': [], 'comments': [], 'intents': [], 'reports': [],
    }


class Authority:
    """Expected-version writes, immutable operation receipts and optional lost ACKs."""
    def __init__(self):
        self.tasks = {ident: projection(ident) for ident in ('task-one', 'task-two')}
        self.receipts = {}
        self.calls = []
        self.after_commit = None
        self.drop_receipt = False

    def connect(self, config):
        authority = self

        class Client:
            def __init__(self):
                self.config = copy.deepcopy(config)

            def call(self, operation_id, command, arguments):
                authority.calls.append((operation_id, command, copy.deepcopy(arguments), self.config['sourceNamespace']))
                if command == 'snapshot':
                    return {'schemaVersion': 1, 'complete': True, 'sourceNamespace': NAMESPACE,
                            'tasks': list(copy.deepcopy(authority.tasks).values()), 'tombstones': []}
                request = encode({'command': command, 'arguments': arguments})
                if operation_id in authority.receipts:
                    original, receipt = authority.receipts[operation_id]
                    if original != request:
                        raise TaskError('operation_payload_conflict', 409)
                    return copy.deepcopy(receipt)
                if command == 'create':
                    ident = 'created-' + operation_id
                    row = projection(ident, content=arguments['content'])
                    row['title'] = arguments['title']
                    authority.tasks[ident] = row
                else:
                    row = authority.tasks[arguments['taskId']]
                    if arguments['expectedVersion'] != row['version']:
                        raise TaskError('revision_conflict', 409, row)
                    row.update(arguments['patch'])
                    row['version'] += 1
                receipt = {'operationId': operation_id, 'acknowledged': True, 'task': copy.deepcopy(row)}
                authority.receipts[operation_id] = request, receipt
                if authority.after_commit:
                    callback, authority.after_commit = authority.after_commit, None
                    callback()
                if authority.drop_receipt:
                    authority.drop_receipt = False
                    raise TaskError('task_connection_unavailable', 503)
                return copy.deepcopy(receipt)

        return Client()

    def mutations(self):
        return [(op, command, args) for op, command, args, _ in self.calls if command != 'snapshot']


class TaskSyncRegressionTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix='agent-city-sync-regression-')
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        # Tests explicitly drive each exchange; no background thread or real transport.
        worker = patch.object(TaskSync, 'start', return_value=None)
        worker.start()
        self.addCleanup(worker.stop)
        self.authority = Authority()
        self.sync = TaskSync(self.directory, self.authority.connect)
        self.configure(enabled=True, sourceNamespace=NAMESPACE, scopes=['tasks:read', 'tasks:write'])

    def configure(self, **changes):
        state = self.sync.snapshot()
        config = {**state['config'], **changes}
        self.sync.configure(config, state['revision'])

    def enqueue(self, op, task='task-one', content='edited', version=1):
        arguments = {'taskId': task, 'expectedVersion': version, 'patch': {'content': content}}
        return self.sync.enqueue(op, 'patch', arguments)

    def restart(self):
        self.sync = TaskSync(self.directory, self.authority.connect)

    def test_fifo_survives_equal_timestamps_key_sorting_restart_and_stale_edits(self):
        with patch('task_sync.now', return_value=SAME_TIME):
            first = self.enqueue('zzzzzzzz-first', content='first edit')
            second = self.enqueue('aaaaaaaa-later', content='later edit')
        self.assertEqual(first['queuedAt'], second['queuedAt'])
        self.assertLess(first['queueOrder'], second['queueOrder'])
        self.restart()

        state = self.sync.exchange()
        self.assertEqual([op for op, _, _ in self.authority.mutations()], ['zzzzzzzz-first'])
        self.assertEqual(state['tasks']['task-one']['content'], 'first edit')
        self.assertEqual(state['outbox']['aaaaaaaa-later']['state'], 'pending')
        self.assertEqual(state['outbox']['aaaaaaaa-later']['request']['arguments']['expectedVersion'], 1)

        state = self.sync.exchange()
        self.assertEqual(state['outbox']['aaaaaaaa-later']['state'], 'conflict')
        self.assertEqual(state['outbox']['aaaaaaaa-later']['conflict']['current']['content'], 'first edit')
        self.assertEqual(state['tasks']['task-one']['content'], 'first edit')

    def test_legacy_outbox_is_migrated_by_timestamp_and_persisted_before_new_commands(self):
        self.enqueue('zzzzzzzz-first', content='legacy first')
        self.enqueue('aaaaaaaa-later', content='legacy later')
        state = self.sync._read()
        state.pop('nextQueueOrder')
        for op, item in state['outbox'].items():
            item.pop('queueOrder')
            item['queuedAt'] = SAME_TIME if op == 'zzzzzzzz-first' else '2026-10-15T06:00:01+00:00'
        # This reproduces the sorted JSON document written by the old application.
        self.sync.path.write_bytes(encode(state))
        self.restart()
        new = self.enqueue('00000000-new', task='task-two')
        persisted = self.sync._read()
        self.assertLess(persisted['outbox']['zzzzzzzz-first']['queueOrder'],
                        persisted['outbox']['aaaaaaaa-later']['queueOrder'])
        self.assertLess(persisted['outbox']['aaaaaaaa-later']['queueOrder'], new['queueOrder'])
        self.restart()
        self.sync.exchange()
        self.assertEqual([op for op, _, _ in self.authority.mutations()], ['zzzzzzzz-first', '00000000-new'])

    def test_identical_legacy_timestamps_keep_a_stable_order_after_migration(self):
        self.enqueue('zzzzzzzz-first')
        self.enqueue('aaaaaaaa-later')
        state = self.sync._read()
        state.pop('nextQueueOrder')
        for item in state['outbox'].values():
            item.pop('queueOrder')
            item['queuedAt'] = SAME_TIME
        self.sync.path.write_bytes(encode(state))
        self.restart()
        # Equal legacy timestamps contain no recoverable original insertion order.
        # Preserve the encoded order once, then freeze it with durable ordinals.
        expected = list(self.sync._read()['outbox'])
        self.configure(staleAfterSeconds=301)
        migrated = self.sync._read()['outbox']
        actual = sorted(migrated, key=lambda op: migrated[op]['queueOrder'])
        self.assertEqual(actual, expected)
        self.restart()
        self.sync.exchange()
        self.assertEqual(self.authority.mutations()[0][0], expected[0])

    def test_unknown_outcome_retry_keeps_operation_id_payload_and_fifo_position(self):
        with patch('task_sync.now', return_value=SAME_TIME):
            first = self.enqueue('zzzzzzzz-first')
            self.enqueue('aaaaaaaa-later', task='task-two')
        self.authority.drop_receipt = True
        state = self.sync.exchange()
        self.assertEqual(state['outbox']['zzzzzzzz-first']['state'], 'pending')
        self.restart()
        retried = self.enqueue('zzzzzzzz-first')
        self.assertEqual(retried['queueOrder'], first['queueOrder'])
        self.assertEqual(retried['request'], first['request'])
        with self.assertRaises(TaskError):
            self.enqueue('zzzzzzzz-first', content='changed retry')
        state = self.sync.exchange()
        self.assertEqual([op for op, _, _ in self.authority.mutations()],
                         ['zzzzzzzz-first', 'zzzzzzzz-first', 'aaaaaaaa-later'])
        self.assertEqual(self.authority.tasks['task-one']['version'], 2)
        self.assertEqual(state['outbox'], {})
        self.assertEqual(state['receipts']['zzzzzzzz-first']['queueOrder'], first['queueOrder'])
        self.assertEqual(self.enqueue('zzzzzzzz-first')['state'], 'acknowledged')

    def test_disable_commits_inflight_ack_and_stops_unsent_commands_and_snapshot(self):
        first = self.enqueue('first-operation')
        second = self.enqueue('second-operation', task='task-two')
        self.authority.after_commit = lambda: self.configure(enabled=False)
        state = self.sync.exchange()
        self.assertFalse(state['config']['enabled'])
        self.assertEqual(state['receipts']['first-operation']['state'], 'acknowledged')
        self.assertEqual(state['receipts']['first-operation']['request'], first['request'])
        self.assertEqual(state['outbox']['second-operation']['request'], second['request'])
        self.assertEqual(state['outbox']['second-operation']['state'], 'pending')
        self.assertEqual(self.authority.tasks['task-two']['version'], 1)
        self.assertEqual(len(self.authority.calls), 1)
        self.sync.exchange()
        self.assertEqual(len(self.authority.calls), 1)
        self.configure(enabled=True)
        state = self.sync.exchange()
        self.assertEqual(state['receipts']['second-operation']['state'], 'acknowledged')

    def test_revoked_write_scope_keeps_unsent_draft_until_authorized_again(self):
        self.enqueue('first-operation')
        second = self.enqueue('second-operation', task='task-two')
        self.authority.after_commit = lambda: self.configure(scopes=['tasks:read'])
        state = self.sync.exchange()
        self.assertEqual(state['receipts']['first-operation']['state'], 'acknowledged')
        self.assertEqual(state['outbox']['second-operation']['state'], 'pending')
        self.assertEqual(len(self.authority.calls), 1)
        self.authority.tasks['task-two']['content'] = 'changed in the authority'
        state = self.sync.exchange()
        self.assertEqual(state['outbox']['second-operation']['state'], 'pending')
        self.assertIsNone(state['failure'])
        self.assertEqual(state['tasks']['task-two']['content'], 'changed in the authority')
        self.assertEqual(len(self.authority.mutations()), 1)
        self.assertEqual(self.authority.calls[-1][1], 'snapshot')
        self.configure(scopes=['tasks:read', 'tasks:write'])
        state = self.sync.exchange()
        self.assertEqual(state['receipts']['second-operation']['request'], second['request'])

    def test_changed_connection_credentials_stop_next_operation(self):
        self.enqueue('first-operation')
        self.enqueue('second-operation', task='task-two')
        self.authority.after_commit = lambda: self.configure(tokenEnv='NEW_TASK_TOKEN')
        state = self.sync.exchange()
        self.assertEqual(state['config']['tokenEnv'], 'NEW_TASK_TOKEN')
        self.assertEqual(state['receipts']['first-operation']['state'], 'acknowledged')
        self.assertEqual(state['outbox']['second-operation']['state'], 'pending')
        self.assertEqual(len(self.authority.calls), 1)

    def test_first_namespace_handshake_does_not_fence_remaining_valid_commands(self):
        self.configure(sourceNamespace=None)
        for op in ('zzzzzzzz-first', 'aaaaaaaa-later'):
            self.sync.enqueue(op, 'create', {'title': 'Synthetic task', 'content': op})
        state = self.sync.exchange()
        self.assertIsNone(state['failure'])
        self.assertEqual(state['config']['sourceNamespace'], NAMESPACE)
        self.assertEqual(state['outbox'], {})
        self.assertEqual([op for op, _, _ in self.authority.mutations()], ['zzzzzzzz-first', 'aaaaaaaa-later'])
        self.assertIsNone(self.authority.calls[0][3])
        self.assertEqual(self.authority.calls[1][3], NAMESPACE)
        self.assertIsNotNone(state['lastSuccess'])

    def test_disable_during_first_handshake_retains_pinned_namespace_and_ack(self):
        self.configure(sourceNamespace=None)
        self.sync.enqueue('first-operation', 'create', {'title': 'Synthetic task', 'content': 'first'})
        self.sync.enqueue('second-operation', 'create', {'title': 'Synthetic task', 'content': 'second'})
        self.authority.after_commit = lambda: self.configure(enabled=False)
        state = self.sync.exchange()
        self.assertFalse(state['config']['enabled'])
        self.assertEqual(state['config']['sourceNamespace'], NAMESPACE)
        self.assertEqual(state['receipts']['first-operation']['state'], 'acknowledged')
        self.assertEqual(state['outbox']['second-operation']['state'], 'pending')
        self.assertEqual(len(self.authority.calls), 1)


if __name__ == '__main__':
    unittest.main()
