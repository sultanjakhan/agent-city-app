"""Read-only exact-turn overlay for the frozen LiveSessions collector.

No writer, HTTP route, journal discovery, executor grant or task lifecycle API.
The host supplies its actual session-list path and routing identity keys.
"""
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

LIMIT = 16 * 1024
IDENT = re.compile(r'[A-Za-z0-9_.:-]{1,100}')


class BindingError(ValueError):
    pass


def exact(value, fields):
    if not isinstance(value, dict) or set(value) != set(fields):
        raise BindingError('invalid_attempt_binding_fields')


def opaque(value):
    if not isinstance(value, str) or not IDENT.fullmatch(value):
        raise BindingError('invalid_attempt_identifier')


def timestamp(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?Z', value):
        raise BindingError('invalid_attempt_timestamp')
    try: return datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError: raise BindingError('invalid_attempt_timestamp') from None


def collector_time(value):
    """Normalize only explicit aware collector times; never first-seen fallback."""
    if value is None: return None
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|[+-]\d\d:\d\d)', value):
        raise BindingError('invalid_collector_timestamp')
    try: parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError: raise BindingError('invalid_collector_timestamp') from None
    if parsed.tzinfo is None or parsed.utcoffset() is None or parsed > datetime.now(timezone.utc):
        raise BindingError('invalid_or_future_collector_timestamp')
    return parsed.astimezone(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')


def label(value, limit=200):
    if not isinstance(value, str) or not value.strip() or len(value) > limit or any(ord(c) < 32 for c in value):
        raise BindingError('invalid_attempt_label')
    return value


def strict(raw):
    if not isinstance(raw, bytes) or len(raw) > LIMIT: raise BindingError('attempt_binding_capacity')
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value: raise BindingError('duplicate_attempt_field')
            value[key] = item
        return value
    try:
        value = json.loads(raw, object_pairs_hook=unique, parse_constant=lambda _: (_ for _ in ()).throw(BindingError('invalid_attempt_number')))
    except (UnicodeError, ValueError, RecursionError): raise BindingError('invalid_attempt_binding_json') from None
    def depth(item, n=0):
        if n > 12: raise BindingError('attempt_binding_depth')
        if isinstance(item, dict):
            for child in item.values(): depth(child, n+1)
        elif isinstance(item, list):
            for child in item: depth(child, n+1)
    depth(value)
    return value


def validate(value):
    exact(value, ('schemaVersion', 'kind', 'bindingId', 'sessionId', 'turnId', 'task',
                  'nativeTaskKey', 'approvedAt', 'appliedSkills'))
    if type(value['schemaVersion']) is not int or value['schemaVersion'] != 1 or value['kind'] != 'passive-attempt-binding':
        raise BindingError('invalid_attempt_binding_schema')
    for key in ('bindingId', 'sessionId', 'turnId'): opaque(value[key])
    timestamp(value['approvedAt'])
    task = value['task']; exact(task, ('profile', 'sourceKey', 'sourceId', 'taskKey'))
    if task['profile'] not in ('production', 'dev') or not isinstance(task['sourceKey'], str) or not re.fullmatch('[a-f0-9]{16}', task['sourceKey']):
        raise BindingError('invalid_attempt_source')
    if not isinstance(task['sourceId'], str) or not re.fullmatch('[A-Za-z0-9_-]{1,80}', task['sourceId']):
        raise BindingError('invalid_attempt_task')
    if task['taskKey'] != 'cicada-' + task['sourceKey'] + '-' + task['sourceId']:
        raise BindingError('invalid_attempt_task_key')
    native = value['nativeTaskKey']
    if native is not None and (not isinstance(native, str) or not re.fullmatch(r'cicada-[a-f0-9]{16}-[A-Za-z0-9_-]{1,80}', native)):
        raise BindingError('invalid_native_task_key')
    if native is not None and native[24:] != task['sourceId']:
        raise BindingError('native_task_source_id_mismatch')
    skills = value['appliedSkills']
    if skills is not None:
        if not isinstance(skills, list) or len(skills) > 20: raise BindingError('attempt_skill_capacity')
        seen = set()
        for event in skills:
            exact(event, ('id', 'turnId', 'skill', 'at', 'kind', 'source'))
            opaque(event['id']); opaque(event['turnId']); label(event['skill'], 100); timestamp(event['at'])
            if (event['turnId'] != value['turnId'] or event['kind'] != 'applied' or
                    event['source'] != 'executor-reported' or event['id'] in seen):
                raise BindingError('explicit_turn_application_required')
            seen.add(event['id'])
    return copy.deepcopy(value)


def read_binding(directory):
    path = Path(directory) / 'passive-attempt-binding.json'
    # No scanning, creation or symlink/reparse traversal, including parents.
    for part in (path, *path.parents):
        if part.is_symlink() or (part.exists() and getattr(part.lstat(), 'st_file_attributes', 0) & 0x400):
            raise BindingError('redirected_attempt_binding')
    if not path.exists(): return None, None
    with path.open('rb') as stream: raw = stream.read(LIMIT + 1)
    return validate(strict(raw)), hashlib.sha256(raw).hexdigest()


def verify_task(connector, binding):
    identity = binding['task']
    snapshot = connector.snapshot(task_keys=[identity['taskKey']])
    source = snapshot.get('source') or {}
    if (snapshot.get('status') != 'connected' or source.get('profile') != identity['profile'] or
            source.get('sourceKey') != identity['sourceKey']):
        raise BindingError('attempt_source_mismatch')
    matches = [task for task in snapshot.get('tasks', []) if task.get('sourceId') == identity['sourceId'] and task.get('taskKey') == identity['taskKey']]
    if len(matches) != 1: raise BindingError('attempt_task_unavailable')
    task = matches[0]
    if task.get('personalEligible') is not True:
        raise BindingError('attempt_personal_task_required')
    return task


def counter(value):
    return value if type(value) is int and 0 <= value <= 10**12 else None


def project_session(item, binding, task, digest, *, identity_fields=()):
    """Build a scoped row from one exact observed stage, never session totals.

    Only host-confirmed routing identity fields are copied from the old row.
    This prevents unknown historical metric aliases leaking through a copy.
    """
    if item.get('id') != binding['sessionId']: raise BindingError('attempt_session_mismatch')
    matches = [s for s in item.get('stages', []) if isinstance(s, dict) and s.get('id') == binding['turnId']]
    if len(matches) != 1: raise BindingError('exact_turn_unavailable')
    original = matches[0]
    start, end = collector_time(original.get('observedStartedAt')), collector_time(original.get('endedAt'))
    if start and end and timestamp(end) < timestamp(start): raise BindingError('invalid_turn_interval')
    usage = original.get('usage') if isinstance(original.get('usage'), dict) else {}
    usage = {key: counter(usage.get(key)) for key in ('input', 'output', 'total', 'cachedInput', 'reasoningOutput')}
    model = original.get('model')
    if model is not None: label(model)
    effort = original.get('effort')
    if effort is not None: label(effort)
    last_event = collector_time(original.get('lastEventAt'))
    if start and last_event and timestamp(last_event) < timestamp(start):
        raise BindingError('invalid_turn_event_order')
    coverage = original.get('coverage')
    if coverage not in ('complete', 'partial', 'unknown'): coverage = 'unknown'
    status = original.get('status')
    if status not in ('working', 'completed', 'interrupted', 'unknown'): status = 'unknown'
    if end and status == 'working': raise BindingError('working_turn_has_end')
    duration = counter(original.get('durationMs'))
    skills = binding['appliedSkills']
    applied_events = []
    for event in skills or []:
        at = timestamp(event['at'])
        if (start and at < timestamp(start)) or (end and at > timestamp(end)):
            raise BindingError('skill_event_outside_bound_turn')
        applied_events.append({'id': event['id'], 'at': event['at'], 'kind': 'skill-applied',
                               'label': 'Skill applied · executor reported', 'skill': event['skill'],
                               'detail': 'Executor reported; not independently verified.', 'source': 'executor-reported'})
    stage = {'id': binding['turnId'], 'name': 'Bound turn', 'status': status,
             'startedAt': start, 'endedAt': end, 'durationMs': duration, 'durationSource': original.get('durationSource'), 'model': model, 'effort': effort,
             'usage': usage, 'events': applied_events,
             'attemptBinding': {'readOnly': True, 'turnId': binding['turnId'], 'independentlyVerified': False}}
    identity = binding['task']
    native = binding['nativeTaskKey']
    title = label(task.get('title'), 500)
    summary = (title + '\nProfile: ' + identity['profile'] + '\nSource key: ' + identity['sourceKey'] +
               '\nSource ID: ' + identity['sourceId'] + '\nConnector task key: ' + identity['taskKey'] +
               '\nNative task key: ' + (native or 'unknown') + '\nBound turn: ' + binding['turnId'] +
               '\nSkill applications: ' + ('unknown' if skills is None else 'executor reported') +
               '\nOwner-approved exact turn; collector metadata and executor-reported skill claims are not independent execution verification.')
    # Only these known identity fields may be requested by the host integration.
    permitted = {'projectId', 'agentId', 'parentId', 'parentSessionId'}
    if not isinstance(identity_fields, tuple) or not set(identity_fields) <= permitted:
        raise BindingError('unsupported_session_identity_mapping')
    row = {key: copy.deepcopy(item[key]) for key in identity_fields if key in item}
    row.update(id=item['id'], name=title, task=summary, result=None, currentAction=None,
               status=status, startedAt=start, endedAt=end, durationMs=duration, usage=usage,
               model=model, effort=effort, coverage=coverage, lastEventAt=last_event,
               durationSource=original.get('durationSource'), skills=[event['skill'] + ' (executor reported)' for event in skills] if skills is not None else [], stages=[stage])
    row['attemptBinding'] = {'kind': 'owner-approved-exact-turn', 'bindingHash': digest,
                             'task': copy.deepcopy(identity), 'nativeTaskKey': native,
                             'turnId': binding['turnId'], 'approvedAt': binding['approvedAt'],
                             'readOnly': True, 'independentlyVerified': False,
                             'skillsKnown': skills is not None, 'usageSource': 'exact-bound-turn-only',
                             'skillSource': 'executor-reported', 'durationSource': (original.get('durationSource') or 'collector-reported-duration') if duration is not None else 'unknown',
                             'runningElapsedSource': 'derived-from-observed-start' if start and not end and status == 'working' else None}
    return row


class BoundLiveSessions:
    def __init__(self, collector, connector, directory, *, sessions_path, identity_fields=()):
        if not isinstance(sessions_path, tuple) or not sessions_path or any(not isinstance(key, str) or not key for key in sessions_path):
            raise BindingError('explicit_snapshot_session_path_required')
        self.collector, self.connector, self.directory = collector, connector, directory
        self.sessions_path, self.identity_fields = sessions_path, identity_fields

    def snapshot(self):
        original = self.collector.snapshot()
        if not isinstance(original, dict): return original
        try:
            binding, digest = read_binding(self.directory)
            if binding is None: return original
            task = verify_task(self.connector, binding)  # Every projection, never cached authority.
            projected = copy.deepcopy(original)
            rows = projected
            for key in self.sessions_path:
                if not isinstance(rows, dict) or key not in rows: raise BindingError('unsupported_session_snapshot_shape')
                rows = rows[key]
            if not isinstance(rows, list) or len(rows) > 1000: raise BindingError('unsupported_session_snapshot_shape')
            matches = [i for i, row in enumerate(rows) if isinstance(row, dict) and row.get('id') == binding['sessionId']]
            if len(matches) != 1: raise BindingError('exact_session_unavailable')
            index = matches[0]
            rows[index] = project_session(rows[index], binding, task, digest, identity_fields=self.identity_fields)
            projected['attemptBinding'] = {'status': 'bound', 'readOnly': True, 'independentlyVerified': False}
            return projected
        except (ValueError, OSError, TypeError):
            # Never fabricate a link on source drift or an unsupported collector shape.
            projected = copy.deepcopy(original)
            projected['attemptBinding'] = {'status': 'unavailable', 'readOnly': True, 'independentlyVerified': False}
            return projected
