import tempfile
import unittest
from pathlib import Path

from repo_inventory import MAX_INSTRUCTION_BYTES, RepoInventory, RepoInventoryError


def make_repo(root: Path, name: str, *, branch: str = "main", worktree: bool = False) -> Path:
    repo = root / name
    repo.mkdir()
    if worktree:
        git_dir = root / f"{name}.gitdir"
        git_dir.mkdir()
        (repo / ".git").write_text(f"gitdir: ../{git_dir.name}\n", encoding="utf-8")
    else:
        git_dir = repo / ".git"
        git_dir.mkdir()
    (git_dir / "HEAD").write_text(f"ref: refs/heads/{branch}\n", encoding="ascii")
    return repo


class RepoInventoryTests(unittest.TestCase):
    def test_scans_depth_one_repositories_and_worktrees(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first = make_repo(root, "alpha")
            second = make_repo(root, "beta-worktree", branch="feature/x", worktree=True)
            nested = root / "nested"
            nested.mkdir()
            make_repo(nested, "too-deep")
            (root / ".hidden").mkdir()
            (root / "node_modules").mkdir()
            result = RepoInventory([root]).list()
            self.assertEqual({item["name"] for item in result}, {"alpha", "beta-worktree"})
            by_name = {item["name"]: item for item in result}
            self.assertEqual(by_name["alpha"]["branch"], "main")
            self.assertEqual(by_name["beta-worktree"]["branch"], "feature/x")
            self.assertEqual(by_name["alpha"]["path"], str(first.resolve()))

    def test_instructions_are_present_and_read_is_bounded(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = make_repo(root, "alpha")
            (repo / "AGENTS.md").write_text("agent rules", encoding="utf-8")
            (repo / "CLAUDE.md").write_text("claude rules", encoding="utf-8")
            rules = repo / ".claude" / "rules"
            rules.mkdir(parents=True)
            (rules / "local.md").write_text("local rules", encoding="utf-8")
            inventory = RepoInventory([root])
            listed = inventory.list()[0]
            self.assertEqual(set(listed["instructions"]), {"AGENTS.md", "CLAUDE.md", ".claude/rules/local.md"})
            details = inventory.read(listed["id"])
            self.assertEqual({item["path"] for item in details["instructionContents"]}, set(listed["instructions"]))

            (repo / "CLAUDE.md").write_bytes(b"x" * (MAX_INSTRUCTION_BYTES + 1))
            details = inventory.read(listed["id"])
            self.assertNotIn("CLAUDE.md", {item["path"] for item in details["instructionContents"]})

    def test_read_requires_current_enumeration(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            make_repo(root, "alpha")
            inventory = RepoInventory([root])
            with self.assertRaises(RepoInventoryError):
                inventory.read("repo-does-not-exist")

    def test_cap_and_detached_head(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for index in range(3):
                repo = make_repo(root, f"repo-{index}")
                (repo / ".git" / "HEAD").write_text("deadbeef\n", encoding="ascii")
            inventory = RepoInventory([root])
            self.assertEqual(len(inventory.list()), 3)
            self.assertEqual(inventory.list()[0]["branch"], "(detached)")

    def test_git_metadata_and_rules_are_bounded_and_pinned(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo_path = root / "bad-marker"
            repo_path.mkdir()
            (repo_path / ".git").write_text("gitdir: " + (root / "outside").as_posix() + "\n" + "x" * 5000, encoding="utf-8")
            (root / "outside").mkdir()
            (root / "outside" / "HEAD").write_text("ref: refs/heads/outside\n", encoding="ascii")
            valid = make_repo(root, "valid")
            (valid / ".git" / "HEAD").write_text("ref: refs/heads/" + "x" * 5000, encoding="ascii")
            rules = valid / ".claude" / "rules"
            rules.mkdir(parents=True)
            (rules / "kept.md").write_text("kept", encoding="utf-8")
            (rules / "ignored.txt").write_text("ignored", encoding="utf-8")
            listed = RepoInventory([root]).list()
            self.assertEqual(len(listed), 1)
            self.assertEqual(listed[0]["instructions"], [".claude/rules/kept.md"])


if __name__ == "__main__":
    unittest.main()
