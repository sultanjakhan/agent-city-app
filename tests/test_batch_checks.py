from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import server as server_module
from server import Store


def model(ident):
    return {"id": ident, "name": ident, "developer": "test", "chinese": False,
            "kind": "chat", "context": 4096, "tools": False, "vision": False, "priceVerified": True}


class BatchChecksTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.skills = Path(self.temp.name) / "skills"
        self.skills.mkdir()
        self.store = Store(Path(self.temp.name) / "data", skills_root=self.skills, executable=False)
        self.store.batch_stop.wait = lambda _seconds: False
        self.patches = [
            patch.object(server_module.access, "key_available", return_value=True),
            patch.object(server_module.credentials, "info", return_value={"available": True, "source": "synthetic", "removable": False, "canSave": False}),
            patch.object(server_module.credentials, "revision", return_value="synthetic-revision"),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        self.store.batch_stop.set()
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def _catalogs(self, providers, counts=1):
        self.store.state["catalogs"] = {provider: {"models": [model(f"{provider}-{index}") for index in range(counts)]}
                                         for provider in providers}
        self.store.state["checks"] = {}

    def _wait_done(self, timeout=2):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not self.store.batch.get("running"):
                return
            time.sleep(0.005)
        self.fail("batch did not finish")

    def test_selects_at_most_ten_distinct_model_ids(self):
        providers = ["openrouter", "kilo"]
        self._catalogs(providers, counts=7)
        with patch.object(server_module.access, "probe", side_effect=lambda provider, ident, _fetcher: {"provider": provider, "model": ident, "status": "ok", "reply": "ok", "finishReason": "stop", "sent": True}):
            self.store.check_pending()
            self._wait_done()
        self.assertEqual(10, self.store.batch["total"])

    def test_missing_key_and_unverified_routes_are_not_sent(self):
        self._catalogs(["openrouter", "cline", "zen"])
        self.store.state["catalogs"]["cline"]["models"][0]["priceVerified"] = False
        self.store.state["catalogs"]["zen"]["models"][0]["kind"] = "embedding"
        def has_key(provider):
            return provider == "openrouter"
        calls = []
        with patch.object(server_module.access, "key_available", side_effect=has_key), patch.object(server_module.access, "probe", side_effect=lambda provider, ident, _fetcher: calls.append((provider, ident)) or {"provider": provider, "model": ident, "status": "ok", "reply": "ok", "finishReason": "stop", "sent": True}):
            self.store.check_pending()
            self._wait_done()
        self.assertEqual([("openrouter", "openrouter-0")], calls)

    def test_rate_limit_stops_only_that_provider(self):
        self._catalogs(["openrouter", "kilo"], counts=2)
        calls = []
        def probe(provider, ident, _fetcher):
            calls.append((provider, ident))
            status = "rate_limited" if provider == "openrouter" else "ok"
            return {"provider": provider, "model": ident, "status": status, "reply": "" if status != "ok" else "ok", "finishReason": "stop", "sent": status == "ok"}
        with patch.object(server_module.access, "probe", side_effect=probe):
            self.store.check_pending()
            self._wait_done()
        self.assertEqual([("openrouter", "openrouter-0"), ("kilo", "kilo-0"), ("kilo", "kilo-1")], calls)

    def test_cancel_stops_before_next_probe(self):
        self._catalogs(["openrouter", "cline"], counts=2)
        started, release = threading.Event(), threading.Event()
        calls = []
        def probe(provider, ident, _fetcher):
            calls.append((provider, ident))
            started.set()
            release.wait(1)
            return {"provider": provider, "model": ident, "status": "ok", "reply": "ok", "finishReason": "stop", "sent": True}
        with patch.object(server_module.access, "probe", side_effect=probe):
            self.store.check_pending()
            self.assertTrue(started.wait(1))
            self.store.batch_stop.set()
            release.set()
            self._wait_done()
        self.assertEqual(1, len(calls))
        self.assertTrue(self.store.batch["cancelled"])

    def test_repeat_batch_ignores_success_and_previous_errors(self):
        self._catalogs(["openrouter"], counts=3)
        self.store.state["checks"] = {
            "openrouter|openrouter-0": {"provider": "openrouter", "model": "openrouter-0", "status": "ok", "reply": "ok", "finishReason": "stop", "sent": True},
            "openrouter|openrouter-1": {"provider": "openrouter", "model": "openrouter-1", "status": "network_error", "reply": "", "finishReason": None, "sent": True},
        }
        calls = []
        with patch.object(server_module.access, "probe", side_effect=lambda provider, ident, _fetcher: calls.append(ident) or {"provider": provider, "model": ident, "status": "ok", "reply": "ok", "finishReason": "stop", "sent": True}):
            self.store.check_pending()
            self._wait_done()
        self.assertEqual(["openrouter-2"], calls)


if __name__ == "__main__":
    unittest.main()
