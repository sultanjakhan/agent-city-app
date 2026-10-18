import builtins
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from storage_lock import StorageLock


class StorageLockTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.panel = self.root / 'panel'
        self.panel.mkdir()
        self.path = self.panel / '.storage-writer.lock'

    @unittest.skipUnless(os.name == 'posix', 'POSIX symlink opening')
    def test_dangling_redirect_is_rejected_without_creating_target(self):
        target = self.root / 'other-writer-lock'
        self.path.symlink_to(target)
        with self.assertRaises(OSError):
            with StorageLock(self.panel):
                pass
        self.assertFalse(target.exists())
        self.assertTrue(self.path.is_symlink())

    @unittest.skipUnless(os.name == 'posix', 'POSIX atomic no-follow opening')
    def test_redirect_inserted_at_open_is_rejected(self):
        target = self.root / 'other-writer-lock'
        original_path_open = Path.open
        original_open = builtins.open

        def insert_redirect():
            if not self.path.is_symlink():
                self.path.symlink_to(target)

        def path_open(path, *args, **kwargs):
            if path == self.path:
                insert_redirect()
            return original_path_open(path, *args, **kwargs)

        def builtin_open(path, *args, **kwargs):
            if Path(path) == self.path:
                insert_redirect()
            return original_open(path, *args, **kwargs)

        with patch.object(Path, 'open', path_open), patch('builtins.open', builtin_open):
            with self.assertRaises(OSError):
                with StorageLock(self.panel):
                    pass
        self.assertFalse(target.exists())

    def test_live_owner_and_released_lock_keep_same_file(self):
        with StorageLock(self.panel):
            identity = self.path.stat().st_ino
            with self.assertRaisesRegex(OSError, 'still in use'):
                StorageLock(self.panel)
            self.assertEqual(self.path.stat().st_ino, identity)
        with StorageLock(self.panel):
            self.assertEqual(self.path.stat().st_ino, identity)

    def test_process_exit_leaves_reclaimable_file(self):
        code = 'import os,sys; from storage_lock import StorageLock; lock=StorageLock(sys.argv[1]); os._exit(0)'
        subprocess.run([sys.executable, '-c', code, str(self.panel)], check=True, timeout=10)
        identity = self.path.stat().st_ino
        with StorageLock(self.panel):
            self.assertEqual(self.path.stat().st_ino, identity)


if __name__ == '__main__':
    unittest.main()
