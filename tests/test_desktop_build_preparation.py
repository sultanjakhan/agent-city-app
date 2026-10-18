import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from tools import prepare_desktop_build as preparation


class DesktopBuildPreparationTests(unittest.TestCase):
    def test_non_windows_refuses_without_creating_any_output(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(sys, 'platform', 'linux'):
            destination = Path(directory) / 'build'
            with self.assertRaisesRegex(ValueError, 'Windows x64'):
                preparation.prepare(destination)
            self.assertFalse(destination.exists())

    def test_existing_directory_is_never_reused_or_modified(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(sys, 'platform', 'win32'):
            destination = Path(directory) / 'build'
            destination.mkdir()
            sentinel = destination / 'retain.txt'
            sentinel.write_text('existing build')
            with self.assertRaises(FileExistsError):
                preparation.prepare(destination)
            self.assertEqual(sentinel.read_text(), 'existing build')
            self.assertEqual(list(destination.iterdir()), [sentinel])

    def test_corrupt_download_cannot_reach_install_or_dotnet(self):
        self.exercise_download(corrupt=True)

    def test_verified_inputs_install_offline_and_restore_locked_with_inherited_environment(self):
        self.exercise_download(corrupt=False)

    def exercise_download(self, corrupt):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'source'
            (source / 'desktop').mkdir(parents=True)
            wheel = 'example-1.0-py3-none-any.whl'
            expected = b'locked-test-wheel'
            (source / 'desktop/build-dependencies.json').write_text(json.dumps([
                {'wheel': wheel, 'sha256': hashlib.sha256(expected).hexdigest(), 'licenseFiles': {}}
            ]))
            build = root / 'build'
            calls = []

            def execute(args, **kwargs):
                calls.append((args, kwargs))
                if 'download' in args:
                    (build / 'dependencies' / wheel).write_bytes(b'corrupt' if corrupt else expected)

            with patch.object(preparation, 'ROOT', source), patch.object(sys, 'platform', 'win32'), \
                 patch.object(preparation.subprocess, 'run', side_effect=execute), \
                 patch.dict(os.environ, {'AGENT_CITY_PREP_TEST': 'inherited'}):
                if corrupt:
                    with self.assertRaisesRegex(ValueError, 'locked wheel mismatch'):
                        preparation.prepare(build)
                    self.assertEqual(len(calls), 1)
                    self.assertFalse((build / 'python-tools').exists())
                else:
                    preparation.prepare(build)
                    self.assertEqual(len(calls), 3)
                    self.assertIn('--no-index', calls[1][0])
                    self.assertIn('--require-hashes', calls[1][0])
                    self.assertIn('--locked-mode', calls[2][0])
                    for _, options in calls:
                        self.assertEqual(options['env']['AGENT_CITY_PREP_TEST'], 'inherited')
                        self.assertTrue(options['check'])
