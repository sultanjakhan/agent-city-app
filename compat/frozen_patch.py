"""Read-only exact-substring assembly of complete frozen source files; no installer."""
import difflib
from pathlib import Path
from compat.frozen_fragments import PASSIVE_ASSIGNMENT, STAGE_RETURN, PATCH_METRICS, STAGE_METRICS, CONNECTOR_INIT, CONNECTOR_TOKS, CONNECTOR_RETURN, LIVE_SCRIPT


def changes(root):
    helper = (Path(root)/'static/passive-attempt-view.js').read_text()
    assignment = PASSIVE_ASSIGNMENT + """    from passive_attempts import BoundLiveSessions
    store.live_sessions = BoundLiveSessions(
        store.live_sessions, store.cicada, Path(value['dataDir']),
        sessions_path=('sessions',), identity_fields=('projectId', 'agentId', 'parentId'))
"""
    stage = """            stages.append({'id': turn['id'], 'name': 'Turn ' + str(index), 'status': turn['status'],
                           'startedAt': turn['start'] or turn['first'], 'observedStartedAt': turn['start'], 'endedAt': turn['end'],
                           'model': next(iter(turn['models'])) if len(turn['models']) == 1 else None,
                           'effort': next(iter(turn['efforts'])) if len(turn['efforts']) == 1 else None,
                           'coverage': coverages[-1],
                           'lastEventAt': max((event['at'] for event in turn['events'].values()), default=None),
                           'durationMs': duration,
                           'durationSource': ('collector-reported-duration' if turn['duration'] is not None else
                                              'derived-from-observed-turn-bounds' if turn['start'] and turn['end'] else 'unknown'),
                           'usage': {**{key: measured[key] for key in ('input', 'output', 'total')},
                                     **{key: measured[key] for key in ('cachedInput', 'reasoningOutput')
                                        if type(measured.get(key)) is int and measured[key] >= 0}},
                           'events': sorted(turn['events'].values(), key=lambda event: (event['at'], event['id']))})
"""
    metrics = PATCH_METRICS.replace('  function patchMetrics(item) {', "  function patchMetrics(item) {\n    if (globalThis.PassiveAttemptView.patchMetrics(item, metricNode, formatNumber, formatDuration, text, formatDateTime)) return;")
    stage_metrics = """    const scopedMetrics = globalThis.PassiveAttemptView.stageMetrics(stage, formatNumber, formatDuration);
    summary.querySelector('.ls-stage-metrics').textContent = scopedMetrics !== null
      ? scopedMetrics
      : `${formatNumber(stage.usage?.total)} tokens · ${formatDuration(stageDuration)}`;
"""
    connector = 'native/agent-system/app/cicada_connector.py'
    return [('passive_server.py', PASSIVE_ASSIGNMENT, assignment),
            ('native/agent-system/app/live_sessions.py', STAGE_RETURN, stage),
            (connector, CONNECTOR_INIT, CONNECTOR_INIT + '            personal_eligibility = {}\n'),
            (connector, CONNECTOR_TOKS, CONNECTOR_TOKS + "                personal_eligibility[str(ident)] = ('task-sphere:personal' in toks and not any(\n                    tok.lower() == 'task-sphere:work' or tok.lower().startswith(('jira', 'investlink')) for tok in toks))\n"),
            (connector, CONNECTOR_RETURN, "            return [dict(task, personalEligible=personal_eligibility[task['sourceId']]) for task in result[:500]], len(result) > 500\n"),
            ('native/agent-system/app/static/live-sessions.js', PATCH_METRICS, metrics),
            ('native/agent-system/app/static/live-sessions.js', STAGE_METRICS, stage_metrics),
            ('native/agent-system/app/static/index.html', LIVE_SCRIPT, '<script src="/passive-attempt-view.js" defer></script>' + LIVE_SCRIPT),
            ('native/agent-system/app/static/passive-attempt-view.js', '', helper),
            ('native/agent-system/app/passive_attempts.py', '', (Path(root)/'passive_attempts.py').read_text())]



def patch_text(root):
    return '# REVIEW EXCERPTS ONLY: not a git-applicable patch; use check_sources complete files.\n' + ''.join(''.join(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
                     fromfile='a/'+name if before else '/dev/null', tofile='b/'+name, n=3)) for name,before,after in changes(root))


def check_sources(root, source_root):
    """Read-only preflight: every supplied anchor must occur exactly once."""
    files = {}
    for name, before, after in changes(source_root):
        path = Path(root)/name
        if name not in files:
            if before:
                files[name] = path.read_bytes().decode('utf-8')
            else:
                if path.exists(): raise ValueError('new adapter file already exists: '+name)
                files[name] = ''
        if before:
            if files[name].count(before) != 1: raise ValueError('anchor absent or ambiguous: '+name)
            files[name] = files[name].replace(before, after, 1)
        else: files[name] = after
    return files


if __name__ == '__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-root', type=Path, help='read-only unique-anchor check of a NEW frozen source copy')
    parser.add_argument('--planned-files-json', action='store_true', help='emit complete planned files as JSON to stdout; requires --check-root; no source writes')
    args=parser.parse_args()
    if args.planned_files_json and not args.check_root:
        parser.error('--planned-files-json requires --check-root')
    source_root=Path(__file__).resolve().parents[1]
    if args.check_root:
        planned=check_sources(args.check_root, source_root)
        if args.planned_files_json:
            import json
            print(json.dumps(planned, ensure_ascii=True))
        else:
            print('Exact frozen anchor preflight passed for',len(planned),'files; no files written')
    else: print(patch_text(source_root), end='')
