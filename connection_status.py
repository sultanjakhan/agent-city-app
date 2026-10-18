"""Dated catalogue observations are independent of current account access.

Pure projection of existing, non-secret snapshots: no network, client execution,
credential reads or persistence. Error details are allowlisted classifications.
"""
from datetime import datetime, timezone
import re
from urllib.parse import urlsplit, urlunsplit


def stamp(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed.isoformat(timespec='seconds') if parsed.tzinfo else None
    except ValueError:
        return None


def public_url(value):
    try:
        parts = urlsplit(value)
        if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password:
            return None
        # Query strings and fragments can carry credentials; never expose them.
        return urlunsplit((parts.scheme, parts.netloc, parts.path, '', ''))
    except (ValueError, TypeError, AttributeError):
        return None


def error_reason(value):
    if not value:
        return None
    text = value if isinstance(value, str) else ''
    match = re.search(r'\bHTTP\s+(\d{3})\b', text, re.I)
    if match:
        code = int(match[1])
        return {'category': {401: 'authentication', 403: 'forbidden', 429: 'rate_limit'}.get(code, 'http'),
                'httpStatus': code}
    categories = [('timeout', ('вовремя', 'timeout', 'timed out')),
                  ('format', ('формат', 'format', 'json')),
                  ('storage', ('сохранить', 'save')),
                  ('network', ('подключиться', 'connect', 'network'))]
    lowered = text.lower()
    for category, markers in categories:
        if any(marker in lowered for marker in markers):
            return {'category': category, 'httpStatus': None}
    return {'category': 'unknown', 'httpStatus': None}


def summarize(snapshot):
    local_only = bool(snapshot.get('settings', {}).get('localOnly'))
    current = stamp(snapshot.get('serverTime'))
    result = {}
    for source in snapshot.get('sources', []):
        ident = source['id']
        catalog = snapshot.get('catalogs', {}).get(ident, {})
        updated = stamp(catalog.get('updatedAt'))
        observed = stamp(catalog.get('observedAt')) or updated
        attempt = stamp(catalog.get('attemptedAt'))
        error = error_reason(catalog.get('error'))
        published = catalog.get('catalogScope') == 'published' or str(catalog.get('sourceKind', '')).startswith('official_docs')
        # An empty, successfully dated catalogue is still a saved snapshot.
        saved = bool(updated or observed)
        provenance = ('published_docs' if published else 'provider_api') if saved else 'none'
        stale = None
        if observed and current:
            age = (datetime.fromisoformat(current) - datetime.fromisoformat(observed)).total_seconds()
            if age >= 0:
                stale = age > 3600
        auth_status = catalog.get('authStatus')
        successful_attempt = bool(attempt and updated and auth_status != 'missing_key'
                                  and 0 <= (datetime.fromisoformat(attempt) - datetime.fromisoformat(updated)).total_seconds() <= 5)
        auth_observation = None
        if source.get('accountCatalog') and attempt and auth_status in {'accepted', 'rejected', 'forbidden', 'rate_limited'}:
            auth_observation = {'status': auth_status, 'observedAt': attempt}
        runtime = snapshot.get('providerRuntime', {}).get(ident)
        client_observation = None
        if runtime and stamp(runtime.get('checkedAt')):
            client_observation = {key: runtime.get(key) for key in ('client', 'source', 'status', 'auth')}
            client_observation['observedAt'] = stamp(runtime['checkedAt'])
        latest_reply = None
        for check in snapshot.get('checks', {}).values():
            at = stamp(check.get('attemptedAt'))
            if check.get('provider') == ident and check.get('status') in {'ok', 'mismatch'} and check.get('reply') and check.get('finishReason') == 'stop' and at:
                if latest_reply is None or datetime.fromisoformat(at) > datetime.fromisoformat(latest_reply):
                    latest_reply = at
        result[ident] = {
            'catalog': {'state': 'saved' if saved else 'missing', 'source': provenance,
                        'sourceUrl': public_url(catalog.get('sourceUrl') if published else source.get('apiCatalogUrl') or source.get('catalogUrl')),
                        'updatedAt': updated, 'observedAt': observed, 'stale': stale,
                        'modelCount': len(catalog.get('allModels', catalog.get('models', [])))},
            'refresh': {'state': 'paused' if local_only else 'available' if source.get('catalogSupported', True) else 'unsupported',
                        'attemptedAt': attempt, 'lastResult': 'failed' if error else 'succeeded' if successful_attempt else 'not_checked',
                        'error': error},
            # Neither a public endpoint response nor a cache proves provider-wide availability.
            'providerAvailability': 'not_checked',
            'authentication': {'state': 'paused' if local_only else 'not_checked', 'lastObservation': auth_observation,
                               'clientObservation': client_observation},
            'entitlement': 'not_checked',
            'inference': {'state': 'paused' if local_only else 'not_checked', 'lastCompletedReplyAt': latest_reply},
        }
    return result
