import tempfile
import threading
import unittest
from pathlib import Path

from repo_inventory import RepoInventory
from rule_store import RepoProfiles, RuleRevisionConflict, RuleValidationError, RulesStore


def repo(root: Path, name: str = "alpha") -> Path:
    path = root / name
    path.mkdir()
    (path / ".git").mkdir()
    (path / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="ascii")
    return path


class Extensions:
    def list(self):
        return [{"id": "ext-a"}, {"id": "ext-b"}]


class RuleStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "workspace"
        self.root.mkdir()
        self.repo = repo(self.root)
        self.inventory = RepoInventory([self.root])
        self.repo_id = self.inventory.list()[0]["id"]
        self.data = Path(self.temp.name) / "data"
        self.rules = RulesStore(self.data, self.inventory)

    def tearDown(self):
        self.temp.cleanup()

    def test_policy_roundtrip_preserves_legacy_profiles_and_omitted_policy(self):
        profiles = RepoProfiles(self.data, self.inventory, Extensions())
        saved = profiles.save(self.repo_id, ["ext-a"], profiles.read(self.repo_id)["revision"])
        self.assertIsNone(saved["policy"])
        policy = {"schemaVersion": 1, "instructions": "Synthetic", "sourceIds": ["docs"], "allowedActions": ["read"], "deniedActions": [], "defaultPipelineId": None}
        saved = profiles.save(self.repo_id, ["ext-a"], saved["revision"], policy)
        reopened = RepoProfiles(self.data, self.inventory, Extensions())
        self.assertEqual(reopened.read(self.repo_id)["policy"], policy)
        saved = reopened.save(self.repo_id, ["ext-b"], saved["revision"])
        self.assertEqual(saved["policy"], policy)
        import json
        raw = json.loads(profiles.path.read_text(encoding="utf-8"))
        self.assertEqual(raw["profiles"][self.repo_id], ["ext-b"])
        with self.assertRaises(RuleRevisionConflict):
            profiles.save(self.repo_id, [], "stale", policy)
        with self.assertRaises(RuleValidationError):
            profiles.save(self.repo_id, [], saved["revision"], {"schemaVersion": 1, "credentials": "forbidden"})

    def test_empty_read_preview_save_and_immutable_history(self):
        initial = self.rules.read()
        self.assertEqual(initial["content"], "")
        saved = self.rules.save("global", "one", initial["revision"])
        saved_again = self.rules.save("global", "two", saved["revision"])
        self.assertEqual(saved_again["content"], "two")
        history = list((self.data / "history").glob("global-*.md"))
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].read_text(encoding="utf-8"), "one")
        preview = self.rules.preview("global", "three", saved_again["revision"])
        self.assertTrue(preview["changed"])
        self.assertIn("global:current", preview["diff"])

    def test_stale_conflict_and_bounds(self):
        initial = self.rules.read()
        self.rules.save("global", "fresh", initial["revision"])
        with self.assertRaises(RuleRevisionConflict):
            self.rules.save("global", "stale", initial["revision"])
        with self.assertRaises(RuleValidationError):
            self.rules.save("global", "x" * (128 * 1024 + 1), self.rules.read()["revision"])

    def test_concurrent_saves_keep_optimistic_revision_boundary(self):
        revision = self.rules.read()["revision"]
        barrier = threading.Barrier(2)
        outcomes = []

        def save(value):
            barrier.wait()
            try:
                self.rules.save("global", value, revision)
                outcomes.append("saved")
            except RuleRevisionConflict:
                outcomes.append("conflict")

        workers = [threading.Thread(target=save, args=(value,)) for value in ("one", "two")]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()
        self.assertEqual(sorted(outcomes), ["conflict", "saved"])

    def test_repository_scope_merges_without_writing_repo(self):
        before = set(self.repo.rglob("*"))
        self.rules.save("global", "global rules", self.rules.read()["revision"])
        current = self.rules.read(self.repo_id)
        self.rules.save(self.repo_id, "repo rules", current["revision"])
        bundle = self.rules.render_bundle(self.repo_id)
        self.assertIn("[global]", bundle)
        self.assertIn("repo rules", bundle)
        self.assertEqual(before, set(self.repo.rglob("*")))
        self.assertFalse((self.repo / "RULES.md").exists())
        with self.assertRaises(RuleValidationError):
            RulesStore(self.repo / ".agent-city-data", self.inventory)

    def test_profiles_allowlist_revision_and_bounds(self):
        profiles = RepoProfiles(self.data, self.inventory, Extensions())
        initial = profiles.read(self.repo_id)
        saved = profiles.save(self.repo_id, ["ext-a"], initial["revision"])
        self.assertEqual(saved["extensionIds"], ["ext-a"])
        with self.assertRaises(RuleRevisionConflict):
            profiles.save(self.repo_id, ["ext-b"], initial["revision"])
        with self.assertRaises(RuleValidationError):
            profiles.save(self.repo_id, ["unknown"], saved["revision"])
        with self.assertRaises(RuleValidationError):
            profiles.save(self.repo_id, ["ext-a"] * 101, saved["revision"])
        self.assertTrue((self.data / "repository-profiles.json").is_file())
        self.assertFalse((self.repo / "repository-profiles.json").exists())


if __name__ == "__main__":
    unittest.main()
