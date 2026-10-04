from datetime import datetime, timedelta, timezone
import unittest

import availability


def stamp(seconds_ago=120):
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).isoformat()


def model(model_id, *, price=True, kind="chat"):
    return {"id": model_id, "priceVerified": price, "kind": kind}


def check(status=None, *, reply="", finish="stop", sent=False, age=120):
    value = {"attemptedAt": stamp(age), "reply": reply, "finishReason": finish, "sent": sent}
    if status is not None:
        value["status"] = status
    return value


class AvailabilityTests(unittest.TestCase):
    def test_unique_models_and_priority_buckets(self):
        snapshot = {
            "credentials": {"done": False, "pending": True, "retry": True, "access": True, "missing": False},
            "sources": [{"id": "access", "discoveryOnly": True}],
            "catalogs": {
                "done": {"models": [model("shared"), model("done")]},
                "pending": {"models": [model("shared"), model("pending")]},
                "retry": {"models": [model("retry")]},
                "access": {"models": [model("access")]},
                "missing": {"models": [model("missing")]},
            },
            "checks": {
                "done|shared": check("ok", reply="yes"),
                "done|done": check("mismatch", reply="text"),
                "retry|retry": check("network_error", sent=True),
            },
        }
        result = availability.summarize(snapshot)
        self.assertEqual(6, result["total"])
        self.assertEqual(2, result["responded"])
        self.assertEqual(1, result["pending"])
        self.assertEqual(1, result["needsRetry"])
        self.assertEqual(1, result["needsAccess"])
        self.assertEqual(1, result["needsKey"])
        self.assertEqual(result["total"], sum(result[key] for key in ("responded", "pending", "needsRetry", "needsAccess", "needsKey")))

    def test_pending_routes_exclude_models_with_response_on_another_provider(self):
        snapshot = {
            "credentials": {"a": True, "b": True},
            "sources": [],
            "catalogs": {"a": {"models": [model("same")]}, "b": {"models": [model("same"), model("only-pending")]}},
            "checks": {"a|same": check("ok", reply="done")},
        }
        result = availability.summarize(snapshot)
        self.assertEqual([{"provider": "b", "model": "only-pending"}], result["pendingRoutes"])

    def test_recent_provider_rate_limit_blocks_other_routes(self):
        snapshot = {
            "credentials": {"groq": True}, "sources": [],
            "catalogs": {"groq": {"models": [model("fresh"), model("other")] }},
            "checks": {"groq|fresh": {**check("rate_limited", age=5), "provider": "groq"}},
        }
        result = availability.summarize(snapshot)
        self.assertEqual(2, result["needsRetry"])
        self.assertEqual([], result["pendingRoutes"])

    def test_key_changed_is_eligible_for_pending_again(self):
        snapshot = {
            "credentials": {"p": True}, "sources": [],
            "catalogs": {"p": {"models": [model("m")] }},
            "checks": {"p|m": check("key_changed")},
        }
        result = availability.summarize(snapshot)
        self.assertEqual(1, result["pending"])
        self.assertEqual([{"provider": "p", "model": "m"}], result["pendingRoutes"])

    def test_docs_only_catalogs_are_not_availability(self):
        snapshot = {
            "credentials": {}, "sources": [],
            "catalogs": {"p": {"docsOnly": True, "models": [model("ghost")] }},
            "checks": {},
        }
        result = availability.summarize(snapshot)
        self.assertEqual({"total": 0, "responded": 0, "pending": 0, "needsRetry": 0, "needsAccess": 0, "needsKey": 0, "pendingRoutes": []}, result)


if __name__ == "__main__":
    unittest.main()
