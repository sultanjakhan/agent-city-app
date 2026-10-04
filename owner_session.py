"""Transient owner bootstrap. No disk, log, OS ACL or persistent credential writes."""
import hashlib
from http.cookies import SimpleCookie, CookieError
import re
import secrets
import threading
import time

CAPABILITY = re.compile(r'^[A-Za-z0-9_-]{43}$')

class OwnerSessions:
    def __init__(self, bootstrap=None, session_ttl=43200, idle_ttl=7200):
        self.lock = threading.Lock()
        self.bootstraps = {}
        self.sessions = {}
        self.grants = {}
        self.session_ttl, self.idle_ttl = session_ttl, idle_ttl
        if bootstrap is not None:
            self.add_bootstrap(bootstrap)

    @classmethod
    def from_environment(cls,environment,bootstrap=None):
        def policy(name,default,minimum,maximum):
            text=environment.get(name,str(default))
            if not isinstance(text,str) or not text.isascii() or not text.isdecimal():raise ValueError("invalid owner session TTL policy")
            value=int(text)
            if not minimum<=value<=maximum:raise ValueError("invalid owner session TTL policy")
            return value
        absolute=policy("AGENT_CITY_OWNER_SESSION_TTL_SECONDS",43200,3600,86400)
        idle=policy("AGENT_CITY_OWNER_SESSION_IDLE_SECONDS",7200,300,14400)
        if idle>absolute:raise ValueError("invalid owner session TTL policy")
        return cls(bootstrap,session_ttl=absolute,idle_ttl=idle)

    def add_bootstrap(self, capability):
        if not isinstance(capability, str) or not CAPABILITY.fullmatch(capability):
            raise ValueError('invalid owner bootstrap')
        with self.lock:
            self._prune()
            if len(self.bootstraps)>=256: raise ValueError('bootstrap limit')
            self.bootstraps[self.digest(capability)] = time.monotonic()+120

    def issue_bootstrap(self):
        capability = secrets.token_urlsafe(32)
        self.add_bootstrap(capability)
        return capability

    @staticmethod
    def digest(value):
        return hashlib.sha256(value.encode('ascii')).digest()

    def exchange(self, capability):
        if not isinstance(capability, str) or not CAPABILITY.fullmatch(capability): return None
        with self.lock:
            expiry = self.bootstraps.pop(self.digest(capability), 0)
            if expiry < time.monotonic(): return None
            session = secrets.token_urlsafe(32)
            self._prune()
            if len(self.sessions)>=64: return None
            now=time.monotonic()
            self.sessions[self.digest(session)] = {'issued':now,'expires':now+self.session_ttl,'lastUse':now}
            return session

    def authorized(self, header, cookie_name):
        try:
            cookies = SimpleCookie(); cookies.load(header or '')
            session = cookies[cookie_name].value if cookie_name in cookies else ''
        except CookieError: return False
        if not CAPABILITY.fullmatch(session): return False
        with self.lock:
            self._prune()
            record=self.sessions.get(self.digest(session))
            if record: record['lastUse']=time.monotonic()
            return record is not None

    def _prune(self):
        now=time.monotonic()
        self.bootstraps={k:v for k,v in self.bootstraps.items() if v>now}
        self.sessions={k:v for k,v in self.sessions.items() if v['expires']>now and now-v['lastUse']<self.idle_ttl}
        self.grants={k:v for k,v in self.grants.items() if v['expires']>now}

    def revoke_all(self):
        with self.lock:
            self.bootstraps.clear();self.sessions.clear();self.grants.clear()

    def revoke_session(self,header,cookie_name):
        try:
            cookies=SimpleCookie();cookies.load(header or '')
            value=cookies[cookie_name].value
        except (CookieError,KeyError):return False
        if not CAPABILITY.fullmatch(value):return False
        with self.lock:return self.sessions.pop(self.digest(value),None) is not None

    @staticmethod
    def body_digest(value):
        import json
        return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

    def issue_grant(self,method,path,body):
        from urllib.parse import urlsplit
        reads={'/api/v1/manifest','/api/v1/models','/api/v1/providers','/api/v1/skills','/api/v1/skill-inventory','/api/v1/projects','/api/v1/extensions','/api/v1/repositories','/api/v1/rules','/api/v1/context','/api/v1/directory','/api/dashboard','/api/task-sync'}
        writes={'/api/skill-activity','/api/runs/report','/api/agent/report','/api/task-sync/queue','/api/task-sync/exchange','/api/task-sync/resolve'}
        if not isinstance(path,str) or len(path)>2048 or any(ord(c)<32 for c in path):raise ValueError('invalid scope')
        parsed=urlsplit(path)
        if parsed.scheme or parsed.netloc or parsed.fragment or not ((method=='GET' and parsed.path in reads and body is None) or (method=='POST' and parsed.path in writes and isinstance(body,dict))):raise ValueError('unsupported scope')
        token=secrets.token_urlsafe(32)
        with self.lock:
            self._prune()
            if len(self.grants)>=128:raise ValueError('grant limit')
            self.grants[self.digest(token)]={'method':method,'path':path,'digest':self.body_digest(body),'expires':time.monotonic()+60}
        return token

    def grant_authorized(self,token,method,path,body=None,consume=False):
        if not isinstance(token,str) or not CAPABILITY.fullmatch(token):return False
        with self.lock:
            self._prune();key=self.digest(token);record=self.grants.get(key)
            if not record or record['method']!=method or record['path']!=path:return False
            if consume:
                if record['digest']!=self.body_digest(body):return False
                self.grants.pop(key)
            return True
