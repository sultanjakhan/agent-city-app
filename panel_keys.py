"""Small, Windows-user-bound credential store for Agent City.

Only the allowlisted environment variables and the per-user DPAPI files are
read.  Browser profiles, editor settings and other credential stores are out
of scope by design.
"""
from __future__ import annotations

import ctypes
import hashlib
import os
from pathlib import Path
import re
import sys
import tempfile
from ctypes import wintypes


class UIForbidden(PermissionError):
    """The requested DPAPI operation is unavailable on this platform."""


# Kept as a named exception for callers that must turn this into a UI error.
UI_FORBIDDEN = UIForbidden
_CRYPTPROTECT_UI_FORBIDDEN = 0x1

PROVIDERS = (
    "openrouter", "kilo", "cline", "zen", "gemini", "groq", "cerebras",
    "mistral", "siliconflow", "huggingface",
)
ENV_KEYS = {
    "huggingface": "HF_TOKEN",
    "openrouter": "OPENROUTER_API_KEY",
    "cline": "CLINE_API_KEY",
    "zen": "OPENCODE_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "groq": "GROQ_API_KEY",
    "cerebras": "CEREBRAS_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "siliconflow": "SILICONFLOW_API_KEY",
}

# This is the only filesystem root intended for test injection.
from storage_config import load_storage
SECRET_ROOT = load_storage().credentials
_KEY_RE = re.compile(r"^[\x21-\x7e]{20,2048}$")


class _Blob(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_byte))]


def _provider(provider: str) -> str:
    if not isinstance(provider, str) or provider not in PROVIDERS:
        raise ValueError("unsupported provider")
    return provider


def _path(provider: str) -> Path:
    return SECRET_ROOT / f"{_provider(provider)}.dpapi"


def _validate_key(key: str) -> None:
    if not isinstance(key, str) or not _KEY_RE.fullmatch(key):
        raise ValueError("key must be 20-2048 printable ASCII characters without whitespace")


def _crypt32():
    if sys.platform != "win32":
        raise UI_FORBIDDEN("DPAPI is available only on Windows")
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    for name in ("CryptProtectData", "CryptUnprotectData"):
        fn = getattr(crypt, name)
        fn.argtypes = [ctypes.POINTER(_Blob), ctypes.c_wchar_p, ctypes.c_void_p,
                       ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD,
                       ctypes.POINTER(_Blob)]
        fn.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    return crypt, kernel


def _protect(key: str) -> bytes:
    crypt, kernel = _crypt32()
    plain = bytearray(key.encode("utf-16-le"))
    plain_buffer = (ctypes.c_byte * len(plain)).from_buffer(plain)
    incoming = _Blob(len(plain), ctypes.cast(plain_buffer, ctypes.POINTER(ctypes.c_byte)))
    outgoing = _Blob()
    try:
        if not crypt.CryptProtectData(ctypes.byref(incoming), None, None, None, None, _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(outgoing)):
            raise OSError(ctypes.get_last_error(), "CryptProtectData failed")
        return bytes(ctypes.string_at(outgoing.data, outgoing.size))
    finally:
        if outgoing.data:
            ctypes.memset(outgoing.data, 0, outgoing.size)
            kernel.LocalFree(outgoing.data)
        ctypes.memset(plain_buffer, 0, len(plain))


def _unprotect(ciphertext: bytes) -> str:
    crypt, kernel = _crypt32()
    raw = bytearray(ciphertext)
    raw_buffer = (ctypes.c_byte * len(raw)).from_buffer(raw)
    incoming = _Blob(len(raw), ctypes.cast(raw_buffer, ctypes.POINTER(ctypes.c_byte)))
    outgoing = _Blob()
    try:
        if not crypt.CryptUnprotectData(ctypes.byref(incoming), None, None, None, None, _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(outgoing)):
            raise ValueError("credential unavailable for this OS user")
        decoded = bytearray(ctypes.string_at(outgoing.data, outgoing.size))
        try:
            return bytes(decoded).decode("utf-16-le")
        finally:
            for i in range(len(decoded)):
                decoded[i] = 0
    finally:
        if outgoing.data:
            ctypes.memset(outgoing.data, 0, outgoing.size)
            kernel.LocalFree(outgoing.data)
        ctypes.memset(raw_buffer, 0, len(raw))


def _environment(provider: str) -> str | None:
    name = ENV_KEYS.get(provider)
    return (os.environ.get(name) or None) if name else None


def read_key(provider: str) -> str | None:
    provider = _provider(provider)
    saved = _path(provider)
    if saved.is_file():
        try:
            ciphertext = bytes.fromhex(saved.read_text(encoding="utf-8-sig").strip())
            return _unprotect(ciphertext)
        except (OSError, ValueError, UnicodeError):
            # A corrupt/unavailable saved value must not hide an explicit env fallback.
            pass
    return _environment(provider)


def key_available(provider: str) -> bool:
    provider = _provider(provider)
    return provider == "kilo" or read_key(provider) is not None


def info(provider: str) -> dict[str, object]:
    provider = _provider(provider)
    if provider == "kilo":
        return {"available": True, "source": "anonymous", "removable": False, "canSave": False}
    saved = _path(provider).is_file()
    source = "none"
    if saved:
        try:
            _unprotect(bytes.fromhex(_path(provider).read_text(encoding="utf-8-sig").strip()))
            source = "saved"
        except (OSError, ValueError, UnicodeError):
            source = "environment" if _environment(provider) else "none"
    elif _environment(provider):
        source = "environment"
    return {"available": source != "none", "source": source,
            "removable": saved, "canSave": sys.platform == "win32", "unreadable": saved and source == "none"}


def revision(provider: str) -> str:
    provider = _provider(provider)
    path = _path(provider)
    if path.is_file():
        try:
            raw = path.read_bytes()
            _unprotect(bytes.fromhex(raw.decode("utf-8-sig").strip()))
            return hashlib.sha256(raw).hexdigest()
        except (OSError, ValueError, UnicodeError):
            pass
    value = _environment(provider)
    return hashlib.sha256(value.encode("utf-8")).hexdigest() if value else ""


def save_key(provider: str, key: str) -> None:
    provider = _provider(provider)
    if provider == "kilo":
        raise ValueError("kilo does not use an API key")
    _validate_key(key)
    encrypted = _protect(key)
    SECRET_ROOT.mkdir(parents=True, exist_ok=True)
    temp_name: str | None = None
    try:
        fd, temp_name = tempfile.mkstemp(prefix=f".{provider}-", suffix=".tmp", dir=str(SECRET_ROOT))
        with os.fdopen(fd, "w", encoding="ascii", newline="") as stream:
            stream.write(encrypted.hex())
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, _path(provider))
        temp_name = None
    finally:
        if temp_name:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass


def remove_key(provider: str) -> bool:
    provider = _provider(provider)
    if provider == "kilo":
        return False
    path = _path(provider)
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return False
