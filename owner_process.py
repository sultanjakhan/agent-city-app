"""Retain an Edge direct-child handoff proven by kernel parent/birth metadata."""
import ctypes
from ctypes import wintypes
import os
import subprocess
import time
from owner_transport import remaining

class NativeOwnershipError(ValueError):pass

class KernelProcess:
    def __init__(self,handle,pid,kernel):self.handle=handle;self.pid=pid;self.kernel=kernel
    def poll(self):
        value=self.kernel.WaitForSingleObject(self.handle,0)
        if value==258:return None
        if value!=0:raise NativeOwnershipError('retained browser handle unavailable')
        code=wintypes.DWORD()
        if not self.kernel.GetExitCodeProcess(self.handle,ctypes.byref(code)):raise NativeOwnershipError('retained browser exit unavailable')
        return code.value
    def wait(self,timeout=None):
        millis=0xffffffff if timeout is None else max(0,min(0xfffffffe,int(timeout*1000)))
        value=self.kernel.WaitForSingleObject(self.handle,millis)
        if value==258:raise subprocess.TimeoutExpired('owned browser child',timeout)
        if value!=0:raise NativeOwnershipError('retained browser wait unavailable')
        return self.poll()
    def terminate(self):
        if self.poll() is None and not self.kernel.TerminateProcess(self.handle,1):raise NativeOwnershipError('retained browser termination refused')
    def close(self):
        if self.handle:self.kernel.CloseHandle(self.handle);self.handle=None


def retain_direct_child(root,pid):
    if os.name!='nt' or root.poll() is None or not hasattr(root,'_handle'):raise NativeOwnershipError('native handoff is unavailable')
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.GetProcessTimes.argtypes=[wintypes.HANDLE]+[ctypes.POINTER(wintypes.FILETIME)]*4;kernel.GetProcessTimes.restype=wintypes.BOOL
    kernel.CreateToolhelp32Snapshot.argtypes=[wintypes.DWORD,wintypes.DWORD];kernel.CreateToolhelp32Snapshot.restype=wintypes.HANDLE
    kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];kernel.OpenProcess.restype=wintypes.HANDLE
    kernel.CloseHandle.argtypes=[wintypes.HANDLE];kernel.CloseHandle.restype=wintypes.BOOL
    kernel.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD];kernel.WaitForSingleObject.restype=wintypes.DWORD
    kernel.GetExitCodeProcess.argtypes=[wintypes.HANDLE,ctypes.POINTER(wintypes.DWORD)];kernel.GetExitCodeProcess.restype=wintypes.BOOL
    kernel.TerminateProcess.argtypes=[wintypes.HANDLE,wintypes.UINT];kernel.TerminateProcess.restype=wintypes.BOOL
    def times(handle):
        created,exited,system,user=(wintypes.FILETIME() for _ in range(4))
        if not kernel.GetProcessTimes(handle,ctypes.byref(created),ctypes.byref(exited),ctypes.byref(system),ctypes.byref(user)):raise NativeOwnershipError('native birth metadata unavailable')
        convert=lambda value:(value.dwHighDateTime<<32)|value.dwLowDateTime
        return convert(created),convert(exited)
    root_created,root_exited=times(root._handle)
    if not root_exited:raise NativeOwnershipError('native root exit metadata unavailable')
    class Entry(ctypes.Structure):
        _fields_=[('dwSize',wintypes.DWORD),('cntUsage',wintypes.DWORD),('th32ProcessID',wintypes.DWORD),('th32DefaultHeapID',ctypes.c_size_t),('th32ModuleID',wintypes.DWORD),('cntThreads',wintypes.DWORD),('th32ParentProcessID',wintypes.DWORD),('pcPriClassBase',wintypes.LONG),('dwFlags',wintypes.DWORD),('szExeFile',wintypes.WCHAR*260)]
    kernel.Process32FirstW.argtypes=[wintypes.HANDLE,ctypes.POINTER(Entry)];kernel.Process32FirstW.restype=wintypes.BOOL
    kernel.Process32NextW.argtypes=[wintypes.HANDLE,ctypes.POINTER(Entry)];kernel.Process32NextW.restype=wintypes.BOOL
    snapshot=kernel.CreateToolhelp32Snapshot(2,0)
    if snapshot==ctypes.c_void_p(-1).value:raise NativeOwnershipError('native parent metadata unavailable')
    entry=Entry();entry.dwSize=ctypes.sizeof(entry);direct=False
    try:
        present=kernel.Process32FirstW(snapshot,ctypes.byref(entry))
        while present:
            if entry.th32ProcessID==pid:
                direct=entry.th32ParentProcessID==root.pid and entry.szExeFile.lower()=='msedge.exe';break
            present=kernel.Process32NextW(snapshot,ctypes.byref(entry))
    finally:kernel.CloseHandle(snapshot)
    if not direct:raise NativeOwnershipError('native browser is not a direct owned child')
    # Read/query, synchronization and terminate rights apply only to this verified
    # child. No ACL, token privilege, policy or process environment is changed.
    handle=kernel.OpenProcess(0x00101001,False,pid)
    if not handle:raise NativeOwnershipError('native browser child handle unavailable')
    try:
        created,_=times(handle)
        if not root_created<=created<=root_exited:raise NativeOwnershipError('native browser child birth mismatch')
        process=KernelProcess(handle,pid,kernel)
        if process.poll() is not None:raise NativeOwnershipError('native browser child already exited')
        return process
    except Exception:kernel.CloseHandle(handle);raise
