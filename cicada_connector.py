"""Read-only, bounded connector for known Cicada SQLite profiles."""
from __future__ import annotations

import hashlib
from contextlib import closing
import json
import os
import stat
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import threading
import time
import shutil
import sys
from typing import Any


class CicadaConnectorError(Exception):
    pass


class CicadaRevisionConflict(CicadaConnectorError):
    pass


# Stable names for the HTTP layer.
ConnectorError = CicadaConnectorError
ConnectorConflict = CicadaRevisionConflict


_REQUIRED = {"id", "kind", "title", "date", "time", "completed", "version", "updated_at",
             "archived", "tags", "status"}
_BUILTIN = {
    "understanding": "Понимание", "requirements": "Требования", "analysis": "Анализ и модели",
    "description": "Описание", "agreement": "Согласование", "decomposition": "Декомпозиция",
    "development": "В разработке", "acceptance": "Приёмка",
}


def _revision(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _has_reparse(path: Path) -> bool:
    current = path
    while True:
        try:
            info = current.lstat()
            if stat.S_ISLNK(info.st_mode) or (getattr(info, "st_file_attributes", 0) & 0x400):
                return True
        except OSError:
            pass
        if current.parent == current:
            return False
        current = current.parent


def _atomic_json(path: Path, payload: Any) -> None:
    if _has_reparse(path) or _has_reparse(path.with_suffix(path.suffix + ".bak")) or _has_reparse(path.with_name(path.name + ".tmp")):
        raise CicadaConnectorError("connector settings path is redirected")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        shutil.copyfile(path, path.with_suffix(path.suffix + ".bak"))
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _default_candidates() -> list[dict[str, str]]:
    from storage_config import load_storage
    return load_storage().cicada_candidates


class CicadaConnector:
    def __init__(self, data_dir: str | os.PathLike[str], candidates: list[dict[str, str]] | None = None):
        self.data_dir = Path(data_dir)
        self.path = self.data_dir / "connectors.json"
        self.candidates = self._validate_candidates(candidates if candidates is not None else _default_candidates())
        self._pins = {}
        self._pin_resolved = {}
        for candidate in self.candidates:
            raw = Path(candidate["path"])
            try:
                exists = raw.is_file()
                self._pins[candidate["id"]] = raw.resolve(strict=True) if exists else (raw if raw.is_absolute() else Path.cwd() / raw)
                self._pin_resolved[candidate["id"]] = exists
            except OSError:
                self._pins[candidate["id"]] = None
        self._lock = threading.RLock()

    @staticmethod
    def _validate_candidates(rows: list[dict[str, str]]) -> list[dict[str, str]]:
        out = []
        seen = set()
        for row in rows:
            if not isinstance(row, dict) or set(row) != {"id", "label", "path", "profile"}:
                raise ValueError("invalid Cicada candidate")
            if row["id"] in seen or row["id"] not in {"production", "dev"}:
                raise ValueError("invalid Cicada candidate id")
            if row["profile"] not in {"production", "dev"} or not all(isinstance(row[k], str) and row[k] for k in row):
                raise ValueError("invalid Cicada candidate")
            seen.add(row["id"]); out.append(dict(row))
        return out

    def _read_settings(self) -> tuple[str | None, str]:
        if _has_reparse(self.path) or _has_reparse(self.path.with_suffix(self.path.suffix + ".bak")) or _has_reparse(self.path.with_name(self.path.name + ".tmp")):
            raise CicadaConnectorError("connector settings path is redirected")
        if not self.path.is_file():
            payload = {"selectedId": "production" if self._find("production", existing=True) else None}
            return payload["selectedId"], _revision(payload)
        try:
            raw = self.path.read_text(encoding="utf-8")
            if len(raw.encode()) > 64 * 1024:
                raise ValueError
            value = json.loads(raw)
            selected = value.get("selectedId")
            if selected is not None and self._find(selected) is None:
                selected = None
            payload = {"selectedId": selected}
            return selected, _revision(payload)
        except Exception as exc:
            raise CicadaConnectorError("повреждены настройки подключения Cicada") from exc

    def _find(self, source_id: str | None, *, existing: bool = False) -> dict[str, str] | None:
        row = next((c for c in self.candidates if c["id"] == source_id), None)
        if row and existing and not Path(row["path"]).is_file():
            return None
        return row

    def settings(self) -> dict[str, Any]:
        with self._lock:
            selected, rev = self._read_settings()
            candidates = [dict(c) for c in self.candidates if Path(c["path"]).is_file() and not _has_reparse(Path(c["path"]))]
            return {"schemaVersion": 1, "candidates": candidates, "selectedId": selected, "revision": rev}

    def select(self, source_id: str | None, revision: str) -> dict[str, Any]:
        with self._lock:
            selected, current = self._read_settings()
            if revision != current:
                raise CicadaRevisionConflict("connector settings changed")
            if source_id is not None and self._find(source_id) is None:
                raise CicadaConnectorError("unknown Cicada source")
            payload = {"selectedId": source_id}
            _atomic_json(self.path, payload)
            return self.settings()

    def _source_path(self, row: dict[str, str]) -> Path:
        path = Path(row["path"])
        if not path.is_file() or path.is_symlink() or _has_reparse(path):
            raise CicadaConnectorError("Cicada database is unavailable")
        resolved = path.resolve(strict=True)
        pin = self._pins.get(row["id"])
        if (self._pin_resolved.get(row["id"], False) and pin != resolved) or (not self._pin_resolved.get(row["id"], False) and pin != path):
            raise CicadaConnectorError("Cicada database identity changed")
        return resolved

    def snapshot(self, *, task_keys: list[str] | None = None, bindings: dict | None = None) -> dict[str, Any]:
        with self._lock:
            selected, _ = self._read_settings()
            row = self._find(selected)
            if row is None:
                return {"source": None, "status": "disconnected", "readAt": _now(), "tasks": []}
            try:
                path = self._source_path(row)
                source_key = hashlib.sha256(str(path).encode()).hexdigest()[:16]
                from work_exchange import ExchangeError
                exchange_status = 'missing'
                try:
                    identity = self.exchange_identity(path)
                    exchange_status = 'available' if identity else 'missing'
                except (ExchangeError, ValueError):
                    identity = None; exchange_status = 'invalid'
                paired = {key: entry['binding'] for key, entry in (bindings or {}).items() if identity and entry['source'] == {'selectedId':selected, 'profile':row['profile'], 'sourceNamespace':identity['sourceNamespace']} and identity['bindings'].get(key) == entry['binding']}
                source_ids = None
                if task_keys is not None:
                    prefix = 'cicada-' + source_key + '-'
                    source_ids = list(dict.fromkeys(
                        paired[key]['sourceId'] if key in paired else key[len(prefix):]
                        for key in task_keys if isinstance(key, str) and (key in paired or key.startswith(prefix))))[:500]
                tasks = self._read_db(path, source_ids=source_ids)
                source = {"id": row["id"], "label": row["label"], "profile": row["profile"], "path": str(path), "sourceKey": source_key}
                tasks, has_more = tasks
                for task in tasks:
                    match = next((b for b in paired.values() if b['sourceId'] == task['sourceId']), None)
                    if match:
                        task['legacyTaskKey'] = task['taskKey']
                        task['taskKey'] = match['taskKey']
                        task['sourceNamespace'] = match['sourceNamespace']
                        task['runTaskKeys'] = [task['taskKey'], task['legacyTaskKey']]
                source['sourceNamespace'] = identity['sourceNamespace'] if identity else None
                source['exchangeStatus'] = exchange_status
                return {"source": source, "status": "connected", "readAt": _now(), "tasks": tasks, "hasMore": has_more}
            except Exception as exc:
                return {"source": {"id": row["id"], "label": row["label"], "profile": row["profile"]}, "status": "error", "readAt": _now(), "tasks": [], "error": "Не удалось прочитать Cicada. Проверь источник в настройках."}

    @staticmethod
    def exchange_identity(path):
        from work_exchange import validate_binding, strict_json, ExchangeError
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=1)) as db:
            db.execute("PRAGMA query_only=ON")
            db.execute("PRAGMA trusted_schema=OFF")
            db.set_progress_handler(lambda: 1, 100000)
            row = db.execute("SELECT substr(value,1,4194305) FROM ui_state WHERE key='calendar_task_run_exchange_v1'").fetchone()
            if not row or not row[0]: return None
            value = strict_json(row[0], limit=4 * 1024 * 1024)
            if not isinstance(value, dict) or set(value) != {'version','sourceNamespace','order','bindings','runs'} or type(value['version']) is not int or value['version'] != 1 or not isinstance(value['bindings'], dict) or len(value['bindings']) > 500 or not isinstance(value['runs'], dict) or len(value['runs']) > 500:
                raise ExchangeError('invalid_source_exchange')
            for key, binding in value['bindings'].items():
                validate_binding(binding)
                if key != binding['taskKey'] or binding['sourceNamespace'] != value['sourceNamespace']:
                    raise ExchangeError('invalid_source_exchange')
            from work_exchange import namespace
            namespace(value['sourceNamespace'])
            return {'sourceNamespace':value['sourceNamespace'], 'bindings':value['bindings']}

    def authorize_binding(self, binding, *, personal_only=False):
        from work_exchange import validate_binding, ExchangeError
        validate_binding(binding)
        with self._lock:
            selected, _ = self._read_settings(); candidate = self._find(selected)
            if candidate is None: raise ExchangeError('no_selected_source')
            path = self._source_path(candidate); identity = self.exchange_identity(path)
            if not identity or identity['sourceNamespace'] != binding['sourceNamespace'] or identity['bindings'].get(binding['taskKey']) != binding:
                raise ExchangeError('unknown_source_binding')
            with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=1)) as db:
                db.execute("PRAGMA query_only=ON"); db.execute("PRAGMA trusted_schema=OFF")
                db.set_progress_handler(lambda: 1, 100000)
                row = db.execute("SELECT tags FROM items WHERE id=? AND kind='task' AND archived=0 LIMIT 1", (binding['sourceId'],)).fetchone()
                if row is None: raise ExchangeError('missing_native_task')
                if personal_only:
                    tags = {part.strip().lower() for part in str(row[0]).split(',')}
                    if 'task-sphere:personal' not in tags or 'task-sphere:work' in tags or any(tag.startswith(('jira','investlink')) for tag in tags):
                        raise ExchangeError('personal_task_required')
            return {'selectedId':selected, 'profile':candidate['profile'], 'sourceNamespace':identity['sourceNamespace']}

    @staticmethod
    def _read_db(path: Path, *, source_ids: list[str] | None = None) -> tuple[list[dict[str, Any]], bool]:
        uri = path.as_uri() + "?mode=ro"
        con = sqlite3.connect(uri, uri=True, timeout=1)
        try:
            con.execute("PRAGMA query_only=ON")
            deadline = time.monotonic() + 2.0
            con.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 100000)
            cols = {r[1] for r in con.execute("PRAGMA table_info(items)")}
            tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not _REQUIRED <= cols or "timeline_blocks" not in tables:
                raise CicadaConnectorError("unsupported Cicada schema")
            process_raw = con.execute("SELECT value FROM ui_state WHERE key='calendar_processes_v1'").fetchone()
            hidden_raw = con.execute("SELECT value FROM ui_state WHERE key='calendar_in_progress_hidden_v1'").fetchone()
            try:
                hidden = json.loads(hidden_raw[0]) if hidden_raw else {}
                if not isinstance(hidden, dict): hidden = {}
            except (ValueError, TypeError): hidden = {}
            processes = {}
            if process_raw and process_raw[0]:
                try:
                    value = json.loads(process_raw[0])
                    processes = {p.get("id"): p for p in value.get("processes", []) if isinstance(p, dict)}
                except Exception:
                    processes = {}
            if source_ids is not None and not source_ids:
                return [], False
            where = "i.kind='task' AND i.archived=0 AND i.status='task' AND i.completed=0"
            params = [datetime.now().date().isoformat()]
            if source_ids is not None:
                source_ids = list(dict.fromkeys(source_ids))[:500]
                where = "i.kind='task' AND i.archived=0 AND i.id IN (" + ','.join('?' for _ in source_ids) + ')'
                params.extend(source_ids)
            sql = """SELECT i.id,substr(i.title,1,500),i.date,i.time,i.completed,i.updated_at,substr(i.tags,1,65536),
                     COALESCE(MAX(CASE WHEN t.is_active=1 THEN 1 ELSE 0 END),0),
                     COALESCE(SUM(CASE WHEN t.is_active=0 THEN CASE WHEN t.duration_seconds>0 THEN t.duration_seconds ELSE t.duration_minutes*60 END ELSE 0 END),0),
                     COALESCE(MAX(CASE WHEN t.date=? THEN 1 ELSE 0 END),0), MAX(t.date || 'T' || t.start_time)
                     FROM items i LEFT JOIN timeline_blocks t ON t.source_type='note' AND t.source_id=i.id
                     WHERE {where}
                     GROUP BY i.id ORDER BY 8 DESC,10 DESC,i.date,i.time,i.id LIMIT 501""".format(where=where)
            result = []
            for ident, title, date, tm, completed, updated, tags, active, seconds, worked_today, latest_start in con.execute(sql, params):
                stopped = hidden.get('note:' + str(ident))
                hidden_paused = False
                if stopped and not active:
                    try:
                        stopped_at = datetime.fromisoformat(stopped.replace('Z', '+00:00')).timestamp()
                        began_at = datetime.fromisoformat(latest_start).timestamp() if latest_start else 0
                        hidden_paused = stopped_at > time.time() - 2 * 86400 and began_at < int(stopped_at)
                    except (ValueError, TypeError, AttributeError): pass
                tags = str(tags or "")[:65536]
                toks = [x.strip() for x in tags.split(",") if x.strip()]
                def pref(prefix: str) -> str:
                    return next((x[len(prefix):] for x in toks if x.startswith(prefix)), "")
                process = pref("task-process:") or ("system-analysis" if pref("task-stage:") or "task-waiting" in toks else "")
                stage = pref("task-stage:")
                history = []
                for token in toks:
                    if token.startswith("task-stage-log:") and "@" in token:
                        stage_id, at = token[len("task-stage-log:"):].rsplit("@", 1)
                        if len(at) <= 64: history.append({"stage": stage_id, "at": at})
                p = processes.get(process, {})
                stage_map = {s.get("id"): s.get("title") for s in p.get("stages", []) if isinstance(s, dict)}
                stage_label = stage_map.get(stage) or (_BUILTIN.get(stage) if process == "system-analysis" else None) or stage
                for entry in history:
                    entry["stageLabel"] = stage_map.get(entry["stage"]) or (_BUILTIN.get(entry["stage"]) if process == "system-analysis" else None) or entry["stage"]
                result.append({"taskKey": "cicada-" + hashlib.sha256(str(path).encode()).hexdigest()[:16] + "-" + str(ident), "sourceId": str(ident), "title": str(title or "")[:500], "date": date, "plannedTime": tm, "completed": bool(completed), "isActive": bool(active), "isPaused": bool(worked_today and not active and not hidden_paused), "actualMinutes": int(seconds or 0) // 60, "process": process, "processLabel": p.get("title") or ("Системный анализ" if process == "system-analysis" else process), "stage": stage, "stageLabel": stage_label, "waiting": "task-waiting" in toks, "stageHistory": history[-200:], "lastUpdatedAt": updated})
            return result[:500], len(result) > 500
        finally:
            con.close()
