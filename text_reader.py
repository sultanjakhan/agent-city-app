"""Read an opened text object within a pinned canonical local root."""
import os
from pathlib import Path


def canonical(path):
    value = os.path.normcase(str(Path(path).resolve(strict=True)))
    if os.name == 'nt' and value.startswith('\\\\?\\'):
        value = value[4:]
    return value


def handle_path(stream):
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        import msvcrt
        function = ctypes.WinDLL('kernel32', use_last_error=True).GetFinalPathNameByHandleW
        function.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
        function.restype = wintypes.DWORD
        buffer = ctypes.create_unicode_buffer(32768)
        length = function(msvcrt.get_osfhandle(stream.fileno()), buffer, len(buffer), 0)
        if not 0 < length < len(buffer):
            raise ValueError('opened path unavailable')
        return canonical(buffer.value)
    fd_path = Path('/proc/self/fd') / str(stream.fileno())
    if fd_path.exists():
        return canonical(fd_path)
    import fcntl
    return canonical(fcntl.fcntl(stream.fileno(), 50, b'\0' * 1024).split(b'\0', 1)[0].decode())


def read_text(path, root, max_size):
    pinned = os.path.normcase(str(Path(root).absolute()))
    if canonical(root) != pinned:
        raise ValueError('root redirected')
    expected = canonical(path)
    Path(expected).relative_to(Path(pinned))
    with Path(path).open('rb') as stream:
        opened = handle_path(stream)
        if opened != expected:
            raise ValueError('opened path changed')
        Path(opened).relative_to(Path(pinned))
        before = os.fstat(stream.fileno())
        if before.st_size > max_size or before.st_nlink > 1:
            raise ValueError('size or hardlink denied')
        raw = stream.read(max_size + 1)
        after = os.fstat(stream.fileno())
        if len(raw) > max_size or (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ValueError('file changed during read')
    text = raw.decode('utf-8-sig')
    if '\0' in text:
        raise ValueError('binary text denied')
    if canonical(root) != pinned:
        raise ValueError('root redirected')
    return raw, text, after


def slice_text(content, start, end, cap, offset=0):
    lines = content.splitlines(keepends=True)
    chosen = ''.join(lines[start - 1:end]).encode('utf-8')
    if not 0 <= offset <= len(chosen):
        raise ValueError('byte_offset_out_of_range')
    try:
        chosen[:offset].decode('utf-8')
    except UnicodeError:
        raise ValueError('byte_offset_not_character_boundary') from None
    text = chosen[offset:offset + cap].decode('utf-8', errors='ignore')
    next_offset = offset + len(text.encode('utf-8'))
    if next_offset == offset and offset < len(chosen):
        raise ValueError('maxBytes_too_small_for_character')
    truncated = next_offset < len(chosen)
    return {'content': text, 'startLine': start, 'endLine': min(end, len(lines)), 'totalLines': len(lines),
            'truncated': truncated, 'byteOffset': offset, 'nextByteOffset': next_offset if truncated else None,
            'continuation': {'startLine': start, 'endLine': end, 'byteOffset': next_offset} if truncated else None}
