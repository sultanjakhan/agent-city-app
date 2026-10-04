import unittest
import subprocess
import secrets
import time
from owner_transport import ControlDeadline
from pathlib import Path
from unittest.mock import patch,Mock
from app_window import WindowInfo
from owner_browser import OwnedBrowser
from owner_controller import OwnerController
from owner_broker import BrokerError

class OwnedBrowserIdentityTests(unittest.TestCase):
    def test_focus_and_close_require_retained_child_pid_and_exact_owner_title(self):
        browser=OwnedBrowser('synthetic-edge.exe');child=Mock();child.pid=100;child.poll.return_value=None
        browser.process=child;browser.title='Agent City [synthetic-owned-origin]';browser.titles={browser.title}
        own=WindowInfo(1,browser.title,'msedge.exe','Chrome_WidgetWin_1',100)
        foreign=WindowInfo(2,browser.title,'msedge.exe','Chrome_WidgetWin_1',200)
        try:
            with patch('owner_browser.app_window.enumerate_windows',return_value=[foreign]),patch('owner_browser.app_window.focus_window') as focused:
                self.assertFalse(browser.focus());focused.assert_not_called()
            with patch('owner_browser.app_window.enumerate_windows',return_value=[foreign,own]),patch('owner_browser.app_window.focus_window',return_value=True) as focused:
                self.assertTrue(browser.focus());focused.assert_called_once_with(own,title=browser.title)
            with self.assertRaises(BrokerError):browser.close()
            with patch('owner_browser.app_window.enumerate_windows',side_effect=[[foreign,own],[]]),patch('owner_browser.app_window.close_window') as closed:
                browser.close(drafts_closed=True);closed.assert_called_once_with(own,title='Agent City [synthetic-owned-origin]',owned_pid=100)
        finally:
            browser.process=None
            if browser.profile:browser.close(drafts_closed=True)
    def test_exited_browser_is_not_reused_and_controller_requires_explicit_restart(self):
        browser=OwnedBrowser('synthetic-edge.exe');child=Mock();child.pid=100;child.poll.return_value=0;browser.process=child
        broker=Mock();controller=OwnerController(broker,browser)
        try:
            controller.open_or_recover();self.assertIsNone(browser.process);broker.recover_browser.assert_called_once_with()
            with self.assertRaises(BrokerError):controller.restart()
            broker.restart.assert_not_called();controller.restart(drafts_closed=True);broker.restart.assert_called_once_with(drafts_closed=True)
        finally:browser.close(drafts_closed=True)


class BrowserCleanupBoundaryTests(unittest.TestCase):
    def test_live_secondary_handle_keeps_profile_and_is_not_forced_without_consent(self):
        browser=OwnedBrowser('synthetic-edge.exe');child=Mock();child.pid=200;child.poll.return_value=None
        child.wait.side_effect=subprocess.TimeoutExpired('owned browser',1)
        browser.children=[child];profile=Path(browser.profile.name)
        try:
            with patch('owner_browser.app_window.enumerate_windows',return_value=[]):
                with self.assertRaises(BrokerError):browser.close(drafts_closed=True)
            self.assertTrue(profile.exists());child.terminate.assert_not_called()
        finally:browser.children=[];browser.close(drafts_closed=True)
    def test_background_termination_requires_explicit_consent_and_no_visible_owned_window(self):
        browser=OwnedBrowser('synthetic-edge.exe');child=Mock();child.pid=200;child.poll.return_value=None
        child.wait.side_effect=[subprocess.TimeoutExpired('owned browser',1),0]
        browser.children=[child]
        try:
            with patch('owner_browser.app_window.enumerate_windows',return_value=[]):browser.close(drafts_closed=True,allow_background_stop=True)
            child.terminate.assert_called_once();self.assertTrue(browser.background_stopped);self.assertIsNone(browser.profile)
        finally:
            browser.children=[]
            if browser.profile:browser.close(drafts_closed=True)


class NativeOpenBudgetTests(unittest.TestCase):
    def test_explicit_small_deadline_overrides_conservative_cold_start_budget(self):
        browser=OwnedBrowser('synthetic-edge.exe');child=Mock();child.pid=321;child.poll.return_value=None
        url='http://agent-city-'+('a'*32)+'.localhost:12345/#owner-bootstrap='+secrets.token_urlsafe(32)
        started=time.monotonic()
        try:
            with patch('owner_browser.spawn_owned',return_value=child),patch('owner_browser.app_window.enumerate_windows',return_value=[]):
                with self.assertRaises(ControlDeadline):browser.open(url,'synthetic-instance',deadline=started+.05)
            self.assertLess(time.monotonic()-started,.3)
        finally:
            browser.process=None;browser.children=[]
            with patch('owner_browser.app_window.enumerate_windows',return_value=[]):browser.close(drafts_closed=True)
