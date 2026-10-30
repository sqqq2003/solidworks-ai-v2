"""Tk panel sharing the tested repair service; imported without creating a UI."""
import json
import queue
import threading
import uuid
from pathlib import Path


class RepairPanel:
    def __init__(self,parent,project_root,demo=None):
        import tkinter as tk
        from tkinter import ttk,filedialog
        self.tk=tk;self.root=parent.winfo_toplevel();self.project_root=Path(project_root)
        self.frame=ttk.Frame(parent,padding=16)
        self.messages=queue.Queue();self.busy=False;self.smoke=None
        self.values={key:tk.StringVar() for key in ('source','specification','output','plan')}
        self.status=tk.StringVar(value='先选择来源模型和已测量的参数记录。')
        ttk.Label(self.frame,text='整机改型预检与试验',font=('Microsoft YaHei UI',16)).pack(anchor='w')
        ttk.Label(self.frame,text='来源模型只读；此处生成和核验试验计划。实际建模与生产验收另行执行。').pack(anchor='w',pady=8)
        form=ttk.Frame(self.frame);form.pack(fill='x')
        labels={'source':'来源模型（只读）','specification':'已测量参数记录 JSON','output':'新建试验输出目录','plan':'待核验的试验计划'}
        def choose(key):
            if key=='output':
                folder=filedialog.askdirectory(parent=self.root,title='选择试验输出父目录')
                value=str(Path(folder)/('trial-'+uuid.uuid4().hex[:10])) if folder else ''
            else:value=filedialog.askopenfilename(parent=self.root,title=labels[key])
            if value:self.values[key].set(value)
        for row,key in enumerate(self.values):
            ttk.Label(form,text=labels[key]).grid(row=row,column=0,sticky='w',pady=5)
            ttk.Entry(form,textvariable=self.values[key]).grid(row=row,column=1,sticky='ew',padx=8)
            ttk.Button(form,text='选择',command=lambda k=key:choose(k)).grid(row=row,column=2)
        form.columnconfigure(1,weight=1)
        actions=ttk.Frame(self.frame);actions.pack(fill='x',pady=12)
        self.prepare_button=ttk.Button(actions,text='生成改型试验计划',command=lambda:self.start('prepare'))
        self.prepare_button.pack(side='left',padx=4)
        self.validate_button=ttk.Button(actions,text='核验计划与模型一致',command=lambda:self.start('validate'))
        self.validate_button.pack(side='left',padx=4)
        self.log=tk.Text(self.frame,height=18,wrap='word');self.log.pack(fill='both',expand=True)
        ttk.Label(self.frame,textvariable=self.status,wraplength=980).pack(anchor='w',pady=8)
        if demo:
            try:
                data=json.loads(Path(demo).read_text(encoding='utf-8-sig'))
                if not isinstance(data,dict) or any(not isinstance(data.get(k),str) or not data[k].strip() for k in ('source','specification','output_root')):
                    raise ValueError('样件配置缺少来源、参数记录或输出目录。')
                for key in ('source','specification'):self.values[key].set(data[key])
                self.values['output'].set(str(Path(data['output_root'])/('trial-'+uuid.uuid4().hex[:10])))
            except (OSError,ValueError,TypeError) as error:
                self.status.set('样件配置未加载，请手动选择文件：'+str(error))
        self._poll_after=self.root.after(150,self.poll)
        def cleanup(event):
            if event.widget is self.frame and self._poll_after:
                try:self.root.after_cancel(self._poll_after)
                except tk.TclError:pass
                self._poll_after=None
        self.frame.bind('<Destroy>',cleanup,add='+')

    def start(self,operation):
        if self.busy:return
        values={k:v.get() for k,v in self.values.items()}
        needed=('source','specification','output') if operation=='prepare' else ('source','plan')
        if any(not values[k].strip() for k in needed):
            self.status.set('请先填写来源和本次操作所需的路径。');return
        self.busy=True
        for button in (self.prepare_button,self.validate_button):button.configure(state='disabled')
        self.status.set('正在核验来源、参数范围和试验状态…')
        def worker():
            try:
                from .repair_workbench import prepare_trial,validate_trial
                result=(prepare_trial(values['source'],values['specification'],values['output'])
                        if operation=='prepare' else validate_trial(values['source'],values['plan']))
                self.messages.put((operation,result,None))
            except Exception as error:self.messages.put((operation,None,str(error)))
        threading.Thread(target=worker,daemon=True).start()

    def poll(self):
        try:
            operation,result,error=self.messages.get_nowait();self.busy=False
            for button in (self.prepare_button,self.validate_button):button.configure(state='normal')
            self.log.insert('end',json.dumps(result or {'status':'failed','error':error},ensure_ascii=False,indent=2)+'\n');self.log.see('end')
            if error:self.status.set('本次未通过：'+error)
            elif operation=='prepare':
                self.values['plan'].set(result['plan'])
                self.status.set(f"试验计划：R{result['existing_radius_mm']:g} → R{result['target_radius_mm']:g} mm；状态 {result['status']}。未执行 CAD。")
            else:self.status.set('计划与当前来源一致，试验门槛核验通过。未执行 CAD。')
            if self.smoke:
                self.smoke['steps'].append({'button':operation,'result':result,'error':error})
                if operation=='prepare' and not error:self.root.after(50,self.validate_button.invoke)
                else:
                    report={'status':'pass' if not error and len(self.smoke['steps'])==2 else 'failed',
                            'method':'Tk button.invoke; real files and repair service',
                            'steps':self.smoke['steps'],'cad_executed':False,'production_approved':False}
                    path=self.smoke['report'];path.parent.mkdir(parents=True,exist_ok=True)
                    with path.open('x',encoding='utf-8') as stream:json.dump(report,stream,ensure_ascii=False,indent=2)
                    self.root.after(100,self.root.destroy)
        except queue.Empty:pass
        self._poll_after=self.root.after(150,self.poll)

    def start_smoke(self,report):
        if Path(report).exists():raise ValueError('smoke report already exists')
        if any(not self.values[k].get().strip() for k in ('source','specification','output')):
            raise ValueError('smoke test requires a complete valid demo configuration')
        self.smoke={'report':Path(report),'steps':[]}
        self.root.after(300,self.prepare_button.invoke)
