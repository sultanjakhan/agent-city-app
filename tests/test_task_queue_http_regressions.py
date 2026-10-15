"""Task editor requests use the real authenticated HTTP queue and durable store."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, build_opener, ProxyHandler

from owner_client import authorize, headers as owner_headers
from server import Server, Store
from task_connection import default_config
from task_sync import TaskSync


class TaskQueueHttpRegressions(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        (root / 'skills').mkdir()
        (root / 'repos').mkdir()
        self.store = Store(root / 'panel', skills_root=root / 'skills',
                           inventory_roots=[], repo_roots=[root / 'repos'], codex_home=root / 'codex',
                           executable=False, local_only=True)
        config = {**default_config(), 'scopes': ['tasks:read', 'tasks:write']}
        self.store.task_sync.configure(config, 0)
        self.http = Server(('127.0.0.1', 0), self.store)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)
        authorize(self.http)
        self.base = f'http://127.0.0.1:{self.http.server_port}'

    def close_server(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join(timeout=3)

    def post(self, payload, *, csrf=True):
        headers = {'X-Agent-City': '1', 'Content-Type': 'application/json'}
        if csrf:
            headers['X-Agent-City-Token'] = self.store.csrf_token
        request = Request(self.base + '/api/task-sync/queue',
                          data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
                          headers=owner_headers(self.base, headers), method='POST')
        try:
            with build_opener(ProxyHandler({})).open(request, timeout=3) as response:
                return response.status, json.loads(response.read())
        except HTTPError as error:
            return error.code, json.loads(error.read())

    def test_long_editor_text_is_queued_unchanged_and_survives_retry_and_restart(self):
        content = '\u042f' * 2100
        cases = [
            ('create', {'title': 'Synthetic task', 'content': content}),
            ('patch', {'taskId': 'synthetic-task', 'expectedVersion': 1,
                       'patch': {'content': content}}),
            ('comment', {'taskId': 'synthetic-task', 'expectedVersion': 1,
                         'comment': content}),
        ]
        for command, arguments in cases:
            with self.subTest(command=command):
                payload = {'version': 1, 'operationId': 'editor-' + command,
                           'command': command, 'arguments': arguments}
                self.assertGreater(len(json.dumps(payload, ensure_ascii=False).encode('utf-8')), 4096)
                status, first = self.post(payload)
                self.assertEqual(status, 200)
                self.assertEqual(first['state'], 'pending')
                self.assertEqual(first['request']['arguments'], arguments)
                status, retry = self.post(payload)
                self.assertEqual(status, 200)
                self.assertEqual(retry, first)
        restarted = TaskSync(self.store.directory).snapshot()
        self.assertEqual(set(restarted['outbox']), {'editor-create', 'editor-patch', 'editor-comment'})
        for command, arguments in cases:
            self.assertEqual(restarted['outbox']['editor-' + command]['request']['arguments'], arguments)

    def test_long_editor_request_still_requires_csrf_and_respects_64k_envelope(self):
        payload = {'version': 1, 'operationId': 'editor-denied', 'command': 'create',
                   'arguments': {'title': 'Synthetic task', 'content': '\u042f' * 2100}}
        self.assertEqual(self.post(payload, csrf=False)[0], 403)
        payload['arguments']['content'] = '\u042f' * 40000
        self.assertEqual(self.post(payload)[0], 413)
        self.assertEqual(self.store.task_sync.snapshot()['outbox'], {})


if __name__ == '__main__':
    unittest.main()
