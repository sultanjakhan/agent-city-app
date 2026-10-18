import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tools import verify_separation as separation


class ReviewedAssetsTests(unittest.TestCase):
    def test_review_is_exact_and_does_not_override_private_rules(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'tools').mkdir()
            (root / 'desktop').mkdir()
            raw = bytes((0, 0, 1, 0, 255, 254))
            icon = root / 'desktop/app.ico'
            icon.write_bytes(raw)
            manifest = {'schemaVersion': 1, 'assets': [{'path': 'desktop/app.ico', 'sha256': hashlib.sha256(raw).hexdigest(), 'baselineCommit': 'a' * 40, 'review': 'Synthetic reviewed ICO'}]}
            path = root / 'tools/reviewed-binaries.json'
            path.write_text(json.dumps(manifest))
            with patch.object(separation, 'APP', root):
                self.assertEqual(separation.scan(), [])
                icon.write_bytes(raw + b'changed')
                self.assertIn({'file': 'desktop/app.ico', 'category': 'unreviewed-binary'}, separation.scan())
                icon.write_bytes(raw)
                (root / 'desktop/unlisted.ico').write_bytes(raw)
                self.assertIn({'file': 'desktop/unlisted.ico', 'category': 'unreviewed-binary'}, separation.scan())
                private = root / 'private'
                private.mkdir()
                (private / 'app.ico').write_bytes(raw)
                manifest['assets'][0]['path'] = 'private/app.ico'
                path.write_text(json.dumps(manifest))
                self.assertIn({'file': 'private', 'category': 'private-directory'}, separation.scan())
                manifest['schemaVersion'] = True
                path.write_text(json.dumps(manifest))
                self.assertIn({'file': 'tools/reviewed-binaries.json', 'category': 'invalid-reviewed-binary-manifest'}, separation.scan())
                manifest['schemaVersion'] = 1
                manifest['assets'][0]['path'] = '../escape.ico'
                path.write_text(json.dumps(manifest))
                self.assertIn({'file': 'tools/reviewed-binaries.json', 'category': 'invalid-reviewed-binary-manifest'}, separation.scan())

    def test_real_public_icon_matches_reviewed_bytes(self):
        entries = separation.reviewed_binaries()
        icon = separation.APP / 'desktop/AgentCity.ico'
        self.assertEqual(hashlib.sha256(icon.read_bytes()).hexdigest(), entries['desktop/AgentCity.ico'])
