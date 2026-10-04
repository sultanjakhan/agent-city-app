import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.request import Request, build_opener, ProxyHandler
from urllib.error import HTTPError
from owner_session import OwnerSessions
import server

class OwnerSessionHttpTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name);skills=root/'skills';skills.mkdir();(root/'repos').mkdir()
        self.store=server.Store(root/'panel',skills_root=skills,codex_home=root/'codex',repo_roots=[root/'repos'],local_only=True,executable=False)
        self.http=server.Server(('127.0.0.1',0),self.store);self.worker=threading.Thread(target=self.http.serve_forever,daemon=True);self.worker.start();self.addCleanup(self.stop)
        self.base='http://127.0.0.1:'+str(self.http.server_port);self.owner=self.http.owner_host+':'+str(self.http.server_port)
    def stop(self):self.http.shutdown();self.http.server_close();self.worker.join(3)
    def call(self,path,body=None,headers=None):
        req=Request(self.base+path,data=json.dumps(body).encode() if body is not None else None,headers=headers or {})
        try:
            with build_opener(ProxyHandler({})).open(req,timeout=3) as response:return response.status,json.load(response),response.headers
        except HTTPError as response:return response.code,json.load(response),response.headers
    def bootstrap(self,capability=None):
        capability=capability or self.http.owner_sessions.issue_bootstrap()
        status,body,headers=self.call('/api/owner-bootstrap',{'capability':capability},{'Host':self.owner,'Origin':'http://'+self.owner,'X-Agent-City':'1','Content-Type':'application/json'})
        self.assertEqual(200,status);self.assertEqual({'authorized':True},body)
        self.assertIn('HttpOnly',headers['Set-Cookie']);self.assertIn('SameSite=Strict',headers['Set-Cookie']);self.assertNotIn('Max-Age',headers['Set-Cookie']);self.assertNotIn('Expires',headers['Set-Cookie'])
        return headers['Set-Cookie'].split(';',1)[0],capability
    def test_foreign_local_client_cannot_read_token_or_mutate(self):
        status,health,_=self.call('/api/health');self.assertEqual(200,status);self.assertEqual({'appId','version','localOnly'},set(health))
        for path in ('/api/state','/api/dashboard','/api/v1/context','/api/codex-controls','/api/data-sources/export','/api/cloud','/api/owner-session'):
            self.assertEqual(401,self.call(path)[0]);self.assertEqual(401,self.call(path,headers={'Host':self.owner})[0])
        for path in ('/api/favorite','/api/codex-controls/connect','/api/runs/report','/api/cloud/sync'):
            status,body,_=self.call(path,{}, {'Host':self.owner,'X-Agent-City':'1','X-Agent-City-Token':self.store.csrf_token});self.assertEqual(401,status);self.assertTrue(self.store.csrf_token not in json.dumps(body),'unexpected bootstrap token exposure')
        self.assertFalse((Path(self.temp.name)/'codex'/'AGENTS.md').exists())
    def test_real_bootstrap_one_use_no_origin_bypass_and_session_read(self):
        cap=self.http.owner_sessions.issue_bootstrap()
        headers={'Host':self.owner,'X-Agent-City':'1'}
        self.assertEqual(403,self.call('/api/owner-bootstrap',{'capability':cap},headers)[0])
        self.assertEqual(403,self.call('/api/owner-bootstrap',{'capability':cap},{**headers,'Origin':'https://foreign.invalid'})[0])
        cookie,_=self.bootstrap(cap)
        self.assertEqual(401,self.call('/api/owner-bootstrap',{'capability':cap},{**headers,'Origin':'http://'+self.owner})[0])
        self.assertEqual(200,self.call('/api/state',headers={'Host':self.owner,'Cookie':cookie})[0])
        self.assertEqual(401,self.call('/api/state',headers={'Cookie':cookie})[0])
        self.assertEqual(403,self.call('/api/state',headers={'Host':self.owner,'Cookie':cookie,'Origin':'https://foreign.invalid'})[0])
    def test_expired_or_malformed_capabilities_and_new_epoch_reject_old_cookie(self):
        cap=self.http.owner_sessions.issue_bootstrap()
        with patch('owner_session.time.monotonic',return_value=10**15):
            self.assertIsNone(self.http.owner_sessions.exchange(cap))
        self.assertIsNone(self.http.owner_sessions.exchange([]));self.assertIsNone(self.http.owner_sessions.exchange('invalid'))
        cookie,_=self.bootstrap();self.http.owner_sessions=OwnerSessions()
        self.assertEqual(401,self.call('/api/state',headers={'Host':self.owner,'Cookie':cookie})[0])
        new_cookie,_=self.bootstrap();self.assertEqual(200,self.call('/api/state',headers={'Host':self.owner,'Cookie':new_cookie})[0])
