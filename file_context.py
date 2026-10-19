"""Local grants and a rebuildable metadata cache. No HTTP path or shell authority."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat as stat_mode
import tempfile
import threading
import time

from skill_inventory import _metadata, _reparse, SkillInventoryError, SkillInventory
from text_reader import canonical, read_text, slice_text
from codex_controls import _reject_redirects, CodexControlsError

MAX_FILE = 2 * 1024 * 1024
MAX_FILES = 10000
EXTENSIONS = {'.md', '.txt', '.rst', '.py', '.js', '.ts', '.tsx', '.jsx', '.html', '.css', '.toml', '.yaml', '.yml', '.json', '.csv'}
EXCLUDED = {'.git', 'node_modules', '__pycache__', '.venv', 'venv', '.ssh', '.aws', '.cache', 'archives', 'archive'}


class ContextError(ValueError):
    def __init__(self, code, status=400, **details):
        self.code, self.status, self.details = code, status, details
        super().__init__(code)


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def opaque(prefix, value):
    return prefix + '-' + digest(value.encode('utf-8'))[:24]


def number(value, default, minimum, maximum):
    if value is None:
        return default
    if isinstance(value, bool) or not str(value).isdigit():
        raise ContextError('invalid_limit')
    result = int(value)
    if not minimum <= result <= maximum:
        raise ContextError('invalid_limit')
    return result


def params(query, allowed):
    if set(query) - set(allowed) or any(len(v) != 1 for v in query.values()):
        raise ContextError('unsupported_parameters')
    result = {k: v[0] for k, v in query.items()}
    if any(not isinstance(v, str) or len(v) > 300 for v in result.values()):
        raise ContextError('invalid_parameters')
    return result


def private_path(path):
    try:
        _reject_redirects(path)
        if path.exists() and path.is_file() and path.stat().st_nlink != 1:
            raise ContextError('unsafe_context_storage', 503)
    except CodexControlsError:
        raise ContextError('unsafe_context_storage', 503) from None


@contextmanager
def config_lock(path):
    """Serialise CAS across host CLI processes as well as threads."""
    private_path(path)
    with path.open('a+b') as stream:
        stream.seek(0)
        if os.name == 'nt':
            import msvcrt
            if not stream.read(1):
                stream.write(b'0'); stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == 'nt':
                stream.seek(0); msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def safe_name(path):
    name = path.name.casefold()
    return (path.suffix.casefold() in EXTENSIONS and not name.startswith('.')
            and not any(word in name for word in ('secret', 'credential', 'private-key', 'token', '.dpapi')))


class FileContext:
    def __init__(self, directory, inventory=None, repos=None, skills=None):
        self.directory = Path(directory)
        private_path(self.directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / 'context-grants.json'
        self.db_path = self.directory / 'context-index.sqlite3'
        private_path(self.path)
        private_path(self.db_path)
        self.inventory, self.repos, self.skills = inventory, repos, skills
        self.lock = threading.RLock()
        with config_lock(self.directory / 'context-grants.lock'):
            if not self.path.exists():
                self._save({'schemaVersion': 1, 'device': {'id': opaque('device', os.urandom(32).hex()), 'name': 'Local device'}, 'roots': []})
        with self._db():
            pass

    def _save(self, value):
        private_path(self.path)
        fd, temporary = tempfile.mkstemp(prefix='context-', suffix='.tmp', dir=self.directory)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(json.dumps(value, ensure_ascii=False, sort_keys=True).encode('utf-8'))
                stream.flush(); os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def config(self):
        private_path(self.path)
        with self.path.open('rb') as stream:
            raw = stream.read(256 * 1024 + 1)
        if len(raw) > 256 * 1024:
            raise ContextError('invalid_grants', 503)
        try:
            value = json.loads(raw)
            if value['schemaVersion'] != 1 or not isinstance(value['roots'], list) or len(value['roots']) > 100:
                raise ValueError()
            if not isinstance(value['device']['id'], str) or not value['device']['id'].startswith('device-'):
                raise ValueError()
            for root in value['roots']:
                if (not isinstance(root, dict) or root.get('deviceId') != value['device']['id']
                        or type(root.get('enabled')) is not bool
                        or any(not isinstance(root.get(key), str) for key in ('id', 'path', 'canonicalPath', 'label', 'source', 'representation', 'canonicalRootId', 'grantedAt'))
                        or not Path(root['path']).is_absolute() or not Path(root['canonicalPath']).is_absolute()
                        or root['path'].startswith(('\\\\', '//')) or root['canonicalPath'].startswith(('\\\\', '//'))):
                    raise ValueError()
        except (ValueError, KeyError, TypeError):
            raise ContextError('invalid_grants', 503) from None
        return value, digest(raw)

    def grant(self, path, label, revision, source='file'):
        """Host-only configuration. Never called from HTTP/MCP arguments."""
        candidate = Path(path)
        if not candidate.is_absolute() or str(candidate).startswith(('\\\\', '//')) or not candidate.is_dir():
            raise ContextError('invalid_root')
        if not label or len(label) > 100 or source not in {'file', 'workspace', 'installed', 'plugin-cache'}:
            raise ContextError('invalid_root')
        target = canonical(candidate)
        with self.lock, config_lock(self.directory / 'context-grants.lock'):
            config, current = self.config()
            if revision != current:
                raise ContextError('grants_changed', 409, revision=current)
            device = config['device']['id']
            ident = opaque('root', device + '\n' + os.path.normcase(str(candidate.absolute())))
            row = {'id': ident, 'deviceId': device, 'label': label, 'path': str(candidate.absolute()),
                   'canonicalPath': target, 'canonicalRootId': opaque('root', device + '\n' + target),
                   'source': source, 'representation': 'link' if any(_reparse(p) for p in (candidate, *candidate.parents)) else 'alias' if os.path.normcase(str(candidate.absolute())) != target else 'source',
                   'grantedAt': now(), 'enabled': True}
            config['roots'] = [r for r in config['roots'] if r['id'] != ident] + [row]
            self._save(config)
        return self.roots()

    def revoke(self, ident, revision):
        with self.lock, config_lock(self.directory / 'context-grants.lock'):
            config, current = self.config()
            if revision != current:
                raise ContextError('grants_changed', 409, revision=current)
            row = next((r for r in config['roots'] if r['id'] == ident), None)
            if row is None:
                raise ContextError('root_unknown', 404)
            row['enabled'] = False
            self._save(config)
        return self.roots()

    def devices(self):
        config, revision = self.config()
        return {'schemaVersion': 1, 'revision': revision, 'devices': [{**config['device'], 'local': True, 'available': True}],
                'remoteAccess': 'unavailable; grants and content stay local'}

    def roots(self):
        config, revision = self.config()
        suggestions = []
        if self.repos is not None:
            suggestions.extend({'repositoryId': r['id'], 'label': r['name'], 'source': 'repository', 'granted': False}
                               for r in self.repos.list()[:10])
        if self.skills is not None:
            suggestions.append({'label': 'Workspace skills', 'source': 'workspace', 'granted': False})
        # Public discovery needs identities and status; filesystem authority stays in config/root.
        public_fields = ('id', 'deviceId', 'label', 'source', 'representation', 'canonicalRootId', 'grantedAt', 'enabled')
        public_roots = [{key: root[key] for key in public_fields} for root in config['roots']]
        return {'schemaVersion': 1, 'revision': revision, 'deviceId': config['device']['id'], 'roots': public_roots,
                'suggestions': suggestions, 'notice': 'Suggestions reuse repository/skill stores; only roots with enabled=true grant access.'}

    def root(self, device, ident):
        config, revision = self.config()
        if device != config['device']['id']:
            raise ContextError('device_unavailable', 404)
        row = next((r for r in config['roots'] if r['id'] == ident), None)
        if row is None:
            raise ContextError('root_unknown', 404)
        if not row['enabled']:
            raise ContextError('access_revoked', 403)
        try:
            if canonical(Path(row['path'])) != row['canonicalPath']:
                raise ContextError('root_redirected', 403)
        except OSError:
            raise ContextError('root_missing', 410) from None
        return row, revision

    @contextmanager
    def _db(self):
        for path in (self.db_path, *(Path(str(self.db_path) + suffix) for suffix in ('-journal', '-wal', '-shm'))):
            private_path(path)
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute('CREATE TABLE IF NOT EXISTS files (root_id TEXT, file_id TEXT, relative TEXT, kind TEXT, size INTEGER, mtime INTEGER, hash TEXT, indexed_at TEXT, name TEXT, description TEXT, PRIMARY KEY(root_id,file_id))')
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _path(self, root, relative):
        base = Path(root['canonicalPath'])
        path = base / relative
        try:
            target = path.resolve(strict=True)
            target.relative_to(base)
            current = base
            for part in Path(relative).parts:
                if part in {'..', '.', ''}:
                    raise ContextError('outside_root', 403)
                current = current / part
                if _reparse(current):
                    raise ContextError('alias_denied', 403)
            if not safe_name(path) or not path.is_file():
                raise ContextError('file_type_denied', 403)
            return path
        except (FileNotFoundError, NotADirectoryError):
            raise ContextError('file_missing', 410) from None
        except (OSError, ValueError):
            raise ContextError('outside_root', 403) from None

    def _read(self, root, relative):
        path = self._path(root, relative)
        try:
            return read_text(path, Path(root['canonicalPath']), MAX_FILE)
        except UnicodeError:
            raise ContextError('encoding_unsupported', 415) from None
        except (OSError, ValueError):
            raise ContextError('file_unavailable', 410) from None

    def refresh(self, root):
        started = time.monotonic()
        count, seen, denied = 0, set(), 0
        with self._db() as db:
            old = {r['relative']: dict(r) for r in db.execute('SELECT * FROM files WHERE root_id=?', (root['id'],))}
            for directory, children, files in os.walk(root['canonicalPath'], followlinks=False):
                if time.monotonic() - started > 10:
                    raise ContextError('scan_limit_exceeded', 413)
                if canonical(Path(directory)) != os.path.normcase(str(Path(directory).absolute())):
                    children[:] = []
                    denied += 1
                    continue
                children[:] = sorted(d for d in children if d.casefold() not in EXCLUDED and not d.startswith('.') and not _reparse(Path(directory) / d))
                for name in sorted(files):
                    path = Path(directory) / name
                    count += 1
                    if count > MAX_FILES or time.monotonic() - started > 10:
                        raise ContextError('scan_limit_exceeded', 413)
                    if not safe_name(path):
                        continue
                    relative = path.relative_to(root['canonicalPath']).as_posix()
                    try:
                        stat = path.lstat()
                        if _reparse(path) or not stat_mode.S_ISREG(stat.st_mode) or stat.st_size > MAX_FILE or stat.st_nlink > 1:
                            continue
                        cached = old.get(relative)
                        if cached and (cached['size'], cached['mtime']) == (stat.st_size, stat.st_mtime_ns):
                            row = cached
                        else:
                            raw, text, stat = self._read(root, relative)
                            skill = name == 'SKILL.md'
                            title, description = _metadata(text) if skill else (name, '')
                            ident = opaque('skill', str(path.resolve(strict=True))) if skill else opaque('file', root['deviceId'] + '\n' + canonical(path))
                            row = {'root_id': root['id'], 'file_id': ident,
                                   'relative': relative, 'kind': 'skill' if skill else 'text', 'size': stat.st_size,
                                   'mtime': stat.st_mtime_ns, 'hash': digest(raw), 'indexed_at': now(), 'name': title[:200], 'description': description[:600]}
                        seen.add(row['file_id'])
                        db.execute('INSERT OR REPLACE INTO files VALUES (:root_id,:file_id,:relative,:kind,:size,:mtime,:hash,:indexed_at,:name,:description)', row)
                    except (ContextError, SkillInventoryError, OSError):
                        denied += 1
            for row in old.values():
                if row['file_id'] not in seen:
                    # Tombstone ID remains for specific missing/redirected diagnostics on read.
                    db.execute('UPDATE files SET indexed_at=NULL WHERE root_id=? AND file_id=?', (root['id'], row['file_id']))
        return denied

    @staticmethod
    def public(row, root):
        return {'id': row['file_id'], 'deviceId': root['deviceId'], 'rootId': root['id'], 'relativePath': row['relative'],
                'kind': row['kind'], 'name': row['name'], 'description': row['description'], 'size': row['size'],
                'mtimeNs': row['mtime'], 'revision': row['hash'], 'hash': row['hash'], 'indexedAt': row['indexed_at'],
                'hashStatus': 'indexed_snapshot; read verifies current content',
                'source': {'rootId': root['id'], 'kind': root['source'], 'representation': root['representation'],
                           'canonicalFileId': row['file_id'], 'snapshotAt': row['indexed_at']}}

    def search(self, values):
        allowed = {'deviceId', 'rootId', 'q', 'kind', 'extension', 'limit', 'offset', 'revision'}
        if set(values) - allowed:
            raise ContextError('unsupported_parameters')
        root, grant_revision = self.root(values.get('deviceId'), values.get('rootId'))
        limit = number(values.get('limit'), 20, 1, 50)
        offset = number(values.get('offset'), 0, 0, MAX_FILES)
        query = values.get('q', '').casefold()
        kind = values.get('kind', '')
        extension = values.get('extension', '').casefold()
        if len(query) > 200 or kind not in {'', 'skill', 'text'} or (extension and extension not in EXTENSIONS):
            raise ContextError('invalid_filter')
        with self.lock:
            skipped = self.refresh(root)
            # A concurrent revoke must also prevent metadata responses.
            _, current_grants = self.root(root['deviceId'], root['id'])
            if current_grants != grant_revision:
                raise ContextError('grants_changed', 409, revision=current_grants)
            with self._db() as db:
                rows = [dict(r) for r in db.execute('SELECT * FROM files WHERE root_id=? AND indexed_at IS NOT NULL ORDER BY relative', (root['id'],))]
        rows = [r for r in rows if (not query or query in (r['relative'] + ' ' + r['name'] + ' ' + r['description']).casefold())
                and (not kind or r['kind'] == kind) and (not extension or r['relative'].casefold().endswith(extension))]
        revision = digest(json.dumps([grant_revision, [(r['file_id'], r['hash']) for r in rows]], sort_keys=True).encode())
        if values.get('revision') and values['revision'] != revision:
            raise ContextError('index_changed', 409, revision=revision)
        selected = rows[offset:offset + limit]
        return {'schemaVersion': 1, 'revision': revision, 'grantsRevision': grant_revision, 'total': len(rows),
                'offset': offset, 'limit': limit, 'nextOffset': offset + limit if offset + limit < len(rows) else None,
                'skipped': skipped, 'files': [self.public(r, root) for r in selected]}

    def read(self, values, *, skill_only=False):
        if set(values) - {'deviceId', 'rootId', 'id', 'revision', 'startLine', 'endLine', 'maxBytes', 'byteOffset'}:
            raise ContextError('unsupported_parameters')
        root, grant_revision = self.root(values.get('deviceId'), values.get('rootId'))
        start = number(values.get('startLine'), 1, 1, 1000000)
        end = number(values.get('endLine'), start + 99, start, start + 199)
        cap = number(values.get('maxBytes'), 8192, 1, 32768)
        byte_offset = number(values.get('byteOffset'), 0, 0, MAX_FILE)
        with self.lock, self._db() as db:
            row = db.execute('SELECT * FROM files WHERE root_id=? AND file_id=?', (root['id'], values.get('id'))).fetchone()
            if row is None:
                raise ContextError('file_unknown; search_first', 404)
            if skill_only and row['kind'] != 'skill':
                raise ContextError('not_a_skill', 400)
            checked = self._path(root, row['relative'])
            expected_id = opaque('skill', str(checked.resolve(strict=True))) if row['kind'] == 'skill' else opaque('file', root['deviceId'] + '\n' + canonical(checked))
            if row['file_id'] != expected_id:
                raise ContextError('index_invalid; rebuild_cache', 409)
            if row['kind'] == 'skill':
                # Extend the existing skill ID reader, with this grant as its fixed authority.
                path = self._path(root, row['relative'])
                inventory = SkillInventory([('granted', Path(root['canonicalPath']))], max_size=MAX_FILE)
                try:
                    skill_id = inventory.enumerate_document(path)
                    document = inventory.read(skill_id)
                except (SkillInventoryError, ValueError, OSError):
                    raise ContextError('skill_unavailable', 410) from None
                text, revision = document['content'], document['revision']
                size, mtime = document['size'], document['mtimeNs']
            else:
                raw, text, stat = self._read(root, row['relative'])
                revision, size, mtime = digest(raw), stat.st_size, stat.st_mtime_ns
                skill_id = None
            if values.get('revision') and values['revision'] != revision:
                raise ContextError('file_changed', 409, revision=revision, previousRevision=values['revision'])
            try:
                chunk = slice_text(text, start, end, cap, byte_offset)
            except ValueError as exc:
                raise ContextError(str(exc)) from None
            _, current_grants = self.root(root['deviceId'], root['id'])
            if current_grants != grant_revision:
                raise ContextError('grants_changed', 409, revision=current_grants)
            item = self.public(dict(row), root)
            item.update(chunk, revision=revision, hash=revision, size=size, mtimeNs=mtime,
                        readAt=now(), maxBytes=cap, changedSinceIndex=row['hash'] != revision,
                        grantsRevision=grant_revision, skillId=skill_id)
            return {'schemaVersion': 1, **item}
