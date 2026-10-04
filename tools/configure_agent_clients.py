"""Opt-in Windows client setup. Plan first; preserve unrelated MCPs and hooks.

No application launch, credentials, model execution or TaskSync provisioning.
"""
import argparse
import base64
import json
import os
from pathlib import Path
import sys
import tomllib
import uuid

SOURCE = Path(__file__).resolve().parent
REPOSITORY = SOURCE.parent
NATIVE_FILES = ('LocalPipeClient.exe', 'LocalPipeClient.dll',
                'LocalPipeClient.deps.json', 'LocalPipeClient.runtimeconfig.json')


def safe(path):
    path = Path(os.path.abspath(path))
    for entry in (path, *path.parents):
        if entry.exists():
            info = entry.lstat()
            if entry.is_symlink() or getattr(info, 'st_file_attributes', 0) & 0x400:
                raise ValueError('Redirected setup path is not supported')
    return path


def encoded_hook(python, script, config, agent):
    # Both cmd and PowerShell can invoke this bare command. Paths stay literal
    # inside the encoded PowerShell payload, including spaces, quotes and $.
    quote = lambda value: "'" + str(value).replace("'", "''") + "'"
    program = ("$OutputEncoding=[System.Text.UTF8Encoding]::new($false);"
               "[Console]::InputEncoding=$OutputEncoding;"
               "[Console]::OutputEncoding=$OutputEncoding;"
               "$eventJson=[Console]::In.ReadToEnd();"
               "$eventJson | & " + quote(python) + " -X utf8 " + quote(script)
               + " --config " + quote(config) + " --agent " + agent
               + ";exit $LASTEXITCODE")
    encoded = base64.b64encode(program.encode('utf-16-le')).decode('ascii')
    return 'powershell.exe -NoProfile -NonInteractive -EncodedCommand ' + encoded


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')


def plan(*, tools_dir, native_client, cicada_profile, city_profile, clients,
         hooks=False, personal_roots=(), codex_home=None, user_home=None, python=None):
    if not clients or set(clients) - {'codex', 'claude'}:
        raise ValueError('Select codex and/or claude explicitly')
    tools_dir, native_client = safe(tools_dir), safe(native_client)
    cicada_profile, city_profile = safe(cicada_profile), safe(city_profile)
    python = safe(python or sys.executable)
    user_home = safe(user_home or Path.home())
    codex_home = safe(codex_home or os.environ.get('CODEX_HOME', user_home / '.codex'))
    roots = [str(safe(root)) for root in personal_roots]
    if not (cicada_profile / 'calendar.db').is_file() or not city_profile.is_file():
        raise ValueError('Select existing installed application profiles')
    if not python.is_file() or any(not Path(root).is_dir() for root in roots):
        raise ValueError('Python or an opted-in personal directory is unavailable')
    if hooks and not roots:
        raise ValueError('Hooks require explicit personal directories')
    if tools_dir == REPOSITORY or REPOSITORY in tools_dir.parents:
        raise ValueError('Mutable setup files must stay outside the repository')
    for protected in (cicada_profile, city_profile.parent):
        if tools_dir == protected or protected in tools_dir.parents:
            raise ValueError('Keep the client transport separate from app data')
    changes = {}
    for name in ('agent_mcp.py', 'agent_hooks.py'):
        changes[tools_dir / name] = safe(SOURCE / name).read_bytes()
    for name in NATIVE_FILES:
        source = safe(native_client.parent / name)
        if not source.is_file():
            raise ValueError('Select a complete LocalPipeClient publish output')
        changes[tools_dir / name] = source.read_bytes()
    configuration = dict(cicadaProfile=str(cicada_profile), cityProfile=str(city_profile),
                         client=str(tools_dir / 'LocalPipeClient.exe'),
                         outbox=str(tools_dir / 'outbox.db'), personalRoots=roots)
    destination = tools_dir / 'connections.json'
    if destination.exists() and json.loads(destination.read_text(encoding='utf-8-sig')) != configuration:
        raise ValueError('Existing connection configuration differs; preserve it and choose another tools directory')
    changes[destination] = json_bytes(configuration)
    servers = {name: dict(command=str(python), args=['-X', 'utf8',
               str(tools_dir / 'agent_mcp.py'), '--app', app, '--profile', str(profile),
               '--client', str(tools_dir / 'LocalPipeClient.exe')])
               for name, app, profile in [('cicada-local', 'cicada', cicada_profile),
                                          ('agent-city-local', 'agent-city', city_profile)]}
    if 'codex' in clients:
        path = safe(codex_home / 'config.toml')
        original = path.read_text(encoding='utf-8-sig') if path.exists() else ''
        value = tomllib.loads(original)
        text = original
        for name, server in servers.items():
            current = value.get('mcp_servers', {}).get(name)
            if current is not None:
                if any(current.get(key) != expected for key, expected in server.items()):
                    raise ValueError('An existing MCP name has different configuration')
                continue
            text += '\n[mcp_servers.' + name + ']\n'
            text += 'command = ' + json.dumps(server['command'], ensure_ascii=False) + '\n'
            text += 'args = ' + json.dumps(server['args'], ensure_ascii=False) + '\n'
        parsed = tomllib.loads(text)
        assert all(parsed['mcp_servers'][name]['args'] == server['args'] for name, server in servers.items())
        changes[path] = text.encode('utf-8') if text != original else path.read_bytes()
    if 'claude' in clients:
        path = safe(user_home / '.claude.json')
        value = json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else {}
        current = value.setdefault('mcpServers', {})
        for name, server in servers.items():
            if name in current and any(current[name].get(key) != expected for key, expected in server.items()):
                raise ValueError('An existing MCP name has different configuration')
            current.setdefault(name, server)
        changes[path] = json_bytes(value)
    if hooks:
        for agent in dict.fromkeys(clients):
            path = safe(codex_home / 'hooks.json' if agent == 'codex' else user_home / '.claude/settings.json')
            value = json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else {}
            events = ['UserPromptSubmit', 'PreToolUse', 'Stop', 'Interrupt' if agent == 'codex' else 'StopFailure']
            command = encoded_hook(python, tools_dir / 'agent_hooks.py', destination, agent)
            for event in events:
                groups = value.setdefault('hooks', {}).setdefault(event, [])
                if not any(handler.get('command') == command for group in groups for handler in group.get('hooks', [])):
                    groups.append({'hooks': [dict(type='command', command=command, timeout=3 if event == 'Interrupt' else 120)]})
            changes[path] = json_bytes(value)
    before = {safe(path): path.read_bytes() if path.exists() else None for path in changes}
    return {'changes': changes, 'before': before, 'toolsDir': tools_dir}


