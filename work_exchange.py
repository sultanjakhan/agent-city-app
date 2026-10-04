"""Explicit offline projections; no dispatcher, network or native task writes."""
from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import secrets
import threading
import time

from codex_controls import _atomic, _reject_redirects, CodexControlsError
from data_sources import parse_portable_json
from run_store import validate as validate_report, FIELDS

def safe_path(path):
    try:
        _reject_redirects(path)
    except CodexControlsError as exc:
        raise ExchangeError('unsafe_exchange_path') from exc


MAX_FILE = 1024 * 1024
MAX_STORE = 4 * MAX_FILE
ID = re.compile(r'^[A-Za-z0-9_-]{1,100}$')
UUID = re.compile(r'^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$')
STATES = {'planned','running','waiting','checking','decision-needed','done','error','cancelled','unknown'}


class ExchangeError(ValueError):
    pass


class ExchangeConflict(ExchangeError):
    pass


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def exact(value, fields):
    if not isinstance(value, dict) or set(value) != set(fields):
        raise ExchangeError('unsupported_exchange_fields')


def namespace(value):
    if not isinstance(value, str) or not UUID.fullmatch(value):
        raise ExchangeError('invalid_source_namespace')
    return value


def ident(value):
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise ExchangeError('invalid_registry_id')


def text(value, maximum):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or any(ord(c) < 32 for c in value):
        raise ExchangeError('invalid_public_label')


def timestamp(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,3})?Z', value):
        raise ExchangeError('invalid_registry_timestamp')
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise ExchangeError('invalid_registry_timestamp') from exc


def strict_json(raw, limit=MAX_FILE):
    try:
        return parse_portable_json(raw, max_bytes=limit)
    except (ValueError, TypeError) as exc:
        raise ExchangeError('invalid_exchange_json') from exc


