"""Bounded local executor reports paired to the selected native authority."""
from work_exchange import exact, validate_binding
from run_store import validate, RunError


def prepare_report(document, *, context=None):
    """Prepare a portable v1 envelope, without pairing, storing or delivering it.

    document is bounded strict JSON, not a filename. Optional context exposes
    the existing cicada/inventory/runs/work_exchange read/preview interfaces.
    Its authority and prior receipts are supplied by the caller: parsing alone
    cannot establish native existence, authorization or sequence freshness.
    Even a checked result must be revalidated by the eventual import authority.
    """
    from work_exchange import (strict_json, validate_envelope, ExchangeError,
                               ExchangeConflict, namespace)
    envelope = validate_envelope(strict_json(document))
    if envelope['kind'] != 'cicada-run-report':
        raise ExchangeError('run_report_required')
    changed = None
    if context is not None:
        binding, row = envelope['binding'], envelope['report']
        source = context.cicada.authorize_binding(binding, personal_only=True)
        exact(source, ('selectedId', 'profile', 'sourceNamespace'))
        namespace(source['sourceNamespace'])
        if (source['selectedId'] not in ('production', 'dev') or
                source['profile'] != source['selectedId'] or
                source['sourceNamespace'] != binding['sourceNamespace']):
            raise ExchangeError('invalid_source_receipt')
        previous = context.work_exchange.bindings().get(binding['taskKey'])
        if previous and (previous['binding'] != binding or previous['source'] != source):
            raise ExchangeConflict('source_profile_conflict')
        known = {skill['id'] for skill in context.inventory.list()}
        if any(ident not in known for ident in row['skillIds']):
            raise RunError('unknown skill')
        changed = context.runs.preview(row)['changed']
    return {'schemaVersion': 1, 'kind': 'agent-city-report-preparation',
            'envelope': envelope, 'contextChecked': context is not None,
            'changed': changed, 'deliverySupported': False,
            'unavailableFields': ['sessionId', 'parentSessionId', 'durationMs', 'skillReads']}


def report(store, payload):
    exact(payload, ('binding', 'report'))
    binding = validate_binding(payload['binding'])
    row = validate(payload['report'])
    if row['taskKey'] != binding['taskKey']:
        raise RunError('report binding mismatch')
    store.cicada.authorize_binding(binding, personal_only=True)
    known = {skill['id'] for skill in store.inventory.list()}
    if any(ident not in known for ident in row['skillIds']):
        raise RunError('unknown skill')
    # Pair only this explicitly reported native task, preserving selected-profile
    # fencing. Merely reading a cloned database never imports its bindings.
    import json
    exchange = store.work_exchange
    with exchange.lock:
        store.runs.preview(row)
        revision = exchange.snapshot()['revision']
        preview = exchange.preview(json.dumps({'schemaVersion':1,'kind':'cicada-task-binding','binding':binding}),revision)
        exchange.apply(preview['previewToken'],revision)
        revision = exchange.snapshot()['revision']
        preview = exchange.preview(json.dumps({'schemaVersion':1,'kind':'cicada-run-report','binding':binding,'report':row}),revision)
        result = exchange.apply(preview['previewToken'],revision)
    return {'schemaVersion': 1, 'run': result['run']}
