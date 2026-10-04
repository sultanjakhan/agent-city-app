"""Real Edge/Tk acceptance, synthetic profile/data and retained handles only."""
import ctypes,json,os,socket,sys,tempfile,time,subprocess
from pathlib import Path
from unittest.mock import patch
APP=Path(__file__).resolve().parents[1]
import argparse
parser=argparse.ArgumentParser();parser.add_argument('--output-dir',type=Path,required=True);options=parser.parse_args()
OUTPUT=options.output_dir.resolve()
if OUTPUT==APP or APP in OUTPUT.parents:raise SystemExit('QA output must be outside application')
OUTPUT.mkdir(parents=True,exist_ok=True)
sys.path.insert(0,str(APP))
import launch,app_window,owner_browser
from owner_browser import OwnedBrowser
real_spawn=owner_browser.spawn_owned
def accessible_spawn(command,deadline,**options):
    return real_spawn(command+["--force-renderer-accessibility"],deadline,**options)
from owner_controller import OwnerController
from owner_broker import BrokerError

result={'native':True,'checks':{},'status':'RUNNING','productionTouched':False}
temp=tempfile.TemporaryDirectory(prefix='agentcity-native-owner-');root=Path(temp.name)
pointer=root/'connection.local.json';pointer.write_text(json.dumps({'schemaVersion':1,'dataRoot':str(root/'private'),'codexHome':str(root/'codex'),'repositoryRoots':[str(root/'repos')],'skillInventoryRoots':[]}),encoding='utf8')
env={k:v for k,v in os.environ.items() if not k.startswith('AGENT_CITY_') and k!='CODEX_HOME' and not k.endswith('_API_KEY') and k not in {'HF_TOKEN','CLINE_API_KEY','OPENCODE_API_KEY'}}
env.update(AGENT_CITY_CONFIG=str(pointer),HOME=str(root/'home'),USERPROFILE=str(root/'home'),PYTHONDONTWRITEBYTECODE='1')
with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
result['isolatedPort']=port;browser=OwnedBrowser(launch.edge_path());broker=None;controller=None;phase=0;phase_started=time.monotonic();windows=[];old_epoch=None;old_profile=Path(browser.profile.name)

def save():(OUTPUT/'native-controller-oracle-result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
def matching():return [w for w in app_window.enumerate_windows(title=browser.title) if browser.process and w.pid==browser.process.pid]
def snapshot(window):
    script=Path(__file__).with_name('native_owner_ui.ps1')
    probe=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-File',str(script),'-Window',str(window.hwnd),'-OwnerPID',str(window.pid)],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=5,creationflags=subprocess.CREATE_NO_WINDOW)
    if probe.returncode:raise RuntimeError('owned native UIA unavailable')
    return json.loads(probe.stdout)
def invoke(label):
    buttons=[w for w in controller.window.winfo_children() if w.winfo_class()=='Button' and w.cget('text')==label]
    if len(buttons)!=1:raise RuntimeError('native controller button missing')
    buttons[0].invoke()
def fail(reason):
    result['status']='FAIL';result['blocker']=reason
    result['retainedBrowserAlive']=bool(browser.process and browser.process.poll() is None)
    result['knownTitleWindows']=sum(len(app_window.enumerate_windows(title=title)) for title in browser.titles)
    result['exactPidTitleWindows']=len(matching())
    if browser.process and browser.process.poll() is None:
        user32,kernel=app_window._windows();from ctypes import wintypes
        callback_type=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
        user32.GetWindowThreadProcessId.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.DWORD)]
        user32.GetWindowTextLengthW.argtypes=[wintypes.HWND];user32.GetWindowTextLengthW.restype=ctypes.c_int
        user32.GetWindowTextW.argtypes=[wintypes.HWND,wintypes.LPWSTR,ctypes.c_int]
        user32.IsWindowVisible.argtypes=[wintypes.HWND];user32.IsWindowVisible.restype=wintypes.BOOL
        categories=[]
        @callback_type
        def inspect(hwnd,_):
            pid=wintypes.DWORD();user32.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
            if pid.value==browser.process.pid and user32.IsWindowVisible(hwnd):
                size=user32.GetWindowTextLengthW(hwnd);text=ctypes.create_unicode_buffer(size+1);user32.GetWindowTextW(hwnd,text,len(text))
                categories.append('expected-owner-title' if text.value==browser.title else 'other-title')
            return True
        user32.EnumWindows.argtypes=[callback_type,wintypes.LPARAM];user32.EnumWindows(inspect,0)
        result['retainedPidVisibleWindowCategories']=categories
    finish()
