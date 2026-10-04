"""Exact-window helpers for the Agent City Chromium app window."""
from __future__ import annotations

from dataclasses import dataclass
import ctypes
from ctypes import wintypes
from pathlib import Path
import sys
import time

WINDOW_TITLE = "Agent City — модели"
WINDOW_TITLES = frozenset({WINDOW_TITLE, "Agent City — models"})
APP_EXECUTABLES = frozenset({"msedge.exe", "chrome.exe"})
APP_CLASS = "Chrome_WidgetWin_1"


@dataclass(frozen=True)
class WindowInfo:
    hwnd: int
    title: str
    executable: str
    class_name: str
    pid: int


def is_exact_window(window: WindowInfo, title: str | None = None, executables=APP_EXECUTABLES) -> bool:
    return (window.title in ({title} if title else WINDOW_TITLES) and window.executable.lower() in executables and window.class_name == APP_CLASS)


def _windows():
    if sys.platform != "win32":
        return None
    return ctypes.WinDLL("user32", use_last_error=True), ctypes.WinDLL("kernel32", use_last_error=True)


def enumerate_windows(title: str | None = None, executables=APP_EXECUTABLES, *, owned_pid=None, user32=None, kernel32=None):
    """Enumerate only visible top-level exact matches; no desktop screenshots or tab inspection."""
    libs = _windows() if user32 is None or kernel32 is None else (user32, kernel32)
    if libs is None:
        return []
    user32, kernel32 = libs
    found = []
    EnumProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [EnumProc, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    process_query_limited_information = 0x1000

    @EnumProc
    def callback(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        pid = wintypes.DWORD()
        if owned_pid is not None:
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value != owned_pid:return True
        length = user32.GetWindowTextLengthW(hwnd)
        title_buffer = ctypes.create_unicode_buffer(max(length + 1, 1))
        user32.GetWindowTextW(hwnd, title_buffer, len(title_buffer))
        observed = title_buffer.value
        if owned_pid is None and observed not in ({title} if title else WINDOW_TITLES):
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        handle = kernel32.OpenProcess(process_query_limited_information, False, pid.value)
        if not handle:
            return True
        try:
            size = wintypes.DWORD(32768)
            image = ctypes.create_unicode_buffer(size.value)
            if not kernel32.QueryFullProcessImageNameW(handle, 0, image, ctypes.byref(size)):
                return True
            executable = Path(image.value).name.lower()
            if executable not in executables:
                return True
            class_buffer = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, class_buffer, len(class_buffer))
            if owned_pid is None and class_buffer.value != APP_CLASS:
                return True
            found.append(WindowInfo(int(hwnd), observed, executable, class_buffer.value, int(pid.value)))
        finally:
            kernel32.CloseHandle(handle)
        return True

    user32.EnumWindows(callback, 0)
    return found


def focus_window(window: WindowInfo, *, title=None, user32=None):
    if user32 is None and not any(item == window for item in enumerate_windows(title=title)):
        return False
    libs = _windows() if user32 is None else (user32, None)
    if libs is None:
        return False
    user32 = libs[0]
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.ShowWindow.restype = wintypes.BOOL
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.SetForegroundWindow.restype = wintypes.BOOL
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.IsIconic.restype = wintypes.BOOL
    if user32.IsIconic(window.hwnd):
        user32.ShowWindow(window.hwnd, 9)  # Restore a minimized window; preserve maximized size.
    return bool(user32.SetForegroundWindow(window.hwnd))


def close_window(window: WindowInfo, *, title=None, owned_pid=None, user32=None):
    """Post WM_CLOSE only to a previously verified exact match."""
    if user32 is None and not any(item == window for item in enumerate_windows(title=title,owned_pid=owned_pid)):
        return False
    libs = _windows() if user32 is None else (user32, None)
    if libs is None:
        return False
    user32 = libs[0]
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.PostMessageW.restype = wintypes.BOOL
    return bool(user32.PostMessageW(window.hwnd, 0x0010, 0, 0))  # WM_CLOSE


def focus_existing(*, title: str | None = None, close_duplicates: bool = True, windows=None):
    matches = [x for x in (windows if windows is not None else enumerate_windows(title)) if is_exact_window(x, title)]
    if windows is None:
        current = {(x.hwnd, x.pid, x.title, x.executable, x.class_name) for x in enumerate_windows(title)}
        matches = [x for x in matches if (x.hwnd, x.pid, x.title, x.executable, x.class_name) in current]
    if not matches:
        return None
    focus_window(matches[0])
    if close_duplicates:
        for duplicate in matches[1:]:
            close_window(duplicate)
    return matches[0]


def wait_for_window(timeout: float = 10.0, interval: float = 0.1):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        match = focus_existing()
        if match is not None:
            return match
        time.sleep(interval)
    return None
