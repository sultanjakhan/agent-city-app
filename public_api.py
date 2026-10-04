"""Versioned read contract for repositories; no credentials, CSRF or reply bodies."""
VERSION = '0.5.24'


def reporting():
    return {'cli': 'city.py report-run --file <local-report.json>',
            'readTasks': 'city.py dashboard', 'schemaVersion': 1,
            'fields': ['runId', 'sequence', 'taskKey', 'agent', 'model', 'provider', 'stage', 'status', 'skillIds', 'mcpCalls', 'inputTokens', 'outputTokens'],
            'mcpCalls': 'null when unknown, otherwise cumulative [{server: technical_id, tool: technical_id, calls: nonnegative_integer}]. No arguments or results.',
            'instructions': 'For actual authorized work, report execution when starting, changing stage, and finishing. '
                            'Use a unique runId and increasing sequence; send the complete snapshot each time. '
                            'Use taskKey from dashboard only when the current assignment explicitly matches that Cicada task; otherwise null. '
                            'Report only observed model/provider and cumulative input/output token usage, otherwise null; never estimate. '
                            'skillIds are enumerated skill-inventory IDs actually applied, not all available skills. '
                            'Report actual MCP tool counters in mcpCalls; do not infer usage from installed servers. '
                            'Do not put task text, prompts or secrets in reports. Reports do not authorize execution. '
                            'An unavailable reporting service must not prevent the requested work.'}


def manifest():
    return {'schemaVersion': 1, 'appId': 'agent-city-panel', 'version': VERSION,
            'readOnly': True, 'endpoints': {
                'models': '/api/v1/models', 'providers': '/api/v1/providers',
                'skills': '/api/v1/skills', 'directory': '/api/v1/directory', 'skillInventory': '/api/v1/skill-inventory',
                'extensions': '/api/v1/extensions', 'repositories': '/api/v1/repositories',
                'rules': '/api/v1/rules', 'context': '/api/v1/context', 'dashboard': '/api/v1/dashboard'},
            'skillContent': '/api/v1/skills?slug={slug}', 'agentReporting': reporting(),
            'semantics': {'discovered': 'Present in a catalog; access and price may be unverified.',
                          'responded': 'A dated completed text response; not a quality or tool-use acceptance.',
                          'free': 'Catalog price evidence only; revalidate before every request.'}}


def providers(snapshot):
    result = []
    for source in snapshot['sources']:
        catalog = snapshot['catalogs'].get(source['id'], {})
        result.append({**source, 'hasKey': snapshot['credentials'].get(source['id'], False),
                       'authStatus': catalog.get('authStatus', 'unverified'),
                       'connectionStatus': snapshot.get('connectionStatus', {}).get(source['id']),
                       'updatedAt': catalog.get('updatedAt'), 'error': catalog.get('error'),
                       'modelCount': len(catalog.get('models', []))})
    return {'schemaVersion': 1, 'asOf': snapshot['serverTime'], 'providers': result}


def models(snapshot):
    routes = []
    source_map = {s['id']: s for s in snapshot['sources']}
    for provider, catalog in snapshot['catalogs'].items():
        for model in catalog.get('models', []):
            check = snapshot['checks'].get(provider + '|' + model['id'], {})
            source = source_map.get(provider, {})
            row = {k: model[k] for k in ('id', 'name', 'developer', 'chinese', 'kind', 'context', 'tools', 'vision', 'priceVerified', 'upstreams') if k in model}
            row.update(provider=provider, execution='api', catalogAt=catalog.get('updatedAt'),
                       sourceUrl=source.get('catalogUrl'), discoveryOnly=source.get('discoveryOnly', False),
                       check={k: check[k] for k in ('status', 'sent', 'attemptedAt', 'durationMs', 'httpStatus', 'finishReason') if k in check})
            routes.append(row)
    return {'schemaVersion': 1, 'asOf': snapshot['serverTime'], 'routes': routes}
