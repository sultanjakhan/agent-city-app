"""Deadline-bound writes to an inherited anonymous pipe, never a named listener."""
import os
import queue
import threading
import time

class ControlDeadline(TimeoutError):
    pass

def remaining(deadline):
    value=deadline-time.monotonic()
    if value<=0:raise ControlDeadline('owner operation deadline')
    return value

def write_pipe(stream,raw,deadline):
    remaining(deadline)
    if os.name!='nt':
        import select
        fd=os.dup(stream.fileno())
        try:
            os.set_blocking(fd,False);offset=0
            while offset<len(raw):
                if not select.select([], [fd], [], remaining(deadline))[1]:raise ControlDeadline('private pipe write deadline')
                try:offset+=os.write(fd,raw[offset:])
                except BlockingIOError:continue
        finally:os.close(fd)
        return
    # Anonymous Windows pipes are synchronous. Write on a cancellable *owned*
    # thread through a duplicated handle, not buffered Python write/flush locks.
    import ctypes
    from ctypes import wintypes
    import msvcrt
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.GetCurrentProcess.restype=wintypes.HANDLE
    kernel.DuplicateHandle.argtypes=[wintypes.HANDLE,wintypes.HANDLE,wintypes.HANDLE,ctypes.POINTER(wintypes.HANDLE),wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
    kernel.DuplicateHandle.restype=wintypes.BOOL
    kernel.OpenThread.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];kernel.OpenThread.restype=wintypes.HANDLE
    kernel.CancelSynchronousIo.argtypes=[wintypes.HANDLE];kernel.CancelSynchronousIo.restype=wintypes.BOOL
    kernel.WriteFile.argtypes=[wintypes.HANDLE,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(wintypes.DWORD),ctypes.c_void_p];kernel.WriteFile.restype=wintypes.BOOL
    kernel.CloseHandle.argtypes=[wintypes.HANDLE];kernel.CloseHandle.restype=wintypes.BOOL
    process=kernel.GetCurrentProcess();pipe=wintypes.HANDLE()
    if not kernel.DuplicateHandle(process,msvcrt.get_osfhandle(stream.fileno()),process,ctypes.byref(pipe),0,False,2):raise OSError('private pipe handle unavailable')
    result=queue.Queue(maxsize=1);state={'thread':None};lock=threading.Lock();cancelled=threading.Event();finished=threading.Event()
    def cancel():
        cancelled.set()
        def interrupt():
            # Retrying closes the race between cancellation and entering WriteFile.
            while not finished.is_set():
                with lock:
                    if state['thread']:kernel.CancelSynchronousIo(state['thread'])
                finished.wait(.01)
        threading.Thread(target=interrupt,daemon=True,name='owned-writer-cancellation').start()
    def write():
        try:
            handle=kernel.OpenThread(0x0001,False,threading.get_native_id())
            if not handle:raise OSError('owned writer unavailable')
            with lock:state['thread']=handle
            offset=0
            while offset<len(raw):
                if cancelled.is_set():raise ControlDeadline('private pipe write cancelled')
                # A cancellation racing before WriteFile is also caught by this
                # writer's deadline; main retires the channel regardless of result.
                remaining(deadline)
                block=ctypes.create_string_buffer(raw[offset:]);written=wintypes.DWORD()
                if not kernel.WriteFile(pipe,block,len(raw)-offset,ctypes.byref(written),None) or not written.value:raise OSError('private pipe write failed')
                offset+=written.value
            result.put(None)
        except (OSError,ControlDeadline):result.put(False)
        finally:
            kernel.CloseHandle(pipe)
            with lock:
                if state['thread']:kernel.CloseHandle(state['thread']);state['thread']=None
            finished.set()
    threading.Thread(target=write,daemon=True,name='owned-private-pipe-writer').start()
    try:value=result.get(timeout=remaining(deadline))
    except (queue.Empty,ControlDeadline):
        cancel();raise ControlDeadline('private pipe write deadline') from None
    if value is False:raise OSError('private pipe write failed')
    remaining(deadline)


def spawn_owned(command,deadline,**kwargs):
    """Bound the caller's wait; late creation is cleaned only by its own handle."""
    import subprocess
    result=queue.Queue(maxsize=1);lock=threading.Lock();state={'cancelled':False,'child':None,'cleanupStarted':False}
    def discard(child):
        with lock:
            if state["cleanupStarted"]:return
            state["cleanupStarted"]=True
        try:
            if child.poll() is None:child.terminate()
        except OSError:return
        try:child.wait(timeout=5)
        except subprocess.TimeoutExpired:return
        for stream in (child.stdin,child.stdout,child.stderr):
            if stream:stream.close()
    def create():
        try:
            child=subprocess.Popen(command,**kwargs)
            with lock:
                state['child']=child;cancelled=state['cancelled']
            if cancelled:discard(child)
            else:result.put(child)
        except (OSError, ValueError, subprocess.SubprocessError):
            # Validation and child setup failures must reach the waiting caller,
            # without an unhandled worker traceback containing private arguments.
            result.put(None)
    remaining(deadline)
    threading.Thread(target=create,daemon=True,name='owned-process-create').start()
    try:
        child=result.get(timeout=remaining(deadline));remaining(deadline)
    except (queue.Empty,ControlDeadline):
        with lock:state['cancelled']=True;late=state['child']
        if late:threading.Thread(target=discard,args=(late,),daemon=True,name='owned-late-child-cleanup').start()
        raise ControlDeadline('owned process creation deadline') from None
    if child is None:raise OSError('owned process creation failed')
    return child
