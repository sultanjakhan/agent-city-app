"""Manual native acceptance on a new inactive desktop and synthetic profile only."""
import argparse,json,os,subprocess,sys,time,uuid
from pathlib import Path
import pywintypes,win32con,win32file,win32gui,win32job,win32process,win32service
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from agent_mcp import Bridge,invoke

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('exe','client','root'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();root=args.root.resolve()
    assert not root.exists()
    for key in ('APPDATA','LOCALAPPDATA'):
        if os.environ.get(key):assert not root.is_relative_to(Path(os.environ[key]).resolve())
    root.mkdir(parents=True)
    for name in ('panel','data','skills','repos','codex'): (root/name).mkdir()
    config=root/'connection.json'
    config.write_text(json.dumps(dict(schemaVersion=1,panelDirectory=str(root/'panel'),dataRoot=str(root/'data'),skillsDirectory=str(root/'skills'),codexHome=str(root/'codex'),repositoryRoots=[str(root/'repos')],skillInventoryRoots=[],cicadaSources=[])),encoding='utf-8')
    desktop_name='CityBackgroundQA-'+uuid.uuid4().hex
    desktop=win32service.CreateDesktop(desktop_name,0,win32con.GENERIC_ALL,None)
    job=win32job.CreateJobObject(None,'')
    limits=win32job.QueryInformationJobObject(job,win32job.JobObjectExtendedLimitInformation)
    limits['BasicLimitInformation']['LimitFlags']|=win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    win32job.SetInformationJobObject(job,win32job.JobObjectExtendedLimitInformation,limits)
    handles=[]
    env={k:v for k,v in os.environ.items() if not k.startswith('AGENT_CITY_') and not k.endswith('_API_KEY')}
    def launch(argv):
        attrs=pywintypes.SECURITY_ATTRIBUTES();attrs.bInheritHandle=True
        log=win32file.CreateFile(str(root/('process-'+str(len(handles))+'.log')),win32con.GENERIC_WRITE,win32con.FILE_SHARE_READ,attrs,win32con.CREATE_ALWAYS,0,None)
        inp=win32file.CreateFile('NUL',win32con.GENERIC_READ,win32con.FILE_SHARE_READ|win32con.FILE_SHARE_WRITE,attrs,win32con.OPEN_EXISTING,0,None)
        startup=win32process.STARTUPINFO();startup.lpDesktop='WinSta0\\'+desktop_name
        startup.dwFlags=win32con.STARTF_USESHOWWINDOW|win32con.STARTF_USESTDHANDLES;startup.wShowWindow=win32con.SW_SHOWNOACTIVATE
        startup.hStdOutput=startup.hStdError=log;startup.hStdInput=inp
        p,t,pid,_=win32process.CreateProcess(str(args.exe),subprocess.list2cmdline([str(args.exe),*argv]),None,None,True,win32con.CREATE_SUSPENDED|win32con.CREATE_UNICODE_ENVIRONMENT|win32con.CREATE_NO_WINDOW,env,str(args.exe.parent),startup)
        log.Close();inp.Close();win32job.AssignProcessToJobObject(job,p);win32process.ResumeThread(t);handles.extend([p,t]);return p,pid
    def finished(p,expected):
        import win32event
        assert win32event.WaitForSingleObject(p,10000)==win32con.WAIT_OBJECT_0
        assert win32process.GetExitCodeProcess(p)==expected
    try:
        argv=['--background','--local-only','--config',str(config)]
        first,pid=launch(argv);bridge=Bridge('agent-city',config,args.client)
        deadline=time.monotonic()+40
        while True:
            try:invoke('agent-city',bridge,'agent_city_read_shared_tasks',{});break
            except RuntimeError:
                assert win32process.GetExitCodeProcess(first)==win32con.STILL_ACTIVE
                if time.monotonic()>deadline:raise
                time.sleep(.2)
        def minimized():
            windows=[int(w) for w in desktop.EnumDesktopWindows() if win32process.GetWindowThreadProcessId(int(w))[1]==pid and win32gui.GetWindowText(int(w))=='Agent City']
            assert len(windows)==1
            assert win32gui.GetWindowPlacement(windows[0])[1]==win32con.SW_SHOWMINIMIZED
        minimized()
        repeated,_=launch(argv);finished(repeated,0);minimized()
        mismatch,_=launch(['--background','--config',str(config)]);finished(mismatch,3);minimized()
        invalid,_=launch(['--background','--config',str(root/'absent.json')]);finished(invalid,2)
        result={'nativeBackgroundStart':True,'minimized':True,'mcpReadSucceeded':True,'repeatedLaunchDidNotRestoreWindow':True,'modeMismatchRejectedWithoutDialog':True,'invalidProfileRejectedWithoutDialog':True,'syntheticOnly':True,'inactiveDesktop':True}
        (root/'acceptance.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result))
    finally:
        win32job.TerminateJobObject(job,0)
        for handle in handles:handle.Close()
        job.Close();desktop.CloseDesktop()

if __name__=='__main__':main()
