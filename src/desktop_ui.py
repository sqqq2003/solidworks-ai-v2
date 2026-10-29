"""A focused Tk desktop; widgets are created only by Workbench/run."""
from pathlib import Path
import json
import queue
import threading
from desktop_jobs import MODES, ACTIONS, QL_ACTIONS, STATUS_LABELS, build_desktop_job

ROOT=Path(__file__).resolve().parents[1]
BG='#F8F8F7'; WHITE='#FFFFFF'; INK='#252525'; MUTED='#787872'; LINE='#E8E8E5'
BLUE='#242424'; NAV='#EFEFED'


def explain_task_result(row):
    """Summarize failures without turning an incomplete result into a pass."""
    status=row.get('status','review_required')
    title=STATUS_LABELS.get(status,status)+' · '+str(row.get('name',row.get('kind','任务')))
    if status=='analyzed':
        analysis=next((event for event in row.get('events',[]) if isinstance(event,dict) and event.get('event')=='analysis'),None)
        if analysis:
            warnings=analysis.get('warnings') or []
            return (title+'\n候选轮廓：'+str(analysis.get('profile_count','未知'))+
                    '；候选折弯线：'+str(analysis.get('bend_line_count','未知'))+
                    ('\n提醒：'+'；'.join(map(str,warnings)) if warnings else '')+
                    '\n候选线条需逐项核对，尚未生成或验收 SolidWorks 模型。')
    if status in {'review_required','generated_unverified','degraded'}:
        artifact=row.get('artifact') or {}
        done=next((event for event in row.get('events',[]) if isinstance(event,dict) and event.get('event')=='done'),{})
        path=artifact.get('path')
        if path:
            result=title+'\n输出文件：'+str(path)
            if 'reopen' in done and done['reopen'] is None:
                result+='\n重开验证尚未完成；请检查运行详情，不能作为生产验收。'
            else:
                result+='\n仍需核对模型和工程要求，不能作为生产验收。'
            return result
    if status not in {'failed','timed_out'}:
        return title
    events=row.get('events') or []
    messages=[str(e.get('message','')) for e in events if isinstance(e,dict) and e.get('event')=='error']
    detail=str(row.get('error') or (messages[-1] if messages else ''))
    diagnostic=detail+' '+str(row.get('stderr') or '')
    if 'Contour search limit reached' in diagnostic:
        return title+'\n图纸中的线条较复杂，暂时无法完整识别轮廓。可先查看图纸概览，确认图层和标注，再准备单个零件的图纸。'
    if status=='timed_out':
        return title+'\n任务等待超时。后台进程可能仍在运行，请先查看运行记录，不要重复启动。'
    if detail:
        return title+'\n原因：'+detail[:350]+'\n可在“运行详情”中查看完整记录。'
    return title+'\n请打开“运行详情”查看原因。'


