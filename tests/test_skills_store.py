import os
from pathlib import Path
import tempfile
import threading
import unittest

from skills_store import (
    RevisionConflict,
    SkillPathError,
    SkillValidationError,
    SkillsStore,
)


GOOD = """---
name: demo-skill
description: A synthetic skill for editor tests.
---

# Demo

Do nothing.
"""


class SkillsStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.skills = self.base / "skills"
        self.data = self.base / "data"
        self.skills.mkdir()
        (self.skills / "demo-skill").mkdir()
        (self.skills / "demo-skill" / "SKILL.md").write_bytes(GOOD.encode("utf-8"))
        self.store = SkillsStore(self.skills, self.data, max_size=4096)

    def tearDown(self):
        self.temp.cleanup()

    def test_list_search_and_read_return_metadata_without_executing(self):
        listed = self.store.list("synthetic")
        self.assertEqual(["demo-skill"], [item["name"] for item in listed])
        self.assertEqual("demo-skill/SKILL.md", listed[0]["path"])
        self.assertEqual("demo-skill", listed[0]["slug"])
        document = self.store.read("demo-skill")
        self.assertEqual(GOOD, document["content"])
        self.assertEqual(listed[0]["revision"], document["revision"])

    def test_preview_and_save_use_optimistic_revision_and_history(self):
        current = self.store.read("demo-skill")
        changed = GOOD.replace("Do nothing.", "Remain inert.")
        preview = self.store.preview("demo-skill", changed, expected_revision=current["revision"])
        self.assertTrue(preview["changed"])
        self.assertIn("Remain inert.", preview["diff"])
        saved = self.store.save("demo-skill", changed, expected_revision=current["revision"])
        self.assertNotEqual(current["revision"], saved["revision"])
        old = self.store.read_revision("demo-skill", current["revision"])
        self.assertEqual(GOOD, old["content"])
        with self.assertRaises(RevisionConflict):
            self.store.save("demo-skill", GOOD, expected_revision=current["revision"])
        restored = self.store.rollback("demo-skill", current["revision"], expected_revision=saved["revision"])
        self.assertEqual(current["revision"], restored["revision"])
        self.assertEqual(GOOD, restored["content"])

    def test_frontmatter_and_size_are_validated_before_write(self):
        current = self.store.read("demo-skill")
        for invalid in ("# no frontmatter\n", "---\nname: only\n---\n", "---\ndescription: only\n---\n"):
            with self.subTest(invalid=invalid), self.assertRaises(SkillValidationError):
                self.store.save("demo-skill", invalid, expected_revision=current["revision"])
        with self.assertRaises(SkillValidationError):
            self.store.save("demo-skill", GOOD + ("x" * 5000), expected_revision=current["revision"])
        self.assertEqual(current["revision"], self.store.read("demo-skill")["revision"])

    def test_traversal_is_blocked_but_skill_support_files_are_allowed(self):
        with self.assertRaises(SkillPathError):
            self.store.read("../demo-skill")
        with self.assertRaises(SkillPathError):
            self.store.read(".git")
        (self.skills / ".git").write_text("blocked", encoding="utf-8")
        (self.skills / "demo-skill" / "scripts").mkdir()
        (self.skills / "demo-skill" / "scripts" / "helper.py").write_text("raise RuntimeError", encoding="utf-8")
        self.assertEqual("demo-skill", self.store.list()[0]["slug"])

    def test_list_skips_invalid_or_foreign_directories(self):
        (self.skills / "broken").mkdir()
        (self.skills / "broken" / "SKILL.md").write_text("no frontmatter", encoding="utf-8")
        (self.skills / "foreign").mkdir()
        (self.skills / "foreign" / "README.md").write_text("not a skill", encoding="utf-8")
        self.assertEqual(["demo-skill"], [item["slug"] for item in self.store.list()])

    def test_tampered_history_is_rejected(self):
        current = self.store.read("demo-skill")
        changed = GOOD.replace("Do nothing.", "Changed.")
        saved = self.store.save("demo-skill", changed, expected_revision=current["revision"])
        history = self.data / "skills-history" / "demo-skill" / f"{current['revision']}.md"
        history.write_text("tampered", encoding="utf-8")
        with self.assertRaises(SkillValidationError):
            self.store.rollback("demo-skill", current["revision"], expected_revision=saved["revision"])

    def test_concurrent_writes_cannot_bypass_revision(self):
        current = self.store.read("demo-skill")
        barrier = threading.Barrier(2)
        results = []

        def worker(text):
            barrier.wait()
            try:
                results.append(self.store.save("demo-skill", GOOD.replace("Do nothing.", text), expected_revision=current["revision"]))
            except RevisionConflict:
                results.append(None)

        threads = [threading.Thread(target=worker, args=(text,)) for text in ("First.", "Second.")]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        self.assertEqual(1, sum(result is not None for result in results))

    def test_symlink_skill_is_blocked_when_platform_allows_symlinks(self):
        target = self.base / "target"
        target.mkdir()
        try:
            (self.skills / "linked").symlink_to(target, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable")
        with self.assertRaises((SkillPathError, SkillValidationError)):
            self.store.list()

    def test_history_is_outside_skills_root(self):
        content = GOOD.replace("Do nothing.", "Changed.")
        self.store.save("demo-skill", content)
        self.assertTrue(list((self.data / "skills-history" / "demo-skill").glob("*.md")))
        self.assertFalse((self.skills / "skills-history").exists())

    def test_crlf_history_keeps_byte_revision(self):
        crlf = GOOD.replace("\n", "\r\n")
        (self.skills / "demo-skill" / "SKILL.md").write_bytes(crlf.encode("utf-8"))
        store = SkillsStore(self.skills, self.data, max_size=4096)
        current = store.read("demo-skill")
        changed = crlf.replace("Do nothing.", "Remain inert.")
        saved = store.save("demo-skill", changed, expected_revision=current["revision"])
        self.assertEqual(crlf, store.read_revision("demo-skill", current["revision"])["content"])
        restored = store.rollback("demo-skill", current["revision"], expected_revision=saved["revision"])
        self.assertEqual(current["revision"], restored["revision"])


if __name__ == "__main__":
    unittest.main()
