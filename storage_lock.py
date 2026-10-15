"""Panel ownership and serialized JSON read/modify/replace transactions."""
from contextlib import contextmanager
import os
from pathlib import Path
import stat
import threading


class StorageLock:
    def __init__(self, directory):
        from storage_migration import safe_path
        directory = safe_path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / '.storage-writer.lock'
        if path.exists() and (path.is_symlink() or getattr(path.lstat(), 'st_file_attributes', 0) & 0x400):
            raise OSError('redirected writer lock')
        self.stream = path.open('a+b')
        try:
            self.stream.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.stream.close()
            raise OSError('Agent City data is still in use') from None
    def __enter__(self): return self
    def __exit__(self, *_): self.stream.close()


_locks = {}
_guard = threading.Lock()


@contextmanager
def write_lock(path):
    # Lock a stable companion file: replacing the JSON file must not replace
    # the inode on which another process is waiting.
    path = Path(path)
    lock_path = path.parent.resolve() / ('.' + path.name + '.lock')
    with _guard:
        lock = _locks.setdefault(str(lock_path), threading.RLock())
    with lock:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        if lock_path.is_symlink():
            raise OSError('storage lock must be a regular file')
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        with os.fdopen(fd, 'r+b') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                raise OSError('storage lock must be a regular file')
            if os.name == 'nt':
                import msvcrt
                # Windows permits locking beyond EOF. Initializing a byte
                # before acquiring its lock races a process that locked it.
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX)
            try:
                yield
            finally:
                if os.name == 'nt':
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream, fcntl.LOCK_UN)
