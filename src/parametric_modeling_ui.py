"""Parameter/functions, physical mapping and reviewed native execution workbench."""
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import queue
import sys
import threading
import uuid

from parametric_workspace import preview_parameters, save_parameter_workspace

ROOT=Path(__file__).resolve().parents[1]


class ParametricModelingWindow:
    def __init__(self,parent,on_message=None):
        import tkinter as tk
        from tkinter import ttk
        self.tk=tk;self.ttk=ttk;self.on_message=on_message
        self.preview_data=None;self.inspection=None;self.binding_rows={};self.review_data=None;self.workspace=None
        self.busy=False;self.generation=0;self.messages=queue.Queue();self.closed=False
        from app_logging import get_journal
        self.journal=get_journal()
        self.window=tk.Toplevel(parent);self.window.title('参数化建模');self.window.geometry('1060x800');self.window.minsize(850,660)
        self.window.protocol('WM_DELETE_WINDOW',self.close)
        self.window.bind('<Destroy>',self._destroyed,add='+')
        body=ttk.Frame(self.window,padding=16);body.pack(fill='both',expand=True)
        ttk.Label(body,text='参数化建模',font=('Microsoft YaHei UI',17)).pack(anchor='w')
        ttk.Label(body,text='参数与函数 → 模型绑定 → 变更审核 → 副本执行',foreground='#586675').pack(anchor='w',pady=(4,12))
        self.spec_path=tk.StringVar();self.rule_label=tk.StringVar(value='A01 参数规则 · 未绑定真实模型')
        rule=ttk.Frame(body);rule.pack(fill='x')
        ttk.Label(rule,textvariable=self.rule_label).pack(side='left',fill='x',expand=True)
        ttk.Button(rule,text='导入规则',command=self.choose_spec).pack(side='right')
        ttk.Button(rule,text='编辑函数',command=self.edit_rules).pack(side='right',padx=8)
        fields=ttk.Frame(body);fields.pack(fill='x',pady=12)
        self.values={key:tk.StringVar(value=value) for key,value in [('length','1800'),('width','900'),('height','1500')]}
        self.dimension_labels={}
        for column,(key,label) in enumerate([('length','目标长度'),('width','目标宽度'),('height','目标高度')]):
            self.dimension_labels[key]=ttk.Label(fields,text=label+' · mm');self.dimension_labels[key].grid(row=0,column=2*column,padx=(0,6))
            ttk.Entry(fields,textvariable=self.values[key],width=11).grid(row=0,column=2*column+1,padx=(0,18))
            self.values[key].trace_add('write',self.invalidate)
        self.extra_inputs=tk.StringVar(value='{}')
        extra=ttk.Frame(body);extra.pack(fill='x')
        ttk.Label(extra,text='额外输入 JSON').pack(side='left')
        ttk.Entry(extra,textvariable=self.extra_inputs).pack(side='left',fill='x',expand=True,padx=8)
        self.extra_inputs.trace_add('write',self.invalidate)
        actions=ttk.Frame(body);actions.pack(fill='x',pady=(10,8))
        self.preview_button=ttk.Button(actions,text='计算参数与依赖',command=self.calculate);self.preview_button.pack(side='left')
        self.save_button=ttk.Button(actions,text='导出方案',command=self.save,state='disabled');self.save_button.pack(side='left',padx=8)
        self.status=tk.StringVar(value='先计算参数，再读取模型尺寸或预览新零件特征计划。')
        ttk.Label(body,textvariable=self.status,wraplength=1000).pack(anchor='w',pady=(0,8))
        self.tabs=ttk.Notebook(body);self.tabs.pack(fill='both',expand=True)
        parameters=ttk.Frame(self.tabs,padding=8);bindings=ttk.Frame(self.tabs,padding=8);review=ttk.Frame(self.tabs,padding=8)
        self.tabs.add(parameters,text='参数与函数');self.tabs.add(bindings,text='模型与绑定');self.tabs.add(review,text='变更预览与执行')
        self.warning=tk.StringVar()
        ttk.Label(parameters,textvariable=self.warning,wraplength=950,foreground='#9A5200').pack(anchor='w',pady=(0,8))
        self.table=self._table(parameters,('parameter','value','unit','depends','confirmation'),
            [('parameter','参数',180),('value','目标值',100),('unit','单位',60),('depends','依赖 / 函数',350),('confirmation','状态',150)])
        self.sw_exe=tk.StringVar();self.source=tk.StringVar();self.configuration=tk.StringVar();self.template=tk.StringVar();self.output_parent=tk.StringVar()
        self.action_mode=tk.StringVar(value='修改已有零件');self.session_mode=tk.StringVar(value='auto')
        mode=ttk.Frame(bindings);mode.pack(fill='x')
        ttk.Label(mode,text='建模方式').pack(side='left')
        ttk.Combobox(mode,textvariable=self.action_mode,values=['修改已有零件','新建零件'],state='readonly',width=15).pack(side='left',padx=8)
        ttk.Label(mode,text='会话').pack(side='left',padx=(12,4))
        ttk.Combobox(mode,textvariable=self.session_mode,values=['auto','idle_existing','dedicated'],state='readonly',width=15).pack(side='left')
        self._path(bindings,'SolidWorks 程序',self.sw_exe,'exe')
        self._path(bindings,'工作目录（自动建新子目录）',self.output_parent,'directory')
        self._path(bindings,'已有零件 SLDPRT',self.source,'part')
        config=ttk.Frame(bindings);config.pack(fill='x',pady=3)
        ttk.Label(config,text='配置名称（须与模型一致）',width=29).pack(side='left')
        ttk.Entry(config,textvariable=self.configuration,width=25).pack(side='left')
        self.inspect_button=ttk.Button(config,text='读取模型尺寸',command=self.inspect_model);self.inspect_button.pack(side='right')
        self._path(bindings,'空白零件模板（新建用）',self.template,'template')
        binding_actions=ttk.Frame(bindings);binding_actions.pack(fill='x',pady=6)
        ttk.Button(binding_actions,text='添加 / 修改绑定',command=self.edit_binding).pack(side='left')
        ttk.Button(binding_actions,text='删除选中绑定',command=self.remove_binding).pack(side='left',padx=8)
        ttk.Button(binding_actions,text='导入绑定表',command=self.import_bindings).pack(side='left')
        self.binding_table=self._table(bindings,('parameter','dimension','role','range'),
            [('parameter','参数',150),('dimension','真实模型尺寸',350),('role','角色',90),('range','允许范围 mm',180)])
        self.binding_table.bind('<Double-1>',lambda _:self.edit_binding())
        ttk.Label(bindings,text='只写入已确认绑定。未绑定参数仅参与计算；auto 复用唯一空闲实例，无实例时自行打开。\n已有文档会保留并拒绝复用；dedicated 使用独立实例，不清空用户文件。',wraplength=950).pack(side='bottom',before=self.binding_table.master,anchor='w',pady=(6,0))
        toolbar=ttk.Frame(review);toolbar.pack(fill='x')
        self.prepare_button=ttk.Button(toolbar,text='生成变更预览',command=self.prepare);self.prepare_button.pack(side='left')
        self.reviewer=tk.StringVar();ttk.Label(toolbar,text='审核人').pack(side='left',padx=(16,4))
        ttk.Entry(toolbar,textvariable=self.reviewer,width=18).pack(side='left')
        self.review_confirmed=tk.BooleanVar(value=False)
        ttk.Checkbutton(review,text='已核对变更尺寸、范围及保护接口；仅对本次副本执行',variable=self.review_confirmed,command=self._buttons).pack(anchor='w',pady=8)
        self.execute_button=ttk.Button(review,text='审核并执行 SolidWorks 副本',command=self.execute,state='disabled');self.execute_button.pack(anchor='w')
        self.review_text=tk.Text(review,wrap='word',height=15,font=('Consolas',10),state='disabled');self.review_text.pack(fill='both',expand=True,pady=8)
        ttk.Label(body,text='数值与特征读回进入待审核；装配联动、工程图和制造验收需另行核对。',foreground='#586675').pack(side='bottom',before=self.tabs,anchor='w',pady=(10,0))
        for variable in (self.source,self.configuration):variable.trace_add('write',self._source_changed)
        for variable in (self.action_mode,self.template):variable.trace_add('write',self.invalidate)
        self.session_mode.trace_add('write',self._clear_review)
        self.reviewer.trace_add('write',lambda *_:self._buttons())
        self._apply_style()
        self._poll_id=self.window.after(80,self._poll)

    def _apply_style(self):
        from desktop_ui import WHITE,INK,LINE,NAV
        style=self.ttk.Style(self.window);self.window.configure(bg=WHITE)
        for kind in ('TFrame','TLabel','TCheckbutton','TNotebook'):
            style.configure('Parameter.'+kind,background=WHITE,foreground=INK)
        style.configure('Parameter.TButton',padding=(10,6))
        style.configure('Parameter.TNotebook.Tab',padding=(16,9),background=NAV)
        style.map('Parameter.TNotebook.Tab',background=[('selected',WHITE)])
        style.configure('Parameter.Treeview',background=WHITE,fieldbackground=WHITE,rowheight=29,borderwidth=0)
        style.configure('Parameter.Treeview.Heading',background=NAV,foreground=INK,padding=(6,8))
        def apply(widget):
            kind=widget.winfo_class()
            if kind in {'TFrame','TLabel','TCheckbutton','TNotebook','TButton','Treeview'}:
                widget.configure(style='Parameter.'+kind)
            for child in widget.winfo_children():apply(child)
        apply(self.window)
        self.table.column('value',anchor='e');self.table.column('unit',anchor='center')

    def _table(self,parent,columns,labels):
        frame=self.ttk.Frame(parent);frame.pack(fill='both',expand=True)
        table=self.ttk.Treeview(frame,columns=columns,show='headings',height=5)
        for key,label,width in labels:table.heading(key,text=label);table.column(key,width=width,minwidth=50)
        scroll=self.ttk.Scrollbar(frame,orient='vertical',command=table.yview)
        table.configure(yscrollcommand=scroll.set);scroll.pack(side='right',fill='y');table.pack(fill='both',expand=True)
        return table

    def _path(self,parent,label,variable,kind):
        row=self.ttk.Frame(parent);row.pack(fill='x',pady=3)
        self.ttk.Label(row,text=label,width=29).pack(side='left')
        self.ttk.Entry(row,textvariable=variable).pack(side='left',fill='x',expand=True)
        def choose():
            from tkinter import filedialog
            if kind=='directory':path=filedialog.askdirectory(parent=self.window)
            else:path=filedialog.askopenfilename(parent=self.window,filetypes=[('文件',{'exe':'*.exe','part':'*.sldprt *.SLDPRT','template':'*.prtdot *.PRTDOT'}[kind])])
            if path:variable.set(path)
        self.ttk.Button(row,text='选择',command=choose).pack(side='right',padx=(6,0))

    def _clear_review(self,*_):
        self.review_data=None;self.workspace=None;self.review_confirmed.set(False);self.generation+=1
        self._buttons()

    def invalidate(self,*_):
        self.preview_data=None
        if hasattr(self,'review_confirmed'):self._clear_review()
        else:self.generation+=1
        if hasattr(self,'save_button'):self.save_button.configure(state='disabled');self.status.set('参数已变化，请重新计算。')

    def _source_changed(self,*_):
        self.inspection=None;self.binding_rows.clear()
        self.refresh_bindings();self._clear_review()

    def _buttons(self):
        if not hasattr(self,'execute_button'):return
        self.execute_button.configure(state='normal' if not self.busy and self.review_data and self.review_confirmed.get() and self.reviewer.get().strip() else 'disabled')
        for name in ('preview_button','inspect_button','prepare_button'):
            getattr(self,name).configure(state='disabled' if self.busy else 'normal')

    def choose_spec(self):
        from tkinter import filedialog
        path=filedialog.askopenfilename(parent=self.window,title='选择机型 / 函数规则',filetypes=[('规则','*.json *.yaml *.yml')])
        if path:self.load_spec(path)

    def load_spec(self,path):
        self.spec_path.set(str(path));self.rule_label.set(Path(path).name);self.invalidate()
        self.journal.record('parametric_rule_selected',path=str(path))

    def edit_rules(self):
        from tkinter import filedialog,messagebox
        from drawing_review import atomic_json
        try:
            path=Path(self.spec_path.get()) if self.spec_path.get() else ROOT/'examples/function-block.json'
            if path.suffix.lower() in {'.yaml','.yml'}:
                import yaml
                value=yaml.safe_load(path.read_text(encoding='utf-8-sig'))
            else:value=json.loads(path.read_text(encoding='utf-8-sig'))
        except Exception as error:self._error(error);return
        dialog=self.tk.Toplevel(self.window);dialog.title('编辑参数与函数规则');dialog.geometry('850x620')
        self.ttk.Label(dialog,text='支持 + − × ÷、有限整数幂及 min/max/abs/sqrt/ceil/floor/round/sin/cos/tan；带单位检查。保存为新规则文件。',wraplength=800).pack(padx=12,pady=10)
        text=self.tk.Text(dialog,wrap='none',font=('Consolas',11));text.pack(fill='both',expand=True,padx=12);text.insert('1.0',json.dumps(value,ensure_ascii=False,indent=2))
        def save():
            try:
                from parametric_functions import solve_functions
                content=json.loads(text.get('1.0','end'))
                if content.get('kind')=='parametric_functions':solve_functions(content)
                target=filedialog.asksaveasfilename(parent=dialog,title='保存为新的规则 JSON',defaultextension='.json')
                if not target:return
                atomic_json(target,content,exclusive=True);self.load_spec(target);dialog.destroy()
            except Exception as error:messagebox.showerror('规则未保存',str(error),parent=dialog)
        self.ttk.Button(dialog,text='保存规则副本',command=save).pack(pady=10)

    def calculate(self):
        self.invalidate()
        try:
            extra=json.loads(self.extra_inputs.get())
            if not isinstance(extra,dict):raise ValueError('额外输入需要 JSON 对象')
            result=preview_parameters(**{k:v.get() for k,v in self.values.items()},spec_path=self.spec_path.get() or None,input_values=extra)
        except Exception as error:self._error(error);return
        self.preview_data=result;self.table.delete(*self.table.get_children())
        plan=result['plan']
        self.dimension_labels['width'].configure(text='目标内档W · mm' if plan['machine_id']=='roller_frame' else '目标宽度 · mm')
        self.dimension_labels['height'].configure(text='侧板+支腿H · mm' if plan['machine_id']=='roller_frame' else '目标高度 · mm')
        self.warning.set('\n'.join(plan.get('warnings',[])+[c.get('message',str(c)) for c in plan.get('conflicts',[])]))
        for name,row in plan['parameter_register'].items():
            value=plan['values_mm'].get(name)
            self.table.insert('', 'end',values=(name,'待确认' if value is None else f'{value:g}',row.get('unit','mm'),row.get('expression') or ', '.join(row.get('depends_on',[])), '待模型绑定'))
        self.status.set(f"参数已计算 · {len(plan['unresolved'])} 项缺少输入 / 来源 · 尚未执行模型")
        self.save_button.configure(state='normal');self.journal.record('parametric_preview_completed',review_sha256=result['review_sha256'])

    def _new_output(self,label):
        if not self.output_parent.get().strip():raise ValueError('请先选择工作目录')
        parent=Path(self.output_parent.get()).expanduser().resolve(strict=True)
        if not parent.is_dir():raise ValueError('工作目录必须是文件夹')
        return parent/(label+'-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8])

    def _run(self,label,job,done):
        if self.busy:return
        self.busy=True;token=self.generation;self.status.set(label+'…');self._buttons()
        def worker():
            try:self.messages.put((token,done,job(),None))
            except Exception as error:self.messages.put((token,done,None,error))
        threading.Thread(target=worker,daemon=True,name='parameter-workbench').start()

    def _poll(self):
        if self.closed:return
        try:
            while True:
                token,done,result,error=self.messages.get_nowait();self.busy=False
                if error:self._error(error)
                elif token!=self.generation:self.status.set('任务已结束；输入期间发生变化，结果已留在工作目录，请重新预览。')
                else:done(result)
                self._buttons()
        except queue.Empty:pass
        self._poll_id=self.window.after(80,self._poll)

    def inspect_model(self):
        try:
            from parametric_functions.api import inspect_native_part
            output=self._new_output('尺寸读取');source=self.source.get();config=self.configuration.get();exe=self.sw_exe.get();mode=self.session_mode.get()
            if not source or not config or not exe:raise ValueError('请填写已有零件、准确配置名称和 SolidWorks 程序路径')
        except Exception as error:self._error(error);return
        def done(result):
            if result.get('status')!='inspection_complete':self._error(ValueError(result.get('error','模型读取失败')));return
            self.inspection=result['inspection'];self._clear_review();self.status.set(f"已读取 {len(self.inspection['dimensions'])} 个线性尺寸。请绑定需要改动及保护的参数。")
        self._run('读取副本尺寸',lambda:inspect_native_part(source,config,exe,output,request_key=output.name,session_mode=mode),done)

    def refresh_bindings(self):
        if not hasattr(self,'binding_table'):return
        self.binding_table.delete(*self.binding_table.get_children())
        for name,row in self.binding_rows.items():
            self.binding_table.insert('', 'end',iid=name,values=(name,row['dimension'],row['component_kind'],str(row['allowed_range'])))

    def edit_binding(self):
        from tkinter import messagebox
        if self.preview_data is None or self.inspection is None:self._error(ValueError('先计算参数并读取模型尺寸'));return
        dialog=self.tk.Toplevel(self.window);dialog.title('确认参数绑定');dialog.geometry('650x400')
        parameters=[n for n,r in self.preview_data['plan']['parameter_register'].items() if r['unit'] in {'mm','m'}]
        selected=self.binding_table.selection();initial=selected[0] if selected else parameters[0] if parameters else ''
        parameter=self.tk.StringVar(value=initial);dimension=self.tk.StringVar();role=self.tk.StringVar(value='editable');lo=self.tk.StringVar();hi=self.tk.StringVar();source=self.tk.StringVar()
        rows=[('参数',parameter,parameters),('真实尺寸',dimension,[d['name'] for d in self.inspection['dimensions']]),('角色',role,['editable','fixed','purchased']),('允许最小值 mm',lo,None),('允许最大值 mm',hi,None),('映射 / 范围来源',source,None)]
        for i,(label,var,choices) in enumerate(rows):
            self.ttk.Label(dialog,text=label).grid(row=i,column=0,sticky='w',padx=12,pady=9)
            widget=self.ttk.Combobox(dialog,textvariable=var,values=choices,state='readonly',width=48) if choices is not None else self.ttk.Entry(dialog,textvariable=var,width=51)
            widget.grid(row=i,column=1,sticky='ew',padx=10,pady=9)
        old=self.binding_rows.get(initial)
        if old:
            dimension.set(old['dimension']);role.set(old['component_kind']);lo.set(str(old['allowed_range'][0]));hi.set(str(old['allowed_range'][1]));source.set(old['source'])
        def confirm():
            try:
                name=parameter.get();d=next(d for d in self.inspection['dimensions'] if d['name']==dimension.get())
                bounds=[float(lo.get()),float(hi.get())]
                from sw_api.mapping import load_mappings
                row={'parameter':name,'document':self.inspection['source_document'],'configuration':self.inspection['configuration'],
                     'feature':d['feature'],'dimension':d['name'],'unit':'mm','depends_on':self.preview_data['plan']['parameter_register'][name].get('depends_on',[]),
                     'source':source.get(),'allowed_range':bounds,'component_kind':role.get(),'status':'confirmed'}
                load_mappings({'schema_version':1,'parameters':[row]})
                self.binding_rows[name]=row;self._clear_review();self.refresh_bindings();dialog.destroy()
            except Exception as error:messagebox.showerror('绑定未确认',str(error),parent=dialog)
        self.ttk.Button(dialog,text='确认此绑定',command=confirm).grid(row=6,column=1,sticky='e',padx=12,pady=12)

    def remove_binding(self):
        for name in self.binding_table.selection():self.binding_rows.pop(name,None)
        self._clear_review();self.refresh_bindings()

    def import_bindings(self):
        from tkinter import filedialog
        path=filedialog.askopenfilename(parent=self.window,filetypes=[('绑定表 JSON','*.json')])
        if not path:return
        try:
            from project_delivery import read_json
            from sw_api.mapping import load_mappings
            payload=read_json(path);load_mappings(payload)
            self.binding_rows={r['parameter']:r for r in payload['parameters']};self._clear_review();self.refresh_bindings()
        except Exception as error:self._error(error)

    def prepare(self):
        try:
            if self.preview_data is None:raise ValueError('请先重新计算参数')
            self._clear_review()
            if self.action_mode.get()=='新建零件':
                from parametric_functions.generate import materialize_part_plan
                from cad_checkpoint import digest_file
                plan=materialize_part_plan(self.preview_data)
                template=Path(self.template.get()).expanduser().resolve(strict=True)
                if template.suffix.lower()!='.prtdot':raise ValueError('新建需要空白 PRTDOT 模板')
                self.review_data={'kind':'generate','materialized':plan,'template':str(template),'template_sha256':digest_file(template)}
                summary={'action':'新建可编辑零件','feature_plan_sha256':plan['plan_sha256'],'features':plan['plan']['features'],
                         'template_sha256':self.review_data['template_sha256'],'status':'review_required','manufacturing_approved':False}
            else:
                if self.inspection is None:raise ValueError('请先读取本次模型尺寸')
                from parametric_functions.workflow import prepare_edit_workspace
                directory=self._new_output('参数审核')
                result=prepare_edit_workspace(self.preview_data,{'schema_version':1,'parameters':list(self.binding_rows.values())},self.inspection,directory)
                if result['phase']=='blocked':raise ValueError('变更尚未可审核：'+str(result['conflicts']+result['pending']))
                self.workspace=directory;self.review_data={'kind':'edit','status':result}
                summary=result
            self._show_review(summary)
            self.status.set('请核对以下变化与保护项，填写审核人，再确认仅对副本执行。');self.tabs.select(2);self._buttons()
        except Exception as error:self._clear_review();self._error(error)

    def execute(self):
        try:
            if not self.review_data or not self.review_confirmed.get() or not self.reviewer.get().strip():raise ValueError('先完成变更预览和具名确认')
            if sys.platform!='win32':raise RuntimeError('SolidWorks 执行需要 Windows；当前可计算、预览和导出')
            output=self._new_output('函数建模');review=deepcopy(self.review_data);preview=deepcopy(self.preview_data)
            exe=self.sw_exe.get();mode=self.session_mode.get();reviewer=self.reviewer.get().strip()
            if review['kind']=='edit':
                from parametric_functions.workflow import approve_edit_workspace
                approved=approve_edit_workspace(self.workspace,reviewer=reviewer,expected_review_sha256=review['status']['review_sha256'])
                workspace=self.workspace
                from parametric_functions.api import execute_edit_workspace
                job=lambda:execute_edit_workspace(workspace,exe,output,approval_sha256=approved['approval_sha256'],request_key=output.name,session_mode=mode)
            else:
                from parametric_functions.generate import generate_native_part
                job=lambda:generate_native_part(preview,exe,review['template'],output,reviewer=reviewer,
                    reviewed_plan_sha256=review['materialized']['plan_sha256'],expected_template_sha256=review['template_sha256'],request_key=output.name,session_mode=mode)
        except Exception as error:self._error(error);return
        def done(result):
            self._show_review(result)
            self.review_confirmed.set(False);self.review_data=None
            self.status.set('执行已结束：'+result.get('status','review_required')+'。结果留在 '+str(output)+'；仍需实机/工程复核。')
            self.journal.record('parametric_native_returned',status=result.get('status'),output=str(output))
        self._run('在隔离副本执行',job,done)

    def _show_review(self,data):
        self.review_text.configure(state='normal');self.review_text.delete('1.0','end')
        self.review_text.insert('1.0',json.dumps(data,ensure_ascii=False,indent=2));self.review_text.configure(state='disabled')

    def save(self):
        from tkinter import filedialog
        if self.preview_data is None:return
        parent=filedialog.askdirectory(parent=self.window,title='选择导出父目录')
        if not parent:return
        try:
            target=Path(parent)/('参数方案-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
            path=save_parameter_workspace(self.preview_data,target)
            self.status.set('方案已导出：'+str(path))
            if self.on_message:self.on_message('参数方案已保存',str(path)+'\n仅为参数/映射交接，未执行 CAD。')
        except Exception as error:self._error(error)

    def _error(self,error):
        from tkinter import messagebox
        self.status.set('未完成：'+str(error));self.journal.exception('parametric_workbench_error',error)
        messagebox.showerror('请检查任务',str(error),parent=self.window)

    def close(self):
        if self.busy:
            from tkinter import messagebox
            messagebox.showinfo('任务运行中','请等待当前任务返回；不会强制终止 SolidWorks。',parent=self.window);return
        self.closed=True;self.window.after_cancel(self._poll_id);self.window.destroy()

    def _destroyed(self,event):
        if event.widget is not self.window:return
        self.closed=True
        try:self.window.after_cancel(self._poll_id)
        except (self.tk.TclError,AttributeError):pass


def open_parametric_modeling(parent,on_message=None):
    return ParametricModelingWindow(parent,on_message)
