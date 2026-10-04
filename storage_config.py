"""Resolve private storage without discovering or importing a user's data."""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil

APP_ROOT = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Storage:
    root: Path
    panel: Path
    skills: Path
    credentials: Path
    codex_home: Path
    repository_roots: list[Path]
    cicada_candidates: list[dict[str, str]]
    skill_inventory_roots: list[tuple[str, Path]]


def _path(value: str | os.PathLike[str], base: Path) -> Path:
    path = Path(value).expanduser()
    resolved = (path if path.is_absolute() else base / path).resolve()
    if resolved == APP_ROOT or APP_ROOT in resolved.parents:
        raise ValueError("Private storage must be outside the application directory")
    return resolved


def external_directory(value: str | os.PathLike[str]) -> Path:
    """Validate explicit runtime directories as well as configured defaults."""
    return _path(value, Path.cwd())


def load_storage() -> Storage:
    """Environment overrides pointer config, then use the adjacent data directory.

    Reading this configuration never creates directories or reads credentials.
    AGENT_CITY_PANEL_DATA remains compatible with existing installations.
    """
    explicit = os.environ.get("AGENT_CITY_CONFIG")
    pointer = Path(explicit).expanduser() if explicit else APP_ROOT / "storage.local.json"
    if explicit and not pointer.is_file():
        raise ValueError("Explicit storage configuration file is unavailable")
    config = {}
    base = pointer.resolve().parent
    if pointer.is_file():
        if pointer.stat().st_size > 64 * 1024:
            raise ValueError("Storage configuration is too large")
        config = json.loads(pointer.read_text(encoding="utf-8-sig"))
        allowed = {"schemaVersion", "dataRoot", "panelDirectory", "skillsDirectory", "credentialsDirectory", "codexHome", "repositoryRoots", "cicadaSources", "skillInventoryRoots"}
        if not isinstance(config, dict) or set(config) - allowed or config.get("schemaVersion") != 1:
            raise ValueError("Invalid storage configuration schema")
    root = _path(os.environ.get("AGENT_CITY_DATA_ROOT") or config.get("dataRoot", "../agent-city-data"), base)

    def field(name, default, env=None):
        override = os.environ.get(env) if env else None
        return _path(override or config.get(name, default), base)

    panel = field("panelDirectory", root / "panel", "AGENT_CITY_PANEL_DATA")
    skills = field("skillsDirectory", root / "skills", "AGENT_CITY_SKILLS_ROOT")
    credentials = field("credentialsDirectory", root / "credentials", "AGENT_CITY_CREDENTIALS_DIR")
    codex = field("codexHome", root / "codex-home", "CODEX_HOME")
    repos = config.get("repositoryRoots", [str(root / "repositories")])
    if not isinstance(repos, list) or not repos or not all(isinstance(x, str) for x in repos):
        raise ValueError("repositoryRoots must contain paths")
    repos = [_path(x, base) for x in repos]
    sources = config.get("cicadaSources", [])
    if not isinstance(sources, list):
        raise ValueError("cicadaSources must be a list")
    resolved_sources = []
    for source in sources:
        if not isinstance(source, dict) or set(source) != {"id", "label", "profile", "path"} or not all(isinstance(v, str) and v for v in source.values()):
            raise ValueError("Invalid Cicada source")
        resolved_sources.append({**source, "path": str(_path(source["path"], base))})
    inventory = config.get("skillInventoryRoots", [])
    if not isinstance(inventory, list):
        raise ValueError("skillInventoryRoots must be a list")
    inventory_paths = []
    for entry in inventory:
        if not isinstance(entry, dict) or set(entry) != {"origin", "path"} or not all(isinstance(v, str) and v for v in entry.values()):
            raise ValueError("Invalid skill inventory root")
        inventory_paths.append((entry["origin"], _path(entry["path"], base)))
    return Storage(root, panel, skills, credentials, codex, repos, resolved_sources, inventory_paths)


def prepare_skills(storage: Storage) -> Path:
    """Seed a new external skill library; never replace a user's existing files."""
    storage.skills.mkdir(parents=True, exist_ok=True)
    for root in storage.repository_roots:
        root.mkdir(parents=True, exist_ok=True)
    if any(storage.skills.iterdir()):
        return storage.skills
    for source in (APP_ROOT / "demo" / "skills").rglob("*"):
        if source.is_file() and not source.is_symlink():
            target = storage.skills / source.relative_to(APP_ROOT / "demo" / "skills")
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
    return storage.skills
