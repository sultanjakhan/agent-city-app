"""Explicit, read-only summaries of private data folders.

Portable manifests contain only allowlisted section locations. Machine bindings
stay in a separate local profile; neither is an active-runtime storage pointer.
"""
from __future__ import annotations

from datetime import datetime, timezone
from contextlib import closing
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import sqlite3
import tempfile
import threading
import time

APP_ROOT = Path(__file__).resolve().parent
MAX_CONFIG = 16 * 1024
MAX_JSON = 4 * 1024 * 1024
KINDS = {'agent-city-data', 'cicada-data'}
# Proposed portable layout; no active Cicada paths or task namespaces change.
SECTIONS = {
    'projects': ('agent-city-data', 'panel/projects.json', 'projects'),
    'skills': ('agent-city-data', 'skills', None),
    'runs': ('agent-city-data', 'panel/agent-runs.json', 'runs'),
    'tasks-production': ('cicada-data', 'profiles/production/calendar.db', None),
    'tasks-dev': ('cicada-data', 'profiles/dev/calendar.db', None),
}
PROTECTED = {'.codex', '.agents', '.aws', '.ssh', '.gnupg', 'credentials', 'secrets',
             'sessions', 'cloud', 'codex-home'}


class SourceError(ValueError):
    pass


class SourceConflict(SourceError):
    pass


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def default_manifest():
    return {'schemaVersion': 1,
            'sources': [{'id': 'city', 'kind': 'agent-city-data', 'root': '../agent-city-data', 'mode': 'read-only'},
                        {'id': 'cicada', 'kind': 'cicada-data', 'root': '../cicada-data', 'mode': 'read-only'}],
            'sections': [{'id': key, 'sourceId': 'city' if kind == 'agent-city-data' else 'cicada',
                          'path': path, 'visible': True, 'placement': 'data'}
                         for key, (kind, path, _) in SECTIONS.items()]}


def validate_manifest(value):
    if not isinstance(value, dict) or set(value) != {'schemaVersion', 'sources', 'sections'} or type(value['schemaVersion']) is not int or value['schemaVersion'] != 1:
        raise SourceError('Неверный формат переносимой конфигурации.')
    if len(canonical(value)) > MAX_CONFIG:
        raise SourceError('Конфигурация слишком велика.')
    sources = value['sources']
    if not isinstance(sources, list) or not 1 <= len(sources) <= 2:
        raise SourceError('Выбери один или два источника данных.')
    ids, kinds = {}, set()
    for row in sources:
        if not isinstance(row, dict) or set(row) != {'id', 'kind', 'root', 'mode'}:
            raise SourceError('Конфигурация содержит неподдерживаемые поля.')
        ident, kind = row['id'], row['kind']
        if not isinstance(ident, str) or not re.fullmatch(r'[a-z][a-z0-9-]{0,63}', ident) or not isinstance(kind, str) or kind not in KINDS or ident in ids or kind in kinds:
            raise SourceError('Неверный или повторяющийся источник.')
        if row['mode'] != 'read-only' or row['root'] != '../' + kind:
            raise SourceError('Допустимы только относительные папки данных и режим чтения.')
        ids[ident] = kind; kinds.add(kind)
    sections = value['sections']
    if not isinstance(sections, list) or not 1 <= len(sections) <= len(SECTIONS):
        raise SourceError('Неверный список разделов.')
    seen = set()
    for row in sections:
        if not isinstance(row, dict) or set(row) != {'id', 'sourceId', 'path', 'visible', 'placement'}:
            raise SourceError('Конфигурация содержит неподдерживаемые поля.')
        ident = row['id']
        if not isinstance(ident, str) or ident not in SECTIONS or ident in seen:
            raise SourceError('Неверный или повторяющийся раздел.')
        kind, path, _ = SECTIONS[ident]
        if not isinstance(row['sourceId'], str) or ids.get(row['sourceId']) != kind or row['path'] != path or type(row['visible']) is not bool or not isinstance(row['placement'], str) or row['placement'] not in {'data', 'dashboard'}:
            raise SourceError('Неверное расположение или источник раздела.')
        seen.add(ident)
    return json.loads(canonical(value))


