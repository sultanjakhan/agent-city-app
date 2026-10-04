"""Bounded local executor reports paired to the selected native authority."""
from work_exchange import exact, validate_binding
from run_store import validate, RunError


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
