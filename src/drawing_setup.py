"""Small drawing setup dialog; no CAD launch until explicitly requested."""
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid


def drawing_defaults(stored=None,context=None,*,output_parent=None):
    """Reuse existing paths only; each launch always receives a fresh output."""
    stored=stored if isinstance(stored,dict) else {}
    context=context if isinstance(context,dict) else {}
    result=dict(models='',assembly='',sw_exe='')
    for key,suffixes in (('assembly',{'.sldasm','.sldprt'}),('sw_exe',{'.exe'})):
        for values in (context,stored):
            value=values.get(key)
            if not isinstance(value,str) or not value.strip():continue
            path=Path(value).expanduser()
            if path.is_file() and path.suffix.lower() in suffixes and (key!='sw_exe' or path.name.lower()=='sldworks.exe'):
                result[key]=str(path.resolve());break
    if result['assembly']:
        assembly=Path(result['assembly']);result['models']=str(assembly.parent)
        value=stored.get('models')
        if isinstance(value,str) and value and Path(value).is_dir() and assembly.is_relative_to(Path(value).resolve()):
            result['models']=str(Path(value).resolve())
    parent=output_parent
    if parent is None:
        value=stored.get('output_parent')
        parent=Path(value) if isinstance(value,str) and value and Path(value).is_dir() else Path.home()/'Desktop'/'text'/'出图测试'
    result['output']=str(Path(parent)/('drawing-'+uuid.uuid4().hex[:12]))
    return result


def detect_drawing_resources(executable,*,sheets=('A2',)):
    executable=Path(executable).expanduser().resolve()
    if not executable.is_file() or executable.name.casefold()!='sldworks.exe':
        raise ValueError('请选择此电脑已安装的 SLDWORKS.exe。')
    if not sheets or any(sheet not in {'A2','A3'} for sheet in sheets):raise ValueError('请选择 A2 或 A3 图幅。')
    templates={}
    program_data=Path(os.environ.get('PROGRAMDATA','C:/ProgramData'))/'SOLIDWORKS'
    preferred=None
    try:
        import win32api
        major=win32api.GetFileVersionInfo(str(executable),'\\')['FileVersionMS']>>16
        preferred=program_data/('SOLIDWORKS '+str(major+1992))/'templates'
    except ImportError:pass
    except OSError:pass
    for sheet in sheets:
        filename='gb_'+sheet.lower()+'.drwdot'
        exact=preferred/filename if preferred else None
        choices=list(program_data.glob('SOLIDWORKS */templates/'+filename)) if program_data.exists() else []
        if exact is not None and exact.is_file():chosen=exact
        elif len(choices)==1:chosen=choices[0]
        else:raise ValueError('未找到唯一且匹配本机版本的 '+sheet+' 图框，请配置对应模板。')
        templates[sheet]=str(chosen)
    bom=[executable.parent/'lang'/lang/'bom-standard.sldbomtbt' for lang in ('chinese-simplified','english')]
    if not templates or not any(p.is_file() for p in bom):
        raise ValueError('未找到 A2 图框或 BOM 模板，请先在 SolidWorks 中配置标准模板。')
    return templates,str(next(p for p in bom if p.is_file()))


