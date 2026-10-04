import contextlib
import io
import json
import os
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit
from urllib.request import Request,build_opener,ProxyHandler
import launch

class TrustedLauncherBootstrapTests(unittest.TestCase):
    def test_actual_default_launcher_owns_child_and_refuses_second_launcher(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);pointer=root/'connection.local.json'
            pointer.write_text(json.dumps({'schemaVersion':1,'dataRoot':str(root/'private'),'codexHome':str(root/'codex'),'repositoryRoots':[str(root/'repos')],'skillInventoryRoots':[]}),encoding='utf8')
            with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
            env=dict(os.environ)
            for key in list(env):
                if key.startswith('AGENT_CITY_') or key=='CODEX_HOME':env.pop(key)
            env.update(AGENT_CITY_CONFIG=str(pointer),HOME=str(root/'home'),USERPROFILE=str(root/'home'),PYTHONDONTWRITEBYTECODE='1')
            urls=[];seen=[]
            def run(controller,auto_open=False):
                seen.append(controller.broker.child.pid)
                try:
                    self.assertTrue(auto_open);controller.open_or_recover()
                    parsed=urlsplit(urls[-1]);capability=parsed.fragment.removeprefix('owner-bootstrap=')
                    request=Request('http://127.0.0.1:'+str(port)+'/api/owner-bootstrap',data=json.dumps({'capability':capability}).encode(),headers={'Host':parsed.netloc,'Origin':'http://'+parsed.netloc,'X-Agent-City':'1','Content-Type':'application/json'})
                    with build_opener(ProxyHandler({})).open(request,timeout=3) as response:self.assertEqual(200,response.status)
                    with contextlib.redirect_stderr(io.StringIO()):self.assertEqual(2,launch.main(['--port',str(port),'--no-browser']))
                    self.assertIsNone(controller.broker.child.poll())
                finally:controller.stop(drafts_closed=True)
            with patch.dict(os.environ,env,clear=True),patch('owner_browser.OwnedBrowser.open',side_effect=lambda url,instance,**_:urls.append(url)),patch('owner_controller.OwnerController.run',run),patch('launch.probe_server') as probe,patch('launch.focus_existing') as focus:
                self.assertEqual(0,launch.main(['--port',str(port)]))
            self.assertEqual(1,len(seen));probe.assert_not_called();focus.assert_not_called()
