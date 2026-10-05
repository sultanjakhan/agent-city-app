"""Versioned shared standards and repository references; no runtime enforcement."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import re
import threading
from typing import Any

from rule_store import (
    MAX_PROFILE_BYTES, RuleStoreError, RuleRevisionConflict,
    _assert_outside_repositories, _atomic_json,
)
from storage_config import external_directory


class StandardsValidationError(RuleStoreError, ValueError):
    pass


class StandardsRevisionConflict(RuleRevisionConflict):
    pass


_REPO_ID = re.compile(r"^repo-[0-9a-f]{24}$")
_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}$")
_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:-[a-zA-Z0-9.-]+)?$")
MAX_REFERENCES = 100
MAX_ORIGINALS = 300


def _hash(value: Any) -> str:
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _original(**value: Any) -> dict[str, Any]:
    value["provenance"] = {"kind": "prototype-proposal", "source": "agent-city-neutral-mockup", "record": "standardDefs"}
    value["originalHash"] = _hash(value)
    return value


_INITIAL_STANDARDS = (
    _original(
        id="neutral-interface-draft", version="0.1.0-draft", category="design", status="draft",
        name="Интерфейс · нейтральный вариант", nameEn="Interface · neutral proposal",
        description="Предложение интерфейса для сравнения.", descriptionEn="An interface proposal for comparison.",
        rules=[
            "Сохранять установленную палитру в обеих темах.",
            "Вторичные действия — текстовые; подложка появляется при наведении.",
            "Главное действие и выбранная строка имеют лёгкое нейтральное выделение.",
            "Тонкие границы помогают отделить поля ввода и рабочие области.",
            "Клавиатурный фокус отличается от выбранного состояния.",
            "Точную геометрию и применение к проектам выбирает пользователь.",
        ],
        rulesEn=[
            "Preserve the established palette in both themes.",
            "Secondary actions use text; their background appears on hover.",
            "The main action and selected row use a subtle neutral highlight.",
            "Thin borders separate input fields and work areas.",
            "Keyboard focus differs from the selected state.",
            "The user chooses exact geometry and project assignments.",
        ],
    ),
    _original(
        id="qa-evidence", version="0.1.0", category="qa", status="template",
        name="QA · проверяемый результат", nameEn="QA · verifiable results",
        description="Приёмка по требованиям и наблюдаемому поведению.", descriptionEn="Acceptance based on requirements and observed behavior.",
        rules=[
            "Для каждого требования указать фактическую проверку.",
            "Не считать отсутствие ошибки доказательством успеха.",
            "Отделять подтверждённое от непроверенного.",
            "Сохранять результат проверки и причину решения.",
        ],
        rulesEn=[
            "Record an actual check for each requirement.",
            "Do not treat the absence of an error as evidence of success.",
            "Distinguish verified behavior from unverified behavior.",
            "Keep the check result and the reason for the decision.",
        ],
    ),
    _original(
        id="frontend-states", version="0.1.0", category="frontend", status="template",
        name="Frontend · состояния интерфейса", nameEn="Frontend · interface states",
        description="Доступность и устойчивость интерактивных экранов.", descriptionEn="Accessible, resilient interactive screens.",
        rules=[
            "Действия доступны с клавиатуры.",
            "Проверять 320 px, широкое окно и обе темы.",
            "Сохранять черновик при переходе между разделами.",
            "Создание задачи и её запуск — отдельные действия.",
        ],
        rulesEn=[
            "Actions are available from the keyboard.",
            "Check a 320 px viewport, a wide window, and both themes.",
            "Preserve drafts when switching sections.",
            "Task creation and launch are separate actions.",
        ],
    ),
)


def _reference(value: Any) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != {"id", "version"}:
        raise StandardsValidationError("standard reference requires id and version")
    if not isinstance(value["id"], str) or not _ID.fullmatch(value["id"]):
        raise StandardsValidationError("invalid standard id")
    if not isinstance(value["version"], str) or len(value["version"]) > 80 or not _VERSION.fullmatch(value["version"]):
        raise StandardsValidationError("invalid standard version")
    return dict(value)


def _validate_original(value: Any) -> dict[str, Any]:
    fields = {"id", "version", "category", "status", "name", "nameEn", "description", "descriptionEn", "rules", "rulesEn", "provenance", "originalHash"}
    if not isinstance(value, dict) or set(value) != fields:
        raise StandardsValidationError("invalid standard original")
    _reference({"id": value["id"], "version": value["version"]})
    if value["category"] not in ("design", "qa", "frontend") or value["status"] not in ("draft", "template"):
        raise StandardsValidationError("invalid standard category or status")
    for field in ("name", "nameEn", "description", "descriptionEn"):
        if not isinstance(value[field], str) or not 1 <= len(value[field].strip()) <= 500:
            raise StandardsValidationError("invalid standard text")
    for field in ("rules", "rulesEn"):
        if not isinstance(value[field], list) or not 1 <= len(value[field]) <= 100 or any(not isinstance(rule, str) or not 1 <= len(rule.strip()) <= 2000 for rule in value[field]):
            raise StandardsValidationError("invalid standard rules")
    if len(value["rules"]) != len(value["rulesEn"]):
        raise StandardsValidationError("standard translations must cover every rule")
    if value["provenance"] != {"kind": "prototype-proposal", "source": "agent-city-neutral-mockup", "record": "standardDefs"}:
        raise StandardsValidationError("invalid standard provenance")
    body = {key: item for key, item in value.items() if key != "originalHash"}
    if value["originalHash"] != _hash(body):
        raise StandardsValidationError("standard original hash mismatch")
    return copy.deepcopy(value)


class StandardsStore:
    def __init__(self, directory: str | Path, repo_inventory: Any):
        self.directory = external_directory(directory)
        _assert_outside_repositories(self.directory, repo_inventory)
        self.repo_inventory = repo_inventory
        self.catalog_path = self.directory / "standards-catalog.json"
        self.path = self.directory / "standard-assignments.json"
        self._lock = threading.RLock()

    def _read_json(self, path: Path, empty: dict[str, Any]) -> dict[str, Any]:
        if not path.exists() and not path.is_symlink():
            return copy.deepcopy(empty)
        if path.is_symlink() or not path.is_file():
            raise StandardsValidationError("standards path must be a regular file")
        try:
            if path.stat().st_size > MAX_PROFILE_BYTES:
                raise StandardsValidationError("standards file exceeds size limit")
            with path.open("rb") as stream:
                raw = stream.read(MAX_PROFILE_BYTES + 1)
            if len(raw) > MAX_PROFILE_BYTES:
                raise StandardsValidationError("standards file exceeds size limit")
            value = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise StandardsValidationError("invalid standards file") from exc
        if not isinstance(value, dict):
            raise StandardsValidationError("invalid standards envelope")
        return value

    def _catalog(self) -> dict[str, Any]:
        value = self._read_json(self.catalog_path, {"schemaVersion": 1, "standards": []})
        if set(value) != {"schemaVersion", "standards"} or type(value["schemaVersion"]) is not int or value["schemaVersion"] != 1 or not isinstance(value["standards"], list) or len(value["standards"]) > MAX_ORIGINALS:
            raise StandardsValidationError("invalid standards catalog")
        originals, keys = [], set()
        for item in value["standards"]:
            original = _validate_original(item)
            key = (original["id"], original["version"])
            if key in keys:
                raise StandardsValidationError("duplicate standard version")
            originals.append(original)
            keys.add(key)
        # A bundled update may add a version; an existing original never changes.
        for item in _INITIAL_STANDARDS:
            if (item["id"], item["version"]) not in keys:
                originals.append(copy.deepcopy(item))
        if len(originals) > MAX_ORIGINALS:
            raise StandardsValidationError("standards catalog exceeds version limit")
        return {"schemaVersion": 1, "standards": originals}

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            catalog = self._catalog()
            standards = [{key: copy.deepcopy(value) for key, value in item.items() if key not in {"rules", "rulesEn"}} for item in catalog["standards"]]
            return {"schemaVersion": 1, "standards": standards, "revision": _hash(catalog), "runtimeEnforced": False}

    def detail(self, standard_id: str, version: str) -> dict[str, Any]:
        reference = _reference({"id": standard_id, "version": version})
        with self._lock:
            for item in self._catalog()["standards"]:
                if item["id"] == reference["id"] and item["version"] == reference["version"]:
                    return {"schemaVersion": 1, **copy.deepcopy(item), "runtimeEnforced": False}
        raise StandardsValidationError("standard version is not in the shared catalog")

    def _repo(self, repo_id: str) -> None:
        if not isinstance(repo_id, str) or not _REPO_ID.fullmatch(repo_id):
            raise StandardsValidationError("invalid repository id")
        try:
            item = self.repo_inventory.read(repo_id)
        except Exception as exc:
            raise StandardsValidationError("repository must be enumerated before use") from exc
        if not isinstance(item, dict) or item.get("id") != repo_id or not isinstance(item.get("path"), str):
            raise StandardsValidationError("invalid repository inventory record")

    def _assignments(self) -> dict[str, Any]:
        value = self._read_json(self.path, {"schemaVersion": 1, "assignments": {}})
        if set(value) != {"schemaVersion", "assignments"} or type(value["schemaVersion"]) is not int or value["schemaVersion"] != 1 or not isinstance(value["assignments"], dict) or len(value["assignments"]) > 200:
            raise StandardsValidationError("invalid standards assignments")
        known = {(item["id"], item["version"]) for item in self._catalog()["standards"]}
        for repo_id, refs in value["assignments"].items():
            if not _REPO_ID.fullmatch(repo_id) or not isinstance(refs, list) or len(refs) > MAX_REFERENCES:
                raise StandardsValidationError("invalid repository standards")
            ids = set()
            for ref in refs:
                reference = _reference(ref)
                if (reference["id"], reference["version"]) not in known or reference["id"] in ids:
                    raise StandardsValidationError("unknown or duplicate standard reference")
                ids.add(reference["id"])
        return value

    def assignments(self, repo_id: str) -> dict[str, Any]:
        with self._lock:
            self._repo(repo_id)
            value = self._assignments()
            return {"schemaVersion": 1, "repoId": repo_id, "standardRefs": copy.deepcopy(value["assignments"].get(repo_id, [])), "revision": _hash(value), "runtimeEnforced": False}

    def apply(self, repo_id: str, standard_id: str, version: str, revision: str) -> dict[str, Any]:
        with self._lock:
            self._repo(repo_id)
            reference = _reference({"id": standard_id, "version": version})
            self.detail(standard_id, version)
            value = self._assignments()
            if revision != _hash(value):
                raise StandardsRevisionConflict("standard assignments changed; reload before saving")
            refs = value["assignments"].get(repo_id, [])
            selected = next((ref for ref in refs if ref["id"] == standard_id), None)
            if selected == reference:
                return self.assignments(repo_id)
            if selected is None and len(refs) >= MAX_REFERENCES:
                raise StandardsValidationError("repository standards exceed reference limit")
            if repo_id not in value["assignments"] and len(value["assignments"]) >= 200:
                raise StandardsValidationError("standards assignments exceed repository limit")
            catalog = self._catalog()
            _atomic_json(self.catalog_path, catalog)
            value["assignments"][repo_id] = [ref for ref in refs if ref["id"] != standard_id] + [reference]
            _atomic_json(self.path, value)
            return self.assignments(repo_id)
