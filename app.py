"""SolidWorks AI project desktop workbench. Importing never creates a window."""
from pathlib import Path
import json
import queue
import sys
import threading

ROOT = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT),str(ROOT/'src')]


def main():
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
    from project_workbench import build_command, confirm_job, capabilities, doctor, run_batch, write_report
    root = tk.Tk()
    root.title('SolidWorks AI V2 — 项目工作台')
    root.geometry('1080x820')
    state = {'busy':False,'jobs':[]}
    messages = queue.Queue()
    stop = threading.Event()
    # t/R/angle/K 故意留空：每单必须由操作员显式填写，不许用上次的数或通用值悄悄顶替（2026-10-24 用户纠正）。空值提交时 float('') 报错，走现有的参数检查弹窗。
    values = {name:tk.StringVar(value=value) for name,value in {
        'kind':'sheet','machine':'QL-5050PX','ql_action':'plan','source':'','output':'','sw_exe':'','profile':'1','variant':'0',
        'thickness':'','radius':'','angle':'','k_factor':'',
        'length':'1800','width':'900','height':'1500'}.items()}
    confirmed, flip, inferred = tk.BooleanVar(), tk.BooleanVar(), tk.BooleanVar()
    for value in values.values():
        value.trace_add('write',lambda *args:confirmed.set(False))
    flip.trace_add('write',lambda *args:confirmed.set(False))
    inferred.trace_add('write',lambda *args:confirmed.set(False))
    tabs = ttk.Notebook(root)
    tabs.pack(fill='both',expand=True,padx=12,pady=10)
    jobs_tab, overview = ttk.Frame(tabs), ttk.Frame(tabs)
    tabs.add(jobs_tab,text='零件与整机参数')
    tabs.add(overview,text='项目状态 / 环境')
    form = ttk.LabelFrame(jobs_tab,text='工作副本与参数（钣金轮廓从 1 开始，滚筒/车件规格从 0 开始）')
    form.pack(fill='x',pady=6)
    modes = ttk.Combobox(form,textvariable=values['kind'],values=('sheet','roller','turned','parametric','ql5050px'),state='readonly')
    modes.grid(row=0,column=1,sticky='ew',padx=6,pady=3)
    ttk.Label(form,text='类型：钣金 / 滚筒 / 车件 / 整机参数').grid(row=0,column=0,sticky='w')
    def choose(key):
        if key == 'output' and values['kind'].get()=='ql5050px':
            parent = filedialog.askdirectory(title='选择父目录；将在其中新建 QL 输出目录')
            path = str(Path(parent)/'ql-output') if parent else ''
        elif key == 'output':
            path = filedialog.asksaveasfilename(defaultextension='.SLDPRT',filetypes=[('SolidWorks part','*.SLDPRT')])
        else:
            pattern = '*.exe' if key=='sw_exe' else ('*.json' if values['kind'].get()=='ql5050px' else '*.dxf *.dwg')
            path = filedialog.askopenfilename(filetypes=[('文件',pattern),('All','*.*')])
        if path:
            values[key].set(path)
    for row,(key,label) in enumerate((('source','二维图纸工作副本'),('output','新 SLDPRT 输出'),('sw_exe','已安装 SLDWORKS.exe')),start=1):
        ttk.Label(form,text=label).grid(row=row,column=0,sticky='w')
        ttk.Entry(form,textvariable=values[key]).grid(row=row,column=1,sticky='ew',padx=6,pady=3)
        ttk.Button(form,text='选择',command=lambda k=key:choose(k)).grid(row=row,column=2)
    numbers = ttk.Frame(form)
    numbers.grid(row=4,column=0,columnspan=3,sticky='ew',pady=8)
    for col,(key,label) in enumerate((('profile','轮廓'),('variant','规格'),('thickness','t mm'),('radius','R mm'),('angle','角度°'),('k_factor','K'))):
        ttk.Label(numbers,text=label).grid(row=0,column=col)
        ttk.Entry(numbers,textvariable=values[key],width=12).grid(row=1,column=col,padx=4)
    machine = ttk.Frame(form)
    machine.grid(row=5,column=0,columnspan=3,sticky='w',pady=4)
    ttk.Combobox(machine,textvariable=values['machine'],values=('QL-5050PX','GT-ZX'),state='readonly',width=14).grid(row=1,column=0,columnspan=2)
    ttk.Label(machine,text='QL 专用任务：选择 ql5050px 类型及 JSON 配置').grid(row=1,column=2,columnspan=4)
    ttk.Combobox(machine,textvariable=values['ql_action'],values=('plan','assembly','bom','drawing','pipeline','auto_assembly','drive','manufacturing','machine_package','intelligence','cad_features','integrated'),state='readonly',width=20).grid(row=2,column=0,columnspan=2)
    ttk.Label(machine,text='QL：装配计划 / 传动改型 / 制造图任务 / 统一交接包（离线）').grid(row=2,column=2,columnspan=4)
    for col,key in enumerate(('length','width','height')):
        ttk.Label(machine,text=key+' mm').grid(row=0,column=col*2)
        ttk.Entry(machine,textvariable=values[key],width=12).grid(row=0,column=col*2+1,padx=4)
    ttk.Checkbutton(form,text='反向折弯',variable=flip).grid(row=6,column=0,sticky='w')
    ttk.Checkbutton(form,text='已核对当前图纸、识别索引、尺寸和方向（原生生成必须）',variable=confirmed).grid(row=6,column=1,columnspan=2,sticky='w')
    ttk.Checkbutton(form,text='滚筒：明确允许通用默认尺寸（非 OEM 实测）',variable=inferred).grid(row=7,column=0,columnspan=3,sticky='w')
    form.columnconfigure(1,weight=1)
    controls = ttk.Frame(jobs_tab)
    controls.pack(fill='x',pady=6)
    table = ttk.Treeview(jobs_tab,columns=('kind','action','source'),show='headings',height=7)
    for key,label in (('kind','类型'),('action','操作 / 状态'),('source','图纸 / 项目')):
        table.heading(key,text=label)
    table.pack(fill='x')
    log = tk.Text(jobs_tab,height=15,wrap='word')
    log.pack(fill='both',expand=True,pady=8)
    status = tk.StringVar(value='准备就绪。云端模拟与 SolidWorks 实机验收分开记录。')
    ttk.Label(root,textvariable=status).pack(fill='x',padx=12,pady=4)
    def append(action):
        if state['busy']:
            return
        try:
            kind = values['kind'].get()
            if kind == 'parametric':
                job = {'kind':kind,'machine':values['machine'].get(),**{k:float(values[k].get()) for k in ('length','width','height')}}
            elif kind == 'ql5050px':
                job = {'kind':kind,'action':values['ql_action'].get(),'machine':'QL-5050PX',
                       'config':values['source'].get(),'name':'QL '+values['ql_action'].get()}
                if values['output'].get():
                    job['output_dir'] = values['output'].get()
            else:
                job = {'kind':kind,'action':action,'name':Path(values['source'].get()).name,
                    **{k:values[k].get() for k in ('source','output','sw_exe')},
                    **{k:float(values[k].get()) for k in ('thickness','radius','angle','k_factor')},
                    'profile':int(values['profile'].get()),'variant':int(values['variant'].get()),
                    'confirmed':confirmed.get(),'flip':flip.get(),'allow_inferred':inferred.get()}
            if kind in {'sheet','roller','turned'} and action == 'generate' and confirmed.get():
                job = confirm_job(job)
            build_command(job)
            if not state['jobs']:
                for item in table.get_children():
                    table.delete(item)
            state['jobs'].append(job)
            table.insert('', 'end', values=(kind,job.get('action','参数预检'),job.get('config',job.get('source','整机包络规划'))))
            status.set(f"已排队 {len(state['jobs'])} 项")
        except (OSError,ValueError,KeyError) as exc:
            messagebox.showerror('参数检查',str(exc))
    def run():
        if state['busy'] or not state['jobs']:
            return
        jobs = list(state['jobs'])
        state['busy'] = True
        stop.clear()
        status.set('串行执行中；停止排队会等待当前任务结束，不强制关闭 SolidWorks。')
        def worker():
            try:
                report = run_batch(jobs,stop_requested=stop.is_set)
                path = write_report(report,ROOT/'runtime/project-reports')
                messages.put((report,str(path)))
            except Exception as exc:
                messages.put(({'status':'failed','error':str(exc)},None))
        threading.Thread(target=worker,daemon=True).start()
    def poll():
        try:
            report,path = messages.get_nowait()
            log.insert('end',json.dumps(report,ensure_ascii=False,indent=2)+'\n')
            log.see('end')
            for item,row in zip(table.get_children(),report.get('results',[])):
                old = table.item(item,'values')
                table.item(item,values=(old[0],row['status'],old[2]))
            state['busy'] = False
            state['jobs'].clear()
            status.set(f"{report['status']}；报告：{path or '查看日志'}")
        except queue.Empty:
            pass
        root.after(150,poll)
    for label,command in (('加入识别',lambda:append('analyze')),('加入计划 / 参数预检',lambda:append('plan')),
        ('加入原生生成',lambda:append('generate')),('加入 QL 任务',lambda:append('plan')),('开始队列',run),('当前任务后停止',stop.set)):
        ttk.Button(controls,text=label,command=command).pack(side='left',padx=3)
    def clear():
        if not state['busy']:
            state['jobs'].clear()
            for item in table.get_children():
                table.delete(item)
    ttk.Button(controls,text='清空队列',command=clear).pack(side='left',padx=3)
    overview_text = tk.Text(overview,wrap='word')
    overview_text.pack(fill='both',expand=True)
    overview_text.insert('end',json.dumps({'environment':doctor(),'project':capabilities()},ensure_ascii=False,indent=2))
    overview_text.configure(state='disabled')
    def close():
        if state['busy']:
            stop.set()
            messagebox.showinfo('任务仍在执行','已停止后续排队。请等待当前任务结束再关闭窗口；不会强制结束 CAD 进程。')
        else:
            root.destroy()
    root.protocol('WM_DELETE_WINDOW',close)
    poll()
    root.mainloop()


if __name__ == '__main__':
    main()


