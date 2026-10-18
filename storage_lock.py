"""One writer for an Agent City panel, including the post-close migration CLI."""
import os
from pathlib import Path

class StorageLock:
    def __init__(self, directory):
        from storage_migration import safe_path
        directory = safe_path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / '.storage-writer.lock'
        if path.is_symlink() or (path.exists() and getattr(path.lstat(), 'st_file_attributes', 0) & 0x400):
            raise OSError('redirected writer lock')
        # Reject a redirect introduced between the check and open on POSIX.
        # Keep the same file: unlinking a lock can admit a second live writer.
        def open_lock(name, flags):
            return os.open(name, flags | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        self.stream = open(path, 'a+b', opener=open_lock)
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
