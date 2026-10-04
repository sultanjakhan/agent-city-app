#!/usr/bin/env python3
"""Agent City: loopback-only API catalogue and CodexBar dashboard. Python 3.11+."""
from __future__ import annotations

import argparse
import copy
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError, URLError

APP_ID = "agent-city-panel"
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "vendor"))
from storage_config import load_storage, prepare_skills, external_directory
import storage_migration
import model_workers as workers
import access
import panel_keys as credentials
import provider_catalogs
import published_catalogs
import provider_runtime
import connection_status
from data_sources import DataSources, SourceError, SourceConflict, validate_manifest, import_document, parse_portable_json
from local_mode import LocalOnlyCloud
import catalog_directory
import public_api
import availability
from skill_inventory import SkillInventory, SkillInventoryError
from project_library import ProjectLibrary, ProjectLibraryError, ProjectRevisionConflict
from project_policy import preview_policy
from repo_inventory import RepoInventory, RepoInventoryError
from pipeline_store import PipelineStore
from pipeline_policy_adapter import preview_repository_pipeline
from rule_store import RulesStore, RepoProfiles, RuleStoreError, RuleRevisionConflict
from skill_activity import SkillActivity, ActivityError
from codex_controls import CodexControls, CodexControlsError, RevisionConflict as CodexRevisionConflict
import sys
from owner_session import OwnerSessions
from run_store import PUBLIC_FIELDS, RunStore, RunError, RunConflict
from task_sync import TaskSync
from task_connection import TaskError
from work_exchange import WorkExchange, ExchangeError, ExchangeConflict
from cloud_sync import CloudSync, SyncError
from cicada_connector import CicadaConnector, ConnectorError, ConnectorConflict
from skills_store import SkillsStore, SkillsStoreError, RevisionConflict
from provider_store import ProviderStore, ProviderError, ProviderConflict

PROVIDERS = {
    "openrouter": {"name": "OpenRouter", "url": workers.OPENROUTER_MODELS_URL,
                   "docs": "https://openrouter.ai/docs/api_reference/limits", "clientIds": ["cline", "kilo", "opencode"],
                   "terms": "Проверяются только модели с нулевой ценой в свежем каталоге. Платные маршруты исключены."},
    "kilo": {"name": "Kilo", "url": workers.KILO_MODELS_URL,
             "docs": "https://kilo.ai/docs/getting-started/using-kilo-for-free", "keyRequired": False, "clientIds": ["kilo"],
             "terms": "Анонимный API. При исчерпании квоты проверка останавливается."},
    "cline": {"name": "Cline API", "url": "https://api.cline.bot/api/v1/ai/cline/recommended-models",
              "docs": "https://docs.cline.bot/api/models", "clientIds": ["cline"],
              "terms": "Отдельный API-ключ из аккаунта Cline. Вход в расширение не заменяет этот ключ."},
    "zen": {"name": "OpenCode Zen", "url": "https://opencode.ai/zen/v1/models",
            "docs": "https://opencode.ai/docs/zen/", "clientIds": ["opencode"],
            "terms": "Модели берутся из API. Каталог не подтверждает бесплатность: запросы к моделям заблокированы до проверки тарифа."},
}
PROVIDERS.update(copy.deepcopy(provider_catalogs.SOURCES))
# Registry presence is independent of free models and account/subscription access.
# These references do not import existing credentials or initiate a login.
PROVIDERS.update({
 'openai': {'name':'OpenAI','url':None,'docs':'https://developers.openai.com/api/reference/resources/models/methods/list',
            'apiCatalogUrl':'https://api.openai.com/v1/models','subscriptionDocs':'https://learn.chatgpt.com/docs/auth',
            'clientIds':['codex'],'keyRequired':False,'keyEntrySupported':False,'catalogSupported':False,'docsOnly':True,
            'terms':'OpenAI API и подписка ChatGPT/Codex — отдельные способы доступа. Наличие подписки и API-ключа здесь не проверено.'},
 'anthropic': {'name':'Anthropic / Claude','url':None,'docs':'https://platform.claude.com/docs/en/api/models/list',
               'apiCatalogUrl':'https://api.anthropic.com/v1/models','subscriptionDocs':'https://code.claude.com/docs/en/authentication',
               'clientIds':['claude-code'],'keyRequired':False,'keyEntrySupported':False,'catalogSupported':False,'docsOnly':True,
               'terms':'Anthropic API и подписка Claude через Claude Code — отдельные способы доступа. Подписочный токен не является API-ключом. Доступ здесь не проверен.'}
})

for _provider, _url in {"openrouter": "https://openrouter.ai/settings/keys", "cline": "https://app.cline.bot",
                       "zen": "https://opencode.ai/auth"}.items():
    PROVIDERS[_provider]["keyUrl"] = _url
for _id in published_catalogs.URLS:
    PROVIDERS[_id].update(apiCatalogUrl=PROVIDERS[_id]['url'], url=published_catalogs.URLS[_id], accountCatalog=False, catalogMode='published')
# Developer attribution, independent of the inference provider. Unknown stays unknown.
CHINESE_DEVELOPERS = {"qwen", "deepseek", "z-ai", "zai", "thudm", "moonshotai",
                      "minimax", "minimaxai", "stepfun", "stepfun-ai", "inclusionai",
                      "baidu", "tencent", "bytedance", "bytedance-seed", "xiaomi",
                      "meituan", "alibaba", "alibaba-cloud", "01-ai", "internlm", "dots-studio"}
MAX_JSON = 4 * 1024 * 1024

def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def data_directory():
    return load_storage().panel


def short(value, limit=180):
    return value[:limit] if isinstance(value, str) else ""


def number(value, low=0, high=1e12):
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        return None
    return value if math.isfinite(value) and low <= value <= high else None


def timestamp(value):
    if not isinstance(value, str) or len(value) > 64:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.isoformat() if parsed.tzinfo else None
    except ValueError:
        return None


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        raise URLError("redirect disabled")


def fetch_catalog(provider):
    """Model metadata only; authenticated catalogues use the selected provider's key."""
    if provider in published_catalogs.URLS:
        return published_catalogs.fetch(provider)
    if provider in provider_catalogs.SOURCES:
        return provider_catalogs.fetch(provider, credentials.read_key)
    request = Request(PROVIDERS[provider]["url"], headers={"Accept": "application/json"})
    with build_opener(NoRedirect()).open(request, timeout=15) as response:
        raw = response.read(MAX_JSON + 1)
    if len(raw) > MAX_JSON:
        raise ValueError("response too large")
    return normalize_catalog(provider, json.loads(raw))


