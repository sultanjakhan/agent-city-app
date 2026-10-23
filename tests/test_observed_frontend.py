"""Synthetic source-only assembly tests; no installed assets or runtime data."""
import hashlib
from pathlib import Path
import tempfile
import unittest
from compat.observed_frontend import assemble, bundle, MARKER

ROOT = Path(__file__).resolve().parents[1]


class ObservedFrontendTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'static').mkdir()
        self.js = b"'use strict';\n// Synthetic baseline only\nwindow.LiveSessions={getSnapshot:()=>null};\n"
        self.css = '/* Synthetic UTF-8 baseline: 雲 */\n:root{--ink:#252525}\n'.encode()
        for name, data in [('live-sessions.js', self.js), ('live-sessions.css', self.css)]:
            (self.root / 'static' / name).write_bytes(data)

    def test_two_existing_assets_only_and_originals_byte_identical(self):
        planned = assemble(self.root, ROOT)
        self.assertEqual({'static/live-sessions.js', 'static/live-sessions.css'}, set(planned))
        self.assertTrue(planned['static/live-sessions.js'].startswith(self.js.decode()))
        self.assertTrue(planned['static/live-sessions.css'].startswith(self.css.decode()))
        self.assertIn('AgentCityObservedHost.install()', planned['static/live-sessions.js'])
        self.assertIn("dataset.agentCityMode!=='passive_dashboard'", planned['static/live-sessions.js'])
        self.assertEqual(self.js, (self.root / 'static/live-sessions.js').read_bytes())
        self.assertEqual(self.css, (self.root / 'static/live-sessions.css').read_bytes())
        self.assertNotIn('<script src=', bundle(ROOT))
        self.assertNotIn("fetch(", bundle(ROOT))

    def test_explicit_input_hash_guard_and_no_reassembly(self):
        hashes = {'live-sessions.js': hashlib.sha256(self.js).hexdigest(), 'live-sessions.css': hashlib.sha256(self.css).hexdigest()}
        self.assertEqual(2, len(assemble(self.root, ROOT, hashes)))
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            assemble(self.root, ROOT, dict(hashes, **{'live-sessions.js': 'wrong'}))
        (self.root / 'static/live-sessions.js').write_bytes(self.js + MARKER.encode())
        with self.assertRaisesRegex(ValueError, 'already assembled'):
            assemble(self.root, ROOT)


if __name__ == '__main__':
    unittest.main()