def open_drawing_setup(parent,project_root,on_message,*,context=None):
    import tkinter as tk
    from tkinter import ttk,filedialog,messagebox
    from user_settings import load_settings,save_settings
    stored=load_settings().get('drawing');stored=stored if isinstance(stored,dict) else {}
    defaults=drawing_defaults(stored,context)
    root=Path(project_root);win=tk.Toplevel(parent);win.title('三视图 / BOM');win.geometry('760x510')
    body=ttk.Frame(win,padding=22);body.pack(fill='both',expand=True)
    ttk.Label(body,text='从零件或总装工作副本生成测试图纸',font=('Microsoft YaHei UI',15)).pack(anchor='w',pady=(0,12))
    fields={key:tk.StringVar(value=defaults[key]) for key in ('assembly','models','output','sw_exe')}
    labels={'models':'模型工作副本目录','assembly':'零件或总装文件','output':'新建输出目录','sw_exe':'SolidWorks 程序'}
    form=ttk.Frame(body);form.pack(fill='x');form.columnconfigure(1,weight=1)
    def choose(key):
        if key in ('models','output'):
            value=filedialog.askdirectory(parent=win)
            if value and key=='output':value=str(Path(value)/('drawing-'+uuid.uuid4().hex[:8]))
        else:value=filedialog.askopenfilename(parent=win,filetypes=[('SolidWorks 模型','*.sldasm *.sldprt')] if key=='assembly' else [('SolidWorks','SLDWORKS.exe')])
        if value:
            fields[key].set(value)
            if key=='assembly':fields['models'].set(str(Path(value).resolve().parent))
    for row,key in enumerate(fields):
        ttk.Label(form,text=labels[key]).grid(row=row,column=0,sticky='w',pady=6)
        ttk.Entry(form,textvariable=fields[key]).grid(row=row,column=1,sticky='ew',padx=8)
        ttk.Button(form,text='选择',command=lambda k=key:choose(k)).grid(row=row,column=2)
    paper=tk.StringVar(value=stored.get('sheet') if stored.get('sheet') in ('A2','A3') else 'A2')
    ratio=tk.StringVar(value=stored.get('scale') if stored.get('scale') in ('1:2','1:5','1:10','1:20') else '1:10')
    options=ttk.Frame(body);options.pack(fill='x',pady=8)
    ttk.Label(options,text='图幅').pack(side='left');ttk.Combobox(options,textvariable=paper,values=('A2','A3'),state='readonly',width=8).pack(side='left',padx=8)
    ttk.Label(options,text='比例').pack(side='left');ttk.Combobox(options,textvariable=ratio,values=('1:2','1:5','1:10','1:20'),state='readonly',width=8).pack(side='left',padx=8)
    ttk.Label(body,text='模型目录与新输出目录自动填写，程序路径可沿用上次设置。\n单件：三视图 + PDF；装配：另含顶层 BOM。保持所选比例，不自动缩小。\n当前为测试出图，尚未完成生产验收。原件只读；生成后需复核。').pack(anchor='w',pady=12)
    def start():
        try:
            values={k:v.get().strip() for k,v in fields.items()}
            if any(not v for v in values.values()):raise ValueError('请先选择模型、总装、输出目录和 SolidWorks。')
            models=Path(values['models']).resolve();assembly=Path(values['assembly']).resolve();output=Path(values['output']).resolve()
            if not assembly.is_file() or not assembly.is_relative_to(models):raise ValueError('总装必须位于所选工作副本目录内。')
            if output.exists():raise ValueError('输出目录已存在，请选择一个新目录。')
            from src.ql5050px.drawing_trial import validate_trial_case
            case=validate_trial_case({'sheet':paper.get(),'denominator':int(ratio.get().split(':')[1])})
            templates,bom=detect_drawing_resources(values['sw_exe'],sheets=(paper.get(),))
            folder=root/'runtime/drawing-launches';folder.mkdir(parents=True,exist_ok=True);token=uuid.uuid4().hex
            request=folder/(token+'.json')
            request.write_text(json.dumps(dict(models=str(models),assembly=str(assembly),output=str(output),sw_exe=values['sw_exe'],templates=templates,bom_template=bom,explicit_partial_model_test=True,cases=[case]),ensure_ascii=False,indent=2),encoding='utf-8')
            with (folder/(token+'.log')).open('x',encoding='utf-8') as stream:
                subprocess.Popen([sys.executable,'-X','utf8',str(root/'drawing_trial_app.py'),'--request',str(request)],cwd=root,stdout=stream,stderr=subprocess.STDOUT)
            settings=load_settings();settings['drawing']={**values,'output_parent':str(output.parent),'sheet':paper.get(),'scale':ratio.get()}
            save_settings(settings)
            on_message('出图准备完成','请在出图窗口核对总装、比例和测试确认，然后执行。')
            win.destroy()
        except (OSError,ValueError) as error:messagebox.showerror('请检查出图设置',str(error),parent=win)
    ttk.Button(body,text='进入出图核对',command=start).pack(anchor='e')
