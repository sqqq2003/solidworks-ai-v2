"""Native batch review dialog, called from the existing project workbench."""
import json,threading
from pathlib import Path


def open_review(parent, state, messages, stop):
    from tkinter import Toplevel,StringVar,BooleanVar,Text,filedialog,messagebox
    from tkinter import ttk
    from .modeling_delivery import prepare_jobs
    if state['busy']:return
    win=Toplevel(parent);win.title('原生批处理：配方与本机绑定审核')
    fields={k:StringVar() for k in ('manifest','sw_exe','template','sketch_plane','output')}
    fields['sketch_plane'].set('Front Plane')
    approved=BooleanVar();resume=BooleanVar()
    for variable in fields.values():variable.trace_add('write',lambda *_:approved.set(False))
    for i,(key,label) in enumerate((('manifest','配方清单 JSON'),('sw_exe','SLDWORKS.exe'),('template','零件模板 PRTDOT'),('sketch_plane','模板草图基准面（需核对）'),('output','新输出目录 / 原批次目录'))):
        ttk.Label(win,text=label).grid(row=i,column=0,sticky='w')
        ttk.Entry(win,textvariable=fields[key],width=65).grid(row=i,column=1)
        def choose(k=key):
            value=filedialog.askdirectory(parent=win) if k=='output' else filedialog.askopenfilename(parent=win)
            if value:fields[k].set(value)
        if key!='sketch_plane':ttk.Button(win,text='选择',command=choose).grid(row=i,column=2)
    preview=Text(win,width=95,height=18);preview.grid(row=5,column=0,columnspan=3)
    prepared={'jobs':None,'digest':None}
    def inspect():
        try:
            request=json.loads(Path(fields['manifest'].get()).read_text(encoding='utf-8-sig'))
            jobs=prepare_jobs(request,sw_exe=fields['sw_exe'].get(),template=fields['template'].get() or None,
                sketch_plane=fields['sketch_plane'].get(),review=True)
            preview.delete('1.0','end');preview.insert('end',json.dumps(jobs,ensure_ascii=False,indent=2))
            prepared['jobs']=jobs;prepared['digest']={k:v.get() for k,v in fields.items()}
            approved.set(False)
        except Exception as exc:messagebox.showerror('审核失败',str(exc),parent=win)
    def start():
        if state['busy']:return
        if not approved.get() or prepared['jobs'] is None or prepared['digest']!={k:v.get() for k,v in fields.items()}:
            messagebox.showerror('未审核','先预检并确认当前参数、方向与本机绑定',parent=win);return
        output=Path(fields['output'].get()).expanduser().resolve()
        if output==Path.cwd() or not fields['output'].get():
            messagebox.showerror('输出目录','请指定独立批次目录',parent=win);return
        state['busy']=True;stop.clear();win.withdraw()
        # Capture Tk values on main thread before background work.
        selected_resume=resume.get()
        def safe_worker():
            try:
                from .modeling_supervisor import supervise
                report=supervise(prepared['jobs'],output,resume=selected_resume,stop_requested=stop.is_set)
                messages.put((report,str(output)))
            except Exception as exc:messages.put(({'status':'failed','error':str(exc)},None))
        threading.Thread(target=safe_worker,daemon=True).start()
        win.destroy()
    ttk.Button(win,text='预检并展开全部配方',command=inspect).grid(row=6,column=0)
    ttk.Checkbutton(win,text='确认尺寸、方向、模板和基准面；只在独立副本执行',variable=approved).grid(row=6,column=1)
    ttk.Checkbutton(win,text='断点续跑 / 重试失败项',variable=resume).grid(row=7,column=0)
    ttk.Button(win,text='串行执行原生批处理',command=start).grid(row=7,column=1)
