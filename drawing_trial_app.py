"""A single native drawing trial action; production export is not implied."""
import argparse,json,queue,subprocess,sys,threading
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent/'src'))


def run_trial_worker(command,log_path):
    """Always return a terminal outcome, including process/log creation errors."""
    try:
        with Path(log_path).open('x',encoding='utf-8') as stream:
            process=subprocess.Popen(command,stdout=stream,stderr=subprocess.STDOUT)
            code=process.wait();stream.flush()
            error=Path(log_path).read_text(encoding='utf-8',errors='replace')[-12000:] if code else None
            return code,error or None
    except OSError as error:return None,str(error)


def inspect_trial_result(code,target,worker_error=None):
    path=Path(target)/'result.json'
    failure={'drawing_generated':False,'message':'本次未通过，请查看失败原因。','result':str(path)}
    if worker_error:return dict(failure,error=worker_error)
    try:
        report=json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(report,dict) or not isinstance(report.get('cells'),list):raise ValueError('图纸结果格式无效')
        cells=report['cells']
        if any(not isinstance(cell,dict) for cell in cells):raise ValueError('图纸单元结果格式无效')
    except (OSError,ValueError) as error:return dict(failure,error=str(error))
    generated=code==0 and bool(cells) and all(c.get('status')=='pass_pending_visual' for c in cells)
    blocked=code==0 and bool(cells) and all(c.get('status')=='expected_layout_block' for c in cells)
    components=report.get('components')
    missing=sum(1 for item in components if isinstance(item,dict) and item.get('exists') is False) if isinstance(components,list) else None
    message=('生成完成（缺件测试），请目视审核。' if generated else
             '固定比例装不下，请选择更大图幅或明确修改比例。' if blocked else
             '本次未产生完整图纸，请查看结果中的失败原因。')
    if generated:
        message+=(' 检测到 '+str(missing)+' 个缺失组件引用。' if missing is not None else ' 缺失组件数量未核实。')
        message+=' 图纸及 BOM 未通过生产验收。'
    return {'drawing_generated':generated,'result':str(path),'error':report.get('error'),
            'traceback':report.get('traceback'),
            'missing_component_references':missing,'message':message}


