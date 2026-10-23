"""Exact supplied frozen source anchors; synthetic surrounding fixture in tests."""
PASSIVE_ASSIGNMENT = "    store.live_sessions = LiveSessions(Path(value['dataDir']), codex_home=Path.home() / '.codex')\n"
STAGE_RETURN = """            stages.append({'id': turn['id'], 'name': 'Turn ' + str(index), 'status': turn['status'],
                           'startedAt': turn['start'] or turn['first'], 'endedAt': turn['end'],
                           'durationMs': duration, 'usage': {key: measured[key] for key in ('input', 'output', 'total')},
                           'events': sorted(turn['events'].values(), key=lambda event: (event['at'], event['id']))})
"""
PATCH_METRICS = r"""  function patchMetrics(item) {
    const usage = item.usage || {};
    const time = metricNode('time'); time.querySelector('.ls-metric-value').textContent = formatDuration(sessionDuration(item));
    time.querySelector('.ls-metric-note').textContent = `Started ${formatDateTime(item.startedAt)}`;
    const tokens = metricNode('tokens'); tokens.querySelector('.ls-metric-value').textContent = formatNumber(usage.total);
    tokens.querySelector('.ls-metric-note').textContent = `Input ${formatNumber(usage.input)} \u00b7 Output ${formatNumber(usage.output)}`;
    const model = metricNode('model'); model.querySelector('.ls-metric-value').textContent = text(item.model);
    model.querySelector('.ls-metric-note').textContent = `Effort \u00b7 ${text(item.effort)}`;
  }
"""
STAGE_METRICS = "    summary.querySelector('.ls-stage-metrics').textContent = `${formatNumber(stage.usage?.total)} tokens · ${formatDuration(stageDuration)}`;\n"
CONNECTOR_INIT = '            result = []\n'
CONNECTOR_TOKS = '                toks = [x.strip() for x in tags.split(",") if x.strip()]\n'
CONNECTOR_RETURN = '            return result[:500], len(result) > 500\n'
LIVE_SCRIPT = '<script src="/live-sessions.js" defer></script>'
