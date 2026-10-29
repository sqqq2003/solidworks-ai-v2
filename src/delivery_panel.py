"""Tabbed desktop over the existing delivery APIs; callbacks capture values before threads."""
import json
from pathlib import Path
import queue
import threading

PHASES={'inputs_required':'需要补充模型或确认映射','review_required':'方案待工程审核',
        'review_recorded':'已记录审核，可按原流程执行副本',
        'revision_required':'工作区需要重新规划','invalid_workspace':'工作区记录不完整',
        'execution_review_required':'已有执行尝试，请先核对现场与证据',
        'execution_attempted_requires_review':'已有执行尝试，请先核对现场与证据',
        'ready_for_review':'工作区检查完成','source_installed_runtime_required':'源码已放入新目录，尚需配置运行环境'}
ISSUES={'revision_lineage_changed':'修订记录已变化，需要核对来源',
        'revision_lineage_missing':'修订记录缺失',
        'implementation_changed':'代码版本已变化，旧审核失效',
        'source_model_changed':'原模型已变化，需要重新核对尺寸与映射',
        'source_model_missing':'原模型无法读取','planning_file_changed':'方案文件已变化',
        'planning_file_missing':'方案文件缺失','input_confirmation_required':'模型或设计意图尚未确认',
        'execution_attempt_requires_independent_review':'保留执行现场，本工作区不会再次执行',
        'approval_invalid':'审核记录与当前方案不一致','manifest_invalid':'工作区记录已损坏'}


def summary(report):
    lines=[PHASES.get(report.get('phase'),{'passed':'文件完整性检查通过','failed':'处理未完成',
           'review_required':'已生成结果，仍需复核'}.get(report.get('status'),'处理完成'))]
    for issue in report.get('issues',[])[:6]:
        lines.append(ISSUES.get(issue.get('code'),issue.get('code','待复核')) if isinstance(issue,dict) else str(issue))
    if report.get('source_revision'):lines.append('源码版本：'+report['source_revision'][:12])
    if report.get('source_files'):lines.append('源码文件：'+str(report['source_files']))
    if report.get('app_directory'):lines.append('新源码目录：'+report['app_directory'])
    if report.get('counts'):lines.append('检查统计：'+json.dumps(report['counts'],ensure_ascii=False))
    if report.get('report_directory'):lines.append('报告目录：'+report['report_directory'])
    lines.append('文件核对不代表工程或制造验收。')
    return '\n'.join(lines)


