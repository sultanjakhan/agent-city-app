import copy
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from repo_inventory import RepoInventory
from rule_store import RuleValidationError
from standards_store import (
    StandardsStore, StandardsValidationError, StandardsRevisionConflict,
    _INITIAL_STANDARDS, _original,
)


class StandardsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "workspace"
        self.root.mkdir()
        for name in ("alpha", "beta"):
            repo = self.root / name
            (repo / ".git").mkdir(parents=True)
            (repo / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="ascii")
        self.inventory = RepoInventory([self.root])
        self.repos = self.inventory.list()
        self.repo_id = self.repos[0]["id"]
        self.data = Path(self.temp.name) / "data"
        self.store = StandardsStore(self.data, self.inventory)

    def tearDown(self):
        self.temp.cleanup()

    def test_catalog_matches_proposal_and_starts_unassigned(self):
        snapshot = self.store.snapshot()
        self.assertEqual(len(snapshot["standards"]), 3)
        draft = self.store.detail("neutral-interface-draft", "0.1.0-draft")
        self.assertEqual(draft["status"], "draft")
        self.assertEqual(draft["provenance"]["kind"], "prototype-proposal")
        self.assertIn("Точную геометрию и применение к проектам выбирает пользователь.", draft["rules"])
        self.assertEqual(self.store.detail("qa-evidence", "0.1.0")["status"], "template")
        self.assertFalse(draft["runtimeEnforced"])
        self.assertEqual(self.store.assignments(self.repo_id)["standardRefs"], [])
        self.assertFalse(self.store.path.exists())

    def test_exact_reference_persists_without_copying_rules_into_project(self):
        original = self.store.detail("qa-evidence", "0.1.0")
        saved = self.store.apply(self.repo_id, "qa-evidence", "0.1.0", self.store.assignments(self.repo_id)["revision"])
        self.assertEqual(saved["standardRefs"], [{"id": "qa-evidence", "version": "0.1.0"}])
        self.assertFalse(saved["runtimeEnforced"])
        raw = json.loads(self.store.path.read_text(encoding="utf-8"))
        self.assertEqual(raw["assignments"][self.repo_id], saved["standardRefs"])
        reopened = StandardsStore(self.data, self.inventory)
        self.assertEqual(reopened.assignments(self.repo_id), saved)
        self.assertEqual(reopened.detail("qa-evidence", "0.1.0"), original)
        self.assertTrue(self.store.catalog_path.is_file())
        for repo in self.repos:
            self.assertEqual(sorted(path.name for path in Path(repo["path"]).iterdir()), [".git"])
        self.assertFalse((self.data / "repository-profiles.json").exists())

    def test_detached_results_and_idempotent_assignment(self):
        detail = self.store.detail("qa-evidence", "0.1.0")
        detail["rules"].clear()
        self.assertTrue(self.store.detail("qa-evidence", "0.1.0")["rules"])
        saved = self.store.apply(self.repo_id, "qa-evidence", "0.1.0", self.store.assignments(self.repo_id)["revision"])
        self.assertEqual(self.store.apply(self.repo_id, "qa-evidence", "0.1.0", saved["revision"]), saved)
        saved["standardRefs"].clear()
        self.assertEqual(len(self.store.assignments(self.repo_id)["standardRefs"]), 1)

    def test_new_bundled_version_preserves_pinned_original(self):
        saved = self.store.apply(self.repo_id, "qa-evidence", "0.1.0", self.store.assignments(self.repo_id)["revision"])
        old = self.store.detail("qa-evidence", "0.1.0")
        body = {key: copy.deepcopy(value) for key, value in _INITIAL_STANDARDS[1].items() if key not in {"provenance", "originalHash"}}
        changed_same_version = _original(**{**body, "description": "Changed bundled description"})
        new_version = _original(**{**body, "version": "0.2.0", "description": "New version"})
        with patch("standards_store._INITIAL_STANDARDS", (changed_same_version, new_version)):
            reopened = StandardsStore(self.data, self.inventory)
            self.assertEqual(reopened.detail("qa-evidence", "0.1.0"), old)
            self.assertEqual(reopened.assignments(self.repo_id)["standardRefs"], saved["standardRefs"])
            updated = reopened.apply(self.repo_id, "qa-evidence", "0.2.0", saved["revision"])
            self.assertEqual(updated["standardRefs"], [{"id": "qa-evidence", "version": "0.2.0"}])
            self.assertEqual(reopened.detail("qa-evidence", "0.1.0"), old)

    def test_revision_conflict_cannot_overwrite_another_repository(self):
        initial = self.store.assignments(self.repo_id)["revision"]
        self.store.apply(self.repos[1]["id"], "frontend-states", "0.1.0", initial)
        before = self.store.path.read_bytes()
        with self.assertRaises(StandardsRevisionConflict):
            self.store.apply(self.repo_id, "qa-evidence", "0.1.0", initial)
        self.assertEqual(self.store.path.read_bytes(), before)
        self.assertEqual(self.store.assignments(self.repo_id)["standardRefs"], [])

    def test_unknown_repository_and_inexact_version_are_rejected(self):
        revision = self.store.assignments(self.repo_id)["revision"]
        for repo_id, standard_id, version in [
            ("repo-" + "0" * 24, "qa-evidence", "0.1.0"),
            (self.repos[0]["path"], "qa-evidence", "0.1.0"),
            (self.repo_id, "qa-evidence", "latest"),
            (self.repo_id, "qa-evidence", "0.2.0"),
            (self.repo_id, "missing", "0.1.0"),
        ]:
            with self.assertRaises(StandardsValidationError):
                self.store.apply(repo_id, standard_id, version, revision)
        self.assertFalse(self.store.path.exists())

    def test_concurrent_assignments_require_fresh_revision(self):
        revision = self.store.assignments(self.repo_id)["revision"]
        barrier = threading.Barrier(2)
        results = []

        def assign(standard_id):
            barrier.wait()
            try:
                self.store.apply(self.repo_id, standard_id, "0.1.0", revision)
                results.append("saved")
            except StandardsRevisionConflict:
                results.append("conflict")

        threads = [threading.Thread(target=assign, args=(ident,)) for ident in ("qa-evidence", "frontend-states")]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=2)
        self.assertCountEqual(results, ["saved", "conflict"])
        self.assertEqual(len(self.store.assignments(self.repo_id)["standardRefs"]), 1)

    def test_separate_instances_cannot_both_save_the_same_revision(self):
        second = StandardsStore(self.data, self.inventory)
        revision = self.store.assignments(self.repo_id)['revision']
        read, release, second_done = threading.Event(), threading.Event(), threading.Event()
        original_read = self.store._assignments
        outcomes = []

        def paused_read():
            value = original_read()
            read.set()
            if not release.wait(3):
                raise AssertionError('assignment read was not released')
            return value

        def assign(store, standard_id):
            try:
                store.apply(self.repo_id, standard_id, '0.1.0', revision)
                outcomes.append('saved')
            except StandardsRevisionConflict:
                outcomes.append('conflict')
            except Exception as error:
                outcomes.append(error)
            finally:
                if store is second:
                    second_done.set()

        self.store._assignments = paused_read
        first_worker = threading.Thread(target=assign, args=(self.store, 'qa-evidence'))
        second_worker = threading.Thread(target=assign, args=(second, 'frontend-states'))
        first_worker.start()
        try:
            self.assertTrue(read.wait(3))
            second_worker.start()
            second_done.wait(.1)
        finally:
            release.set()
            first_worker.join(3)
            if second_worker.ident is not None:
                second_worker.join(3)
        self.assertFalse(first_worker.is_alive())
        self.assertFalse(second_worker.is_alive())
        self.assertCountEqual(outcomes, ['saved', 'conflict'])
        self.assertEqual(second.assignments(self.repo_id)['standardRefs'],
                         [{'id': 'qa-evidence', 'version': '0.1.0'}])

    def test_catalog_tampering_and_unsafe_storage_are_rejected(self):
        self.store.apply(self.repo_id, "qa-evidence", "0.1.0", self.store.assignments(self.repo_id)["revision"])
        raw = json.loads(self.store.catalog_path.read_text(encoding="utf-8"))
        raw["standards"][0]["rules"][0] = "Silently changed original"
        self.store.catalog_path.write_text(json.dumps(raw), encoding="utf-8")
        with self.assertRaises(StandardsValidationError):
            self.store.detail("neutral-interface-draft", "0.1.0-draft")
        with self.assertRaises(StandardsValidationError):
            self.store.snapshot()
        with self.assertRaises(RuleValidationError):
            StandardsStore(Path(self.repos[0]["path"]) / "data", self.inventory)

    def test_malformed_assignment_and_symlink_do_not_get_overwritten(self):
        self.data.mkdir()
        self.store.path.write_text(json.dumps({"schemaVersion": 1, "assignments": {self.repo_id: [{"id": "qa-evidence", "version": "0.1.0", "rules": []}]}}), encoding="utf-8")
        with self.assertRaises(StandardsValidationError):
            self.store.assignments(self.repo_id)
        target = self.data / "original.json"
        target.write_text("{}", encoding="utf-8")
        self.store.catalog_path.symlink_to(target)
        with self.assertRaises(StandardsValidationError):
            self.store.snapshot()
        self.assertEqual(target.read_text(encoding="utf-8"), "{}")


if __name__ == "__main__":
    unittest.main()
