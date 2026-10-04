import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import panel_keys as credentials


KEY = "synthetic-key-1234567890"
KEY_2 = "synthetic-replaced-key-2345678901"


class CredentialsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {}, clear=False)
        self.env.start()
        for name in credentials.ENV_KEYS.values():
            os.environ.pop(name, None)
        self.root_patch = patch.object(credentials, "SECRET_ROOT", self.root)
        self.root_patch.start()

    def tearDown(self):
        self.root_patch.stop()
        self.env.stop()
        self.temp.cleanup()

    def _require_dpapi(self):
        if os.name != "nt":
            self.skipTest("DPAPI is Windows-only")
        try:
            credentials._protect(KEY)
        except (OSError, credentials.UI_FORBIDDEN) as exc:
            self.skipTest(f"DPAPI unavailable in this test session: {exc}")

    @unittest.skipUnless(os.name == "nt", "DPAPI is Windows-only")
    def test_real_dpapi_roundtrip_and_revision_is_opaque(self):
        self._require_dpapi()
        credentials.save_key("openrouter", KEY)
        self.assertEqual(credentials.read_key("openrouter"), KEY)
        self.assertEqual(credentials.info("openrouter")["source"], "saved")
        self.assertNotIn(KEY, credentials.revision("openrouter"))
        self.assertNotEqual(credentials.revision("openrouter"), "")

    @unittest.skipUnless(os.name == "nt", "DPAPI is Windows-only")
    def test_saved_key_wins_over_environment(self):
        self._require_dpapi()
        credentials.save_key("cline", KEY)
        os.environ["CLINE_API_KEY"] = "environment-key-123456"
        self.assertEqual(credentials.read_key("cline"), KEY)
        self.assertEqual(credentials.info("cline")["source"], "saved")

    @unittest.skipUnless(os.name == "nt", "DPAPI Windows test")
    def test_replace_then_remove_reveals_environment_fallback(self):
        self._require_dpapi()
        os.environ["GROQ_API_KEY"] = KEY_2
        credentials.save_key("groq", KEY)
        self.assertEqual(credentials.read_key("groq"), KEY)
        credentials.save_key("groq", KEY_2)
        self.assertEqual(credentials.read_key("groq"), KEY_2)
        self.assertTrue(credentials.remove_key("groq"))
        self.assertEqual(credentials.read_key("groq"), KEY_2)
        self.assertEqual(credentials.info("groq")["source"], "environment")

    def test_environment_fallback_and_remove(self):
        os.environ["GEMINI_API_KEY"] = KEY
        self.assertEqual(credentials.read_key("gemini"), KEY)
        self.assertEqual(credentials.info("gemini")["source"], "environment")
        self.assertFalse(credentials.remove_key("gemini"))
        self.assertFalse(credentials.info("gemini")["removable"])

    def test_kilo_is_anonymous(self):
        self.assertTrue(credentials.key_available("kilo"))
        self.assertEqual(credentials.info("kilo"), {"available": True, "source": "anonymous", "removable": False, "canSave": False})

    def test_validation_and_provider_traversal(self):
        with self.assertRaises(ValueError):
            credentials.save_key("../escape", KEY)
        with self.assertRaises(ValueError):
            credentials.save_key("openrouter", "too short")
        with self.assertRaises(ValueError):
            credentials.save_key("openrouter", "x" * 20 + " ")
        self.assertFalse((self.root.parent / "escape.dpapi").exists())

    def test_allowlist_does_not_read_unknown_environment(self):
        os.environ["AWS_SECRET_ACCESS_KEY"] = KEY
        self.assertIsNone(credentials.read_key("openrouter"))


if __name__ == "__main__":
    unittest.main()
