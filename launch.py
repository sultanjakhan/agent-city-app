#!/usr/bin/env python3
"""Start the trusted controller of its own local-only Agent City child."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import ctypes
import json
import os
import secrets
from pathlib import Path
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import build_opener, ProxyHandler
urlopen = build_opener(ProxyHandler({})).open
import webbrowser

from app_window import focus_existing, wait_for_window
from server import APP_ID, ROOT, data_directory

MUTEX_NAME = "Local\\AgentCity-47831-singleton"
LOG_ROTATE_BYTES = 2 * 1024 * 1024


def open_server_log(directory: Path):
    """Keep startup failures across restarts; retain one previous log."""
    log = directory / "server.log"
    previous = directory / "server.log.1"
    if log.is_symlink() or previous.is_symlink():
        raise OSError("server log must not be a symbolic link")
    if log.exists() and log.stat().st_size >= LOG_ROTATE_BYTES:
        log.replace(previous)
    return log.open("a", encoding="utf-8")


def probe_server(url: str):
    """Return running/occupied/offline without mutating a port owner."""
    try:
        with urlopen(url + "/api/health", timeout=3) as response:
            body = json.loads(response.read(1024))
            return "running" if isinstance(body, dict) and body.get("appId") == APP_ID else "occupied"
    except HTTPError:
        return "occupied"
    except (json.JSONDecodeError, TypeError, ValueError):
        return "occupied"
    except URLError as exc:
        return "occupied" if isinstance(exc.reason, TimeoutError) else "offline"
    except (OSError, AttributeError):
        return "offline"


def running(url: str) -> bool:
    return probe_server(url) == "running"


@contextmanager
def launch_mutex(name: str = MUTEX_NAME):
    """Serialize concurrent launchers with a named Windows mutex."""
    if sys.platform != "win32":
        yield
        return
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    kernel.CreateMutexW.restype = ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel.WaitForSingleObject.restype = ctypes.c_uint32
    kernel.ReleaseMutex.argtypes = [ctypes.c_void_p]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.CreateMutexW(None, False, name)
    if not handle:
        raise OSError(ctypes.get_last_error(), "CreateMutexW failed")
    try:
        result = kernel.WaitForSingleObject(handle, 10000)
        if result not in (0x00000000, 0x00000080):
            raise TimeoutError("another Agent City launcher is still starting")
        yield
    finally:
        kernel.ReleaseMutex(handle)
        kernel.CloseHandle(handle)


def edge_path() -> Path:
    candidates = [
        Path(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)")) / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / "Microsoft/Edge/Application/msedge.exe",
    ]
    return next((path for path in candidates if path.is_file()), candidates[0])


def open_app(url: str):
    existing = focus_existing()
    if existing is not None and '#owner-bootstrap=' not in url:
        return existing
    if sys.platform == "win32":
        edge = edge_path()
        if edge.is_file():
            subprocess.Popen([str(edge), f"--app={url}", "--window-size=1220,860"],
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
            return wait_for_window()
    webbrowser.open(url)
    return None


def start_owned_broker(port,environment,browser_open):
    from owner_broker import OwnerBroker
    broker=OwnerBroker(ROOT,port,environment,browser_open)
    broker.start()
    return broker


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=47831)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--owner-broker", action="store_true",help="long-lived trusted controller for its own local-only child")
    parser.add_argument("--no-refresh", action="store_true", help="start without provider requests")
    parser.add_argument("--local-only", action="store_true", help="disable cloud and credential operations")
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    if sys.platform!="win32" and not args.no_browser:
        print("Native owner browser is not accepted on this platform; no server was started.",file=sys.stderr)
        return 4
    from owner_browser import OwnedBrowser
    from owner_controller import OwnerController
    from owner_broker import BrokerError
    browser=OwnedBrowser(edge_path())
    try:
        broker=start_owned_broker(args.port,dict(os.environ),browser.open)
    except (BrokerError,OSError,ValueError):
        browser.close(drafts_closed=True)
        print('Owned broker could not start its child; no existing server/window was reused.',file=sys.stderr)
        return 2
    broker.browser_deadline_open=browser.open
    controller=OwnerController(broker,browser)
    try:controller.run(auto_open=not args.no_browser)
    except Exception:  # Native failure is generic; retire private authority without exposing payloads.
        broker._retire_channel()
        print('Native owner controller unavailable; private authority retired. No foreign process was reused.',file=sys.stderr)
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
