"""Bounded JSON library for reference projects.

This module stores metadata only. It never clones, imports, executes, or
connects to a project.  The file is re-read for every public read so the HTTP
layer can expose a current catalogue without a process restart.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import threading
from typing import Any
from urllib.parse import urlsplit

from storage_lock import write_lock


class ProjectLibraryError(Exception):
    """Base class for project-library errors."""


class ProjectValidationError(ProjectLibraryError, ValueError):
    pass


class ProjectRevisionConflict(ProjectLibraryError):
    pass


class ProjectPathError(ProjectLibraryError, ValueError):
    pass


_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_CATEGORIES = {"memory", "retrieval", "evals", "mcp", "other"}
_STATUS = {"reference", "candidate", "archived"}
_MAX_BYTES = 2 * 1024 * 1024
_MAX_RECORDS = 500
_MAX_TEXT = 4000
_MAX_USE_CASES = 20


def _safe_path(path: str | os.PathLike[str]) -> Path:
    if not isinstance(path, (str, os.PathLike)):
        raise ProjectPathError("path must be a filesystem path")
    candidate = Path(path)
    if candidate.name not in {"projects.json", "localprojects.json"}:
        raise ProjectPathError("library path must be projects.json or localprojects.json")
    if candidate.exists() and candidate.is_symlink():
        raise ProjectPathError("library file must not be a symlink")
    parent = candidate.parent.resolve()
    if parent.name == ".git" or ".git" in parent.parts:
        raise ProjectPathError("library cannot be stored under .git")
    return parent / candidate.name


def _text(value: Any, field: str, *, max_length: int = _MAX_TEXT) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > max_length:
        raise ProjectValidationError(f"{field} must be non-empty text")
    return value.strip()


def _bilingual(value: Any, field: str) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != {"ru", "en"}:
        raise ProjectValidationError(f"{field} must contain ru and en")
    return {"ru": _text(value["ru"], f"{field}.ru"), "en": _text(value["en"], f"{field}.en")}


def _https_url(value: Any, field: str, *, github: bool = False) -> str:
    value = _text(value, field, max_length=500)
    parts = urlsplit(value)
    if (parts.scheme, parts.username, parts.password, parts.query, parts.fragment) != ("https", None, None, "", ""):
        raise ProjectValidationError(f"{field} must be an https URL without credentials/query")
    if not parts.hostname:
        raise ProjectValidationError(f"{field} must have a hostname")
    if github and parts.hostname.casefold() != "github.com":
        raise ProjectValidationError(f"{field} must point to github.com")
    if github and len([part for part in parts.path.split("/") if part]) < 2:
        raise ProjectValidationError(f"{field} must point to a GitHub repository")
    return value.rstrip("/")


def validate_record(record: Any) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise ProjectValidationError("project must be an object")
    allowed = {"id", "name", "description", "useCases", "category", "repoUrl", "docsUrl", "status"}
    unknown = set(record) - allowed
    if unknown:
        raise ProjectValidationError(f"unknown project fields: {sorted(unknown)}")
    ident = record.get("id")
    if ident is None:
        name = record.get("name")
        if isinstance(name, str):
            ident = re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")[:64]
    if not isinstance(ident, str) or not _ID.fullmatch(ident):
        raise ProjectValidationError("id must be lowercase kebab-case")
    description = _bilingual(record.get("description"), "description")
    cases = record.get("useCases")
    if not isinstance(cases, list) or not cases or len(cases) > _MAX_USE_CASES:
        raise ProjectValidationError("useCases must be a non-empty bounded list")
    use_cases = [_bilingual(item, f"useCases[{index}]") for index, item in enumerate(cases)]
    category = record.get("category")
    if category not in _CATEGORIES:
        raise ProjectValidationError("invalid category")
    status = record.get("status", "reference")
    if status not in _STATUS:
        raise ProjectValidationError("invalid status")
    return {
        "id": ident,
        "name": _text(record.get("name"), "name", max_length=200),
        "description": description,
        "useCases": use_cases,
        "category": category,
        "repoUrl": _https_url(record.get("repoUrl"), "repoUrl", github=True),
        "docsUrl": _https_url(record.get("docsUrl"), "docsUrl"),
        "status": status,
    }


def _canonical(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


class ProjectLibrary:
    def __init__(self, path: str | os.PathLike[str], *, max_bytes: int = _MAX_BYTES,
                 seed_path: str | os.PathLike[str] | None = None):
        if not isinstance(max_bytes, int) or max_bytes <= 0 or max_bytes > _MAX_BYTES:
            raise ValueError("max_bytes must be between 1 and 2 MiB")
        self.path = _safe_path(path)
        self.seed_path = _safe_path(seed_path) if seed_path is not None else None
        if self.seed_path == self.path:
            self.seed_path = None
        self.max_bytes = max_bytes
        self._lock = threading.RLock()

    def _read_file(self, path: Path) -> tuple[dict[str, Any], str]:
        if not path.exists():
            raise FileNotFoundError(path)
        if path.is_symlink() or not path.is_file():
            raise ProjectPathError("library must be a regular file")
        try:
            size = path.stat().st_size
        except FileNotFoundError:
            raise
        if size > self.max_bytes:
            raise ProjectValidationError("library exceeds size limit")
        with path.open("rb") as stream:
            raw = stream.read(self.max_bytes + 1)
        if len(raw) > self.max_bytes:
            raise ProjectValidationError("library exceeds size limit")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProjectValidationError("library must be valid UTF-8 JSON") from exc
        if not isinstance(payload, dict) or payload.get("schemaVersion") != 1 or not isinstance(payload.get("projects"), list):
            raise ProjectValidationError("invalid library envelope")
        if len(payload["projects"]) > _MAX_RECORDS:
            raise ProjectValidationError("library has too many projects")
        normalized = [validate_record(item) for item in payload["projects"]]
        ids = [item["id"] for item in normalized]
        if len(ids) != len(set(ids)):
            raise ProjectValidationError("project ids must be unique")
        normalized_payload = {"schemaVersion": 1, "projects": normalized}
        return normalized_payload, hashlib.sha256(_canonical(normalized_payload)).hexdigest()

    def _read(self) -> tuple[dict[str, Any], str]:
        try:
            return self._read_file(self.path)
        except FileNotFoundError:
            if self.seed_path is not None:
                try:
                    return self._read_file(self.seed_path)
                except FileNotFoundError:
                    pass
            payload = {"schemaVersion": 1, "projects": []}
            return payload, hashlib.sha256(_canonical(payload)).hexdigest()

    def list(self) -> list[dict[str, Any]]:
        return self.snapshot()["projects"]

    def snapshot(self) -> dict[str, Any]:
        payload, revision = self._read()
        return {"schemaVersion": payload["schemaVersion"], "projects": copy.deepcopy(payload["projects"]),
                "revision": revision}

    def revision(self) -> str:
        _, revision = self._read()
        return revision

    def save(self, record: dict[str, Any], revision: str | None) -> dict[str, Any]:
        validated = validate_record(record)
        with self._lock, write_lock(self.path):
            payload, current_revision = self._read()
            if revision != current_revision:
                raise ProjectRevisionConflict("project library revision changed")
            projects = list(payload["projects"])
            index = next((i for i, item in enumerate(projects) if item["id"] == validated["id"]), None)
            if index is None:
                if len(projects) >= _MAX_RECORDS:
                    raise ProjectValidationError("library has too many projects")
                projects.append(validated)
            else:
                projects[index] = validated
            next_payload = {"schemaVersion": 1, "projects": projects}
            self._write(next_payload)
            return copy.deepcopy(validated)

    def _write(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        raw = _canonical(payload)
        if len(raw) > self.max_bytes:
            raise ProjectValidationError("library exceeds size limit")
        fd, temporary = tempfile.mkstemp(prefix=".projects-", suffix=".tmp", dir=str(self.path.parent))
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
