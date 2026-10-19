"""Real isolated HTTP authority; no production profile or model calls."""
import argparse
import json
import secrets
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--data', required=True)
    parser.add_argument('--skills', required=True)
    parser.add_argument('--legacy-models', action='store_true')
    args = parser.parse_args()
    server.access.clients = lambda: []
    server.access.key_available = lambda _: False
    server.credentials.info = lambda _: {'available': False, 'source': 'fixture', 'removable': False, 'canSave': False}
    server.credentials.revision = lambda _: ''
    store = server.Store(args.data, skills_root=args.skills, executable=False, cicada_candidates=[],
                         repo_roots=[Path(args.skills).parent / 'repos'])
    store.state['catalogs'] = {'openrouter': {'updatedAt': '2026-10-04T00:00:00Z', 'authStatus': 'unverified',
        'models': [{'id': f'fixture/{i:04d}', 'name': f'Fixture model {i}', 'developer': 'Synthetic', 'kind': 'text',
                    'tools': i % 2 == 0, 'vision': False, 'priceVerified': True} for i in range(319)]}}
    if args.legacy_models:
        import model_query
        server.page_models = lambda snapshot, query: server.public_api.models(snapshot)
    http = server.Server(('127.0.0.1', 0), store)
    print(json.dumps({'port': http.server_port, 'version': server.public_api.VERSION,
                      'ownerHost': http.owner_host + ':' + str(http.server_port),
                      'bootstrap': http.owner_sessions.issue_bootstrap()}), flush=True)
    http.serve_forever()
