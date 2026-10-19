"""Read-only inventory of skills from a small set of trusted local roots.

This module never writes, imports, or executes skill content.  Roots are fixed
by the caller (the default list is limited to Agent City, user skill roots,
and known plugin cache namespaces); HTTP input must never become a root.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import threading
from datetime import datetime, timezone
from text_reader import read_text, slice_text
from typing import Iterable


class SkillInventoryError(Exception):
    pass


_REPARSE = 0x400
_FIELD = re.compile(r"^([A-Za-z][A-Za-z0-9_-]*)[ \t]*:[ \t]*(.*)$")
_BLOCK = {"|", ">", "|-", ">-", "|+", ">+"}


def _reparse(path: Path) -> bool:
    try:
        return path.is_symlink() or bool(path.lstat().st_file_attributes & _REPARSE)
    except (AttributeError, OSError):
        return path.is_symlink()


def _scalar(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        value = value[1:-1]
    return value.strip()


def _metadata(content: str) -> tuple[str, str]:
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        raise SkillInventoryError("missing frontmatter")
    values: dict[str, str] = {}
    closing = None
    index = 1
    while index < len(lines):
        line = lines[index]
        if line.strip() == "---":
            closing = index
            break
        if not line.strip() or line.lstrip().startswith("#") or line[:1].isspace():
            index += 1
            continue
        match = _FIELD.match(line)
        if not match:
            index += 1
            continue
        key, value = match.group(1), match.group(2).strip()
        if key in values:
            raise SkillInventoryError("duplicate frontmatter")
        if value in _BLOCK:
            block = []
            index += 1
            while index < len(lines) and (not lines[index].strip() or lines[index][:1].isspace()):
                block.append(lines[index].strip())
                index += 1
            if key == "description":
                values[key] = "\n".join(block).strip()
            continue
        if key in {"name", "description"}:
            values[key] = _scalar(value)
        index += 1
    if closing is None or not values.get("name") or not values.get("description"):
        raise SkillInventoryError("incomplete frontmatter")
    return values["name"], values["description"]


def default_roots(worktree_root: str | os.PathLike[str] | None = None) -> list[tuple[str, Path]]:
    home = Path.home()
    roots: list[tuple[str, Path]] = [
        ("worktree", Path(worktree_root) if worktree_root is not None else __import__("storage_config").load_storage().skills),
        ("codex", home / ".codex" / "skills"),
        ("codex", home / ".codex" / "skills" / ".system"),
        ("agents", home / ".agents" / "skills"),
    ]
    # Bounded discovery inside the already configured plugin cache, independent
    # of vendor names. No reparse node is followed at any level.
    cache = home / ".codex" / "plugins" / "cache"
    def children(path, limit):
        try:
            return sorted((p for p in path.iterdir() if p.is_dir() and not p.name.startswith('.') and not _reparse(p)),
                          key=lambda p: p.name.casefold(), reverse=True)[:limit]
        except OSError:
            return []
    if not cache.is_dir() or _reparse(cache):
        return roots
    for namespace_root in children(cache, 32):
        if not namespace_root.is_dir() or _reparse(namespace_root):
            continue
        for plugin in children(namespace_root, 64):
            if not plugin.is_dir() or _reparse(plugin):
                continue
            for version in children(plugin, 8):
                candidate = version / "skills"
                if version.is_dir() and not _reparse(version) and candidate.is_dir() and not _reparse(candidate):
                    roots.append((f"plugin:{plugin.name}", candidate))
                    if len(roots) >= 256:
                        return roots
    return roots


class SkillInventory:
    """Enumerate and read skills from caller-supplied trusted roots."""

    def __init__(self, roots: Iterable[tuple[str, str | os.PathLike[str]] | dict[str, object]] | None = None,
                 *, worktree_root: str | os.PathLike[str] | None = None,
                 max_size: int = 1024 * 1024, max_skills: int = 2000):
        if not isinstance(max_size, int) or max_size <= 0 or not isinstance(max_skills, int) or max_skills <= 0:
            raise ValueError("limits must be positive integers")
        self.max_size, self.max_skills = max_size, max_skills
        self._default_mode = roots is None
        self._worktree_root = worktree_root
        self._roots: list[tuple[str, Path]] = []
        self._configure(list(roots) if roots is not None else default_roots(worktree_root))
        self._entries: dict[str, dict[str, object]] = {}
        self._lock = threading.RLock()

    def _configure(self, raw_roots: list[tuple[str, str | os.PathLike[str]] | dict[str, object]]) -> None:
        roots: list[tuple[str, Path]] = []
        for item in raw_roots:
            if isinstance(item, dict):
                origin, path = item.get("origin"), item.get("path")
            else:
                origin, path = item
            if not isinstance(origin, str) or not origin or not isinstance(path, (str, os.PathLike)):
                continue
            candidate = Path(path)
            if candidate.is_dir():
                roots.append((origin, candidate.absolute()))
        self._roots = roots

    def _candidate_allowed(self, path: Path, trusted_targets: tuple[Path, ...], origin: str) -> bool:
        if _reparse(path):
            # A user-installed skill is often a directory junction to its source
            # repository. Trust this direct child only, not arbitrary nested links.
            if origin in {'codex', 'agents'}:
                return True
            try:
                resolved = path.resolve()
            except OSError:
                return False
            return any(resolved == root or root in resolved.parents for root in trusted_targets)
        return True

    def list(self, query: str = "") -> list[dict[str, object]]:
        if not isinstance(query, str):
            raise ValueError("query must be a string")
        with self._lock:
            if self._default_mode:
                self._configure(default_roots(self._worktree_root))
            trusted_targets = tuple(path.resolve() for _, path in self._roots)
            seen: set[Path] = set()
            entries: dict[str, dict[str, object]] = {}
            for origin, root in self._roots:
                if not root.is_dir():
                    continue
                for folder in sorted(root.iterdir(), key=lambda item: item.name.casefold()):
                    if folder.name == ".git" or not folder.is_dir() or not self._candidate_allowed(folder, trusted_targets, origin):
                        continue
                    document = folder / "SKILL.md"
                    if _reparse(document) or not document.is_file():
                        continue
                    try:
                        resolved = document.resolve()
                        if resolved in seen:
                            continue
                        if document.stat().st_size > self.max_size:
                            continue
                        with document.open("rb") as stream:
                            raw = stream.read(self.max_size + 1)
                        if len(raw) > self.max_size:
                            continue
                        content = raw.decode("utf-8")
                        name, description = _metadata(content)
                    except (OSError, UnicodeError, SkillInventoryError):
                        continue
                    seen.add(resolved)
                    ident = "skill-" + hashlib.sha256(str(resolved).encode("utf-8")).hexdigest()[:24]
                    entries[ident] = {"id": ident, "slug": folder.name, "name": name,
                                      "description": description, "origin": origin, "source": origin,
                                      "status": "cached" if origin.startswith("plugin:") else "workspace" if origin == "worktree" else "installed",
                                      "path": str(document.absolute()), "_resolvedPath": str(resolved), "editable": False}
                    if len(entries) >= self.max_skills:
                        break
                if len(entries) >= self.max_skills:
                    break
            needle = query.casefold()
            result = [item for item in entries.values()
                      if not needle or needle in f"{item['slug']} {item['name']} {item['description']} {item['origin']}".casefold()]
            self._entries = entries
            return [{key: value for key, value in item.items() if not key.startswith('_')} for item in result]

    def enumerate_document(self, path: Path) -> str:
        """Adopt a file already discovered under this inventory's fixed roots."""
        path = Path(path)
        resolved = path.resolve(strict=True)
        root = next((r.resolve() for _, r in self._roots if resolved.is_relative_to(r.resolve())), None)
        if root is None or path.name != 'SKILL.md' or _reparse(path):
            raise SkillInventoryError('skill is outside configured roots')
        current = root
        for part in resolved.relative_to(root).parts:
            current /= part
            if _reparse(current):
                raise SkillInventoryError('skill alias denied')
        _, content, _ = read_text(path, root, self.max_size)
        name, description = _metadata(content)
        ident = 'skill-' + hashlib.sha256(str(resolved).encode('utf-8')).hexdigest()[:24]
        with self._lock:
            self._entries[ident] = {'id': ident, 'name': name, 'slug': path.parent.name, 'description': description,
                                   'origin': self._roots[0][0], 'path': str(path.absolute()), '_resolvedPath': str(resolved), 'editable': False}
        return ident

    def read(self, opaque_id: str, *, start_line=1, end_line=None, max_bytes=None, revision=None, byte_offset=0) -> dict[str, object]:
        with self._lock:
            entry = self._entries.get(opaque_id)
            if entry is None:
                raise SkillInventoryError("skill must be enumerated before reading")
            try:
                path = Path(str(entry["path"]))
                resolved = path.resolve()
                trusted = tuple(root.resolve() for _, root in self._roots)
                installed_link = any(origin in {'codex', 'agents'} and path.parent.parent == root
                                     for origin, root in self._roots)
                if (_reparse(path) or not path.is_file() or resolved != Path(str(entry["_resolvedPath"]))
                        or not (installed_link or any(resolved == root or root in resolved.parents for root in trusted))):
                    raise SkillInventoryError("skill is no longer readable")
                if path.stat().st_size > self.max_size:
                    raise SkillInventoryError("skill is no longer readable")
                raw, content, stat = read_text(path, resolved.parent, self.max_size)
                _metadata(content)
                current_revision = hashlib.sha256(raw).hexdigest()
                if revision is not None and revision != current_revision:
                    raise SkillInventoryError('skill changed; revision=' + current_revision)
                result = {key: value for key, value in entry.items() if not key.startswith("_")}
                result.update(revision=current_revision, hash=current_revision, size=stat.st_size, mtimeNs=stat.st_mtime_ns,
                              readAt=datetime.now(timezone.utc).isoformat())
                if max_bytes is not None or end_line is not None:
                    if (type(start_line) is not int or start_line < 1 or type(end_line) is not int
                            or not start_line <= end_line < start_line + 200 or type(max_bytes) is not int or not 1 <= max_bytes <= 32768):
                        raise SkillInventoryError('invalid range')
                    if type(byte_offset) is not int or byte_offset < 0:
                        raise SkillInventoryError('invalid byte offset')
                    result.update(slice_text(content, start_line, end_line, max_bytes, byte_offset))
                    content = result['content']
                result['content'] = content
                return result
            except SkillInventoryError:
                raise
            except (OSError, UnicodeError, ValueError) as exc:
                raise SkillInventoryError("skill is no longer readable") from exc


__all__ = ["SkillInventory", "SkillInventoryError", "default_roots"]
