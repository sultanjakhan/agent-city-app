"""Pack only verified public build files; private configuration never enters a release."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import stat
import zipfile


def pack(candidate: Path, output: Path):
    candidate = candidate.absolute()
    for path in [candidate, *candidate.parents]:
        if path.is_symlink() or getattr(path.stat(), 'st_file_attributes', 0) & 0x400:
            raise ValueError('Reparse candidate')
    manifest = json.loads((candidate / 'build-manifest.json').read_text('utf-8'))
    version = manifest['applicationSourceVersion']
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('Invalid release version')
    paths = {'build-manifest.json'}
    for item in manifest['files']:
        relative = item['path']
        parts = relative.replace('\\', '/').split('/')
        if any(p in ('', '.', '..') for p in parts) or ':' in relative:
            raise ValueError('Invalid release path')
        if relative.casefold() in {x.casefold() for x in paths}:
            raise ValueError('Duplicate release path')
        path = candidate / relative
        if path.is_symlink() or getattr(path.stat(), 'st_file_attributes', 0) & 0x400:
            raise ValueError('Reparse release file')
        if path.stat().st_size != item['bytes'] or hashlib.sha256(path.read_bytes()).hexdigest() != item['sha256']:
            raise ValueError('Build inventory mismatch')
        paths.add(relative)
    actual = set()
    for path in candidate.rglob('*'):
        if path.is_symlink() or getattr(path.stat(), 'st_file_attributes', 0) & 0x400:
            raise ValueError('Reparse release tree')
        if path.is_file():
            actual.add(path.relative_to(candidate).as_posix())
    if actual != paths:
        raise ValueError('Unlisted release files')
    forbidden = {'desktop-profile.json', 'connection.json', 'connection.local.json', 'storage.local.json',
                 'installation.json', 'uninstall-agentcity.ps1', 'updates-channel.json'}
    if any(Path(p).name.casefold() in forbidden or Path(p).suffix.casefold() in {'.dpapi', '.key', '.pem', '.db', '.sqlite'} for p in paths):
        raise ValueError('Private release file')
    output.mkdir(parents=True, exist_ok=False)
    name = f'agent-city-windows-x64-{version}.zip'
    package = output / name
    with zipfile.ZipFile(package, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for relative in sorted(paths):
            archive.write(candidate / relative, relative)
    latest = {'schemaVersion': 1, 'version': version, 'packageName': name,
              'packageSha256': hashlib.sha256(package.read_bytes()).hexdigest(), 'packageBytes': package.stat().st_size}
    (output / 'latest.json').write_bytes(json.dumps(latest, separators=(',', ':')).encode('utf-8'))
    return latest


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--candidate', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(pack(args.candidate, args.output)))
