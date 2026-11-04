"""A visible parameter workspace over the existing A01 solver and mapping API."""
from datetime import datetime
from pathlib import Path

from parametric_workspace import preview_parameters, save_parameter_workspace


class ParametricModelingWindow:
    def __init__(self,parent,on_message=None):
        import tkinter as tk
        from tkinter import ttk
        self.tk=tk;self.on_message=on_message;self.preview_data=None
        from app_logging import get_journal
        self.journal=get_journal()
        self.window=tk.Toplevel(parent);self.window.title('参数化建模');self.window.geometry('1000x690')
        self.window.minsize(820,580)
        body=ttk.Frame(self.window,padding=18);body.pack(fill='both',expand=True)
        ttk.Label(body,text='参数化建模',font=('Microsoft YaHei UI',17)).pack(anchor='w')
        ttk.Label(body,text='输入目标尺寸，预览关联参数，再确认真实模型尺寸绑定。所有尺寸单位为 mm。').pack(anchor='w',pady=(6,14))
        self.spec_path=tk.StringVar();self.rule_label=tk.StringVar(value='内置 A01 规则（示例目标尺寸，非实测尺寸）')
        rule=ttk.Frame(body);rule.pack(fill='x')
        ttk.Label(rule,textvariable=self.rule_label).pack(side='left',fill='x',expand=True)
        ttk.Button(rule,text='导入机型规则 JSON',command=self.choose_spec).pack(side='right')
        fields=ttk.Frame(body);fields.pack(fill='x',pady=16)
        self.values={key:tk.StringVar(value=value) for key,value in [('length','1800'),('width','900'),('height','1500')]}
        for column,(key,label) in enumerate([('length','目标长度'),('width','目标宽度'),('height','目标高度')]):
            ttk.Label(fields,text=label+' · mm').grid(row=0,column=column*2,padx=(0,8))
            ttk.Entry(fields,textvariable=self.values[key],width=12).grid(row=0,column=column*2+1,padx=(0,20))
            self.values[key].trace_add('write',self.invalidate)
        actions=ttk.Frame(body);actions.pack(fill='x')
        self.preview_button=ttk.Button(actions,text='计算参数与依赖',command=self.calculate);self.preview_button.pack(side='left')
        self.save_button=ttk.Button(actions,text='保存方案与模型映射表',command=self.save,state='disabled');self.save_button.pack(side='left',padx=10)
        ttk.Button(actions,text='执行 SolidWorks 改型',state='disabled').pack(side='left')
        self.status=tk.StringVar(value='先计算参数；完成真实模型绑定与实机验证后，开放模型改型。')
        ttk.Label(body,textvariable=self.status,wraplength=900).pack(anchor='w',pady=12)
        ttk.Label(body,text='未确认的尺寸保留为“待确认”；机型规则仅支持已有 JSON 契约，不执行导入的程序。\n方案和映射表不等于已生成模型，也不表示工程或生产验收通过。',wraplength=900).pack(side='bottom',anchor='w',pady=(12,0))
        table=ttk.Frame(body);table.pack(fill='both',expand=True)
        columns=('parameter','value','unit','depends','confirmation')
        self.table=ttk.Treeview(table,columns=columns,show='headings')
        for key,label,width in [('parameter','参数',230),('value','目标值',90),('unit','单位',55),('depends','依赖',260),('confirmation','确认状态',190)]:
            self.table.heading(key,text=label);self.table.column(key,width=width,minwidth=45)
        self.table.pack(side='left',fill='both',expand=True)
        scroll=ttk.Scrollbar(table,orient='vertical',command=self.table.yview);scroll.pack(side='right',fill='y');self.table.configure(yscrollcommand=scroll.set)

    def invalidate(self,*args):
        self.preview_data=None
        if hasattr(self,'save_button'):
            self.save_button.configure(state='disabled');self.status.set('参数已变化，请重新计算。')

    def choose_spec(self):
        from tkinter import filedialog
        path=filedialog.askopenfilename(parent=self.window,title='选择机型参数规则',filetypes=[('机型规则 JSON','*.json')])
        if path:
            self.spec_path.set(path);self.rule_label.set(Path(path).name);self.invalidate()
            self.journal.record('parametric_rule_selected',path=path)

    def calculate(self):
        from tkinter import messagebox
        self.invalidate()
        try:
            result=preview_parameters(**{k:v.get() for k,v in self.values.items()},spec_path=self.spec_path.get() or None)
        except (OSError,ValueError,TypeError,KeyError,RuntimeError) as error:
            self.journal.exception('parametric_preview_failed',error)
            self.status.set('计算未完成，请检查尺寸或机型规则。')
            messagebox.showerror('请检查参数',str(error),parent=self.window);return
        self.preview_data=result
        self.journal.record('parametric_preview_completed',target=result['target_envelope_mm'],review_sha256=result['review_sha256'])
        for item in self.table.get_children():self.table.delete(item)
        plan=result['plan']
        for name,row in plan['parameter_register'].items():
            value=plan['values_mm'].get(name)
            confirmation=row.get('confirmation_status','unconfirmed')
            label={'confirmed':'已确认','unconfirmed':'待确认','pending_mapping':'待模型映射',
                   'generic_rule_not_oem':'通用规则，待核对'}.get(confirmation,'待核对 · '+confirmation)
            self.table.insert('', 'end',values=(name,'待确认' if value is None else f'{value:g}',row.get('unit','mm'),', '.join(row.get('depends_on',[])),label))
        self.status.set(f"参数方案已计算 · {len(plan['unresolved'])} 项待确认 · 尚未生成或修改模型")
        self.save_button.configure(state='normal')

    def save(self):
        from tkinter import filedialog,messagebox
        if self.preview_data is None:return
        parent=filedialog.askdirectory(parent=self.window,title='选择保存位置，将自动新建方案目录')
        if not parent:return
        try:
            target=Path(parent)/datetime.now().strftime('参数化方案-%Y%m%d-%H%M%S-%f')
            path=save_parameter_workspace(self.preview_data,target)
        except (OSError,ValueError,TypeError,KeyError) as error:
            self.journal.exception('parametric_workspace_save_failed',error)
            messagebox.showerror('方案未保存',str(error),parent=self.window);return
        self.journal.record('parametric_workspace_saved',path=str(path),review_sha256=self.preview_data['review_sha256'])
        self.status.set('方案已保存：'+str(path))
        if self.on_message:self.on_message('参数化方案已保存',str(path)+'\n包含参数计划、机型规则和待确认模型映射表；尚未执行模型改型。')


def open_parametric_modeling(parent,on_message=None):
    return ParametricModelingWindow(parent,on_message)
