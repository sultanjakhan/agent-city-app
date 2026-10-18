"""Prepare an owned Windows cloud build root from the checked-in dependency locks.

No signing material, application profile or installed application is accessed.
The subsequent build_desktop.py invocation remains offline and requires clean Git.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
MARKER = '.agentcity-desktop-build-root'
MARKER_TEXT = 'Agent City isolated build outputs only\n'


def prepare(build):
    if sys.platform != 'win32':
        raise ValueError('Windows x64 cloud executor required')
    build = build.absolute()
    for path in (build, *build.parents):
        if path.is_symlink() or (path.exists() and getattr(path.lstat(), 'st_file_attributes', 0) & 0x400):
            raise ValueError('reparse build root')
    build = build.resolve()
    if build == ROOT or ROOT in build.parents or build in ROOT.parents or len(build.parts) < 3:
        raise ValueError('build root must be external to the source checkout')
    # Preparation owns a fresh directory, never overwrites another run's inputs.
    build.mkdir(parents=True, exist_ok=False)
    (build / MARKER).write_text(MARKER_TEXT)
    dependencies = json.loads((ROOT / 'desktop/build-dependencies.json').read_text())
    requirements = []
    for item in dependencies:
        wheel = item['wheel']
        if Path(wheel).name != wheel or not wheel.endswith('.whl'):
            raise ValueError('invalid locked wheel path')
        name, version, *_ = wheel.split('-')
        requirements.append(f'{name}=={version} --hash=sha256:{item["sha256"]}')
    requirements_path = build / 'build-requirements.txt'
    requirements_path.write_text('\n'.join(requirements) + '\n', encoding='utf-8')
    wheels = build / 'dependencies'
    wheels.mkdir()
    env = dict(os.environ)
    env.update(DOTNET_SKIP_FIRST_TIME_EXPERIENCE='1', DOTNET_CLI_TELEMETRY_OPTOUT='1',
               DOTNET_GENERATE_ASPNET_CERTIFICATE='false', DOTNET_CLI_HOME=str(build / 'dotnet-home'))
    subprocess.run([sys.executable, '-m', 'pip', 'download', '--require-hashes', '--no-deps',
                    '--only-binary=:all:', '--dest', str(wheels), '-r', str(requirements_path)], env=env, check=True)
    for item in dependencies:
        if hashlib.sha256((wheels / item['wheel']).read_bytes()).hexdigest() != item['sha256']:
            raise ValueError('locked wheel mismatch')
    subprocess.run([sys.executable, '-m', 'pip', 'install', '--no-index', '--no-deps', '--require-hashes',
                    '--find-links', str(wheels), '--target', str(build / 'python-tools'),
                    '-r', str(requirements_path)], env=env, check=True)
    subprocess.run(['dotnet', 'restore', str(ROOT / 'desktop/AgentCity.Desktop.csproj'),
                    '--locked-mode', '-p:RestorePackagesPath=' + str(build / 'nuget-packages')], env=env, check=True)
    print('Locked cloud build inputs prepared; no package was built or signed.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-root', type=Path, required=True)
    prepare(parser.parse_args().build_root)
