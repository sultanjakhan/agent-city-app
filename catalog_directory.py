"""Public discovery only. Registry entries never become credential destinations."""
import json
import re
from urllib.parse import urlsplit
from urllib.request import Request, build_opener
from provider_catalogs import _NoRedirect

URL = 'https://models.dev/api.json'
DOCS = 'https://models.dev/'


def normalize(payload):
    if not isinstance(payload, dict):
        raise ValueError('invalid registry')
    providers = []
    for ident, entry in list(payload.items())[:1000]:
        if not re.fullmatch(r'[a-zA-Z0-9_-]{1,100}', ident) or not isinstance(entry, dict):
            continue
        docs = entry.get('doc', '')
        if not isinstance(docs, str) or len(docs) > 1000:
            docs = ''
        parts = urlsplit(docs)
        if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password:
            docs = ''
        name = entry.get('name')
        models = entry.get('models', {})
        providers.append({'id': ident, 'name': name[:150] if isinstance(name, str) else ident,
                          'docs': docs, 'modelCount': len(models) if isinstance(models, dict) else 0})
    if not providers:
        raise ValueError('registry has no providers')
    return {'providers': sorted(providers, key=lambda p: p['name'].casefold()),
            'sourceUrl': URL, 'docs': DOCS}


def fetch():
    request = Request(URL, headers={'Accept': 'application/json', 'User-Agent': 'AgentCityPanel/0.4'})
    with build_opener(_NoRedirect()).open(request, timeout=20) as response:
        raw = response.read(16 * 1024 * 1024 + 1)
    if len(raw) > 16 * 1024 * 1024:
        raise ValueError('registry too large')
    return normalize(json.loads(raw))
