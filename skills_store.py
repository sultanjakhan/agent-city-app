"""Safe, non-executing storage for editing existing Agent Skills.

The store only handles ``SKILL.md`` files below an explicitly supplied skills
root.  It never imports, executes, downloads, or otherwise interprets a skill.
History is kept in the supplied data directory, outside the skills tree.
"""
from __future__ import annotations

import difflib
import hashlib
import os
from pathlib import Path
import re
import tempfile
import threading
from datetime import datetime, timezone
from typing import Any


class SkillsStoreError(Exception):
    """Base error for safe skills storage operations."""


class SkillNotFound(SkillsStoreError):
    pass


class SkillPathError(SkillsStoreError):
    pass


class SkillValidationError(SkillsStoreError):
    pass


class RevisionConflict(SkillsStoreError):
    """The caller tried to write against an old revision."""


_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_FRONTMATTER = re.compile(r"^---[ \t]*\r?\n(?P<body>.*?)(?:\r?\n)---[ \t]*(?:\r?\n|$)", re.DOTALL)
_FIELD = re.compile(r"^(name|description)[ \t]*:[ \t]*(.*)$")
_REPARSE_POINT = 0x400


def _is_reparse(path: Path) -> bool:
    try:
        return path.is_symlink() or bool(path.stat().st_file_attributes & _REPARSE_POINT)
    except (AttributeError, OSError):
        return path.is_symlink()


