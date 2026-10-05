"""Synthetic owner checks for release 0.6.0 standards and local host APIs."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, build_opener, ProxyHandler

from owner_client import authorize, owner_urlopen
from server import Server, Store


class ReleaseHttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        skills = self.root / "skills"
        skills.mkdir()
        self.repo = self.root / "repos" / "synthetic-project"
        (self.repo / ".git").mkdir(parents=True)
        (self.repo / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="ascii")
        (self.repo / "AGENTS.md").write_text("Keep original project instructions.\n", encoding="utf-8")
        self.store = Store(self.root / "data", skills_root=skills, executable=False,
                           codex_home=self.root / "codex-home", repo_roots=[self.root / "repos"])
        self.http = Server(("127.0.0.1", 0), self.store)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        authorize(self.http)
        self.base = "http://127.0.0.1:" + str(self.http.server_port)
        status, value = self._request("/api/repositories")
        self.assertEqual(status, 200)
        self.repo_id = value["repositories"][0]["id"]

    def tearDown(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join(timeout=2)
        self.temp.cleanup()

    def _request(self, path, body=None, *, owner=True, csrf=True):
        headers = {"Host": self.http.owner_host + ":" + str(self.http.server_port)}
        if body is not None:
            headers.update({"X-Agent-City": "1", "Content-Type": "application/json"})
            if csrf:
                headers["X-Agent-City-Token"] = self.store.csrf_token if csrf is True else str(csrf)
        req = Request(self.base + path, data=json.dumps(body).encode("utf-8") if body is not None else None, headers=headers)
        opener = owner_urlopen if owner else build_opener(ProxyHandler({})).open
        try:
            with opener(req, timeout=3) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            with error:
                return error.code, json.loads(error.read().decode("utf-8"))

    def _assignment_path(self):
        return "/api/standards/assignments?" + urlencode({"repoId": self.repo_id})

    def _payload(self, revision, **changes):
        return {"repoId": self.repo_id, "id": "qa-evidence", "version": "0.1.0", "revision": revision, **changes}

    def _standards_files(self):
        return {path.name: path.read_bytes() if path.exists() else None for path in (self.store.standards.path, self.store.standards.catalog_path)}

    def test_owner_boundary_covers_all_new_reads_and_apply(self):
        paths = ["/api/standards", "/api/standards/detail?id=qa-evidence&version=0.1.0", self._assignment_path(), "/api/hardware", "/api/storage-map"]
        before = self._standards_files()
        for path in paths:
            with self.subTest(path=path):
                status, result = self._request(path, owner=False)
                self.assertEqual(status, 401)
                self.assertEqual(result, {"error": "owner_session_required"})
        status, _ = self._request("/api/standards/apply", self._payload("unknown"), owner=False)
        self.assertEqual(status, 401)
        self.assertEqual(self._standards_files(), before)

    def test_apply_preserves_original_and_exposes_exact_version_in_context(self):
        status, catalog = self._request("/api/standards")
        self.assertEqual(status, 200)
        self.assertFalse(catalog["runtimeEnforced"])
        self.assertEqual(next(item for item in catalog["standards"] if item["id"] == "neutral-interface-draft")["status"], "draft")
        _, original = self._request("/api/standards/detail?id=qa-evidence&version=0.1.0")
        _, initial = self._request(self._assignment_path())
        self.assertEqual(initial["standardRefs"], [])
        before = self._standards_files()
        for csrf in (False, "incorrect-token"):
            self.assertEqual(self._request("/api/standards/apply", self._payload(initial["revision"]), csrf=csrf)[0], 403)
            self.assertEqual(self._standards_files(), before)
        status, saved = self._request("/api/standards/apply", self._payload(initial["revision"]))
        self.assertEqual(status, 200)
        self.assertEqual(saved["standardRefs"], [{"id": "qa-evidence", "version": "0.1.0"}])
        self.assertFalse(saved["runtimeEnforced"])
        self.assertEqual(self._request(self._assignment_path()), (200, saved))
        self.assertEqual(self._request("/api/standards/detail?id=qa-evidence&version=0.1.0"), (200, original))
        status, context = self._request("/api/v1/context?" + urlencode({"cwd": str(self.repo / "src")}))
        self.assertEqual(status, 200)
        self.assertEqual(context["standards"], [original])
        self.assertEqual(context["standards"][0]["rules"], original["rules"])
        self.assertFalse(context["standards"][0]["runtimeEnforced"])
        _, outside = self._request("/api/v1/context?" + urlencode({"cwd": str(self.root / "outside")}))
        self.assertEqual(outside["standards"], [])
        raw = json.loads(self.store.standards.path.read_text(encoding="utf-8"))
        self.assertEqual(raw["assignments"][self.repo_id], saved["standardRefs"])
        self.assertEqual((self.repo / "AGENTS.md").read_text(encoding="utf-8"), "Keep original project instructions.\n")
        self.assertEqual(sorted(path.name for path in self.repo.iterdir()), [".git", "AGENTS.md"])

    def test_conflict_and_idempotence_keep_saved_reference(self):
        _, initial = self._request(self._assignment_path())
        _, saved = self._request("/api/standards/apply", self._payload(initial["revision"]))
        before = self._standards_files()
        status, duplicate = self._request("/api/standards/apply", self._payload(saved["revision"]))
        self.assertEqual((status, duplicate), (200, saved))
        self.assertEqual(self._standards_files(), before)
        status, _ = self._request("/api/standards/apply", self._payload(initial["revision"], id="frontend-states"))
        self.assertEqual(status, 409)
        self.assertEqual(self._standards_files(), before)
        self.assertEqual(self._request(self._assignment_path()), (200, saved))

    def test_invalid_requests_do_not_write_standards(self):
        _, initial = self._request(self._assignment_path())
        valid = self._payload(initial["revision"])
        before = self._standards_files()
        for payload in [
            {**valid, "version": "latest"},
            {**valid, "version": "0.2.0"},
            {**valid, "id": "missing"},
            {**valid, "repoId": str(self.repo)},
            {**valid, "repoId": "repo-" + "0" * 24},
            {**valid, "rules": ["Client cannot replace an original"]},
            {key: value for key, value in valid.items() if key != "revision"},
        ]:
            with self.subTest(payload=payload):
                self.assertEqual(self._request("/api/standards/apply", payload)[0], 400)
                self.assertEqual(self._standards_files(), before)
        for path in ["/api/standards/detail?id=qa-evidence", "/api/standards/detail?id=qa-evidence&version=latest", "/api/standards/assignments?repoId=missing"]:
            self.assertEqual(self._request(path)[0], 400)
        self.assertEqual(self._standards_files(), before)

    def test_local_hardware_facts_and_storage_locations_are_owner_visible(self):
        status, hardware = self._request("/api/hardware")
        self.assertEqual(status, 200)
        self.assertEqual(hardware["schemaVersion"], 1)
        self.assertTrue(hardware["observedAt"])
        self.assertIsInstance(hardware["system"], str)
        self.assertIsInstance(hardware["architecture"], str)
        self.assertGreater(hardware["dataDisk"]["totalBytes"], 0)
        self.assertGreaterEqual(hardware["dataDisk"]["freeBytes"], 0)
        status, storage = self._request("/api/storage-map")
        self.assertEqual(status, 200)
        self.assertEqual(storage["dataDirectory"], str(self.store.directory))
        locations = {item["name"]: item for item in storage["locations"]}
        self.assertEqual(locations["Standards"]["path"], str(self.store.standards.catalog_path))
        self.assertEqual(locations["Project standards"]["path"], str(self.store.standards.path))
        self.assertFalse(locations["Project standards"]["exists"])
        self.assertTrue(all(set(item) <= {"name", "owner", "path", "exists", "sourceId"} for item in storage["locations"]))


if __name__ == "__main__":
    unittest.main()
