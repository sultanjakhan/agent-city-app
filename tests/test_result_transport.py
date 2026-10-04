import json
import os
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from urllib.request import build_opener, ProxyHandler
from urllib.error import HTTPError

from task_connection import default_config
import server
from tools.task_gateway import Gateway, server_for


class QueueBridge:
    def __init__(self):
        self.calls = []

    def call(self, request):
        self.calls.append(request)
        if request["method"] == "GET":
            return {"config": {"sourceNamespace": "00000000-0000-4000-8000-000000000001"}, "tasks": {}, "lastSuccess": None, "outbox": {}}
        return {"state": "pending", "operationId": request["body"]["operationId"], "request": request["body"]}


def cfg():
    return {**default_config(), "sourceNamespace": "00000000-0000-4000-8000-000000000001", "taskIds": None,
            "scopes": ["tasks:read", "tasks:write", "tasks:execute"], "profile": "", "client": ""}


class ResultTransportTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"TEST_RESULT_TRANSPORT_TOKEN": "t" * 48})
        self.env.start(); self.addCleanup(self.env.stop)
        self.bridge = QueueBridge()
        self.gateway = Gateway("agent-city", cfg(), [{
            "tokenEnv": "TEST_RESULT_TRANSPORT_TOKEN", "scopes": ["tasks:read", "tasks:write", "tasks:execute"],
            "taskIds": None, "sourceNamespace": "00000000-0000-4000-8000-000000000001",
        }], self.bridge)
        self.http = server_for(self.gateway)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.http.shutdown(); self.http.server_close(); self.thread.join()

    def post(self, value, token="t" * 48):
        raw = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
        request = Request(f"http://127.0.0.1:{self.http.server_port}/commands", data=raw,
                         method="POST", headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"})
        try:
            with urlopen(request, timeout=3) as response:
                return response.status, json.loads(response.read())
        except HTTPError as error:
            return error.code, json.loads(error.read())

    def test_long_russian_result_reaches_existing_queue_unchanged(self):
        content = "Результат проверки. " * 500  # >4 KiB, comfortably below 64 KiB.
        value = {"version": 1, "operationId": "result-long-001", "command": "submit_result",
                 "arguments": {"taskId": "task-001", "expectedVersion": 1, "runId": "run-001", "content": content}}
        status, response = self.post(value)
        self.assertEqual(status, 200)
        self.assertEqual(response["request"], value)
        self.assertEqual(self.bridge.calls[-1]["body"], value)

    def test_unauthorized_and_oversized_are_rejected_before_bridge(self):
        value = {"version": 1, "operationId": "result-auth-001", "command": "submit_result", "arguments": {"content": "x"}}
        self.assertEqual(self.post(value, "wrong")[0], 401)
        before = len(self.bridge.calls)
        oversized = {**value, "arguments": {"content": "Ж" * 40000}}
        self.assertEqual(self.post(oversized, "wrong")[0], 401)
        self.assertEqual(self.post(oversized)[0], 413)
        self.assertEqual(len(self.bridge.calls), before)

    def test_malformed_request_is_rejected_before_dispatch(self):
        request = Request(f"http://127.0.0.1:{self.http.server_port}/commands", data=b"{bad",
                         method="POST", headers={"Content-Type": "application/json", "Authorization": "Bearer " + "t" * 48})
        with self.assertRaises(HTTPError) as error:
            urlopen(request, timeout=3)
        self.assertEqual(error.exception.code, 400)
        self.assertEqual(len(self.bridge.calls), 0)


class NativeQueueHttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = __import__('tempfile').TemporaryDirectory()
        root = __import__('pathlib').Path(self.temp.name)
        (root / 'skills').mkdir(); (root / 'repos').mkdir()
        self.store = server.Store(root / 'panel', skills_root=root / 'skills', codex_home=root / 'codex',
                                  repo_roots=[root / 'repos'], local_only=True, executable=False)
        namespace = '00000000-0000-4000-8000-000000000002'
        config = {**default_config(), 'enabled': False, 'transport': 'pipe', 'endpoint': '',
                  'profile': str(root / 'cicada.db'), 'client': str(root / 'fixture-client'),
                  'tokenEnv': '',
                  'sourceNamespace': namespace, 'scopes': ['tasks:read', 'tasks:execute']}
        self.store.task_sync.configure(config, 0)
        self.http = server.Server(('127.0.0.1', 0), self.store)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True); self.thread.start()
        self.addCleanup(self.stop)
        self.owner = self.http.owner_host + ':' + str(self.http.server_port)
        self.base = 'http://127.0.0.1:' + str(self.http.server_port)
        status, _, headers = self.request('/api/owner-bootstrap', {'capability': self.http.owner_sessions.issue_bootstrap()},
            {'Host': self.owner, 'Origin': 'http://' + self.owner, 'X-Agent-City': '1', 'Content-Type': 'application/json'})
        self.assertEqual(status, 200); self.cookie = headers['Set-Cookie'].split(';', 1)[0]

    def stop(self):
        self.http.shutdown(); self.http.server_close(); self.thread.join(3); self.temp.cleanup()

    def request(self, path, value, headers=None):
        raw = json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode()
        request = Request(self.base + path, data=raw, method='POST', headers=headers or {})
        try:
            with build_opener(ProxyHandler({})).open(request, timeout=3) as response:
                return response.status, json.loads(response.read()), response.headers
        except HTTPError as error:
            return error.code, json.loads(error.read()), error.headers

    def task_headers(self, csrf=True):
        result = {'Host': self.owner, 'Cookie': self.cookie, 'X-Agent-City': '1', 'Content-Type': 'application/json'}
        if csrf: result['X-Agent-City-Token'] = self.store.csrf_token
        return result

    def test_real_queue_accepts_8000_utf8_bytes_and_reuses_operation(self):
        content = 'Ж' * 4000
        value = {'version': 1, 'operationId': 'native-long-001', 'command': 'submit_result',
                 'arguments': {'taskId': 'task-001', 'expectedVersion': 1, 'runId': 'run-001', 'content': content}}
        status, item, _ = self.request('/api/task-sync/queue', value, self.task_headers())
        self.assertEqual(status, 200); self.assertEqual(item['request']['arguments']['content'], content)
        status, retry, _ = self.request('/api/task-sync/queue', value, self.task_headers())
        self.assertEqual(status, 200); self.assertEqual(retry, item)
        self.assertEqual(len(self.store.task_sync.snapshot()['outbox']), 1)

    def test_real_queue_auth_and_limits_preserve_old_routes(self):
        value = {'version': 1, 'operationId': 'native-over-001', 'command': 'submit_result',
                 'arguments': {'content': 'Ж' * 40000}}
        small = {**value, 'arguments': {'content': 'draft'}}
        self.assertEqual(self.request('/api/task-sync/queue', small, self.task_headers(False))[0], 403)
        no_session = self.task_headers(); no_session.pop('Cookie')
        self.assertEqual(self.request('/api/task-sync/queue', value, no_session)[0], 401)
        self.assertEqual(self.request('/api/task-sync/queue', value, self.task_headers())[0], 413)
        self.assertEqual(len(self.store.task_sync.snapshot()['outbox']), 0)
        favorite = {'id': 'x', 'enabled': True, 'padding': 'x' * 5000}
        self.assertEqual(self.request('/api/favorite', favorite, self.task_headers())[0], 413)


if __name__ == "__main__":
    unittest.main()
