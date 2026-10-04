"""Disposable server for UI tests. Synthetic data only; no providers or CodexBar called."""
from pathlib import Path
import os
import json
import sqlite3
import hashlib
import hmac
import base64
import sys
import tempfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import Server, Store, now
import access
import panel_keys as credentials
for variable in credentials.ENV_KEYS.values():
    os.environ.pop(variable, None)


def unavailable(_):
    raise TimeoutError("synthetic outage")


def make_cicada(path, title):
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
    db.execute("INSERT INTO items VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
               ("shared-task", "task", title, "private notes must not leave Cicada", "2026-09-27", "09:00",
                20, 0, 1, "created", "updated", "general", "", 0, 0,
                "task-process:custom,task-stage:analysis,task-stage-log:analysis@2026-09-27T08:00:00Z",
                None, "task"))
    db.execute("INSERT INTO ui_state VALUES(?,?,?)", ("calendar_processes_v1", '{"processes":[]}', "now"))
    db.execute("INSERT INTO timeline_blocks(id,source_type,source_id,date,start_time,is_active) VALUES(1,'note',?,'2026-09-27','09:00',1)", ("shared-task",))
    from work_exchange import validate_binding
    import hashlib
    ns='11111111-1111-4111-8111-111111111111' if path.name.endswith('production.db') else '22222222-2222-4222-8222-222222222222'
    b={'sourceNamespace':ns,'sourceType':'note','sourceId':'shared-task','taskKey':'cicada-'+hashlib.sha256(ns.encode()).hexdigest()[:16]+'-shared-task'}
    validate_binding(b)
    state={'version':1,'sourceNamespace':ns,'order':0,'bindings':{b['taskKey']:b},'runs':{}}
    db.execute("INSERT INTO ui_state VALUES(?,?,?)", ('calendar_task_run_exchange_v1',json.dumps(state),'now'))
    db.commit(); db.close()


