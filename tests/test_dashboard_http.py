from owner_client import authorize, owner_urlopen
from contextlib import closing
import json
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from server import Server, Store


def request(url, *, method="GET", body=None, headers=None):
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = Request(url, data=data, method=method, headers=headers or {})
    try:
        with owner_urlopen(req, timeout=3) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def make_cicada(path):
    db = sqlite3.connect(path)
    db.executescript("""
      CREATE TABLE items(id TEXT PRIMARY KEY, kind TEXT, title TEXT, notes TEXT, date TEXT, time TEXT,
        duration_minutes INTEGER, completed INTEGER, version INTEGER, created_at TEXT, updated_at TEXT,
        category TEXT, color TEXT, priority INTEGER, archived INTEGER, tags TEXT, content_blocks TEXT, status TEXT);
      CREATE TABLE timeline_blocks(id INTEGER PRIMARY KEY, source_type TEXT, source_id TEXT, date TEXT,
        start_time TEXT, end_time TEXT, duration_minutes INTEGER, duration_seconds INTEGER, is_active INTEGER,
        completion_date TEXT, created_at TEXT, updated_at TEXT);
      CREATE TABLE ui_state(key TEXT PRIMARY KEY, value TEXT, updated_at TEXT);
    """)
    db.execute(
        "INSERT INTO items VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("task-1", "task", "Synthetic task", "", "2026-09-27", "09:00", 20, 0, 1,
         "created", "updated", "general", "", 0, 0, "task-stage:analysis", None, "task"),
    )
    db.execute("INSERT INTO timeline_blocks(id,source_type,source_id,date,start_time,is_active) VALUES(1,'note',?,'2026-09-27','09:00',1)", ("task-1",))
    db.commit()
    db.close()


