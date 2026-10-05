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
from agent_mcp import Bridge, NativeTaskError, invoke, parse


def digest(value): return hashlib.sha256(value.encode()).hexdigest()[:32]


def eligible(cwd, roots):
    try:
        path = Path(cwd).resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        return False
    for item in roots:
        try:
            root = Path(item).resolve(strict=True)
        except (OSError, RuntimeError, ValueError):
            # A stale configured root must not hide a later valid opt-in root.
            continue
        if path == root or root in path.parents:
            return True
    return False


DEFINITE_ERRORS = {
    'personal_task_required', 'task_version_conflict', 'task_already_completed',
    'task_archived', 'task_not_found', 'task_forbidden', 'task_rejected',
    'operation_rejected', 'personal_scope_required', 'agent_request_rejected',
    'unknown_task_binding', 'run_sequence_or_identity_conflict',
    'new_run_id_required', 'usage_decreased', 'task_binding_mismatch',
    'operation_payload_conflict',
}


def _native_code(error):
    value = getattr(error, 'value', None)
    if isinstance(value, dict):
        code = value.get('code') or value.get('error')
    else:
        code = None
    return code if isinstance(code, str) else ''


def _definite_error(error):
    """Return a bounded code for a permanent native rejection, if known."""
    if not isinstance(error, NativeTaskError):
        return None
    code = _native_code(error)
    return code if code in DEFINITE_ERRORS else None


def _error_record(error, code):
    # Native error objects can contain task text. Keep only a stable category.
    return {'code': code, 'kind': 'definite_native_rejection'}


def _message_state(message):
    return message.get('state', 'pending')


def _blocked(state):
    return bool(state.get('blocked'))


def _mark_definite(db, ident, message, state, error, code):
    message['state'] = 'conflict' if code == 'task_version_conflict' else 'rejected'
    message['error'] = _error_record(error, code)
    state['blocked'] = True
    state['blockedBy'] = message['operationId']
    state['blockedCode'] = code
    state.pop('resumeOperationId', None)
    db.execute('INSERT INTO outbox_history(queue_id,value) VALUES(?,?)', (ident, json.dumps(message)))
    db.execute('UPDATE outbox SET value=? WHERE id=?', (json.dumps(message), ident))
    db.execute('DELETE FROM outbox WHERE id=?', (ident,))
    db.execute('UPDATE sessions SET value=? WHERE id=?', (json.dumps(state), message['session']))


def _row_for_operation(db, operation_id):
    if not isinstance(operation_id, str) or not 1 <= len(operation_id) <= 100:
        raise ValueError('operationId required')
    for table in ('outbox_history', 'outbox'):
        rows = db.execute(f'SELECT id,value FROM {table} ORDER BY id').fetchall() if table == 'outbox' else db.execute('SELECT queue_id,value FROM outbox_history ORDER BY queue_id').fetchall()
        for ident, raw in rows:
            message = json.loads(raw)
            if message.get('operationId') == operation_id:
                return ident, message
    raise ValueError('operationId not found')


def _new_attempt(message, *, action=None, payload=None):
    """Clone a rejected attempt, retaining its immutable history."""
    retry = dict(message)
    retry['operationId'] = str(uuid.uuid4())
    retry['state'] = 'pending'
    retry.pop('error', None)
    retry['native'] = None
    retry['action'] = action or message['action']
    retry['payload'] = payload
    return retry


def _insert_attempt(db, message):
    queue_id = _next_queue_id(db)
    db.execute('INSERT INTO outbox(id,value) VALUES(?,?)', (queue_id, json.dumps(message)))


def _next_queue_id(db):
    active = db.execute('SELECT COALESCE(MAX(id),0) FROM outbox').fetchone()[0]
    history = db.execute('SELECT COALESCE(MAX(queue_id),0) FROM outbox_history').fetchone()[0]
    return max(active, history) + 1


def _ensure_tables(db):
    db.execute('CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY,value TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS outbox(id INTEGER PRIMARY KEY,value TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS outbox_history(queue_id INTEGER PRIMARY KEY,value TEXT NOT NULL)')