def normalize_catalog(provider, payload):
    if provider == "cline":
        if not isinstance(payload, dict) or not isinstance(payload.get("free"), list):
            raise ValueError("unsupported Cline free catalogue")
        models = []
        for item in payload["free"][:2000]:
            ident = item.get("id") if isinstance(item, dict) else None
            if not isinstance(ident, str) or len(ident) > 200:
                continue
            dev = ident.split("/")[0]
            if dev == "cline-free":
                dev = next((d for prefix, d in [("mimo-", "xiaomi"), ("deepseek-", "deepseek"), ("gemini-", "google"),
                           ("muse-", "meta")] if ident.split("/")[-1].startswith(prefix)), "unknown")
            models.append({"id": ident, "name": short(item.get("name")) or ident, "developer": dev,
                           "chinese": dev in CHINESE_DEVELOPERS, "context": None, "tools": None, "vision": False,
                           "priceVerified": False, "kind": "chat"})
        return {"models": models, "skippedCount": 0}
    if provider == "zen":
        # The official /models endpoint may not include prices. Do not infer them from a name.
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise ValueError("unsupported Zen catalogue")
        result = provider_catalogs.normalize(provider, payload)
        for model in result["models"]:
            if model["id"].startswith("jev-"):
                model["kind"] = "structured"
        return result
    parse = workers._openrouter_model_stats if provider == "openrouter" else workers._kilo_model_stats
    accepted, skipped = parse(payload)
    raw_by_id = {x.get("id"): x for x in payload["data"] if isinstance(x, dict) and isinstance(x.get("id"), str)}
    def conditional(item):
        return (item.get('plan') in ('trial', 'subscription', 'conditional') or
                item.get('pricingType') in ('trial', 'subscription', 'conditional') or item.get('freeTier') is True)
    id_counts = Counter(item.get('id') for item in payload['data'] if isinstance(item, dict) and isinstance(item.get('id'), str))
    reason = workers._openrouter_free_reason if provider == 'openrouter' else workers._kilo_free_reason
    eligible_ids = {item['id'] for item in accepted if id_counts[item['id']] == 1 and len(item['id']) <= 200
                    and not conditional(raw_by_id[item['id']]) and reason(raw_by_id[item['id']])}
    summary = {'confirmedFree': len(eligible_ids), 'knownPaid': 0, 'unknown': 0, 'complete': True}
    for item in payload['data']:
        if not isinstance(item, dict) or not isinstance(item.get('id'), str):
            summary['unknown'] += 1
            continue
        if item['id'] in eligible_ids:
            continue
        if id_counts[item['id']] != 1:
            summary['unknown'] += 1
            continue
        pricing = item.get('pricing')
        try:
            if conditional(item) or not isinstance(pricing, dict) or not all(k in pricing for k in ('prompt', 'completion')) or any(isinstance(v, bool) for v in pricing.values()):
                raise ValueError()
            prices = [Decimal(str(value)) for value in pricing.values()]
            if not prices or any(not value.is_finite() or value < 0 for value in prices) or not any(value > 0 for value in prices):
                raise ValueError()
            summary['knownPaid'] += 1
        except (InvalidOperation, ValueError):
            summary['unknown'] += 1
    summary['complete'] = summary['unknown'] == 0
    result = []
    for item in accepted[:2000]:
        model_id = item["id"]
        if model_id not in eligible_ids:
            continue
        if len(model_id) > 200:
            continue
        raw = raw_by_id[model_id]
        developer = model_id.split("/")[0] if "/" in model_id else "unknown"
        params = raw.get("supported_parameters")
        result.append({
            "id": model_id, "name": short(raw.get("name")) or model_id.split("/")[-1],
            "developer": developer, "chinese": developer.lower() in CHINESE_DEVELOPERS,
            "context": number(raw.get("context_length"), 1),
            "tools": "tools" in params if isinstance(params, list) else None,
            "vision": "image" in (raw.get("architecture", {}).get("input_modalities") or []),
            "priceVerified": True, "kind": "chat",
        })
    # Preserve all model types; unknown metadata never implies chat capability.
    full=[]
    for raw in payload['data'][:2000]:
        ident=raw.get('id') if isinstance(raw,dict) else None
        if not isinstance(ident,str) or not ident or len(ident)>200:continue
        architecture=raw.get('architecture') if isinstance(raw.get('architecture'),dict) else {}
        inputs=architecture.get('input_modalities',[]);outputs=architecture.get('output_modalities',[])
        modality=architecture.get('modality')
        if modality and isinstance(modality,str) and '->' in modality:
            left,right=modality.split('->',1);inputs=left.split('+');outputs=right.split('+')
        kind='unknown'
        declared=raw.get('type')
        if declared in ('chat','structured','audio','moderation','embedding','image'):kind=declared
        elif isinstance(outputs,list) and 'audio' in outputs:kind='audio'
        elif isinstance(outputs,list) and 'image' in outputs and 'text' not in outputs:kind='image'
        elif isinstance(outputs,list) and 'embedding' in outputs:kind='embedding'
        elif isinstance(inputs,list) and isinstance(outputs,list) and 'audio' in inputs:kind='audio'
        elif isinstance(inputs,list) and isinstance(outputs,list) and 'text' in inputs and 'text' in outputs:kind='chat'
        developer=ident.split('/')[0] if '/' in ident else 'unknown'
        params=raw.get('supported_parameters')
        full.append({'id':ident,'name':short(raw.get('name')) or ident,'developer':developer,'chinese':developer.lower() in CHINESE_DEVELOPERS,'context':number(raw.get('context_length'),1),'tools':'tools' in params if isinstance(params,list) else None,'vision':'image' in inputs if isinstance(inputs,list) else False,'priceVerified':False,'kind':kind})
    free_by_id = {row['id']: row for row in result}
    for row in full:
        kind=row['kind'];row.update(free_by_id.get(row['id'], {}));row['kind']=kind
        if row['id'] in free_by_id:free_by_id[row['id']]['kind']=kind
        row['priceStatus'] = 'confirmed-free' if row.get('priceVerified') is True else 'unknown'
        raw = raw_by_id[row['id']]
        try:
            prices = raw.get('pricing')
            if id_counts[row['id']] != 1 or conditional(raw) or not isinstance(prices,dict) or not all(key in prices for key in ('prompt','completion')) or any(isinstance(value,bool) for value in prices.values()):raise ValueError()
            values = [Decimal(str(value)) for value in prices.values()]
            if values and all(value.is_finite() and value >= 0 for value in values) and any(value > 0 for value in values):row['priceStatus']='paid'
        except (ValueError, InvalidOperation):pass
    full = [row for row in full if id_counts[row['id']] == 1]
    return {"models": result, "allModels": full, "catalogScope": "published-api", "skippedCount": len(skipped), 'pricingSummary': summary}


def find_codexbar():
    explicit = os.environ.get("AGENT_CITY_CODEXBAR_CLI")
    candidates = [Path(explicit)] if explicit else []
    if not explicit:
        for name in ("codexbar-cli", "codexbar", "CodexBarCLI"):
            found = shutil.which(name)
            if found:
                candidates.append(Path(found))
        if sys.platform == "win32":
            candidates.insert(0, Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "Programs/CodexBar/codexbar-cli.exe")
        elif sys.platform == "darwin":
            candidates += [Path("/Applications/CodexBar.app/Contents/Helpers/CodexBarCLI"),
                           Path("/opt/homebrew/bin/codexbar"), Path("/usr/local/bin/codexbar")]
    return next((p.resolve() for p in candidates if p.is_file()), None)


WINDOW_LABELS = {"session": "Сессия", "weekly": "Неделя", "reset-credits": "Сбросы лимита"}


def normalize_codexbar(payload):
    if not isinstance(payload, dict) or payload.get("schemaVersion") != 1 or not isinstance(payload.get("providers"), list):
        raise ValueError("unsupported CodexBar dashboard schema")
    rows = []
    for item in payload["providers"][:100]:
        if not isinstance(item, dict) or item.get("enabled") is False:
            continue
        provider_id = short(item.get("id"), 80)
        if not provider_id or not re.fullmatch(r"[a-zA-Z0-9_-]+", provider_id):
            continue
        windows = []
        for window in item.get("windows", [])[:12] if isinstance(item.get("windows"), list) else []:
            if not isinstance(window, dict):
                continue
            used = number(window.get("usedPercent"), 0, 100)
            remaining = number(window.get("remainingPercent"), 0, 100)
            if remaining is None and used is not None:
                remaining = 100 - used
            kind = short(window.get("kind"), 40)
            windows.append({"kind": kind, "label": short(window.get("label"), 80) or WINDOW_LABELS.get(kind, "Лимит"),
                            "remainingPercent": remaining, "resetAt": timestamp(window.get("resetAt"))})
        credits = item.get("credits")
        rows.append({"id": provider_id, "name": short(item.get("name"), 60) or provider_id,
                     "windows": windows, "updatedAt": timestamp(item.get("updatedAt")),
                     "error": bool(item.get("error")),
                     "credits": number(credits.get("remaining")) if isinstance(credits, dict) else None})
    host = payload.get("host") if isinstance(payload.get("host"), dict) else {}
    return {"version": short(host.get("codexBarVersion"), 40), "generatedAt": timestamp(payload.get("generatedAt")),
            "staleAfterSeconds": number(payload.get("staleAfterSeconds"), 1, 86400),
            "providers": rows}


def fetch_codexbar(executable):
    # Redacted CLI snapshot. Never read CodexBar credentials, history or account identities.
    with tempfile.TemporaryFile() as output:
        kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
        process = subprocess.Popen([str(executable), "dashboard", "--timeout", "15", "--identity", "redacted"],
                                   stdout=output, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, **kwargs)
        deadline = time.monotonic() + 22
        try:
            while process.poll() is None:
                if time.monotonic() > deadline or os.fstat(output.fileno()).st_size > MAX_JSON:
                    raise TimeoutError("CodexBar output or timeout limit")
                time.sleep(0.05)
            if process.returncode != 0:
                raise ValueError("CodexBar command failed")
            output.seek(0)
            raw = output.read(MAX_JSON + 1)
            if len(raw) > MAX_JSON:
                raise ValueError("CodexBar output limit")
            return normalize_codexbar(json.loads(raw))
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)


