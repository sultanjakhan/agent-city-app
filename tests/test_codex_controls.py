from pathlib import Path
import tempfile
import unittest
import os
from types import SimpleNamespace
from unittest.mock import patch
from codex_controls import _read, _atomic

from codex_controls import CodexControls, CodexControlsError, RevisionConflict, START, END


class Inventory:
    def __init__(self, rows): self.rows = rows
    def list(self): return list(self.rows)


class CodexControlsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.home = self.base / "codex"
        self.home.mkdir()
        self.skills = self.base / "skills" / "demo"
        self.skills.mkdir(parents=True)
        (self.skills / "SKILL.md").write_text("---\nname: Demo\ndescription: d\n---\n", encoding="utf-8")
        self.row = {"id": "s1", "origin": "codex", "path": str(self.skills / "SKILL.md")}
        self.inv = Inventory([self.row])
        self.controls = CodexControls(self.home, self.base / "data", self.inv, "# managed rule")

    def tearDown(self): self.tmp.cleanup()

    def test_parent_reparse_rejects_read_and_write_without_side_effects(self):
        target = self.home / "config.toml"
        target.write_bytes(b"synthetic ordinary config")
        original = Path.lstat
        def metadata(path, *args, **kwargs):
            if path == self.home:
                return SimpleNamespace(st_mode=0o040755, st_file_attributes=0x400)
            return original(path, *args, **kwargs)
        with patch.object(Path, "lstat", metadata):
            with self.assertRaisesRegex(CodexControlsError, "unsafe file path"):
                _read(target, 1024)
            with self.assertRaisesRegex(CodexControlsError, "unsafe file path"):
                _atomic(target, b"replacement")
        self.assertEqual(b"synthetic ordinary config", target.read_bytes())
        self.assertEqual([target], list(self.home.iterdir()))

    def test_ordinary_path_read_write_remains_supported(self):
        target = self.home / "nested" / "config.toml"
        _atomic(target, b"synthetic replacement")
        self.assertEqual(b"synthetic replacement", _read(target, 1024))

    def test_status_and_toggle_preserves_secret_like_text_and_returns_revision_only(self):
        cfg = self.home / "config.toml"
        cfg.write_text('# token = "DO_NOT_RETURN"\n[other]\nkeep = true\n', encoding="utf-8")
        before = self.controls.config_status()
        result = self.controls.set_enabled("s1", False, before["revision"])
        self.assertEqual("disabled", self.controls.config_status()["skills"][0]["status"])
        self.assertNotIn("DO_NOT_RETURN", str(result))
        self.assertIn('token = "DO_NOT_RETURN"', cfg.read_text(encoding="utf-8"))

    def test_existing_entry_and_duplicate_alias_are_safe(self):
        cfg = self.home / "config.toml"
        cfg.write_text('[[skills.config]]\npath = "' + str(self.skills).replace("\\", "/") + '"\nenabled = true\n', encoding="utf-8")
        status = self.controls.config_status()
        self.controls.set_enabled("s1", False, status["revision"])
        self.assertIn("enabled = false", cfg.read_text(encoding="utf-8"))
        path = str(self.skills / "SKILL.md").replace("\\", "/")
        cfg.write_text('[[skills.config]]\npath = "' + path + '"\nenabled = true\n[[skills.config]]\npath = "' + path + '"\nenabled = true\n', encoding="utf-8")
        self.assertEqual("unknown", self.controls.config_status()["skills"][0]["status"])

    def test_conflict_and_unsupported_origins(self):
        (self.home / "config.toml").write_text("x = 1\n", encoding="utf-8")
        with self.assertRaises(RevisionConflict): self.controls.set_enabled("s1", False, "0" * 64)
        other = Inventory([{**self.row, "origin": "plugin:foo"}])
        with self.assertRaises(CodexControlsError): CodexControls(self.home, self.base / "data", other, "x").set_enabled("s1", False, self.controls.config_status()["revision"])

    def test_override_precedence_and_bridge_idempotent(self):
        (self.home / "AGENTS.md").write_text("normal\n", encoding="utf-8")
        (self.home / "AGENTS.override.md").write_text("override\n", encoding="utf-8")
        status = self.controls.bridge_status()
        self.assertTrue(status["path"].endswith("AGENTS.override.md"))
        result = self.controls.connect_bridge(status["revision"])
        again = self.controls.connect_bridge(result["revision"])
        self.assertFalse(again["changed"])
        self.assertTrue(self.controls.bridge_status()["connected"])
        self.assertEqual(1, (self.home / "AGENTS.override.md").read_text(encoding="utf-8").count("agent-city:managed-rules:start"))

    def test_malformed_bridge_and_stale_rules_are_rejected(self):
        p = self.home / "AGENTS.md"
        p.write_text("x\n<!-- agent-city:managed-rules:start -->\n", encoding="utf-8")
        with self.assertRaises(CodexControlsError): self.controls.connect_bridge(self.controls.bridge_status()["revision"])
        p.write_text('original rules\n', encoding='utf-8')
        status = self.controls.bridge_status()
        p.write_text('concurrent rules\n', encoding='utf-8')
        with self.assertRaises(RevisionConflict):
            self.controls.connect_bridge(status['revision'])
        self.assertEqual('concurrent rules\n', p.read_text(encoding='utf-8'))

    def test_missing_other_skill_and_unfamiliar_layout_do_not_corrupt_config(self):
        import json
        cfg = self.home / 'config.toml'
        unrelated = '[[skills.config]]\npath = ' + json.dumps((self.base / 'gone' / 'SKILL.md').as_posix()) + '\nenabled = false\n'
        cfg.write_bytes(unrelated.encode())
        self.controls.set_enabled('s1', False, self.controls.config_status()['revision'])
        self.assertTrue(cfg.read_bytes().startswith(unrelated.encode()))
        text = '[[skills.config]] # comment on header\npath = ' + json.dumps(self.row['path']) + '\nenabled = false\n'
        cfg.write_bytes(text.encode())
        self.assertEqual('disabled', self.controls.config_status()['skills'][0]['status'])
        with self.assertRaises(CodexControlsError):
            self.controls.set_enabled('s1', True, self.controls.config_status()['revision'])
        self.assertEqual(text.encode(), cfg.read_bytes())
        cfg.write_text('broken = [', encoding='utf-8')
        with self.assertRaises(CodexControlsError):
            self.controls.config_status()

    def test_windows_style_skill_paths_and_reparse_config_are_safe(self):
        cfg = self.home / "config.toml"
        cfg.write_text('[[skills.config]]\npath = "' + str(self.skills).replace("\\", "/") + '"\nenabled = true\n', encoding="utf-8")
        self.assertEqual("enabled", self.controls.config_status()["skills"][0]["status"])
        link = self.base / "config-link.toml"
        try:
            link.symlink_to(cfg)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable")
        self.controls.config_path = link
        with self.assertRaises(CodexControlsError):
            self.controls.config_status()

    def test_config_block_stops_at_unrelated_table_and_crlf_bridge_order_is_malformed(self):
        cfg = self.home / "config.toml"
        cfg.write_bytes(("[[skills.config]]\r\npath = \"" + str(self.skills).replace("\\", "/") + "\"\r\nenabled = true\r\n\r\n[other]\r\nenabled = false\r\n").encode())
        status = self.controls.config_status()
        self.controls.set_enabled("s1", False, status["revision"])
        self.assertIn(b"enabled = false\r\n", cfg.read_bytes())
        p = self.home / "AGENTS.md"
        p.write_bytes((END + "\r\n" + START + "\r\n").encode())
        self.assertTrue(self.controls.bridge_status()["malformed"])


if __name__ == "__main__": unittest.main()
