"""Local rule and repository-extension profile storage.

Rules are copied into Agent City's data directory.  Repository files are only
read through the supplied inventory and are never modified or executed.
"""
from __future__ import annotations
from project_policy import validate_policy, PolicyValidationError

import copy
import difflib
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import threading
from typing import Any


MAX_RULE_BYTES = 128 * 1024
MAX_EXTENSIONS = 100
MAX_PROFILE_BYTES = 1024 * 1024
_REPO_ID = re.compile(r"^repo-[0-9a-f]{24}$")


class RuleStoreError(Exception):
    pass


class RuleRevisionConflict(RuleStoreError):
    pass


class RuleValidationError(RuleStoreError, ValueError):
    pass


def _revision(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _atomic_text(path: Path, content: str) -> None:
    raw = content.encode("utf-8")
    if len(raw) > MAX_RULE_BYTES:
        raise RuleValidationError("rules exceed size limit")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".rule-", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _atomic_json(path: Path, value: object) -> None:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    if len(text.encode("utf-8")) > MAX_PROFILE_BYTES:
        raise RuleValidationError("profiles exceed size limit")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".profile-", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _assert_outside_repositories(directory: Path, inventory: Any) -> None:
    try:
        repositories = inventory.list()
    except Exception as exc:
        raise RuleValidationError("repository inventory is unavailable") from exc
    for item in repositories:
        path = item.get("path") if isinstance(item, dict) else None
        if not isinstance(path, str):
            continue
        repo = Path(path).resolve()
        try:
            directory.relative_to(repo)
        except ValueError:
            continue
        raise RuleValidationError("rule data must be outside repositories")


class RulesStore:
    def __init__(self, directory: str | os.PathLike[str], repo_inventory: Any):
        self.directory = Path(directory).resolve()
        self.repo_inventory = repo_inventory
        _assert_outside_repositories(self.directory, repo_inventory)
        self._lock = threading.RLock()
        self.global_path = self.directory / "global-rules.md"
        self.repo_dir = self.directory / "repository-rules"
        self.history_dir = self.directory / "history"

    def _scope(self, scope: str) -> tuple[str, Path]:
        if scope == "global":
            return scope, self.global_path
        if not isinstance(scope, str) or not _REPO_ID.fullmatch(scope):
            raise RuleValidationError("invalid repository scope")
        try:
            info = self.repo_inventory.read(scope)
        except Exception as exc:
            raise RuleValidationError("repository must be enumerated before use") from exc
        if not isinstance(info, dict) or not isinstance(info.get("path"), str):
            raise RuleValidationError("invalid repository inventory record")
        return scope, self.repo_dir / f"{scope}.md"

    def _read_path(self, path: Path) -> tuple[str, str]:
        if not path.exists():
            return "", _revision("")
        if path.is_symlink() or not path.is_file():
            raise RuleValidationError("rule path must be a regular file")
        if path.stat().st_size > MAX_RULE_BYTES:
            raise RuleValidationError("rules exceed size limit")
        raw = path.read_bytes()
        if len(raw) > MAX_RULE_BYTES:
            raise RuleValidationError("rules exceed size limit")
        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise RuleValidationError("rules must be UTF-8") from exc
        return content, _revision(content)

    def read(self, scope: str = "global") -> dict[str, str]:
        name, path = self._scope(scope)
        content, revision = self._read_path(path)
        return {"scope": name, "path": str(path), "content": content, "revision": revision}

    def preview(self, scope: str, content: str, revision: str) -> dict[str, object]:
        with self._lock:
            current = self.read(scope)
            if revision != current["revision"]:
                raise RuleRevisionConflict("rules changed")
            if not isinstance(content, str):
                raise RuleValidationError("content must be text")
            if len(content.encode("utf-8")) > MAX_RULE_BYTES:
                raise RuleValidationError("rules exceed size limit")
            diff = "".join(difflib.unified_diff(
                current["content"].splitlines(keepends=True), content.splitlines(keepends=True),
                fromfile=f"{scope}:current", tofile=f"{scope}:draft"))
            return {"scope": scope, "revision": current["revision"], "content": content, "changed": content != current["content"], "diff": diff}

    def save(self, scope: str, content: str, revision: str) -> dict[str, str]:
        with self._lock:
            current = self.read(scope)
            if revision != current["revision"]:
                raise RuleRevisionConflict("rules changed")
            if not isinstance(content, str):
                raise RuleValidationError("content must be text")
            raw = content.encode("utf-8")
            if len(raw) > MAX_RULE_BYTES:
                raise RuleValidationError("rules exceed size limit")
            _, path = self._scope(scope)
            if path.exists():
                old = path.read_bytes()
                backup = self.history_dir / f"{scope}-{current['revision']}.md"
                if not backup.exists():
                    _atomic_text(backup, old.decode("utf-8"))
            _atomic_text(path, content)
            return self.read(scope)

    def repository_rules(self, repo_id: str | None = None) -> list[dict[str, str]]:
        result = [self.read("global")]
        if repo_id is not None:
            result.append(self.read(repo_id))
        return result

    def render_bundle(self, repo_id: str | None = None) -> str:
        sections = []
        for item in self.repository_rules(repo_id):
            sections.append(f"[{item['scope']}]\n{item['content']}")
        return "\n\n".join(sections)


class RepoProfiles:
    def __init__(self, directory: str | os.PathLike[str], repo_inventory: Any, extension_library: Any):
        self.directory = Path(directory).resolve()
        self.path = self.directory / "repository-profiles.json"
        self.repo_inventory = repo_inventory
        self.extension_library = extension_library
        _assert_outside_repositories(self.directory, repo_inventory)
        self._lock = threading.RLock()

    def _validate_repo(self, repo_id: str) -> None:
        if not isinstance(repo_id, str) or not _REPO_ID.fullmatch(repo_id):
            raise RuleValidationError("invalid repository id")
        try:
            self.repo_inventory.read(repo_id)
        except Exception as exc:
            raise RuleValidationError("repository must be enumerated before use") from exc

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"schemaVersion": 1, "profiles": {}}
        if self.path.is_symlink() or not self.path.is_file():
            raise RuleValidationError("profile path must be a regular file")
        try:
            if self.path.stat().st_size > MAX_PROFILE_BYTES:
                raise RuleValidationError("profiles exceed size limit")
            with self.path.open("rb") as stream:
                raw = stream.read(MAX_PROFILE_BYTES + 1)
            if len(raw) > MAX_PROFILE_BYTES:
                raise RuleValidationError("profiles exceed size limit")
            value = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RuleValidationError("invalid profiles file") from exc
        if not isinstance(value, dict) or value.get("schemaVersion") != 1 or not isinstance(value.get("profiles"), dict):
            raise RuleValidationError("invalid profiles envelope")
        policies = value.get("policies", {})
        if not isinstance(policies, dict):
            raise RuleValidationError("invalid policies map")
        try:
            for policy in policies.values():
                validate_policy(policy)
        except PolicyValidationError as exc:
            raise RuleValidationError(str(exc)) from exc
        return value

    def _snapshot(self, payload: dict[str, Any]) -> dict[str, Any]:
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return {"schemaVersion": 1, "profiles": copy.deepcopy(payload["profiles"]), "policies": copy.deepcopy(payload.get("policies", {})), "revision": hashlib.sha256(canonical).hexdigest()}

    def read(self, repo_id: str) -> dict[str, Any]:
        with self._lock:
            self._validate_repo(repo_id)
            payload = self._read()
            return {"policy": copy.deepcopy(payload.get("policies", {}).get(repo_id)), "repoId": repo_id, "extensionIds": list(payload["profiles"].get(repo_id, [])), "revision": self._snapshot(payload)["revision"]}

    def save(self, repo_id: str, extension_ids: list[str], revision: str, policy: Any = None) -> dict[str, Any]:
        with self._lock:
            self._validate_repo(repo_id)
            if not isinstance(extension_ids, list) or len(extension_ids) > MAX_EXTENSIONS or any(not isinstance(item, str) for item in extension_ids):
                raise RuleValidationError("invalid extension selection")
            allowed = {item.get("id") for item in self.extension_library.list() if isinstance(item, dict) and isinstance(item.get("id"), str)}
            if any(item not in allowed for item in extension_ids) or len(set(extension_ids)) != len(extension_ids):
                raise RuleValidationError("extension is not in the allowlist")
            payload = self._read()
            current = self._snapshot(payload)["revision"]
            if revision != current:
                raise RuleRevisionConflict("profile changed")
            if policy is not None:
                try:
                    normalized = validate_policy(policy)
                except PolicyValidationError as exc:
                    raise RuleValidationError(str(exc)) from exc
                payload.setdefault("policies", {})[repo_id] = normalized
            payload["profiles"][repo_id] = list(extension_ids)
            _atomic_json(self.path, payload)
            return self.read(repo_id)


__all__ = ["RulesStore", "RepoProfiles", "RuleStoreError", "RuleRevisionConflict", "RuleValidationError", "MAX_RULE_BYTES", "MAX_EXTENSIONS", "MAX_PROFILE_BYTES"]
