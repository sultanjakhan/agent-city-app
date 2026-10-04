from contextlib import closing
import json
import sqlite3
import shutil
import tempfile
import unittest
from pathlib import Path

from cicada_connector import CicadaConnector, CicadaRevisionConflict


class CicadaConnectorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "cicada.db"
        c = sqlite3.connect(self.db)
        c.executescript("""
          PRAGMA user_version=5;
          CREATE TABLE items(id TEXT PRIMARY KEY, kind TEXT, title TEXT, notes TEXT, date TEXT, time TEXT,
            duration_minutes INTEGER, completed INTEGER, version INTEGER, created_at TEXT, updated_at TEXT,
            category TEXT, color TEXT, priority INTEGER, archived INTEGER, tags TEXT, content_blocks TEXT, status TEXT);
          CREATE TABLE timeline_blocks(id INTEGER PRIMARY KEY, source_type TEXT, source_id TEXT, date TEXT,
            start_time TEXT, end_time TEXT, duration_minutes INTEGER, duration_seconds INTEGER, is_active INTEGER,
            completion_date TEXT, created_at TEXT, updated_at TEXT);
          CREATE TABLE ui_state(key TEXT PRIMARY KEY, value TEXT, updated_at TEXT);
        """)
        c.execute("INSERT INTO ui_state VALUES(?,?,?)", ("calendar_processes_v1", json.dumps({"version": 1, "processes": [{"id":"custom","title":"Custom process","stages":[{"id":"review","title":"Review"}]}]}), "now"))
        rows = [
            ("keep", "task", "Visible", "", "2026-09-27", "09:00", 20, 0, 1, "c", "u", "g", "", 0, 0, "task-process:custom,task-stage:review,task-stage-log:review@2026-09-27T08:00:00Z", None, "task"),
            ("done", "task", "Done", "", None, None, 20, 1, 1, "c", "u", "g", "", 0, 0, "", None, "task"),
            ("arch", "task", "Archived", "", None, None, 20, 0, 1, "c", "u", "g", "", 0, 1, "", None, "task"),
            ("event", "event", "Event", "", None, None, 20, 0, 1, "c", "u", "g", "", 0, 0, "", None, "event"),
        ]
        c.executemany("INSERT INTO items VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        c.execute("INSERT INTO timeline_blocks VALUES(1,'note','keep','2026-09-27','09:00','09:20',20,1200,0,NULL,'c','u')")
        c.commit(); c.close()
        candidates = [{"id":"production", "label":"Cicada", "path":str(self.db), "profile":"production"}]
        self.connector = CicadaConnector(self.root / "state", candidates=candidates)

    def tearDown(self):
        self.tmp.cleanup()

    def test_requested_history_avoids_first_page_and_does_not_read_other_sources(self):
        self.connector.select('production', self.connector.settings()['revision'])
        prefix = 'cicada-' + self.connector.snapshot()['source']['sourceKey'] + '-'
        with closing(sqlite3.connect(self.db)) as db, db:
            for index in range(501):
                db.execute("INSERT INTO items(id,kind,title,completed,archived,status) VALUES(?,'task',?,0,0,'task')",
                           (f'page-{index}', f'Unrelated {index}'))
            db.execute("UPDATE items SET status='done' WHERE id='done'")
        value = self.connector.snapshot(task_keys=[prefix+'done'])
        self.assertEqual([t['sourceId'] for t in value['tasks']], ['done'])
        self.assertTrue(value['tasks'][0]['completed'])
        self.assertEqual(self.connector.snapshot(task_keys=['cicada-aaaaaaaaaaaaaaaa-done'])['tasks'], [])
        self.assertEqual(self.connector.snapshot(task_keys=[prefix+"' OR 1=1 --"])['tasks'], [])

    def test_filters_fields_and_dynamic_labels_without_notes(self):
        self.connector.select("production", self.connector.settings()["revision"])
        snap = self.connector.snapshot()
        self.assertEqual(snap["status"], "connected")
        self.assertEqual([t["sourceId"] for t in snap["tasks"]], ["keep"])
        task = snap["tasks"][0]
        self.assertEqual(task["processLabel"], "Custom process")
        self.assertEqual(task["stageLabel"], "Review")
        self.assertEqual(task["actualMinutes"], 20)
        self.assertNotIn("notes", task); self.assertNotIn("content", task)

    def test_labels_are_reread_after_ui_state_change(self):
        self.connector.select("production", self.connector.settings()["revision"])
        c = sqlite3.connect(self.db)
        value = {"version": 1, "processes": [{"id":"custom", "title":"Renamed", "stages":[{"id":"review", "title":"Renamed stage"}]}]}
        c.execute("UPDATE ui_state SET value=? WHERE key='calendar_processes_v1'", (json.dumps(value),)); c.commit(); c.close()
        task = self.connector.snapshot()["tasks"][0]
        self.assertEqual(task["processLabel"], "Renamed")
        self.assertEqual(task["stageLabel"], "Renamed stage")

    def test_read_only_and_source_key(self):
        before = self.db.read_bytes()
        self.connector.select("production", self.connector.settings()["revision"])
        snap = self.connector.snapshot()
        self.assertTrue(snap["source"]["sourceKey"])
        self.assertEqual(before, self.db.read_bytes())

    def test_disconnect_and_revision_conflict(self):
        first = self.connector.settings()
        self.connector.select("production", first["revision"])
        stale = self.connector.settings()["revision"]
        self.connector.select(None, stale)
        current = self.connector.settings()
        with self.assertRaises(CicadaRevisionConflict):
            self.connector.select("production", stale)
        self.assertEqual(self.connector.snapshot()["status"], "disconnected")

    def test_unknown_stage_keeps_id_and_missing_file_is_error(self):
        c = sqlite3.connect(self.db); c.execute("UPDATE items SET tags='task-stage:deleted' WHERE id='keep'"); c.commit(); c.close()
        self.connector.select("production", self.connector.settings()["revision"])
        self.assertEqual(self.connector.snapshot()["tasks"][0]["stageLabel"], "deleted")
        self.db.unlink()
        self.assertEqual(self.connector.snapshot()["status"], "error")

    def test_old_schema_rejected(self):
        old = self.root / "old.db"; c = sqlite3.connect(old); c.execute("CREATE TABLE items(id TEXT)"); c.commit(); c.close()
        connector = CicadaConnector(self.root / "state2", candidates=[{"id":"dev","label":"Cicada DEV","path":str(old),"profile":"dev"}])
        connector.select("dev", connector.settings()["revision"])
        self.assertEqual(connector.snapshot()["status"], "error")

    def test_has_more_distinguishes_500_and_501(self):
        c = sqlite3.connect(self.db)
        c.execute("DELETE FROM items")
        rows = [(str(i), "task", f"T{i}", "", None, None, 1, 0, 1, "c", "u", "g", "", 0, 0, "", None, "task") for i in range(501)]
        c.executemany("INSERT INTO items VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows); c.commit(); c.close()
        self.connector.select("production", self.connector.settings()["revision"])
        self.assertEqual(len(self.connector.snapshot()["tasks"]), 500)
        self.assertTrue(self.connector.snapshot()["hasMore"])
        c = sqlite3.connect(self.db); c.execute("DELETE FROM items WHERE id='500'"); c.commit(); c.close()
        self.assertFalse(self.connector.snapshot()["hasMore"])

    def test_hash_in_path_and_custom_stage_do_not_use_builtin_label(self):
        c = sqlite3.connect(self.db)
        c.execute("UPDATE items SET tags='task-process:custom,task-stage:understanding' WHERE id='keep'"); c.commit(); c.close()
        hashed = self.root / "hash#folder"; hashed.mkdir(); copied = hashed / "calendar.db"; shutil.copyfile(self.db, copied)
        connector = CicadaConnector(self.root / "state-hash", candidates=[{"id":"dev", "label":"Cicada DEV", "path":str(copied), "profile":"dev"}])
        connector.select("dev", connector.settings()["revision"])
        snap = connector.snapshot()
        self.assertEqual(snap["status"], "connected")
        self.assertEqual(snap["tasks"][0]["stageLabel"], "understanding")

    def test_read_only_wal_sees_committed_row_while_writer_is_open(self):
        writer = sqlite3.connect(self.db)
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("INSERT INTO items VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", ("wal", "task", "WAL", "", None, None, 1, 0, 1, "c", "u", "g", "", 0, 0, "", None, "task"))
        writer.commit()
        self.connector.select("production", self.connector.settings()["revision"])
        ids = {row["sourceId"] for row in self.connector.snapshot()["tasks"]}
        writer.close()
        self.assertIn("wal", ids)

    def test_candidate_created_after_connector_start_can_be_selected(self):
        future = self.root / "future.db"
        connector = CicadaConnector(self.root / "future-state", candidates=[{"id":"dev", "label":"Cicada DEV", "path":str(future), "profile":"dev"}])
        shutil.copyfile(self.db, future)
        connector.select("dev", connector.settings()["revision"])
        self.assertEqual(connector.snapshot()["status"], "connected")


if __name__ == "__main__":
    unittest.main()
