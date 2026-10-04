import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import desktop_bridge
import owner_broker


def frame(action="bootstrap", **updates):
    value={"version":1,"id":1,"action":action,"draftsClosed":False}
    value.update(updates)
    return json.dumps(value).encode()+b"\n"


class DesktopBridgeTests(unittest.TestCase):
    def test_strict_private_frames_and_draft_consent(self):
        self.assertEqual(desktop_bridge.request(frame(),1)["action"],"bootstrap")
        for data in (frame(id=True), frame(version=True), frame(id=2), frame(action="delegate"),
                     frame("stop"), frame("restart"), frame(extra="synthetic"),
                     frame(draftsClosed=1), b'{"version":1,"version":1}\n', b"x"*16385, frame().rstrip()):
            with self.subTest(size=len(data)), self.assertRaises(ValueError):desktop_bridge.request(data,1)
        self.assertEqual(desktop_bridge.request(frame("stop",draftsClosed=True),1)["action"],"stop")

    def test_frozen_command_dispatch_preserves_owned_script_allowlist(self):
        with patch.object(sys,"frozen",True,create=True):
            self.assertEqual(owner_broker.script_command(Path("synthetic"),"server.py",["--port","0"]),
                             [sys.executable,"--internal-script","server.py","--port","0"])
            with self.assertRaises(ValueError):owner_broker.script_command(Path("synthetic"),"other.py",[])
        self.assertEqual(owner_broker.script_command(Path("synthetic"),"city.py",[]),[sys.executable,str(Path("synthetic")/"city.py")])

    def test_ephemeral_port_readiness_is_owned_and_validated(self):
        class Child:
            pid=123
            stdin=io.BytesIO()
            def poll(self):return None
            def terminate(self):pass
            def wait(self,timeout=None):return 0
        for port,accepted in ((50123,True),(True,False),(0,False),(65536,False)):
            broker=owner_broker.OwnerBroker(Path("synthetic"),0,{},lambda *args:None)
            def spawn(command,deadline,**options):
                env=options["env"]
                ready={"version":1,"kind":"ready","instance":env["AGENT_CITY_OWNER_INSTANCE"],"pid":123,
                       "appRoot":str(broker.root),"ownerHost":env["AGENT_CITY_OWNER_HOST"],"port":port,"localOnly":True}
                child=Child();child.stdin=io.BytesIO();child.stdout=io.BytesIO(json.dumps(ready).encode()+b"\n")
                self.assertIn("--local-only",command);self.assertIn("--no-refresh",command)
                return child
            with patch.object(owner_broker,"spawn_owned",spawn):
                if accepted:self.assertEqual(broker.start()["port"],port)
                else:
                    with self.assertRaises(owner_broker.BrokerError):broker.start()

    def test_normal_runtime_is_explicit_and_cannot_accept_local_only_readiness(self):
        class Child:
            pid=123
            def poll(self):return None
            def terminate(self):pass
            def wait(self,timeout=None):return 0
        for ready_local,accepted in ((False,True),(True,False),(0,False)):
            broker=owner_broker.OwnerBroker(Path("synthetic"),0,{},lambda *args:None,local_only=False)
            def spawn(command,deadline,**options):
                self.assertNotIn("--local-only",command)
                self.assertIn("--no-refresh",command)
                self.assertIn("--owner-control-stdin",command)
                env=options["env"]
                ready={"version":1,"kind":"ready","instance":env["AGENT_CITY_OWNER_INSTANCE"],"pid":123,
                       "appRoot":str(broker.root),"ownerHost":env["AGENT_CITY_OWNER_HOST"],"port":50123,"localOnly":ready_local}
                child=Child();child.stdin=io.BytesIO();child.stdout=io.BytesIO(json.dumps(ready).encode()+b"\n")
                return child
            with patch.object(owner_broker,"spawn_owned",spawn):
                if accepted:self.assertIs(broker.start()["localOnly"],False)
                else:
                    with self.assertRaises(owner_broker.BrokerError):broker.start()
        with self.assertRaises(ValueError):owner_broker.OwnerBroker(Path("synthetic"),0,{},None,local_only=0)

    def test_adapter_eof_revokes_and_uses_explicit_config_without_discovery(self):
        observed={};sent=[]
        class Broker:
            child=None
            owner_host="synthetic.localhost"
            def __init__(self,root,port,environment,callback,**options):observed.update(environment=environment,port=port,options=options)
            def start(self):return {"port":50123}
            def _retire_channel(self):observed["retired"]=True
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/"storage.json";p.write_text('{"schemaVersion":1}')
            with patch.object(desktop_bridge,"OwnerBroker",Broker), patch.object(desktop_bridge,"send",sent.append), \
                 patch.object(sys,"stdin",SimpleNamespace(buffer=io.BytesIO())), \
                 patch.dict(desktop_bridge.os.environ,{"AGENT_CITY_PANEL_DATA":"synthetic-override","CODEX_HOME":"synthetic-override"}):
                self.assertEqual(desktop_bridge.main(["--config",str(p)]),0)
            self.assertEqual(observed["port"],0)
            self.assertTrue(observed["options"]["local_only"])
            self.assertEqual(observed["environment"]["AGENT_CITY_CONFIG"],str(p.resolve()))
            self.assertNotIn("AGENT_CITY_PANEL_DATA",observed["environment"])
            self.assertNotIn("CODEX_HOME",observed["environment"])
            self.assertTrue(observed["retired"])
            self.assertEqual(sent[0]["kind"],"ready")

    def test_normal_status_and_explicit_stop_are_private_and_readonly_until_stop(self):
        observed={};sent=[]
        class Child:
            def poll(self):return None
        class Broker:
            owner_host="synthetic.localhost"
            def __init__(self,root,port,environment,callback,**options):
                observed["localOnly"]=options["local_only"];self.child=Child()
            def start(self):return {"port":50123}
            def stop(self,**options):observed["stopped"]=options["drafts_closed"];self.child=None
            def _retire_channel(self):observed["retired"]=True
        incoming=frame("status")+frame("stop",id=2,draftsClosed=True)
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/"storage.json";p.write_text('{"schemaVersion":1}')
            with patch.object(desktop_bridge,"OwnerBroker",Broker), patch.object(desktop_bridge,"send",sent.append), \
                 patch.object(sys,"stdin",SimpleNamespace(buffer=io.BytesIO(incoming))):
                self.assertEqual(desktop_bridge.main(["--config",str(p),"--runtime","normal"]),0)
        self.assertIs(observed["localOnly"],False)
        self.assertEqual(sent[1]["result"],{"backendAlive":True,"localOnly":False})
        self.assertTrue(observed["stopped"]);self.assertTrue(observed["retired"])

    def test_status_reports_dead_server_while_bridge_keeps_handling_private_commands(self):
        sent=[]
        class Child:
            calls=0
            def poll(self):self.calls+=1;return None if self.calls==1 else 7
        class Broker:
            owner_host="synthetic.localhost"
            def __init__(self,*args,**options):self.child=Child()
            def start(self):return {"port":50123}
            def stop(self,**options):self.child=None
            def _retire_channel(self):pass
        incoming=frame("status")+frame("status",id=2)+frame("stop",id=3,draftsClosed=True)
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/"storage.json";p.write_text('{"schemaVersion":1}')
            with patch.object(desktop_bridge,"OwnerBroker",Broker), patch.object(desktop_bridge,"send",sent.append), \
                 patch.object(sys,"stdin",SimpleNamespace(buffer=io.BytesIO(incoming))):
                self.assertEqual(desktop_bridge.main(["--config",str(p)]),0)
        self.assertTrue(sent[1]["result"]["backendAlive"])
        self.assertFalse(sent[2]["result"]["backendAlive"])
        self.assertTrue(sent[3]["result"]["stopped"])


if __name__=="__main__":unittest.main()
