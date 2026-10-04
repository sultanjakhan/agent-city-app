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
    # Plugin cache is a known, bounded namespace.  Only its versioned `skills`
    # directories are accepted; no general filesystem search is performed.
    cache = home / ".codex" / "plugins" / "cache"
    for namespace in ("openai-bundled", "openai-curated-remote", "openai-primary-runtime"):
        namespace_root = cache / namespace
        if not namespace_root.is_dir() or _reparse(namespace_root):
            continue
        for plugin in namespace_root.iterdir():
            if not plugin.is_dir() or _reparse(plugin):
                continue
            for version in plugin.iterdir():
                candidate = version / "skills"
                if version.is_dir() and not _reparse(version) and candidate.is_dir() and not _reparse(candidate):
                    roots.append((f"plugin:{plugin.name}", candidate))
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

    def read(self, opaque_id: str) -> dict[str, object]:
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
                with path.open("rb") as stream:
                    raw = stream.read(self.max_size + 1)
                if len(raw) > self.max_size:
                    raise SkillInventoryError("skill is no longer readable")
                content = raw.decode("utf-8")
                _metadata(content)
                result = {key: value for key, value in entry.items() if not key.startswith("_")}
                result["content"] = content
                return result
            except SkillInventoryError:
                raise
            except (OSError, UnicodeError, ValueError) as exc:
                raise SkillInventoryError("skill is no longer readable") from exc


__all__ = ["SkillInventory", "SkillInventoryError", "default_roots"]
