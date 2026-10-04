import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import tempfile
from urllib.error import HTTPError
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import access
from server import normalize_catalog, Store


class FakeOpener:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.requests = []
    def open(self, request, timeout):
        self.requests.append(request)
        if self.error:
            raise self.error
        return self
    def __enter__(self): return self
    def __exit__(self, *_): pass
    def read(self, _): return json.dumps(self.response).encode()


class ProbeTests(unittest.TestCase):
    def call(self, opener, catalog=None, key="test-only"):
        return access.probe("openrouter", "qwen/test:free", lambda _: catalog if catalog is not None else {"models": [{"id": "qwen/test:free", "priceVerified": True}]}, key_reader=lambda _: key, opener=opener)

    def test_paid_unknown_or_missing_key_never_sends(self):
        op = FakeOpener()
        for cat in [{"models": []}, {"models": [{"id": "qwen/test:free", "priceVerified": False}]}, {"models": [{"id": "qwen/test:free"}]}]:
            self.assertEqual(self.call(op, cat)["status"], "price_unverified")
        self.assertEqual(self.call(op, key=None)["status"], "missing_key")
        self.assertEqual(op.requests, [])

    def test_exact_reply_complete_and_no_paid_fallback(self):
        op = FakeOpener({"choices": [{"message": {"content": access.MARKER}, "finish_reason": "stop"}]})
        result = self.call(op)
        self.assertEqual(result["status"], "ok")
        body = json.loads(op.requests[0].data)
        self.assertEqual(body["model"], "qwen/test:free")
        self.assertFalse(body["provider"]["allow_fallbacks"])
        self.assertEqual(body["provider"]["max_price"], {"prompt": 0, "completion": 0})
        self.assertNotIn("tools", body)
        self.assertNotIn("test-only", json.dumps(result))

    def test_empty_truncated_and_wrong_reply_are_not_success(self):
        for content, finish, status in [(None, "stop", "empty"), (access.MARKER, "length", "incomplete"), ("incorrect", "stop", "mismatch")]:
            result = self.call(FakeOpener({"choices": [{"message": {"content": content}, "finish_reason": finish}]}))
            self.assertEqual(result["status"], status)

    def test_quota_no_retry_no_error_body_or_key_in_receipt(self):
        op = FakeOpener(error=HTTPError("https://example.invalid", 429, "SECRET", {}, None))
        result = self.call(op)
        self.assertEqual(result["status"], "rate_limited")
        self.assertEqual(len(op.requests), 1)
        self.assertNotIn("SECRET", json.dumps(result))

    def test_provider_401_uses_fresh_key_reader_value(self):
        current = ["first-synthetic-key"]
        opener = FakeOpener(error=HTTPError("https://example.invalid", 401, "SECRET", {}, None))
        result = access.probe(
            "openrouter", "qwen/test:free", lambda _: {"models": [{"id": "qwen/test:free", "priceVerified": True}]},
            key_reader=lambda _provider: current[0], opener=opener)
        self.assertEqual(result["status"], "auth_error")
        self.assertEqual(opener.requests[0].get_header("Authorization"), "Bearer first-synthetic-key")
        current[0] = "second-synthetic-key"
        opener2 = FakeOpener(error=HTTPError("https://example.invalid", 401, "SECRET", {}, None))
        access.probe("openrouter", "qwen/test:free", lambda _: {"models": [{"id": "qwen/test:free", "priceVerified": True}]},
                     key_reader=lambda _provider: current[0], opener=opener2)
        self.assertEqual(opener2.requests[0].get_header("Authorization"), "Bearer second-synthetic-key")

    def test_cline_uses_free_group_not_pass_or_free_substring(self):
        rows = normalize_catalog("cline", {"free": [{"id": "cline-free/deepseek-v4.1-flash"}], "clinePass": [{"id": "paid/free"}]})["models"]
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["chinese"])
        self.assertFalse(rows[0]["priceVerified"])

    def test_zen_names_without_prices_do_not_authorize_inference(self):
        result = normalize_catalog("zen", {"data": [{"id": "mimo-v2.6-flash-free"}]})
        self.assertFalse(result["models"][0]["priceVerified"])

    def test_discovery_providers_cannot_send_even_if_catalog_claims_free(self):
        op = FakeOpener()
        for provider in ["gemini", "groq", "cerebras", "mistral", "siliconflow"]:
            result = access.probe(provider, "test", lambda _: {"models": [{"id": "test", "priceVerified": True}]}, key_reader=lambda _: "synthetic-only", opener=op)
            self.assertEqual(result["status"], "price_unverified")
            self.assertFalse(result["sent"])
        self.assertEqual(op.requests, [])

    def test_check_persists_and_unknown_routes_or_rapid_retries_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            store.state['catalogs']['openrouter'] = {'models': [{'id': 'qwen/test:free'}]}
            record = self.call(FakeOpener({'choices': [{'message': {'content': access.MARKER}, 'finish_reason': 'stop'}]}))
            with patch('access.probe', return_value=record):
                store._check_one('openrouter', 'qwen/test:free', 'openrouter|qwen/test:free')
            self.assertEqual(Store(directory).state['checks']['openrouter|qwen/test:free']['reply'], access.MARKER)
            with self.assertRaises(ValueError): store.check('unknown', 'qwen/test:free')
            with self.assertRaises(ValueError): store.check('openrouter', 'unknown')
            with self.assertRaises(ValueError): store.check('openrouter', 'qwen/test:free')


if __name__ == "__main__": unittest.main()