def friendly_error(exc):
    if isinstance(exc, HTTPError):
        return f"Источник вернул HTTP {exc.code}. Попробуй обновить позже."
    if isinstance(exc, (TimeoutError, subprocess.TimeoutExpired)):
        return "Источник не ответил вовремя. Попробуй обновить позже."
    if isinstance(exc, (json.JSONDecodeError, ValueError, workers.WorkerError)):
        return "Не удалось прочитать формат источника. Последние данные сохранены."
    return "Не удалось подключиться к источнику. Последние данные сохранены."


class Store:
    def __init__(self, directory, catalog_fetcher=fetch_catalog, bar_fetcher=fetch_codexbar, executable=None, skills_root=None, directory_fetcher=catalog_directory.fetch, inventory_roots=None, repo_roots=None, codex_home=None, cicada_candidates=None, local_only=False):
        self.local_only = bool(local_only)
        self.directory = external_directory(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "state.json"
        new_profile = not any(self.directory.iterdir())
        self.data_sources = DataSources(self.directory, new_profile=new_profile)
        self.providers = ProviderStore(self.directory, PROVIDERS)
        storage = load_storage()
        external_skills = skills_root or prepare_skills(storage)
        self.skills = SkillsStore(external_skills, self.directory)
        self.inventory = (SkillInventory(inventory_roots if inventory_roots is not None else [('worktree', self.skills.root)])
                          if inventory_roots is not None or skills_root else SkillInventory(roots=[("worktree", self.skills.root), *storage.skill_inventory_roots]))
        self.batch = {}
        self.batch_stop = threading.Event()
        self.projects = ProjectLibrary(self.directory / 'projects.json', seed_path=ROOT / 'data/projects.json')
        self.repos = RepoInventory(repo_roots if repo_roots is not None else [self.directory] if skills_root else storage.repository_roots)
        self.pipelines = PipelineStore(self.directory)
        self.rules = RulesStore(self.directory, self.repos)
        self.repo_profiles = RepoProfiles(self.directory, self.repos, self.projects)
        self.activity = SkillActivity(self.directory)
        self.runs = RunStore(self.directory)
        self.cicada = CicadaConnector(self.directory, candidates=cicada_candidates if cicada_candidates is not None else [] if skills_root else storage.cicada_candidates)
        self.work_exchange = WorkExchange(self.directory, self.cicada, self.runs)
        self.task_sync = TaskSync(self.directory)
        self.task_sync.start()
        self.cloud = LocalOnlyCloud() if self.local_only else CloudSync(self.directory, self.cloud_reports)
        control_home = codex_home or (self.directory / 'test-codex-home' if skills_root else storage.codex_home)
        bridge = ('## Agent City\n\n'
                  'At the start of a task, read the additional local rules and repository profile with:\n'
                  f'`python -X utf8 "{(ROOT / "city.py").as_posix()}" context --cwd "<current working directory>"`\n'
                  'Use the actual working directory. Read the returned global and repository rules. '
                  'Repository instructions and higher-priority instructions take precedence. '
                  'An extension profile is a preference, not permission to install or execute it. '
                  'If Agent City is unavailable, continue using existing instructions; report the missing context.\n\n'
                  'After actually applying a skill, find its opaque ID with `city.py skill-inventory`, then report '
                  '`city.py report-use --id <skill-id> --agent codex --event-id <unique-use-id>` using the same script path. '
                  'Report once per actual application. Opening or discovering a skill does not count. '
                  'Never include task text or secrets in event IDs. Statistics cover reported events only.\n')
        self.codex = CodexControls(control_home, self.directory, self.inventory, bridge)
        self.lock = threading.RLock()
        self.catalog_fetcher = catalog_fetcher
        self.bar_fetcher = bar_fetcher
        self.directory_fetcher = directory_fetcher
        self.executable = executable if executable is not None else find_codexbar()
        self.busy = set()
        self.csrf_token = secrets.token_urlsafe(32)
        self.last_attempt = {}
        self.state = {"schemaVersion": 1, "favorites": [], "catalogs": {}, "codexbar": {}, "checks": {}, "directory": {}}
        self.clients = access.clients()
        try:
            raw = self.path.read_bytes()
            saved = json.loads(raw) if len(raw) <= MAX_JSON else None
            if isinstance(saved, dict) and saved.get("schemaVersion") == 1:
                if isinstance(saved.get("favorites"), list):
                    self.state["favorites"] = [x for x in saved["favorites"][:2000] if isinstance(x, str) and len(x) <= 200]
                if isinstance(saved.get("catalogs"), dict):
                    self.state["catalogs"] = {k: v for k, v in saved["catalogs"].items() if k in PROVIDERS and isinstance(v, dict) and isinstance(v.get("models"), list)}
                if isinstance(saved.get("codexbar"), dict):
                    self.state["codexbar"] = saved["codexbar"]
                if isinstance(saved.get("checks"), dict):
                    self.state["checks"] = saved["checks"]
                if isinstance(saved.get('directory'), dict):
                    self.state['directory'] = saved['directory']
        except (OSError, ValueError):
            pass
        # Old versions seeded curated offers without a successful API response.
        # Keep favorites/checks, but never treat that list as a discovered catalogue.
        for catalog in self.state["catalogs"].values():
            if catalog.pop("docsOnly", False):
                catalog["models"] = []
                catalog.pop("documentedAt", None)
                catalog.pop("updatedAt", None)

    def save(self):
        temporary = self.path.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(self.state, stream, ensure_ascii=False, allow_nan=False)
        os.replace(temporary, self.path)

    def cloud_reports(self):
        rows = [{key: value for key, value in row.items() if key in PUBLIC_FIELDS} for row in self.runs.snapshot()]
        names = {s['id']: s['name'] for s in self.inventory.list()}
        production = next((c for c in self.cicada.candidates if c['profile']=='production'),None)
        prefix = 'cicada-'+hashlib.sha256(str(Path(production['path']).resolve()).encode()).hexdigest()[:16]+'-' if production else None
        for row in rows:
            row['skillNames'] = {key: names[key] for key in row['skillIds'] if key in names}
            if prefix and (row.get('taskKey') or '').startswith(prefix):
                row['taskBinding']={'profile':'production','sourceId':row['taskKey'][len(prefix):]}
        return rows

    def dashboard(self):
        try:
            registry = self.work_exchange.snapshot(); pairs = registry['bindings']
        except (ValueError, OSError):
            registry = {'publishers': {}, 'bindings': {}, 'error': 'invalid_exchange_storage'}; pairs = {}
        source = self.cicada.snapshot(bindings=pairs)
        runs = [{key: value for key, value in row.items() if key in PUBLIC_FIELDS} for row in self.runs.snapshot()]
        for remote in list(self.cloud.remote):
            row=copy.deepcopy(remote);row['taskKey']=None
            binding=row.get('taskBinding')
            if binding and (source.get('source') or {}).get('profile')=='production' and source['source'].get('sourceKey'):
                row['taskKey']='cicada-'+source['source']['sourceKey']+'-'+binding['sourceId']
            runs.append(row)
        def current(run):
            try:
                return run['status'] in {'running', 'waiting'} and -30 <= time.time() - datetime.fromisoformat(run['updatedAt']).timestamp() <= 300
            except (ValueError, KeyError): return False
        working = {row['taskKey'] for row in runs if current(row)}
        # Read current names from Cicada only; never persist task text in reports.
        keys = list(dict.fromkeys(row['taskKey'] for row in sorted(runs, key=lambda r: r['updatedAt'], reverse=True) if row.get('taskKey')))
        historical = self.cicada.snapshot(task_keys=keys, bindings=pairs)
        source_key = (source.get('source') or {}).get('sourceKey')
        if (historical.get('source') or {}).get('sourceKey') != source_key:
            # A settings change between reads must not join two Cicada profiles.
            historical = {'tasks': [], 'status': 'source_changed'}
        source['historyTasks'] = historical['tasks']
        source['historyStatus'] = historical['status']
        source['historyLimited'] = bool(source_key) and sum(key.startswith('cicada-'+source_key+'-') for key in keys) > 500
        known = {task['taskKey']: task for task in source['tasks']}
        known.update({task['taskKey']: task for task in historical['tasks']})
        source['tasks'] = [task for task in known.values() if not task['completed'] and (task['isActive'] or task.get('isPaused') or any(key in working for key in task.get('runTaskKeys', [task['taskKey']])))]
        skills = {s['id']: {'id': s['id'], 'name': s['name']} for s in self.inventory.list()}
        for row in runs:
            row['skills'] = [skills.get(ident, {'id': ident, 'name': row.get('skillNames', {}).get(ident, ident)}) for ident in row['skillIds']]
        return {'schemaVersion': 1, 'asOf': now(), 'cicada': source, 'runs': runs, 'workRegistry': registry,
                'telemetry': 'reported', 'notice': 'Tasks are read from Cicada. Model, token and skill fields require an explicit agent report. Missing data is not zero.'}

    def snapshot(self):
        with self.lock:
            value = copy.deepcopy(self.state)
            active_sources = self.providers.sources()
            value['catalogs'] = {key: catalog for key, catalog in value['catalogs'].items() if key in active_sources}
            # Legacy Cline snapshots treated membership in `free` as zero-price
            # evidence. That group does not supply numeric pricing; keep the
            # user's cache on disk but do not expose it as confirmed free.
            for model in value['catalogs'].get('cline', {}).get('models', []):
                model['priceVerified'] = False
            seeds = json.loads((ROOT / 'published_catalog_seed.json').read_text(encoding='utf8'))
            for ident, seed in seeds.items():
                if ident not in active_sources:continue
                current = value['catalogs'].get(ident, {})
                if not current.get('models'):
                    value['catalogs'][ident] = {**copy.deepcopy(seed), **{key:current[key] for key in ('error','attemptedAt') if key in current}, 'updatedAt':seed['observedAt'], 'authStatus':'unverified'}
            for record in value["checks"].values():
                if not self.local_only and record.get("credentialRevision") and record["credentialRevision"] != credentials.revision(record.get("provider")):
                    record.update(status="key_changed", reply="", sent=False, detail="Ключ изменён; нужна новая проверка")
                record.pop("credentialRevision", None)
            for provider, catalog in value["catalogs"].items():
                if not PROVIDERS[provider].get('accountCatalog') and catalog.get('error'):
                    catalog['authStatus'] = 'unverified'
                if not self.local_only and catalog.get("credentialRevision") and catalog["credentialRevision"] != credentials.revision(provider):
                    catalog["authStatus"] = "unverified"
                catalog.pop("credentialRevision", None)
            value.update({"appId": APP_ID, "busy": sorted(self.busy), "serverTime": now(),
                          "csrfToken": self.csrf_token,
                          "codexbarInstalled": self.executable is not None,
                          "clients": self.clients,
                          "settings": {"version": public_api.VERSION, "skillsRoot": str(self.skills.root),
                                       "libraryMode": "external", "localOnly": self.local_only,
                                       "dataRoot": str(self.directory.resolve()), "registryUrl": catalog_directory.URL,
                                       "storage": storage_migration.status()},
                          "credentials": {p: None if self.local_only else access.key_available(p) if p in credentials.PROVIDERS else None for p in PROVIDERS},
                          "credentialInfo": {p: {"available": None, "source": "paused", "unverified": True, "canSave": False, "removable": False, "localOnly": True} if self.local_only else credentials.info(p) if p in credentials.PROVIDERS else {"available": None, "unverified": True, "canSave": False} for p in PROVIDERS},
                          "providerRegistry": self.providers.snapshot(),
                          "providerRuntime": provider_runtime.read(self.directory),
                          "sources": [{"id": key, **{k: item[k] for k in ("name", "docs", "keyUrl", "terms", "accountCatalog", "supported", "website", "docsOnly", "catalogSupported", "keyEntrySupported", "apiCatalogUrl", "subscriptionDocs", "catalogMode", "accessMode", "catalogPolicy") if k in item},
                                       "catalogUrl": item['url'], "keyRequired": item.get("keyRequired", True), "clientIds": item.get("clientIds", []),
                                       "discoveryOnly": key in provider_catalogs.SOURCES} for key, item in active_sources.items()]})
            value['dataSourcesOnboarding'] = self.data_sources.new_profile and not self.data_sources.path.exists()
            value['connectionStatus'] = connection_status.summarize(value)
            value['availability'] = availability.summarize(value)
            value['batch'] = copy.deepcopy(self.batch)
            return value

    def check_pending(self):
        if self.local_only:
            raise RuntimeError("Network and credential operations are disabled in local-only mode")
        with self.lock:
            if self.busy:
                raise RuntimeError('Дождись завершения текущей проверки.')
            routes = self.snapshot()['availability']['pendingRoutes']
            # Ten distinct models maximum, one provider per model in this pass.
            selected, seen = [], set()
            for route in routes:
                if route['model'] not in seen:
                    selected.append(route)
                    seen.add(route['model'])
                if len(selected) == 10:
                    break
            self.batch = {'total': len(selected), 'completed': 0, 'responded': 0,
                          'stopped': {}, 'running': bool(selected)}
            if not selected:
                return
            self.busy.add('check')
            self.batch_stop.clear()
            threading.Thread(target=self._check_batch, args=(selected,), daemon=True).start()

    def _check_batch(self, routes):
        try:
            for route in routes:
                if self.batch_stop.is_set():
                    break
                provider, model_id = route['provider'], route['model']
                if provider in self.batch['stopped']:
                    continue
                record = access.probe(provider, model_id, self.catalog_fetcher)
                record['credentialRevision'] = credentials.revision(provider)
                with self.lock:
                    self.state['checks'][provider + '|' + model_id] = record
                    self.batch['completed'] += 1
                    self.batch['responded'] += int(availability.responded(record))
                    if record['status'] in availability.STOP:
                        self.batch['stopped'][provider] = record['status']
                    self.save()
                if self.batch_stop.wait(3.2):
                    break
        finally:
            with self.lock:
                self.batch['running'] = False
                self.batch['cancelled'] = self.batch_stop.is_set()
                self.busy.discard('check')

    def credential(self, provider, key=None, remove=False):
        if self.local_only:
            raise RuntimeError("Network and credential operations are disabled in local-only mode")
        with self.lock:
            if provider not in PROVIDERS or provider == "kilo":
                raise ValueError("unknown credential provider")
            if not PROVIDERS[provider].get('keyEntrySupported', True):
                raise ProviderError('Подключение через ключ для этого провайдера пока не поддерживается в панели.')
            if provider not in self.providers.sources():
                raise ProviderError('Провайдер удалён из списка. Обнови страницу перед действием.')
            if "check" in self.busy or provider in self.busy:
                raise RuntimeError("Дождись завершения текущей проверки.")
            credentials.remove_key(provider) if remove else credentials.save_key(provider, key)
            self.state["checks"] = {k: v for k, v in self.state["checks"].items() if v.get("provider") != provider}
            catalog = self.state["catalogs"].get(provider)
            if catalog is not None:
                catalog.update(authStatus="unverified", credentialRevision=credentials.revision(provider))
                catalog.pop("error", None)
            self.last_attempt.pop(provider, None)
            self.save()

    def check(self, provider, model_id):
        if self.local_only:
            raise RuntimeError("Network and credential operations are disabled in local-only mode")
        with self.lock:
            if provider not in PROVIDERS or not isinstance(model_id, str):
                raise ValueError("unknown route")
            if provider not in self.providers.sources():
                raise ProviderError('Провайдер удалён из списка. Обнови страницу перед действием.')
            if self.providers.sources()[provider].get('accessMode') == 'subscription':
                raise ProviderError('Subscription access must be checked in the official client.')
            if not any(m.get("id") == model_id for m in self.state["catalogs"].get(provider, {}).get("models", [])):
                raise ValueError("unknown model")
            if "check" in self.busy or provider in self.busy:
                return
            # No request bursts or silent retries. A provider-wide auth/quota refusal has a cooldown.
            key = provider + "|" + model_id
            records = self.state["checks"].values()
            for record in records:
                stamp = timestamp(record.get("attemptedAt"))
                age = (datetime.now(timezone.utc) - datetime.fromisoformat(stamp)).total_seconds() if stamp else 1e9
                if record.get("provider") == provider and age < 60 and (record.get("model") == model_id or record.get("status") in {"rate_limited", "forbidden", "auth_error", "payment_required"}):
                    raise ValueError("check cooldown")
            self.busy.add("check")
            threading.Thread(target=self._check_one, args=(provider, model_id, key), daemon=True).start()

    def _check_one(self, provider, model_id, key):
        try:
            revision = credentials.revision(provider)
            record = access.probe(provider, model_id, self.catalog_fetcher)
            record["credentialRevision"] = revision
            with self.lock:
                self.state["checks"][key] = record
                try:
                    self.save()
                except OSError:
                    record["detail"] += " · Не удалось сохранить проверку"
        finally:
            with self.lock:
                self.busy.discard("check")

    def favorite(self, model_id, enabled):
        with self.lock:
            known = {x.get("id") for c in self.state["catalogs"].values() for x in c.get('allModels',c.get('models',[])) if isinstance(x, dict)}
            saved = set(self.state["favorites"])
            if model_id not in known and model_id not in saved:
                raise ValueError("unknown model")
            saved.add(model_id) if enabled else saved.discard(model_id)
            old = self.state["favorites"]
            self.state["favorites"] = sorted(saved)
            try:
                self.save()
            except OSError:
                self.state["favorites"] = old
                raise

    def refresh(self, target="all"):
        if self.local_only:
            raise RuntimeError("Network and credential operations are disabled in local-only mode")
        with self.lock:
            active = [key for key, source in self.providers.sources().items() if source['supported'] and source.get('catalogSupported', True)]
            targets = active + ["codexbar", "directory"] if target == "all" else active + ['directory'] if target == "catalog" else [target]
            for item in targets:
                if item not in (*PROVIDERS, "codexbar", 'directory'):
                    raise ValueError("unknown source")
                if item in PROVIDERS and item not in active:
                    raise ValueError("inactive source")
                if item in self.busy or time.monotonic() - self.last_attempt.get(item, -100) < 10:
                    continue
                self.busy.add(item)
                self.last_attempt[item] = time.monotonic()
                threading.Thread(target=self._refresh_one, args=(item,), daemon=True).start()

    def _refresh_one(self, target):
        if self.local_only:
            raise RuntimeError("Network and credential operations are disabled in local-only mode")
        if target == 'directory':
            try:
                result = {**self.directory_fetcher(), 'updatedAt': now(), 'error': None}
            except Exception as exc:
                result = {**self.state.get('directory', {}), 'error': friendly_error(exc)}
            with self.lock:
                self.state['directory'] = result
                try:
                    self.save()
                finally:
                    self.busy.discard(target)
            return
        error = None
        result = None
        revision = None
        auth_status = "unverified"
        try:
            if target == "codexbar":
                if not self.executable:
                    raise FileNotFoundError("CodexBar not installed")
                result = self.bar_fetcher(self.executable)
            else:
                revision = credentials.revision(target)
                source = PROVIDERS[target]
                if source.get("accountCatalog") and not credentials.key_available(target):
                    raise PermissionError("missing credential")
                result = self.catalog_fetcher(target)
                if source.get("accountCatalog"):
                    auth_status = "accepted"
                elif target == "openrouter" and self.catalog_fetcher is fetch_catalog and credentials.key_available(target):
                    auth_status = access.verify_openrouter_key()["status"]
        except Exception as exc:
            if isinstance(exc, PermissionError):
                error, auth_status = None, "missing_key"
            elif isinstance(exc, HTTPError):
                error = {401: "Ключ не принят · HTTP 401", 403: "Доступ отклонён · HTTP 403", 429: "Лимит запросов · HTTP 429"}.get(exc.code, friendly_error(exc))
                auth_status = ({401: "rejected", 403: "forbidden", 429: "rate_limited"}.get(exc.code, "unverified")
                               if PROVIDERS.get(target, {}).get('accountCatalog') else 'unverified')
            else:
                error = "CodexBar не найден на этом устройстве." if isinstance(exc, FileNotFoundError) else friendly_error(exc)
        with self.lock:
            parent = self.state if target == "codexbar" else self.state["catalogs"]
            previous = parent.get(target, {})
            if result is not None:
                parent[target] = {**result, "updatedAt": now(), "error": None}
            else:
                parent[target] = {**previous, "error": error}
                if target != "codexbar":
                    parent[target].setdefault("models", [])
            parent[target]["attemptedAt"] = now()
            if target != "codexbar":
                parent[target].update(authStatus=auth_status, credentialRevision=revision)
            try:
                self.save()
            except OSError:
                parent[target]["error"] = "Данные получены, но не удалось сохранить их на устройстве."
            finally:
                self.busy.discard(target)


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, store, bootstrap=None, owner_host=None, exclusive=False):
        self.exclusive_windows=exclusive and os.name=="nt"
        if self.exclusive_windows:self.allow_reuse_address=False
        self.store = store
        self.owner_sessions = OwnerSessions.from_environment(os.environ,bootstrap)
        self.owner_host = owner_host or 'agent-city-'+secrets.token_hex(16)+'.localhost'
        if not re.fullmatch(r'agent-city-[a-f0-9]{32}\.localhost', self.owner_host): raise ValueError('invalid owner host')
        super().__init__(address, Handler)
        self.owner_write_condition=threading.Condition()
        self.owner_mutation_fenced=False
        self.owner_active_writes=0
        self.owner_cookie = 'agent_city_owner_'+str(self.server_port)


    def server_bind(self):
        if self.exclusive_windows:
            import socket
            self.socket.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
        super().server_bind()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def respond(self, status, body, content_type="application/json; charset=utf-8", cookie=None):
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if cookie: self.send_header("Set-Cookie", cookie)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def allowed(self, write=False):
        owner_host = self.server.owner_host+":"+str(self.server.server_port)
        hosts = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}", owner_host}
        host = self.headers.get("Host")
        origin = self.headers.get("Origin")
        if host not in hosts or (origin is not None and origin != f"http://{host}"):
            self.respond(403, {"error": "Доступ разрешён только из локального приложения."})
            return False
        if write and self.headers.get("X-Agent-City") != "1":
            self.respond(403, {"error": "Неверный запрос приложения."})
            return False
        path = urlsplit(self.path).path
        self.owner_delegation_pending=False;self.owner_delegation_consumed=False
        if path.startswith('/api/') and path not in {'/api/health','/api/owner-bootstrap'} and (host!=owner_host or not self.server.owner_sessions.authorized(self.headers.get('Cookie'),self.server.owner_cookie)):
            grant=self.headers.get('X-Agent-City-Grant')
            if host==owner_host and self.server.owner_sessions.grant_authorized(grant,self.command,self.path,consume=self.command=='GET'):
                self.owner_delegation_pending=self.command!='GET';self.owner_delegation_consumed=self.command=='GET'
            else:
                self.respond(401,{'error':'owner_session_required'});return False
        return True

    def csrf_authorized(self):
        return self.owner_delegation_consumed or secrets.compare_digest(self.headers.get('X-Agent-City-Token',''),self.server.store.csrf_token)

    def do_GET(self):
        if not self.allowed():
            return
        path = urlsplit(self.path).path
        if path == '/api/owner-session':
            return self.respond(200, {'authorized': True})
        if path == '/api/work-exchange':
            try: return self.respond(200, self.server.store.work_exchange.snapshot())
            except (ValueError, OSError): return self.respond(400, {'error':'invalid_exchange_storage'})
        if path == "/api/pipelines":
            try:
                return self.respond(200, self.server.store.pipelines.snapshot())
            except (ValueError, OSError):
                return self.respond(400, {"error": "Invalid pipeline storage"})
        if path == "/api/state":
            try:
                return self.respond(200, self.server.store.snapshot())
            except (ProviderError, OSError):
                return self.respond(500, {'error': 'Не удалось прочитать хранилище провайдеров. Файл сохранён.'})
        if path == "/api/health":
            return self.respond(200, {"appId": APP_ID, "version": public_api.VERSION, "localOnly": self.server.store.local_only})
        if path in {'/api/data-sources', '/api/data-sources/export', '/api/data-sources/status'}:
            try:
                store = self.server.store.data_sources
                result = store.export() if path.endswith('/export') else store.summaries() if path.endswith('/status') else store.snapshot()
                return self.respond(200, result)
            except (SourceError, OSError, ValueError):
                return self.respond(400, {'error': 'Не удалось прочитать локальную конфигурацию источников.'})
        if path == '/api/task-sync':
            try:return self.respond(200,self.server.store.task_sync.snapshot())
            except (TaskError,OSError):return self.respond(409,{'error':'task_sync_unavailable'})
        if path == '/api/cloud':
            return self.respond(200, self.server.store.cloud.status())
        if path in {'/api/dashboard', '/api/v1/dashboard', '/api/connectors'}:
            try:
                result = self.server.store.cicada.settings() if path.endswith('/connectors') else self.server.store.dashboard()
                return self.respond(200, result)
            except (ConnectorError, RunError, OSError, ValueError):
                return self.respond(400, {'error': 'Не удалось прочитать данные дашборда. Проверь коннектор в настройках.'})
        if path == '/api/codex-controls':
            try:
                config = self.server.store.codex.config_status()
                writable = not self.server.store.local_only
                if not writable:
                    for skill in config.get('skills', []): skill['canToggle'] = False
                return self.respond(200, {'schemaVersion': 1, 'config': config, 'bridge': self.server.store.codex.bridge_status(), 'writeSupported': writable})
            except (CodexControlsError, OSError, ValueError):
                return self.respond(400, {'error': 'Не удалось прочитать настройки Codex. Файлы не изменены.'})
        if path in {'/api/projects', '/api/v1/projects', '/api/extensions', '/api/v1/extensions'}:
            try:
                return self.respond(200, self.server.store.projects.snapshot())
            except (ProjectLibraryError, OSError):
                return self.respond(400, {'error': 'Не удалось прочитать библиотеку проектов.'})
        if path in {'/api/skill-inventory', '/api/v1/skill-inventory'}:
            params = parse_qs(urlsplit(self.path).query)
            try:
                skills = self.server.store.inventory.list(params.get('q', [''])[0])
                if 'id' in params:
                    return self.respond(200, {'schemaVersion': 1, **self.server.store.inventory.read(params['id'][0])})
                activity = self.server.store.activity.snapshot()
                for skill in skills:
                    skill['activity'] = activity['skills'].get(skill['id'], {})
                return self.respond(200, {'schemaVersion': 1, 'skills': skills, 'trackingSince': activity['startedAt']})
            except (SkillInventoryError, OSError, ValueError):
                return self.respond(400, {'error': 'Не удалось прочитать skill. Проверь путь и формат файла.'})
        if path in {'/api/repositories', '/api/v1/repositories', '/api/rules', '/api/v1/rules', '/api/v1/context'}:
            params = parse_qs(urlsplit(self.path).query)
            store = self.server.store
            try:
                repos = store.repos.list()
                if path.endswith('/repositories'):
                    if 'id' in params:
                        ident = params['id'][0]
                        return self.respond(200, {'schemaVersion': 1, **store.repos.read(ident), 'profile': store.repo_profiles.read(ident)})
                    return self.respond(200, {'schemaVersion': 1, 'repositories': repos})
                if path.endswith('/rules'):
                    return self.respond(200, {'schemaVersion': 1, **store.rules.read(params.get('scope', ['global'])[0])})
                cwd = params.get('cwd', [''])[0]
                if not isinstance(cwd, str) or len(cwd) > 4096:
                    raise ValueError()
                # Expand Windows 8.3 aliases as well as normal project paths. No file content is read.
                if cwd and (not os.path.isabs(cwd) or cwd.startswith(('\\\\', '//'))):
                    raise ValueError()
                if cwd and os.name == 'nt' and os.path.splitdrive(cwd)[0].casefold() not in {os.path.splitdrive(r['path'])[0].casefold() for r in repos}:
                    raise ValueError()
                normalized = os.path.normcase(str(Path(cwd).resolve())) if cwd else ''
                matches = [r for r in repos if normalized == os.path.normcase(r['path']) or normalized.startswith(os.path.normcase(r['path']) + os.sep)]
                repo = max(matches, key=lambda r: len(r['path'])) if matches else None
                selected = store.repo_profiles.read(repo['id'])['extensionIds'] if repo else []
                return self.respond(200, {'schemaVersion': 1, 'repository': repo,
                                         'rules': store.rules.repository_rules(repo['id'] if repo else None),
                                         'extensions': [p for p in store.projects.list() if p['id'] in selected],
                                         'agentReporting': public_api.reporting(),
                                         'notice': 'Extension selection is a profile, not installation or authorization to run code.'})
            except (RepoInventoryError, RuleStoreError, OSError, ValueError):
                return self.respond(400, {'error': 'Не удалось прочитать правила или репозиторий.'})
        if path == '/api/skills':
            params = parse_qs(urlsplit(self.path).query)
            try:
                if 'slug' in params:
                    if 'revision' in params:
                        return self.respond(200, self.server.store.skills.read_revision(params['slug'][0], params['revision'][0]))
                    return self.respond(200, self.server.store.skills.read(params['slug'][0]))
                return self.respond(200, {'skills': self.server.store.skills.list(params.get('q', [''])[0])})
            except (SkillsStoreError, OSError, ValueError):
                return self.respond(400, {'error': 'Не удалось прочитать skill. Проверь путь и формат файла.'})
        if path.startswith('/api/v1/'):
            resource = path.rsplit('/', 1)[-1]
            try:
                snapshot = self.server.store.snapshot()
            except (ProviderError, OSError):
                return self.respond(500, {'error': 'Не удалось прочитать хранилище провайдеров. Файл сохранён.'})
            if resource == 'manifest':
                return self.respond(200, public_api.manifest())
            if resource == 'models':
                return self.respond(200, public_api.models(snapshot))
            if resource == 'providers':
                return self.respond(200, public_api.providers(snapshot))
            if resource == 'directory':
                return self.respond(200, {'schemaVersion': 1, **snapshot.get('directory', {})})
            if resource == 'skills':
                try:
                    params = parse_qs(urlsplit(self.path).query)
                    if 'slug' in params:
                        skill = self.server.store.skills.read(params['slug'][0])
                        skill.pop('history', None)
                        return self.respond(200, {'schemaVersion': 1, 'skill': skill})
                    return self.respond(200, {'schemaVersion': 1, 'root': str(self.server.store.skills.root), 'skills': self.server.store.skills.list()})
                except (SkillsStoreError, OSError, ValueError):
                    return self.respond(400, {'error': 'Не удалось прочитать skill. Проверь путь и формат файла.'})
        files = {"/": ("index.html", "text/html; charset=utf-8"),
                 "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                 "/i18n.js": ("i18n.js", "text/javascript; charset=utf-8"),
                 "/workspace.js": ("workspace.js", "text/javascript; charset=utf-8"),
                 "/providers.js": ("providers.js", "text/javascript; charset=utf-8"),
                 "/integrations.js": ("integrations.js", "text/javascript; charset=utf-8"),
                 "/pipeline.js": ("pipeline.js", "text/javascript; charset=utf-8"),
                 "/work-registry.js": ("work-registry.js", "text/javascript; charset=utf-8"),
                 "/pipeline.css": ("pipeline.css", "text/css; charset=utf-8"),
                 "/dashboard.js": ("dashboard.js", "text/javascript; charset=utf-8"),
                 "/shared-tasks.js": ("shared-tasks.js", "text/javascript; charset=utf-8"),
                 "/shared-tasks.css": ("shared-tasks.css", "text/css; charset=utf-8"),
                 "/data-sources.js": ("data-sources.js", "text/javascript; charset=utf-8"),
                 "/owner-session.js": ("owner-session.js", "text/javascript; charset=utf-8"),
                 "/appearance.js": ("appearance.js", "text/javascript; charset=utf-8"),
                 "/shared-neutral.css": ("shared-neutral.css", "text/css; charset=utf-8"),
                 "/styles.css": ("styles.css", "text/css; charset=utf-8"),
                 "/icon.svg": ("icon.svg", "image/svg+xml")}
        if path in files:
            filename, mime = files[path]
            return self.respond(200, (ROOT / "static" / filename).read_bytes(), mime)
        self.respond(404, {"error": "Не найдено"})

    def do_POST(self):
        if not self.allowed(write=True):return
        with self.server.owner_write_condition:
            if self.server.owner_mutation_fenced:return self.respond(503,{'error':'owner_restart_pending'})
            self.server.owner_active_writes+=1
        try:self._do_POST()
        finally:
            with self.server.owner_write_condition:
                self.server.owner_active_writes-=1;self.server.owner_write_condition.notify_all()

    def _do_POST(self):
        if not self.allowed(write=True):
            return
        requested_path = urlsplit(self.path).path
        if requested_path == '/api/owner-logout':
            if not self.csrf_authorized():return self.respond(403,{'error':'invalid_application_token'})
            self.server.owner_sessions.revoke_session(self.headers.get('Cookie'),self.server.owner_cookie)
            return self.respond(200,{'revoked':True},cookie=self.server.owner_cookie+'=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0')
        if requested_path == '/api/owner-bootstrap':
            # Require our own origin as well as the one-use launcher capability.
            if self.headers.get('Host') != self.server.owner_host+':'+str(self.server.server_port) or self.headers.get('Origin') != 'http://'+self.headers.get('Host', ''):
                return self.respond(403, {'error': 'invalid_bootstrap_origin'})
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 1 <= length <= 256: raise ValueError()
                self.connection.settimeout(5)
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict) or set(payload) != {'capability'}: raise ValueError()
                session = self.server.owner_sessions.exchange(payload['capability'])
                if not session: return self.respond(401, {'error': 'owner_bootstrap_rejected'})
                return self.respond(200, {'authorized': True}, cookie=self.server.owner_cookie+'='+session+'; HttpOnly; SameSite=Strict; Path=/')
            except (ValueError, TypeError, OSError):
                return self.respond(400, {'error': 'invalid_owner_bootstrap'})
        if self.server.store.local_only and (requested_path.startswith("/api/cloud/") or requested_path in {"/api/credential", "/api/refresh", "/api/check", "/api/check-pending"}):
            return self.respond(403, {"error": "Режим только локально: облако, ключи и сетевые проверки временно отключены.", "localOnly": True})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            path = urlsplit(self.path).path
            limit = 2 * 1024 * 1024 if path.startswith(('/api/skills/', '/api/projects/', '/api/extensions/', '/api/rules/', '/api/data-sources/', '/api/pipelines/', '/api/work-exchange/')) else 4096
            if length < 1 or length > limit:
                return self.respond(413, {"error": "Неверный размер запроса."})
            self.connection.settimeout(5)
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError()
            if self.owner_delegation_pending:
                if not self.server.owner_sessions.grant_authorized(self.headers.get('X-Agent-City-Grant'),self.command,self.path,payload,consume=True):
                    return self.respond(401,{'error':'invalid_owner_delegation'})
                self.owner_delegation_consumed=True
            path = urlsplit(self.path).path
            if path.startswith('/api/work-exchange/'):
                if not self.csrf_authorized():
                    return self.respond(403, {'error':'invalid_application_token'})
                exchange = self.server.store.work_exchange
                try:
                    if path.endswith('/preview'):
                        if set(payload) != {'document','revision'}: raise ExchangeError('unsupported_exchange_fields')
                        result = exchange.preview(payload['document'], payload['revision'])
                    elif path.endswith('/apply'):
                        if set(payload) != {'previewToken','revision'}: raise ExchangeError('unsupported_exchange_fields')
                        result = exchange.apply(payload['previewToken'], payload['revision'])
                    elif path.endswith('/export-report'):
                        if set(payload) != {'runId'}: raise ExchangeError('unsupported_exchange_fields')
                        result = exchange.export_report(payload['runId'])
                    else: return self.respond(404, {'error':'unknown_exchange_action'})
                    return self.respond(200, result)
                except (ExchangeConflict, RunConflict): return self.respond(409, {'error':'exchange_conflict'})
                except (ValueError, OSError): return self.respond(400, {'error':'invalid_exchange_or_source'})
            if path.startswith('/api/data-sources/'):
                if not self.csrf_authorized():
                    return self.respond(403, {'error': 'Обнови окно приложения перед сохранением.'})
                store = self.server.store.data_sources
                try:
                    action = path.rsplit('/', 1)[-1]
                    if action == 'validate':
                        if set(payload) != {'document'}: raise SourceError('Конфигурация содержит неподдерживаемые поля.')
                        document = payload['document']
                        result = {'manifest': import_document(parse_portable_json(document) if isinstance(document, str) else document)}
                    elif action == 'dismiss':
                        if payload: raise SourceError('Конфигурация содержит неподдерживаемые поля.')
                        result = store.dismiss_onboarding()
                    elif action in {'preview', 'apply', 'create'}:
                        fields = {'manifest', 'bindings', 'revision'} | ({'previewToken'} if action != 'preview' else set()) | ({'sourceId'} if action == 'create' else set())
                        if set(payload) != fields: raise SourceError('Конфигурация содержит неподдерживаемые поля.')
                        args = (payload['manifest'], payload['bindings'], payload['revision'])
                        result = store.preview(*args) if action == 'preview' else store.apply(*args, payload['previewToken']) if action == 'apply' else store.create_structure(payload['sourceId'], *args, payload['previewToken'])
                    else:
                        return self.respond(404, {'error': 'Не найдено'})
                    return self.respond(200, result)
                except SourceConflict as error:
                    return self.respond(409, {'error': str(error)})
                except (SourceError, TypeError, ValueError) as error:
                    return self.respond(400, {'error': str(error) if isinstance(error, SourceError) else 'Неверная конфигурация источников.'})
                except OSError:
                    return self.respond(500, {'error': 'Не удалось выполнить локальное действие. Проверь права на папку.'})
            if path in {'/api/pipelines/preview', '/api/pipelines/save'}:
                if not self.csrf_authorized():
                    return self.respond(403, {'error': 'Invalid application token'})
                allowed_fields = {'pipeline', 'pipelineRestrictions', 'stageRestrictions'} | ({'revision'} if path.endswith('/save') else set())
                if 'pipeline' not in payload or set(payload) - allowed_fields:
                    return self.respond(400, {'error': 'Invalid pipeline request fields'})
                model_ids = {m['id'] for catalog in self.server.store.state.get('catalogs', {}).values() for m in catalog.get('models', []) if isinstance(m, dict) and isinstance(m.get('id'), str)}
                skill_ids = {s['id'] for s in self.server.store.inventory.list()}
                result = preview_repository_pipeline(payload['pipeline'], self.server.store.repo_profiles, preview_policy,
                    payload.get('pipelineRestrictions'), payload.get('stageRestrictions'), model_ids, skill_ids)
                if path.endswith('/preview'):
                    return self.respond(200, result)
                return self.respond(200, self.server.store.pipelines.save(payload.get('pipeline'), payload.get('revision')))
            if path == '/api/providers/resolve':
                if not self.csrf_authorized():
                    return self.respond(403, {'error': 'Обнови окно приложения перед сохранением.'})
                return self.respond(200, self.server.store.providers.resolve(payload.get('website')))
            if path in {'/api/providers/add', '/api/providers/remove', '/api/providers/settings'}:
                if not self.csrf_authorized():
                    return self.respond(403, {'error': 'Обнови окно приложения перед сохранением.'})
                store = self.server.store
                with store.lock:
                    ident = payload.get('id')
                    if path.endswith('/remove') and (ident in store.busy or 'check' in store.busy):
                        return self.respond(409, {'error': 'Дождись завершения текущего запроса перед удалением.'})
                    store.providers.change(path.rsplit('/', 1)[-1], payload, payload.get('revision'))
                    if path.endswith('/remove'):
                        store.last_attempt.pop(ident, None)
                return self.respond(200, store.snapshot())
            if path in {'/api/storage/prepare','/api/storage/cancel'}:
                if not self.csrf_authorized():
                    return self.respond(403, {'error': 'Обнови окно приложения перед сохранением.'})
                try:
                    if path.endswith('/prepare') and set(payload)=={'destination','revision'}:
                        result=storage_migration.prepare(payload['destination'],payload['revision'])
                    elif path.endswith('/cancel') and set(payload)=={'revision'}:
                        result=storage_migration.cancel(payload['revision'])
                    else:raise storage_migration.MigrationError('Неверные поля запроса переноса.')
                    return self.respond(200,result)
                except storage_migration.MigrationError as error:
                    return self.respond(409,{'error':str(error)})
            if path in {'/api/cloud/profile','/api/cloud/sync'}:
                if not self.csrf_authorized():
                    return self.respond(403, {'error': 'Обнови окно приложения перед сохранением.'})
                if path.endswith('/profile'): self.server.store.cloud.configure(payload)
                threading.Thread(target=self.server.store.cloud.sync, daemon=True).start()
                return self.respond(200, self.server.store.cloud.status())
            if path.startswith('/api/task-sync/'):
                if not self.csrf_authorized():return self.respond(403,{'error':'task_scope_denied'})
                sync=self.server.store.task_sync
                try:
                    if path=='/api/task-sync/configure' and set(payload)=={'config','revision'}:result=sync.configure(payload['config'],payload['revision'])
                    elif path=='/api/task-sync/exchange' and payload=={}:result=sync.exchange()
                    elif path=='/api/task-sync/queue' and set(payload)=={'version','operationId','command','arguments'} and payload['version']==1:result=sync.enqueue(payload['operationId'],payload['command'],payload['arguments'])
                    elif path=='/api/task-sync/resolve' and set(payload)=={'operationId','revision'}:result=sync.resolve(payload['operationId'],payload['revision'])
                    else:raise TaskError('invalid_task_sync_request')
                    return self.respond(200,result)
                except TaskError as error:return self.respond(error.status,{'isError':True,'code':error.code,'current':error.current,'error':error.code})
            if path in {'/api/connectors/cicada', '/api/runs/report', '/api/agent/report'}:
                if not self.csrf_authorized():
                    return self.respond(403, {'error': 'Обнови окно приложения перед сохранением.'})
                if path.endswith('/cicada'):
                    return self.respond(200, self.server.store.cicada.select(payload.get('sourceId'), payload.get('revision')))
                if path == '/api/agent/report':
                    from agent_reporting import report
                    return self.respond(200, report(self.server.store, payload))
                known_skills = {s['id'] for s in self.server.store.inventory.list()}
                ids = payload.get('skillIds', [])
                if not isinstance(ids, list) or any(not isinstance(ident, str) or ident not in known_skills for ident in ids):
                    raise RunError('unknown skill')
                return self.respond(200, {'schemaVersion': 1, 'run': self.server.store.runs.report(payload)})
            elif path in {'/api/codex-controls/skill', '/api/codex-controls/connect'}:
                if not self.csrf_authorized():
                    return self.respond(403, {'error': 'Обнови окно приложения перед сохранением.'})
                if self.server.store.local_only:
                    return self.respond(403, {'error': 'Codex writes are disabled in local-only mode; owner authentication is not configured.'})
                controls = self.server.store.codex
                result = (controls.connect_bridge(payload.get('revision')) if path.endswith('/connect') else
                          controls.set_enabled(payload.get('id'), payload.get('enabled'), payload.get('revision')))
                return self.respond(200, result)
            elif path in {'/api/rules/preview', '/api/rules/save', '/api/repositories/profile', '/api/skill-activity'}:
                if not self.csrf_authorized():
                    return self.respond(403, {'error': 'Обнови окно приложения перед сохранением.'})
                store = self.server.store
                if path == '/api/skill-activity':
                    store.inventory.list()
                    store.inventory.read(payload.get('id'))
                    return self.respond(200, store.activity.record(payload.get('id'), payload.get('kind'), payload.get('agent', 'user'), payload.get('eventId')))
                store.repos.list()
                if path == '/api/repositories/profile':
                    return self.respond(200, store.repo_profiles.save(payload.get('repoId'), payload.get('extensionIds'), payload.get('revision'), payload.get('policy')))
                action = store.rules.preview if path.endswith('/preview') else store.rules.save
                return self.respond(200, action(payload.get('scope'), payload.get('content'), payload.get('revision')))
            elif path == '/api/projects/policy/preview':
                return self.respond(200, preview_policy(payload.get('policy'), payload.get('pipeline'), payload.get('stage')))
            elif path in {'/api/projects/save', '/api/extensions/save'}:
                if not self.csrf_authorized():
                    return self.respond(403, {'error': 'Обнови окно приложения перед сохранением.'})
                self.server.store.projects.save(payload.get('project'), payload.get('revision'))
                return self.respond(200, self.server.store.projects.snapshot())
            elif path.startswith('/api/skills/'):
                if not self.csrf_authorized():
                    return self.respond(403, {'error': 'Обнови окно приложения перед сохранением.'})
                if not isinstance(payload.get('revision'), str) or not re.fullmatch('[a-f0-9]{64}', payload['revision']):
                    raise ValueError()
                action = path.rsplit('/', 1)[-1]
                store = self.server.store.skills
                if action == 'preview':
                    result = store.preview(payload.get('slug'), payload.get('content'), expected_revision=payload['revision'])
                elif action == 'save':
                    result = store.save(payload.get('slug'), payload.get('content'), expected_revision=payload['revision'])
                elif action == 'restore':
                    result = store.rollback(payload.get('slug'), payload.get('targetRevision'), expected_revision=payload['revision'])
                else:
                    raise ValueError()
                return self.respond(200, result)
            elif path == "/api/credential":
                token = self.headers.get("X-Agent-City-Token", "")
                if not secrets.compare_digest(token, self.server.store.csrf_token):
                    return self.respond(403, {"error": "Обнови окно приложения перед сохранением ключа."})
                if payload.get("action") not in {"save", "remove"}:
                    raise ValueError()
                self.server.store.credential(payload.get("provider"), payload.get("key"), payload["action"] == "remove")
            elif path == "/api/refresh":
                self.server.store.refresh(payload.get("target", "all"))
            elif path == "/api/favorite":
                if not isinstance(payload.get("id"), str) or not isinstance(payload.get("enabled"), bool):
                    raise ValueError()
                self.server.store.favorite(payload["id"], payload["enabled"])
            elif path == "/api/check":
                self.server.store.check(payload.get("provider"), payload.get("model"))
            elif path in {'/api/check-pending', '/api/check-cancel'}:
                if not self.csrf_authorized():
                    return self.respond(403, {'error': 'Обнови окно приложения перед сохранением.'})
                if path == '/api/check-pending':
                    self.server.store.check_pending()
                else:
                    self.server.store.batch_stop.set()
            else:
                return self.respond(404, {"error": "Не найдено"})
            self.respond(200, self.server.store.snapshot())
        except ProviderConflict as exc:
            self.respond(409, {'error': str(exc)})
        except ProviderError as exc:
            self.respond(400, {'error': str(exc)})
        except (ConnectorConflict, RunConflict):
            self.respond(409, {'error': 'Уже есть более новые данные. Обнови состояние и повтори действие.'})
        except SyncError:
            self.respond(400, {'error':'Не удалось подключить облачный профиль. Проверь файл подключения.'})
        except (ConnectorError, RunError):
            self.respond(400, {'error': 'Не удалось сохранить коннектор или отчёт агента. Проверь поля.'})
        except CodexRevisionConflict:
            self.respond(409, {'error': 'Настройки Codex изменились. Обнови данные и повтори действие.'})
        except CodexControlsError:
            self.respond(400, {'error': 'Не удалось изменить настройки Codex. Проверь файл конфигурации.'})
        except RuleRevisionConflict:
            self.respond(409, {'error': 'Правила или профиль изменены. Открой заново; черновик сохранён в поле.'})
        except (RuleStoreError, RepoInventoryError, ActivityError, SkillInventoryError):
            self.respond(400, {'error': 'Не удалось изменить правила, профиль или настройки навыка.'})
        except ProjectRevisionConflict:
            self.respond(409, {'error': 'Библиотека изменена. Закрой карточку и открой её заново.'})
        except ProjectLibraryError:
            self.respond(400, {'error': 'Проверь поля проекта: HTTPS-ссылки, описание и сценарии на RU и EN.'})
        except RevisionConflict:
            self.respond(409, {'error': 'Файл изменён другим редактором. Открой его заново; твой черновик сохранён в поле.'})
        except SkillsStoreError:
            self.respond(400, {'error': 'Не удалось изменить skill. Проверь frontmatter, размер и выбранную версию.'})
        except (ValueError, TypeError, KeyError):
            self.respond(400, {"error": "Неверные данные запроса."})
        except RuntimeError as exc:
            self.respond(409, {"error": str(exc)})
        except OSError:
            self.respond(500, {"error": "Не удалось сохранить изменение."})


