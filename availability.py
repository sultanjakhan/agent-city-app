"""Catalog presence, completed replies and eligibility are separate facts."""
from datetime import datetime, timezone

STOP = {'rate_limited', 'forbidden', 'auth_error', 'payment_required', 'missing_key',
        'credential_error', 'catalog_error', 'network_error'}


def responded(check):
    return (check.get('status') in {'ok', 'mismatch'} and bool(check.get('reply'))
            and check.get('finishReason') == 'stop')


def summarize(snapshot):
    sources = {s['id']: s for s in snapshot.get('sources', [])}
    checks = snapshot.get('checks', {})
    rows = {}
    pending = []
    blocked = set()
    for check in checks.values():
        if check.get('status') not in STOP:
            continue
        try:
            elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(check['attemptedAt'].replace('Z', '+00:00'))).total_seconds()
            if elapsed < 60:
                blocked.add(check.get('provider'))
        except (ValueError, KeyError, TypeError):
            pass
    for provider, catalog in snapshot.get('catalogs', {}).items():
        if catalog.get('docsOnly'):
            continue
        source = sources.get(provider, {})
        for model in catalog.get('models', []):
            check = checks.get(provider + '|' + model['id'], {})
            row = rows.setdefault(model['id'], set())
            if responded(check):
                row.add('responded')
            if not snapshot.get('credentials', {}).get(provider):
                row.add('needsKey')
            elif source.get('accessMode') == 'subscription' or source.get('discoveryOnly') or model.get('priceVerified') is not True or model.get('kind', 'chat') != 'chat':
                row.add('needsAccess')
            elif provider in blocked:
                row.add('needsRetry')
            elif check.get('sent') or check.get('status') not in {None, 'skipped', 'key_changed', 'missing_key'}:
                row.add('needsRetry')
            else:
                row.add('pending')
                pending.append({'provider': provider, 'model': model['id']})
    # Each model belongs to exactly one summary bucket; a working route wins.
    priority = ['responded', 'pending', 'needsRetry', 'needsAccess', 'needsKey']
    counts = dict.fromkeys(priority, 0)
    for states in rows.values():
        for category in priority:
            if category in states:
                counts[category] += 1
                break
    pending = [r for r in pending if 'responded' not in rows[r['model']]]
    return {'total': len(rows), **counts, 'pendingRoutes': pending}
