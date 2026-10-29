"""Small desktop panel over delivery APIs; no parallel CAD framework."""
import json
from pathlib import Path
import queue
import threading


def open_delivery(parent):
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
    from project_delivery import (read_json, prepare_workflow, workflow_status,
                                  approve_workflow, execute_workflow)
    from release_evidence import audit_submission, inspect_diagnostics
    from project_delivery import write_new
    win=tk.Toplevel(parent);win.title('项目交付与验收');win.geometry('860x720')
    win.configure(bg='#FFFFFF');win.columnconfigure(1,weight=1);win.rowconfigure(13,weight=1)
    values={name:tk.StringVar() for name in ('request','workspace','reviewer','review_sha256',
        'approval_sha256','sw_exe','matrix','submission','evidence_root','output')}
    state={'busy':False};events=queue.Queue();buttons=[]
    def choose(name,directory=False,new=False):
        options={'parent':win}
        path=(filedialog.askdirectory(**options) if directory else
              filedialog.asksaveasfilename(**options) if new else filedialog.askopenfilename(**options))
        if path:values[name].set(path)
    def row(index,name,label,**options):
        ttk.Label(win,text=label).grid(row=index,column=0,sticky='w',padx=16,pady=4)
        ttk.Entry(win,textvariable=values[name]).grid(row=index,column=1,sticky='ew',padx=6,pady=4)
        if options:
            ttk.Button(win,text='选择',command=lambda:choose(name,**options)).grid(row=index,column=2,padx=12)
    ttk.Label(win,text='方案 → 具名审核 → Windows 副本执行 → 证据核对',font=('',13,'bold')).grid(row=0,column=0,columnspan=3,sticky='w',padx=16,pady=16)
    for index,name,label,opts in [
        (1,'request','统一改型请求 JSON',{'new':False}),
        (2,'workspace','工作区（创建时须新路径）',{'new':True}),
        (3,'reviewer','审核人',{}),(4,'review_sha256','影响分析摘要',{}),
        (5,'approval_sha256','审核记录摘要',{}),(6,'sw_exe','SolidWorks 安装程序',{'new':False})]:row(index,name,label,**opts)
    actions=ttk.Frame(win);actions.grid(row=7,column=0,columnspan=3,sticky='ew',padx=16,pady=10)
    def invoke(call):
        if state['busy']:return
        state['busy']=True
        for button in buttons:button.configure(state='disabled')
        text.delete('1.0','end');text.insert('end','正在处理…\n')
        def worker():
            try:events.put((call(),None))
            except Exception as exc:events.put((None,str(exc)))
        threading.Thread(target=worker,daemon=True).start()
    def vals():return {k:v.get().strip() for k,v in values.items()}
    # Capture Tk values on the UI thread, before the worker starts.
    def action(frame,label,factory):
        item=ttk.Button(frame,text=label,command=lambda:invoke(factory(vals())));item.pack(side='left',padx=3);buttons.append(item)
    action(actions,'创建方案',lambda v:lambda:prepare_workflow(read_json(v['request']),v['workspace']))
    action(actions,'读取状态',lambda v:lambda:workflow_status(v['workspace']))
    action(actions,'记录审核',lambda v:lambda:approve_workflow(v['workspace'],reviewer=v['reviewer'],review_sha256=v['review_sha256']))
    action(actions,'Windows 执行 · 新副本',lambda v:lambda:execute_workflow(v['workspace'],sw_exe=v['sw_exe'],approval_sha256=v['approval_sha256']))
    for index,name,label,opts in [(8,'matrix','验收矩阵 JSON',{'new':False}),
        (9,'submission','回传记录 JSON / 诊断 ZIP',{'new':False}),
        (10,'evidence_root','证据文件目录',{'directory':True}),
        (11,'output','新报告目录 / 诊断 JSON',{'new':True})]:row(index,name,label,**opts)
    inbox=ttk.Frame(win);inbox.grid(row=12,column=0,columnspan=3,sticky='ew',padx=16,pady=8)
    def audit(v):
        def run():
            report=audit_submission(read_json(v['matrix']),read_json(v['submission']),v['evidence_root'])
            output=Path(v['output']);output.mkdir(parents=True,exist_ok=False)
            write_new(output/'audit.json',report);write_new(output/'repair-tasks.json',{'tasks':report['repair_tasks']})
            return report
        return run
    action(inbox,'核对回传与生成待办',audit)
    def diagnose(v):
        def run():
            report=inspect_diagnostics(v['submission']);write_new(v['output'],report);return report
        return run
    action(inbox,'读取诊断 ZIP',diagnose)
    text=tk.Text(win,wrap='word',relief='flat',bg='#F5F5F3');text.grid(row=13,column=0,columnspan=3,sticky='nsew',padx=16,pady=10)
    text.insert('end','当前执行入口支持已有滚筒模型改型。整机与二维建模继续使用原工作台入口。\n核对通过不代表工程或制造放行；缺映射、原件、实机证据时会保留待复核。\n')
    def poll():
        try:
            report,error=events.get_nowait();state['busy']=False
            for item in buttons:item.configure(state='normal')
            text.delete('1.0','end');text.insert('end',error if error else json.dumps(report,ensure_ascii=False,indent=2))
            if report:
                for name in ('review_sha256','approval_sha256'):
                    if report.get(name):values[name].set(report[name])
        except queue.Empty:pass
        state['poll']=win.after(100,poll)
    def close():
        if state['busy']:
            messagebox.showinfo('任务仍在运行','请等待任务结束，不会强制结束 CAD 进程。',parent=win);return
        win.after_cancel(state['poll']);win.destroy()
    win.protocol('WM_DELETE_WINDOW',close);state['poll']=win.after(100,poll)
    return win
