import copy
import unittest

from model_query import page_models


def snapshot():
    return {
        "serverTime": "2026-10-04T10:00:00Z",
        "sources": [{"id": "openrouter", "catalogUrl": "https://example.invalid/catalog"}, {"id": "zen"}],
        "credentials": {"openrouter": True, "zen": False},
        "catalogs": {
            "openrouter": {"updatedAt": "2026-10-03", "authStatus": "accepted", "models": [
                {"id": "zeta", "name": "Zeta Vision", "developer": "Acme Labs", "kind": "chat", "tools": True, "vision": True, "priceVerified": True, "priceVerifiedAt": "2026-10-02"},
                {"id": "alpha", "name": "Alpha", "developer": "Other", "kind": "chat", "tools": False, "vision": False, "priceVerified": False},
            ]},
            "zen": {"updatedAt": "2026-10-01", "models": [{"id": "struct", "name": "Struct", "developer": "Acme Types", "kind": "structured", "priceVerified": False}]},
        },
        "checks": {"openrouter|zeta": {"status": "ok", "attemptedAt": "2026-10-04T09:00:00Z"}},
    }


class ModelQueryTests(unittest.TestCase):
    def test_filters_and_separate_evidence(self):
        result = page_models(snapshot(), {"developer": "acme", "provider": "openrouter", "vision": True})
        self.assertEqual([row["id"] for row in result["routes"]], ["zeta"])
        self.assertEqual(result["routes"][0]["evidence"]["catalog"]["date"], "2026-10-03")
        self.assertEqual(result["routes"][0]["evidence"]["price"]["date"], "2026-10-02")
        self.assertEqual(result["routes"][0]["evidence"]["auth"], {"hasKey": True, "authStatus": "accepted"})
        self.assertEqual(result["routes"][0]["evidence"]["quota"], {"status": "unknown"})

    def test_bounded_pagination_and_stable_revision(self):
        first = page_models(snapshot(), {"limit": 1})
        second = page_models(snapshot(), {"limit": 1, "offset": 1, "revision": first["revision"]})
        self.assertEqual(first["total"], 3)
        self.assertEqual(first["nextOffset"], 1)
        self.assertEqual(second["nextOffset"], 2)
        self.assertEqual(first["revision"], second["revision"])

    def test_response_status_and_stale_revision(self):
        result = page_models(snapshot(), {"responseStatus": "ok"})
        self.assertEqual([row["id"] for row in result["routes"]], ["zeta"])
        changed = copy.deepcopy(snapshot())
        changed["catalogs"]["zen"]["updatedAt"] = "2026-10-05"
        with self.assertRaisesRegex(ValueError, "stale revision"):
            page_models(changed, {"revision": result["revision"]})

    def test_unknown_and_invalid_arguments_are_rejected(self):
        for params in ({"wat": 1}, {"limit": 51}, {"offset": -1}, {"tools": "true"}, {"provider": 3}):
            with self.assertRaises(ValueError):
                page_models(snapshot(), params)


if __name__ == "__main__":
    unittest.main()
