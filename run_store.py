"""Reported agent work, never inferred from open windows or skill discovery."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import threading


class RunError(ValueError):
    pass


class RunConflict(RunError):
    pass


MAX_BYTES = 4 * 1024 * 1024
PUBLIC_FIELDS = {'updatedAt', 'firstReportedAt', 'history', 'runId', 'sequence', 'taskKey', 'agent', 'model', 'provider', 'stage', 'status', 'skillIds', 'mcpCalls', 'inputTokens', 'outputTokens'}

STATUSES = {'running', 'waiting', 'done', 'error', 'cancelled'}
FIELDS = {'runId', 'sequence', 'taskKey', 'agent', 'model', 'provider', 'stage', 'status', 'skillIds', 'mcpCalls', 'inputTokens', 'outputTokens'}


def token_count(value):
    return value if type(value) is int and 0 <= value <= 10**12 else None


def validate(payload):
    if not isinstance(payload, dict) or set(payload) - FIELDS:
        raise RunError('unsupported run fields')
    row = {key: payload.get(key) for key in FIELDS}
    if not isinstance(row['runId'], str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,100}', row['runId']):
        raise RunError('invalid run ID')
    if type(row['sequence']) is not int or not 1 <= row['sequence'] <= 10**9:
        raise RunError('sequence must increase')
    if not isinstance(row['status'], str) or not isinstance(row['agent'], str) or row['status'] not in STATUSES or row['agent'] not in {'codex', 'claude', 'other', 'agent-city'}:
        raise RunError('invalid agent or status')
    if row['taskKey'] is not None and (not isinstance(row['taskKey'], str) or not re.fullmatch(r'cicada-[a-f0-9]{16}-[A-Za-z0-9_-]{1,80}', row['taskKey'])):
        raise RunError('invalid task key')
    for key, limit in [('model', 200), ('provider', 80), ('stage', 120)]:
        value = row[key]
        if value is not None and (not isinstance(value, str) or not value.strip() or len(value) > limit or any(ord(c) < 32 for c in value)):
            raise RunError('invalid run label')
    if row['skillIds'] is None:
        row['skillIds'] = []
    if not isinstance(row['skillIds'], list) or len(row['skillIds']) > 40 or any(not isinstance(s, str) or not re.fullmatch(r'skill-[a-f0-9]{24}', s) for s in row['skillIds']):
        raise RunError('invalid skill IDs')
    row['skillIds'] = sorted(set(row['skillIds']))
    if row['mcpCalls'] is not None:
        if not isinstance(row['mcpCalls'], list) or len(row['mcpCalls']) > 30:
            raise RunError('invalid MCP counters')
        seen = set()
        for call in row['mcpCalls']:
            if not isinstance(call, dict) or set(call) != {'server', 'tool', 'calls'}:
                raise RunError('MCP arguments and results are not accepted')
            for key in ('server', 'tool'):
                if not isinstance(call[key], str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,100}', call[key]):
                    raise RunError('MCP technical identifier required')
            pair = (call['server'], call['tool'])
            if pair in seen or token_count(call['calls']) is None:
                raise RunError('invalid MCP counters')
            seen.add(pair)
        row['mcpCalls'] = sorted(row['mcpCalls'], key=lambda call: (call['server'], call['tool']))
    for key in ('inputTokens', 'outputTokens'):
        if row[key] is not None and token_count(row[key]) is None:
            raise RunError('token usage must be a reported nonnegative integer or null')
    return row


class RunStore:
    def __init__(self, directory):
        self.path = Path(directory).resolve() / 'agent-runs.json'
        self.lock = threading.RLock()

    def _read(self):
        if not self.path.exists():
            return {'schemaVersion': 1, 'runs': {}}
        if self.path.is_symlink() or getattr(self.path.lstat(), 'st_file_attributes', 0) & 0x400:
            raise RunError('unsafe run storage')
        with self.path.open('rb') as stream:
            raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise RunError('run storage is too large')
        data = json.loads(raw)
        if not isinstance(data, dict) or set(data) != {'schemaVersion', 'runs'} or type(data.get('schemaVersion')) is not int or data['schemaVersion'] != 1 or not isinstance(data.get('runs'), dict) or len(data['runs']) > 500:
            raise RunError('invalid run storage')
        metadata = {'updatedAt', 'firstReportedAt', '_digest', 'history'}
        history_fields = {'stage', 'status', 'skillIds', 'mcpCalls', 'inputTokens', 'outputTokens', 'reportedAt'}
        for ident, saved in data['runs'].items():
            # Earlier v1 reports predate MCP counters. Normalize only that
            # documented shape in memory; reading must never rewrite history.
            if isinstance(saved, dict) and set(saved) == (FIELDS | metadata) - {'mcpCalls'}:
                saved['mcpCalls'] = None
            if not isinstance(saved, dict) or set(saved) != FIELDS | metadata or saved.get('runId') != ident:
                raise RunError('invalid stored run fields')
            validate({key: saved[key] for key in FIELDS})
            if not all(isinstance(saved[key], str) for key in ('updatedAt', 'firstReportedAt', '_digest')):
                raise RunError('invalid stored run metadata')
            history = saved['history']
            if not isinstance(history, list) or len(history) > 30:
                raise RunError('invalid stored run history')
            for item in history:
                if isinstance(item, dict) and set(item) == {'stage', 'status', 'reportedAt'}:
                    # Old stage events did not record resource usage. Do not
                    # copy today's cumulative totals back into earlier events.
                    item.update(skillIds=[], mcpCalls=None, inputTokens=None, outputTokens=None)
                if not isinstance(item, dict) or set(item) != history_fields or not isinstance(item['reportedAt'], str):
                    raise RunError('invalid stored run history')
                previous = {key: saved[key] for key in FIELDS}
                previous.update({key: value for key, value in item.items() if key != 'reportedAt'})
                validate(previous)
        return data

    def snapshot(self):
        with self.lock:
            rows = list(self._read()['runs'].values())
        return sorted(rows, key=lambda row: row['updatedAt'], reverse=True)

    @staticmethod
    def _advance(row, old, count):
        if old:
            previous = validate({key: old.get(key) for key in FIELDS})
            if row['sequence'] == old['sequence'] and previous == row:
                return False
            if row['sequence'] <= old['sequence']:
                raise RunConflict('a newer report already exists')
            if any(row[key] != old[key] for key in ('agent', 'taskKey', 'model', 'provider')):
                raise RunError('a different task or executor needs a new run ID')
            for key in ('inputTokens', 'outputTokens'):
                if old[key] is not None and (row[key] is None or row[key] < old[key]):
                    raise RunError('usage totals must not decrease')
            counters = {(c['server'], c['tool']): c['calls'] for c in row['mcpCalls'] or []}
            if any(counters.get((c['server'], c['tool']), -1) < c['calls'] for c in old.get('mcpCalls') or []):
                raise RunError('MCP totals must not decrease')
        elif count >= 500:
            raise RunError('run storage limit reached')
        return True

    def preview(self, payload):
        row = validate(payload)
        with self.lock:
            data = self._read()
            changed = self._advance(row, data['runs'].get(row['runId']), len(data['runs']))
            return {'changed':changed, 'report':row}

    def report(self, payload):
        row = validate(payload)
        digest = hashlib.sha256(json.dumps(row, sort_keys=True).encode()).hexdigest()
        with self.lock:
            data = self._read()
            old = data['runs'].get(row['runId'])
            self._advance(row, old, len(data['runs']))
            if old and row['sequence'] == old['sequence']:
                return {key: value for key, value in old.items() if not key.startswith('_')}
            stamp = datetime.now(timezone.utc).isoformat(timespec='seconds')
            row.update(updatedAt=stamp, firstReportedAt=old['firstReportedAt'] if old else stamp, _digest=digest)
            history = list(old.get('history', [])) if old else []
            tracked = ('stage', 'status', 'skillIds', 'mcpCalls', 'inputTokens', 'outputTokens')
            if not old or any(row[key] != old.get(key) for key in tracked):
                history.append({**{key: row[key] for key in tracked}, 'reportedAt': stamp})
            row['history'] = history[-30:]
            data['runs'][row['runId']] = row
            raw = json.dumps(data, ensure_ascii=False, allow_nan=False).encode('utf-8')
            if len(raw) > MAX_BYTES:
                raise RunError('run storage limit reached')
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, name = tempfile.mkstemp(dir=self.path.parent, prefix='.runs-')
            try:
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(raw)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(name, self.path)
            finally:
                if os.path.exists(name):
                    os.unlink(name)
            return {key: value for key, value in row.items() if not key.startswith('_')}
