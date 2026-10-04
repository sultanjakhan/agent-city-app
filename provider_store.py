"""Local provider references. Websites never become arbitrary credential endpoints."""
from __future__ import annotations

import copy
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import tempfile
import threading
from urllib.parse import urlsplit, urlunsplit


class ProviderError(ValueError):
    pass


class ProviderConflict(ProviderError):
    pass


def website(value):
    if not isinstance(value, str) or len(value) > 1000:
        raise ProviderError('Укажи HTTPS-ссылку на сайт провайдера.')
    try:
        parts = urlsplit(value.strip())
        host = (parts.hostname or '').encode('idna').decode('ascii').lower()
        port = parts.port
    except (ValueError, UnicodeError):
        raise ProviderError('Некорректная ссылка на сайт.') from None
    if parts.scheme != 'https' or not host or parts.username or parts.password or parts.query or parts.fragment or port not in (None, 443):
        raise ProviderError('Нужна HTTPS-ссылка без токенов, параметров и нестандартного порта.')
    try:
        ipaddress.ip_address(host)
        raise ProviderError('Укажи доменное имя публичного сайта, не IP-адрес.')
    except ValueError as exc:
        if isinstance(exc, ProviderError):
            raise
    if '.' not in host or host.endswith(('.local', '.localhost', '.internal')) or any(not part or not all(c.isalnum() or c == '-' for c in part) for part in host.split('.')):
        raise ProviderError('Укажи доменное имя публичного сайта.')
    return urlunsplit(('https', host, parts.path.rstrip('/') or '', '', ''))


class ProviderStore:
    def __init__(self, directory, adapters):
        self.path = Path(directory) / 'providers.json'
        self.adapters = adapters
        self.lock = threading.RLock()
        self.hosts = {}
        for key, source in adapters.items():
            for field in ('docs', 'keyUrl', 'url'):
                host = urlsplit(source.get(field, '')).hostname
                if host:
                    self.hosts[host.lower().removeprefix('www.')] = key
        self.hosts.update({'kilo.ai': 'kilo', 'cline.bot': 'cline', 'groq.com': 'groq',
                           'cerebras.ai': 'cerebras', 'mistral.ai': 'mistral',
                           'siliconflow.cn': 'siliconflow', 'huggingface.co': 'huggingface', 'openai.com': 'openai', 'chatgpt.com': 'openai', 'anthropic.com': 'anthropic', 'claude.ai': 'anthropic'})

    def _read(self):
        if not self.path.exists():
            return {'schemaVersion': 1, 'hidden': [], 'references': []}
        if self.path.is_symlink() or self.path.stat().st_size > 256 * 1024:
            raise ProviderError('Не удалось прочитать хранилище провайдеров. Файл сохранён.')
        try:
            value = json.loads(self.path.read_text(encoding='utf-8'))
            if value.get('schemaVersion') != 1 or not isinstance(value.get('hidden'), list) or not isinstance(value.get('references'), list):
                raise ValueError()
            if any(key not in self.adapters for key in value['hidden']):
                raise ValueError()
            for row in value['references']:
                if row.get('website') != website(row.get('website')) or row.get('id') != self.reference_id(row['website']) or not isinstance(row.get('name'), str):
                    raise ValueError()
            settings=value.get('settings', {})
            if not isinstance(settings, dict):raise ValueError()
            for ident, option in settings.items():
                if not isinstance(option,dict) or set(option)!={'accessMode','catalogPolicy'} or option['accessMode'] not in ('api','subscription') or option['catalogPolicy'] not in ('confirmed-free-only','all'):raise ValueError()
            return value
        except (ValueError, TypeError, AttributeError, KeyError):
            raise ProviderError('Не удалось прочитать хранилище провайдеров. Файл сохранён.') from None

    @staticmethod
    def reference_id(url):
        host = urlsplit(url).hostname.removeprefix('www.')
        return 'website-' + hashlib.sha256(host.encode()).hexdigest()[:20]

    @staticmethod
    def revision(value):
        return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    def sources(self):
        value = self._read()
        sources = {key: {**source, 'supported': True, 'website': 'https://' + urlsplit(source['docs']).netloc} for key, source in self.adapters.items() if key not in value['hidden']}
        sources.update({row['id']: {**row, 'supported': False, 'url': None, 'docs': row['website'], 'keyRequired': False,
                                   'terms': 'Сайт сохранён. API-адаптер не поддерживается; токен и модели не импортируются.'} for row in value['references']})
        for ident,source in sources.items():source.update({'accessMode':'api','catalogPolicy':'confirmed-free-only',**value.get('settings',{}).get(ident,{})})
        return sources

    def snapshot(self):
        value = self._read()
        return {**copy.deepcopy(value), 'revision': self.revision(value)}

    def resolve(self, value):
        url = website(value)
        key = self.hosts.get(urlsplit(url).hostname.removeprefix('www.'))
        source = self.adapters.get(key, {})
        return {'id': key, 'supported': bool(key), 'keySupported': bool(key) and source.get('keyEntrySupported', key != 'kilo'), 'website': url}

    def change(self, action, payload, revision):
        with self.lock:
            value = self._read()
            if revision != self.revision(value):
                raise ProviderConflict('Список изменился. Обнови список и повтори действие.')
            result = copy.deepcopy(value)
            if action == 'add':
                url = website(payload.get('website'))
                host = urlsplit(url).hostname.removeprefix('www.')
                key = self.hosts.get(host)
                if key:
                    if key not in result['hidden']:
                        raise ProviderError('Этот провайдер уже добавлен.')
                    result['hidden'].remove(key)
                else:
                    key = self.reference_id(url)
                    if any(row['id'] == key for row in result['references']):
                        raise ProviderError('Этот провайдер уже добавлен.')
                    if len(result['references']) >= 200:
                        raise ProviderError('Достигнут лимит: 200 сайтов.')
                    result['references'].append({'id': key, 'name': host, 'website': url})
            elif action == 'settings':
                key=payload.get('id')
                if key not in self.sources():raise ProviderError('Provider is not active.')
                option=payload.get('settings')
                if not isinstance(option,dict) or set(option)!={'accessMode','catalogPolicy'} or option['accessMode'] not in ('api','subscription') or option['catalogPolicy'] not in ('confirmed-free-only','all'):raise ProviderError('Invalid provider settings.')
                result.setdefault('settings',{})[key]=copy.deepcopy(option)
            elif action == 'remove':
                key = payload.get('id')
                if key in self.adapters and key not in result['hidden']:
                    result['hidden'].append(key)
                    result['hidden'].sort()
                elif any(row['id'] == key for row in result['references']):
                    result['references'] = [row for row in result['references'] if row['id'] != key]
                else:
                    raise ProviderError('Провайдер уже удалён или не найден.')
            else:
                raise ProviderError('Неизвестное действие.')
            if self.path.is_symlink():
                raise ProviderError('Хранилище не должно быть ссылкой.')
            fd, temporary = tempfile.mkstemp(dir=self.path.parent, prefix='.providers-', suffix='.tmp')
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                    json.dump(result, stream, ensure_ascii=False)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self.path)
            finally:
                Path(temporary).unlink(missing_ok=True)
            return self.snapshot()