class DashboardHttpTests(unittest.TestCase):
    def test_history_reads_completed_title_dynamically_and_retains_deleted_task_reports(self):
        from test_run_store import report
        key = self.store.cicada.snapshot()['tasks'][0]['taskKey']
        self.store.runs.report(report(taskKey=key, status='done', skillIds=[]))
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("UPDATE items SET completed=1,status='done',title='Completed current title',notes='private note'")
        before = self.db.read_bytes()
        value = self.store.dashboard()
        self.assertEqual(value['cicada']['tasks'], [])
        self.assertEqual(value['cicada']['historyTasks'][0]['title'], 'Completed current title')
        self.assertEqual(before, self.db.read_bytes())
        self.assertNotIn('private note', json.dumps(value))
        self.assertNotIn('Completed current title', json.dumps(self.store.cloud_reports()))
        self.assertNotIn('Completed current title', self.store.runs.path.read_text())
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("UPDATE items SET title='Renamed after completion'")
        self.assertEqual(self.store.dashboard()['cicada']['historyTasks'][0]['title'], 'Renamed after completion')
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute('DELETE FROM items')
        value = self.store.dashboard()
        self.assertEqual(value['cicada']['historyTasks'], [])
        self.assertEqual(value['runs'][0]['taskKey'], key)
        settings = self.store.cicada.settings()
        self.store.cicada.select(None, settings['revision'])
        value = self.store.dashboard()
        self.assertEqual(value['cicada']['historyStatus'], 'disconnected')
        self.assertEqual(len(value['runs']), 1)

    def test_history_excludes_unreported_tasks_and_foreign_source_ids(self):
        from test_run_store import report
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("UPDATE items SET completed=1,status='done'")
        self.assertEqual(self.store.dashboard()['cicada']['historyTasks'], [])
        self.store.runs.report(report(taskKey='cicada-aaaaaaaaaaaaaaaa-task-1', status='done', skillIds=[]))
        value = self.store.dashboard()
        self.assertEqual(value['cicada']['historyTasks'], [])
        self.assertEqual(len(value['runs']), 1)

    def test_source_change_between_reads_cannot_mix_history_titles(self):
        from unittest.mock import patch
        import copy
        first = self.store.cicada.snapshot()
        second = copy.deepcopy(first)
        second['source']['sourceKey'] = 'aaaaaaaaaaaaaaaa'
        second['tasks'][0]['title'] = 'Other profile private title'
        with patch.object(self.store.cicada, 'snapshot', side_effect=[first, second]):
            value = self.store.dashboard()
        self.assertEqual(value['cicada']['historyStatus'], 'source_changed')
        self.assertEqual(value['cicada']['historyTasks'], [])
        self.assertNotIn('Other profile private title', json.dumps(value))

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.db = root / "cicada.db"
        make_cicada(self.db)
        self.skills = root / "skills" / "demo"
        self.skills.mkdir(parents=True)
        (self.skills / "SKILL.md").write_text(
            "---\nname: demo\ndescription: Synthetic skill\n---\n\nbody\n", encoding="utf-8"
        )
        candidates = [{"id": "production", "label": "Cicada", "path": str(self.db), "profile": "production"}]
        self.store = Store(root / "data", skills_root=root / "skills", executable=False,
                           cicada_candidates=candidates)
        self.http = Server(("127.0.0.1", 0), self.store)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        authorize(self.http)
        self.base = f"http://127.0.0.1:{self.http.server_port}"
        self.headers = {"Host": f"127.0.0.1:{self.http.server_port}", "X-Agent-City": "1",
                        "X-Agent-City-Token": self.store.csrf_token, "Content-Type": "application/json"}

    def tearDown(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join(timeout=2)
        self.temp.cleanup()

    def post(self, path, payload, *, csrf=True):
        headers = dict(self.headers)
        if not csrf:
            headers.pop("X-Agent-City-Token")
        return request(self.base + path, method="POST", body=payload, headers=headers)

    def test_dashboard_is_read_only_and_exposes_synthetic_task_without_secret_or_zero_tokens(self):
        status, dashboard = request(self.base + "/api/dashboard")
        self.assertEqual(status, 200)
        self.assertEqual(dashboard["cicada"]["status"], "connected")
        task = dashboard["cicada"]["tasks"][0]
        self.assertTrue(task["taskKey"].startswith("cicada-"))
        self.assertEqual(task["sourceId"], "task-1")
        self.assertEqual(dashboard["runs"], [])
        self.assertEqual(dashboard["telemetry"], "reported")
        self.assertIn("Missing data is not zero", dashboard["notice"])
        self.assertNotIn("credentials", dashboard["cicada"])

    def test_cloud_profile_is_csrf_guarded_and_status_contains_no_secrets(self):
        self.assertEqual(self.post('/api/cloud/profile',{},csrf=False)[0],403)
        self.assertEqual(self.post('/api/cloud/profile',{})[0],400)
        status,value=request(self.base+'/api/cloud')
        self.assertEqual(status,200); self.assertFalse(value['configured'])
        self.assertNotIn('key',value); self.assertNotIn('token',value)

    def test_remote_report_binds_to_cicada_id_and_does_not_enter_local_run_store(self):
        from datetime import datetime,timezone
        from test_run_store import report
        remote=report(taskKey=None)
        remote.update(updatedAt=datetime.now(timezone.utc).isoformat(),taskBinding={'profile':'production','sourceId':'task-1'},originDevice='device-mac',readOnly=True)
        self.store.cloud.remote=[remote]
        value=self.store.dashboard(); task=value['cicada']['tasks'][0]
        self.assertEqual(value['runs'][0]['taskKey'],task['taskKey'])
        self.assertEqual(self.store.runs.snapshot(),[])

    def test_connector_requires_csrf_and_rejects_stale_revision(self):
        status, settings = request(self.base + "/api/connectors")
        self.assertEqual(status, 200)
        self.assertEqual(settings["selectedId"], "production")
        status, _ = self.post("/api/connectors/cicada",
                              {"sourceId": None, "revision": settings["revision"]}, csrf=False)
        self.assertEqual(status, 403)
        status, changed = self.post("/api/connectors/cicada",
                                    {"sourceId": None, "revision": settings["revision"]})
        self.assertEqual(status, 200)
        status, _ = self.post("/api/connectors/cicada",
                              {"sourceId": "production", "revision": settings["revision"]})
        self.assertEqual(status, 409)
        self.assertIsNone(changed["selectedId"])

    def test_run_report_requires_csrf_validates_skills_and_sequence(self):
        _, dashboard = request(self.base + "/api/dashboard")
        _, inventory = request(self.base + "/api/skill-inventory")
        skill_id = inventory["skills"][0]["id"]
        task_key = dashboard["cicada"]["tasks"][0]["taskKey"]
        payload = {
            "runId": "run-00000001", "sequence": 1, "taskKey": task_key,
            "agent": "codex", "model": "synthetic-model", "provider": "synthetic-provider",
            "stage": "analysis", "status": "running", "skillIds": [skill_id],
            "inputTokens": None, "outputTokens": None,
        }
        self.assertEqual(self.post("/api/runs/report", payload, csrf=False)[0], 403)
        unknown = dict(payload, skillIds=["skill-ffffffffffffffffffffffff"])
        self.assertEqual(self.post("/api/runs/report", unknown)[0], 400)
        status, result = self.post("/api/runs/report", payload)
        self.assertEqual(status, 200)
        self.assertIsNone(result["run"]["inputTokens"])
        self.assertIsNone(result["run"]["outputTokens"])
        self.assertEqual(result["run"]["taskKey"], task_key)
        status, _ = self.post("/api/runs/report", dict(payload, status="done"))
        self.assertEqual(status, 409)
        status, _ = self.post("/api/runs/report", dict(payload, sequence=2, status="done"))
        self.assertEqual(status, 200)

    def test_manifest_is_public_versioned_read_contract(self):
        status, manifest = request(self.base + "/api/v1/manifest")
        self.assertEqual(status, 200)
        self.assertEqual(manifest["schemaVersion"], 1)
        self.assertTrue(manifest["readOnly"])
        self.assertIn("dashboard", manifest["endpoints"])
        self.assertNotIn("csrfToken", manifest)
        self.assertNotIn("credentials", manifest)

    def test_only_started_tasks_are_returned_and_pause_stop_finish_are_dynamic(self):
        from datetime import datetime, timezone, timedelta
        def change(sql, params=()):
            db=sqlite3.connect(self.db)
            try: db.execute(sql, params); db.commit()
            finally: db.close()
        self.assertEqual(len(request(self.base + '/api/dashboard')[1]['cicada']['tasks']), 1)
        change("UPDATE timeline_blocks SET is_active=0,date=?,start_time='00:00'", (datetime.now().date().isoformat(),))
        paused = request(self.base + '/api/dashboard')[1]['cicada']['tasks']
        self.assertTrue(paused[0]['isPaused'])
        change("INSERT INTO ui_state(key,value) VALUES('calendar_in_progress_hidden_v1',?)", (json.dumps({'note:task-1':datetime.now(timezone.utc).isoformat()}),))
        self.assertEqual(request(self.base + '/api/dashboard')[1]['cicada']['tasks'], [])
        change('UPDATE timeline_blocks SET is_active=1')
        self.assertEqual(len(request(self.base + '/api/dashboard')[1]['cicada']['tasks']), 1)
        change("UPDATE items SET completed=1,status='done'")
        self.assertEqual(request(self.base + '/api/dashboard')[1]['cicada']['tasks'], [])
        change("UPDATE items SET completed=0,status='task'")
        change('DELETE FROM timeline_blocks')
        self.assertEqual(request(self.base + '/api/dashboard')[1]['cicada']['tasks'], [])


if __name__ == "__main__":
    unittest.main()
