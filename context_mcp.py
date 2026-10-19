"""Read-only stdio MCP over the actual loopback Agent City authority.

Port is host configuration. Tools cannot choose URLs, paths, grants or commands.
This entry point does not replace an already installed MCP package.
"""
import argparse
import json
import sys
from urllib.parse import urlencode
from urllib.request import Request, build_opener, ProxyHandler
from urllib.error import HTTPError
from provider_catalogs import _NoRedirect

TEXT = {'type': 'string', 'maxLength': 300}
NUMBER = {'type': 'integer', 'minimum': 0}
SCOPED = {'deviceId': TEXT, 'rootId': TEXT}
SEARCH = {**SCOPED, 'q': TEXT, 'kind': {'type': 'string', 'enum': ['skill', 'text']}, 'extension': TEXT,
          'limit': NUMBER, 'offset': NUMBER, 'revision': TEXT}
READ = {**SCOPED, 'id': TEXT, 'revision': TEXT, 'startLine': NUMBER, 'endLine': NUMBER, 'maxBytes': NUMBER, 'byteOffset': NUMBER}
MODELS = {k: TEXT for k in ('q', 'provider', 'developer', 'kind', 'authStatus', 'responseStatus', 'revision')}
MODELS.update({k: {'type': 'boolean'} for k in ('priceVerified', 'tools', 'vision')})
MODELS.update(limit=NUMBER, offset=NUMBER)


def tool(name, description, properties, required):
    return {'name': name, 'description': description, 'inputSchema': {'type': 'object', 'properties': properties,
            'required': required, 'additionalProperties': False}}


TOOLS = [
    tool('agent_city_devices', 'List registered local devices; remote access is not inferred.', {}, []),
    tool('agent_city_file_roots', 'List host-configured root grants and their revision. Cannot grant access.', {}, []),
    tool('agent_city_file_search', 'Bounded metadata search inside one granted device/root. Content stays local.', SEARCH, ['deviceId', 'rootId']),
    tool('agent_city_skill_search', 'Find SKILL.md via the existing skill inventory metadata and explicit root grant.', {k: v for k, v in SEARCH.items() if k != 'kind'}, ['deviceId', 'rootId']),
    tool('agent_city_file_read', 'Read UTF-8 text by enumerated opaque ID, with hash, line and byte bounds.', READ, ['deviceId', 'rootId', 'id']),
    tool('agent_city_read_skill', 'Extend SkillInventory.read(id) through its existing API, within a host root grant.', READ, ['deviceId', 'rootId', 'id']),
    tool('agent_city_models', 'Filter a bounded model catalogue page; separate price/auth/quota/inference evidence. No model launch.', MODELS, []),
]


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate_field')
        result[key] = value
    return result


def parse(raw):
    value = json.loads(raw, object_pairs_hook=unique, parse_constant=lambda _: (_ for _ in ()).throw(ValueError('invalid_number')))
    pending = [(value, 0)]
    while pending:
        item, depth = pending.pop()
        if depth > 64:
            raise ValueError('request_nesting_limit')
        if isinstance(item, dict):
            pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            pending.extend((child, depth + 1) for child in item)
    return value


def validate(name, args):
    definition = next((t for t in TOOLS if t['name'] == name), None)
    if definition is None or type(args) is not dict:
        raise ValueError('unsupported_tool')
    contract = definition['inputSchema']
    if set(args) - set(contract['properties']) or set(contract['required']) - set(args):
        raise ValueError('unsupported_tool_fields')
    for key, value in args.items():
        spec = contract['properties'][key]
        kind = spec['type']
        if (kind == 'string' and (type(value) is not str or len(value) > spec.get('maxLength', 300))
                or kind == 'integer' and (type(value) is not int or value < 0)
                or kind == 'boolean' and type(value) is not bool
                or 'enum' in spec and value not in spec['enum']):
            raise ValueError('invalid_tool_arguments')


