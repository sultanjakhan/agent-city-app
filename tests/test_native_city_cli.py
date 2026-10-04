import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import city

class NativeCliTests(unittest.TestCase):
    def test_native_context_uses_current_account_client_without_ui_start(self):
        with tempfile.TemporaryDirectory() as root:
            root=Path(root)
            (root/'Agent City').mkdir();(root/'Programs/Agent City').mkdir(parents=True)
            pointer=root/'Agent City/connection.json';pointer.write_text('{}')
            host=root/'Programs/Agent City/AgentCity.exe';host.write_bytes(b'fixture')
            result=type('Response',(),{'returncode':0,'stdout':b'{"ok":true,"result":{"schemaVersion":1}}'})()
            with patch.dict(city.os.environ,{'LOCALAPPDATA':str(root),'AGENT_CITY_CONFIG':str(pointer)}),patch.object(city.subprocess,'run',return_value=result) as run:
                self.assertEqual(city.native_request('/api/v1/context?cwd=fixture'),{'schemaVersion':1})
                args=run.call_args.args[0]
                self.assertEqual(args,[str(host),'--agent-request-stdin',str(pointer)])
                frame=json.loads(run.call_args.kwargs['input'])
                self.assertEqual(frame,{'method':'GET','path':'/api/v1/context?cwd=fixture','body':None})
                self.assertEqual(run.call_args.kwargs['creationflags'],city.subprocess.CREATE_NO_WINDOW)

    def test_explicit_port_keeps_test_http_path(self):
        with patch.object(city.sys,'argv',['city.py','context','--cwd','fixture','--port','1111']),patch.object(city,'native_request') as native,patch.object(city,'build_opener',side_effect=city.URLError('offline')):
            with self.assertRaises(SystemExit):city.main()
            native.assert_not_called()