def finish():
    global broker
    blocked_status=result["status"] if result["status"].startswith("BLOCKED_") else None
    try:
        if broker and broker.child:broker.stop(drafts_closed=True)
    except Exception:
        result['cleanupFallback']=True
        if broker and broker.child:broker._terminate_own_child()
    try:browser.close(drafts_closed=True,allow_background_stop=True,deadline=time.monotonic()+15)
    except Exception as error:
        result['status']='FAIL native graceful close';result['blocker']='native close '+type(error).__name__+((': '+str(error)) if isinstance(error,BrokerError) else '')
        result['checks']['nativeGracefulClose']=False;result['cleanupFallback']=True
        # This fixture contains no user drafts. Failure cleanup targets only
        # Popen handles it created with its own fresh synthetic profile.
        for child in browser.children:
            if child.poll() is None:child.terminate()
            child.wait(timeout=5)
        result['profileRetained']=True
        if browser.profile:browser.profile._finalizer.detach()
    result['checks']['profileRemoved']=not old_profile.exists()
    result['checks']['explicitBackgroundStopUsed']=browser.background_stopped
    if blocked_status:result['status']=blocked_status
    save()
    if controller and controller.window:controller.window.destroy()
def tick():
    global phase,phase_started,windows,old_epoch
    try:
        if time.monotonic()-phase_started>35:fail('native phase '+str(phase)+' timeout');return
        if controller.action_busy:controller.window.after(100,tick);return
        if phase==0:
            found=matching()
            if not found:controller.window.after(100,tick);return
            result['checks']['realEdgeExactPidTitle']=True;windows=found
            result['checks']['kernelDirectChildHandoff']=type(browser.process).__name__=='KernelProcess'
            visible=snapshot(found[0]);result['checks']['nativeAuthenticatedUIVisible']=visible['modelMenuVisible'] and not visible['authDialogVisible']
            result['uiaFirst']={key:visible[key] for key in ('controlCount','modelMenuVisible','authDialogVisible')}
            result['checks']['scopedCliThroughActualChild']=isinstance(controller.cli('dashboard'),dict)
            if not result['checks']['nativeAuthenticatedUIVisible']:
                result['status']='BLOCKED_NATIVE_DOM_OBSERVABILITY'
                result['blocker']='Exact retained Edge app window has no supported authenticated DOM observer; no auth/reload failure inferred'
                finish();return
            old_epoch=broker.epoch;invoke('Revoke browser and CLI authority');phase=1
        elif phase==1:
            invoke('Open / recover browser session');phase=2
        elif phase==2:
            found=matching()
            if len(found)<2:controller.window.after(100,tick);return
            result['checks']['realEdgeRecoverySecondOwnedWindow']=True
            result['status']='BLOCKED_NATIVE_RELOAD_ORACLE'
            result['blocker']='No supported fresh-document/reload-completion observer; UIA RuntimeId and posted F5 are not acceptance oracles'
            finish();return
        elif phase==3:
            if broker.epoch==old_epoch or not matching():controller.window.after(100,tick);return
            result['checks']['nativeRestartNewEpochAndWindow']=True
            result['checks']['scopedCliAfterRestart']=isinstance(controller.cli('dashboard'),dict)
            result['checks']['allOwnerWindowsRetainedPid']=all(w.pid==browser.process.pid for title in browser.titles for w in app_window.enumerate_windows(title=title))
            result['status']='RUNNING native close';phase=4
            controller.window.tk.call(controller.window.protocol('WM_DELETE_WINDOW'))
            if phase!=4:phase_started=time.monotonic()
        controller.window.after(100,tick);return
        if phase!=4:phase_started=time.monotonic()
        controller.window.after(100,tick)
    except Exception as error:
        if phase==0:
            result['status']='BLOCKED_NATIVE_OBSERVER_UNAVAILABLE';result['blocker']='Exact retained Edge app observer unavailable: '+type(error).__name__;finish()
        else:fail('native phase '+str(phase)+' '+type(error).__name__)
try:
    broker=launch.start_owned_broker(port,env,browser.open);broker.browser_deadline_open=browser.open
    controller=OwnerController(broker,browser)
    real_tk=__import__('tkinter').Tk
    def make_tk(*args,**kwargs):
        window=real_tk(*args,**kwargs);window.after(100,tick);return window
    with patch('owner_controller.tk.Tk',side_effect=make_tk),patch('owner_controller.messagebox.askyesno',return_value=True),patch('owner_browser.spawn_owned',side_effect=accessible_spawn):controller.run(auto_open=True)
    if result['status']=='RUNNING native close':
        result['checks']['nativeOwnedClose']=broker.child is None and browser.process is None
        result['checks']['profileRemoved']=not old_profile.exists()
        result['checks']['explicitBackgroundStopUsed']=browser.background_stopped
        result['status']='PASS scoped native open/recovery/restart/owned close' if result['checks']['nativeOwnedClose'] and result['checks']['profileRemoved'] else 'FAIL native owned close'
        save()
except Exception as error:
    result['status']='FAIL';result['blocker']='native initialization '+type(error).__name__;finish()
finally:
    if not result.get('profileRetained'):temp.cleanup()
    else:temp._finalizer.detach()
print(json.dumps({'status':result['status'],'checks':result['checks'],'blocker':result.get('blocker')}))
