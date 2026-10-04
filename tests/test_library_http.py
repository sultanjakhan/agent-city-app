from owner_client import authorize, owner_urlopen
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

import server as server_module
from server import Server, Store


SKILL = """---
name: Fixture skill
description: Read-only fixture.
---

Do not execute.
"""


def request_json(url, *, method="GET", payload=None, headers=None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(url, data=data, method=method, headers=headers or {})
    try:
        with owner_urlopen(request, timeout=3) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


class LibraryHttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.skills = base / "skills"
        (self.skills / "fixture").mkdir(parents=True)
        (self.skills / "fixture" / "SKILL.md").write_bytes(SKILL.encode("utf-8"))
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
        self.base = f"http://127.0.0.1:{self.http.server_port}"
        self.write_headers = {"X-Agent-City": "1", "Content-Type": "application/json", "X-Agent-City-Token": self.store.csrf_token}

    def tearDown(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join(timeout=2)
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def test_pipeline_preview_uses_saved_repository_policy_and_rejects_simulation(self):
        from test_pipeline_store import fixture
        repo_id = "repo-" + "a" * 24
        pipeline = fixture(); pipeline["projectId"] = repo_id
        policy = {"schemaVersion": 1, "sourceIds": ["docs"],
                  "allowedActions": ["read", "write"], "deniedActions": ["write"]}
        with patch.object(self.store.repos, "read", return_value={"id": repo_id}):
            current = self.store.repo_profiles.read(repo_id)
            self.store.repo_profiles.save(repo_id, [], current["revision"], policy)
            before = self.store.repo_profiles.path.read_bytes()
            payload = {"pipeline": pipeline,
                       "pipelineRestrictions": {"sourceIds": ["docs", "extra"], "allowedActions": ["read", "publish"]},
                       "stageRestrictions": {"work": {"allowedActions": []}}}
            status, body = request_json(self.base + "/api/pipelines/preview", method="POST", payload=payload, headers=self.write_headers)
            self.assertEqual(200, status)
            self.assertEqual("repository-profiles.json", body["projectPolicySource"])
            self.assertEqual("unknown", body["projectBudgetSupport"])
            self.assertEqual(["read"], body["projectPolicy"]["pipeline"]["allowedActions"])
            self.assertEqual([], body["projectPolicy"]["stages"]["work"]["allowedActions"])
            self.assertTrue(body["conflicts"]); self.assertFalse(body["canRun"])
            self.assertEqual(before, self.store.repo_profiles.path.read_bytes())
            status, _ = request_json(self.base + "/api/pipelines/preview", method="POST", payload={"pipeline": pipeline, "projectPolicy": policy}, headers=self.write_headers)
            self.assertEqual(400, status)
            self.assertFalse(self.store.pipelines.path.exists())

    def test_policy_preview_reports_expansion_without_mutation(self):
        before = self.store.projects.snapshot()
        payload = {"policy": {"schemaVersion": 1, "sourceIds": ["docs"], "allowedActions": ["read"]}, "pipeline": {"allowedActions": ["publish"], "sourceIds": ["private"]}}
        status, body = request_json(self.base + "/api/projects/policy/preview", method="POST", payload=payload, headers=self.write_headers)
        self.assertEqual(status, 200)
        self.assertEqual(body["allowedActions"], [])
        self.assertEqual(body["sourceIds"], [])
        self.assertEqual(len(body["conflicts"]), 2)
        self.assertFalse(body["runtimeEnforced"])
        self.assertEqual(self.store.projects.snapshot(), before)
        payload["policy"]["credentials"] = "not-accepted"
        status, _ = request_json(self.base + "/api/projects/policy/preview", method="POST", payload=payload, headers=self.write_headers)
        self.assertEqual(status, 400)

    def test_inventory_list_read_opaque_id_and_no_save_route(self):
        status, listed = request_json(self.base + "/api/skill-inventory")
        self.assertEqual(200, status)
        self.assertEqual(["fixture"], [item["slug"] for item in listed["skills"]])
        skill = listed["skills"][0]
        self.assertFalse(skill["editable"])
        self.assertNotEqual(str(self.skills / "fixture" / "SKILL.md"), skill["id"])
        status, document = request_json(self.base + "/api/skill-inventory?id=" + skill["id"])
        self.assertEqual(200, status)
        self.assertEqual(SKILL, document["content"])
        before = (self.skills / "fixture" / "SKILL.md").read_bytes()
        status, _ = request_json(self.base + "/api/skill-inventory", method="POST", payload={}, headers=self.write_headers)
        self.assertEqual(404, status)
        self.assertEqual(before, (self.skills / "fixture" / "SKILL.md").read_bytes())

    def test_inventory_rejects_foreign_opaque_id(self):
        status, body = request_json(self.base + "/api/skill-inventory?id=skill-not-enumerated")
        self.assertEqual(400, status)
        self.assertIn("skill", body["error"])

    def test_projects_read_and_v1_read_need_no_csrf(self):
        for path in ("/api/projects", "/api/v1/projects"):
            status, body = request_json(self.base + path)
            self.assertEqual(200, status)
            self.assertIn("projects", body)
            self.assertIn("revision", body)

    def test_project_save_requires_csrf_and_persists_user_file_only(self):
        seed = self.store.projects.seed_path
        seed_before = seed.read_bytes() if seed and seed.exists() else None
        status, initial = request_json(self.base + "/api/projects")
        record = {"id": "fixture-project", "name": "Fixture Project",
                  "description": {"ru": "Тестовый проект", "en": "Fixture project"},
                  "useCases": [{"ru": "Проверка", "en": "Verification"}], "category": "other",
                  "repoUrl": "https://github.com/example/fixture", "docsUrl": "https://example.com/fixture", "status": "candidate"}
        payload = {"project": record, "revision": initial["revision"]}
        status, _ = request_json(self.base + "/api/projects/save", method="POST", payload=payload,
                                 headers={"X-Agent-City": "1", "Content-Type": "application/json"})
        self.assertEqual(403, status)
        self.assertFalse((self.store.projects.path).exists())
        status, saved = request_json(self.base + "/api/projects/save", method="POST", payload=payload, headers=self.write_headers)
        self.assertEqual(200, status)
        self.assertTrue((self.store.projects.path).exists())
        self.assertIn(record["id"], {item["id"] for item in saved["projects"]})
        status, stale = request_json(self.base + "/api/projects/save", method="POST", payload=payload, headers=self.write_headers)
        self.assertEqual(409, status)
        if seed_before is not None:
            self.assertEqual(seed_before, seed.read_bytes())

    def test_batch_check_requires_csrf(self):
        status, body = request_json(self.base + "/api/check-pending", method="POST",
                                    payload={}, headers={"X-Agent-City": "1", "Content-Type": "application/json"})
        self.assertEqual(403, status)
        self.assertIn("окно", body["error"])


if __name__ == "__main__":
    unittest.main()
