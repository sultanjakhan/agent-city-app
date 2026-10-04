"""Read counters for one explicitly bound Codex turn; never export conversation text."""
from pathlib import Path
import json
import os
import re


class UsageError(ValueError):
    pass


UUID = re.compile(r'^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$')
COUNTERS = ('input_tokens', 'output_tokens', 'cached_input_tokens')


def counters(value):
    if not isinstance(value, dict):
        raise UsageError('Codex usage counters are missing')
    result = {key: value.get(key) for key in COUNTERS}
    if any(type(n) is not int or not 0 <= n <= 2**53 - 1 for n in result.values()):
        raise UsageError('Codex usage counters are invalid')
    return result


def read_turn(path, session_id, turn_id):
    """Use cumulative deltas, ignoring repeated quota snapshots. Fail on resets/gaps."""
    previous = None
    active = None
    found = complete = identity = False
    models = set()
    result = dict.fromkeys(COUNTERS, 0)
    samples = 0
    started = finished = None
    with Path(path).open(encoding='utf-8') as stream:
        for line in stream:
            try:
                event = json.loads(line)
            except ValueError:
                # An unfinished final JSONL line is possible while Codex is writing.
                if not line.endswith('\n'):
                    break
                raise UsageError('Codex journal contains an unreadable record') from None
            payload = event.get('payload', {})
            if event.get('type') == 'session_meta':
                if payload.get('id') != session_id:
                    raise UsageError('Codex session identity does not match')
                identity = True
            elif event.get('type') == 'turn_context' and active == turn_id:
                if payload.get('model'):
                    models.add(payload['model'])
            elif event.get('type') == 'event_msg':
                kind = payload.get('type')
                if kind == 'task_started':
                    active = payload.get('turn_id')
                    if active == turn_id:
                        if found:
                            raise UsageError('Codex turn occurs more than once')
                        found = True
                        started = event.get('timestamp')
                elif kind == 'token_count' and payload.get('info'):
                    info = payload['info']
                    total = counters(info.get('total_token_usage'))
                    if active == turn_id:
                        last = counters(info.get('last_token_usage'))
                        base = previous or dict.fromkeys(COUNTERS, 0)
                        delta = {k: total[k] - base[k] for k in COUNTERS}
                        if any(n < 0 for n in delta.values()) or (any(delta.values()) and delta != last):
                            raise UsageError('Codex counters reset or skip requests; cannot attribute this turn safely')
                        for key in COUNTERS:
                            result[key] += delta[key]
                        samples += int(any(delta.values()))
                    previous = total
                elif kind in {'task_complete', 'turn_aborted'}:
                    if active == turn_id and payload.get('turn_id', active) == turn_id:
                        complete = kind == 'task_complete'
                        finished = event.get('timestamp')
                        break
                    active = None
    if not identity or not found or not complete or not samples:
        raise UsageError('A completed Codex turn with measured usage is required')
    if len(models) != 1:
        raise UsageError('A single observed model is required; mixed-model turns need separate reports')
    if result['cached_input_tokens'] > result['input_tokens']:
        raise UsageError('Cached input exceeds total input')
    return {'schemaVersion': 1, 'source': 'codex-session-turn', 'sessionId': session_id,
            'turnId': turn_id, 'model': next(iter(models)), 'inputTokens': result['input_tokens'],
            'outputTokens': result['output_tokens'], 'cachedInputTokens': result['cached_input_tokens'],
            'startedAt': started, 'finishedAt': finished, 'requests': samples}


def usage_for_turn(session_id, turn_id, codex_home=None):
    if not UUID.fullmatch(session_id or '') or not UUID.fullmatch(turn_id or ''):
        raise UsageError('Explicit Codex session and turn UUIDs are required')
    root = Path(codex_home or __import__('storage_config').load_storage().codex_home) / 'sessions'
    paths = list(root.glob(f'*/*/*/rollout-*-{session_id}.jsonl'))
    if len(paths) != 1:
        raise UsageError('The exact local Codex session journal was not found uniquely')
    return read_turn(paths[0], session_id, turn_id)


def enrich_report(report, usage):
    if report.get('agent') != 'codex' or report.get('model') != usage['model']:
        raise UsageError('Report must identify the measured Codex model')
    if report.get('status') != 'done':
        raise UsageError('Completed turn usage requires a completed run report')
    for key in ('inputTokens', 'outputTokens'):
        if report.get(key) is not None and report[key] != usage[key]:
            raise UsageError('Report usage conflicts with measured Codex usage')
    return {**report, **{key: usage[key] for key in ('inputTokens', 'outputTokens')}}
