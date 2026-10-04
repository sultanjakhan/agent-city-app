import unittest
from project_policy import preview_policy, validate_policy, PolicyValidationError

class PolicyTests(unittest.TestCase):
    def policy(self, **changes):
        return dict(schemaVersion=1, instructions="Check project rules", sourceIds=["docs"], allowedActions=["read", "write"], deniedActions=["write"], defaultPipelineId=None, **changes)

    def test_ceiling_conflicts_and_deny(self):
        result = preview_policy(self.policy(), {"allowedActions": ["read", "write", "publish"], "sourceIds": ["docs", "secret"]}, {"allowedActions": ["read"], "deniedActions": ["read"]})
        self.assertEqual(result["allowedActions"], [])
        self.assertEqual(result["sourceIds"], ["docs"])
        self.assertEqual(len(result["conflicts"]), 5)
        self.assertFalse(result["runtimeEnforced"])

    def test_empty_child_is_stricter_and_stage_cannot_restore(self):
        result = preview_policy(self.policy(), {"sourceIds": [], "allowedActions": []}, {"sourceIds": ["docs"], "allowedActions": ["read"]})
        self.assertEqual(result["sourceIds"], [])
        self.assertEqual(result["allowedActions"], [])
        self.assertEqual(len(result["conflicts"]), 3)

    def test_manual_task_and_inheritance(self):
        result = preview_policy(self.policy())
        self.assertEqual(result["allowedActions"], ["read"])
        self.assertIsNone(validate_policy(self.policy())["defaultPipelineId"])

    def test_invalid_and_credential_like_references(self):
        for value in [{"schemaVersion": 2}, {"schemaVersion": 1, "sourceIds": ["https://user:password@example.com"]}, {"schemaVersion": 1, "credentials": "secret"}, {"schemaVersion": 1, "allowedActions": ["read", "read"]}]:
            with self.assertRaises(PolicyValidationError): validate_policy(value)
        with self.assertRaises(PolicyValidationError): preview_policy(self.policy(), {"permissions": ["admin"]})
