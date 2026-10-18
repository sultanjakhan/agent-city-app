import os
from pathlib import Path
import subprocess
import sys
import time
import unittest
from owner_transport import write_pipe,ControlDeadline
from owner_session import OwnerSessions

class OwnerTransportDeadlineTests(unittest.TestCase):
    def test_real_nonreading_owned_pipe_returns_by_shared_deadline(self):
        flags={'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {}
        child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(5)'],stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,bufsize=0,**flags)
        try:
            started=time.monotonic()
            with self.assertRaises(ControlDeadline):write_pipe(child.stdin,b'x'*1024*1024,started+.15)
            self.assertLess(time.monotonic()-started,.8)
            child.stdin.close()
        finally:
            if child.poll() is None:child.terminate()
            child.wait(timeout=3)
    def test_conservative_session_policy_is_configurable_and_invalid_fails_closed(self):
        auth=OwnerSessions.from_environment({})
        self.assertEqual((43200,7200),(auth.session_ttl,auth.idle_ttl))
        auth=OwnerSessions.from_environment({'AGENT_CITY_OWNER_SESSION_TTL_SECONDS':'3600','AGENT_CITY_OWNER_SESSION_IDLE_SECONDS':'300'})
        self.assertEqual((3600,300),(auth.session_ttl,auth.idle_ttl))
        for value in ('-1','0','nan','86401','1.5'):
            with self.assertRaises(ValueError):OwnerSessions.from_environment({'AGENT_CITY_OWNER_SESSION_TTL_SECONDS':value})
        with self.assertRaises(ValueError):OwnerSessions.from_environment({'AGENT_CITY_OWNER_SESSION_TTL_SECONDS':'3600','AGENT_CITY_OWNER_SESSION_IDLE_SECONDS':'7200'})

    @unittest.skipUnless(os.name=='nt','Windows kernel handoff metadata')
    def test_unrelated_live_synthetic_process_cannot_be_adopted_as_browser(self):
        from owner_process import retain_direct_child,NativeOwnershipError
        flags={'creationflags':subprocess.CREATE_NO_WINDOW}
        root=subprocess.Popen([sys.executable,'-c','pass'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,**flags);root.wait(timeout=3)
        foreign=subprocess.Popen([sys.executable,'-c','import time; time.sleep(5)'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,**flags)
        try:
            with self.assertRaises(NativeOwnershipError):retain_direct_child(root,foreign.pid)
            self.assertIsNone(foreign.poll())
        finally:foreign.terminate();foreign.wait(timeout=3)

class OwnedSpawnFailureTests(unittest.TestCase):
    def test_process_setup_failures_are_immediate_and_private(self):
        from contextlib import redirect_stderr
        from io import StringIO
        from unittest.mock import patch
        from owner_transport import spawn_owned
        for error in (ValueError, OSError, subprocess.SubprocessError):
            with self.subTest(error=error.__name__):
                stderr = StringIO()
                started = time.monotonic()
                with redirect_stderr(stderr), patch('subprocess.Popen', side_effect=error('synthetic-private-argument')):
                    with self.assertRaises(OSError) as failure:
                        spawn_owned(['synthetic'], started + 1)
                self.assertNotIsInstance(failure.exception, ControlDeadline)
                self.assertEqual(str(failure.exception), 'owned process creation failed')
                self.assertEqual(stderr.getvalue(), '')
                self.assertLess(time.monotonic() - started, .5)

    def test_real_invalid_argument_fails_without_creating_a_child(self):
        from owner_transport import spawn_owned
        with self.assertRaises(OSError) as failure:
            spawn_owned([sys.executable, 'synthetic\0private'], time.monotonic() + 1)
        self.assertNotIsInstance(failure.exception, ControlDeadline)
        self.assertEqual(str(failure.exception), 'owned process creation failed')

    def test_success_returns_the_exact_owned_child(self):
        from unittest.mock import patch
        from owner_transport import spawn_owned
        child = object()
        with patch('subprocess.Popen', return_value=child) as create:
            self.assertIs(spawn_owned(['synthetic'], time.monotonic() + 1, stdin=subprocess.PIPE), child)
        create.assert_called_once_with(['synthetic'], stdin=subprocess.PIPE)