def _migrate_history(db):
    """Move rejected rows written by the pre-history adapter out of capacity."""
    for ident, raw in db.execute('SELECT id,value FROM outbox ORDER BY id').fetchall():
        message = json.loads(raw)
        if _message_state(message) in ('conflict', 'rejected'):
            db.execute('INSERT OR IGNORE INTO outbox_history(queue_id,value) VALUES(?,?)', (ident, raw))
            db.execute('DELETE FROM outbox WHERE id=?', (ident,))


def _outbox_path(config):
    path = Path(config['outbox'])
    if path.is_symlink():
        raise ValueError('unsafe outbox')
    return path


def outbox_status(config, operation_id=None):
    path = _outbox_path(config)
    if not path.exists():
        return []
    with closing(sqlite3.connect(path, timeout=2)) as db:
        _ensure_tables(db)
        rows = [(ident, raw) for ident, raw in db.execute('SELECT queue_id,value FROM outbox_history ORDER BY queue_id').fetchall()]
        rows += [(ident, raw) for ident, raw in db.execute('SELECT id,value FROM outbox ORDER BY id').fetchall()]
    rows.sort(key=lambda row: row[0])
    result = []
    for ident, raw in rows:
        message = json.loads(raw)
        if operation_id is not None and message.get('operationId') != operation_id:
            continue
        report = message.get('report') or {}
        result.append({
            'id': ident, 'operationId': message.get('operationId'),
            'state': _message_state(message), 'action': message.get('action'),
            'session': message.get('session'), 'sequence': report.get('sequence'),
            'status': report.get('status'), 'error': message.get('error'),
        })
    return result


def retry_attempt(config, operation_id):
    """Explicitly copy a definite rejection into a new, pending operation."""
    path = _outbox_path(config)
    with closing(sqlite3.connect(path, timeout=2)) as db:
        _ensure_tables(db)
        db.execute('BEGIN IMMEDIATE')
        _migrate_history(db)
        ident, message = _row_for_operation(db, operation_id)
        state = json.loads(db.execute('SELECT value FROM sessions WHERE id=?', (message['session'],)).fetchone()[0])
        if state.get('blockedBy') != operation_id or state.get('resumeOperationId'):
            raise ValueError('operation is not the current blocked rejection')
        if _message_state(message) not in ('conflict', 'rejected'):
            raise ValueError('operation is not a definite rejection')
        retry = _new_attempt(message, payload=message.get('payload'))
        if retry['payload'] is not None:
            retry['payload'] = dict(retry['payload'], operationId=retry['operationId'])
        _insert_attempt(db, retry)
        state['blocked'] = False; state['resumeOperationId'] = retry['operationId']
        state.pop('blockedBy', None); state.pop('blockedCode', None)
        db.execute('UPDATE sessions SET value=? WHERE id=?', (json.dumps(state), message['session']))
        db.commit()
    return retry['operationId']


def resolve_attempt(config, operation_id, bridges=None):
    """Resolve a rejection explicitly, refreshing version or opting into a new binding."""
    path = _outbox_path(config)
    with closing(sqlite3.connect(path, timeout=2)) as db:
        _ensure_tables(db)
        db.execute('BEGIN IMMEDIATE')
        _migrate_history(db)
        ident, message = _row_for_operation(db, operation_id)
        code = (message.get('error') or {}).get('code')
        state = json.loads(db.execute('SELECT value FROM sessions WHERE id=?', (message['session'],)).fetchone()[0])
        if state.get('blockedBy') != operation_id or state.get('resumeOperationId'):
            raise ValueError('operation is not the current blocked rejection')
        if _message_state(message) not in ('conflict', 'rejected') or not code:
            raise ValueError('operation is not a resolvable rejection')
        session = message['session']
        payload = message.get('payload')
        action = message.get('action')
        if code == 'task_version_conflict':
            task_id = payload.get('taskId') if isinstance(payload, dict) else state.get('taskId')
            if not task_id:
                raise ValueError('task version conflict has no task')
            if bridges is None:
                raise ValueError('native bridge required to refresh version')
            cicada = bridges[0]
            task = invoke('cicada', cicada, 'cicada_read_task', {'taskId': task_id})
            if not isinstance(task, dict) or not isinstance(task.get('version'), int):
                raise ValueError('native task version unavailable')
            payload = dict(payload or {}, taskId=task_id, expectedVersion=task['version'],
                           operationId=message['operationId'], report=message['report'])
        else:
            raise ValueError('restore_original_task_required')
        retry = _new_attempt(message, action=action, payload=payload)
        if retry['payload'] is not None:
            retry['payload'] = dict(retry['payload'], operationId=retry['operationId'])
        _insert_attempt(db, retry)
        state['blocked'] = False; state['resumeOperationId'] = retry['operationId']
        state.pop('blockedBy', None); state.pop('blockedCode', None)
        db.execute('UPDATE sessions SET value=? WHERE id=?', (json.dumps(state), session))
        db.commit()
    return retry['operationId']


