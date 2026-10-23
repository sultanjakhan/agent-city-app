"""Owner-imported observations only. Never execution authority or native writes."""
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import secrets
import threading
import time

from codex_controls import _atomic
from work_exchange import exact, strict_json, canonical, safe_path

MAX_BUNDLE = 32 * 1024
MAX_STORE = 2 * 1024 * 1024
MAX_RECEIPTS = 100
FIELDS = ('status', 'sessionId', 'parentSessionId', 'model', 'inputTokens', 'outputTokens',
          'startedAt', 'endedAt', 'durationMs')
ID = re.compile(r'[A-Za-z0-9_.:-]{1,100}')


class ObservationError(ValueError):
    pass


class ObservationConflict(ObservationError):
    pass


def opaque(value):
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise ObservationError('invalid_observation_identifier')


def stamp(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?Z', value):
        raise ObservationError('invalid_observation_timestamp')
    try: return datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError: raise ObservationError('invalid_observation_timestamp') from None


def validate_task(value):
    exact(value, ('profile', 'sourceKey', 'sourceId', 'taskKey'))
    if value['profile'] not in ('production', 'dev'):
        raise ObservationError('invalid_observation_profile')
    if not isinstance(value['sourceKey'], str) or not re.fullmatch('[a-f0-9]{16}', value['sourceKey']):
        raise ObservationError('invalid_observation_source')
    if not isinstance(value['sourceId'], str) or not re.fullmatch('[A-Za-z0-9_-]{1,80}', value['sourceId']):
        raise ObservationError('invalid_observation_task')
    if value['taskKey'] != 'cicada-' + value['sourceKey'] + '-' + value['sourceId']:
        raise ObservationError('observation_task_mismatch')
    return copy.deepcopy(value)


def validate(document):
    if not isinstance(document, str): raise ObservationError('observation_json_required')
    bundle = strict_json(document, limit=MAX_BUNDLE)
    exact(bundle, ('schemaVersion', 'kind', 'observationId', 'sequence', 'task', 'exporter',
                   'observedAt', 'exportedAt', 'coverage', 'fields', 'skillApplications'))
    if type(bundle['schemaVersion']) is not int or bundle['schemaVersion'] != 1 or bundle['kind'] != 'task-observation-bundle':
        raise ObservationError('invalid_observation_schema')
    opaque(bundle['observationId'])
    if type(bundle['sequence']) is not int or not 1 <= bundle['sequence'] <= 10**9:
        raise ObservationError('invalid_observation_sequence')
    validate_task(bundle['task'])
    exact(bundle['exporter'], ('id', 'source'))
    for value in bundle['exporter'].values(): opaque(value)
    observed, exported = stamp(bundle['observedAt']), stamp(bundle['exportedAt'])
    if observed > exported: raise ObservationError('invalid_observation_order')
    coverage = bundle['coverage']
    exact(coverage, ('kind', 'attemptId', 'startedAt', 'endedAt', 'source'))
    opaque(coverage['source'])
    if coverage['kind'] == 'attempt':
        opaque(coverage['attemptId'])
        if coverage['startedAt'] is not None or coverage['endedAt'] is not None:
            raise ObservationError('attempt_coverage_uses_identity')
    elif coverage['kind'] == 'interval':
        if (coverage['attemptId'] is not None or stamp(coverage['startedAt']) > stamp(coverage['endedAt']) or
                stamp(coverage['endedAt']) > observed):
            raise ObservationError('invalid_interval_coverage')
    elif coverage['kind'] == 'metadata-snapshot':
        if any(coverage[key] is not None for key in ('attemptId', 'startedAt', 'endedAt')):
            raise ObservationError('invalid_snapshot_coverage')
    else: raise ObservationError('bounded_observation_coverage_required')
    exact(bundle['fields'], FIELDS)
    for key, field in bundle['fields'].items():
        exact(field, ('value', 'source', 'observedAt'))
        value = field['value']
        if value is None:
            if field['source'] is not None or field['observedAt'] is not None:
                raise ObservationError('unknown_measurement_has_provenance')
            continue
        opaque(field['source'])
        if stamp(field['observedAt']) > observed: raise ObservationError('invalid_observation_order')
        if key == 'status':
            if value not in ('running', 'waiting', 'stopped', 'completed', 'cancelled', 'error'):
                raise ObservationError('invalid_observed_status')
        elif key in ('inputTokens', 'outputTokens', 'durationMs'):
            if type(value) is not int or not 0 <= value <= 10**12: raise ObservationError('invalid_observation_counter')
        elif key in ('startedAt', 'endedAt'):
            if stamp(value) > observed: raise ObservationError('invalid_observation_order')
        elif key == 'model':
            if not isinstance(value, str) or not value.strip() or len(value) > 200 or any(ord(c) < 32 for c in value):
                raise ObservationError('invalid_observation_model')
        else: opaque(value)
    start, end = (bundle['fields'][key]['value'] for key in ('startedAt', 'endedAt'))
    if start and end and stamp(end) < stamp(start): raise ObservationError('invalid_observation_order')
    if end is not None and bundle['fields']['status']['value'] in ('running', 'waiting'):
        raise ObservationError('ended_attempt_cannot_be_current')
    skills = bundle['skillApplications']
    if skills is not None:
        if not isinstance(skills, list) or len(skills) > 20: raise ObservationError('invalid_skill_applications')
        seen = set()
        for skill in skills:
            exact(skill, ('skillId', 'evidenceId', 'source', 'observedAt', 'kind'))
            if skill['kind'] != 'applied': raise ObservationError('application_evidence_required')
            for key in ('skillId', 'evidenceId', 'source'): opaque(skill[key])
            if stamp(skill['observedAt']) > observed or skill['evidenceId'] in seen:
                raise ObservationError('invalid_skill_application_evidence')
            seen.add(skill['evidenceId'])
    if coverage['kind'] == 'metadata-snapshot':
        if (any(bundle['fields'][key]['value'] is not None for key in
                ('status', 'inputTokens', 'outputTokens', 'startedAt', 'endedAt', 'durationMs')) or
                skills is not None):
            raise ObservationError('snapshot_cannot_attribute_execution_usage')
    return bundle


def advance(bundle, digest, receipts):
    prior = [entry for entry in receipts if entry['bundle']['observationId'] == bundle['observationId']]
    replay = next((entry for entry in prior if entry['bundleHash'] == digest), None)
    if replay is not None: return False  # Exact historical replay, never rollback.
    if prior:
        old = prior[-1]['bundle']
        if bundle['sequence'] <= old['sequence']: raise ObservationConflict('observation_sequence_conflict')
        if any(bundle[key] != old[key] for key in ('task', 'exporter', 'coverage')):
            raise ObservationConflict('observation_identity_conflict')
        if stamp(bundle['observedAt']) < stamp(old['observedAt']) or stamp(bundle['exportedAt']) < stamp(old['exportedAt']):
            raise ObservationConflict('observation_time_regression')
        for key in FIELDS:
            before, after = old['fields'][key], bundle['fields'][key]
            if before['value'] is None: continue
            if after['value'] is None or stamp(after['observedAt']) < stamp(before['observedAt']):
                raise ObservationConflict('observation_measurement_regression')
            if key in ('inputTokens', 'outputTokens', 'durationMs'):
                if after['value'] < before['value']: raise ObservationConflict('observation_counter_regression')
            elif key == 'status':
                if before['value'] in ('stopped', 'completed', 'cancelled', 'error') and after['value'] != before['value']:
                    raise ObservationConflict('observation_terminal_attempt_conflict')
            elif after['value'] != before['value']:
                raise ObservationConflict('observation_identity_conflict')
        if old['skillApplications'] is not None:
            newer = {s['evidenceId']: s for s in bundle['skillApplications'] or []}
            if any(newer.get(s['evidenceId']) != s for s in old['skillApplications']):
                raise ObservationConflict('observation_skill_evidence_regression')
    if len(receipts) >= MAX_RECEIPTS: raise ObservationError('observation_capacity')
    return True


class ObservationStore:
    def __init__(self, directory, connector):
        self.path = Path(directory) / 'imported-observations.json'
        self.connector = connector
        self.lock = threading.RLock()
        self.previews = {}

    def _read(self):
        safe_path(self.path)
        if not self.path.exists(): return [], 'none'
        with self.path.open('rb') as stream: raw = stream.read(MAX_STORE + 1)
        value = strict_json(raw, limit=MAX_STORE)
        exact(value, ('schemaVersion', 'receipts'))
        if type(value['schemaVersion']) is not int or value['schemaVersion'] != 1 or not isinstance(value['receipts'], list) or len(value['receipts']) > MAX_RECEIPTS:
            raise ObservationError('invalid_observation_storage')
        receipts = []
        for entry in value['receipts']:
            exact(entry, ('document', 'bundleHash', 'importedAt'))
            bundle = validate(entry['document']); stamp(entry['importedAt'])
            digest = hashlib.sha256(entry['document'].encode('utf-8')).hexdigest()
            if entry['bundleHash'] != digest or not advance(bundle, digest, receipts):
                raise ObservationError('invalid_observation_receipt')
            receipts.append(dict(entry, bundle=bundle))
        return receipts, hashlib.sha256(raw).hexdigest()

    def preview(self, document):
        bundle = validate(document)
        digest = hashlib.sha256(document.encode('utf-8')).hexdigest()
        with self.lock:
            task = self.connector.read_observation_task(bundle['task'])
            receipts, revision = self._read()
            changed = advance(bundle, digest, receipts)
            self.previews = {k: v for k, v in self.previews.items() if v[0] > time.monotonic()}
            if len(self.previews) >= 10: raise ObservationError('observation_preview_capacity')
            token = secrets.token_urlsafe(24)
            self.previews[token] = (time.monotonic() + 600, document, revision)
            return {'previewToken': token, 'revision': revision, 'bundle': bundle,
                    'bundleHash': digest, 'task': task, 'changed': changed,
                    'origin': 'imported', 'readOnly': True, 'independentlyVerified': False}

    def import_preview(self, token, revision):
        with self.lock:
            preview = self.previews.get(token) if isinstance(token, str) else None
            if not preview or preview[0] < time.monotonic(): raise ObservationError('observation_preview_required')
            _, document, expected = preview
            bundle = validate(document)
            # A preview is never authority. Recheck selected task/source now.
            self.connector.read_observation_task(bundle['task'])
            receipts, current = self._read()
            if current != expected or revision != expected: raise ObservationConflict('observation_revision_conflict')
            digest = hashlib.sha256(document.encode('utf-8')).hexdigest()
            changed = advance(bundle, digest, receipts)
            if changed:
                receipts.append({'document': document, 'bundleHash': digest,
                                 'importedAt': datetime.now(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')})
                raw = canonical({'schemaVersion': 1, 'receipts': [{key: value for key, value in r.items() if key != 'bundle'} for r in receipts]})
                if len(raw) > MAX_STORE: raise ObservationError('observation_capacity')
                safe_path(self.path); _atomic(self.path, raw)
            self.previews.pop(token, None)
            return {'changed': changed, 'origin': 'imported', 'readOnly': True,
                    'bundleHash': digest, 'independentlyVerified': False}

    def projection(self):
        with self.lock:
            receipts, _ = self._read()
        latest = {}
        for entry in receipts: latest[entry['bundle']['observationId']] = entry
        rows, unavailable = [], 0
        for entry in latest.values():
            try: task = self.connector.read_observation_task(entry['bundle']['task'])
            except (ValueError, OSError, RuntimeError):
                unavailable += 1; continue
            rows.append({'bundle': entry['bundle'], 'bundleHash': entry['bundleHash'],
                         'importedAt': entry['importedAt'], 'origin': 'imported', 'readOnly': True,
                         'independentlyVerified': False, 'task': task,
                         'receipts': [{'bundleHash': r['bundleHash'], 'importedAt': r['importedAt'],
                                       'sequence': r['bundle']['sequence']} for r in receipts
                                      if r['bundle']['observationId'] == entry['bundle']['observationId']]})
        return {'schemaVersion': 1, 'rows': rows, 'unavailableCount': unavailable,
                'notice': 'Imported metadata; supplied provenance is not independent execution verification.'}
