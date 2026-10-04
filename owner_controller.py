"""Native trusted controller: async deadline-bound actions, no public listener."""
import json
from pathlib import Path
import queue
import threading
import time
import tkinter as tk
from tkinter import messagebox, filedialog
from owner_broker import BrokerError
from owner_transport import remaining, ControlDeadline

class OwnerController:
    def __init__(self,broker,browser):
        self.broker=broker;self.browser=browser;self.window=None;self.action_busy=False;self.action_expired=False
    def open_or_recover(self,deadline=None):
        if self.browser.process and self.browser.process.poll() is not None:self.browser.acknowledge_exited_browser()
        return self.broker.recover_browser(**({'deadline':deadline} if deadline is not None else {}))
    def restart(self,drafts_closed=False,deadline=None):
        if drafts_closed is not True:raise BrokerError('explicit draft closure required')
        return self.broker.restart(drafts_closed=True,**({'deadline':deadline} if deadline is not None else {}))
    def stop(self,drafts_closed=False,deadline=None):
        if drafts_closed is not True:raise BrokerError('explicit draft closure required')
        if self.broker.child:
            if self.broker.child.poll() is None:self.broker.stop(drafts_closed=True,**({'deadline':deadline} if deadline is not None else {}))
            else:self.broker._terminate_own_child(deadline=deadline)
        self.browser.close(drafts_closed=True,allow_background_stop=True,**({'deadline':deadline} if deadline is not None else {}))
    def cli(self,resource,body=None,deadline=None):
        options={'deadline':deadline} if deadline is not None else {}
        if resource=='dashboard':return self.broker.run_cli('GET','/api/dashboard',**options)
        if resource=='manifest':return self.broker.run_cli('GET','/api/v1/manifest',**options)
        if resource=='report-run' and isinstance(body,dict):return self.broker.run_cli('POST','/api/runs/report',body,**options)
        raise BrokerError('unsupported explicit CLI request')
    def run(self,auto_open=False):
        window=tk.Tk();self.window=window
        window.title('Agent City owner controller');window.geometry('470x360')
        tk.Label(window,text="Control only this launcher's own server child.\nAuthority expires or is revoked; no saved recovery key.",justify='left').pack(padx=16,pady=12)
        status=tk.StringVar(value='Owned server ready.');self.status=status
        tk.Label(window,textvariable=status,wraplength=420).pack(padx=16,pady=8)
        buttons=[]
        def action(fn,success=None,budget=30):
            if self.action_busy:return
            self.action_busy=True;self.action_expired=False;deadline=time.monotonic()+budget;result=queue.Queue(maxsize=1);expired=False
            for button in buttons:button.config(state='disabled')
            status.set('Working on owned child...')
            def work():
                try:fn(deadline);remaining(deadline);result.put(True)
                except Exception:result.put(False)  # Generic outcome only; never log authority or payload.
            threading.Thread(target=work,daemon=True,name='owner-controller-action').start()
            def poll():
                nonlocal expired
                if not expired and time.monotonic()>=deadline:
                    expired=True;self.action_expired=True;self.broker._retire_channel()
                    status.set('Operation deadline reached. Authority revoked; wait for owned cleanup.')
                try:ok=result.get_nowait()
                except queue.Empty:window.after(25,poll);return
                self.action_busy=False
                for button in buttons:button.config(state='normal')
                if expired:status.set('Operation timed out. Review owned child/browser before retry.')
                elif ok:
                    status.set('Owned operation completed.')
                    if success:success()
                else:status.set('Operation refused. No authority details were logged. Review the owned child/browser.')
            window.after(25,poll)
        def button(label,command):
            item=tk.Button(window,text=label,command=command);item.pack(padx=16,pady=4,fill='x');buttons.append(item)
        button('Open / recover browser session',lambda:action(lambda deadline:self.open_or_recover(deadline=deadline)))
        button('Revoke browser and CLI authority',lambda:action(lambda deadline:self.broker.rpc('revoke',deadline=deadline)))
        button('CLI: read dashboard',lambda:action(lambda deadline:self.cli('dashboard',deadline=deadline)))
        def report():
            if self.action_busy:return
            name=filedialog.askopenfilename(parent=window,title='Choose explicit JSON run report',filetypes=[('JSON report','*.json')])
            if not name:return
            def send(deadline):
                remaining(deadline)
                with Path(name).open('rb') as stream:raw=stream.read(4097)
                if len(raw)>4096:raise BrokerError('report too large')
                self.cli('report-run',json.loads(raw),deadline=deadline)
            action(send)
        button('CLI: send selected run report',report)
        def restart():
            if self.action_busy:return
            if messagebox.askyesno('Owned restart','Are all browser drafts saved or closed? Restart only this owned server child?',parent=window):
                action(lambda deadline:self.restart(drafts_closed=True,deadline=deadline),budget=45)
        button('Restart owned child',restart)
        def close():
            if self.action_busy:
                if self.action_expired and messagebox.askyesno('Operation timed out','Authority was retired. Close only this controller and preserve the browser/profile for explicit review?',parent=window):window.destroy()
                return
            if messagebox.askyesno('Close owner controller','Are all drafts saved or closed? Stop only this owned server/browser, including its windowless background process?',parent=window):
                action(lambda deadline:self.stop(drafts_closed=True,deadline=deadline),success=window.destroy,budget=30)
        window.protocol('WM_DELETE_WINDOW',close)
        if auto_open:window.after(50,lambda:action(lambda deadline:self.open_or_recover(deadline=deadline)))
        window.mainloop()