def enqueue(db, client, event):
    """Capture only observed identifiers/status. Never read prompt or transcript."""
    session = event.get('session_id')
    if not isinstance(session, str) or not 1 <= len(session) <= 100: raise ValueError('session identity unavailable')
    key = client + '-' + digest(session)
    prior = db.execute('SELECT value FROM sessions WHERE id=?', (key,)).fetchone()
    state = json.loads(prior[0]) if prior else {'taskId':None,'runId':None,'sequence':0,'model':None}
    name = event['hook_event_name']
    if name == 'UserPromptSubmit':
        if _blocked(state) or state.get('resumeOperationId'):
            # A definite native rejection requires explicit resolution before
            # this session may start another run.
            return
        turn = event.get('turn_id') if client == 'codex' else None
        run = client + '-' + digest(session + ':' + (turn if isinstance(turn,str) and turn else str(uuid.uuid4())))
        if run == state['runId']: return
        model = event.get('model') if client == 'codex' else None
        if not isinstance(model,str) or not model.strip() or len(model)>200 or any(ord(c)<32 for c in model): model = None
        state.update(runId=run,sequence=0,model=model,acknowledged=False,terminal=False,lastActivityAt=0)
        db.execute('INSERT INTO sessions(id,value) VALUES(?,?) ON CONFLICT(id) DO UPDATE SET value=excluded.value',(key,json.dumps(state)))
        return
    elif name == 'PreToolUse':
        if not state.get('runId') or state.get('terminal') or _blocked(state) or state.get('resumeOperationId'): return
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
        if not state.get('runId') or _blocked(state) or state.get('resumeOperationId'): return
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
    message = {'session':key,'operationId':str(uuid.uuid4()),'action':action,'report':report,
               'payload':None,'native':None,'state':'pending'}
    if db.execute('SELECT count(*) FROM outbox').fetchone()[0]>=500: raise ValueError('transport capacity')
    _insert_attempt(db, message)
    db.execute('INSERT INTO sessions(id,value) VALUES(?,?) ON CONFLICT(id) DO UPDATE SET value=excluded.value', (key,json.dumps(state)))