class LocalAPI:
    def __init__(self, port=None):
        self.native = port is None
        self.base = f'http://127.0.0.1:{port}'
        self.opener = build_opener(ProxyHandler({}), _NoRedirect())

    def call(self, name, args):
        validate(name, args)
        values = dict(args)
        if name == 'agent_city_devices':
            path = '/api/v1/devices'
        elif name == 'agent_city_file_roots':
            path = '/api/v1/file-roots'
        elif name.endswith('_search'):
            path = '/api/v1/file-search'
            if name == 'agent_city_skill_search':
                values['kind'] = 'skill'
        elif name == 'agent_city_read_skill':
            path = '/api/v1/skill-inventory'
        elif name == 'agent_city_file_read':
            path = '/api/v1/file-read'
        else:
            path = '/api/v1/models'
        values = {k: str(v).lower() if type(v) is bool else v for k, v in values.items()}
        path += '?' + urlencode(values) if values else ''
        if self.native:
            from city import native_request
            value = native_request(path)
            if value is None:
                raise ValueError('native_authority_unavailable')
            return {'content': [{'type': 'text', 'text': json.dumps(value, ensure_ascii=False)}],
                    'structuredContent': value, 'isError': False}
        url = self.base + path
        try:
            with self.opener.open(Request(url), timeout=20) as response:
                raw = response.read(256 * 1024 + 1)
        except HTTPError as exc:
            raw = exc.read(4096)
            value = parse(raw)
            return {'content': [{'type': 'text', 'text': json.dumps(value, ensure_ascii=False)}],
                    'structuredContent': value, 'isError': True}
        if len(raw) > 256 * 1024:
            raise ValueError('response_limit_exceeded')
        value = parse(raw)
        return {'content': [{'type': 'text', 'text': json.dumps(value, ensure_ascii=False)}],
                'structuredContent': value, 'isError': False}


def serve(api):
    for raw in iter(lambda: sys.stdin.buffer.readline(16385), b''):
        ident = None
        try:
            if len(raw) > 16384:
                raise ValueError('request_limit_exceeded')
            request = parse(raw)
            if not isinstance(request, dict):
                raise ValueError('invalid_request_object')
            ident, method = request.get('id'), request['method']
            if not isinstance(method, str):
                raise ValueError('invalid_request_method')
            if not isinstance(request.get('params', {}), dict):
                raise ValueError('invalid_request_params')
            if method.startswith('notifications/'):
                continue
            if method == 'initialize':
                result = {'protocolVersion': request.get('params', {}).get('protocolVersion', '2025-03-26'),
                          'capabilities': {'tools': {}}, 'serverInfo': {'name': 'agent-city-context-local', 'version': '1.0.0'}}
            elif method == 'tools/list':
                result = {'tools': TOOLS}
            elif method == 'ping':
                result = {}
            elif method == 'tools/call':
                try:
                    arguments = request.get('params', {})
                    result = api.call(arguments['name'], arguments.get('arguments', {}))
                except Exception as exc:
                    code = str(exc) if isinstance(exc, ValueError) else 'local_api_unavailable'
                    result = {'content': [{'type': 'text', 'text': code[:100]}], 'isError': True}
            else:
                raise ValueError('unsupported_method')
            answer = {'jsonrpc': '2.0', 'id': ident, 'result': result}
        except (ValueError, KeyError, TypeError, RecursionError):
            answer = {'jsonrpc': '2.0', 'id': ident, 'error': {'code': -32600, 'message': 'Invalid request'}}
        sys.stdout.write(json.dumps(answer, ensure_ascii=False, allow_nan=False) + '\n')
        sys.stdout.flush()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, help='explicit legacy HTTP port; default uses the installed native authority')
    args = parser.parse_args()
    if args.port is not None and not 1 <= args.port <= 65535:
        parser.error('invalid port')
    serve(LocalAPI(args.port))


if __name__ == '__main__':
    main()
