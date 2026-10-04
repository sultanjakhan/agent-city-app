"""Metadata-only lifecycle adapter. SQLite here is a transport outbox, not a task authority.

Personal directory opt-in only. No prompt/transcript/tool arguments are stored.
An ended AI turn does not complete its Cicada task or launch a human timer.
"""
import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import time
import uuid
from agent_mcp import Bridge, invoke, parse


def digest(value): return hashlib.sha256(value.encode()).hexdigest()[:32]


def eligible(cwd, roots):
    path = Path(cwd).resolve(strict=True)
    return any(path == (root := Path(item).resolve(strict=True)) or root in path.parents for item in roots)


def enqueue(db, client, event):
    """Capture only observed identifiers/status. Never read prompt or transcript."""
    session = event.get('session_id')
    if not isinstance(session, str) or not 1 <= len(session) <= 100: raise ValueError('session identity unavailable')
    key = client + '-' + digest(session)
    prior = db.execute('SELECT value FROM sessions WHERE id=?', (key,)).fetchone()
    state = json.loads(prior[0]) if prior else {'taskId':None,'runId':None,'sequence':0,'model':None}
    name = event['hook_event_name']
    if name == 'UserPromptSubmit':
        turn = event.get('turn_id') if client == 'codex' else None
        run = client + '-' + digest(session + ':' + (turn if isinstance(turn,str) and turn else str(uuid.uuid4())))
        if run == state['runId']: return
        model = event.get('model') if client == 'codex' else None
        if not isinstance(model,str) or not model.strip() or len(model)>200 or any(ord(c)<32 for c in model): model = None
        state.update(runId=run,sequence=0,model=model,acknowledged=False,terminal=False,lastActivityAt=0)
        db.execute('INSERT INTO sessions(id,value) VALUES(?,?) ON CONFLICT(id) DO UPDATE SET value=excluded.value',(key,json.dumps(state)))
        return
    elif name == 'PreToolUse':
        if not state['runId'] or state.get('terminal'): return
        now = time.time()
        if state.get('acknowledged'):
            # Refresh only on observed tool activity, at most once per minute.
            # Retry a pending snapshot before appending another one during an outage.
            if any(json.loads(row[0])['session']==key for row in db.execute('SELECT value FROM outbox')): return
            elapsed = now - state.get('lastActivityAt',0)
            if 0 <= elapsed < 60: return
            state['sequence'] += 1; action = 'report'
        else:
            state.update(sequence=1,acknowledged=True); action = 'begin'
        state['lastActivityAt'] = now; status = 'running'
    elif name in ('Stop','Interrupt','StopFailure'):
        if not state['runId']: return
        status = {'Stop':'done','Interrupt':'cancelled','StopFailure':'error'}[name]
        if state.get('terminal'): return
        if not state.get('acknowledged'):
            if name!='Stop': return
            # A completed text-only turn proves actual work. Queue its initial
            # acknowledged snapshot followed by the terminal snapshot together.
            enqueue(db,client,dict(event,hook_event_name='PreToolUse'))
            state=json.loads(db.execute('SELECT value FROM sessions WHERE id=?',(key,)).fetchone()[0])
        state['sequence'] += 1; state['terminal'] = True; action = 'report'
    else: return
    if action == 'begin': state['terminal'] = False
    report = dict(runId=state['runId'],sequence=state['sequence'],taskKey=None,agent=client,model=state['model'],
                  provider=None,stage=None,status=status,skillIds=[],mcpCalls=None,inputTokens=None,outputTokens=None)
    message = {'session':key,'operationId':str(uuid.uuid4()),'action':action,'report':report,'payload':None,'native':None}
    if db.execute('SELECT count(*) FROM outbox').fetchone()[0]>=500: raise ValueError('transport capacity')
    db.execute('INSERT INTO outbox(value) VALUES(?)', (json.dumps(message),))
    db.execute('INSERT INTO sessions(id,value) VALUES(?,?) ON CONFLICT(id) DO UPDATE SET value=excluded.value', (key,json.dumps(state)))


def drain(db, cicada, city):
    # Exclusive transaction serializes lifecycle callbacks and retries the exact
    # saved native request after a lost response. Application writes stay native.
    while (pending := db.execute('SELECT id,value FROM outbox ORDER BY id LIMIT 1').fetchone()):
        ident, raw = pending; message = json.loads(raw)
        state = json.loads(db.execute('SELECT value FROM sessions WHERE id=?',(message['session'],)).fetchone()[0])
        if message['payload'] is None:
            task = invoke('cicada',cicada,'cicada_read_task',{'taskId':state['taskId']}) if state['taskId'] else None
            body = {'operationId':message['operationId'],'taskId':state['taskId'],'expectedVersion':task['version'] if task else None,'report':message['report']}
            if message['action']=='begin': body.update(title=message['report']['agent'].capitalize()+' · чат '+message['session'][-8:],content='',projects=['ai'])
            if message['action']=='report' and task is None: raise ValueError('native task unavailable')
            message['payload'] = body
            db.execute('UPDATE outbox SET value=? WHERE id=?',(json.dumps(message),ident)); db.commit(); db.execute('BEGIN IMMEDIATE')
        if message['native'] is None:
            name = 'cicada_begin_ai_work' if message['action']=='begin' else 'cicada_report_ai_work'
            message['native'] = invoke('cicada',cicada,name,message['payload'])
            state['taskId'] = message['native']['task']['id']
            db.execute('UPDATE sessions SET value=? WHERE id=?',(json.dumps(state),message['session']))
            db.execute('UPDATE outbox SET value=? WHERE id=?',(json.dumps(message),ident)); db.commit(); db.execute('BEGIN IMMEDIATE')
        invoke('agent-city',city,'agent_city_report_run',{'binding':message['native']['binding'],'report':message['native']['report']})
        db.execute('DELETE FROM outbox WHERE id=?',(ident,)); db.commit(); db.execute('BEGIN IMMEDIATE')


def process(config, client, event, bridges=None):
    if not eligible(event.get('cwd',''),config['personalRoots']): return
    path = Path(config['outbox']); path.parent.mkdir(parents=True,exist_ok=True)
    if path.is_symlink(): raise ValueError('unsafe outbox')
    with closing(sqlite3.connect(path,timeout=2)) as db:
        db.execute('CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY,value TEXT NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS outbox(id INTEGER PRIMARY KEY,value TEXT NOT NULL)')
        db.commit(); db.execute('BEGIN IMMEDIATE'); enqueue(db,client,event); db.commit(); db.execute('BEGIN IMMEDIATE')
        if not db.execute('SELECT 1 FROM outbox LIMIT 1').fetchone(): return
        cicada, city = bridges or (Bridge('cicada',config['cicadaProfile'],config['client']),Bridge('agent-city',config['cityProfile'],config['client']))
        drain(db,cicada,city)


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--config',required=True); parser.add_argument('--agent',choices=['codex','claude'],required=True)
    args=parser.parse_args()
    try:
        raw=sys.stdin.buffer.read(65537)
        if len(raw)>65536: raise ValueError('event too large')
        event=parse(raw); config=json.loads(Path(args.config).read_text(encoding='utf-8-sig'))
        process(config,args.agent,event)
    except Exception:
        # Reporting cannot block authorized AI work. The exact outbox item stays
        # pending for the next callback; this is not evidence of task completion.
        print(json.dumps({'systemMessage':'Cicada / Agent City: регистрация ожидает подключения; работа ИИ продолжается.'},ensure_ascii=False))
    return 0


if __name__=='__main__': sys.exit(main())