with tempfile.TemporaryDirectory(prefix="agentcity-ui-") as directory:
    # The fixture must not depend on a bundled catalogue: independent QA may
    # deliberately exclude data/ while preserving only application code.
    project = {"id":"fixture-reference", "name":"Synthetic reference",
               "description":{"ru":"Synthetic fixture", "en":"Synthetic fixture"},
               "useCases":[{"ru":"Synthetic check", "en":"Synthetic check"}],
               "category":"other", "status":"reference",
               "repoUrl":"https://github.com/example/fixture-reference",
               "docsUrl":"https://example.invalid/docs"}
    (Path(directory) / "projects.json").write_text(json.dumps({"schemaVersion":1,"projects":[project]}), encoding="utf-8")
    credentials.SECRET_ROOT = Path(directory) / "keys"
    skills_root = Path(directory) / 'skills'
    (skills_root / 'sample').mkdir(parents=True)
    (skills_root / 'sample' / 'SKILL.md').write_text('---\nname: sample\ndescription: Synthetic skill for UI testing\n---\nOriginal body.\n', encoding='utf-8')
    repos_root = Path(directory) / 'repos'
    (repos_root / 'fixture-repo' / '.git').mkdir(parents=True)
    (repos_root / 'fixture-repo' / '.git' / 'HEAD').write_text('ref: refs/heads/main\n', encoding='utf-8')
    (repos_root / 'fixture-repo' / 'AGENTS.md').write_text('Keep repository instructions intact.\n', encoding='utf-8')
    codex_home = Path(directory) / 'codex'
    installed = codex_home / 'skills' / 'installed'
    installed.mkdir(parents=True)
    (installed / 'SKILL.md').write_text('---\nname: Installed test\ndescription: Synthetic installed skill\n---\nNever execute.\n', encoding='utf-8')
    (codex_home / 'config.toml').write_text('model = "synthetic-only"\n', encoding='utf-8')
    (codex_home / 'AGENTS.md').write_text('Preserve existing global instructions.\n', encoding='utf-8')
    production_db = Path(directory) / 'cicada-production.db'
    dev_db = Path(directory) / 'cicada-dev.db'
    make_cicada(production_db, 'Production task title')
    make_cicada(dev_db, 'DEV task title')
    cicada_candidates = [
        {'id': 'production', 'label': 'Cicada', 'path': str(production_db), 'profile': 'production'},
        {'id': 'dev', 'label': 'Cicada DEV', 'path': str(dev_db), 'profile': 'dev'},
    ]
    store = Store(directory, catalog_fetcher=unavailable, bar_fetcher=unavailable, executable=Path("synthetic-cli"), skills_root=skills_root, repo_roots=[repos_root], codex_home=codex_home, inventory_roots=[('worktree', skills_root), ('codex', codex_home / 'skills')], cicada_candidates=cicada_candidates, directory_fetcher=lambda: {'providers': [{'id': 'new-lab', 'name': 'New Lab', 'modelCount': 7, 'docs': 'https://example.invalid/docs'}]})
    store.data_sources.new_profile = False
    store.state['directory'] = {'providers': [{'id': 'new-lab', 'name': 'New Lab', 'modelCount': 7, 'docs': 'https://example.invalid/docs'}], 'updatedAt': now()}
    stamp = now()
    import json
    (Path(directory)/'provider-runtime-status.json').write_text(json.dumps({'openai':{'client':'codex','auth':'chatgpt','status':'authenticated','source':'codex-login-status','checkedAt':stamp},'zen':{'client':'opencode','auth':'api-key','status':'unverified','source':'panel-status-and-official-docs','checkedAt':stamp,'clientInPath':False}}),encoding='utf8')
    qwen = {"id": "qwen/test:free", "name": "Qwen Test", "developer": "qwen", "chinese": True, "context": 131072, "tools": True, "vision": False, "priceVerified": True}
    other = {"id": "example/test:free", "name": "Example Test", "developer": "example", "chinese": False, "context": 64000, "tools": None, "vision": False, "priceVerified": True}
    store.state["catalogs"] = {"openrouter": {"models": [qwen, other], "updatedAt": stamp, "error": None}, "kilo": {"models": [qwen], "updatedAt": stamp, "error": None}}
    store.state['catalogs']['openrouter']['allModels'] = [qwen,other,{'id':'example/paid','name':'Paid Test','developer':'example','priceVerified':False,'priceStatus':'paid'},{'id':'example/unknown','name':'Unknown Test','developer':'example','priceVerified':False,'priceStatus':'unknown'}]
    jev = {"id": "jev-test", "name": "Jev Test", "developer": "typesafe", "kind": "structured", "priceVerified": False}
    store.state["catalogs"]["zen"] = {"models": [jev], "updatedAt": stamp}
    store.clients = [{"id": "cline", "name": "Cline", "extensionInstalled": True, "cliInstalled": True, "docs": "https://docs.cline.bot/provider-config/openrouter"},
                     {"id": "opencode", "name": "OpenCode", "extensionInstalled": False, "cliInstalled": False, "docs": "https://opencode.ai/docs/ide/"}]
    access.key_available = lambda provider: provider in {"openrouter", "kilo"} or credentials.key_available(provider)
    access.probe = lambda provider, model, _: {"provider": provider, "model": model, "attemptedAt": now(), "status": "ok", "sent": True,
                                              "reply": "CITY_OK_4", "finishReason": "stop", "durationMs": 50, "detail": "Контрольный ответ получен"}
    store.state["codexbar"] = {"version": "test", "generatedAt": stamp, "staleAfterSeconds": 180, "updatedAt": stamp, "error": None,
        "providers": [{"id": "codex", "name": "Codex", "windows": [{"kind": "session", "label": "Сессия", "remainingPercent": 100, "resetAt": None}, {"kind": "weekly", "label": "Неделя", "remainingPercent": 0, "resetAt": None}], "updatedAt": stamp, "error": False},
                      {"id": "claude", "name": "Claude", "windows": [], "updatedAt": stamp, "error": True}]}
    bootstrap_root=os.environ.pop('AGENT_CITY_UI_BOOTSTRAP')
    service = Server(("127.0.0.1", int(os.environ.get('AGENT_CITY_TEST_PORT', '47833'))), store, bootstrap=bootstrap_root, owner_host=os.environ.pop('AGENT_CITY_UI_OWNER_HOST'))
    for worker in range(128):
        capability=base64.urlsafe_b64encode(hmac.new(bootstrap_root.encode(),str(worker).encode(),hashlib.sha256).digest()).decode().rstrip('=')
        service.owner_sessions.add_bootstrap(capability)
    service.owner_sessions.add_bootstrap(os.environ.pop('AGENT_CITY_UI_EXTRA_BOOTSTRAP'))
    service.serve_forever()