def apply(prepared):
    changed = {path: data for path, data in prepared['changes'].items() if prepared['before'][path] != data}
    if not changed:
        return {'changedFiles': 0, 'backup': None}
    # Reject concurrent edits before any write; check each target again at commit.
    def unchanged(path):
        safe(path)
        return (path.read_bytes() if path.exists() else None) == prepared['before'][path]
    if not all(unchanged(path) for path in changed):
        raise ValueError('Configuration changed after the plan; run setup again')
    backup = prepared['toolsDir'] / 'setup-backups' / uuid.uuid4().hex
    backup.mkdir(parents=True)
    manifest = []
    for index, path in enumerate(changed):
        data = prepared['before'][path]
        if data is not None:
            (backup / str(index)).write_bytes(data)
        manifest.append({'path': str(path), 'previousCopy': str(index) if data is not None else None})
    (backup / 'manifest.json').write_bytes(json_bytes(manifest))
    for path, data in changed.items():
        if not unchanged(path):
            raise ValueError('Concurrent edit preserved; setup stopped. Inspect the backup manifest for partial changes')
        path.parent.mkdir(parents=True, exist_ok=True)
        staged = path.with_name(path.name + '.setup-' + uuid.uuid4().hex)
        staged.write_bytes(data)
        os.replace(staged, path)
    return {'changedFiles': len(changed), 'backup': str(backup)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('tools-dir', 'native-client', 'cicada-profile', 'city-profile'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--client', action='append', choices=['codex', 'claude'], required=True)
    parser.add_argument('--personal-root', action='append', type=Path, default=[])
    parser.add_argument('--codex-home', type=Path)
    parser.add_argument('--user-home', type=Path)
    parser.add_argument('--python', type=Path)
    parser.add_argument('--hooks', action='store_true')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if os.name != 'nt':
        parser.error('This setup targets the current Windows pipe transport; other platforms are not accepted yet')
    prepared = plan(tools_dir=args.tools_dir, native_client=args.native_client,
                    cicada_profile=args.cicada_profile, city_profile=args.city_profile,
                    clients=args.client, hooks=args.hooks, personal_roots=args.personal_root,
                    codex_home=args.codex_home, user_home=args.user_home, python=args.python)
    result = apply(prepared) if args.apply else {'planOnly': True,
        'changedFiles': sum(prepared['before'][path] != data for path, data in prepared['changes'].items()),
        'files': [str(path) for path in prepared['changes']]}
    result.update(taskSyncConfigured=False, hooksRequireClientTrust=args.hooks, applicationsLaunched=False)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
