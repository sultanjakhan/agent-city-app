from owner_client import authorize, owner_urlopen
import json
from pathlib import Path
import tempfile
import threading
import unittest
import subprocess
import sys
from urllib.parse import urlencode
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import server as server_module
from server import Server, Store


SKILL = "---\nname: demo\ndescription: Demo\n---\n\nbody\n"


def request(url, *, method="GET", body=None, headers=None):
    data = None if body is None else json.dumps(body).encode()
    req = Request(url, data=data, method=method, headers=headers or {})
    try:
        with owner_urlopen(req, timeout=3) as response:
            return response.status, json.loads(response.read().decode())
    except HTTPError as exc:
        return exc.code, json.loads(exc.read().decode())


class ManagementHttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.skills = root / "skills" / "demo"
        self.skills.mkdir(parents=True)
        (self.skills / "SKILL.md").write_text(SKILL, encoding="utf-8")
        self.codex_home = root / "codex-home"
        self.codex_skills = self.codex_home / "skills" / "demo"
        self.codex_skills.mkdir(parents=True)
        (self.codex_skills / "SKILL.md").write_text(SKILL, encoding="utf-8")
        self.system_skill = self.codex_home / "skills" / ".system"
        self.system_skill.mkdir(parents=True)
        (self.system_skill / "SKILL.md").write_text(SKILL.replace("demo", "sys"), encoding="utf-8")
        repos = root / 'repos'
        self.repo = repos / 'demo-repo'
        (self.repo / '.git').mkdir(parents=True)
        (self.repo / '.git' / 'HEAD').write_text('ref: refs/heads/main\n')
        (self.repo / 'AGENTS.md').write_text('Keep original instructions.\n')
        self.store = Store(root / "data", skills_root=root / "skills", executable=False,
                           inventory_roots=[("codex", self.codex_home / "skills")], codex_home=self.codex_home, repo_roots=[repos])
        self.http = Server(("127.0.0.1", 0), self.store)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        authorize(self.http)
        self.base = f"http://127.0.0.1:{self.http.server_port}"

    def tearDown(self):
        self.http.shutdown(); self.http.server_close(); self.thread.join(timeout=2); self.temp.cleanup()

    def _post(self, path, body, csrf=True):
        headers = {"Host": f"127.0.0.1:{self.http.server_port}", "X-Agent-City": "1", "Content-Type": "application/json"}
        if csrf: headers["X-Agent-City-Token"] = self.store.csrf_token
        return request(self.base + path, method="POST", body=body, headers=headers)

    def test_codex_toggle_and_bridge_require_csrf_and_revision(self):
        status, controls = request(self.base + "/api/codex-controls")
        self.assertEqual(200, status)
        skill = controls["config"]["skills"][0]
        status, body = self._post("/api/codex-controls/skill", {"id": skill["id"], "enabled": False, "revision": controls["config"]["revision"]}, csrf=False)
        self.assertEqual(403, status)
        status, body = self._post("/api/codex-controls/skill", {"id": skill["id"], "enabled": False, "revision": controls["config"]["revision"]})
        self.assertEqual(200, status)
        status, readback = request(self.base + "/api/codex-controls")
        self.assertEqual("disabled", readback["config"]["skills"][0]["status"])
        stale, _ = self._post("/api/codex-controls/skill", {"id": skill["id"], "enabled": True, "revision": controls["config"]["revision"]})
        self.assertEqual(409, stale)
        status, enabled = self._post("/api/codex-controls/skill", {"id": skill["id"], "enabled": True, "revision": readback["config"]["revision"]})
        self.assertEqual(200, status)
        status, controls = request(self.base + "/api/codex-controls")
        status, _ = self._post('/api/codex-controls/connect', {'revision': controls['bridge']['revision']}, csrf=False)
        self.assertEqual(403, status)
        self.assertFalse((self.codex_home / 'AGENTS.md').exists())
        status, bridge = self._post("/api/codex-controls/connect", {"revision": controls["bridge"]["revision"]})
        self.assertEqual(200, status)
        self.assertIn("revision", bridge)

    def test_system_skill_is_not_toggleable_and_unauthorized_cli_cannot_report_use(self):
        status, controls = request(self.base + "/api/codex-controls")
        self.assertEqual(1, len(controls["config"]["skills"]))
        status, inventory = request(self.base + "/api/skill-inventory")
        self.assertEqual(200, status)
        system = next(item for item in inventory["skills"] if "/.system/" in item["path"].replace("\\", "/"))
        rejected, _ = self._post("/api/codex-controls/skill", {"id": system["id"], "enabled": False, "revision": controls["config"]["revision"]})
        self.assertEqual(400, rejected)
        ident = inventory["skills"][0]["id"]
        cmd = [sys.executable, "city.py", "report-use", "--port", str(self.http.server_port), "--id", ident, "--event-id", "cli-event"]
        first = subprocess.run(cmd, cwd=Path(__file__).parents[1], capture_output=True, text=True, timeout=10)
        second = subprocess.run(cmd, cwd=Path(__file__).parents[1], capture_output=True, text=True, timeout=10)
        self.assertEqual(1, first.returncode)
        self.assertIn("owner session", first.stderr)
        self.assertEqual(1, second.returncode)
        status, snapshot = request(self.base + "/api/skill-inventory")
        self.assertEqual(0, snapshot["skills"][0]["activity"].get("reportedUses",0))

    def test_rules_context_uses_cwd_and_revision(self):
        status, body = request(self.base + '/api/v1/context?' + urlencode({'cwd': str(self.repo / 'src')}))
        self.assertEqual(200, status)
        repo_id = body['repository']['id']
        self.assertEqual('demo-repo', body['repository']['name'])
        for scope in ['global', repo_id]:
            _, rules = request(self.base + '/api/v1/rules?' + urlencode({'scope': scope}))
            payload = {'scope': scope, 'content': 'rules for ' + scope, 'revision': rules['revision']}
            self.assertEqual(403, self._post('/api/rules/save', payload, csrf=False)[0])
            self.assertEqual(200, self._post('/api/rules/preview', payload)[0])
            self.assertEqual(200, self._post('/api/rules/save', payload)[0])
            self.assertEqual(409, self._post('/api/rules/save', payload)[0])
        _, profile = request(self.base + '/api/repositories?id=' + repo_id)
        extension_id = self.store.projects.list()[0]['id']
        payload = {'repoId': repo_id, 'extensionIds': [extension_id], 'revision': profile['profile']['revision']}
        self.assertEqual(200, self._post('/api/repositories/profile', payload)[0])
        _, context = request(self.base + '/api/v1/context?' + urlencode({'cwd': str(self.repo)}))
        self.assertEqual(['global', repo_id], [r['scope'] for r in context['rules']])
        self.assertEqual([extension_id], [e['id'] for e in context['extensions']])
        _, outside = request(self.base + '/api/v1/context?' + urlencode({'cwd': str(self.repo) + '-elsewhere'}))
        self.assertIsNone(outside['repository'])
        self.assertEqual('Keep original instructions.\n', (self.repo / 'AGENTS.md').read_text())

    def test_activity_is_separate_and_invalid_id_rejected(self):
        status, body = request(self.base + "/api/skill-inventory")
        self.assertEqual(200, status)
        self.assertEqual({}, body["skills"][0]["activity"])
        status, body = self._post("/api/skill-activity", {"id": "missing", "kind": "used", "eventId": "e1"})
        self.assertEqual(400, status)
        status, body = request(self.base + "/api/skill-inventory?id=missing")
        self.assertEqual(400, status)


if __name__ == "__main__":
    unittest.main()
