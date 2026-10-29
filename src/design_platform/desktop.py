"""Read-only design/mapping workbench. UI never starts native CAD writes."""
import json
from pathlib import Path
from .workflow import build_delivery
from .assistant import parse_request
from .mapping import suggest_bindings,approve_binding


def main():
    import tkinter as tk
    from tkinter import ttk,filedialog,messagebox,simpledialog
    root=tk.Tk();root.title('SolidWorks AI — 设计方案与映射审核');root.geometry('1080x760')
    state={'request':None,'report':None,'candidates':[]}
    instruction=tk.StringVar();ttk.Entry(root,textvariable=instruction).pack(fill='x',padx=8,pady=8)
    buttons=ttk.Frame(root);buttons.pack(fill='x');tabs=ttk.Notebook(root);tabs.pack(fill='both',expand=True,padx=8,pady=8)
    plan_tab=ttk.Frame(tabs);mapping_tab=ttk.Frame(tabs);tabs.add(plan_tab,text='方案 / 风险 / 验收');tabs.add(mapping_tab,text='参数映射候选')
    output=tk.Text(plan_tab,wrap='word');output.pack(fill='both',expand=True)
    table=ttk.Treeview(mapping_tab,columns=('parameter','document','dimension','value','unit'),show='headings')
    for field in table['columns']:table.heading(field,text=field)
    table.pack(fill='both',expand=True)
    def show(value):output.delete('1.0','end');output.insert('end',json.dumps(value,ensure_ascii=False,indent=2))
    def guarded(call):
        try:call()
        except Exception as exc:messagebox.showerror('需要检查输入',str(exc))
    def load():
        path=filedialog.askopenfilename(filetypes=[('JSON','*.json')])
        if path:state['request']=json.loads(Path(path).read_text(encoding='utf-8-sig'));show(state['request'])
    def mapping():
        req=state['request']
        if not req:raise ValueError('先加载设计请求')
        report=suggest_bindings(req['snapshot'],req['parameters']);state['report']=report
        state['candidates']=[]
        for item in table.get_children():table.delete(item)
        for row in report['mappings']:
            for candidate in row['candidates']:
                index=len(state['candidates']);state['candidates'].append((row['parameter'],candidate))
                table.insert('', 'end',iid=str(index),values=(row['parameter'],candidate['model_path'],candidate['dimension'],candidate['measured_value'],candidate['units']))
        show(report);tabs.select(mapping_tab)
    def approve():
        selected=table.selection()
        if not selected:raise ValueError('选择一个候选映射')
        parameter,candidate=state['candidates'][int(selected[0])]
        role=simpledialog.askstring('设计意图','角色：adjustable / interface / fixed / purchased')
        if role is None:return
        source=simpledialog.askstring('审核依据','填写模型测量、图纸或工程确认来源')
        if not source:return
        bounds=None
        if role=='adjustable':
            text=simpledialog.askstring('允许范围','按候选单位输入最小值,最大值')
            if text is None:return
            bounds=[float(v.strip()) for v in text.split(',')]
        approval={'parameter':parameter,'document_id':candidate['document_id'],'dimension':candidate['dimension'],
            'role':role,'allowed_range':bounds,'source':source,'reviewed':True,'report_sha256':state['report']['report_sha256']}
        binding=approve_binding(state['report'],approval)
        path=filedialog.asksaveasfilename(defaultextension='.json',filetypes=[('JSON','*.json')])
        if path:
            with Path(path).open('x',encoding='utf-8') as f:json.dump(binding,f,ensure_ascii=False,indent=2)
        show(binding)
    def export():
        if state['request'] is None:raise ValueError('先加载设计请求')
        parent=filedialog.askdirectory(title='选择父目录；新包目录必须不存在')
        if not parent:return
        name=simpledialog.askstring('交接包','新目录名称')
        if not name or Path(name).name!=name or name in {'.','..'}:raise ValueError('使用单个新目录名称')
        show(build_delivery(state['request'],Path(parent)/name));tabs.select(plan_tab)
    for label,call in [('读取设计指令',lambda:show(parse_request(instruction.get()))),('加载请求',load),('列出映射候选',mapping),('确认所选映射',approve),('生成统一交接包',export)]:
        ttk.Button(buttons,text=label,command=lambda fn=call:guarded(fn)).pack(side='left',padx=5)
    ttk.Label(root,text='候选识别需要工程确认；本工作台只生成方案、映射和交接包，原生执行使用已有独占会话入口。').pack(fill='x',padx=8)
    root.mainloop()
