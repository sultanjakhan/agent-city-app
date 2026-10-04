"""Declarative technical pipelines. No executor or credential operations."""
import copy
import hashlib
import json
import math
import re
import threading
from pathlib import Path
from rule_store import _atomic_json
from storage_config import external_directory

LIMITS = ('tokens', 'costUsd', 'timeSeconds', 'retries')
ID = re.compile(r'^[a-zA-Z0-9_-]{1,80}$')


def limits(value):
    if not isinstance(value, dict) or set(value) - set(LIMITS):
        raise ValueError('Invalid limits')
    for key, number in value.items():
        if isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number) or number < 0:
            raise ValueError('Limits must be finite nonnegative numbers')
        if key != 'costUsd' and not isinstance(number, int):
            raise ValueError('Token, time and retry limits must be integers')
    return value


def validate(value):
    p = copy.deepcopy(value)
    if not isinstance(p, dict) or set(p) != {'schemaVersion','id','name','projectId','limits','stages'} or p['schemaVersion'] != 1:
        raise ValueError('Invalid pipeline schema')
    if not isinstance(p['id'], str) or not ID.fullmatch(p['id']):
        raise ValueError('Invalid pipeline id')
    if not isinstance(p['name'], str) or not 1 <= len(p['name'].strip()) <= 200 or not isinstance(p['projectId'], str) or not ID.fullmatch(p['projectId']):
        raise ValueError('Name and project reference required')
    limits(p['limits'])
    if not isinstance(p['stages'], list) or not 1 <= len(p['stages']) <= 50:
        raise ValueError('One to fifty stages required')
    ids = set()
    for s in p['stages']:
        if not isinstance(s, dict) or set(s) != {'id','name','kind','modelRefs','skillRefs','limits','transitions'}:
            raise ValueError('Invalid stage schema')
        if not isinstance(s['id'], str) or not ID.fullmatch(s['id']) or s['id'] in ids:
            raise ValueError('Invalid or duplicate stage id')
        ids.add(s['id'])
        if not isinstance(s['name'], str) or not 1 <= len(s['name'].strip()) <= 200 or s['kind'] not in ('work','review'):
            raise ValueError('Invalid stage name or kind')
        for key in ('modelRefs','skillRefs'):
            if not isinstance(s[key], list) or len(s[key]) > 100 or any(not isinstance(x,str) or not 1 <= len(x) <= 300 for x in s[key]) or len(set(s[key])) != len(s[key]):
                raise ValueError('Invalid references')
        limits(s['limits'])
        if not isinstance(s['transitions'], list) or len(s['transitions']) > 20:
            raise ValueError('Invalid transitions')
        seen = set()
        for t in s['transitions']:
            if not isinstance(t, dict) or set(t) != {'when','target','action'} or t['when'] not in ('success','failure','limit','reviewRejected') or t['action'] not in ('next','stop','escalate'):
                raise ValueError('Invalid transition')
            if t['when'] in seen:
                raise ValueError('Ambiguous transition condition')
            seen.add(t['when'])
            if t['action'] != 'next' and t['target'] is not None:
                raise ValueError('Stop/escalation cannot select stage')
    for s in p['stages']:
        for t in s['transitions']:
            if t['action'] == 'next' and (not isinstance(t['target'], str) or t['target'] not in ids):
                raise ValueError('Unknown transition target')
    if not any(s['kind'] == 'review' for s in p['stages']):
        raise ValueError('A review stage is required')
    if len(json.dumps(p).encode()) > 128 * 1024:
        raise ValueError('Pipeline too large')
    return p


def preview(pipeline, policy=None, model_ids=(), skill_ids=()):
    p = validate(pipeline)
    conflicts, warnings = [], []
    if policy is None:
        policy_limits = {}
        warnings.append('Project policy unknown: preview cannot authorize execution.')
    else:
        if not isinstance(policy, dict) or set(policy) != {'schemaVersion','projectId','limits'} or policy['schemaVersion'] != 1 or policy['projectId'] != p['projectId']:
            raise ValueError('Invalid or mismatched project policy')
        policy_limits = limits(policy['limits'])
    def effective(child, parent, scope):
        for key, n in child.items():
            if key in parent and n > parent[key]:
                conflicts.append(f'{scope}.{key} exceeds upper bound')
        return {k: min(child[k], parent[k]) if k in child and k in parent else child.get(k, parent.get(k)) for k in LIMITS}
    pipeline_limits = effective(p['limits'], policy_limits, 'pipeline')
    effective_stages = {}
    for s in p['stages']:
        effective_stages[s['id']] = effective(s['limits'], {k:v for k,v in pipeline_limits.items() if v is not None}, s['id'])
        for field, known in (('modelRefs', model_ids), ('skillRefs', skill_ids)):
            for ref in s[field]:
                if ref not in known:
                    warnings.append(f'{s["id"]}: unresolved {field} {ref}')
    reachable = set()
    def visit(ident):
        if ident in reachable: return
        reachable.add(ident)
        for t in next(s for s in p['stages'] if s['id']==ident)['transitions']:
            if t['action']=='next': visit(t['target'])
    visit(p['stages'][0]['id'])
    if not any(s['kind']=='review' and s['id'] in reachable for s in p['stages']):
        conflicts.append('Review stage is unreachable from entry stage')
    for s in p['stages']:
        if s['id'] not in reachable: warnings.append(f'{s["id"]}: unreachable stage')
    warnings.append('Catalog references do not grant access. External execution and limit enforcement are not implemented.')
    return {'conflicts':conflicts,'warnings':warnings,'effectiveLimits':pipeline_limits,'stageLimits':effective_stages,
            'enforcement':{'configurationValidation':'supported','externalClient':'unknown', **{k:'advisory' for k in LIMITS}},'canRun':False}


class PipelineStore:
    def __init__(self, directory):
        self.path = external_directory(directory) / 'pipelines.json'
        self.lock = threading.RLock()
    def snapshot(self):
        with self.lock:
            value = json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else {'schemaVersion':1,'pipelines':[]}
            for p in value['pipelines']: validate(p)
            return {**value,'revision':hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()}
    def save(self, pipeline, revision):
        p = validate(pipeline)
        with self.lock:
            state = self.snapshot()
            if revision != state.pop('revision'): raise RuntimeError('Pipeline revision conflict; reload before saving')
            state['pipelines'] = [x for x in state['pipelines'] if x['id'] != p['id']] + [p]
            _atomic_json(self.path,state)
            return self.snapshot()
