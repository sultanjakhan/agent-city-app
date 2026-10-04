import contextlib
import io
import json
import os
from pathlib import Path
import socket
import tempfile
import time
import unittest
from unittest.mock import patch, Mock
from urllib.request import Request,build_opener,ProxyHandler
from urllib.error import HTTPError
import launch
from owner_session import OwnerSessions
from owner_broker import BrokerError, OwnerBroker
from test_run_store import report

class ScopedAuthorityTests(unittest.TestCase):
    def test_session_absolute_idle_revoke_and_map_caps(self):
        clock=[100.0]
        with patch('owner_session.time.monotonic',side_effect=lambda:clock[0]):
            auth=OwnerSessions(session_ttl=10,idle_ttl=4)
            cap=auth.issue_bootstrap();session=auth.exchange(cap);cookie='owner='+session
            self.assertTrue(auth.authorized(cookie,'owner'));clock[0]+=5
            self.assertFalse(auth.authorized(cookie,'owner'))
            cap=auth.issue_bootstrap();session=auth.exchange(cap);cookie='owner='+session
            for _ in range(4):clock[0]+=3;auth.authorized(cookie,'owner')
            self.assertFalse(auth.authorized(cookie,'owner'))
            cap=auth.issue_bootstrap();session=auth.exchange(cap);cookie='owner='+session
            self.assertTrue(auth.revoke_session(cookie,'owner'));self.assertFalse(auth.authorized(cookie,'owner'))
            for _ in range(256):auth.issue_bootstrap()
            with self.assertRaises(ValueError):auth.issue_bootstrap()
            clock[0]+=121;self.assertIsInstance(auth.issue_bootstrap(),str)
    def test_scoped_single_use_expiry_revoke_and_no_admin_scope(self):
        auth=OwnerSessions();body=report(skillIds=[])
        token=auth.issue_grant('POST','/api/runs/report',body)
        self.assertFalse(auth.grant_authorized(token,'POST','/api/codex-controls/connect',body,True))
        self.assertFalse(auth.grant_authorized(token,'GET','/api/runs/report',None,True))
        self.assertFalse(auth.grant_authorized(token,'POST','/api/runs/report',{**body,'sequence':2},True))
        self.assertTrue(auth.grant_authorized(token,'POST','/api/runs/report',body,True));self.assertFalse(auth.grant_authorized(token,'POST','/api/runs/report',body,True))
        for path in ('/api/state','/api/credential','/api/codex-controls/connect','/api/cloud/sync'):
            with self.assertRaises(ValueError):auth.issue_grant('POST',path,{})
        token=auth.issue_grant('GET','/api/dashboard',None)
        with patch('owner_session.time.monotonic',return_value=time.monotonic()+61):self.assertFalse(auth.grant_authorized(token,'GET','/api/dashboard',None,True))
        token=auth.issue_grant('GET','/api/dashboard',None);auth.revoke_all();self.assertFalse(auth.grant_authorized(token,'GET','/api/dashboard',None,True))

class OwnedLauncherEndToEndTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);pointer=self.root/'connection.local.json'
        pointer.write_text(json.dumps({'schemaVersion':1,'dataRoot':str(self.root/'private'),'codexHome':str(self.root/'codex'),'repositoryRoots':[str(self.root/'repos')],'skillInventoryRoots':[]}),encoding='utf8')
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));self.port=sock.getsockname()[1]
        env=dict(os.environ)
        for key in list(env):
            if key.startswith('AGENT_CITY_') or key=='CODEX_HOME':env.pop(key)
        env.update(AGENT_CITY_CONFIG=str(pointer),HOME=str(self.root/'home'),USERPROFILE=str(self.root/'home'),PYTHONDONTWRITEBYTECODE='1')
        self.urls=[];self.broker=launch.start_owned_broker(self.port,env,lambda url,instance:self.urls.append((url,instance)))
        self.addCleanup(self.cleanup)
    def cleanup(self):
        if self.broker.child:
            try:self.broker.stop(drafts_closed=True)
            except BrokerError:self.broker._terminate_own_child()
    def call(self,path,body=None,grant=None,cookie=None,host=None):
        owner=self.broker.owner_host+':'+str(self.port)
        headers={'Host':host or owner,'Origin':'http://'+(host or owner),'X-Agent-City':'1','Content-Type':'application/json'}
        if grant:headers['X-Agent-City-Grant']=grant
        if cookie:headers['Cookie']=cookie
        req=Request('http://127.0.0.1:'+str(self.port)+path,data=json.dumps(body).encode() if body is not None else None,headers=headers)
        try:
            with build_opener(ProxyHandler({})).open(req,timeout=3) as response:return response.status,json.load(response),response.headers
        except HTTPError as response:return response.code,json.load(response),response.headers
    def browser_cookie(self):
        self.broker.recover_browser();cap=self.urls[-1][0].split('#owner-bootstrap=',1)[1]
        status,_,headers=self.call('/api/owner-bootstrap',{'capability':cap});self.assertEqual(200,status)
        return headers['Set-Cookie'].split(';',1)[0]
    def test_real_launcher_private_ready_browser_recovery_scope_cli_and_revoke(self):
        self.assertEqual(401,self.call('/api/state')[0]);cookie=self.browser_cookie();self.assertEqual(200,self.call('/api/state',cookie=cookie)[0])
        read=self.broker.run_cli('GET','/api/dashboard');self.assertEqual([],read['runs'])
        body=report(skillIds=[],mcpCalls=None);written=self.broker.run_cli('POST','/api/runs/report',body);self.assertEqual(body['runId'],written['run']['runId'])
        token=self.broker.grant('GET','/api/dashboard');self.assertEqual(401,self.call('/api/state',grant=token)[0]);self.assertEqual(200,self.call('/api/dashboard',grant=token)[0]);self.assertEqual(401,self.call('/api/dashboard',grant=token)[0])
        token=self.broker.grant('POST','/api/runs/report',{**body,'sequence':2});self.assertEqual(401,self.call('/api/runs/report',{**body,'sequence':3},grant=token)[0]);self.assertEqual(200,self.call('/api/runs/report',{**body,'sequence':2},grant=token)[0])
        with self.assertRaises(BrokerError):self.broker.grant('POST','/api/codex-controls/connect',{})
        self.broker.rpc('revoke');self.assertEqual(401,self.call('/api/state',cookie=cookie)[0]);cookie=self.browser_cookie();self.assertEqual(200,self.call('/api/state',cookie=cookie)[0])
    def test_no_browser_start_response_loss_and_bad_scope_do_not_poison_controller(self):
        self.assertEqual([],self.urls)
        with self.assertRaises(ValueError):self.broker.grant('POST','/api/runs/report',{'inputTokens':float('nan')})
        with self.assertRaises(BrokerError):self.broker.grant('POST','/api/credential',{})
        stale=self.broker.rpc('bootstrap')['capability']
        self.broker.recover_browser();self.assertEqual(401,self.call('/api/owner-bootstrap',{'capability':stale})[0])
        fresh=self.urls[-1][0].split('#owner-bootstrap=',1)[1]
        status,_,headers=self.call('/api/owner-bootstrap',{'capability':fresh});self.assertEqual(200,status)
        lost=headers['Set-Cookie'].split(';',1)[0]  # Emulate consumed response being lost by the browser.
        cookie=self.browser_cookie();self.assertEqual(401,self.call('/api/state',cookie=lost)[0]);self.assertEqual(200,self.call('/api/state',cookie=cookie)[0])

    def test_explicit_owned_restart_preserves_runtime_and_rejects_old_epoch(self):
        cookie=self.browser_cookie();old_host=self.broker.owner_host+':'+str(self.port);old_pid=self.broker.child.pid;old_epoch=self.broker.epoch
        body=report(skillIds=[],mcpCalls=None);self.broker.run_cli('POST','/api/runs/report',body)
        before=(self.root/'private'/'panel'/'agent-runs.json').read_bytes()
        with self.assertRaises(BrokerError):self.broker.restart()
        self.assertEqual(old_pid,self.broker.child.pid)
        self.broker.restart(drafts_closed=True);self.assertNotEqual(old_epoch,self.broker.epoch)
        self.assertEqual(before,(self.root/'private'/'panel'/'agent-runs.json').read_bytes())
        self.assertEqual(403,self.call('/api/state',cookie=cookie,host=old_host)[0])
        cap=self.urls[-1][0].split('#owner-bootstrap=',1)[1];status,_,headers=self.call('/api/owner-bootstrap',{'capability':cap});self.assertEqual(200,status)
        self.assertEqual(200,self.call('/api/state',cookie=headers['Set-Cookie'].split(';',1)[0])[0])
    def test_second_launcher_refuses_occupied_port_and_preserves_existing_owned_child(self):
        old_pid=self.broker.child.pid
        with self.assertRaises(BrokerError):
            launch.start_owned_broker(self.port,self.broker.environment,lambda *_:None)
        self.assertEqual(old_pid,self.broker.child.pid)
        self.assertIsNone(self.broker.child.poll())
        self.assertEqual(200,self.call('/api/health')[0])
        self.assertEqual([],self.urls)

    def test_restart_fence_denies_writes_and_private_channel_loss_stops_only_child(self):
        token=self.broker.grant('POST','/api/runs/report',report(skillIds=[]))
        self.assertTrue(self.broker.rpc('restart-ready')['quiescent'])
        self.assertEqual(503,self.call('/api/runs/report',report(skillIds=[]),grant=token)[0])
        self.broker.rpc('resume');self.assertEqual(200,self.call('/api/runs/report',report(skillIds=[]),grant=token)[0])
        child=self.broker.child;child.stdin.close();child.wait(timeout=5);self.assertEqual(0,child.returncode)
        with self.assertRaises(BrokerError):self.broker.recover_browser()


class PrivateChannelFailureTests(unittest.TestCase):
    def test_timeout_retires_channel_without_killing_child_or_retrying(self):
        import queue
        broker=OwnerBroker(Path.cwd(),12345,{},lambda *_:None)
        child=Mock();child.poll.return_value=None;broker.child=child
        broker.responses=Mock();broker.responses.get.side_effect=queue.Empty
        with patch('owner_broker.write_pipe') as written:
            with self.assertRaises(BrokerError):broker.rpc('bootstrap')
        self.assertTrue(broker.channel_failed);child.stdin.close.assert_called_once()
        child.terminate.assert_not_called();child.kill.assert_not_called()
        with self.assertRaises(BrokerError):broker.rpc('bootstrap')
        self.assertEqual(1,written.call_count)
    def test_wrong_epoch_reply_retires_channel_without_consuming_later_replies(self):
        broker=OwnerBroker(Path.cwd(),12345,{},lambda *_:None)
        child=Mock();child.poll.return_value=None;broker.child=child
        broker.responses.put({'version':1,'id':'wrong-request','ok':True,'result':{}})
        with patch('owner_broker.write_pipe') as written:
            with self.assertRaises(BrokerError):broker.rpc('bootstrap')
        self.assertTrue(broker.channel_failed);child.stdin.close.assert_called_once()
        child.terminate.assert_not_called()