def validate_binding(binding):
    exact(binding, ('sourceNamespace','sourceType','sourceId','taskKey'))
    ns = namespace(binding['sourceNamespace'])
    if binding['sourceType'] != 'note' or not isinstance(binding['sourceId'], str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', binding['sourceId']):
        raise ExchangeError('invalid_native_binding')
    expected = 'cicada-' + hashlib.sha256(ns.encode('utf-8')).hexdigest()[:16] + '-' + binding['sourceId']
    if binding['taskKey'] != expected:
        raise ExchangeError('invalid_native_binding')
    return copy.deepcopy(binding)


def validate_registry(snapshot):
    exact(snapshot, ('schemaVersion','kind','snapshotId','sequence','source','publishedAt','staleAfterSeconds','projects','tasks','runs'))
    if type(snapshot['schemaVersion']) is not int or snapshot['schemaVersion'] != 1 or snapshot['kind'] != 'work-registry-snapshot':
        raise ExchangeError('invalid_registry_schema')
    ident(snapshot['snapshotId'])
    if type(snapshot['sequence']) is not int or not 1 <= snapshot['sequence'] <= 2**53-1:
        raise ExchangeError('invalid_registry_sequence')
    exact(snapshot['source'], ('publisherId','sourceNamespace','mode'))
    ident(snapshot['source']['publisherId']); namespace(snapshot['source']['sourceNamespace'])
    if snapshot['source']['mode'] != 'published-snapshot': raise ExchangeError('unsupported_registry_mode')
    published = timestamp(snapshot['publishedAt'])
    if type(snapshot['staleAfterSeconds']) is not int or not 60 <= snapshot['staleAfterSeconds'] <= 604800:
        raise ExchangeError('invalid_freshness_policy')
    projects, tasks = snapshot['projects'], snapshot['tasks']
    if not isinstance(projects, list) or len(projects) > 100 or not isinstance(tasks, list) or len(tasks) > 1000 or snapshot['runs'] != []:
        raise ExchangeError('unsupported_registry_contents')
    project_ids, by_id = set(), {}
    for project in projects:
        exact(project, ('id','title')); ident(project['id']); text(project['title'], 200)
        if project['id'] in project_ids: raise ExchangeError('duplicate_registry_id')
        project_ids.add(project['id'])
    for task in tasks:
        exact(task, ('id','projectId','parentTaskId','title','relationship','status','lastUpdated','provenance','operation','waitingFor','result','localBinding'))
        ident(task['id']); ident(task['projectId']); text(task['title'], 500)
        if task['id'] in by_id or task['projectId'] not in project_ids: raise ExchangeError('invalid_registry_relationship')
        if not isinstance(task['status'], str) or task['status'] not in STATES or task['relationship'] not in ('root','parallel','sequential'):
            raise ExchangeError('invalid_registry_status')
        if (task['parentTaskId'] is None) != (task['relationship'] == 'root'): raise ExchangeError('invalid_registry_relationship')
        if task['parentTaskId'] is not None: ident(task['parentTaskId'])
        if timestamp(task['lastUpdated']) > published: raise ExchangeError('invalid_registry_timestamp')
        exact(task['provenance'], ('kind','reference'))
        if task['provenance']['kind'] != 'parent-published': raise ExchangeError('unsupported_provenance')
        text(task['provenance']['reference'], 500)
        for field in ('operation','waitingFor','result'):
            if task[field] is not None: text(task[field], 2000)
        if task['localBinding'] is not None: validate_binding(task['localBinding'])
        by_id[task['id']] = task
    for task in tasks:
        seen, parent = {task['id']}, task['parentTaskId']
        while parent is not None:
            ancestor = by_id.get(parent)
            if not ancestor or ancestor['projectId'] != task['projectId'] or parent in seen:
                raise ExchangeError('invalid_registry_relationship')
            seen.add(parent); parent = ancestor['parentTaskId']
    if len(canonical(snapshot)) > MAX_FILE: raise ExchangeError('exchange_file_too_large')
    return copy.deepcopy(snapshot)


def validate_envelope(value):
    if not isinstance(value, dict): raise ExchangeError('invalid_exchange_envelope')
    kind = value.get('kind')
    if kind == 'work-registry-snapshot': return validate_registry(value)
    fields = ('schemaVersion','kind','binding') if kind == 'cicada-task-binding' else ('schemaVersion','kind','binding','report')
    exact(value, fields)
    if type(value['schemaVersion']) is not int or value['schemaVersion'] != 1 or kind not in ('cicada-task-binding','cicada-run-report'):
        raise ExchangeError('invalid_exchange_envelope')
    result = copy.deepcopy(value); result['binding'] = validate_binding(value['binding'])
    if kind == 'cicada-run-report':
        try: result['report'] = validate_report(value['report'])
        except ValueError as exc: raise ExchangeError('invalid_run_report') from exc
        if result['report']['taskKey'] != result['binding']['taskKey']: raise ExchangeError('report_binding_mismatch')
    return result


def freshness(snapshot, task, now=None):
    now = now or datetime.now(timezone.utc)
    try:
        published, updated = timestamp(snapshot['publishedAt']), timestamp(task['lastUpdated'])
        if published > now or updated > now: return 'unknown'
        return 'stale' if (now-updated).total_seconds() > snapshot['staleAfterSeconds'] else 'fresh'
    except (ValueError, TypeError): return 'unknown'


class WorkExchange:
    def __init__(self, directory, connector, runs):
        self.path = Path(directory) / 'work-exchange.json'
        self.connector, self.runs = connector, runs
        self.lock = threading.RLock(); self.previews = {}

    def _read(self):
        safe_path(self.path)
        if not self.path.exists(): return {'schemaVersion':1,'bindings':{},'publishers':{}}, 'none'
        with self.path.open('rb') as stream: raw = stream.read(MAX_STORE+1)
        value = strict_json(raw, limit=MAX_STORE)
        exact(value, ('schemaVersion','bindings','publishers'))
        if type(value['schemaVersion']) is not int or value['schemaVersion'] != 1 or not isinstance(value['bindings'], dict) or not isinstance(value['publishers'], dict) or len(value['bindings']) > 500 or len(value['publishers']) > 20:
            raise ExchangeError('invalid_exchange_storage')
        for key, paired in value['bindings'].items():
            exact(paired, ('binding','source')); binding = validate_binding(paired['binding'])
            exact(paired['source'], ('selectedId','profile','sourceNamespace'))
            if key != binding['taskKey'] or paired['source']['sourceNamespace'] != binding['sourceNamespace'] or paired['source']['selectedId'] not in ('production','dev') or paired['source']['profile'] != paired['source']['selectedId']: raise ExchangeError('invalid_exchange_storage')
        for key, entry in value['publishers'].items():
            exact(entry, ('snapshot','receivedAt')); validate_registry(entry['snapshot']); timestamp(entry['receivedAt'])
            if key != self.publisher_key(entry['snapshot']): raise ExchangeError('invalid_exchange_storage')
        return value, hashlib.sha256(raw).hexdigest()

    @staticmethod
    def publisher_key(snapshot):
        return snapshot['source']['publisherId'] + ':' + snapshot['source']['sourceNamespace']

    def bindings(self):
        with self.lock: return self._read()[0]['bindings']

    def snapshot(self):
        with self.lock:
            value, revision = self._read()
            for entry in value['publishers'].values():
                for task in entry['snapshot']['tasks']: task['freshness'] = freshness(entry['snapshot'], task)
            return {**value,'revision':revision,'executionSupported':False,'republicationSupported':False}

    def _check(self, envelope, state):
        kind = envelope['kind']
        if kind == 'work-registry-snapshot':
            old = state['publishers'].get(self.publisher_key(envelope))
            if old and envelope['sequence'] <= old['snapshot']['sequence']:
                if envelope['sequence'] == old['snapshot']['sequence'] and canonical(envelope) == canonical(old['snapshot']): return False, None
                raise ExchangeConflict('registry_sequence_conflict')
            return True, None
        binding = envelope['binding']; source = self.connector.authorize_binding(binding)
        previous = state['bindings'].get(binding['taskKey'])
        if previous and previous['binding'] != binding: raise ExchangeConflict('binding_identity_conflict')
        if previous and previous['source'] != source: raise ExchangeConflict('source_profile_conflict')
        if kind == 'cicada-run-report' and (not previous or previous['binding'] != binding): raise ExchangeError('binding_not_paired')
        if kind == 'cicada-run-report':
            safe_path(self.runs.path)
            self.runs.preview(envelope['report'])
        return kind != 'cicada-task-binding' or previous is None, source

    def preview(self, raw, revision):
        envelope = validate_envelope(strict_json(raw))
        with self.lock:
            state, current = self._read()
            if revision != current: raise ExchangeConflict('exchange_revision_conflict')
            changed, source = self._check(envelope, state)
            self.previews = {k:v for k,v in self.previews.items() if v[0] > time.monotonic()}
            if len(self.previews) >= 20: self.previews.pop(next(iter(self.previews)))
            token = secrets.token_urlsafe(24)
            self.previews[token] = (time.monotonic()+600, envelope, revision, source)
            return {'previewToken':token,'revision':revision,'envelope':envelope,'changed':changed,'source':source,'readOnly':True,'executionSupported':False}

    def apply(self, token, revision):
        with self.lock:
            receipt = self.previews.get(token) if isinstance(token, str) else None
            if not receipt or receipt[0] < time.monotonic(): raise ExchangeError('preview_required')
            _, envelope, expected, approved_source = receipt
            state, current = self._read()
            if revision != expected or current != expected: raise ExchangeConflict('exchange_revision_conflict')
            changed, source = self._check(envelope, state)
            if source != approved_source: raise ExchangeConflict('selected_source_changed')
            if envelope['kind'] == 'cicada-run-report':
                result = self.runs.report(envelope['report'])
                self.previews.pop(token, None)
                return {'run':result,'executionSupported':False}
            if changed:
                if envelope['kind'] == 'work-registry-snapshot':
                    state['publishers'][self.publisher_key(envelope)] = {'snapshot':envelope,'receivedAt':datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z')}
                else: state['bindings'][envelope['binding']['taskKey']] = {'binding':envelope['binding'],'source':source}
                raw = canonical(state)
                if len(raw) > MAX_STORE or len(state['bindings']) > 500 or len(state['publishers']) > 20: raise ExchangeError('exchange_storage_limit')
                try: _atomic(self.path, raw)
                except CodexControlsError as exc: raise ExchangeError('unsafe_exchange_path') from exc
            self.previews.pop(token, None)
            return {'changed':changed,'revision':self._read()[1],'executionSupported':False}

    def export_report(self, run_id):
        with self.lock:
            state, _ = self._read()
            safe_path(self.runs.path)
            row = next((r for r in self.runs.snapshot() if r['runId'] == run_id), None)
            paired = state['bindings'].get(row['taskKey']) if row else None
            binding = paired['binding'] if paired else None
            if not binding: raise ExchangeError('binding_not_paired')
            if self.connector.authorize_binding(binding) != paired['source']: raise ExchangeConflict('source_profile_conflict')
            return {'schemaVersion':1,'kind':'cicada-run-report','binding':binding,'report':{field:row.get(field) for field in FIELDS}}