class Workbench:
    def __init__(self, root):
        import tkinter as tk
        from tkinter import ttk, font
        self.tk=tk;self.ttk=ttk;self.root=root
        from app_logging import get_journal,install_tk_hook
        self.journal=get_journal();install_tk_hook(root)
        self.state={'busy':False,'jobs':[]};self.messages=queue.Queue();self.stop=threading.Event()
        self.values={k:tk.StringVar(value=v) for k,v in {
            'kind':'sheet','source':'','output':'','sw_exe':'','machine':'QL-5050PX','ql_action':'plan',
            'profile':'1','variant':'0','thickness':'','radius':'','angle':'','k_factor':'',
            'uniform_scale':'',
            'length':'1800','width':'900','height':'1500'}.items()}
        self.confirmed=tk.BooleanVar();self.flip=tk.BooleanVar();self.inferred=tk.BooleanVar();self.preserve_circle_holes=tk.BooleanVar()
        self.native_open=False;self.advanced_open=False;self.detail_open=False
        self.report_text='';self.inputs=[];self.nav_buttons={};self.row_ids=[]
        self.running_rows=[];self.running_jobs=[];self.queue_running=False;self.last_request=None
        self.settings_open=False;self.chat_cards=[];self.tool_panels=[]
        self.ai_session=None;self.ai_busy=False;self.ai_generation=0
        self.ai_events=queue.Queue();self.ai_cancel=threading.Event()
        self.ai_status=tk.StringVar(value='本地审核')
        self.action=tk.StringVar(value='生成计划');self.ql_action=tk.StringVar(value='参数计划')
        self.status=tk.StringVar(value='就绪');self.queue_count=tk.StringVar(value='0 项待运行')
        self.summary=tk.StringVar(value='添加任务后，可在这里查看进度和结果。')
        root.title('SolidWorks AI · 设计工作台');root.geometry('1200x800');root.minsize(1000,700);root.configure(bg=BG)
        families=set(font.families(root));self.family=next((f for f in ('Microsoft YaHei UI','Microsoft YaHei','Segoe UI','Noto Sans CJK SC','Noto Sans CJK JP') if f in families),font.nametofont('TkDefaultFont').actual('family'))
        root.option_add('*Font',(self.family,10));root.option_add('*TCombobox*Listbox.font',(self.family,10))
        style=ttk.Style(root);style.theme_use('clam')
        style.configure('.',font=(self.family,10),background=WHITE,foreground=INK)
        style.configure('TEntry',fieldbackground=WHITE,bordercolor=LINE,lightcolor=LINE,darkcolor=LINE,padding=8)
        style.map('TEntry',bordercolor=[('focus',BLUE)])
        style.configure('TCombobox',fieldbackground=WHITE,background=WHITE,bordercolor=LINE,padding=7,arrowsize=12)
        style.map('TCombobox',fieldbackground=[('readonly',WHITE)],selectbackground=[('readonly',WHITE)],selectforeground=[('readonly',INK)])
        style.configure('TCheckbutton',background=WHITE,foreground=MUTED,padding=3)
        style.configure('Treeview',rowheight=36,background=WHITE,fieldbackground=WHITE,borderwidth=0,font=(self.family,10))
        style.configure('Treeview.Heading',font=(self.family,9),background='#F7F9FC',foreground=MUTED,relief='flat',padding=(12,9))
        style.map('Treeview',background=[('selected','#EAF1FF')],foreground=[('selected',INK)])
        style.configure('Vertical.TScrollbar',background='#CDD7E3',troughcolor=WHITE,borderwidth=0,arrowsize=10)
        style.configure('Horizontal.TProgressbar',background=BLUE,troughcolor=LINE,borderwidth=0,thickness=3)
        self._layout()
        for var in self.values.values():var.trace_add('write',self._invalidate)
        self.flip.trace_add('write',self._invalidate);self.inferred.trace_add('write',self._invalidate)
        self.preserve_circle_holes.trace_add('write',self._invalidate)
        self.action.trace_add('write',self._action_changed)
        self.switch_mode('sheet')
        for event in ('<MouseWheel>','<Button-4>','<Button-5>'):root.bind_all(event,self.scroll_content,add='+')
        root.protocol('WM_DELETE_WINDOW',self.close)
        self.poll_id=root.after(120,self.poll)

    def label(self,parent,text,*,size=10,color=INK,bg=WHITE,bold=False,**kw):
        return self.tk.Label(parent,text=text,bg=bg,fg=color,font=(self.family,size,'bold' if bold else 'normal'),**kw)

    def button(self,parent,text,command,*,primary=False,dark=False):
        bg=BLUE if primary else NAV if dark else BG
        return self.tk.Button(parent,text=text,command=command,bg=bg,fg=WHITE if primary or dark else INK,
            activebackground='#444444' if primary else '#E4E4E0',activeforeground=WHITE if primary else INK,
            relief='flat',bd=0,highlightthickness=0,padx=16,pady=9,cursor='hand2',font=(self.family,10),disabledforeground='#9BA8B8')

    def _layout(self):
        tk,ttk=self.tk,self.ttk
        self.root.configure(bg=WHITE)
        nav=tk.Frame(self.root,bg=NAV,width=218);nav.pack(side='left',fill='y');nav.pack_propagate(False)
        brand=tk.Frame(nav,bg=NAV);brand.pack(fill='x',padx=20,pady=(24,22))
        self.label(brand,'◈',size=21,bg=NAV,bold=True).pack(side='left',padx=(0,9))
        self.label(brand,'SolidWorks AI',size=13,bg=NAV,bold=True).pack(side='left')
        self.button(nav,'＋  新建设计任务',self.new_task).pack(fill='x',padx=12,pady=(0,20))
        self.label(nav,'设计工作空间',size=9,bg=NAV,color=MUTED).pack(anchor='w',padx=22,pady=(0,8))
        for key,(title,_) in MODES.items():
            if key in {'roller','turned','parametric'}:continue
            title={'sheet':'图纸转模型','ql5050px':'整机改型'}.get(key,title)
            button=self.button(nav,title,lambda k=key:self.switch_mode(k))
            button.configure(anchor='w',pady=10,padx=16)
            button.pack(fill='x',padx=12,pady=2);self.nav_buttons[key]=button
        self.button(nav,'三视图 / BOM',self.open_drawing).pack(fill='x',padx=12,pady=2)
        self.button(nav,'DXF 图纸概览',self.open_dxf_overview).pack(fill='x',padx=12,pady=2)
        self.button(nav,'钣金批量预检',self.open_sheet_batch_review).pack(fill='x',padx=12,pady=2)
        self.button(nav,'尺寸试改预检',self.native_review).pack(fill='x',padx=12,pady=2)
        tk.Frame(nav,bg=LINE,height=1).pack(fill='x',padx=20,pady=20)
        self.button(nav,'任务队列',self.show_queue).pack(fill='x',padx=12,pady=2)
        self.button(nav,'项目交付 / 验收',self.open_delivery).pack(fill='x',padx=12,pady=2)
        self.button(nav,'AI 连接',self.configure_ai).pack(fill='x',padx=12,pady=2)
        self.button(nav,'设置',self.show_environment).pack(fill='x',padx=12,pady=2)
        self.button(nav,'运行记录',self.show_logs).pack(fill='x',padx=12,pady=2)
        self.label(nav,'V2  ·  本地工作副本',size=9,bg=NAV,color=MUTED).pack(side='bottom',anchor='w',padx=22,pady=24)
        shell=tk.Frame(self.root,bg=WHITE);shell.pack(side='left',fill='both',expand=True)
        bar=tk.Frame(shell,bg=WHITE,padx=24,pady=16);bar.pack(fill='x')
        self.context=tk.StringVar(value='新设计任务')
        self.tk.Label(bar,textvariable=self.context,bg=WHITE,fg=INK,font=(self.family,11,'bold')).pack(side='left')
        self.settings_button=self.button(bar,'任务设置',self.toggle_settings);self.settings_button.pack(side='right')
        self.queue_button=self.button(bar,'任务队列',self.show_queue);self.queue_button.pack(side='right',padx=8)
        tk.Frame(shell,bg=LINE,height=1).pack(fill='x')
        workspace=tk.Frame(shell,bg=WHITE);workspace.pack(fill='both',expand=True)
        self.settings=tk.Frame(workspace,bg=WHITE,width=350,highlightbackground=LINE,highlightthickness=1)
        self.settings.pack_propagate(False)
        self._settings_layout(self.settings)
        center=tk.Frame(workspace,bg=WHITE);center.pack(side='left',fill='both',expand=True,padx=22)
        feed=tk.Frame(center,bg=WHITE);feed.pack(fill='both',expand=True)
        self.feed_canvas=tk.Canvas(feed,bg=WHITE,highlightthickness=0)
        self.feed_canvas.pack(side='left',fill='both',expand=True)
        scrollbar=ttk.Scrollbar(feed,orient='vertical',command=self.feed_canvas.yview)
        scrollbar.pack(side='right',fill='y')
        def scroll_changed(first,last):
            scrollbar.set(first,last)
            if float(first)<=0 and float(last)>=1:scrollbar.pack_forget()
            elif not scrollbar.winfo_manager():scrollbar.pack(side='right',fill='y')
        self.feed_canvas.configure(yscrollcommand=scroll_changed)
        self.conversation=tk.Frame(self.feed_canvas,bg=WHITE,padx=40,pady=28)
        feed_window=self.feed_canvas.create_window((0,0),window=self.conversation,anchor='nw')
        def resize_feed(event):
            self.feed_canvas.itemconfigure(feed_window,width=event.width)
            if hasattr(self,'description'):self.description.configure(wraplength=max(300,event.width-90))
            for card in self.chat_cards:
                for widget in card.winfo_children():
                    if isinstance(widget,tk.Label):widget.configure(wraplength=max(280,event.width-100))
        self.feed_canvas.bind('<Configure>',resize_feed)
        self.conversation.bind('<Configure>',lambda e:self.feed_canvas.configure(scrollregion=self.feed_canvas.bbox('all')))
        self.welcome=tk.Frame(self.feed_canvas,bg=WHITE)
        self.welcome.place(relx=.5,rely=.45,anchor='center')
        self.label(self.welcome,'◈',size=36,bold=True).pack(pady=(0,16))
        self.title=self.label(self.welcome,'今天要设计什么？',size=25,bold=True);self.title.pack()
        self.description=self.label(self.welcome,'描述设计目标，从一份可审核的方案开始。',color=MUTED,wraplength=600)
        self.description.pack(pady=(12,22))
        quick=tk.Frame(self.welcome,bg=WHITE);quick.pack()
        self.button(quick,'选择 DXF 并检查',self.start_dxf_review,primary=True).pack(side='left',padx=5)
        for text,kind in [('图纸转模型','sheet'),('滚筒改型','roller'),('整机任务','ql5050px')]:
            self.button(quick,text,lambda k=kind:self.quick_task(k)).pack(side='left',padx=5)
        composer_wrap=tk.Frame(center,bg=WHITE,padx=28,pady=16);composer_wrap.pack(fill='x',side='bottom')
        self.composer_panel=tk.Frame(composer_wrap,bg=BG,highlightbackground=LINE,highlightthickness=1,padx=16,pady=12)
        self.composer_panel.pack(fill='x')
        self.composer=tk.Text(self.composer_panel,height=3,wrap='word',relief='flat',bd=0,highlightthickness=0,
              bg=BG,fg=INK,insertbackground=INK,font=(self.family,11),padx=0,pady=4,undo=True)
        self.composer.pack(fill='x')
        self.placeholder='描述设计目标，例如：把滚筒总长改成 800 mm，轴径和两端安装结构不变。'
        self.composer.insert('1.0',self.placeholder);self.composer.configure(fg=MUTED);self.placeholder_visible=True
        self.composer.bind('<FocusIn>',self._composer_focus);self.composer.bind('<FocusOut>',self._composer_blur)
        self.composer.bind('<Control-Return>',lambda e:self.send_instruction())
        self.composer.bind('<Command-Return>',lambda e:self.send_instruction())
        tools=tk.Frame(self.composer_panel,bg=BG);tools.pack(fill='x',pady=(10,0))
        attach=self.button(tools,'＋ 添加文件',lambda:self.choose('source'));attach.configure(bg=BG);attach.pack(side='left')
        self.attachment=tk.StringVar(value='')
        self.tk.Label(tools,textvariable=self.attachment,bg=BG,fg=MUTED,font=(self.family,9)).pack(side='left',padx=8)
        self.send_button=self.button(tools,'↑',self.send_instruction,primary=True);self.send_button.configure(padx=14,pady=5);self.send_button.pack(side='right')
        footer=tk.Frame(composer_wrap,bg=WHITE);footer.pack(fill='x',pady=(9,0))
        self.label(footer,'先审核方案，再执行模型修改。',size=9,color=MUTED).pack(side='left')
        self.label(footer,'Ctrl + Enter 提交',size=9,color=MUTED).pack(side='right')
        state_line=tk.Frame(center,bg=WHITE,padx=28,pady=8);state_line.pack(fill='x',side='bottom')
        self.tk.Label(state_line,textvariable=self.status,bg=WHITE,fg=MUTED,font=(self.family,9)).pack(side='left')
        self.detail_button=self.button(state_line,'运行详情',self.toggle_details);self.detail_button.pack(side='right')
        self.progress=ttk.Progressbar(center,mode='indeterminate')
        self.detail_window=None;self.log_widget=None
        self._queue_layout()
        self._sync_buttons()

    def _settings_layout(self,parent):
        tk,ttk=self.tk,self.ttk
        heading=tk.Frame(parent,bg=WHITE,padx=18,pady=16);heading.pack(fill='x')
        self.label(heading,'任务设置',size=12,bold=True).pack(side='left')
        self.button(heading,'×',self.toggle_settings).pack(side='right')
        self.canvas=tk.Canvas(parent,bg=WHITE,highlightthickness=0)
        self.canvas.pack(side='left',fill='both',expand=True)
        scrollbar=ttk.Scrollbar(parent,orient='vertical',command=self.canvas.yview);scrollbar.pack(side='right',fill='y')
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.form=tk.Frame(self.canvas,bg=WHITE,padx=16,pady=14);self.form.columnconfigure(0,weight=1)
        window=self.canvas.create_window((0,0),window=self.form,anchor='nw')
        self.canvas.bind('<Configure>',lambda e:self.canvas.itemconfigure(window,width=e.width))
        self.form.bind('<Configure>',lambda e:self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.form_title=self.label(self.form,'项目交付',size=11,bold=True);self.form_title.grid(row=0,column=0,sticky='w',pady=(0,14))
        self.part_selector=ttk.Combobox(self.form,values=('钣金零件','滚筒零件','车削零件','目标包络'),state='readonly')
        self.part_selector.grid(row=1,column=0,sticky='ew',pady=(0,12))
        self.part_selector.bind('<<ComboboxSelected>>',lambda e:self.switch_mode({'钣金零件':'sheet','滚筒零件':'roller','车削零件':'turned','目标包络':'parametric'}[self.part_selector.get()]))
        self.files=tk.Frame(self.form,bg=WHITE);self.files.grid(row=2,column=0,sticky='ew');self.files.columnconfigure(0,weight=1)
        self.source_label=self.path_row(self.files,0,'source','项目配置 · JSON')
        self.output_label=self.path_row(self.files,1,'output','新输出目录')
        self.package_hint=self.label(self.form,'结果存入新目录，原始文件保持不变。',size=9,color=MUTED,wraplength=280,justify='left')
        self.package_hint.grid(row=3,column=0,sticky='w',pady=(8,14))
        self.action_frame=tk.Frame(self.form,bg=WHITE);self.action_frame.grid(row=4,column=0,sticky='ew',pady=(0,16))
        self.label(self.action_frame,'处理方式',size=9,color=MUTED).pack(anchor='w',pady=(0,6))
        self.action_box=ttk.Combobox(self.action_frame,textvariable=self.action,values=tuple(ACTIONS),state='readonly',width=25)
        self.ql_box=ttk.Combobox(self.action_frame,textvariable=self.ql_action,values=tuple(QL_ACTIONS),state='readonly',width=25)
        self.ql_box.bind('<<ComboboxSelected>>',lambda e:self.values['ql_action'].set(QL_ACTIONS[self.ql_action.get()]))
        self.inputs.extend([(self.action_box,'readonly'),(self.ql_box,'readonly')])
        self.sheet_frame=tk.Frame(self.form,bg=WHITE);self.sheet_frame.grid(row=5,column=0,sticky='ew',pady=(0,16))
        self.numeric_row(self.sheet_frame,[('thickness','板厚 · mm'),('radius','内半径 · mm'),('angle','折弯角度 · °'),('k_factor','K 因子'),('uniform_scale','等比例倍数（留空不变；孔同步缩放）')])
        ttk.Checkbutton(self.sheet_frame,text='圆孔孔径不变（孔心随外形缩放）',variable=self.preserve_circle_holes).grid(row=6,column=0,columnspan=2,sticky='w',pady=(8,0))
        self.machine_frame=tk.Frame(self.form,bg=WHITE);self.machine_frame.grid(row=6,column=0,sticky='ew',pady=(0,16));self.machine_frame.columnconfigure(0,weight=1)
        model=ttk.Combobox(self.machine_frame,textvariable=self.values['machine'],values=('QL-5050PX','GT-ZX'),state='readonly',width=23)
        model.grid(row=0,column=0,sticky='ew',pady=(0,12));self.inputs.append((model,'readonly'))
        dimensions=tk.Frame(self.machine_frame,bg=WHITE);dimensions.grid(row=1,column=0,sticky='ew')
        self.numeric_row(dimensions,[('length','目标长度 · mm'),('width','目标宽度 · mm'),('height','目标高度 · mm')])
        self.extra_line=tk.Frame(self.form,bg=WHITE);self.extra_line.grid(row=7,column=0,sticky='ew')
        self.advanced_toggle=self.button(self.extra_line,'高级选项  +',self.toggle_advanced);self.advanced_toggle.pack(anchor='w',pady=3)
        self.native_toggle=self.button(self.extra_line,'SolidWorks 设置  +',self.toggle_native);self.native_toggle.pack(anchor='w',pady=3)
        self.advanced=tk.Frame(self.form,bg=WHITE);self.advanced.grid(row=8,column=0,sticky='ew',pady=(10,0))
        self.index_frame=tk.Frame(self.advanced,bg=WHITE);self.index_frame.pack(fill='x')
        self.profile_fields=tk.Frame(self.index_frame,bg=WHITE);self.numeric_row(self.profile_fields,[('profile','轮廓编号 · 从 1 开始')])
        self.variant_fields=tk.Frame(self.index_frame,bg=WHITE);self.numeric_row(self.variant_fields,[('variant','规格索引 · 从 0 开始')])
        self.inferred_check=ttk.Checkbutton(self.advanced,text='允许通用默认尺寸（非 OEM 实测）',variable=self.inferred)
        self.native=tk.Frame(self.form,bg=WHITE);self.native.grid(row=9,column=0,sticky='ew',pady=(12,0));self.native.columnconfigure(0,weight=1)
        self.path_row(self.native,0,'sw_exe','SolidWorks 程序')
        self.flip_check=ttk.Checkbutton(self.native,text='反向折弯',variable=self.flip);self.flip_check.grid(row=1,column=0,sticky='w',pady=6)
        ttk.Checkbutton(self.native,text='已核对图纸、索引、尺寸和方向',variable=self.confirmed).grid(row=2,column=0,sticky='w')
        self.label(self.native,'修改输入会取消确认。',size=9,color=MUTED).grid(row=3,column=0,sticky='w',pady=5)
        controls=tk.Frame(self.form,bg=WHITE);controls.grid(row=10,column=0,sticky='ew',pady=(22,12))
        self.add_button=self.button(controls,'加入任务队列',self.append,primary=True);self.add_button.pack(fill='x')
        self.run_current_button=self.button(controls,'立即运行当前任务',self.run_current);self.run_current_button.pack(fill='x',pady=(6,0))
        self.native_button=self.button(controls,'尺寸试改预检',self.native_review)

    def _queue_layout(self):
        tk,ttk=self.tk,self.ttk
        self.queue_window=tk.Toplevel(self.root);self.queue_window.title('任务队列');self.queue_window.geometry('960x540');self.queue_window.configure(bg=WHITE)
        self.queue_window.protocol('WM_DELETE_WINDOW',self.queue_window.withdraw)
        top=tk.Frame(self.queue_window,bg=WHITE,padx=20,pady=18);top.pack(fill='x')
        self.label(top,'任务队列',size=17,bold=True).pack(side='left')
        self.tk.Label(top,textvariable=self.queue_count,bg=WHITE,fg=MUTED).pack(side='left',padx=12)
        self.clear_button=self.button(top,'清空',self.clear);self.clear_button.pack(side='right')
        body=tk.Frame(self.queue_window,bg=WHITE,padx=20);body.pack(fill='both',expand=True)
        self.table=ttk.Treeview(body,columns=('task','file','state'),show='headings',height=7,selectmode='browse')
        for key,label,width in [('task','任务',150),('file','文件 / 项目',460),('state','状态',170)]:
            self.table.heading(key,text=label,anchor='w');self.table.column(key,width=width,anchor='w',stretch=(key=='file'))
        self.table.pack(side='left',fill='both',expand=True);scroll=ttk.Scrollbar(body,command=self.table.yview);scroll.pack(side='right',fill='y');self.table.configure(yscrollcommand=scroll.set)
        self.empty=self.label(body,'暂无任务',color=MUTED);self.empty.place(relx=.5,rely=.5,anchor='center')
        self.table.tag_configure('failed',foreground='#AD4141');self.table.tag_configure('review',foreground='#98742A')
        bottom=tk.Frame(self.queue_window,bg=WHITE,padx=20,pady=18);bottom.pack(fill='x')
        self.tk.Label(bottom,textvariable=self.summary,bg=WHITE,fg=MUTED).pack(side='left')
        self.start_button=self.button(bottom,'运行队列',self.start,primary=True);self.start_button.pack(side='right')
        self.stop_button=self.button(bottom,'当前任务后停止',self.stop_after_current);self.stop_button.pack(side='right',padx=8)
        self.queue_window.withdraw()

    def path_row(self,parent,row,key,title):
        group=self.tk.Frame(parent,bg=WHITE);group.grid(row=row,column=0,sticky='ew',pady=(0,12));group.columnconfigure(0,weight=1)
        label=self.label(group,title,size=9,color=MUTED);label.grid(row=0,column=0,columnspan=2,sticky='w',pady=(0,5))
        entry=self.ttk.Entry(group,textvariable=self.values[key],width=17);entry.grid(row=1,column=0,sticky='ew')
        button=self.button(group,'…',lambda:self.choose(key));button.configure(padx=10);button.grid(row=1,column=1,padx=(6,0))
        self.inputs.extend([(entry,'normal'),(button,'normal')]);return label

    def numeric_row(self,parent,fields):
        for i,(key,title) in enumerate(fields):
            row,column=divmod(i,2);parent.columnconfigure(column,weight=1)
            self.label(parent,title,size=9,color=MUTED).grid(row=row*2,column=column,sticky='w',padx=(0,8),pady=(8,5))
            entry=self.ttk.Entry(parent,textvariable=self.values[key],width=10);entry.grid(row=row*2+1,column=column,sticky='ew',padx=(0,8));self.inputs.append((entry,'normal'))

    def _invalidate(self,*_):
        self.confirmed.set(False)
        if hasattr(self,'attachment'):
            name=Path(self.values['source'].get()).name
            self.attachment.set(name if len(name)<28 else name[:25]+'…')
            self.context.set(name or '新设计任务')

    def switch_mode(self,kind):
        if self.state['busy']:return
        self.values['kind'].set(kind);self.form_title.configure(text=MODES[kind][0]);self.description.configure(text=MODES[kind][1])
        self.part_selector.grid_remove() if kind=='ql5050px' else self.part_selector.grid()
        if kind!='ql5050px':self.part_selector.set({'sheet':'钣金零件','roller':'滚筒零件','turned':'车削零件','parametric':'目标包络'}[kind])
        for key,b in self.nav_buttons.items():b.configure(bg='#DEDEDA' if key==kind else NAV,fg=INK if key==kind else '#666662')
        geometry=kind in {'sheet','roller','turned'}
        self.source_label.configure(text='图纸工作副本' if geometry else '项目配置 · JSON')
        self.output_label.configure(text='新零件 · SLDPRT' if geometry else '新输出目录')
        self.files.grid_remove() if kind=='parametric' else self.files.grid()
        self.package_hint.grid_remove() if kind=='parametric' else self.package_hint.grid()
        self.machine_frame.grid() if kind=='parametric' else self.machine_frame.grid_remove()
        self.action_frame.grid() if geometry or kind=='ql5050px' else self.action_frame.grid_remove()
        self.action_box.pack_forget();self.ql_box.pack_forget()
        if geometry:self.action_box.pack(side='left')
        elif kind=='ql5050px':self.ql_box.pack(side='left')
        self.extra_line.grid() if geometry else self.extra_line.grid_remove()
        self.profile_fields.pack_forget();self.variant_fields.pack_forget();self.inferred_check.pack_forget()
        if kind=='sheet':self.profile_fields.pack(fill='x')
        if kind in {'roller','turned'}:self.variant_fields.pack(fill='x')
        if kind=='roller':self.inferred_check.pack(anchor='w',pady=(10,0))
        self.flip_check.grid() if kind=='sheet' else self.flip_check.grid_remove()
        self._refresh_options();self.canvas.yview_moveto(0)

    def _action_changed(self,*_):
        self.confirmed.set(False)
        if self.action.get()=='原生生成':
            self.native_open=True
            if not self.settings_open:self.toggle_settings()
        self._refresh_options()

    def _refresh_options(self):
        kind=self.values['kind'].get();geometry=kind in {'sheet','roller','turned'}
        self.sheet_frame.grid() if kind=='sheet' and self.action.get()!='识别图纸' else self.sheet_frame.grid_remove()
        self.native.grid() if geometry and self.native_open else self.native.grid_remove()
        self.advanced.grid() if geometry and self.advanced_open else self.advanced.grid_remove()
        self.native_toggle.configure(text='SolidWorks 设置  −' if self.native_open else 'SolidWorks 设置  +')
        self.advanced_toggle.configure(text='高级选项  −' if self.advanced_open else '高级选项  +')

    def scroll_content(self,event):
        widget=event.widget;target=None
        while widget is not None:
            if widget in (self.form,self.canvas):target=self.canvas;break
            if widget in (self.conversation,self.feed_canvas):target=self.feed_canvas;break
            widget=getattr(widget,'master',None)
        if target is None:return
        delta=getattr(event,'delta',0)
        direction=-1 if getattr(event,'num',None)==4 or delta>0 else 1
        target.yview_scroll(direction*3,'units')
        return 'break'

    def toggle_native(self):
        self.native_open=not self.native_open;self._refresh_options()
    def toggle_advanced(self):
        self.advanced_open=not self.advanced_open;self._refresh_options()

    def choose(self,key):
        from tkinter import filedialog
        kind=self.values['kind'].get()
        if key=='output' and kind in {'unified','ql5050px'}:
            parent=filedialog.askdirectory(parent=self.root,title='选择父目录，结果将保存到新的子目录')
            path=str(Path(parent)/('project-output' if kind=='unified' else 'ql-output')) if parent else ''
        elif key=='output':path=filedialog.asksaveasfilename(parent=self.root,defaultextension='.SLDPRT',filetypes=[('SolidWorks 零件','*.SLDPRT')])
        else:
            pattern='*.exe' if key=='sw_exe' else '*.json' if kind in {'unified','ql5050px'} else '*.dxf *.dwg'
            path=filedialog.askopenfilename(parent=self.root,filetypes=[('输入文件',pattern),('所有文件','*.*')])
        if path:
            self.values[key].set(path);self.journal.record('input_selected',field=key,path=path,kind=kind)

    def append(self):
        if self.state['busy']:return False
        from tkinter import messagebox
        try:
            job=build_desktop_job({k:v.get() for k,v in self.values.items()},ACTIONS.get(self.action.get(),'plan'),
                 confirmed=self.confirmed.get(),flip=self.flip.get(),allow_inferred=self.inferred.get(),preserve_circle_holes=self.preserve_circle_holes.get())
            if not self.state['jobs']:
                for item in self.table.get_children():self.table.delete(item)
                self.row_ids=[]
            self.state['jobs'].append(job)
            self.journal.record('job_queued',job=job)
            source=job.get('config',job.get('source','目标包络'))
            item=self.table.insert('', 'end',values=(MODES[job['kind']][0],Path(source).name,'待运行'))
            self.row_ids.append(item);self.empty.place_forget();self.summary.set('任务已加入队列，准备好后点击运行。')
            self.queue_count.set(f"{len(self.state['jobs'])} 项待运行");self.status.set('就绪');self._sync_buttons()
            self.add_message('任务已加入队列',MODES[job['kind']][0]+' · '+Path(source).name+'\n准备好后，在任务队列中运行。')
            return True
        except (OSError,ValueError,KeyError) as exc:
            self.journal.exception('job_validation_failed',exc)
            messagebox.showerror('请检查任务信息',str(exc),parent=self.root)
            return False

    def run_current(self):
        from tkinter import messagebox
        if self.state['busy']:return
        if self.state['jobs']:
            messagebox.showinfo('队列中有待运行任务','请先在任务队列中运行或清空已有任务，再运行当前任务。',parent=self.root)
            return
        if self.append():self.start()

    def _sync_buttons(self):
        busy=self.state['busy'];has_jobs=bool(self.state['jobs'])
        self.queue_button.configure(text=f'任务队列 · {len(self.state["jobs"])}' if has_jobs else '任务队列')
        self.send_button.configure(state='disabled' if busy else 'normal',text='■' if self.ai_busy else '↑')
        self.add_button.configure(state='disabled' if busy else 'normal')
        self.run_current_button.configure(state='disabled' if busy else 'normal')
        self.start_button.configure(state='normal' if has_jobs and not busy else 'disabled')
        self.clear_button.configure(state='disabled' if busy or not self.table.get_children() else 'normal')
        self.stop_button.configure(state='normal' if busy else 'disabled')
        self.native_button.configure(state='disabled' if busy else 'normal')
        for button in self.nav_buttons.values():button.configure(state='disabled' if busy else 'normal')
        for widget,normal in self.inputs:widget.configure(state='disabled' if busy else normal)

    def start(self):
        if self.state['busy'] or not self.state['jobs']:return
        from project_workbench import run_batch,write_report
        jobs=list(self.state['jobs']);self.running_jobs=jobs;self.running_rows=list(self.row_ids);self.queue_running=True
        self.state['busy']=True;self.stop.clear();self._sync_buttons()
        self.journal.record('queue_started',jobs=len(jobs))
        self.add_message('开始执行',f'{len(jobs)} 项任务将按顺序处理，完成后在这里查看结果。')
        self.status.set('运行中');self.summary.set('正在串行处理，当前任务结束后更新结果。');self.progress.place(relx=0,rely=0,relwidth=1,height=2);self.progress.start(12)
        for item in self.row_ids:self.table.set(item,'state','排队中')
        def worker():
            try:
                report=run_batch(jobs,stop_requested=self.stop.is_set)
                path=write_report(report,ROOT/'runtime/project-reports');self.messages.put((report,str(path)))
            except Exception as exc:self.messages.put(({'status':'failed','error':str(exc)},None))
        threading.Thread(target=worker,daemon=True).start()

    def stop_after_current(self):
        self.journal.record('queue_stop_requested')
        self.stop.set();self.summary.set('已请求停止；等待当前任务结束，不强制关闭 SolidWorks。')

    def poll(self):
        self._poll_ai()
        if getattr(self,'poll_id',None):
            try:self.root.after_cancel(self.poll_id)
            except self.tk.TclError:pass
        try:
            while True:
                report,path=self.messages.get_nowait()
                self.journal.record('queue_finished',status=report.get('status'),report=path,error=report.get('error'))
                self.report_text+=json.dumps(report,ensure_ascii=False,indent=2)+'\n\n'
                rows=report.get('results',[])
                if self.queue_running:
                    for item,row in zip(self.running_rows,rows):
                        state=row.get('status','review_required');self.table.set(item,'state',STATUS_LABELS.get(state,state))
                        self.table.item(item,tags=('failed' if state in {'failed','timed_out'} else 'review' if state in {'review_required','pending_mapping'} else '',))
                    if not rows:
                        for item in self.running_rows:self.table.set(item,'state',STATUS_LABELS.get(report.get('status'),'待复核'))
                    self.state['jobs'].clear();self.queue_running=False;self.running_rows=[]
                    self.queue_count.set(f'{len(rows)} 项结果')
                self.state['busy']=False;self.progress.stop();self.progress.place_forget()
                translated=STATUS_LABELS.get(report.get('status'),report.get('status','待复核'))
                self.status.set(translated);self.summary.set('处理结束，请查看结果。' if not report.get('error') else '任务未完成，请查看运行详情。')
                content='\n\n'.join(explain_task_result(row) for row in rows)
                overview_source=None
                for job,row in zip(self.running_jobs,rows):
                    source=job.get('source','')
                    if row.get('status')=='failed' and source and Path(source).suffix.casefold()=='.dxf':
                        overview_source=source;break
                self.running_jobs=[]
                self.add_message('执行结果 · '+translated,content or str(report.get('error','请在运行详情中查看完整记录。')),overview_source=overview_source)
                if path:self.report_text+='报告位置：'+path+'\n'
                self._update_log();self._sync_buttons()
        except queue.Empty:pass
        if self.state['busy']:
            self._sync_buttons()
        self.poll_id=self.root.after(120,self.poll)

    def clear(self):
        if self.state['busy']:return
        self.state['jobs'].clear();self.row_ids=[]
        for item in self.table.get_children():self.table.delete(item)
        self.empty.place(relx=.5,rely=.60,anchor='center');self.queue_count.set('0 项待运行');self.summary.set('添加任务后，可在这里查看进度和结果。');self._sync_buttons()

    def toggle_settings(self):
        self.settings_open=not self.settings_open
        if self.settings_open:self.settings.pack(side='right',fill='y',before=self.settings.master.winfo_children()[-1])
        else:self.settings.pack_forget()
        self.settings_button.configure(text='收起设置' if self.settings_open else '任务设置')

    def show_queue(self):
        self.queue_window.deiconify();self.queue_window.lift()

    def quick_task(self,kind):
        self.switch_mode(kind)
        if not self.settings_open:self.toggle_settings()
        self.composer.focus_set()

    def new_task(self):
        if self.state['busy']:return
        self.ai_cancel.set();self.ai_generation+=1;self.ai_busy=False
        if self.ai_session is not None:
            from ai_assistant import AssistantSession
            self.ai_session=AssistantSession(self.ai_session.config)
        for card in self.chat_cards:card.destroy()
        self.chat_cards=[];self.last_request=None
        for key in ('source','output','thickness','radius','angle','k_factor'):self.values[key].set('')
        self.composer.delete('1.0','end');self.placeholder_visible=False;self._composer_blur()
        self.welcome.place(relx=.5,rely=.45,anchor='center');self.status.set('就绪')

    def _composer_focus(self,event=None):
        if self.placeholder_visible:
            self.composer.delete('1.0','end');self.composer.configure(fg=INK);self.placeholder_visible=False

    def _composer_blur(self,event=None):
        if not self.composer.get('1.0','end').strip():
            self.composer.insert('1.0',self.placeholder);self.composer.configure(fg=MUTED);self.placeholder_visible=True

    def add_message(self,title,body,*,request=None,overview_source=None):
        self.welcome.place_forget()
        card=self.tk.Frame(self.conversation,bg=WHITE,pady=16);card.pack(fill='x',anchor='n')
        self.chat_cards.append(card)
        self.label(card,title,size=10,bold=True).pack(anchor='w',pady=(0,10))
        width=max(340,self.feed_canvas.winfo_width()-130)
        self.label(card,body,size=11,justify='left',anchor='w',wraplength=width).pack(anchor='w',fill='x')
        if request is not None:self.button(card,'保存审核请求',lambda:self.save_request(request)).pack(anchor='w',pady=(12,0))
        if overview_source:self.button(card,'查看这张图的概览',lambda:self.open_dxf_overview(overview_source)).pack(anchor='w',pady=(12,0))
        self.root.update_idletasks();self.feed_canvas.yview_moveto(1)

    def send_instruction(self):
        if self.ai_busy:
            self.ai_cancel.set();self.status.set('已请求停止，等待当前 API 调用结束。');return 'break'
        if self.state['busy'] or self.placeholder_visible:return 'break'
        text=self.composer.get('1.0','end').strip()
        if not text:return 'break'
        if self.ai_session is not None:
            self._start_ai(text);return 'break'
        from design_instruction import instruction_request
        from tkinter import messagebox
        try:request=instruction_request({'text':text})
        except (ValueError,KeyError,TypeError) as exc:
            messagebox.showerror('无法生成审核请求',str(exc),parent=self.root);return 'break'
        self.add_message('你',text)
        parsed=request['parsed'];self.last_request=request
        if parsed['part_kind']!='roller' or parsed['target_overall_mm'] is None:
            summary='当前快捷指令支持滚筒总长改型，请写明总长（mm）和需要保持不变的接口。其他任务可在任务设置中选择配置文件。'
        else:
            names={'shaft_diameter':'轴径','shaft_end_installation_interfaces':'两端安装结构'}
            protected='、'.join(names[k] for k in parsed['protected_requirements'])
            summary=f'目标总长：{parsed["target_overall_mm"]:g} mm\n'+('保持不变：'+protected+'\n' if protected else '待补充：需要保持不变的接口。\n')
            summary+='下一步：在真实模型上确认尺寸绑定与修改范围。\n尚未执行模型修改。'
        self.add_message('方案待审核',summary,request=request)
        self.composer.delete('1.0','end');self._composer_blur();self.status.set('审核请求已生成 · 未执行模型修改')
        return 'break'

    def configure_ai(self):
        from ai_assistant import AIConfig,AssistantSession,AssistantError
        from ai_assistant.protocols import LABELS,BASES
        from ai_assistant.client import scoped_api_key
        from tkinter import messagebox
        win=self.tk.Toplevel(self.root);win.title('AI 连接');win.geometry('610x720');win.configure(bg=WHITE)
        win.columnconfigure(0,weight=1)
        self.label(win,'连接模型服务',size=18,bold=True).grid(row=0,column=0,sticky='w',padx=24,pady=(20,8))
        self.label(win,'选择 API 协议与服务地址。只发送对话文字，不自动上传 CAD 附件。',size=9,color=MUTED,wraplength=560,justify='left').grid(row=1,column=0,sticky='w',padx=24,pady=(0,12))
        try:env=AIConfig.from_env();env.normalized_base()
        except AssistantError:env=AIConfig(model='',api_key='')
        current=self.ai_session.config if self.ai_session else env
        model=self.tk.StringVar(value=current.model);key=self.tk.StringVar()
        protocol=self.tk.StringVar(value=LABELS[current.protocol]);base=self.tk.StringVar(value=current.normalized_base())
        use_tools=self.tk.BooleanVar(value=current.enable_tools);token_field=self.tk.StringVar(value=current.token_parameter)
        presets={'自定义 / 当前配置':None,
            'OpenAI':('responses',BASES['responses']),
            'DeepSeek':('chat_completions','https://api.deepseek.com'),
            '通用 OpenAI 兼容服务':('chat_completions','https://your-provider.example/v1'),
            'Claude / Anthropic':('anthropic',BASES['anthropic']),
            'Gemini / Google':('gemini',BASES['gemini']),
            'Ollama · 本机':('chat_completions','http://localhost:11434/v1'),
            'LM Studio · 本机':('chat_completions','http://localhost:1234/v1')}
        preset=self.tk.StringVar(value='自定义 / 当前配置')
        def caption(row,text):self.label(win,text,size=9,color=MUTED).grid(row=row,column=0,sticky='w',padx=24,pady=(5,4))
        caption(2,'服务预设')
        picker=self.ttk.Combobox(win,textvariable=preset,values=tuple(presets),state='readonly');picker.grid(row=3,column=0,sticky='ew',padx=24)
        caption(4,'接口协议')
        protocol_picker=self.ttk.Combobox(win,textvariable=protocol,values=tuple(LABELS.values()),state='readonly');protocol_picker.grid(row=5,column=0,sticky='ew',padx=24)
        caption(6,'API 基础地址 · 例如 https://服务域名/v1')
        self.ttk.Entry(win,textvariable=base).grid(row=7,column=0,sticky='ew',padx=24)
        caption(8,'模型名称 · 使用服务商或本机提供的实际名称')
        self.ttk.Entry(win,textvariable=model).grid(row=9,column=0,sticky='ew',padx=24)
        caption(10,'API 密钥 · 不跨服务沿用，本机回环服务可留空')
        self.ttk.Entry(win,textvariable=key,show='*').grid(row=11,column=0,sticky='ew',padx=24)
        self.ttk.Checkbutton(win,text='启用受控工具（模型不支持时可关闭，仅对话）',variable=use_tools).grid(row=12,column=0,sticky='w',padx=24,pady=(10,4))
        extra=self.tk.Frame(win,bg=WHITE);extra.grid(row=13,column=0,sticky='ew',padx=24)
        self.label(extra,'兼容接口的输出额度字段',size=9,color=MUTED).pack(side='left')
        self.ttk.Combobox(extra,textvariable=token_field,values=('max_tokens','max_completion_tokens'),state='readonly',width=22).pack(side='right')
        self.label(win,'密钥只在本次运行内使用。新连接会重置模型上下文；首次对话才验证是否接通。',size=9,color=MUTED,wraplength=560,justify='left').grid(row=14,column=0,sticky='w',padx=24,pady=12)
        actions=self.tk.Frame(win,bg=WHITE);actions.grid(row=15,column=0,sticky='ew',padx=24,pady=6)
        def choose_preset(event=None):
            value=presets[preset.get()]
            if value:
                protocol.set(LABELS[value[0]]);base.set(value[1]);model.set('');key.set('')
        picker.bind('<<ComboboxSelected>>',choose_preset)
        def activate():
            if self.ai_busy:messagebox.showinfo('正在回复','请等待当前回复结束后再切换连接。',parent=win);return
            try:
                selected=next(k for k,v in LABELS.items() if v==protocol.get())
                probe=AIConfig(model=model.get().strip(),api_key='',protocol=selected,base_url=base.get().strip(),enable_tools=use_tools.get(),token_parameter=token_field.get())
                saved=scoped_api_key(probe,key.get(),(self.ai_session.config if self.ai_session else None,env))
                config=AIConfig(model=probe.model,api_key=saved,protocol=selected,base_url=probe.base_url,
                                enable_tools=probe.enable_tools,token_parameter=probe.token_parameter)
                session=AssistantSession(config)
            except (AssistantError,StopIteration) as exc:
                messagebox.showerror('配置未完成',str(exc) or '请选择有效协议。',parent=win);return
            key.set('');self.ai_session=session;self.ai_generation+=1;self.ai_status.set('本机模型' if config.is_local() else '在线模型')
            self.status.set('模型服务已配置 · 首次对话验证连接');win.destroy()
        def local():
            if self.ai_busy:messagebox.showinfo('正在回复','请先停止或等待当前回复。',parent=win);return
            key.set('');self.ai_session=None;self.ai_generation+=1;self.ai_status.set('本地审核');self.status.set('已切换到本地审核');win.destroy()
        self.button(actions,'使用本地审核',local).pack(side='left')
        self.button(actions,'启用连接',activate,primary=True).pack(side='right')

    def _start_ai(self,text):
        self.ai_cancel=threading.Event();self.ai_generation+=1;token=self.ai_generation
        session=self.ai_session;cancel=self.ai_cancel
        self.ai_busy=True;self.add_message('你',text);self.status.set('正在请求模型服务…')
        self.composer.delete('1.0','end');self._composer_blur();self._sync_buttons()
        def worker():
            from ai_assistant import AssistantError
            try:self.ai_events.put((token,session.chat(text,cancel=cancel),None))
            except AssistantError as exc:self.ai_events.put((token,None,str(exc)))
            except Exception:self.ai_events.put((token,None,'AI 回复未完成，请检查连接后重试。'))
        threading.Thread(target=worker,daemon=True).start()

    def _poll_ai(self):
        try:
            while True:
                token,report,error=self.ai_events.get_nowait()
                if token!=self.ai_generation:continue
                self.ai_busy=False
                if error:
                    self.add_message('AI 回复未完成',error);self.status.set('AI 回复未完成')
                else:
                    self.add_message('AI 建议 · 待工程审核',report['text'])
                    for request in report.get('review_requests',[]):
                        self.last_request=request;self.add_message('可保存的审核请求','请核对目标尺寸与保护接口，保存请求不会执行模型修改。',request=request)
                    self.report_text+=json.dumps(report,ensure_ascii=False,indent=2)+'\n\n';self._update_log()
                    self.status.set('回复未完整 · 可缩小问题后重试' if report.get('incomplete') else 'AI 建议已返回 · 未执行模型修改')
                self._sync_buttons()
        except queue.Empty:pass


    def save_request(self,request):
        from tkinter import filedialog,messagebox
        path=filedialog.asksaveasfilename(parent=self.root,defaultextension='.json',initialfile='design-review-request.json',filetypes=[('审核请求','*.json')])
        if not path:return
        try:
            with Path(path).open('x',encoding='utf-8') as stream:json.dump(request,stream,ensure_ascii=False,indent=2,allow_nan=False)
            self.status.set('审核请求已保存')
        except (OSError,ValueError) as exc:messagebox.showerror('未保存审核请求',str(exc),parent=self.root)

    def toggle_details(self):
        if self.detail_window and self.detail_window.winfo_exists():self.detail_window.lift();return
        self.detail_window=self.tk.Toplevel(self.root);self.detail_window.title('运行详情');self.detail_window.geometry('900x570')
        self.log_widget=self.tk.Text(self.detail_window,bg='#F7F9FC',fg=INK,relief='flat',padx=20,pady=16,wrap='word',font=(self.family,10))
        self.log_widget.pack(fill='both',expand=True);self._update_log()

    def _update_log(self):
        if self.log_widget is not None and self.log_widget.winfo_exists():
            self.log_widget.configure(state='normal');self.log_widget.delete('1.0','end');self.log_widget.insert('end',self.report_text or '暂无运行记录。');self.log_widget.configure(state='disabled')

    def show_environment(self):
        from project_workbench import doctor
        from capability_registry import build_capability_report,load_records,format_capability_report
        win=self.tk.Toplevel(self.root);win.title('环境与版本');win.geometry('790x570');win.configure(bg=WHITE)
        self.label(win,'环境与能力状态',size=18,bold=True).pack(anchor='w',padx=24,pady=(22,10))
        self.label(win,'环境可用不代表模型或制造验收通过。',color=MUTED).pack(anchor='w',padx=24,pady=(0,12))
        self.button(win,'修复跨电脑模型引用',self.relocate_models).pack(anchor='w',padx=24,pady=(0,12))
        text=self.tk.Text(win,relief='flat',bg='#F7F9FC',fg=INK,padx=20,pady=16,wrap='word')
        text.pack(fill='both',expand=True,padx=24,pady=(0,24))
        records,load_error=load_records(ROOT)
        report=build_capability_report(root=ROOT,source_path=self.values['source'].get(),
                                       sw_exe=self.values['sw_exe'].get(),records=records)
        self.journal.record('capability_status_viewed',source_sha256=report['selected_input']['sha256'],
                            solidworks_file_version=report['solidworks'].get('version'),
                            capabilities=len(report['capabilities']),index_error=load_error)
        environment=doctor()
        text.insert('end',format_capability_report(report,load_error=load_error)+'\n\n运行环境：'+
                    str(environment.get('platform'))+' / Python '+str(environment.get('python')))
        text.configure(state='disabled')

    def show_logs(self):
        from tkinter import filedialog,messagebox
        from app_logging import WorkJournal
        win=self.tk.Toplevel(self.root);win.title('运行记录');win.geometry('950x620')
        top=self.tk.Frame(win,bg=WHITE,padx=18,pady=14);top.pack(fill='x')
        self.label(top,'运行记录',size=16,bold=True).pack(side='left')
        text=self.tk.Text(win,wrap='word',padx=18,pady=12,relief='flat');text.pack(fill='both',expand=True)
        def refresh():
            text.delete('1.0','end')
            if not isinstance(self.journal,WorkJournal):text.insert('end','日志尚未启用。');return
            names={'session_started':'程序启动','code_identified':'程序版本','input_selected':'选择输入',
                   'capability_status_viewed':'查看能力状态',
                   'dimension_change_started':'尺寸修改前记录',
                   'dimension_change_readback':'尺寸写入后读回',
                   'dimension_change_failed':'尺寸修改失败',
                   'dimension_change_batch_failed':'尺寸修改批次失败',
                   'dimension_change_reopened':'保存重开尺寸读回',
                   'dimension_change_reopen_failed':'重开尺寸读回失败',
                   'part_reopen_geometry':'重开后的实体与包络',
                   'geometry_snapshot_captured':'几何快照已读取',
                   'geometry_snapshot_failed':'几何快照读取失败',
                   'roller_geometry_comparison':'滚筒几何对照',
                   'job_queued':'任务入队','job_started':'任务开始','job_finished':'任务结束','job_failed':'任务失败',
                   'job_validation_failed':'参数检查失败','job_timed_out':'任务等待超时','queue_started':'队列开始',
                   'queue_finished':'队列结束','queue_stop_requested':'请求停止排队','worker_started':'后台进程启动',
                   'drawing_started':'出图开始','drawing_finished':'出图结束','native_drawing_failed':'实机出图失败',
                   'native_drawing_checkpoint':'实机出图进度','ui_callback_exception':'界面异常',
                   'unhandled_exception':'未处理异常','worker_unhandled_exception':'后台异常','cli_analysis':'识别完成',
                   'cli_error':'识别/建模错误','cli_progress':'执行进度','cli_done':'生成完成','session_finished':'程序退出',
                   'diagnostics_exported':'日志已导出','doctor_completed':'环境检查完成'}
            names.update({'package_identified':'测试包版本','reference_relocation_started':'引用修复开始',
                          'reference_updated':'引用已更新','reference_relocation_failed':'引用修复失败',
                          'reference_relocation_finished':'引用修复结束'})
            for row in self.journal.events():text.insert('end',row['time']+'  '+row['level']+'  '+names.get(row['event'],row['event'])+'\n'+json.dumps(row['details'],ensure_ascii=False)+'\n\n')
            text.see('end')
        def export():
            path=filedialog.asksaveasfilename(parent=win,defaultextension='.zip',initialfile='SolidWorksAI-诊断日志.zip')
            if not path:return
            try:self.journal.export(path);messagebox.showinfo('已导出','诊断包仅包含日志，不包含模型或图纸。',parent=win)
            except (OSError,ValueError) as error:messagebox.showerror('导出失败',str(error),parent=win)
        self.button(top,'导出诊断包',export).pack(side='right');self.button(top,'刷新',refresh).pack(side='right',padx=8);refresh()

    def relocate_models(self):
        from tkinter import filedialog,messagebox
        import subprocess,sys,uuid
        package=filedialog.askdirectory(parent=self.root,title='选择含 portable-models.json 的模型测试包')
        if not package:return
        if not (Path(package)/'portable-models.json').is_file():
            messagebox.showerror('未选择模型测试包','此目录没有模型包清单。',parent=self.root);return
        executable=filedialog.askopenfilename(parent=self.root,title='选择本机 SLDWORKS.exe',filetypes=[('SolidWorks','SLDWORKS.exe')])
        if not executable:return
        folder=ROOT/'runtime';folder.mkdir(exist_ok=True);log=folder/('relocate-'+uuid.uuid4().hex+'.log')
        with log.open('x',encoding='utf-8') as stream:
            subprocess.Popen([sys.executable,'-X','utf8',str(ROOT/'work/relocate_model_package.py'),'--package',package,'--sw-exe',executable],cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT)
        self.add_message('正在修复测试包引用','请先关闭已有 SolidWorks。只更新模型测试包，完成结果写入包内 relocation-result.json。\n日志：'+str(log))

    def native_review(self):
        from ql5050px.repair_panel import RepairPanel
        win=self.tk.Toplevel(self.root);win.title('尺寸试改预检');win.geometry('960x620')
        panel=RepairPanel(win,ROOT);panel.frame.pack(fill='both',expand=True);self.tool_panels.append(panel)
        win.protocol('WM_DELETE_WINDOW',lambda:win.destroy() if not panel.busy else panel.status.set('请等待当前预检结束。'))

    def open_drawing(self):
        from drawing_setup import open_drawing_setup
        open_drawing_setup(self.root,ROOT,self.add_message)

    def open_sheet_batch_review(self):
        if self.state['busy']:return
        from tkinter import filedialog
        source=filedialog.askopenfilename(parent=self.root,title='选择已转换的钣金 DXF 工作副本',filetypes=[('DXF 图纸','*.dxf')])
        if not source:return
        win=self.tk.Toplevel(self.root);win.title('钣金批量预检');win.geometry('950x620')
        widget=self.tk.Text(win,wrap='word',padx=16,pady=12);widget.pack(fill='both',expand=True)
        widget.insert('end','正在检查候选轮廓…');widget.configure(state='disabled')
        results=queue.Queue()
        def inspect():
            try:
                from sheet_batch_review import inspect_sheet_batch,format_batch_review
                report=inspect_sheet_batch(source);self.journal.record('sheet_batch_review',source=source,sha256=report['source_sha256'],candidates=len(report['candidates']))
                results.put(('ok',report,format_batch_review(report)))
            except Exception as exc:
                self.journal.exception('sheet_batch_review_failed',exc,source=source);results.put(('error',None,'批量预检失败：'+str(exc)))
        def poll_result():
            if not win.winfo_exists():return
            try:status,report,body=results.get_nowait()
            except queue.Empty:win.after(150,poll_result);return
            widget.configure(state='normal');widget.delete('1.0','end');widget.insert('end',body);widget.configure(state='disabled')
            if status=='ok' and report and not report['production_approved']:
                # 预检只是只读检查；给出「开始导出」入口，让用户确认后再走串行生成。
                bar=self.tk.Frame(win,bg=WHITE);bar.pack(fill='x',padx=16,pady=8)
                self.label(bar,'预检未放行生产；导出前会再次逐件确认。',color=MUTED).pack(side='left')
                self.button(bar,'开始导出…',lambda:self.start_sheet_batch_export(source,win)).pack(side='right')
        threading.Thread(target=inspect,daemon=True).start();win.after(150,poll_result)

    def start_sheet_batch_export(self, source, parent_win=None):
        """弹确认窗 → 构造批量导出任务 → 加入队列串行执行。"""
        from tkinter import messagebox
        from project_workbench import confirm_job
        from export_dialog import ask_export_all_options, list_part_rows
        from batch_export import discover_sheet_parts
        from cad_analyzer import analyze_cad_file

        sw_exe=self.values['sw_exe'].get().strip()
        if not sw_exe:
            messagebox.showwarning('缺少 SolidWorks','请在左侧「SolidWorks 程序」里指定 SLDWORKS.exe，再开始导出。',parent=parent_win or self.root)
            return
        try:
            analysis=analyze_cad_file(source)
            jobs=discover_sheet_parts(analysis)
            real=[j for j in jobs if not j.text_frame]
        except Exception as exc:
            self.journal.exception('sheet_batch_export_analyze_failed',exc,source=source)
            messagebox.showerror('识别失败',str(exc),parent=parent_win or self.root)
            return
        if not real:
            messagebox.showinfo('没有零件','这张图里没有可导出的钣金零件（候选均为疑似文字框）。',parent=parent_win or self.root)
            return
        rows=list_part_rows(real)
        options=ask_export_all_options(
            parent_win or self.root,
            part_count=len(real),
            bent_count=sum(1 for j in real if j.bend_indices),
            labeled_count=0,
            initial_dir=str(Path(source).parent),
            thickness='4',
            radius='1.2',
            angle='90',
            parts=rows,
        )
        if options is None:
            return
        try:
            job=confirm_job({
                'kind':'sheet','action':'batch','name':Path(source).name,
                'source':source,'sw_exe':sw_exe,
                'output_dir':str(options.output_dir),
                'thickness':options.thickness_mm,
                'radius':options.radius_mm,
                'angle':options.angle_degrees,
            })
        except Exception as exc:
            self.journal.exception('sheet_batch_export_confirm_failed',exc)
            messagebox.showerror('参数错误',str(exc),parent=parent_win or self.root)
            return
        if not self.state['jobs']:
            for item in self.table.get_children():self.table.delete(item)
            self.row_ids=[]
        self.state['jobs'].append(job)
        item=self.table.insert('','end',values=(MODES['sheet'][0],Path(source).name+'（批量）','待运行'))
        self.row_ids.append(item)
        self.queue_count.set(f"{len(self.state['jobs'])} 项待运行");self.status.set('就绪');self._sync_buttons()
        self.journal.record('sheet_batch_export_queued',source=source,output_dir=str(options.output_dir))
        self.add_message('批量导出已加入队列','钣金批量导出 · '+Path(source).name+'\n输出目录：'+str(options.output_dir)+'\n请在任务队列中运行。')
        if parent_win is not None:
            try:parent_win.destroy()
            except self.tk.TclError:pass

    def start_dxf_review(self):
        if self.state['busy']:return
        from tkinter import filedialog
        path=filedialog.askopenfilename(parent=self.root,title='选择要检查的 DXF 图纸',filetypes=[('DXF 图纸','*.dxf')])
        if not path:return
        self.switch_mode('sheet');self.action.set('识别图纸');self.values['source'].set(path)
        self.journal.record('input_selected',field='source',path=path,kind='sheet')
        self.open_dxf_overview(path)

    def open_dxf_overview(self,path=None):
        from tkinter import filedialog
        if path is None:
            path=filedialog.askopenfilename(parent=self.root,title='选择需要查看的 DXF 图纸',
                                            filetypes=[('DXF 图纸','*.dxf')])
        if not path:return
        win=self.tk.Toplevel(self.root);win.title('DXF 图纸概览');win.geometry('850x620')
        top=self.tk.Frame(win,bg=WHITE);top.pack(fill='x',padx=18,pady=12)
        self.label(top,'只读检查 · 未执行建模',color=MUTED).pack(side='left')
        text=self.tk.Text(win,wrap='word',padx=16,pady=12,relief='flat')
        text.pack(fill='both',expand=True);text.insert('end','正在读取…');text.configure(state='disabled')
        results=queue.Queue()
        def inspect():
            try:
                from dxf_overview import inspect_dxf,format_overview,preview_geometry
                result=inspect_dxf(path)
                try:preview=preview_geometry(path,result['sha256']);preview_error=None
                except Exception as exc:preview=None;preview_error=str(exc)
                self.journal.record('dxf_overview_completed',source=path,source_sha256=result['sha256'],
                                    mismatch_count=result['dimension_mismatch_count'])
                results.put(('ok',(format_overview(result),preview,preview_error)))
            except Exception as exc:
                self.journal.exception('dxf_overview_failed',exc,source=path)
                results.put(('error',str(exc)))
        def poll_result():
            if not win.winfo_exists():return
            try:status,body=results.get_nowait()
            except queue.Empty:
                win.after(150,poll_result);return
            text.configure(state='normal');text.delete('1.0','end')
            if status=='ok':
                body,preview,preview_error=body
                if preview is not None:
                    self.button(top,'查看图形',lambda:self.show_dxf_preview(preview)).pack(side='right')
                elif preview_error:body+='\n图形预览不可用：'+preview_error
            text.insert('end',body if status=='ok' else '图纸概览失败：'+body)
            text.configure(state='disabled')
        threading.Thread(target=inspect,daemon=True).start()
        win.after(150,poll_result)

    def show_dxf_preview(self,preview):
        tk=self.tk
        win=tk.Toplevel(self.root);win.title('DXF 图形预览');win.geometry('1040x680');win.configure(bg=WHITE)
        self.label(win,'仅供查看：线条近似显示，文字、标注、块及部分实体可能未显示；不能用于尺寸或制造判断。',
                   color=MUTED,wraplength=980,justify='left').pack(anchor='w',padx=14,pady=10)
        body=tk.Frame(win,bg=WHITE);body.pack(fill='both',expand=True,padx=14,pady=(0,14))
        panel=tk.Frame(body,bg=WHITE,width=210);panel.pack(side='left',fill='y');panel.pack_propagate(False)
        self.label(panel,'显示图层',bold=True).pack(anchor='w',pady=(0,8))
        listing=tk.Listbox(panel,selectmode='extended',exportselection=False)
        listing.pack(fill='both',expand=True)
        names=sorted({row['layer'] for row in preview['paths']})
        for name in names:listing.insert('end',name)
        listing.selection_set(0,'end')
        canvas=tk.Canvas(body,bg='white',highlightbackground=LINE,highlightthickness=1)
        canvas.pack(side='right',fill='both',expand=True,padx=(12,0))
        def draw():
            canvas.delete('all')
            selected={names[i] for i in listing.curselection()}
            paths=[row['points'] for row in preview['paths'] if row['layer'] in selected]
            if not paths:
                canvas.create_text(20,20,anchor='nw',text='所选图层没有可预览的线条。');return
            points=[p for row in paths for p in row]
            x0=min(p[0] for p in points);x1=max(p[0] for p in points)
            y0=min(p[1] for p in points);y1=max(p[1] for p in points)
            width=max(canvas.winfo_width(),2);height=max(canvas.winfo_height(),2)
            scale=min(max(width-40,1)/max(x1-x0,1e-9),max(height-40,1)/max(y1-y0,1e-9))
            for row in paths:
                coords=[]
                for x,y in row:coords.extend((20+(x-x0)*scale,height-20-(y-y0)*scale))
                canvas.create_line(*coords,fill='#303030')
        def show_all():listing.selection_set(0,'end');draw()
        self.button(panel,'显示所选图层',draw).pack(fill='x',pady=(10,4))
        self.button(panel,'显示全部',show_all).pack(fill='x')
        if preview['truncated']:
            self.label(panel,'图形过多，仅显示部分线条。',color=MUTED,wraplength=190).pack(anchor='w',pady=10)
        canvas.bind('<Configure>',lambda event:draw())

    def open_delivery(self):
        from delivery_panel import open_delivery
        open_delivery(self.root)

    def close(self):
        from tkinter import messagebox
        if self.state['busy'] or any(panel.busy for panel in self.tool_panels):
            self.stop.set();messagebox.showinfo('等待当前任务结束','已停止后续排队。请等待当前任务结束再关闭，不会强制结束 CAD 进程。',parent=self.root)
        else:
            self.ai_cancel.set();self.ai_generation+=1
            self.root.after_cancel(self.poll_id);self.root.destroy()


def run():
    import tkinter as tk
    root=tk.Tk();Workbench(root);root.mainloop()
