"""Assemble new passive view into two existing assets; originals stay private.

No native/runtime installation, server change or read beyond explicit JS/CSS files.
"""
import hashlib
import json
from pathlib import Path

MARKER = '/* Agent City observed-work bundle v1 */'
BOOT = """
(function(){
 let installed=false;
 function initialize(){
  if(installed||document.documentElement.dataset.agentCityMode!=='passive_dashboard')return;
  installed=true;
  const controller=globalThis.AgentCityObservedHost.install();
  globalThis.AgentCityObservedController=controller;
  queueMicrotask(()=>{if(typeof globalThis.render==='function')globalThis.render();});
 }
 window.addEventListener('agentcity:live-summary',initialize);
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',initialize,{once:true});
 else initialize();
})();
"""


def bundle(source_root):
    root = Path(source_root) / 'static'
    return '\n' + MARKER + '\n' + '\n'.join(
        (root / name).read_text(encoding='utf-8') for name in
        ('observed-work.js', 'observed-feed.js', 'observed-host.js')) + BOOT


def assemble(baseline_root, source_root, expected_hashes=None):
    """Return complete private planned files. Never publish returned legacy content."""
    baseline = Path(baseline_root)
    result = {}
    for name in ('live-sessions.js', 'live-sessions.css'):
        path = baseline / 'static' / name
        if path.is_symlink(): raise ValueError('redirected baseline asset')
        raw = path.read_bytes()
        if expected_hashes is not None and hashlib.sha256(raw).hexdigest() != expected_hashes.get(name):
            raise ValueError('baseline asset hash mismatch')
        content = raw.decode('utf-8')
        if MARKER in content: raise ValueError('view already assembled; use original approved copy')
        if name.endswith('.js'):
            result['static/' + name] = content + bundle(source_root)
        else:
            result['static/' + name] = content + '\n' + MARKER + '\n' + (Path(source_root) / 'static/observed-work.css').read_text(encoding='utf-8')
    return result


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, required=True, help='approved PRIVATE source-only baseline directory')
    parser.add_argument('--output-dir', type=Path, required=True, help='NEW PRIVATE review directory, outside any git checkout')
    parser.add_argument('--expected-hashes', type=Path, help='private JSON map of the two input asset SHA256 values')
    args = parser.parse_args()
    output = args.output_dir.resolve()
    if output.exists() or any((p / '.git').exists() for p in (output, *output.parents)):
        parser.error('output must be a new private directory outside git')
    expected = json.loads(args.expected_hashes.read_text(encoding='utf-8')) if args.expected_hashes else None
    planned = assemble(args.baseline, Path(__file__).resolve().parents[1], expected)
    output.mkdir(parents=True)
    for name, content in planned.items():
        path = output / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode('utf-8'))
    print(json.dumps({'plannedAssets': len(planned), 'installed': False, 'baselineWritten': False}))
