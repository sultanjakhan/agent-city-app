from owner_client import authorize, headers as owner_headers
import http.client
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import URLError, HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import Store, Server, normalize_catalog, normalize_codexbar, now
import panel_keys as credentials


def model(model_id="qwen/example:free", **extra):
    return {"id": model_id, "name": "Example", "pricing": {"prompt": "0", "completion": "0"},
            "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]}, **extra}


class CatalogTests(unittest.TestCase):
    def test_only_confirmed_zero_price_text_models(self):
        payload = {"data": [model(), model("vendor/paid:free", pricing={"prompt": "0.01", "completion": "0"}),
                            model("vendor/unknown", pricing={"prompt": "0"}),
                            model("vendor/cache", pricing={"prompt": "0", "completion": "0", "input_cache_read": "1"}),
                            model("openrouter/free"), model("vendor/audio", architecture={"modality": "text->audio"})]}
        result = normalize_catalog("openrouter", payload)
        self.assertEqual([x["id"] for x in result["models"]], ["qwen/example:free"])
        self.assertTrue(result["models"][0]["chinese"])
        self.assertIsNone(result["models"][0]["tools"])

    def test_kilo_keeps_exact_free_routes(self):
        data = normalize_catalog("kilo", {"data": [model("qwen/paid"), model()]})
        self.assertEqual(len(data["models"]), 1)

    def test_price_verified_means_zero_not_merely_known_paid_price(self):
        payload = {'data': [model('zero:free'),
                            model('known-paid:free', pricing={'prompt': '0.01', 'completion': '0.02'}),
                            model('unknown:free', pricing={}),
                            model('conditional:free', pricing={'prompt': '0', 'completion': '0', 'request': '1'})]}
        for provider in ('openrouter', 'kilo'):
            with self.subTest(provider=provider):
                rows = normalize_catalog(provider, payload)['models']
                self.assertEqual(['zero:free'], [row['id'] for row in rows])
                self.assertTrue(rows[0]['priceVerified'])

    def test_cline_free_group_trial_or_unknown_is_not_zero_price_evidence(self):
        rows = normalize_catalog('cline', {'free': [
            {'id': 'free-label-only'},
            {'id': 'known-paid', 'pricing': {'prompt': '1', 'completion': '1'}},
            {'id': 'trial-credit', 'plan': 'trial', 'freeCredits': 10},
        ]})['models']
        self.assertTrue(rows)
        self.assertTrue(all(row['priceVerified'] is False for row in rows))

    def test_paid_only_catalog_has_known_pricing_but_unknown_and_trial_do_not(self):
        paid = normalize_catalog('openrouter', {'data': [model('paid', pricing={'prompt': '1', 'completion': '2'})]})
        self.assertEqual([], paid['models'])
        self.assertEqual({'confirmedFree': 0, 'knownPaid': 1, 'unknown': 0, 'complete': True}, paid['pricingSummary'])
        for entry in (model('unknown', pricing={}), model('trial', plan='trial'), model('subscription', pricingType='subscription')):
            with self.subTest(id=entry['id']):
                result = normalize_catalog('openrouter', {'data': [entry]})
                self.assertEqual([], result['models'])
                self.assertEqual(1, result['pricingSummary']['unknown'])
                self.assertFalse(result['pricingSummary']['complete'])

    def test_conflicting_duplicate_prices_cannot_confirm_free(self):
        result = normalize_catalog('openrouter', {'data': [model('duplicate'), model('duplicate', pricing={'prompt':'1','completion':'1'})]})
        self.assertEqual([], result['models'])
        self.assertFalse(result['pricingSummary']['complete'])

    def test_malformed_catalog_is_not_an_empty_success(self):
        with self.assertRaises(Exception):
            normalize_catalog("openrouter", {"error": "outage"})

    def test_zen_discovers_new_ids_without_curated_list_or_price_assumptions(self):
        result = normalize_catalog("zen", {"data": [{"id": "new-vendor/new-model-free", "name": "New Model", "context_length": 12345}]})
        self.assertEqual([m["id"] for m in result["models"]], ["new-vendor/new-model-free"])
        self.assertEqual(result["models"][0]["context"], 12345)
        self.assertFalse(result["models"][0]["priceVerified"])
        self.assertNotIn("docsOnly", result)


class CodexBarTests(unittest.TestCase):
    def test_normalizes_zero_unknown_and_partial_failure_without_identity(self):
        raw = {"schemaVersion": 1, "generatedAt": now(), "staleAfterSeconds": 180,
               "host": {"codexBarVersion": "0.56.8", "account": "do-not-copy"}, "providers": [
                   {"id": "codex", "name": "Codex", "enabled": True, "identity": {"accountEmail": "private@example.invalid"},
                    "windows": [{"kind": "session", "usedPercent": 100}, {"kind": "weekly", "remainingPercent": None}],
                    "updatedAt": now(), "credits": {"remaining": 0}, "error": None},
                   {"id": "claude", "name": "Claude", "windows": [], "error": {"message": "SECRET"}},
                   {"id": "disabled", "enabled": False} ]}
        clean = normalize_codexbar(raw)
        self.assertEqual(len(clean["providers"]), 2)
        self.assertEqual(clean["providers"][0]["windows"][0]["remainingPercent"], 0)
        self.assertIsNone(clean["providers"][0]["windows"][1]["remainingPercent"])
        self.assertEqual(clean["providers"][0]["credits"], 0)
        self.assertTrue(clean["providers"][1]["error"])
        serialized = json.dumps(clean)
        for private in ("private@example", "SECRET", "do-not-copy", "identity"):
            self.assertNotIn(private, serialized)

    def test_invalid_percent_and_timestamp_stay_unknown(self):
        clean = normalize_codexbar({"schemaVersion": 1, "providers": [{"id": "codex", "windows": [
            {"kind": "session", "remainingPercent": float("nan"), "usedPercent": True, "resetAt": "not a date"}]}]})
        window = clean["providers"][0]["windows"][0]
        self.assertIsNone(window["remainingPercent"])
        self.assertIsNone(window["resetAt"])

    def test_unknown_schema_rejected(self):
        with self.assertRaises(ValueError):
            normalize_codexbar({"schemaVersion": 2, "providers": []})

    def test_source_labels_are_preserved_and_generic_windows_are_not_assumed_weekly(self):
        clean = normalize_codexbar({"schemaVersion": 1, "providers": [{"id": "custom", "windows": [
            {"kind": "secondary", "label": "Requests today", "remainingPercent": 40},
            {"kind": "secondary", "remainingPercent": 50}]}]})
        self.assertEqual([w["label"] for w in clean["providers"][0]["windows"]], ["Requests today", "Лимит"])
        self.assertIsNone(clean["staleAfterSeconds"])


class StateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name, executable=Path("not-installed"))

    def tearDown(self):
        self.temp.cleanup()

    def test_favorites_survive_restart(self):
        self.store.catalog_fetcher = lambda _: normalize_catalog("openrouter", {"data": [model()]})
        self.store._refresh_one("openrouter")
        self.store.favorite("qwen/example:free", True)
        restarted = Store(self.temp.name)
        self.assertEqual(restarted.snapshot()["favorites"], ["qwen/example:free"])
        restarted.favorite("qwen/example:free", False)
        self.assertEqual(Store(self.temp.name).snapshot()["favorites"], [])

    def test_no_seed_catalog_and_legacy_curated_models_are_removed_without_losing_favorites(self):
        self.assertTrue(self.store.snapshot()["catalogs"]["zen"]["models"])
        self.store.state["catalogs"]["zen"] = {"docsOnly": True, "models": [{"id": "old-curated"}], "updatedAt": now()}
        self.store.state["favorites"] = ["old-curated"]
        self.store.save()
        snapshot = Store(self.temp.name).snapshot()
        self.assertNotIn("old-curated", [m["id"] for m in snapshot["catalogs"]["zen"]["models"]])
        self.assertEqual(snapshot["catalogs"]["zen"]["sourceKind"], "official_docs_snapshot")
        self.assertEqual(snapshot["favorites"], ["old-curated"])

    def test_failure_retains_last_good_then_paid_model_disappears(self):
        self.store.catalog_fetcher = lambda _: normalize_catalog("openrouter", {"data": [model()]})
        self.store._refresh_one("openrouter")
        self.store.favorite("qwen/example:free", True)
        updated = self.store.snapshot()["catalogs"]["openrouter"]["updatedAt"]
        def offline(_):
            raise URLError("secret transport detail")
        self.store.catalog_fetcher = offline
        self.store._refresh_one("openrouter")
        catalog = self.store.snapshot()["catalogs"]["openrouter"]
        self.assertEqual(catalog["updatedAt"], updated)
        self.assertEqual(len(catalog["models"]), 1)
        self.assertTrue(catalog["error"])
        self.assertNotIn("secret", catalog["error"])
        self.store.catalog_fetcher = lambda _: normalize_catalog("openrouter", {"data": [model(pricing={"prompt": "1", "completion": "1"})]})
        self.store._refresh_one("openrouter")
        self.assertEqual(self.store.snapshot()["catalogs"]["openrouter"]["models"], [])
        self.assertEqual(self.store.snapshot()["favorites"], ["qwen/example:free"])
        self.store.favorite("qwen/example:free", False)

    def test_only_one_concurrent_fetch_per_source(self):
        started, finish = threading.Event(), threading.Event()
        calls = []
        def fetch(source):
            calls.append(source); started.set(); finish.wait(3)
            return {"models": []}
        self.store.catalog_fetcher = fetch
        self.store.refresh("openrouter")
        self.assertTrue(started.wait(1))
        self.store.refresh("openrouter")
        self.assertEqual(calls, ["openrouter"])
        finish.set()
        for thread in threading.enumerate():
            if thread.name.endswith("(_refresh_one)"):
                thread.join(3)
        self.assertEqual(self.store.snapshot()["busy"], [])


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.keys_patch = patch.object(credentials, "SECRET_ROOT", Path(self.temp.name) / "keys")
        self.keys_patch.start()
        self.store = Store(self.temp.name, executable=Path("not-installed"))
        self.store.state["catalogs"]["openrouter"] = {"models": normalize_catalog("openrouter", {"data": [model()]})["models"]}
        self.server = Server(("127.0.0.1", 0), self.store)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        authorize(self.server)

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join()
        self.keys_patch.stop()
        self.temp.cleanup()

    def call(self, path, method="GET", body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        connection.request(method, path, body=body, headers=owner_headers("http://127.0.0.1:"+str(self.server.server_port),headers))
        response = connection.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        connection.close()
        return result

    def require_dpapi(self):
        try:
            credentials._protect("synthetic-dpapi-probe-123456")
        except (OSError, credentials.UI_FORBIDDEN) as exc:
            self.skipTest(f"DPAPI unavailable in this test session: {exc}")

    def test_http_favorite_and_static_page(self):
        status, headers, page = self.call("/")
        self.assertEqual(status, 200)
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        self.assertIn("Agent City", page.decode())
        body = json.dumps({"id": "qwen/example:free", "enabled": True})
        status, _, raw = self.call("/api/favorite", "POST", body, {"X-Agent-City": "1"})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(raw)["favorites"], ["qwen/example:free"])
        self.assertEqual(Store(self.temp.name).snapshot()["favorites"], ["qwen/example:free"])

    def test_external_origin_host_and_cross_site_mutation_rejected(self):
        for headers in ({"Host": "evil.invalid"}, {"Origin": "https://evil.invalid"}):
            self.assertEqual(self.call("/api/state", headers=headers)[0], 403)
        self.assertEqual(self.call("/api/refresh", "POST", '{}')[0], 403)
        self.assertEqual(self.call("/api/refresh", "POST", '{}', {"X-Agent-City": "1", "Origin": "null"})[0], 403)
        self.assertEqual(self.call("/../../state.json")[0], 404)
        self.assertEqual(self.call("/server.py")[0], 404)

    def test_unknown_favorite_and_malformed_body_are_rejected(self):
        for body in ('null', '{', '{"id":"unknown","enabled":true}'):
            self.assertEqual(self.call("/api/favorite", "POST", body, {"X-Agent-City": "1"})[0], 400)

    def test_credential_requires_csrf_token_and_rejects_external_origin(self):
        body = json.dumps({"action": "save", "provider": "cline", "key": "synthetic-key-1234567890"})
        for headers in ({"X-Agent-City": "1"}, {"X-Agent-City": "1", "X-Agent-City-Token": "bad"},
                        {"X-Agent-City": "1", "X-Agent-City-Token": self.store.csrf_token, "Origin": "https://evil.invalid"}):
            self.assertEqual(self.call("/api/credential", "POST", body, headers)[0], 403)
        self.assertFalse(credentials.SECRET_ROOT.exists())

    def test_credential_allowlist_and_validation(self):
        headers = {"X-Agent-City": "1", "X-Agent-City-Token": self.store.csrf_token}
        for provider, key in (("../outside", "synthetic-key-1234567890"), ("kilo", "synthetic-key-1234567890"), ("cline", "short")):
            body = json.dumps({"action": "save", "provider": provider, "key": key})
            self.assertEqual(self.call("/api/credential", "POST", body, headers)[0], 400)

    @unittest.skipUnless(sys.platform == "win32", "DPAPI Windows test")
    def test_credential_http_roundtrip_no_secret_in_state_and_old_checks_invalidated(self):
        self.require_dpapi()
        key = "synthetic-only-api-key-1234567890"
        headers = {"X-Agent-City": "1", "X-Agent-City-Token": self.store.csrf_token}
        self.store.state["checks"]["cline|example"] = {"provider": "cline", "status": "ok", "reply": "old"}
        with patch("server.fetch_catalog", side_effect=AssertionError("save must not call network")):
            status, _, raw = self.call("/api/credential", "POST", json.dumps({"action": "save", "provider": "cline", "key": key}), headers)
        self.assertEqual(status, 200)
        value = json.loads(raw)
        self.assertTrue(value["credentialInfo"]["cline"]["available"])
        self.assertEqual(value["checks"], {})
        self.assertEqual(credentials.read_key("cline"), key)
        self.assertNotIn(key, raw.decode())
        self.assertNotIn(key, self.store.path.read_text(encoding="utf-8"))
        self.assertNotIn(key, (credentials.SECRET_ROOT / "cline.dpapi").read_text())
        self.assertTrue(Store(self.temp.name).snapshot()["credentials"]["cline"])
        status, _, _ = self.call("/api/credential", "POST", json.dumps({"action": "remove", "provider": "cline"}), headers)
        self.assertEqual(status, 200)
        self.assertFalse((credentials.SECRET_ROOT / "cline.dpapi").exists())

    @unittest.skipUnless(sys.platform == "win32", "DPAPI Windows test")
    def test_credential_replace_survives_store_restart_then_remove(self):
        self.require_dpapi()
        first = "synthetic-first-api-key-1234567890"
        second = "synthetic-second-api-key-1234567890"
        headers = {"X-Agent-City": "1", "X-Agent-City-Token": self.store.csrf_token}
        for key in (first, second):
            status, _, raw = self.call("/api/credential", "POST", json.dumps({"action": "save", "provider": "groq", "key": key}), headers)
            self.assertEqual(status, 200)
            self.assertNotIn(key, raw.decode())
            self.assertNotIn(key, self.store.path.read_text(encoding="utf-8"))
        self.assertEqual(credentials.read_key("groq"), second)
        restarted = Store(self.temp.name)
        self.assertEqual(restarted.snapshot()["credentialInfo"]["groq"]["source"], "saved")
        status, _, _ = self.call("/api/credential", "POST", json.dumps({"action": "remove", "provider": "groq"}), headers)
        self.assertEqual(status, 200)
        self.assertIsNone(credentials.read_key("groq"))

    def test_key_change_blocked_during_provider_or_model_request(self):
        headers = {"X-Agent-City": "1", "X-Agent-City-Token": self.store.csrf_token}
        body = json.dumps({"action": "save", "provider": "cline", "key": "synthetic-only-api-key-1234567890"})
        for busy in ({"check"}, {"cline"}):
            self.store.busy = busy
            self.assertEqual(self.call("/api/credential", "POST", body, headers)[0], 409)
        self.assertFalse(credentials.SECRET_ROOT.exists())

    @unittest.skipUnless(sys.platform == "win32", "DPAPI Windows test")
    def test_saved_key_reaches_provider_and_invalid_replacement_removes_accepted_status(self):
        self.require_dpapi()
        accepted = "synthetic-accepted-key-1234567890"
        rejected = "synthetic-rejected-key-1234567890"
        sent_keys = []
        class Reply:
            def __init__(self, body): self.body = body
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def read(self, _): return json.dumps(self.body).encode()
        class Catalog:
            def open(self, request, timeout): return Reply({"data": [model()]})
        class Auth:
            def open(self, request, timeout):
                key = request.get_header("Authorization").removeprefix("Bearer ")
                sent_keys.append(key)
                if key != accepted: raise HTTPError(request.full_url, 401, "rejected", {}, None)
                return Reply({"data": {"limit": None}})
        headers = {"X-Agent-City": "1", "X-Agent-City-Token": self.store.csrf_token}
        for key, expected in [(accepted, "accepted"), (rejected, "rejected")]:
            status, _, _ = self.call("/api/credential", "POST", json.dumps({"provider": "openrouter", "action": "save", "key": key}), headers)
            self.assertEqual(status, 200)
            self.assertNotEqual(self.store.snapshot()["catalogs"]["openrouter"].get("authStatus"), "accepted")
            with patch("server.build_opener", return_value=Catalog()), patch("access.build_opener", return_value=Auth()):
                self.store._refresh_one("openrouter")
            snapshot = self.store.snapshot()
            self.assertEqual(snapshot["catalogs"]["openrouter"]["authStatus"], expected)
            self.assertNotIn(key, json.dumps(snapshot))
        self.assertEqual(sent_keys, [accepted, rejected])

    def test_changed_external_key_invalidates_check_and_auth_receipt(self):
        self.store.state["checks"]["cline|example"] = {"provider": "cline", "status": "ok", "reply": "old", "credentialRevision": "old"}
        self.store.state["catalogs"]["cline"] = {"models": [], "authStatus": "accepted", "credentialRevision": "old"}
        snapshot = self.store.snapshot()
        self.assertEqual(snapshot["checks"]["cline|example"]["status"], "key_changed")
        self.assertEqual(snapshot["checks"]["cline|example"]["reply"], "")
        self.assertEqual(snapshot["catalogs"]["cline"]["authStatus"], "unverified")
        self.assertNotIn("credentialRevision", json.dumps(snapshot))


if __name__ == "__main__":
    unittest.main()