def main():
    from app_logging import bootstrap,install_tk_hook
    journal=bootstrap(Path(__file__).resolve().parent,'drawing-ui')
    if sys.platform=='win32':
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('SolidWorksAI.DrawingTrial.1')
    import tkinter as tk
    from tkinter import ttk,filedialog
    p=argparse.ArgumentParser();p.add_argument('--request',type=Path,required=True);p.add_argument('--smoke-test',action='store_true');args=p.parse_args()
    request=json.loads(args.request.read_text(encoding='utf-8'))
    if not args.smoke_test:
        from datetime import datetime
        request['output']=str(Path(request['output']).parent/('interactive-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f')))
    root=tk.Tk();root.title('SolidWorks AI · 一键三视图/BOM（缺件测试）');root.geometry('900x460')
    install_tk_hook(root)
    body=ttk.Frame(root,padding=20);body.pack(fill='both',expand=True)
    ttk.Label(body,text='一键生成三视图、关联 BOM 与 PDF',font=('Microsoft YaHei UI',16)).pack(anchor='w')
    ttk.Label(body,text='测试模式：保留缺件说明；结果不用于生产。已有 SolidWorks 实例不自动关闭。').pack(anchor='w',pady=10)
    source=tk.StringVar(value=request['assembly']);output=tk.StringVar(value=request['output'])
    sheet=tk.StringVar(value='A2');scale=tk.StringVar(value='1:10');confirm=tk.BooleanVar(value=False)
    for label,var in [('隔离总装副本',source),('新输出目录',output)]:
        ttk.Label(body,text=label).pack(anchor='w');ttk.Entry(body,textvariable=var).pack(fill='x',pady=4)
    row=ttk.Frame(body);row.pack(fill='x',pady=8)
    ttk.Combobox(row,textvariable=sheet,values=['A2','A3'],state='readonly',width=12).pack(side='left')
    ttk.Combobox(row,textvariable=scale,values=['1:5','1:10','1:20'],state='readonly',width=12).pack(side='left',padx=10)
    ttk.Checkbutton(body,text='我确认这是缺件测试副本，允许生成测试图纸',variable=confirm).pack(anchor='w',pady=8)
    status=tk.StringVar(value='待确认');ttk.Label(body,textvariable=status,wraplength=840).pack(anchor='w',pady=10)
    messages=queue.Queue();state={'busy':False,'process':None,'poll_after':None,'result_dir':None}
    def cleanup_poll(event):
        if event.widget is root and state['poll_after']:
            try:root.after_cancel(state['poll_after'])
            except tk.TclError:pass
            state['poll_after']=None
    root.bind('<Destroy>',cleanup_poll,add='+')
    def start():
        if state['busy']:return
        if not confirm.get():status.set('请先勾选缺件测试确认。');return
        target=Path(output.get()).resolve()
        if target.exists():status.set('输出目录已存在，请选择新目录；不会覆盖旧成果。');return
        updated=dict(request,assembly=source.get(),output=str(target),explicit_partial_model_test=True,cases=[{'sheet':sheet.get(),'denominator':int(scale.get().split(':')[1])}])
        journal.record('drawing_started',assembly=source.get(),output=str(target),sheet=sheet.get(),scale=scale.get())
        request_path=args.request.parent/(target.name+'-request.json')
        request_path.write_text(json.dumps(updated,ensure_ascii=False,indent=2),encoding='utf-8')
        state['busy']=True;button.configure(state='disabled');status.set('正在生成：请等待原生校验、保存重开和 PDF 检查完成。')
        def worker():
            log=args.request.parent/(target.name+'-console.log')
            code,error=run_trial_worker([sys.executable,'-X','utf8',str(Path(__file__).parent/'work/drawing_trial.py'),'--request',str(request_path)],log)
            messages.put((code,target,error))
        threading.Thread(target=worker,daemon=True).start()
    button=ttk.Button(body,text='一键生成测试图纸',command=start);button.pack(anchor='w',pady=6)
    def open_results():
        if state['result_dir'] is not None:
            import os
            try:os.startfile(str(state['result_dir']))
            except OSError as error:status.set('无法打开结果文件夹：'+str(error))
    result_button=ttk.Button(body,text='打开结果文件夹',command=open_results,state='disabled');result_button.pack(anchor='w')
    def poll():
        try:
            code,target,worker_error=messages.get_nowait();state['busy']=False;button.configure(state='normal')
            report_path=target/'result.json'
            if target.is_dir():state['result_dir']=target;result_button.configure(state='normal')
            outcome=inspect_trial_result(code,target,worker_error);generated=outcome['drawing_generated']
            journal.record('drawing_finished',level='INFO' if generated else 'ERROR',exit_code=code,output=str(target),**outcome)
            status.set(outcome['message']+(' '+outcome['error'] if outcome.get('error') else '')+' 结果：'+str(report_path))
            evidence={'exit_code':code,'result':str(report_path),'button_executed':True,'drawing_generated':generated,'test_method':'tk_button_invoke' if args.smoke_test else 'interactive','production_approved':False}
            evidence['error']=outcome.get('error')
            (args.request.parent/(target.name+'-ui-result.json')).write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
            (args.request.parent/'ui-result.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
            if args.smoke_test:root.after(500,root.destroy)
        except queue.Empty:pass
        state['poll_after']=root.after(250,poll)
    def close():
        if state['busy']:status.set('任务仍在执行；为保留会话归属，本窗口将在任务结束后允许关闭。');return
        root.destroy()
    root.protocol('WM_DELETE_WINDOW',close)
    if args.smoke_test:
        if request.get('explicit_partial_model_test') is not True:raise ValueError('smoke test requires explicit trial request')
        def smoke():
            # Tk integration test invokes the same button/validation/worker path.
            confirm.set(True);button.invoke()
        root.after(500,smoke)
    poll();root.mainloop()

if __name__=='__main__':main()