def drain(db, cicada, city):
    # Exclusive transaction serializes lifecycle callbacks and retries the exact
    # saved native request after a lost response. Application writes stay native.
    skipped_sessions = set()
    first_retryable = None
    while True:
        pending = None
        for candidate in db.execute('SELECT id,value FROM outbox ORDER BY id').fetchall():
            candidate_id, candidate_raw = candidate
            candidate_message = json.loads(candidate_raw)
            if _message_state(candidate_message) != 'pending':
                continue
            candidate_state_row = db.execute('SELECT value FROM sessions WHERE id=?', (candidate_message['session'],)).fetchone()
            if candidate_state_row is None:
                continue
            candidate_state = json.loads(candidate_state_row[0])
            if _blocked(candidate_state) or candidate_message['session'] in skipped_sessions:
                continue
            resume = candidate_state.get('resumeOperationId')
            if resume and candidate_message.get('operationId') != resume:
                continue
            pending = candidate
            break
        if pending is None:
            if first_retryable is not None:
                raise first_retryable
            return
        ident, raw = pending; message = json.loads(raw)
        state = json.loads(db.execute('SELECT value FROM sessions WHERE id=?',(message['session'],)).fetchone()[0])
        try:
            if message['payload'] is None:
                task = invoke('cicada',cicada,'cicada_read_task',{'taskId':state.get('taskId')}) if state.get('taskId') else None
                body = {'operationId':message['operationId'],'taskId':state.get('taskId'),'expectedVersion':task['version'] if task else None,'report':message['report']}
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
            if state.get('resumeOperationId') == message.get('operationId'):
                state.pop('resumeOperationId', None)
                db.execute('UPDATE sessions SET value=? WHERE id=?',(json.dumps(state),message['session']))
            db.execute('DELETE FROM outbox WHERE id=?',(ident,)); db.commit(); db.execute('BEGIN IMMEDIATE')
        except Exception as error:
            code = _definite_error(error)
            if code is None:
                # Unknown outcomes and timeouts keep the exact pending payload
                # and operationId for replay. They remain retryable, while
                # independent sessions can still drain in this invocation.
                if first_retryable is None:
                    first_retryable = error
                skipped_sessions.add(message['session'])
                db.rollback(); db.execute('BEGIN IMMEDIATE')
                continue
            _mark_definite(db, ident, message, state, error, code)
            db.commit(); db.execute('BEGIN IMMEDIATE')


def process(config, client, event, bridges=None):
    if not eligible(event.get('cwd',''),config['personalRoots']): return
    path = _outbox_path(config); path.parent.mkdir(parents=True,exist_ok=True)
    with closing(sqlite3.connect(path,timeout=2)) as db:
        _ensure_tables(db)
        db.commit(); db.execute('BEGIN IMMEDIATE'); _migrate_history(db); db.commit(); db.execute('BEGIN IMMEDIATE'); enqueue(db,client,event); db.commit(); db.execute('BEGIN IMMEDIATE')
        if not db.execute('SELECT 1 FROM outbox LIMIT 1').fetchone(): return
        cicada, city = bridges or (Bridge('cicada',config['cicadaProfile'],config['client']),Bridge('agent-city',config['cityProfile'],config['client']))
        drain(db,cicada,city)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--config',required=True)
    parser.add_argument('--agent',choices=['codex','claude'])
    parser.add_argument('command',nargs='?',choices=['status','retry','resolve'])
    parser.add_argument('operation_id',nargs='?')
    args=parser.parse_args()
    if args.command:
        try:
            config=json.loads(Path(args.config).read_text(encoding='utf-8-sig'))
            if args.command == 'status':
                print(json.dumps({'outbox':outbox_status(config,args.operation_id)},ensure_ascii=False))
                return 0
            if not args.operation_id:
                raise ValueError('operationId required')
            if args.command == 'retry':
                operation_id = retry_attempt(config,args.operation_id)
            else:
                # Version refresh reads the current native task; constructing a
                # bridge is deferred until an explicit resolve command.
                bridges=(Bridge('cicada',config['cicadaProfile'],config['client']), None)
                operation_id = resolve_attempt(config,args.operation_id,bridges)
            print(json.dumps({'operationId':operation_id,'state':'pending'},ensure_ascii=False))
            return 0
        except Exception as error:
            print(json.dumps({'error':str(error)[:120]},ensure_ascii=False))
            return 2
    if not args.agent:
        parser.error('--agent is required for hook events')
    try:
        config=json.loads(Path(args.config).read_text(encoding='utf-8-sig'))
        raw=sys.stdin.buffer.read(65537)
        if len(raw)>65536: raise ValueError('event too large')
        event=parse(raw)
        process(config,args.agent,event)
    except Exception:
        # Reporting cannot block authorized AI work. The exact outbox item stays
        # pending for the next callback; this is not evidence of task completion.
        print(json.dumps({'systemMessage':'Cicada / Agent City: регистрация ожидает подключения; работа ИИ продолжается.'},ensure_ascii=False))
    return 0


if __name__=='__main__': sys.exit(main())
