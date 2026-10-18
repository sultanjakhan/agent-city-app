import copy
import hashlib
from pathlib import Path
import tempfile
import unittest

from task_connection import TaskConnection, TaskError, default_config
from task_sync import TaskSync

NS = '11111111-1111-4111-8111-111111111111'


def task(identity):
    return dict(id=identity, version=1, title='Synthetic', content='', tags='',
                results=[], history=[], comments=[], intents=[], reports=[],
                binding=dict(sourceNamespace=NS, sourceType='note', sourceId=identity,
                             taskKey='cicada-' + hashlib.sha256(NS.encode()).hexdigest()[:16] + '-' + identity))


class Bridge:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def call(self, request):
        self.calls.append(copy.deepcopy(request))
        if request['body']['command'] == 'snapshot':
            return dict(schemaVersion=1, sourceNamespace=NS, complete=True,
                        tasks=[], tombstones=[])
        return copy.deepcopy(self.response)


def config(root):
    return dict(default_config(), enabled=True, transport='pipe', endpoint='', tokenEnv='',
                profile=str(root / 'synthetic.db'), client=str(root / 'synthetic-client'),
                scopes=['tasks:read', 'tasks:execute'])


class ResponseIdentityTests(unittest.TestCase):
    def test_wrong_task_receipt_does_not_retire_exact_launch_request(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bridge = Bridge(dict(operationId='synthetic-ack-001', acknowledged=True,
                                 task=task('different-task')))
            sync = TaskSync(root, lambda cfg: TaskConnection(cfg, bridge))
            sync.stop.set()
            sync.configure(config(root), 0)
            args = dict(taskId='requested-task', expectedVersion=1,
                        intentId='synthetic-intent', report=dict(runId='synthetic-run', status='running'))
            sync.enqueue('synthetic-ack-001', 'acknowledge', args)
            state = sync.exchange()
            self.assertIn('synthetic-ack-001', state['outbox'])
            self.assertEqual(state['outbox']['synthetic-ack-001']['state'], 'pending')
            self.assertEqual(state['outbox']['synthetic-ack-001']['request']['arguments'], args)
            self.assertEqual(state['tasks'], {})
            self.assertNotIn('synthetic-ack-001', state['receipts'])
            bridge.response['task'] = task('requested-task')
            state = sync.exchange()
            self.assertEqual(state['receipts']['synthetic-ack-001']['state'], 'acknowledged')
            writes = [c for c in bridge.calls if c['body']['command'] == 'acknowledge']
            self.assertEqual(len(writes), 2)
            self.assertEqual(writes[0], writes[1])

    def test_get_and_receipt_reject_inconsistent_source_binding(self):
        with tempfile.TemporaryDirectory() as temp:
            for command in ('get', 'acknowledge'):
                row = task('requested-task')
                row['binding']['sourceId'] = 'different-task'
                response = row if command == 'get' else dict(task=row, acknowledged=True, operationId='synthetic-ack-001')
                client = TaskConnection(config(Path(temp)), Bridge(response))
                with self.subTest(command=command):
                    with self.assertRaises(TaskError) as error:
                        client.call('synthetic-ack-001', command, dict(taskId='requested-task'))
                    self.assertEqual(error.exception.code, 'task_response_identity_mismatch')
                    self.assertEqual(error.exception.status, 503)

    def test_exact_get_identity_is_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            row = task('requested-task')
            client = TaskConnection(config(Path(temp)), Bridge(row))
            self.assertEqual(client.call('synthetic-get-001', 'get', dict(taskId='requested-task')), row)
