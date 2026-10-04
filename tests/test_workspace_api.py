from owner_client import authorize, owner_urlopen
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

import catalog_directory
import provider_catalogs
import server as server_module
from server import Server, Store


SKILL = """---
name: demo-skill
description: Synthetic workspace skill.
---

# Demo

Keep this inert.
"""


def json_request(url, *, method="GET", body=None, headers=None):
    payload = None if body is None else json.dumps(body).encode("utf-8")
    request = Request(url, data=payload, method=method, headers=headers or {})
    try:
        with owner_urlopen(request, timeout=3) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


class WorkspaceApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.skills = base / "skills"
        (self.skills / "demo-skill").mkdir(parents=True)
        (self.skills / "demo-skill" / "SKILL.md").write_bytes(SKILL.encode("utf-8"))
        self.store = Store(base / "data", skills_root=self.skills, executable=False)
        self.patches = [
            patch.object(server_module.access, "key_available", return_value=False),
            patch.object(server_module.credentials, "info", return_value={"available": False, "source": "none", "removable": False, "canSave": False}),
            patch.object(server_module.credentials, "revision", return_value=""),
        ]
        for item in self.patches:
            item.start()
        self.http = Server(("127.0.0.1", 0), self.store)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        authorize(self.http)
        self.base_url = f"http://127.0.0.1:{self.http.server_port}"

    def tearDown(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join(timeout=2)
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def _write(self, action, payload, token=True):
        headers = {"Host": f"127.0.0.1:{self.http.server_port}", "X-Agent-City": "1", "Content-Type": "application/json"}
        if token:
            headers["X-Agent-City-Token"] = self.store.csrf_token
        return json_request(self.base_url + "/api/skills/" + action, method="POST", body=payload, headers=headers)

    def test_skills_http_read_preview_save_history_and_stale_revision(self):
        status, body = json_request(self.base_url + "/api/skills?q=demo")
        self.assertEqual(200, status)
        self.assertEqual("demo-skill", body["skills"][0]["slug"])
        status, document = json_request(self.base_url + "/api/skills?slug=demo-skill")
        self.assertEqual(200, status)
        revision = document["revision"]
        changed = SKILL.replace("Keep this inert.", "Stay inert.")
        status, preview = self._write("preview", {"slug": "demo-skill", "content": changed, "revision": revision})
        self.assertEqual(200, status)
        self.assertIn("Stay inert.", preview["diff"])
        status, saved = self._write("save", {"slug": "demo-skill", "content": changed, "revision": revision})
        self.assertEqual(200, status)
        self.assertEqual(revision, saved["history"][0]["revision"])
        status, stale = self._write("save", {"slug": "demo-skill", "content": SKILL, "revision": revision})
        self.assertEqual(409, status)
        self.assertIn("изменён", stale["error"])

    def test_skill_write_requires_csrf(self):
        document = self.store.skills.read("demo-skill")
        status, body = self._write("save", {"slug": "demo-skill", "content": SKILL, "revision": document["revision"]}, token=False)
        self.assertEqual(403, status)
        self.assertIn("окно", body["error"])

    def test_v1_contract_has_no_csrf_credentials_or_reply_bodies(self):
        def walk(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    self.assertNotIn(key, {"csrfToken", "credentials", "reply"})
                    yield from walk(item)
            elif isinstance(value, list):
                for item in value:
                    yield from walk(item)

        for resource in ("manifest", "models", "providers", "skills", "directory"):
            status, body = json_request(self.base_url + "/api/v1/" + resource)
            self.assertEqual(200, status, resource)
            list(walk(body))
        status, body = json_request(self.base_url + '/api/v1/skills?slug=demo-skill')
        self.assertEqual(status, 200)
        self.assertEqual(body['skill']['content'], SKILL)
        self.assertNotIn('history', body['skill'])
        status, _ = json_request(self.base_url + '/api/v1/skills?slug=..%2Fother')
        self.assertEqual(status, 400)

    def test_registry_ignores_unsafe_docs_urls(self):
        payload = {
            "safe": {"name": "Safe", "doc": "https://example.com/docs", "models": {}},
            "http": {"name": "HTTP", "doc": "http://example.com", "models": {}},
            "userinfo": {"name": "Userinfo", "doc": "https://user:pass@example.com", "models": {}},
        }
        result = catalog_directory.normalize(payload)
        self.assertEqual(["http", "safe", "userinfo"], [item["id"] for item in result["providers"]])
        self.assertEqual("", next(item["docs"] for item in result["providers"] if item["id"] == "http"))
        self.assertEqual("", next(item["docs"] for item in result["providers"] if item["id"] == "userinfo"))

    def test_huggingface_upstreams_are_discovery_only(self):
        result = provider_catalogs.normalize("huggingface", {"data": [{
            "id": "Qwen/Qwen3-8B", "providers": [{"provider": "hf-inference", "status": "live", "context_length": 32768, "supports_tools": True}],
        }]})
        self.assertEqual(1, len(result["models"]))
        model = result["models"][0]
        self.assertEqual("hf-inference", model["upstreams"][0]["name"])
        self.assertFalse(model["priceVerified"])
        self.assertNotIn("free", json.dumps(model, ensure_ascii=False).lower())


if __name__ == "__main__":
    unittest.main()
