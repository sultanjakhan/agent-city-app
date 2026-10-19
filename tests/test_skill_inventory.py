from pathlib import Path
import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from skill_inventory import SkillInventory, SkillInventoryError, default_roots


SKILL = """---
name: Demo
description: A safe synthetic skill.
---

# Content

Do not execute this.
"""


class SkillInventoryTests(unittest.TestCase):
    def test_plugin_namespace_is_not_a_vendor_allowlist(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            document = home / '.codex/plugins/cache/arbitrary-vendor/example-plugin/0.1.0/skills/demo/SKILL.md'
            document.parent.mkdir(parents=True)
            document.write_bytes(SKILL.encode('utf-8'))
            with patch('skill_inventory.Path.home', return_value=home):
                inventory = SkillInventory()
                rows = inventory.list('Demo')
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]['origin'], 'plugin:example-plugin')
                self.assertEqual(inventory.read(rows[0]['id'])['content'], SKILL)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.root = self.base / "root"
        self.root.mkdir()
        (self.root / "demo").mkdir()
        (self.root / "demo" / "SKILL.md").write_bytes(SKILL.encode("utf-8"))
        (self.root / "demo" / "references").mkdir()
        (self.root / "demo" / "references" / "note.txt").write_text("support file", encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def test_list_and_read_are_read_only_and_deduplicate_resolved_documents(self):
        store = SkillInventory([("worktree", self.root), ("duplicate", self.root)])
        before = (self.root / "demo" / "SKILL.md").read_bytes()
        rows = store.list("safe")
        self.assertEqual(1, len(rows))
        row = rows[0]
        self.assertEqual("demo", row["slug"])
        self.assertEqual("worktree", row["origin"])
        self.assertEqual("workspace", row["status"])
        self.assertFalse(row["editable"])
        self.assertNotEqual(str(self.root), row["id"])
        document = store.read(row["id"])
        self.assertEqual(SKILL, document["content"])
        self.assertEqual(before, (self.root / "demo" / "SKILL.md").read_bytes())

    def test_read_requires_id_from_latest_enumeration(self):
        store = SkillInventory([("worktree", self.root)])
        with self.assertRaises(SkillInventoryError):
            store.read("../demo/SKILL.md")

    def test_invalid_and_oversized_skills_are_skipped(self):
        (self.root / "broken").mkdir()
        (self.root / "broken" / "SKILL.md").write_text("not frontmatter", encoding="utf-8")
        (self.root / "huge").mkdir()
        (self.root / "huge" / "SKILL.md").write_bytes((SKILL + "x" * 100).encode("utf-8"))
        rows = SkillInventory([("worktree", self.root)], max_size=len(SKILL.encode("utf-8"))).list()
        self.assertEqual(["demo"], [row["slug"] for row in rows])

    def test_extra_frontmatter_fields_are_tolerated(self):
        content = SKILL.replace("description: A safe synthetic skill.", "description: A safe synthetic skill.\nlicense: Apache-2.0")
        (self.root / "demo" / "SKILL.md").write_text(content, encoding="utf-8")
        rows = SkillInventory([("plugin:demo", self.root)]).list()
        self.assertEqual("plugin:demo", rows[0]["source"])
        self.assertEqual("cached", rows[0]["status"])

    def test_nested_metadata_and_block_description_are_read(self):
        content = """---
name: Nested
description: |
  First line.
  Second line.
metadata:
  short-description: ignored
---
Body
"""
        (self.root / "demo" / "SKILL.md").write_text(content, encoding="utf-8")
        row = SkillInventory([("worktree", self.root)]).list()[0]
        self.assertEqual("First line.\nSecond line.", row["description"])

    def test_default_roots_can_replace_worktree_root(self):
        roots = default_roots(self.root)
        self.assertEqual(self.root, roots[0][1])

    def test_default_mode_refreshes_plugin_roots_on_each_list(self):
        plugin = self.base / "plugin-cache" / "v1" / "skills"
        (plugin / "new-skill").mkdir(parents=True)
        (plugin / "new-skill" / "SKILL.md").write_bytes(SKILL.replace("Demo", "New").encode("utf-8"))
        roots = [("worktree", self.root)]
        with patch("skill_inventory.default_roots", side_effect=[roots, roots, roots + [("plugin:new", plugin)]]) as mocked:
            inventory = SkillInventory()
            self.assertEqual(["demo"], [row["slug"] for row in inventory.list()])
            self.assertEqual(["demo", "new-skill"], sorted(row["slug"] for row in inventory.list()))
            self.assertEqual(3, mocked.call_count)

    def test_symlinked_external_skill_is_not_enumerated_when_supported(self):
        external = self.base / "external"
        external.mkdir()
        (external / "SKILL.md").write_text(SKILL, encoding="utf-8")
        try:
            (self.root / "external").symlink_to(external, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable")
        self.assertEqual(["demo"], [row["slug"] for row in SkillInventory([("worktree", self.root)]).list()])

    @unittest.skipUnless(os.name == 'nt', 'Windows directory junction')
    def test_installed_junction_skill_can_read_repository_source_without_recursive_discovery(self):
        canonical = self.base / "canonical"
        target = canonical / "junction-skill"
        target.mkdir(parents=True)
        (target / "SKILL.md").write_bytes(SKILL.encode("utf-8"))
        junction = self.root / "junction-skill"
        if subprocess.run(["cmd", "/c", "mklink", "/J", str(junction), str(target)], capture_output=True, text=True).returncode:
            self.skipTest("directory junctions unavailable")
        inventory = SkillInventory([("agents", self.root)])
        rows = [row for row in inventory.list() if row["slug"] == "junction-skill"]
        self.assertEqual(1, len(rows))
        self.assertTrue(str(junction) in rows[0]["path"])
        self.assertEqual(SKILL, inventory.read(rows[0]["id"])["content"])
        self.assertNotIn('_resolvedPath', rows[0])
        # A source replaced with a different target must be re-enumerated.
        inventory._entries[rows[0]['id']]['_resolvedPath'] = str(self.base / 'another' / 'SKILL.md')
        with self.assertRaises(SkillInventoryError):
            inventory.read(rows[0]['id'])


if __name__ == "__main__":
    unittest.main()
