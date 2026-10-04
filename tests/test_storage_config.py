import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import storage_config


class StorageConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="storage-config-")
        self.base = Path(self.temp.name).resolve()
        self.app = self.base / "agent-city"
        self.app.mkdir()
        self.environ = patch.dict(os.environ, {}, clear=True)
        self.environ.start()
        self.app_patch = patch.object(storage_config, "APP_ROOT", self.app)
        self.app_patch.start()

    def tearDown(self):
        self.app_patch.stop()
        self.environ.stop()
        self.temp.cleanup()

    def test_default_is_adjacent_and_resolution_creates_nothing(self):
        storage = storage_config.load_storage()
        self.assertEqual(storage.root, self.base / "agent-city-data")
        self.assertFalse(storage.root.exists())
        self.assertEqual(storage.cicada_candidates, [])
        self.assertEqual(storage.skill_inventory_roots, [])

    def test_pointer_paths_are_relative_to_pointer_and_move_together(self):
        private = self.base / "custom-data"
        private.mkdir()
        pointer = private / "connection.local.json"
        pointer.write_text(json.dumps({"schemaVersion": 1, "dataRoot": ".", "skillsDirectory": "custom-skills", "credentialsDirectory": "private-keys", "repositoryRoots": ["repos"], "skillInventoryRoots": [{"origin": "installed", "path": "installed-skills"}]}), encoding="utf-8")
        os.environ["AGENT_CITY_CONFIG"] = str(pointer)
        storage = storage_config.load_storage()
        self.assertEqual(storage.root, private)
        self.assertEqual(storage.skills, private / "custom-skills")
        self.assertEqual(storage.credentials, private / "private-keys")
        self.assertEqual(storage.skill_inventory_roots, [("installed", private / "installed-skills")])
        self.assertFalse(storage.skills.exists())

    def test_environment_overrides_pointer_and_legacy_panel_override_survives(self):
        pointer = self.base / "connection.json"
        pointer.write_text(json.dumps({"schemaVersion": 1, "dataRoot": "original"}), encoding="utf-8")
        os.environ.update(AGENT_CITY_CONFIG=str(pointer), AGENT_CITY_DATA_ROOT=str(self.base / "override"), AGENT_CITY_PANEL_DATA=str(self.base / "legacy-panel"))
        storage = storage_config.load_storage()
        self.assertEqual(storage.root, self.base / "override")
        self.assertEqual(storage.panel, self.base / "legacy-panel")
        self.assertEqual(storage.skills, self.base / "override/skills")

    def test_missing_explicit_pointer_fails_without_fallback(self):
        os.environ["AGENT_CITY_CONFIG"] = str(self.base / "missing.json")
        with self.assertRaises(ValueError):
            storage_config.load_storage()

    def test_unknown_config_fields_are_rejected(self):
        pointer = self.app / "storage.local.json"
        pointer.write_text(json.dumps({"schemaVersion": 1, "dataRoot": "../data", "apiKey": "synthetic-placeholder"}), encoding="utf-8")
        with self.assertRaises(ValueError):
            storage_config.load_storage()

    def test_reject_private_paths_inside_app_including_explicit_override(self):
        for name in ["AGENT_CITY_DATA_ROOT", "AGENT_CITY_PANEL_DATA", "AGENT_CITY_SKILLS_ROOT", "AGENT_CITY_CREDENTIALS_DIR", "CODEX_HOME"]:
            with self.subTest(name=name), patch.dict(os.environ, {name: str(self.app / "private")}):
                with self.assertRaises(ValueError):
                    storage_config.load_storage()
        with self.assertRaises(ValueError):
            storage_config.external_directory(self.app / "private")
        self.assertFalse((self.app / "private").exists())

    def test_demo_seeding_never_replaces_existing_user_library(self):
        demo = self.app / "demo/skills/example"
        demo.mkdir(parents=True)
        (demo / "SKILL.md").write_text("Synthetic demonstration", encoding="utf-8")
        storage = storage_config.load_storage()
        storage.skills.mkdir(parents=True)
        original = storage.skills / "user-skill/SKILL.md"
        original.parent.mkdir()
        original.write_text("User definition", encoding="utf-8")
        storage_config.prepare_skills(storage)
        self.assertEqual(original.read_text("utf-8"), "User definition")
        self.assertFalse((storage.skills / "example").exists())

    def test_empty_library_gets_demo_outside_app(self):
        demo = self.app / "demo/skills/example"
        demo.mkdir(parents=True)
        original = demo / "SKILL.md"
        original.write_text("Synthetic demonstration", encoding="utf-8")
        storage = storage_config.load_storage()
        storage_config.prepare_skills(storage)
        self.assertEqual((storage.skills / "example/SKILL.md").read_text("utf-8"), original.read_text("utf-8"))
