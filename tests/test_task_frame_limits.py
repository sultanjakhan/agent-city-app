import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request

sys.path.insert(0, str(Path(__file__).resolve().parent))
from owner_client import authorize, owner_urlopen
from server import Server, Store

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from agent_mcp import Bridge
import desktop_bridge
import owner_broker
from tools.shared_task_mcp import serve as serve_shared


def http_json(url, *, body, headers):
    request = Request(url, data=json.dumps(body, ensure_ascii=False).encode(), method='POST', headers=headers)
    try:
        with owner_urlopen(request, timeout=3) as response:
            return response.status, json.loads(response.read().decode())
    except HTTPError as error:
        return error.code, json.loads(error.read().decode())


class TaskFrameLimitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        (root / 'skills').mkdir()
        (root / 'repos' / 'synthetic' / '.git').mkdir(parents=True)
        self.store = Store(root / 'data', skills_root=root / 'skills', executable=False,
                           inventory_roots=[], codex_home=root / 'codex-home', repo_roots=[root / 'repos'])
        self.http = Server(('127.0.0.1', 0), self.store)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        authorize(self.http)
        self.base = f'http://127.0.0.1:{self.http.server_port}'
        self.headers = {
            'Host': f'127.0.0.1:{self.http.server_port}',
            'X-Agent-City': '1',
            'X-Agent-City-Token': self.store.csrf_token,
            'Content-Type': 'application/json',
        }
        self.recorded = []
        self.original_enqueue = self.store.task_sync.enqueue
        self.store.task_sync.enqueue = self._record_enqueue

    def tearDown(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join(timeout=2)
        self.temp.cleanup()

    def _record_enqueue(self, operation_id, command, arguments):
        self.recorded.append((operation_id, command, arguments))
        return {'state': 'pending', 'operationId': operation_id}

    def test_authenticated_queue_accepts_exact_8000_utf8_bytes_above_legacy_4096(self):
        content = 'Ж' * 3998 + '"\\Ж'
        self.assertEqual(len(content.encode('utf-8')), 8000)
        payload = {'version': 1, 'operationId': 'frame-valid-8000', 'command': 'submit_result',
                   'arguments': {'content': content}}
        serialized = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.assertGreater(len(serialized), 4096)
        status, body = http_json(self.base + '/api/task-sync/queue', body=payload, headers=self.headers)
        self.assertEqual(status, 200)
        self.assertEqual(body['state'], 'pending')
        self.assertEqual(len(self.recorded), 1)
        self.assertEqual(len(self.recorded[0][2]['content'].encode('utf-8')), 8000)

    def test_queue_over_64k_is_413_before_enqueue_and_small_endpoint_keeps_4096_limit(self):
        oversized = {'version': 1, 'operationId': 'frame-too-large', 'command': 'submit_result',
                     'arguments': {'content': 'Ж' * 40000}}
        self.assertGreater(len(json.dumps(oversized, ensure_ascii=False).encode('utf-8')), 64 * 1024)
        status, _ = http_json(self.base + '/api/task-sync/queue', body=oversized, headers=self.headers)
        self.assertEqual(status, 413)
        self.assertEqual(self.recorded, [])

        small = {'id': 'synthetic', 'kind': 'used', 'eventId': 'small'}
        unauthenticated = dict(self.headers)
        unauthenticated.pop('X-Agent-City-Token')
        status, _ = http_json(self.base + '/api/skill-activity', body=small, headers=unauthenticated)
        self.assertEqual(status, 403)
        too_large_for_small_endpoint = {'id': 'synthetic', 'kind': 'used', 'eventId': 'x' * 5000}
        status, _ = http_json(self.base + '/api/skill-activity', body=too_large_for_small_endpoint, headers=self.headers)
        self.assertEqual(status, 413)


class PythonFrameLimitTests(unittest.TestCase):
    def test_broker_delegate_envelope_and_shared_mcp_accept_escaped_full_result(self):
        content = 'Ж' * 4000
        body = {'version': 1, 'operationId': 'escaped-full-result', 'command': 'submit_result',
                'arguments': {'content': content}}
        broker = owner_broker.OwnerBroker(Path('.'), 0, {}, lambda *args: None)
        incoming = io.BytesIO()
        broker.child = type('Child', (), {'stdin': incoming, 'poll': lambda self: None})()
        ident = 'a' * 32
        broker.responses.put({'version': 1, 'id': ident, 'ok': True, 'result': {'grant': 'synthetic'}})
        with patch('owner_broker.uuid.uuid4', return_value=type('Id', (), {'hex': ident})()), \
                patch('owner_broker.write_pipe', side_effect=lambda stream, raw, deadline: stream.write(raw)):
            self.assertEqual(broker.grant('POST', '/api/task-sync/queue', body), 'synthetic')
        self.assertGreater(len(incoming.getvalue()), 16384)
        self.assertLess(len(incoming.getvalue()), 64 * 1024)
        # Larger envelopes do not widen lifecycle/control inputs.
        with self.assertRaisesRegex(owner_broker.BrokerError, 'control message limit'):
            broker.rpc('bootstrap', {'padding': content})

        class Connection:
            config = {'scopes': ['tasks:execute']}
            def call(self, op, command, arguments):
                self.content = arguments['content']
                return {'accepted': True}
        connection = Connection()
        message = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params':
                   {'name': 'shared_task_command', 'arguments': {k: body[k] for k in ('operationId', 'command', 'arguments')}}}
        raw = json.dumps(message).encode() + b'\n'
        self.assertGreater(len(raw), 16000)
        out = io.BytesIO()
        serve_shared(connection, io.BytesIO(raw), out)
        self.assertFalse(json.loads(out.getvalue())['result']['isError'])
        self.assertEqual(connection.content, content)

    def test_bridge_allows_serialized_payload_above_16k_but_rejects_64k_before_subprocess(self):
        bridge = object.__new__(Bridge)
        bridge.name = 'synthetic-pipe'
        bridge.client = 'synthetic-client'
        valid = {'blob': 'Ж' * 10000}
        observed = {}

        def run(command, **kwargs):
            observed['input'] = kwargs['input']
            return type('Completed', (), {'stdout': b'{"ok":true,"result":{"accepted":true}}\n'})()

        with patch('agent_mcp.subprocess.run', side_effect=run):
            self.assertEqual(bridge.call(valid), {'accepted': True})
        self.assertGreater(len(observed['input']), 16 * 1024)
        self.assertLess(len(observed['input']), 64 * 1024)

        with patch('agent_mcp.subprocess.run') as process:
            with self.assertRaisesRegex(ValueError, 'request too large'):
                bridge.call({'blob': 'Ж' * 40000})
            process.assert_not_called()

    def test_private_bridge_agent_request_has_64k_limit_other_actions_keep_16k(self):
        request = {'version': 1, 'id': 1, 'action': 'agent-request', 'draftsClosed': False,
                   'request': {'method': 'POST', 'path': '/api/task-sync/queue',
                               'body': {'content': 'Ж' * 10000}}}
        raw = json.dumps(request, ensure_ascii=False).encode('utf-8') + b'\n'
        self.assertGreater(len(raw), 16 * 1024)
        self.assertLessEqual(len(raw), 64 * 1024)
        self.assertEqual(desktop_bridge.request(raw, 1)['action'], 'agent-request')

        with self.assertRaisesRegex(ValueError, 'frame'):
            desktop_bridge.request(raw + ('Ж'.encode('utf-8') * 30000), 1)

        ordinary = json.dumps({'version': 1, 'id': 1, 'action': 'bootstrap', 'draftsClosed': False}).encode()
        with self.assertRaises(ValueError):
            desktop_bridge.request(ordinary + (b' ' * 17000) + b'\n', 1)


if __name__ == '__main__':
    unittest.main()
