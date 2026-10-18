"""Owner-requested data relocation, applied only after native writers drain.

The original directories are never removed. Config stays at its stable location;
external repositories and agent installations are references, not copy targets.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import uuid
from storage_config import APP_ROOT, load_storage
from cloud_sync import atomic_bytes

class MigrationError(ValueError): pass

def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def safe_path(value):
    if not isinstance(value, (str, os.PathLike)) or not str(value).strip():
        raise MigrationError('Укажи абсолютный путь к локальной папке.')
    path=Path(value).expanduser()
    if not path.is_absolute() or str(path).startswith(('\\\\','//')):
        raise MigrationError('Нужна абсолютная локальная папка.')
    path=Path(os.path.abspath(path))
    for item in [*reversed(path.parents),path]:
        if item.exists() or item.is_symlink():
            mode=item.lstat()
            if stat.S_ISLNK(mode.st_mode) or getattr(mode,'st_file_attributes',0)&0x400:
                raise MigrationError('Папки со ссылками и перенаправлениями не поддерживаются.')
    if path.exists() and not path.is_dir():raise MigrationError('Выбери папку, а не файл.')
    # Windows 8.3 spellings must not bypass overlap checks or profile identity.
    return path.resolve(strict=False)

def configured_pointer():
    value=os.environ.get('AGENT_CITY_CONFIG')
    if not value:raise MigrationError('Выбор папки доступен в установленном приложении с явным профилем.')
    pointer=Path(value).absolute()
    safe_path(pointer.parent)
    if pointer.is_symlink() or not pointer.is_file() or getattr(pointer.lstat(),'st_file_attributes',0)&0x400 or pointer.stat().st_size>65536:
        raise MigrationError('Указатель хранилища недоступен.')
    return pointer

def job_path(pointer):return pointer.with_name(pointer.name+'.migration.json')

def plan(destination):
    storage=load_storage();target=safe_path(destination)
    code=Path(sys.executable).resolve().parent.parent if getattr(sys,'frozen',False) else APP_ROOT
    sources=[storage.root,storage.panel,storage.skills,storage.credentials]
    for source in [code,*sources]:
        source=safe_path(source)
        if target==source or source in target.parents or target in source.parents:
            raise MigrationError('Новая папка не должна пересекаться с программой или текущими данными.')
    if target.exists() and any(target.iterdir()):raise MigrationError('Выбери пустую папку: существующие данные не объединяются автоматически.')
    # Keep all legacy data, including inactive files, in one preserved subtree.
    # Active external stores have their own names and cannot overwrite that tree.
    mappings=[(storage.root,target/'library')]
    fields={}
    for name,source,label in [('panelDirectory',storage.panel,'panel'),('skillsDirectory',storage.skills,'skills'),('credentialsDirectory',storage.credentials,'credentials')]:
        if source==storage.root or storage.root in source.parents:
            mapped=target/'library'/source.relative_to(storage.root)
        else:
            mapped=target/label
            for prior,dest in mappings:
                if source==prior or prior in source.parents:
                    mapped=dest/source.relative_to(prior);break
            else:mappings.append((source,mapped))
        fields[name]=str(mapped)
    return storage,target,mappings,fields

def status():
    try:
        pointer=configured_pointer();storage=load_storage()
        result={'supported':True,'revision':digest(pointer),'root':str(storage.root),'panel':str(storage.panel),'skills':str(storage.skills),'state':'idle'}
        job=job_path(pointer)
        if job.exists():
            if job.is_symlink() or job.stat().st_size>65536:raise MigrationError('Запрос переноса недоступен.')
            value=json.loads(job.read_text('utf-8'))
            result.update(state=value.get('state','error'),destination=value.get('destination'),error=value.get('error'))
        return result
    except (OSError,ValueError):return {'supported':False,'state':'unavailable'}

def prepare(destination,revision):
    pointer=configured_pointer()
    if revision!=digest(pointer):raise MigrationError('Настройки изменились. Обнови страницу перед переносом.')
    _,target,_,_=plan(destination)
    value={'version':1,'state':'prepared','configRevision':revision,'destination':str(target)}
    atomic_bytes(job_path(pointer),json.dumps(value,ensure_ascii=False).encode())
    return status()

def cancel(revision):
    pointer=configured_pointer()
    if revision!=digest(pointer):raise MigrationError('Настройки изменились. Обнови страницу.')
    job=job_path(pointer)
    if job.is_symlink():raise MigrationError('Запрос переноса недоступен.')
    job.unlink(missing_ok=True)
    return status()

def inventory(root, writer_lock=None):
    safe_path(root)
    if not root.exists():return []
    files=[];pending=[root]
    while pending:
        parent=pending.pop()
        for path in parent.iterdir():
            if path.name=='.storage-writer.lock' and (parent==root or path==writer_lock):continue
            attr=path.lstat()
            if stat.S_ISLNK(attr.st_mode) or getattr(attr,'st_file_attributes',0)&0x400:
                raise MigrationError('В данных обнаружена ссылка: перенос отменён.')
            if path.name=='.git':raise MigrationError('В папке данных есть Git-репозиторий. Выбери отдельное хранилище приложения.')
            if path.is_dir():pending.append(path)
            elif path.is_file():files.append((path,path.relative_to(root),digest(path),attr.st_size))
            else:raise MigrationError('В данных обнаружен неподдерживаемый тип файла.')
            if len(files)>50000:raise MigrationError('Слишком много файлов для переноса за одно закрытие.')
    return sorted(files,key=lambda row:row[1].as_posix())

def copy_file(source,target):
    target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    safe_path(target.parent)
    with source.open('rb') as incoming,target.open('xb') as outgoing:
        shutil.copyfileobj(incoming,outgoing);outgoing.flush();os.fsync(outgoing.fileno())

def apply_prepared(config):
    from storage_lock import StorageLock
    os.environ['AGENT_CITY_CONFIG']=str(Path(config).absolute())
    for key in ('AGENT_CITY_DATA_ROOT','AGENT_CITY_PANEL_DATA','AGENT_CITY_SKILLS_ROOT','AGENT_CITY_CREDENTIALS_DIR','CODEX_HOME'):
        os.environ.pop(key,None)
    storage=load_storage()
    try:
        with StorageLock(storage.panel): return _apply_prepared(config)
    except OSError:
        return {'state':'busy','sourcePreserved':True}


def _apply_prepared(config):
    """Native host calls this only after its owned backend has exited."""
    os.environ['AGENT_CITY_CONFIG']=str(Path(config).absolute())
    for key in ('AGENT_CITY_DATA_ROOT','AGENT_CITY_PANEL_DATA','AGENT_CITY_SKILLS_ROOT','AGENT_CITY_CREDENTIALS_DIR','CODEX_HOME'):
        os.environ.pop(key,None)
    pointer=configured_pointer();job=job_path(pointer)
    if not job.exists():return {'state':'idle'}
    value=json.loads(job.read_text('utf-8'))
    if value.get('state')!='prepared':return {'state':value.get('state','error')}
    stage=None;switched=False;pointer_raw=None
    try:
        if set(value)!={'version','state','configRevision','destination'} or value['version']!=1 or digest(pointer)!=value['configRevision']:
            raise MigrationError('Профиль изменился после подготовки переноса. Исходные данные сохранены.')
        storage,target,mappings,fields=plan(value['destination'])
        pointer_raw=pointer.read_bytes();config_value=json.loads(pointer_raw.decode('utf-8-sig'))
        # The panel is usually nested under root; its held lock is runtime state,
        # not user data, and Windows refuses to read/copy the locked byte.
        writer_lock=storage.panel/'.storage-writer.lock'
        inventories=[(source,dest,inventory(source,writer_lock)) for source,dest in mappings]
        total=sum(item[3] for _,_,rows in inventories for item in rows)
        if total>2*1024**3:raise MigrationError('Хранилище больше 2 ГиБ: нужен отдельный перенос.')
        ancestor=target.parent
        while not ancestor.exists():ancestor=ancestor.parent
        if shutil.disk_usage(ancestor).free<total+10*1024**2:raise MigrationError('Недостаточно свободного места. Исходные данные сохранены.')
        target.parent.mkdir(parents=True,exist_ok=True)
        safe_path(target.parent)
        stage=target.with_name('.agent-city-migration-'+uuid.uuid4().hex)
        stage.mkdir(mode=0o700)
        for _,destination,rows in inventories:
            base=stage/destination.relative_to(target);base.mkdir(parents=True,exist_ok=True,mode=0o700)
            for source,relative,expected,_ in rows:
                copy=base/relative;copy_file(source,copy)
                if digest(copy)!=expected or digest(source)!=expected:raise MigrationError('Данные изменились во время копирования. Исходная папка остаётся активной.')
        for source,_,rows in inventories:
            if [(str(p),h,n) for p,_,h,n in inventory(source,writer_lock)]!=[(str(p),h,n) for p,_,h,n in rows]:
                raise MigrationError('Запись в исходные данные ещё продолжается. Перенос отменён.')
        if pointer.read_bytes()!=pointer_raw:raise MigrationError('Указатель изменился во время переноса.')
        safe_path(target)
        if target.exists():target.rmdir() # Empty only; never recursive deletion.
        stage.rename(target);stage=None
        if sys.platform=='darwin' and (storage.panel/'cloud/profile.json').exists():
            # Preserve the old Keychain item and create only an identical alias.
            # If Keychain is unavailable, the original pointer stays active.
            from keyring.backends.macOS import Keyring
            keyring=Keyring()
            old_id=hashlib.sha256(str((storage.panel/'cloud').resolve()).encode()).hexdigest()
            new_id=hashlib.sha256(str((Path(fields['panelDirectory'])/'cloud').resolve()).encode()).hexdigest()
            raw=keyring.get_password('Agent City Cloud',old_id)
            if not raw: raise MigrationError('Облачный ключ недоступен.')
            from cloud_sync import profile_check
            profile_check(json.loads(raw))
            prior=keyring.get_password('Agent City Cloud',new_id)
            if prior is not None and prior!=raw: raise MigrationError('Целевой ключ отличается.')
            if prior is None:keyring.set_password('Agent City Cloud',new_id,raw)
            if keyring.get_password('Agent City Cloud',new_id)!=raw:raise MigrationError('Ключ не сохранён.')
        config_value.update(dataRoot=str(target),**fields)
        def remap(reference):
            path=Path(reference)
            for source,destination in mappings:
                if path==source or source in path.parents:return str(destination/path.relative_to(source))
            return str(path)
        config_value['codexHome']=remap(storage.codex_home)
        config_value['repositoryRoots']=[remap(path) for path in storage.repository_roots]
        config_value['skillInventoryRoots']=[{'origin':origin,'path':remap(path)} for origin,path in storage.skill_inventory_roots]
        config_value['cicadaSources']=[{**source,'path':remap(source['path'])} for source in storage.cicada_candidates]
        backup=pointer.with_name(pointer.name+'.before-migration-'+uuid.uuid4().hex)
        with backup.open('xb') as stream:stream.write(pointer_raw);stream.flush();os.fsync(stream.fileno())
        atomic_bytes(pointer,json.dumps(config_value,ensure_ascii=False,indent=2).encode())
        switched=True
        value.update(state='complete',filesVerified=sum(len(rows) for _,_,rows in inventories),sourcePreserved=True)
        atomic_bytes(job,json.dumps(value,ensure_ascii=False).encode())
        return {'state':'complete','filesVerified':value['filesVerified'],'sourcePreserved':True}
    except (OSError,ValueError):
        if switched and pointer_raw is not None:
            atomic_bytes(pointer,pointer_raw)
        # Retain partial private staging as recovery material; do not delete data.
        value.update(state='error',error='Перенос не завершён. Исходная папка сохранена; проверь место, доступ и отсутствие записи.')
        if stage is not None:value['recoveryDirectory']=str(stage)
        atomic_bytes(job,json.dumps(value,ensure_ascii=False).encode())
        return {'state':'error','sourcePreserved':True}
