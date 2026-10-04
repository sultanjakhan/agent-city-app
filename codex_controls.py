"""Safe, bounded controls for Codex skill switches and global rules.

This module edits only explicitly selected config/rules files.  It never
returns their contents and does not execute skills or MCP servers.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import threading
import tomllib
from typing import Any


class CodexControlsError(Exception):
    pass


class RevisionConflict(CodexControlsError):
    pass


MAX_CONFIG = 2 * 1024 * 1024
MAX_RULES = 512 * 1024
START = "<!-- agent-city:managed-rules:start -->"
END = "<!-- agent-city:managed-rules:end -->"


def _hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _reject_redirects(path: Path) -> None:
    for candidate in (path, *path.parents):
        try:
            metadata = candidate.lstat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise CodexControlsError("unsafe file path") from exc
        if candidate.is_symlink() or getattr(metadata, "st_file_attributes", 0) & 0x400:
            raise CodexControlsError("unsafe file path")


def _read(path: Path, limit: int) -> bytes:
    _reject_redirects(path)
    try:
        if path.is_symlink() or (getattr(path.lstat(), "st_file_attributes", 0) & 0x400):
            raise CodexControlsError("unsafe file path")
        if not path.is_file() or path.stat().st_size > limit:
            raise CodexControlsError("file is unavailable or too large")
        with path.open("rb") as stream:
            raw = stream.read(limit + 1)
        if len(raw) > limit:
            raise CodexControlsError("file is unavailable or too large")
        return raw
    except OSError as exc:
        raise CodexControlsError("file is unavailable") from exc


def _atomic(path: Path, raw: bytes) -> None:
    _reject_redirects(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        try:
            os.unlink(name)
        except FileNotFoundError:
            pass


def _validate_toml(raw: bytes) -> dict:
    try:
        return tomllib.loads(raw.decode("utf-8"))
    except (UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise CodexControlsError("unsupported or malformed TOML") from exc


def _configured_rows(raw: bytes) -> list:
    parsed = _validate_toml(raw)
    skills = parsed.get('skills', {})
    if not isinstance(skills, dict) or not isinstance(skills.get('config', []), list):
        raise CodexControlsError('unsupported skill config layout')
    rows = skills.get('config', [])
    if any(not isinstance(row, dict) or not isinstance(row.get('path'), str) for row in rows):
        raise CodexControlsError('unsupported skill config layout')
    return rows


def _configured_target(path: str) -> Path:
    target = Path(path)
    if not target.is_absolute():
        raise CodexControlsError('relative configured skill path is unsupported')
    if target.name.casefold() != 'skill.md':
        target /= 'SKILL.md'
    return target.resolve()


def _backup(path: Path, raw: bytes) -> None:
    backup = path.with_name(path.name + "." + _hash(raw)[:12] + ".bak")
    _atomic(backup, raw)


def _resolved_skill(path: str | os.PathLike[str]) -> tuple[Path, Path]:
    candidate = Path(os.path.normpath(os.fspath(path)))
    if candidate.name.casefold() != "skill.md":
        candidate = candidate / "SKILL.md"
    try:
        return candidate, candidate.resolve(strict=True)
    except OSError as exc:
        raise CodexControlsError("skill target is unavailable") from exc


def _inventory_row(inventory: Any, skill_id: str) -> dict[str, Any]:
    rows = inventory.list()
    for row in rows:
        if row.get("id") == skill_id:
            return row
    raise CodexControlsError("skill must be enumerated before changing")


def _toggleable(row: dict[str, Any]) -> bool:
    if row.get("origin") not in {"codex", "agents"}:
        return False
    path = str(row.get("path", "")).replace("\\", "/").casefold()
    return "/.system/" not in path and not path.endswith("/.system")


def _skill_blocks(text: str) -> list[tuple[int, int, str | None, bool | None]]:
    marks = list(re.finditer(r"(?m)^\[\[skills\.config\]\][ \t]*(?:\r?\n|$)", text))
    tables = list(re.finditer(r"(?m)^\[\[?[^\r\n\]]+\]\]?[ \t]*(?:\r?\n|$)", text))
    result = []
    for mark in marks:
        next_tables = [item.start() for item in tables if item.start() > mark.start()]
        end = min(next_tables) if next_tables else len(text)
        body = text[mark.start():end]
        try:
            parsed = tomllib.loads(body)
            item = parsed.get("skills", {}).get("config", [{}])[0]
            path = item.get("path") if isinstance(item, dict) and isinstance(item.get("path"), str) else None
            enabled = item.get("enabled") if isinstance(item, dict) and isinstance(item.get("enabled"), bool) else None
        except (tomllib.TOMLDecodeError, AttributeError, IndexError):
            path, enabled = None, None
        result.append((mark.start(), end, path, enabled))
    return result


class CodexControls:
    def __init__(self, codex_home: str | os.PathLike[str], data_dir: str | os.PathLike[str],
                 inventory: Any, bridge_content: str):
        self.codex_home = Path(codex_home).absolute()
        self.data_dir = Path(data_dir).absolute()
        self.inventory = inventory
        if not isinstance(bridge_content, str) or len(bridge_content.encode("utf-8")) > MAX_RULES:
            raise ValueError("bridge content is invalid")
        self.bridge_content = bridge_content
        self.config_path = self.codex_home / "config.toml"
        self._lock = threading.RLock()

    def config_status(self) -> dict[str, Any]:
        with self._lock:
            raw = _read(self.config_path, MAX_CONFIG) if self.config_path.exists() else b""
        configured_rows = _configured_rows(raw)
        rows = self.inventory.list()
        out = []
        for row in rows:
            if not _toggleable(row):
                continue
            try:
                _, target = _resolved_skill(str(row.get("path", "")))
            except CodexControlsError:
                continue
            matches = []
            for configured_row in configured_rows:
                try:
                    configured_target = _configured_target(configured_row['path'])
                except CodexControlsError:
                    continue
                if configured_target == target:
                    matches.append(configured_row.get('enabled', True))
            state = "unknown" if len(matches) > 1 or any(not isinstance(v, bool) for v in matches) else ("enabled" if not matches or any(matches) else "disabled")
            out.append({"id": row.get("id"), "status": state,
                        "canToggle": _toggleable(row),
                        "path": row.get("path")})
        return {"revision": _hash(raw), "skills": out}

    def set_enabled(self, skill_id: str, enabled: bool, revision: str) -> dict[str, Any]:
        with self._lock:
            if not isinstance(enabled, bool) or not isinstance(revision, str):
                raise CodexControlsError("invalid request")
            row = _inventory_row(self.inventory, skill_id)
            if not _toggleable(row):
                raise CodexControlsError("skill is not user-toggleable")
            _, target = _resolved_skill(str(row.get("path", "")))
            raw = _read(self.config_path, MAX_CONFIG) if self.config_path.exists() else b""
            if _hash(raw) != revision:
                raise RevisionConflict("config changed")
            configured_rows = _configured_rows(raw)
            text = raw.decode("utf-8")
            blocks = _skill_blocks(text)
            # Refuse unfamiliar layouts instead of accidentally editing a different table or string.
            if len(blocks) != len(configured_rows) or any(block[2] != row['path'] for block, row in zip(blocks, configured_rows)):
                raise CodexControlsError('unsupported skill config layout')
            aliases: set[str] = set()
            raw_aliases: set[str] = set()
            for _, _, configured, _ in blocks:
                if configured is None:
                    continue
                if configured in raw_aliases:
                    raise CodexControlsError("duplicate skill configuration")
                raw_aliases.add(configured)
                canonical = _configured_target(configured)
                key = os.path.normcase(os.path.normpath(str(canonical)))
                if key in aliases:
                    raise CodexControlsError("duplicate skill configuration")
                aliases.add(key)
            matches = []
            for block in blocks:
                configured = block[2]
                if configured is None:
                    continue
                configured_target = _configured_target(configured)
                if configured_target == target:
                    matches.append(block)
            if len(matches) > 1:
                raise CodexControlsError("duplicate skill configuration")
            if matches:
                start, end, _, _ = matches[0]
                block_text = text[start:end]
                new_block, count = re.subn(r"(?mi)^(\s*enabled[ \t]*=[ \t]*)(true|false)([ \t]*(?:#.*)?\r?$)",
                                           lambda m: m.group(1) + str(enabled).lower() + m.group(3), block_text, count=1)
                if count != 1:
                    raise CodexControlsError("unsupported skill config layout")
                new_text = text[:start] + new_block + text[end:]
            else:
                suffix = "" if not text or text.endswith(("\n", "\r")) else "\n"
                config_path = Path(str(row.get("path"))).as_posix()
                new_text = text + suffix + "[[skills.config]]\npath = " + json.dumps(config_path, ensure_ascii=False) + "\nenabled = " + str(enabled).lower() + "\n"
            new_raw = new_text.encode("utf-8")
            if len(new_raw) > MAX_CONFIG:
                raise CodexControlsError('config exceeds size limit')
            _validate_toml(new_raw)
            _backup(self.config_path, raw)
            _atomic(self.config_path, new_raw)
            return {"revision": _hash(new_raw), "skillId": skill_id, "enabled": enabled}

    def bridge_status(self) -> dict[str, Any]:
        with self._lock:
            override = self.codex_home / "AGENTS.override.md"
        normal = self.codex_home / "AGENTS.md"
        target = override if override.exists() and _read(override, MAX_RULES).strip() else normal
        raw = _read(target, MAX_RULES) if target.exists() else b""
        text = raw.decode("utf-8")
        starts, ends = text.count(START), text.count(END)
        malformed = starts != ends or starts > 1 or ends > 1 or (END in text and START in text and text.index(END) < text.index(START))
        newline = "\r\n" if "\r\n" in text else "\n"
        desired = START + newline + self.bridge_content.rstrip("\r\n") + newline + END
        existing = ""
        if starts == 1 and ends == 1 and not malformed:
            existing = text[text.index(START):text.index(END) + len(END)]
        return {"path": str(target), "revision": _hash(raw), "hasBlock": starts == 1 and ends == 1,
                "connected": bool(existing.replace("\r\n", "\n") == desired.replace("\r\n", "\n")), "malformed": malformed}

    def connect_bridge(self, expected_revision: str) -> dict[str, Any]:
        with self._lock:
            status = self.bridge_status()
            if status["revision"] != expected_revision:
                raise RevisionConflict("rules changed")
            if status["malformed"]:
                raise CodexControlsError("malformed managed rules block")
            path = Path(status["path"])
            raw = _read(path, MAX_RULES) if path.exists() else b""
            text = raw.decode("utf-8")
            block = START + "\n" + self.bridge_content.rstrip("\r\n") + "\n" + END
            if START in text:
                start, end = text.index(START), text.index(END, text.index(START)) + len(END)
                new_text = text[:start] + block + text[end:]
            else:
                sep = "" if not text or text.endswith(("\n", "\r")) else "\n"
                new_text = text + sep + block + "\n"
            new_raw = new_text.encode("utf-8")
            if len(new_raw) > MAX_RULES:
                raise CodexControlsError('rules exceed size limit')
            _backup(path, raw) if path.exists() else None
            _atomic(path, new_raw)
            return {"path": str(path), "revision": _hash(new_raw), "changed": new_raw != raw}


__all__ = ["CodexControls", "CodexControlsError", "RevisionConflict"]
