import contextlib
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import panel_keys
import set_panel_key


OLD = 'synthetic-existing-key-12345'
NEW = 'synthetic-replacement-key-12345'


class KeyRotationTests(unittest.TestCase):
    def test_empty_environment_is_absent_consistently(self):
        with tempfile.TemporaryDirectory() as root, patch.object(panel_keys, 'SECRET_ROOT', Path(root)), patch.dict(os.environ, {'GROQ_API_KEY': ''}):
            self.assertIsNone(panel_keys.read_key('groq'))
            self.assertFalse(panel_keys.key_available('groq'))
            self.assertFalse(panel_keys.info('groq')['available'])
            self.assertEqual(panel_keys.revision('groq'), '')

    def test_failed_replacement_preserves_saved_key(self):
        with tempfile.TemporaryDirectory() as root, patch.object(panel_keys, 'SECRET_ROOT', Path(root)), patch.object(panel_keys, '_protect', side_effect=lambda key: key.encode()), patch.object(panel_keys, '_unprotect', side_effect=lambda raw: raw.decode()):
            panel_keys.save_key('groq', OLD)
            for operation in ('_protect', 'os.fsync', 'os.replace'):
                with self.subTest(operation=operation), patch('panel_keys.' + operation, side_effect=OSError('synthetic persistence failure')):
                    with self.assertRaises(OSError):
                        panel_keys.save_key('groq', NEW)
                self.assertEqual(panel_keys.read_key('groq'), OLD)
                self.assertEqual(list(Path(root).iterdir()), [Path(root) / 'groq.dpapi'])
            with self.assertRaises(ValueError):
                panel_keys.save_key('groq', 'short')
            self.assertEqual(panel_keys.read_key('groq'), OLD)
            panel_keys.save_key('groq', NEW)
            self.assertEqual(panel_keys.read_key('groq'), NEW)

    def test_cli_failure_is_nonzero_and_redacted(self):
        output = io.StringIO()
        with patch('sys.argv', ['set_panel_key.py', 'groq']), patch.object(set_panel_key, 'getpass', return_value=NEW), patch.object(set_panel_key, 'save_key', side_effect=OSError(NEW)), contextlib.redirect_stderr(output), contextlib.redirect_stdout(output):
            self.assertEqual(set_panel_key.main(), 1)
        self.assertNotIn(NEW, output.getvalue())
        self.assertNotIn('Key saved', output.getvalue())


if __name__ == '__main__':
    unittest.main()
