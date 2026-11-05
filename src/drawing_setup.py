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
    for key,suffix in (('assembly','.sldasm'),('sw_exe','.exe')):
        for values in (context,stored):
            value=values.get(key)
            if not isinstance(value,str) or not value.strip():continue
            path=Path(value).expanduser()
            if path.is_file() and path.suffix.lower()==suffix and (key!='sw_exe' or path.name.lower()=='sldworks.exe'):
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


def detect_drawing_resources(executable):
    executable=Path(executable).expanduser().resolve()
    if not executable.is_file() or executable.name.casefold()!='sldworks.exe':
        raise ValueError('请选择此电脑已安装的 SLDWORKS.exe。')
    templates=[]
    program_data=Path(os.environ.get('PROGRAMDATA','C:/ProgramData'))/'SOLIDWORKS'
    if program_data.exists():templates=list(program_data.glob('SOLIDWORKS */templates/gb_a2.drwdot'))
    try:
        import win32api
        major=win32api.GetFileVersionInfo(str(executable),'\\')['FileVersionMS']>>16
        exact=program_data/('SOLIDWORKS '+str(major+1992))/'templates/gb_a2.drwdot'
        if exact.is_file():templates=[exact]
        elif len(templates)>1:raise ValueError('未找到与本机 SolidWorks 版本对应的 A2 模板。')
    except ImportError:pass
    except OSError:
        if len(templates)>1:raise ValueError('无法核实 SolidWorks 模板版本。')
    bom=[executable.parent/'lang'/lang/'bom-standard.sldbomtbt' for lang in ('chinese-simplified','english')]
    if not templates or not any(p.is_file() for p in bom):
        raise ValueError('未找到 A2 图框或 BOM 模板，请先在 SolidWorks 中配置标准模板。')
    return {'A2':str(sorted(templates)[-1])},str(next(p for p in bom if p.is_file()))


def open_drawing_setup(parent,project_root,on_message,*,context=None):
    import tkinter as tk
    from tkinter import ttk,filedialog,messagebox
    from user_settings import load_settings,save_settings
    defaults=drawing_defaults(load_settings().get('drawing'),context)
    root=Path(project_root);win=tk.Toplevel(parent);win.title('三视图 / BOM');win.geometry('760x450')
    body=ttk.Frame(win,padding=22);body.pack(fill='both',expand=True)
    ttk.Label(body,text='从总装工作副本生成测试图纸',font=('Microsoft YaHei UI',15)).pack(anchor='w',pady=(0,12))
    fields={key:tk.StringVar(value=defaults[key]) for key in ('assembly','models','output','sw_exe')}
    labels={'models':'模型工作副本目录','assembly':'总装文件','output':'新建输出目录','sw_exe':'SolidWorks 程序'}
    form=ttk.Frame(body);form.pack(fill='x');form.columnconfigure(1,weight=1)
    def choose(key):
        if key in ('models','output'):
            value=filedialog.askdirectory(parent=win)
            if value and key=='output':value=str(Path(value)/('drawing-'+uuid.uuid4().hex[:8]))
        else:value=filedialog.askopenfilename(parent=win,filetypes=[('总装','*.sldasm')] if key=='assembly' else [('SolidWorks','SLDWORKS.exe')])
        if value:
            fields[key].set(value)
            if key=='assembly':fields['models'].set(str(Path(value).resolve().parent))
    for row,key in enumerate(fields):
        ttk.Label(form,text=labels[key]).grid(row=row,column=0,sticky='w',pady=6)
        ttk.Entry(form,textvariable=fields[key]).grid(row=row,column=1,sticky='ew',padx=8)
        ttk.Button(form,text='选择',command=lambda k=key:choose(k)).grid(row=row,column=2)
    ttk.Label(body,text='选择总装后自动填写模型目录；输出目录自动新建，程序路径可沿用上次设置。\nA2 · 1:10 · 三视图 + 顶层 BOM + PDF\n当前为测试出图，尚未完成生产验收。原件只读；生成后需复核。').pack(anchor='w',pady=16)
    def start():
        try:
            values={k:v.get().strip() for k,v in fields.items()}
            if any(not v for v in values.values()):raise ValueError('请先选择模型、总装、输出目录和 SolidWorks。')
            models=Path(values['models']).resolve();assembly=Path(values['assembly']).resolve();output=Path(values['output']).resolve()
            if not assembly.is_file() or not assembly.is_relative_to(models):raise ValueError('总装必须位于所选工作副本目录内。')
            if output.exists():raise ValueError('输出目录已存在，请选择一个新目录。')
            templates,bom=detect_drawing_resources(values['sw_exe'])
            folder=root/'runtime/drawing-launches';folder.mkdir(parents=True,exist_ok=True);token=uuid.uuid4().hex
            request=folder/(token+'.json')
            request.write_text(json.dumps(dict(models=str(models),assembly=str(assembly),output=str(output),sw_exe=values['sw_exe'],templates=templates,bom_template=bom,explicit_partial_model_test=True,cases=[{'sheet':'A2','denominator':10}]),ensure_ascii=False,indent=2),encoding='utf-8')
            with (folder/(token+'.log')).open('x',encoding='utf-8') as stream:
                subprocess.Popen([sys.executable,'-X','utf8',str(root/'drawing_trial_app.py'),'--request',str(request)],cwd=root,stdout=stream,stderr=subprocess.STDOUT)
            settings=load_settings();settings['drawing']={**values,'output_parent':str(output.parent)}
            save_settings(settings)
            on_message('出图准备完成','请在出图窗口核对总装、比例和测试确认，然后执行。')
            win.destroy()
        except (OSError,ValueError) as error:messagebox.showerror('请检查出图设置',str(error),parent=win)
    ttk.Button(body,text='进入出图核对',command=start).pack(anchor='e')
