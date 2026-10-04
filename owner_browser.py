"""Transient browser profile/window owned by this controller, never a title-only reuse."""
import os
import re
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit
import app_window
from owner_broker import BrokerError
from owner_transport import spawn_owned, remaining
from owner_process import retain_direct_child, NativeOwnershipError
from codex_controls import _reject_redirects, CodexControlsError

NATIVE_OPEN_SECONDS = 30  # Conservative cold private-profile launch/handoff budget.

class OwnedBrowser:
    def __init__(self,edge):
        self.edge=Path(edge);self.profile=tempfile.TemporaryDirectory(prefix='agentcity-owner-browser-')
        self.profile._finalizer.detach()  # Only explicit verified cleanup; never GC cleanup of an active browser.
        self.process=None;self.title=None;self.children=[];self.titles=set();self.launch_process=None;self.background_stopped=False
    def _profile_safe(self):
        if self.profile is None:return
        path=Path(self.profile.name)
        try:
            _reject_redirects(path)
            path.resolve().relative_to(Path(tempfile.gettempdir()).resolve())
            if not path.name.startswith('agentcity-owner-browser-'):raise ValueError()
        except (CodexControlsError,ValueError,OSError):
            # Preserve rejected metadata for explicit review; never let a finalizer
            # recursively remove a redirected browser profile later.
            self.profile._finalizer.detach()
            raise BrokerError('unsafe transient browser profile') from None
    def open(self,url,instance,deadline=None):
        deadline=deadline if deadline is not None else time.monotonic()+NATIVE_OPEN_SECONDS
        remaining(deadline)
        parsed=urlsplit(url)
        if parsed.scheme!='http' or parsed.hostname is None or not re.fullmatch(r'agent-city-[a-f0-9]{32}\.localhost',parsed.hostname) or not re.fullmatch(r'owner-bootstrap=[A-Za-z0-9_-]{43}',parsed.fragment):raise BrokerError('invalid browser handoff')
        self.title='Agent City ['+parsed.hostname+']';self.titles.add(self.title)
        if self.profile is None:
            self.profile=tempfile.TemporaryDirectory(prefix='agentcity-owner-browser-');self.profile._finalizer.detach()
        self._profile_safe()
        if self.process is not None and self.process.poll() is not None:raise BrokerError('owned browser exited; explicit controller recovery required')
        flags={'creationflags':subprocess.CREATE_NO_WINDOW} if sys.platform=='win32' else {'start_new_session':True}
        child=spawn_owned([str(self.edge),'--user-data-dir='+self.profile.name,'--no-first-run','--no-default-browser-check','--disable-background-mode','--disable-background-networking','--disable-sync','--app='+url,'--window-size=1220,860'],deadline,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,**flags)
        self.children.append(child)
        if self.process is None:self.process=child;self.launch_process=child
        self.confirm_native_window(deadline)
        return {'requested':True,'instance':instance}
    def confirm_native_window(self,deadline):
        while True:
            remaining(deadline)
            windows=app_window.enumerate_windows(title=self.title)
            if self.process and self.process.poll() is None and any(w.pid==self.process.pid for w in windows):return True
            if self.launch_process and self.launch_process.poll() is not None:
                candidates={w.pid for w in windows}
                if len(candidates)==1:
                    try:retained=retain_direct_child(self.launch_process,next(iter(candidates)))
                    except NativeOwnershipError:raise BrokerError('native browser handoff ownership refused') from None
                    self.process=retained;self.children.append(retained);return True
            time.sleep(min(.05,remaining(deadline)))

    def focus(self):
        if not self.process or self.process.poll() is not None:return False
        windows=[window for window in app_window.enumerate_windows(title=self.title) if window.pid==self.process.pid]
        return bool(windows) and app_window.focus_window(windows[0],title=self.title)
    def close(self,drafts_closed=False,deadline=None,allow_background_stop=False):
        deadline=deadline if deadline is not None else time.monotonic()+8
        if drafts_closed is not True:raise BrokerError('explicit draft closure required')
        retained=list(self.children)
        if self.process and self.process not in retained:retained.append(self.process)
        for child in retained:
            if child.poll() is None:
                for window in app_window.enumerate_windows(owned_pid=child.pid):
                    if window.pid==child.pid:app_window.close_window(window,title=window.title,owned_pid=child.pid)
                try:child.wait(timeout=min(5,remaining(deadline)))
                except subprocess.TimeoutExpired:
                    if not allow_background_stop or app_window.enumerate_windows(owned_pid=child.pid):
                        raise BrokerError('owned browser child still active; profile retained') from None
                    # Explicit controller close consent covers this retained,
                    # windowless process in its own transient profile only.
                    child.terminate();child.wait(timeout=remaining(deadline));self.background_stopped=True
        # Do not clean/reuse a profile if native ownership differs from our handles.
        for title in self.titles:
            if app_window.enumerate_windows(title=title):raise BrokerError('browser window still active; profile retained')
        self._profile_safe()
        if self.profile:self.profile.cleanup()
        self.profile=None;self.process=None;self.titles.clear();
        for child in self.children:
            if hasattr(child,"close"):child.close()
        self.children.clear();self.launch_process=None
    def acknowledge_exited_browser(self):
        if self.process and self.process.poll() is None:raise BrokerError('owned browser is still active')
        for child in self.children:
            if child.poll() is None:raise BrokerError('owned browser child still active')
        for title in self.titles:
            if app_window.enumerate_windows(title=title):raise BrokerError('browser window still active; profile retained')
        self.process=None