def main():
    parser = argparse.ArgumentParser(description="Agent City API panel")
    parser.add_argument("--port", type=int, default=47831)
    parser.add_argument("--data-dir", type=Path, default=data_directory())
    parser.add_argument("--no-refresh", action="store_true", help="use cached data without any provider requests")
    parser.add_argument("--local-only", action="store_true", help="disable cloud, credential observation/mutations and provider requests")
    parser.add_argument("--owner-control-stdin",action="store_true",help="private inherited owner control channel")
    args = parser.parse_args()
    from storage_lock import StorageLock
    writer_lock = StorageLock(args.data_dir)
    store = Store(args.data_dir, local_only=args.local_only)
    bootstrap = os.environ.pop("AGENT_CITY_OWNER_BOOTSTRAP", None)
    server = Server(("127.0.0.1", args.port), store, bootstrap=bootstrap, owner_host=os.environ.pop("AGENT_CITY_OWNER_HOST", None), exclusive=args.owner_control_stdin)
    if args.owner_control_stdin:
        from owner_control import start_control
        start_control(server,os.environ.pop('AGENT_CITY_OWNER_INSTANCE',None))
    store.cloud.start()
    if not args.no_refresh and not args.local_only:
        store.refresh()
    print(f"Agent City http://127.0.0.1:{server.server_port}",file=sys.stderr if args.owner_control_stdin else sys.stdout,flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        writer_lock.__exit__()


if __name__ == "__main__":
    main()