def _revision(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _scalar(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        if value[0] == '"':
            value = value[1:-1].replace('\\"', '"').replace('\\n', '\n')
        else:
            value = value[1:-1].replace("''", "'")
    return value.strip()


def _metadata(content: str) -> tuple[str, str]:
    match = _FRONTMATTER.match(content)
    if not match:
        raise SkillValidationError("SKILL.md must start with YAML frontmatter")
    values: dict[str, str] = {}
    for line in match.group("body").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        field = _FIELD.match(line)
        if not field:
            raise SkillValidationError("frontmatter only supports scalar name and description")
        if field.group(1) in values:
            raise SkillValidationError(f"duplicate frontmatter field: {field.group(1)}")
        if field.group(2).strip() in {"|", ">", "|-", ">-", "|+", ">+"}:
            raise SkillValidationError("folded frontmatter values are not supported")
        values[field.group(1)] = _scalar(field.group(2))
    for key in ("name", "description"):
        if not values.get(key):
            raise SkillValidationError(f"frontmatter requires {key}")
    return values["name"], values["description"]


class SkillsStore:
    """Manage existing skills under one canonical, non-symlink root."""

    def __init__(self, skills_root: str | os.PathLike[str], data_dir: str | os.PathLike[str], *, max_size: int = 1024 * 1024):
        root = Path(skills_root)
        if _is_reparse(root) or not root.is_dir():
            raise SkillPathError("skills root must be a real directory")
        self.root = root.resolve()
        self.max_size = max_size
        if not isinstance(max_size, int) or max_size <= 0:
            raise ValueError("max_size must be positive")
        data = Path(data_dir)
        if data.exists() and _is_reparse(data):
            raise SkillPathError("data directory must not be a symlink")
        data_resolved = data.resolve()
        if data_resolved == self.root or self.root in data_resolved.parents:
            raise SkillPathError("history must be outside the skills root")
        self.data_dir = data_resolved
        self.history_root = self.data_dir / "skills-history"
        self._lock = threading.RLock()

    def _dir(self, name: str) -> Path:
        if not isinstance(name, str) or not _NAME.fullmatch(name) or name in {".git", ".."}:
            raise SkillPathError("invalid skill name")
        path = self.root / name
        if path.parent != self.root or path.is_symlink() or not path.is_dir():
            raise SkillNotFound(name)
        if _is_reparse(path):
            raise SkillPathError("skill directory must not be a symlink")
        return path

    def _file(self, name: str) -> Path:
        directory = self._dir(name)
        path = directory / "SKILL.md"
        if _is_reparse(path) or not path.is_file():
            raise SkillPathError("SKILL.md must be a regular file")
        return path

    def _read(self, name: str) -> dict[str, Any]:
        path = self._file(name)
        raw = path.read_bytes()
        if len(raw) > self.max_size:
            raise SkillValidationError("SKILL.md exceeds size limit")
        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SkillValidationError("SKILL.md must be UTF-8") from exc
        title, description = _metadata(content)
        return {"slug": name, "name": title, "description": description, "path": path.relative_to(self.root).as_posix(),
                "content": content, "revision": _revision(content), "history": self._history(name)}

    def _history_dir(self, name: str, *, create: bool = False) -> Path:
        path = self.history_root / name
        if _is_reparse(self.history_root):
            raise SkillPathError("history root must not be a symlink or junction")
        if create:
            self.history_root.mkdir(parents=True, exist_ok=True)
            if _is_reparse(self.history_root):
                raise SkillPathError("history root must not be a symlink or junction")
            path.mkdir(exist_ok=True)
        if path.exists() and (_is_reparse(path) or not path.is_dir()):
            raise SkillPathError("history directory is outside the data root")
        if path.resolve().parent != self.history_root.resolve():
            raise SkillPathError("history path escaped data root")
        return path

    def _history(self, name: str) -> list[dict[str, str]]:
        directory = self._history_dir(name)
        if not directory.exists():
            return []
        result = []
        for item in directory.iterdir():
            if _is_reparse(item) or not item.is_file() or not re.fullmatch(r"[0-9a-f]{64}\.md", item.name):
                continue
            result.append({"revision": item.stem, "modifiedAt": datetime.fromtimestamp(item.stat().st_mtime, timezone.utc).isoformat()})
        return sorted(result, key=lambda item: item["modifiedAt"], reverse=True)

    def list(self, query: str = "") -> list[dict[str, Any]]:
        if not isinstance(query, str):
            raise ValueError("query must be a string")
        result = []
        for directory in sorted(self.root.iterdir(), key=lambda item: item.name.lower()):
            if directory.name == ".git" or directory.is_symlink():
                continue
            if not directory.is_dir():
                continue
            try:
                item = self._read(directory.name)
            except SkillsStoreError:
                continue
            haystack = f"{item['name']} {item['description']} {item['path']}".casefold()
            if query.casefold() in haystack:
                result.append({k: item[k] for k in ("slug", "name", "description", "path", "revision")})
        return result

    def read(self, name: str) -> dict[str, Any]:
        return self._read(name)

    def preview(self, name: str, content: str, *, expected_revision: str | None = None) -> dict[str, Any]:
        current = self._read(name)
        if expected_revision is not None and expected_revision != current["revision"]:
            raise RevisionConflict("skill revision changed")
        self._validate_content(content)
        diff = "".join(difflib.unified_diff(current["content"].splitlines(keepends=True), content.splitlines(keepends=True),
                                             fromfile=current["path"], tofile=current["path"]))
        return {"path": current["path"], "revision": current["revision"], "nextRevision": _revision(content),
                "changed": content != current["content"], "diff": diff}

    def read_revision(self, name: str, revision: str) -> dict[str, str]:
        """Read one immutable history revision without changing the skill."""
        with self._lock:
            self._file(name)  # validate the current skill path as well
            if not re.fullmatch(r"[0-9a-f]{64}", revision):
                raise SkillPathError("invalid revision")
            history = self._history_dir(name) / f"{revision}.md"
            if _is_reparse(history) or not history.is_file():
                raise SkillNotFound("revision not found")
            raw = history.read_bytes()
            if len(raw) > self.max_size:
                raise SkillValidationError("history revision exceeds size limit")
            try:
                content = raw.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise SkillValidationError("history revision must be UTF-8") from exc
            if _revision(content) != revision:
                raise SkillValidationError("history revision hash mismatch")
            self._validate_content(content)
            return {"content": content, "revision": revision}

    def _validate_content(self, content: str) -> None:
        if not isinstance(content, str):
            raise SkillValidationError("content must be text")
        if len(content.encode("utf-8")) > self.max_size:
            raise SkillValidationError("SKILL.md exceeds size limit")
        _metadata(content)

    def _history_file(self, name: str, revision: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{64}", revision):
            raise SkillPathError("invalid revision")
        return self._history_dir(name, create=True) / f"{revision}.md"

    def _write(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".skill-", suffix=".tmp", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def save(self, name: str, content: str, *, expected_revision: str | None = None) -> dict[str, Any]:
        with self._lock:
            current = self._read(name)
            if expected_revision is not None and expected_revision != current["revision"]:
                raise RevisionConflict("skill revision changed")
            self._validate_content(content)
            if content == current["content"]:
                return current
            self._write(self._history_file(name, current["revision"]), current["content"])
            self._write(self._file(name), content)
            return self._read(name)

    def rollback(self, name: str, revision: str, *, expected_revision: str | None = None) -> dict[str, Any]:
        with self._lock:
            current = self._read(name)
            if expected_revision is not None and expected_revision != current["revision"]:
                raise RevisionConflict("skill revision changed")
            if not re.fullmatch(r"[0-9a-f]{64}", revision):
                raise SkillPathError("invalid revision")
            content = self.read_revision(name, revision)["content"]
            if content != current["content"]:
                self._write(self._history_file(name, current["revision"]), current["content"])
                self._write(self._file(name), content)
            return self._read(name)
