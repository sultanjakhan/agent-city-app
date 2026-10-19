"""Read Agent City context or report a skill actually used by an agent."""
import argparse
import json
import re
import sys
import os
import subprocess
from pathlib import Path
from urllib.error import URLError, HTTPError
from urllib.parse import urlencode
from urllib.request import Request, build_opener, ProxyHandler
from provider_catalogs import _NoRedirect
from codex_usage import UsageError, usage_for_turn, enrich_report


def native_request(path, body=None):
    """Use the installed current-account pipe; never start/focus an application."""
    if os.name != 'nt':
        return None
    pointer = Path(os.environ.get('AGENT_CITY_CONFIG') or
                   Path(os.environ['LOCALAPPDATA']) / 'Agent City/connection.json')
    if not pointer.is_file():
        return None
    host = (Path(sys.executable).parent.parent / 'AgentCity.exe' if getattr(sys, 'frozen', False)
            else Path(os.environ['LOCALAPPDATA']) / 'Programs/Agent City/AgentCity.exe')
    for item in (pointer, *pointer.parents, host, *host.parents):
        if item.exists() and (item.is_symlink() or getattr(item.lstat(), 'st_file_attributes', 0) & 0x400):
            raise ValueError('redirected native authority')
    if not host.is_file():
        raise OSError('native host unavailable')
    frame = json.dumps({'method': 'GET' if body is None else 'POST', 'path': path, 'body': body},
                       ensure_ascii=False, allow_nan=False).encode() + b'\n'
    if len(frame) >= 16000:
        raise ValueError('native request too large')
    result = subprocess.run([str(host), '--agent-request-stdin', str(pointer)], input=frame,
                            capture_output=True, timeout=45, creationflags=subprocess.CREATE_NO_WINDOW)
    if len(result.stdout) > 1024 * 1024:
        raise ValueError('native reply too large')
    reply = json.loads(result.stdout)
    if result.returncode or not reply.get('ok'):
        raise OSError('native authority rejected request')
    return reply['result']


def delegated_stdin():
    # The capability travels only in the trusted parent's inherited stdin pipe.
    from owner_session import CAPABILITY
    try:
        raw=sys.stdin.buffer.read(16385)
        if len(raw)>16384:raise ValueError()
        message=json.loads(raw)
        if not isinstance(message,dict) or set(message)!={'version','port','ownerHost','method','path','body','grant'} or message['version']!=1 or type(message['port']) is not int or not 1<=message['port']<=65535 or not isinstance(message['ownerHost'],str) or not re.fullmatch(r'agent-city-[a-f0-9]{32}\.localhost',message['ownerHost']) or not isinstance(message['grant'],str) or not CAPABILITY.fullmatch(message['grant']) or message['method'] not in ('GET','POST') or not isinstance(message['path'],str):raise ValueError()
        owner=message['ownerHost']+':'+str(message['port'])
        headers={'Host':owner,'Origin':'http://'+owner,'X-Agent-City':'1','X-Agent-City-Grant':message['grant'],'Content-Type':'application/json'}
        data=json.dumps(message['body'],allow_nan=False).encode() if message['method']=='POST' else None
        request=Request('http://127.0.0.1:'+str(message['port'])+message['path'],data=data,headers=headers,method=message['method'])
        with build_opener(ProxyHandler({}),_NoRedirect()).open(request,timeout=10) as response:raw=response.read(8*1024*1024+1)
        if len(raw)>8*1024*1024:raise ValueError()
        payload=json.loads(raw)
        # The inherited-pipe protocol is UTF-8, regardless of the Windows
        # console code page of a newly launched (including frozen) CLI child.
        sys.stdout.buffer.write(json.dumps(payload,ensure_ascii=False,allow_nan=False).encode('utf-8')+b'\n')
        sys.stdout.buffer.flush()
        return 0
    except (ValueError,TypeError,KeyError,OSError,URLError):
        print('Owner-delegated CLI request rejected; no grant details are logged.',file=sys.stderr)
        return 1


