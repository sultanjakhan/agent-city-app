import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app_window
import launch


class LaunchTests(unittest.TestCase):
    def test_log_keeps_previous_startup_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / "server.log").write_text("previous failure\n", encoding="utf-8")
            with launch.open_server_log(directory) as log:
                log.write("next start\n")
            self.assertEqual((directory / "server.log").read_text(encoding="utf-8"), "previous failure\nnext start\n")

    def test_large_log_rotates_once_before_appending(self):
        with tempfile.TemporaryDirectory() as tmp, patch("launch.LOG_ROTATE_BYTES", 10):
            directory = Path(tmp)
            (directory / "server.log.1").write_text("older log", encoding="utf-8")
            (directory / "server.log").write_text("latest failure\n", encoding="utf-8")
            with launch.open_server_log(directory) as log:
                log.write("new start\n")
            self.assertEqual((directory / "server.log.1").read_text(encoding="utf-8"), "latest failure\n")
            self.assertEqual((directory / "server.log").read_text(encoding="utf-8"), "new start\n")

    def test_probe_distinguishes_agent_city_foreign_and_offline(self):
        class Response:
            def __init__(self, payload): self.payload = payload
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def read(self, _): return json.dumps(self.payload).encode()
        with patch("launch.urlopen", return_value=Response({"appId": launch.APP_ID})):
            self.assertEqual(launch.probe_server("http://127.0.0.1:1"), "running")
        with patch("launch.urlopen", return_value=Response({"appId": "foreign"})):
            self.assertEqual(launch.probe_server("http://127.0.0.1:1"), "occupied")
        with patch("launch.urlopen", side_effect=OSError("offline")):
            self.assertEqual(launch.probe_server("http://127.0.0.1:1"), "offline")
        with patch("launch.urlopen", return_value=Response("<html>foreign</html>")):
            self.assertEqual(launch.probe_server("http://127.0.0.1:1"), "occupied")

    def test_reuses_exact_window_and_closes_only_duplicates(self):
        first = app_window.WindowInfo(1, app_window.WINDOW_TITLE, "msedge.exe", "Chrome_WidgetWin_1", 10)
        second = app_window.WindowInfo(2, app_window.WINDOW_TITLE, "msedge.exe", "Chrome_WidgetWin_1", 11)
        foreign = app_window.WindowInfo(3, app_window.WINDOW_TITLE, "msedge.exe", "Chrome_WidgetWin_2", 12)
        browser_tab = app_window.WindowInfo(4, "New Tab", "msedge.exe", "Chrome_WidgetWin_1", 13)
        self.assertFalse(app_window.is_exact_window(foreign))
        self.assertFalse(app_window.is_exact_window(browser_tab))
        with patch("app_window.focus_window") as focus, patch("app_window.close_window") as close:
            result = app_window.focus_existing(windows=[foreign, browser_tab, first, second])
        self.assertEqual(result, first)
        focus.assert_called_once_with(first)
        close.assert_called_once_with(second)

    def test_open_app_does_not_spawn_when_exact_window_exists(self):
        existing = app_window.WindowInfo(1, app_window.WINDOW_TITLE, "msedge.exe", "Chrome_WidgetWin_1", 10)
        with patch("launch.focus_existing", return_value=existing), patch("launch.subprocess.Popen") as popen:
            self.assertIs(launch.open_app("http://127.0.0.1:47831"), existing)
        popen.assert_not_called()

    def test_english_window_is_reused_and_unrelated_titles_are_rejected(self):
        english = app_window.WindowInfo(8, 'Agent City — models', 'msedge.exe', 'Chrome_WidgetWin_1', 20)
        russian = app_window.WindowInfo(9, app_window.WINDOW_TITLE, 'msedge.exe', 'Chrome_WidgetWin_1', 21)
        foreign = app_window.WindowInfo(10, 'Agent City — models - Microsoft Edge', 'msedge.exe', 'Chrome_WidgetWin_1', 22)
        self.assertTrue(app_window.is_exact_window(english))
        self.assertFalse(app_window.is_exact_window(foreign))
        with patch('app_window.focus_window') as focus, patch('app_window.close_window') as close:
            self.assertEqual(app_window.focus_existing(windows=[english, russian, foreign]), english)
        focus.assert_called_once_with(english)
        close.assert_called_once_with(russian)

    def test_failed_owned_child_aborts_without_public_probe_or_window_reuse(self):
        from owner_broker import BrokerError
        with patch('launch.start_owned_broker',side_effect=BrokerError('owned child refused')),patch('launch.probe_server') as probe,patch('launch.focus_existing') as focus:
            self.assertEqual(launch.main(['--no-browser']),2)
        probe.assert_not_called();focus.assert_not_called()

    def test_slow_window_failure_returns_none_without_second_spawn(self):
        with patch("launch.sys.platform", "win32"), patch("launch.focus_existing", return_value=None), patch("launch.edge_path", return_value=Path("edge.exe")), patch("pathlib.Path.is_file", return_value=True), patch("launch.subprocess.Popen"), patch("launch.wait_for_window", return_value=None):
            self.assertIsNone(launch.open_app("http://127.0.0.1:47831"))


if __name__ == "__main__":
    unittest.main()