def open_delivery(parent):
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
    from project_delivery import (read_json,prepare_workflow,workflow_status,approve_workflow,
        execute_workflow,inspect_workspace,revise_workflow,write_new)
    from release_evidence import audit_submission,inspect_diagnostics,save_audit,compare_audits
    from release_install import inspect_kit,install_kit
    win=tk.Toplevel(parent);win.title('项目交付与验收');win.geometry('900x790');win.minsize(760,680);win.configure(bg='#FFFFFF')
    style=ttk.Style(win);style.configure('Delivery.TEntry',padding=(6,2));style.configure('Delivery.TButton',padding=(9,4))
    style.configure('Delivery.TNotebook',background='#FFFFFF',borderwidth=0)
    win.columnconfigure(0,weight=1);win.rowconfigure(1,weight=1)
    ttk.Label(win,text='规划、审核和证据在同一工作区保存',font=('',14,'bold')).grid(row=0,column=0,sticky='w',padx=18,pady=14)
    book=ttk.Notebook(win,name='pages',style='Delivery.TNotebook');book.grid(row=1,column=0,sticky='nsew',padx=16)
    tabs={}
    for name,label in [('design','改型工作区'),('evidence','验收回传'),('candidate','候选包')]:
        frame=ttk.Frame(book,name=name,padding=8);frame.columnconfigure(1,weight=1);book.add(frame,text=label);tabs[name]=frame
    values={name:tk.StringVar() for name in ('request','workspace','revision_dir','reason','reviewer','review_sha256',
        'approval_sha256','sw_exe','matrix','submission','evidence_root','output','previous_report','kit','kit_sha256','install_dir')}
    state={'busy':False,'detail':False};events=queue.Queue();buttons=[]
    def choose(name,kind):
        call={'directory':filedialog.askdirectory,'new':filedialog.asksaveasfilename,'file':filedialog.askopenfilename}[kind]
        path=call(parent=win)
        if path:values[name].set(path)
    def row(frame,index,name,label,kind=None):
        ttk.Label(frame,text=label).grid(row=index,column=0,sticky='w',padx=4,pady=3)
        ttk.Entry(frame,name=name,textvariable=values[name],style='Delivery.TEntry').grid(row=index,column=1,sticky='ew',padx=5,pady=3)
        if kind:ttk.Button(frame,text='选择',style='Delivery.TButton',command=lambda:choose(name,kind)).grid(row=index,column=2,padx=4)
    def vals():return {k:v.get().strip() for k,v in values.items()}
    def invoke(call):
        if state['busy']:return
        state['busy']=True
        for button in buttons:button.configure(state='disabled')
        output.configure(state='normal');output.delete('1.0','end');output.insert('end','正在处理…');output.configure(state='disabled')
        def worker():
            try:events.put((call(),None))
            except Exception as exc:events.put((None,str(exc)))
        threading.Thread(target=worker,daemon=True).start()
    def action(frame,label,factory):
        item=ttk.Button(frame,text=label,style='Delivery.TButton',command=lambda:invoke(factory(vals())));item.pack(side='left',padx=3,pady=4);buttons.append(item)
    design=tabs['design']
    row(design,0,'request','改型请求 JSON','file');row(design,1,'workspace','当前工作区','directory')
    row(design,2,'revision_dir','新建 / 修订目录','new');row(design,3,'reason','修订原因')
    actions=ttk.Frame(design);actions.grid(row=4,column=0,columnspan=3,sticky='ew',pady=6)
    action(actions,'创建方案',lambda v:lambda:prepare_workflow(read_json(v['request']),v['revision_dir'] or v['workspace']))
    action(actions,'检查工作区',lambda v:lambda:inspect_workspace(v['workspace']))
    action(actions,'创建修订版',lambda v:lambda:revise_workflow(v['workspace'],read_json(v['request']),v['revision_dir'],reason=v['reason']))
    review=ttk.LabelFrame(design,text='具名审核与副本执行',padding=8);review.grid(row=5,column=0,columnspan=3,sticky='ew');review.columnconfigure(1,weight=1)
    for index,name,label,kind in [(0,'reviewer','审核人',None),(1,'review_sha256','影响分析摘要',None),
        (2,'approval_sha256','审核记录摘要',None),(3,'sw_exe','SolidWorks 程序','file')]:row(review,index,name,label,kind)
    controls=ttk.Frame(review);controls.grid(row=4,column=0,columnspan=3,sticky='ew')
    action(controls,'读取审核状态',lambda v:lambda:workflow_status(v['workspace']))
    action(controls,'记录审核',lambda v:lambda:approve_workflow(v['workspace'],reviewer=v['reviewer'],review_sha256=v['review_sha256']))
    action(controls,'Windows 执行 · 新副本',lambda v:lambda:execute_workflow(v['workspace'],sw_exe=v['sw_exe'],approval_sha256=v['approval_sha256']))
    evidence=tabs['evidence']
    for index,name,label,kind in [(0,'matrix','本轮验收矩阵','file'),(1,'submission','回传 JSON / 诊断 ZIP','file'),
        (2,'evidence_root','证据文件目录','directory'),(3,'previous_report','上一轮 audit.json（可选）','file'),
        (4,'output','新报告目录 / 诊断 JSON','new')]:row(evidence,index,name,label,kind)
    inbox=ttk.Frame(evidence);inbox.grid(row=5,column=0,columnspan=3,sticky='ew',pady=8)
    def audit(v):
        return lambda:save_audit(audit_submission(read_json(v['matrix']),read_json(v['submission']),v['evidence_root']),
                                v['output'],previous=read_json(v['previous_report']) if v['previous_report'] else None)
    action(inbox,'核对回传与生成待办',audit)
    def diagnose(v):
        def run():
            report=inspect_diagnostics(v['submission']);write_new(v['output'],report);return report
        return run
    action(inbox,'读取诊断 ZIP',diagnose)
    def compare(v):
        def run():
            report=compare_audits(read_json(v['previous_report']),read_json(v['submission']));write_new(v['output'],report);return report
        return run
    action(inbox,'比较两轮 audit.json',compare)
    candidate=tabs['candidate']
    row(candidate,0,'kit','源码交测包 ZIP','file');row(candidate,1,'kit_sha256','发布回执中的 ZIP SHA256')
    row(candidate,2,'install_dir','独立新目录','new')
    ttk.Label(candidate,text='先核对发布哈希，再解压源码到新目录。不会运行代码、安装依赖或替换旧程序。',wraplength=680).grid(row=3,column=0,columnspan=3,sticky='w',padx=4,pady=12)
    install=ttk.Frame(candidate);install.grid(row=4,column=0,columnspan=3,sticky='ew')
    action(install,'检查交测包',lambda v:lambda:inspect_kit(v['kit'],expected_sha256=v['kit_sha256'] or None))
    action(install,'解压到新目录',lambda v:lambda:install_kit(v['kit'],v['install_dir'],expected_sha256=v['kit_sha256']))
    output=tk.Text(win,name='summary',height=6,wrap='word',relief='flat',bg='#F5F5F3');output.grid(row=2,column=0,sticky='ew',padx=16,pady=8)
    output.insert('end','创建或选择工作区继续设计。执行前仍需真实模型、确认映射和工程审核。');output.configure(state='disabled')
    details=ttk.Frame(win);details.columnconfigure(0,weight=1)
    raw=tk.Text(details,height=6,wrap='word',relief='flat',state='disabled');raw.grid(row=0,column=0,sticky='ew')
    def toggle():
        state['detail']=not state['detail']
        if state['detail']:
            output.grid_remove();details.grid(row=2,column=0,sticky='ew',padx=16,pady=8)
        else:
            details.grid_remove();output.grid()
    ttk.Button(win,text='查看 / 收起完整记录',command=toggle).grid(row=3,column=0,sticky='w',padx=16,pady=3)
    def poll():
        try:
            report,error=events.get_nowait();state['busy']=False
            for item in buttons:item.configure(state='normal')
            output.configure(state='normal');output.delete('1.0','end');output.insert('end',error if error else summary(report));output.configure(state='disabled')
            raw.configure(state='normal');raw.delete('1.0','end');raw.insert('end',error if error else json.dumps(report,ensure_ascii=False,indent=2));raw.configure(state='disabled')
            if report:
                for name in ('review_sha256','approval_sha256'):
                    if report.get(name):values[name].set(report[name])
                if report.get('workspace'):values['workspace'].set(report['workspace'])
        except queue.Empty:pass
        state['poll']=win.after(100,poll)
    def close():
        if state['busy']:
            messagebox.showinfo('任务仍在运行','请等待任务结束，不会强制结束 CAD 进程。',parent=win);return
        win.after_cancel(state['poll']);win.destroy()
    win.protocol('WM_DELETE_WINDOW',close);state['poll']=win.after(100,poll)
    return win