def main():
    if sys.argv[1:]==['--owner-delegated-stdin']:
        return delegated_stdin()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('resource', choices=['manifest', 'models', 'providers', 'skills', 'skill-inventory', 'projects', 'extensions', 'repositories', 'rules', 'context', 'report-use', 'directory', 'dashboard', 'report-run', 'codex-usage', 'devices', 'file-roots', 'file-search', 'file-read', 'grant-root', 'revoke-root'])
    parser.add_argument('--port', type=int, help='explicit legacy HTTP server; otherwise use the installed native pipe')
    parser.add_argument('--slug', help='read one skill, with the skills resource')
    parser.add_argument('--id', help='read an enumerated skill from skill-inventory')
    parser.add_argument('--cwd', help='working directory for repository context')
    parser.add_argument('--scope', default='global', help='global or enumerated repository ID for rules')
    parser.add_argument('--agent', choices=['codex', 'claude', 'other'], default='codex')
    parser.add_argument('--event-id', help='unique ID for one actual use; retries are deduplicated')
    parser.add_argument('--file', type=Path, help='UTF-8 JSON report for report-run; no prompts, keys or task text')
    parser.add_argument('--codex-session', help='exact local Codex session UUID; with --codex-turn')
    parser.add_argument('--codex-turn', help='completed Codex turn UUID explicitly bound to this run')
    parser.add_argument('--device-id')
    parser.add_argument('--root-id')
    parser.add_argument('--q')
    parser.add_argument('--kind')
    parser.add_argument('--extension')
    parser.add_argument('--limit', type=int)
    parser.add_argument('--offset', type=int)
    parser.add_argument('--revision')
    parser.add_argument('--start-line', type=int)
    parser.add_argument('--end-line', type=int)
    parser.add_argument('--max-bytes', type=int)
    parser.add_argument('--byte-offset', type=int)
    parser.add_argument('--provider')
    parser.add_argument('--developer')
    parser.add_argument('--price-verified', choices=['true', 'false'])
    parser.add_argument('--path', type=Path, help='grant-root only; never sent through HTTP')
    parser.add_argument('--data', type=Path, help='host-local grant configuration directory')
    parser.add_argument('--label', default='Local documents')
    parser.add_argument('--source', choices=['file', 'workspace', 'installed', 'plugin-cache'], default='file')
    args = parser.parse_args()
    if args.resource in {'grant-root', 'revoke-root'}:
        from file_context import FileContext, ContextError
        if args.data is None or not args.data.is_absolute() or not args.data.is_dir():
            parser.error('host grants require an existing absolute --data profile directory')
        directory = args.data
        if not args.revision or (args.resource == 'grant-root' and not args.path) or (args.resource == 'revoke-root' and not args.root_id):
            parser.error('host grant mutation requires revision and path/root-id; read file-roots first')
        try:
            local = FileContext(directory)
            result = local.grant(args.path, args.label, args.revision, args.source) if args.resource == 'grant-root' else local.revoke(args.root_id, args.revision)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return
        except ContextError as exc:
            parser.exit(1, exc.code + '\n')
    if args.path or args.data:
        parser.error('path/data are host grant configuration only')
    usage = None
    if args.resource == 'codex-usage' or args.codex_session or args.codex_turn:
        if args.resource not in {'codex-usage', 'report-run'}:
            parser.error('Codex usage flags require codex-usage or report-run')
        try:
            usage = usage_for_turn(args.codex_session, args.codex_turn)
        except (UsageError, OSError) as exc:
            parser.exit(1, f'Cannot import Codex usage: {exc}\n')
        if args.resource == 'codex-usage':
            print(json.dumps(usage, indent=2))
            return
    explicit_port = args.port is not None
    args.port = args.port if explicit_port else 47831
    if not 1 <= args.port <= 65535:
        parser.error('invalid local port')
    url = f'http://127.0.0.1:{args.port}/api/v1/{args.resource}'
    fields = {k: v for k, v in {'deviceId': args.device_id, 'rootId': args.root_id, 'q': args.q, 'kind': args.kind,
              'extension': args.extension, 'limit': args.limit, 'offset': args.offset, 'revision': args.revision,
              'startLine': args.start_line, 'endLine': args.end_line, 'maxBytes': args.max_bytes, 'byteOffset': args.byte_offset,
              'provider': args.provider, 'developer': args.developer, 'priceVerified': args.price_verified}.items() if v is not None}
    if args.slug:
        if args.resource != 'skills':
            parser.error('--slug requires the skills resource')
        fields['slug'] = args.slug
    if args.id and args.resource != 'report-use':
        if args.resource not in {'skill-inventory', 'repositories', 'file-read'} or args.slug:
            parser.error('--id requires skill-inventory, repositories or file-read without --slug')
        fields['id'] = args.id
    if args.resource == 'context':
        if not args.cwd:
            parser.error('context requires --cwd')
        fields['cwd'] = args.cwd
    if args.resource == 'rules':
        fields['scope'] = args.scope
    if fields:
        url += '?' + urlencode(fields)
    if args.resource == 'report-use' and (not args.id or not args.event_id):
        parser.error('report-use requires --id and --event-id')
    if args.resource == 'report-run' and not args.file:
        parser.error('report-run requires --file')
    if not explicit_port:
        try:
            if args.resource == 'report-run':
                parser.exit(1, 'Use the Agent City MCP for reports bound to an exact Cicada task.\n')
            path = url.split('/api/', 1)[1]
            body = None
            if args.resource == 'report-use':
                path = 'skill-activity'
                body = {'id': args.id, 'kind': 'use', 'agent': args.agent, 'eventId': args.event_id}
            payload = native_request('/api/' + path, body)
            if payload is not None:
                print(json.dumps(payload, ensure_ascii=False, indent=2))
                return 0
        except (OSError, ValueError, subprocess.TimeoutExpired):
            parser.exit(1, 'Installed Agent City is unavailable or denied the native request. No window was opened.\n')
    try:
        opener = build_opener(ProxyHandler({}), _NoRedirect())
        req = Request(url)
        if args.resource in {'report-use', 'report-run'}:
            with opener.open(f'http://127.0.0.1:{args.port}/api/state', timeout=10) as response:
                state = json.loads(response.read(8 * 1024 * 1024 + 1))
            token = state.get('csrfToken')
            if not isinstance(token, str) or not token:
                raise ValueError('missing local token')
            if args.resource == 'report-run':
                with args.file.open('rb') as stream:
                    raw = stream.read(4097)
                if len(raw) > 4096:
                    raise ValueError('report too large')
                report = json.loads(raw)
                if usage is not None:
                    report = enrich_report(report, usage)
                endpoint = '/api/runs/report'
            else:
                report = {'id': args.id, 'kind': 'use', 'agent': args.agent, 'eventId': args.event_id}
                endpoint = '/api/skill-activity'
            req = Request(f'http://127.0.0.1:{args.port}{endpoint}',
                          data=json.dumps(report).encode(),
                          headers={'X-Agent-City': '1', 'X-Agent-City-Token': token, 'Content-Type': 'application/json'})
        with opener.open(req, timeout=10) as response:
            raw = response.read(8 * 1024 * 1024 + 1)
        if len(raw) > 8 * 1024 * 1024:
            raise ValueError('response too large')
        payload = json.loads(raw)
        if args.resource != 'report-use' and payload.get('schemaVersion') != 1:
            raise ValueError('unsupported schema')
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    except HTTPError as exc:
        if exc.code == 401:
            parser.exit(1, 'Agent City requires an owner session. An authorized CLI grant is not implemented in this prototype; no action was performed.\n')
        parser.exit(1, 'Agent City denied the request. No action was performed.\n')
    except UsageError as exc:
        parser.exit(1, f'Cannot import Codex usage: {exc}\n')
    except (URLError, ValueError, OSError):
        parser.exit(1, 'Agent City is unavailable or returned an unsupported response. Start the local app.\n')


if __name__ == '__main__':
    raise SystemExit(main())
