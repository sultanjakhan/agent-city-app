"""Read Agent City context or report a skill actually used by an agent."""
import argparse
import json
import re
import sys
from pathlib import Path
from urllib.error import URLError, HTTPError
from urllib.parse import urlencode
from urllib.request import Request, build_opener, ProxyHandler
from provider_catalogs import _NoRedirect
from codex_usage import UsageError, usage_for_turn, enrich_report


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
        print(json.dumps(payload,ensure_ascii=False,allow_nan=False))
        return 0
    except (ValueError,TypeError,KeyError,OSError,URLError):
        print('Owner-delegated CLI request rejected; no grant details are logged.',file=sys.stderr)
        return 1


def main():
    if sys.argv[1:]==['--owner-delegated-stdin']:
        return delegated_stdin()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('resource', choices=['manifest', 'models', 'providers', 'skills', 'skill-inventory', 'projects', 'extensions', 'repositories', 'rules', 'context', 'report-use', 'directory', 'dashboard', 'report-run', 'codex-usage'])
    parser.add_argument('--port', type=int, default=47831)
    parser.add_argument('--slug', help='read one skill, with the skills resource')
    parser.add_argument('--id', help='read an enumerated skill from skill-inventory')
    parser.add_argument('--cwd', help='working directory for repository context')
    parser.add_argument('--scope', default='global', help='global or enumerated repository ID for rules')
    parser.add_argument('--agent', choices=['codex', 'claude', 'other'], default='codex')
    parser.add_argument('--event-id', help='unique ID for one actual use; retries are deduplicated')
    parser.add_argument('--file', type=Path, help='UTF-8 JSON report for report-run; no prompts, keys or task text')
    parser.add_argument('--codex-session', help='exact local Codex session UUID; with --codex-turn')
    parser.add_argument('--codex-turn', help='completed Codex turn UUID explicitly bound to this run')
    args = parser.parse_args()
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
    if not 1 <= args.port <= 65535:
        parser.error('invalid local port')
    url = f'http://127.0.0.1:{args.port}/api/v1/{args.resource}'
    if args.slug:
        if args.resource != 'skills':
            parser.error('--slug requires the skills resource')
        url += '?' + urlencode({'slug': args.slug})
    if args.id and args.resource != 'report-use':
        if args.resource not in {'skill-inventory', 'repositories'} or args.slug:
            parser.error('--id requires skill-inventory without --slug')
        url += '?' + urlencode({'id': args.id})
    if args.resource == 'context':
        if not args.cwd:
            parser.error('context requires --cwd')
        url += '?' + urlencode({'cwd': args.cwd})
    if args.resource == 'rules':
        url += '?' + urlencode({'scope': args.scope})
    if args.resource == 'report-use' and (not args.id or not args.event_id):
        parser.error('report-use requires --id and --event-id')
    if args.resource == 'report-run' and not args.file:
        parser.error('report-run requires --file')
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
