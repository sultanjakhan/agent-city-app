import json
import tempfile
import threading
import unittest
from pathlib import Path

from project_library import ProjectLibrary, ProjectRevisionConflict, ProjectValidationError


def project(**overrides):
    value = {
        "id": "demo-tool",
        "name": "Demo Tool",
        "description": {"ru": "Локальный инструмент.", "en": "A local tool."},
        "useCases": [{"ru": "Поиск документов.", "en": "Document search."}],
        "category": "retrieval",
        "repoUrl": "https://github.com/example/demo-tool",
        "docsUrl": "https://example.com/docs",
        "status": "reference",
    }
    value.update(overrides)
    return value


class ProjectLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "projects.json"
        self.library = ProjectLibrary(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def test_empty_read_and_atomic_add_update(self):
        self.assertEqual(self.library.list(), [])
        revision = self.library.revision()
        saved = self.library.save(project(), revision)
        self.assertEqual(saved["id"], "demo-tool")
        first = self.library.revision()
        self.assertNotEqual(revision, first)
        saved = self.library.save(project(description={"ru": "Обновлено.", "en": "Updated."}), first)
        self.assertEqual(saved["description"]["en"], "Updated.")
        self.assertEqual(self.library.list()[0]["description"]["ru"], "Обновлено.")

    def test_seed_is_read_only_and_save_survives_new_instance(self):
        seed = Path(self.temp.name) / "seed" / "projects.json"
        seed.parent.mkdir()
        seed.write_text(json.dumps({"schemaVersion": 1, "projects": [project(id="seed-tool")]}, ensure_ascii=False), encoding="utf-8")
        local = Path(self.temp.name) / "localprojects.json"
        library = ProjectLibrary(local, seed_path=seed)
        seed_before = seed.read_bytes()
        self.assertEqual(library.snapshot()["projects"][0]["id"], "seed-tool")
        library.save(project(id="user-tool"), library.revision())
        self.assertEqual(seed.read_bytes(), seed_before)
        self.assertIn("user-tool", {item["id"] for item in ProjectLibrary(local, seed_path=seed).list()})

    def test_save_requires_current_revision(self):
        with self.assertRaises(ProjectRevisionConflict):
            self.library.save(project(), None)

    def test_stale_revision_is_rejected(self):
        revision = self.library.revision()
        self.library.save(project(), revision)
        with self.assertRaises(ProjectRevisionConflict):
            self.library.save(project(id="other-tool"), revision)

    def test_reloads_external_change_each_time(self):
        payload = {"schemaVersion": 1, "projects": [project()]}
        self.path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        self.assertEqual(self.library.list()[0]["id"], "demo-tool")

    def test_rejects_unsafe_source_and_unknown_fields(self):
        with self.assertRaises(ProjectValidationError):
            self.library.save(project(repoUrl="http://github.com/example/demo-tool"), self.library.revision())
        with self.assertRaises(ProjectValidationError):
            self.library.save(project(repoUrl="https://evil.example/demo"), self.library.revision())
        with self.assertRaises(ProjectValidationError):
            self.library.save({**project(), "command": "python setup.py"}, self.library.revision())

    def test_rejects_malformed_library(self):
        self.path.write_text("[]", encoding="utf-8")
        with self.assertRaises(ProjectValidationError):
            self.library.list()

    def test_two_library_instances_check_revision_inside_the_same_transaction(self):
        second = ProjectLibrary(self.path)
        revision = self.library.revision()
        read, release, second_done = threading.Event(), threading.Event(), threading.Event()
        original_read = self.library._read
        outcomes = []

        def paused_read():
            value = original_read()
            read.set()
            if not release.wait(3):
                raise AssertionError('library read was not released')
            return value

        def save(library, ident):
            try:
                library.save(project(id=ident), revision)
                outcomes.append('saved')
            except ProjectRevisionConflict:
                outcomes.append('conflict')
            except Exception as error:
                outcomes.append(error)
            finally:
                if library is second:
                    second_done.set()

        self.library._read = paused_read
        first_worker = threading.Thread(target=save, args=(self.library, 'first'))
        second_worker = threading.Thread(target=save, args=(second, 'second'))
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
        self.assertEqual([item['id'] for item in second.list()], ['first'])


if __name__ == "__main__":
    unittest.main()
