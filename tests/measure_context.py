"""Comparable loopback measurements and one allowed real skill through HTTP/MCP."""
import argparse
import hashlib
import json
from pathlib import Path
import statistics
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_context_http_mcp import ContextTransportTests, SKILL


def measure(function, samples=5):
    times, sizes = [], []
    for _ in range(samples):
        start = time.perf_counter()
        status, result, size = function()
        assert status == 200, result
        times.append((time.perf_counter() - start) * 1000)
        sizes.append(size)
    return {'medianMs': round(statistics.median(times), 3), 'bytes': sizes[-1], 'samples': samples}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--real-skill-root', type=Path)
    args = parser.parse_args()
    case = ContextTransportTests()
    case.setUp()
    report = {'method': 'same Python opener, UTF-8 wire bytes, 5 sequential loopback GETs, same 319-route synthetic snapshot; only model response policy differs', 'installedMcpUpdated': False}
    try:
        for i in range(400):
            path = case.skills / f'fixture-{i:04d}'
            path.mkdir()
            (path / 'SKILL.md').write_text(SKILL.replace('synthetic-skill', f'needle-{i:04d}') + ('inert fixture text\n' * 3000), encoding='utf-8')
        report['fileCount'] = 403
        started = time.perf_counter()
        result = case.search(q='needle-0399', kind='skill', limit=1)
        report['coldIndexMs'] = round((time.perf_counter() - started) * 1000, 3)
        assert result['total'] == 1
        report['skillBefore'] = measure(lambda: case.http('/api/skill-inventory', {'q': 'needle-0399'}))
        report['skillAfter'] = measure(lambda: case.http('/api/v1/file-search', {**case.scope, 'q': 'needle-0399', 'kind': 'skill', 'limit': 1}))
        report['modelsAfter'] = measure(lambda: case.http('/api/v1/models'))
        report['backendVersion'] = case.http('/api/health')[1]['version']
        report['indexBytes'] = case.context.db_path.stat().st_size
        report['sourceBytes'] = sum(p.stat().st_size for p in case.skills.rglob('*') if p.is_file())
        with case.context._db() as db:
            report['indexColumns'] = [r[1] for r in db.execute('PRAGMA table_info(files)')]
        child = case.children[-1]
        child.terminate(); child.wait(timeout=3)
        case.start(legacy=True)
        report['modelsBefore'] = measure(lambda: case.http('/api/v1/models'))
        child = case.children[-1]
        child.terminate(); child.wait(timeout=3)
        case.start()
        if args.real_skill_root:
            case.grant(args.real_skill_root)
            result = case.mcp('agent_city_skill_search', {**case.scope, 'q': 'task-execution', 'limit': 1})
            assert not result['isError'], result
            item = result['structuredContent']['files'][0]
            query = {**case.scope, 'id': item['id'], 'revision': item['revision'], 'startLine': 1, 'endLine': 4, 'maxBytes': 1024}
            status, document, wire = case.http('/api/skill-inventory', query)
            assert status == 200, document
            answer = case.mcp('agent_city_read_skill', query)
            assert not answer['isError'], answer
            assert answer['structuredContent']['content'] == document['content']
            assert document['content'].startswith('---')
            expected = hashlib.sha256((args.real_skill_root / 'SKILL.md').read_bytes()).hexdigest()
            assert expected == document['revision']
            report['realSkill'] = {'id': item['id'], 'revision': expected, 'httpBytes': wire, 'http': 'PASS', 'stdioMcp': 'PASS',
                                   'openedThrough': 'existing /api/skill-inventory -> scoped SkillInventory.read(id)',
                                   'sourceRepresentation': case.root['representation']}
        report['sqliteJustification'] = 'metadata cache retained only if warm scoped search beats existing inventory scan in this measured workload'
        report['sqliteBeneficialInThisRun'] = report['skillAfter']['medianMs'] < report['skillBefore']['medianMs']
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(report, ensure_ascii=False))
    finally:
        case.tearDown()


if __name__ == '__main__':
    main()
