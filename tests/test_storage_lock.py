import multiprocessing
import os
from pathlib import Path
import tempfile
import unittest

from storage_lock import write_lock


def publish_marker(path, started, finished):
    started.set()
    with write_lock(path):
        Path(path).write_text('saved', encoding='utf-8')
    finished.set()


class StorageLockTests(unittest.TestCase):
    def test_other_process_waits_until_transaction_releases_the_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'document.json'
            context = multiprocessing.get_context('spawn')
            started, finished = context.Event(), context.Event()
            process = context.Process(target=publish_marker, args=(str(path), started, finished))
            try:
                with write_lock(path):
                    process.start()
                    self.assertTrue(started.wait(5))
                    self.assertFalse(finished.wait(.1))
                    self.assertFalse(path.exists())
                process.join(5)
                self.assertEqual(process.exitcode, 0)
                self.assertTrue(finished.is_set())
                self.assertEqual(path.read_text(encoding='utf-8'), 'saved')
            finally:
                if process.is_alive():
                    process.terminate()
                    process.join(5)

    def test_lock_file_stays_bounded_after_repeated_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'document.json'
            for _ in range(20):
                with write_lock(path):
                    pass
            self.assertLessEqual((path.parent / '.document.json.lock').stat().st_size, 1)

    @unittest.skipIf(os.name == 'nt', 'creating symlinks requires Windows privileges')
    def test_unsafe_companion_file_is_rejected_without_changing_its_target(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'document.json'
            target = Path(directory) / 'target'
            target.write_text('unchanged', encoding='utf-8')
            (path.parent / '.document.json.lock').symlink_to(target)
            with self.assertRaises(OSError):
                with write_lock(path):
                    path.write_text('must not write', encoding='utf-8')
            self.assertEqual(target.read_text(encoding='utf-8'), 'unchanged')
            self.assertFalse(path.exists())


if __name__ == '__main__':
    unittest.main()
