"""Read-only inventory of local Git repositories and worktrees.

The inventory never invokes Git and never follows a repository path outside its
configured workspace root.  HTTP callers must use the opaque ids returned by
``list`` before calling ``read``.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import threading
from typing import Iterable


class RepoInventoryError(Exception):
    pass


MAX_REPOS = 200
MAX_INSTRUCTION_BYTES = 256 * 1024
MAX_INSTRUCTION_FILES = 128
MAX_GIT_METADATA_BYTES = 4096
_EXCLUDED = {"node_modules", "archive", "archives"}


def _safe_resolved(path: Path, root: Path) -> Path | None:
    try:
        if path.is_symlink():
            return None
        resolved = path.resolve()
    except OSError:
        return None
    try:
        resolved.relative_to(root)
    except ValueError:
        return None
    return resolved


def _git_dir(repo: Path, root: Path) -> Path | None:
    marker = repo / ".git"
    try:
        if marker.is_dir() and not marker.is_symlink():
            candidate = _safe_resolved(marker, root)
            return candidate if candidate is not None else None
        if not marker.is_file() or marker.is_symlink():
            return None
        if marker.stat().st_size > MAX_GIT_METADATA_BYTES:
            return None
        with marker.open("rb") as stream:
            raw = stream.read(MAX_GIT_METADATA_BYTES + 1)
        if len(raw) > MAX_GIT_METADATA_BYTES:
            return None
        text = raw.decode("utf-8", errors="strict")
    except (OSError, UnicodeError, ValueError):
        return None
    first = text.splitlines()[0].strip() if text.splitlines() else ""
    if not first.lower().startswith("gitdir:"):
        return None
    raw = first[7:].strip()
    if not raw:
        return None
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = marker.parent / candidate
    try:
        candidate = candidate.resolve()
    except OSError:
        return None
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate if candidate.is_dir() and not candidate.is_symlink() else None


def _branch(git_dir: Path) -> str | None:
    try:
        marker = git_dir / "HEAD"
        if marker.stat().st_size > MAX_GIT_METADATA_BYTES:
            return None
        with marker.open("rb") as stream:
            raw = stream.read(MAX_GIT_METADATA_BYTES + 1)
        if len(raw) > MAX_GIT_METADATA_BYTES:
            return None
        head = raw.decode("ascii", errors="strict").strip()
    except (OSError, UnicodeError):
        return None
    if head.startswith("ref: "):
        ref = head[5:].strip()
        return ref.removeprefix("refs/heads/") or None
    return "(detached)" if head else None


def _metadata(repo: Path, root: Path) -> dict[str, object] | None:
    resolved = _safe_resolved(repo, root)
    git_dir = _git_dir(repo, root)
    if resolved is None or git_dir is None:
        return None
    rules = repo / ".claude" / "rules"
    instruction_paths: list[str] = []
    for candidate in (repo / "AGENTS.md", repo / "AGENTS.override.md", repo / "CLAUDE.md"):
        if candidate.is_file() and not candidate.is_symlink():
            instruction_paths.append(candidate.relative_to(repo).as_posix())
    try:
        if rules.is_dir() and not rules.is_symlink() and _safe_resolved(rules, repo) is not None:
            for candidate in sorted(rules.iterdir(), key=lambda p: p.name.casefold()):
                if len(instruction_paths) >= MAX_INSTRUCTION_FILES:
                    break
                if candidate.suffix.casefold() == ".md" and candidate.is_file() and not candidate.is_symlink():
                    instruction_paths.append(candidate.relative_to(repo).as_posix())
    except OSError:
        pass
    return {
        "id": "repo-" + hashlib.sha256(str(resolved).casefold().encode("utf-8")).hexdigest()[:24],
        "name": repo.name,
        "path": str(resolved),
        "branch": _branch(git_dir),
        "instructions": instruction_paths,
    }


class RepoInventory:
    def __init__(self, roots: Iterable[str | os.PathLike[str]] | None = None):
        if roots is None:
            from storage_config import load_storage
            default = load_storage().root
            roots = [default]
        parsed: list[Path] = []
        for raw in roots:
            if not isinstance(raw, (str, os.PathLike)):
                raise ValueError("roots must contain filesystem paths")
            path = Path(raw)
            if path.is_symlink() or not path.is_dir():
                continue
            resolved = path.resolve()
            if resolved not in parsed:
                parsed.append(resolved)
        if not parsed:
            raise ValueError("at least one readable root is required")
        self.roots = tuple(parsed)
        self._entries: dict[str, dict[str, object]] = {}
        self._lock = threading.RLock()

    def list(self) -> list[dict[str, object]]:
        with self._lock:
            entries: dict[str, dict[str, object]] = {}
            for root in self.roots:
                root_item = _metadata(root, root)
                if root_item is not None:
                    entries[str(root_item['id'])] = root_item
                try:
                    children = sorted(root.iterdir(), key=lambda p: p.name.casefold())
                except OSError:
                    continue
                for child in children:
                    if len(entries) >= MAX_REPOS:
                        break
                    if not child.is_dir() or child.is_symlink() or child.name.startswith(".") or child.name.casefold() in _EXCLUDED:
                        continue
                    item = _metadata(child, root)
                    if item is not None:
                        entries[str(item["id"])] = item
            self._entries = entries
            return [dict(item) for item in entries.values()]

    def read(self, opaque_id: str) -> dict[str, object]:
        if not isinstance(opaque_id, str):
            raise RepoInventoryError("repo id is required")
        with self._lock:
            item = self._entries.get(opaque_id)
            if item is None:
                raise RepoInventoryError("repo must be enumerated before reading")
            repo = Path(str(item["path"]))
            root = next((base for base in self.roots if _safe_resolved(repo, base) == repo), None)
            if root is None or _metadata(repo, root) is None:
                raise RepoInventoryError("repo is no longer readable")
            result = dict(item)
            contents: list[dict[str, str]] = []
            for relative in list(item.get("instructions", []))[:MAX_INSTRUCTION_FILES]:
                candidate = repo / str(relative)
                if candidate.is_symlink() or not candidate.is_file():
                    continue
                resolved_candidate = _safe_resolved(candidate, repo)
                if resolved_candidate is None or resolved_candidate != candidate:
                    continue
                try:
                    if candidate.stat().st_size > MAX_INSTRUCTION_BYTES:
                        continue
                    with candidate.open("rb") as stream:
                        raw = stream.read(MAX_INSTRUCTION_BYTES + 1)
                except OSError:
                    continue
                if len(raw) <= MAX_INSTRUCTION_BYTES:
                    contents.append({"path": str(relative), "content": raw.decode("utf-8", errors="replace")})
            result["instructionContents"] = contents
            return result


__all__ = ["RepoInventory", "RepoInventoryError", "MAX_REPOS", "MAX_INSTRUCTION_BYTES"]
