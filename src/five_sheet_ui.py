"""Nonblocking workbench entry for reviewed five-sheet presentation packs."""
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid


def launch_preview(project_root,manifest,output,*,resume=False):
    root=Path(project_root).resolve();manifest=Path(manifest).resolve(strict=True)
    output=Path(output).resolve()
    if not manifest.is_file():raise ValueError('工作包中没有五图分区清单。')
    if not resume and output.exists():raise ValueError('输出目录已存在，请选择新目录或恢复原任务。')
    folder=root/'runtime/five-sheet-launches';folder.mkdir(parents=True,exist_ok=True)
    log=folder/(uuid.uuid4().hex+'.log')
    command=[sys.executable,'-X','utf8',str(root/'work/generate_five_sheet_preview.py'),
             '--manifest',str(manifest),'--output',str(output)]
    if resume:command.append('--resume')
    with log.open('x',encoding='utf-8') as stream:
        process=subprocess.Popen(command,cwd=root,stdout=stream,stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    return process,log


def open_five_sheet_preview(parent,project_root,on_message):
    import tkinter as tk
    from tkinter import ttk,filedialog,messagebox
    win=tk.Toplevel(parent);win.title('五图版式预览');win.geometry('800x420')
    body=ttk.Frame(win,padding=20);body.pack(fill='both',expand=True)
    ttk.Label(body,text='生成钣金、方管、明细、总图和三视图预览',
              font=('Microsoft YaHei UI',13)).pack(anchor='w',pady=(0,14))
    pack=tk.StringVar();output=tk.StringVar();status=tk.StringVar(value='请选择已核对分区的五图工作包。')
    form=ttk.Frame(body);form.pack(fill='x');form.columnconfigure(1,weight=1)
    def choose_pack():
        value=filedialog.askdirectory(parent=win,title='选择五图工作包')
        if value:pack.set(value)
    def choose_output():
        value=filedialog.askdirectory(parent=win,title='选择输出位置')
        if value:output.set(str(Path(value)/('five-sheet-'+uuid.uuid4().hex[:8])))
    for row,(label,variable,choose) in enumerate((('五图工作包',pack,choose_pack),('新建输出目录',output,choose_output))):
        ttk.Label(form,text=label).grid(row=row,column=0,sticky='w',pady=8)
        ttk.Entry(form,textvariable=variable).grid(row=row,column=1,sticky='ew',padx=8)
        ttk.Button(form,text='选择',command=choose).grid(row=row,column=2)
    ttk.Label(body,text='输出DXF、PDF和图片。分区及原图变化时需重新核对；预览不代表加工批准。',wraplength=720).pack(anchor='w',pady=12)
    ttk.Label(body,textvariable=status,wraplength=720).pack(anchor='w',pady=6)
    active={'process':None}
    def begin(resume=False):
        if active['process'] is not None and active['process'].poll() is None:return
        try:
            if resume:
                directory=filedialog.askdirectory(parent=win,title='选择需要恢复的五图输出目录')
                if not directory:return
                state=json.loads((Path(directory)/'preview-state.json').read_text(encoding='utf-8'))
                manifest=Path(state['manifest']);output.set(directory);pack.set(str(manifest.parent))
            else:
                if not pack.get().strip() or not output.get().strip():
                    raise ValueError('请先选择工作包和输出位置。')
                manifest=Path(pack.get())/'five-sheet-preview.json'
            destination=output.get()
            process,log=launch_preview(project_root,manifest,destination,resume=resume)
            active['process']=process;status.set('正在生成预览，界面可继续使用。')
            on_message('五图版式任务已启动',destination)
            def poll():
                if not win.winfo_exists():return
                code=process.poll()
                if code is None:
                    win.after(350,poll);return
                try:state=json.loads((Path(destination)/'preview-state.json').read_text(encoding='utf-8'))
                except (OSError,ValueError):state={}
                if code==0 and state.get('status')=='completed_preview':
                    issues=[str(value)[:180] for value in state.get('issues',[])[:3]]
                    status.set('五图预览已生成，待工程复核。'+(' 待处理：'+'；'.join(issues) if issues else ''))
                    on_message('五图预览完成',destination)
                else:
                    detail=state.get('error','未取得完成记录，请查看任务日志。')
                    status.set('任务失败：'+detail+' 日志：'+str(log))
                    on_message('五图预览未完成',detail)
            win.after(350,poll)
        except (OSError,ValueError,KeyError,TypeError) as error:
            messagebox.showerror('无法开始五图预览',str(error),parent=win)
    bar=ttk.Frame(body);bar.pack(fill='x',pady=10)
    def open_output():
        path=Path(output.get()).resolve()
        if not output.get().strip() or not path.is_dir():
            messagebox.showerror('输出尚未生成','请选择已生成的输出目录。',parent=win);return
        os.startfile(str(path))
    ttk.Button(bar,text='恢复失败任务…',command=lambda:begin(True)).pack(side='left')
    ttk.Button(bar,text='打开输出目录',command=open_output).pack(side='left',padx=8)
    ttk.Button(bar,text='生成五图预览',command=begin).pack(side='right')
    return win