def no_redirect(path):
    for part in [path, *path.parents]:
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if part.is_symlink() or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise SourceError('Папки и файлы с перенаправлением не поддерживаются.')


def local_root(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 4096 or any(ord(c) < 32 for c in value):
        raise SourceError('Укажи полный путь к локальной папке.')
    path = Path(value)
    if not path.is_absolute() or value.startswith(('\\\\', '//')) or '..' in path.parts or '~' in path.parts:
        raise SourceError('Нужен абсолютный локальный путь без обхода каталогов.')
    if any(part.casefold() in PROTECTED for part in path.parts):
        raise SourceError('Хранилища ключей и сессий не являются источником данных.')
    no_redirect(path)
    resolved = path.resolve()
    if resolved == APP_ROOT or APP_ROOT in resolved.parents or resolved in APP_ROOT.parents:
        raise SourceError('Данные должны находиться отдельно от кода приложения.')
    for ancestor in [resolved, *resolved.parents]:
        if ((ancestor / 'server.py').is_file() and (ancestor / 'public_api.py').is_file()) or (ancestor / 'agent-system/app/server.py').is_file():
            raise SourceError('Данные должны находиться отдельно от кода приложения.')
    if resolved.exists() and not resolved.is_dir():
        raise SourceError('Источник должен быть папкой.')
    return resolved


def validate_bindings(value, manifest):
    if not isinstance(value, dict) or set(value) - {row['id'] for row in manifest['sources']}:
        raise SourceError('Неверные локальные пути источников.')
    return {ident: str(local_root(path)) for ident, path in value.items()}


def file_stamp(path):
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(timespec='seconds')


def section_summary(root, section):
    """Only counts/metadata are returned; never task text, model replies or keys."""
    path = root / section['path']
    no_redirect(path)
    row = {'id': section['id'], 'sourceId': section['sourceId'], 'path': section['path'],
           'visible': section['visible'], 'placement': section['placement'],
           'state': 'missing', 'count': None, 'updatedAt': None, 'error': None}
    if not path.exists():
        return row
    row['updatedAt'] = file_stamp(path)
    if section['id'] == 'skills':
        if not path.is_dir():
            raise SourceError('Неверный формат папки навыков.')
        count = 0
        for index, child in enumerate(path.iterdir()):
            if index >= 500:
                raise SourceError('Слишком много записей для локального preview.')
            no_redirect(child)
            if child.is_dir() and (child / 'SKILL.md').is_file():
                no_redirect(child / 'SKILL.md'); count += 1
        row.update(state='ready', count=count)
        return row
    if not path.is_file():
        raise SourceError('Ожидаемый файл данных отсутствует.')
    if section['id'].startswith('tasks-'):
        if path.stat().st_size > 64 * 1024 * 1024:
            raise SourceError('База слишком велика для локального preview.')
        if Path(str(path) + '-wal').exists():
            row.update(state='busy', error='База использует WAL. Счётчик отложен; запись не выполнялась.')
            return row
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro&immutable=1', uri=True, timeout=1)) as db:
            db.execute('PRAGMA trusted_schema=OFF')
            db.set_progress_handler(lambda: 1, 100000)
            count = db.execute("SELECT COUNT(*) FROM items WHERE kind='task'").fetchone()[0]
        row.update(state='ready', count=count)
        return row
    if path.stat().st_size > MAX_JSON:
        raise SourceError('Файл слишком велик для локального preview.')
    data = json.loads(path.read_text(encoding='utf-8-sig'))
    field = SECTIONS[section['id']][2]
    records = data.get(field) if isinstance(data, dict) else None
    if not isinstance(records, (list, dict)):
        raise SourceError('Формат раздела не распознан.')
    row.update(state='ready', count=len(records))
    return row


class DataSources:
    def __init__(self, directory, *, new_profile=False):
        self.path = Path(directory) / 'data-sources.local.json'
        self.new_profile = new_profile
        self.lock = threading.RLock()
        self.receipts = {}

    def _read(self):
        no_redirect(self.path)
        if not self.path.exists():
            return {'schemaVersion': 1, 'manifest': default_manifest(), 'bindings': {}}, 'none'
        if self.path.stat().st_size > 32 * 1024:
            raise SourceError('Не удалось прочитать локальную конфигурацию источников.')
        try:
            raw = self.path.read_bytes(); value = json.loads(raw)
            if not isinstance(value, dict) or set(value) != {'schemaVersion', 'manifest', 'bindings'} or type(value['schemaVersion']) is not int or value['schemaVersion'] != 1:
                raise ValueError()
            manifest = validate_manifest(value['manifest'])
            bindings = validate_bindings(value['bindings'], manifest)
            return {'schemaVersion': 1, 'manifest': manifest, 'bindings': bindings}, hashlib.sha256(raw).hexdigest()
        except (ValueError, OSError, TypeError):
            raise SourceError('Не удалось прочитать локальную конфигурацию источников.') from None

    def snapshot(self):
        with self.lock:
            value, revision = self._read()
            return {**value, 'revision': revision, 'profilePath': str(self.path), 'readOnly': True,
                    'needsOnboarding': self.new_profile and revision == 'none',
                    'savedAt': file_stamp(self.path) if self.path.exists() else None}

    def export(self):
        manifest = self.snapshot()['manifest']
        profiles = []
        for source in manifest['sources']:
            rows = [row for row in manifest['sections'] if row['sourceId'] == source['id']]
            document = {'schemaVersion': 1, 'appId': 'agent-city',
                        'source': {'kind': 'directory', 'path': None},
                        'structureVersion': 1, 'localGit': False,
                        'sections': [{'id': row['id'], 'visible': row['visible'], 'placement': row['placement'], 'order': index}
                                     for index, row in enumerate(rows)],
                        'refresh': {'mode': 'manual'}, 'onboarding': {'status': 'skipped'}}
            profiles.append({'id': source['id'], 'repositoryKind': source['kind'], 'config': document})
        return {'schemaVersion': 1, 'appId': 'agent-city', 'profiles': profiles}

    def inspect(self, manifest, bindings):
        manifest = validate_manifest(manifest); bindings = validate_bindings(bindings, manifest)
        sources, sections = [], []
        for source in manifest['sources']:
            binding = bindings.get(source['id']); root = local_root(binding) if binding else None
            source_row = {'id': source['id'], 'kind': source['kind'], 'root': binding,
                          'state': 'not_connected' if root is None else 'missing' if not root.exists() else 'available',
                          'gitDetected': bool(root and (root / '.git').exists()), 'mode': 'read-only',
                          'structurePlan': ['panel', 'skills', 'repositories'] if source['kind'] == 'agent-city-data' else ['profiles/production', 'profiles/dev']}
            sources.append(source_row)
            for section in manifest['sections']:
                if section['sourceId'] != source['id']:
                    continue
                if not section['visible']:
                    sections.append({**section, 'state': 'hidden', 'count': None, 'updatedAt': None, 'error': None})
                    continue
                if root is None:
                    sections.append({**section, 'state': 'not_connected', 'count': None, 'updatedAt': None, 'error': None})
                    continue
                try:
                    sections.append(section_summary(root, section))
                except (SourceError, OSError, ValueError, sqlite3.Error):
                    sections.append({**section, 'state': 'error', 'count': None, 'updatedAt': None,
                                     'error': 'Не удалось прочитать раздел. Проверь формат и доступ к файлу.'})
        return {'sources': sources, 'sections': sections, 'checkedAt': datetime.now(timezone.utc).isoformat(timespec='seconds')}

    def summaries(self):
        value = self.snapshot()
        return self.inspect(value['manifest'], value['bindings'])

    def preview(self, manifest, bindings, revision):
        with self.lock:
            _, current = self._read()
            if revision != current:
                raise SourceConflict('Источники изменились. Обнови конфигурацию; черновик сохранён.')
            manifest = validate_manifest(manifest); bindings = validate_bindings(bindings, manifest)
            result = self.inspect(manifest, bindings)
            token = secrets.token_urlsafe(24)
            self.receipts = {key: item for key, item in self.receipts.items() if item[0] > time.monotonic()}
            if len(self.receipts) >= 20:
                self.receipts.clear()
            self.receipts[token] = (time.monotonic() + 600, canonical({'manifest': manifest, 'bindings': bindings, 'revision': revision}))
            return {**result, 'previewToken': token, 'revision': current, 'manifest': manifest, 'bindings': bindings}

    def apply(self, manifest, bindings, revision, token):
        with self.lock:
            manifest = validate_manifest(manifest); bindings = validate_bindings(bindings, manifest)
            _, current = self._read()
            if revision != current:
                raise SourceConflict('Источники изменились. Обнови конфигурацию; черновик сохранён.')
            receipt = self.receipts.get(token) if isinstance(token, str) else None
            candidate = canonical({'manifest': manifest, 'bindings': bindings, 'revision': revision})
            if not receipt or receipt[0] < time.monotonic() or receipt[1] != candidate:
                raise SourceError('Сначала выполни preview текущего выбора.')
            # Revalidate paths immediately before writing the local profile.
            self.inspect(manifest, bindings); no_redirect(self.path)
            value = {'schemaVersion': 1, 'manifest': manifest, 'bindings': bindings}
            raw = canonical(value) + b'\n'
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, name = tempfile.mkstemp(dir=self.path.parent, prefix='.sources-')
            try:
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(raw); stream.flush(); os.fsync(stream.fileno())
                os.replace(name, self.path)
            finally:
                if os.path.exists(name): os.unlink(name)
            self.receipts.pop(token, None)
            return self.snapshot()

    def dismiss_onboarding(self):
        with self.lock:
            value = self.snapshot()
            if value['revision'] != 'none':
                return value
            preview = self.preview(value['manifest'], {}, value['revision'])
            return self.apply(value['manifest'], {}, value['revision'], preview['previewToken'])

    def create_structure(self, source_id, manifest, bindings, revision, token):
        with self.lock:
            manifest = validate_manifest(manifest); bindings = validate_bindings(bindings, manifest)
            _, current = self._read()
            if revision != current:
                raise SourceConflict('Источники изменились. Обнови конфигурацию; черновик сохранён.')
            receipt = self.receipts.get(token) if isinstance(token, str) else None
            candidate = canonical({'manifest': manifest, 'bindings': bindings, 'revision': revision})
            if not receipt or receipt[0] < time.monotonic() or receipt[1] != candidate:
                raise SourceError('Сначала выполни preview текущего выбора.')
            source = next((row for row in manifest['sources'] if row['id'] == source_id), None)
            if not source or source_id not in bindings:
                raise SourceError('Укажи папку выбранного источника.')
            result = self._create(source['kind'], bindings[source_id])
            self.receipts.pop(token, None)
            return result

    def _create(self, kind, value):
        root = local_root(value)
        if not root.parent.is_dir():
            raise SourceError('Родительская папка должна существовать.')
        directories = ['panel', 'skills', 'repositories'] if kind == 'agent-city-data' else ['profiles/production', 'profiles/dev']
        # Validate the entire plan before adding any directory. Existing files
        # and Git metadata are never replaced; empty databases are not fabricated.
        for relative in directories:
            target = root / relative; no_redirect(target)
            if target.exists() and not target.is_dir():
                raise SourceError('Структура конфликтует с существующим файлом.')
        root.mkdir(exist_ok=True)
        for relative in directories:
            (root / relative).mkdir(parents=True, exist_ok=True)
        return {'kind': kind, 'root': str(root), 'directories': directories,
                'dataCopied': False, 'gitCreated': False}


def parse_portable_json(raw, max_bytes=MAX_CONFIG):
    """Bound raw import before parsing, without touching a source folder."""
    error = "Invalid portable JSON"
    try:
        if isinstance(raw, str):
            raw = raw.encode("utf-8", errors="strict")
        if not isinstance(raw, bytes) or len(raw) > max_bytes:
            raise SourceError(error)
        text = raw.decode("utf-8", errors="strict")
        depth, quoted, escaped = 0, False, False
        for char in text:
            if quoted:
                if escaped: escaped = False
                elif char == "\\": escaped = True
                elif char == '"': quoted = False
            elif char == '"': quoted = True
            elif char in "[{":
                depth += 1
                if depth > 16: raise SourceError(error)
            elif char in "]}":
                depth -= 1
                if depth < 0: raise SourceError(error)
        def pairs(rows):
            result = {}
            for key, value in rows:
                if key in result: raise SourceError(error)
                result[key] = value
            return result
        def constant(_): raise SourceError(error)
        def number(value):
            result = float(value)
            if not math.isfinite(result): raise SourceError(error)
            return result
        return json.loads(text, object_pairs_hook=pairs, parse_constant=constant, parse_float=number)
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise SourceError(error) from exc


def import_document(value):
    """Shared per-app shape, wrapped for Agent City's two summary sources.

Native Cicada section IDs and placements require its own adapter; this bundle
is deliberately scoped to Agent City and never rewrites a Cicada config.
"""
    if not isinstance(value, dict) or set(value) != {'schemaVersion', 'appId', 'profiles'} or type(value['schemaVersion']) is not int or value['schemaVersion'] != 1 or value['appId'] != 'agent-city':
        raise SourceError('Неверный формат переносимой конфигурации.')
    if len(canonical(value)) > MAX_CONFIG:
        raise SourceError('Конфигурация слишком велика.')
    if not isinstance(value['profiles'], list) or not 1 <= len(value['profiles']) <= 2:
        raise SourceError('Неверный список профилей источников.')
    manifest = {'schemaVersion': 1, 'sources': [], 'sections': []}
    for profile in value['profiles']:
        if not isinstance(profile, dict) or set(profile) != {'id', 'repositoryKind', 'config'}:
            raise SourceError('Конфигурация содержит неподдерживаемые поля.')
        doc = profile['config']; kind = profile['repositoryKind']
        fields = {'schemaVersion', 'appId', 'source', 'structureVersion', 'localGit', 'sections', 'refresh', 'onboarding'}
        if not isinstance(doc, dict) or set(doc) != fields or not isinstance(kind, str) or kind not in KINDS:
            raise SourceError('Конфигурация содержит неподдерживаемые поля.')
        if type(doc['schemaVersion']) is not int or doc['schemaVersion'] != 1 or doc['appId'] != 'agent-city' or type(doc['structureVersion']) is not int or doc['structureVersion'] != 1:
            raise SourceError('Неверная версия или приложение конфигурации.')
        if doc['source'] != {'kind': 'directory', 'path': None} or doc['localGit'] is not False or doc['refresh'] != {'mode': 'manual'} or doc['onboarding'] != {'status': 'skipped'}:
            raise SourceError('Переносимая конфигурация не должна содержать локальные пути или права записи.')
        rows = doc['sections']
        if not isinstance(rows, list) or not 1 <= len(rows) <= len(SECTIONS):
            raise SourceError('Неверный список разделов.')
        orders = set()
        for row in rows:
            if not isinstance(row, dict) or set(row) != {'id', 'visible', 'placement', 'order'} or type(row['order']) is not int or not 0 <= row['order'] < len(SECTIONS) or row['order'] in orders:
                raise SourceError('Неверный порядок разделов.')
            ident = row['id']
            if not isinstance(ident, str) or ident not in SECTIONS or SECTIONS[ident][0] != kind:
                raise SourceError('Неверный раздел источника.')
            orders.add(row['order'])
        manifest['sources'].append({'id': profile['id'], 'kind': kind, 'root': '../' + kind, 'mode': 'read-only'})
        for row in sorted(rows, key=lambda row: row['order']):
            manifest['sections'].append({'id': row['id'], 'sourceId': profile['id'], 'path': SECTIONS[row['id']][1],
                                         'visible': row['visible'], 'placement': row['placement']})
    return validate_manifest(manifest)
