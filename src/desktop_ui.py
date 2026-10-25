"""A focused Tk desktop; widgets are created only by Workbench/run."""
from pathlib import Path
import json
import queue
import threading
from desktop_jobs import MODES, ACTIONS, QL_ACTIONS, STATUS_LABELS, build_desktop_job

ROOT=Path(__file__).resolve().parents[1]
BG='#F8F8F7'; WHITE='#FFFFFF'; INK='#252525'; MUTED='#787872'; LINE='#E8E8E5'
BLUE='#242424'; NAV='#EFEFED'


class Workbench:
    def __init__(self, root):
        import tkinter as tk
        from tkinter import ttk, font
        self.tk=tk;self.ttk=ttk;self.root=root
        self.state={'busy':False,'jobs':[]};self.messages=queue.Queue();self.stop=threading.Event()
        self.values={k:tk.StringVar(value=v) for k,v in {
            'kind':'unified','source':'','output':'','sw_exe':'','machine':'QL-5050PX','ql_action':'plan',
            'profile':'1','variant':'0','thickness':'','radius':'','angle':'','k_factor':'',
            'length':'1800','width':'900','height':'1500'}.items()}
        self.confirmed=tk.BooleanVar();self.flip=tk.BooleanVar();self.inferred=tk.BooleanVar()
        self.native_open=False;self.advanced_open=False;self.detail_open=False
        self.report_text='';self.inputs=[];self.nav_buttons={};self.row_ids=[]
        self.running_rows=[];self.queue_running=False;self.last_request=None
        self.settings_open=False;self.chat_cards=[]
        self.ai_session=None;self.ai_busy=False;self.ai_generation=0
        self.ai_events=queue.Queue();self.ai_cancel=threading.Event()
        self.ai_status=tk.StringVar(value='本地审核')
        self.action=tk.StringVar(value='生成计划');self.ql_action=tk.StringVar(value='参数计划')
        self.status=tk.StringVar(value='就绪');self.queue_count=tk.StringVar(value='0 项待运行')
        self.summary=tk.StringVar(value='添加任务后，可在这里查看进度和结果。')
        root.title('SolidWorks AI · 设计工作台');root.geometry('1360x900');root.minsize(1080,740);root.configure(bg=BG)
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
        self.action.trace_add('write',self._action_changed)
        self.switch_mode('unified')
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
            button=self.button(nav,title,lambda k=key:self.switch_mode(k))
            button.configure(anchor='w',pady=10,padx=16)
            button.pack(fill='x',padx=12,pady=2);self.nav_buttons[key]=button
        tk.Frame(nav,bg=LINE,height=1).pack(fill='x',padx=20,pady=20)
        self.button(nav,'任务队列',self.show_queue).pack(fill='x',padx=12,pady=2)
        self.button(nav,'环境与版本',self.show_environment).pack(fill='x',padx=12,pady=2)
        self.button(nav,'AI 连接',self.configure_ai).pack(fill='x',padx=12,pady=2)
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
        for text,kind in [('零件改型','roller'),('制造资料','unified'),('设计检查','ql5050px')]:
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
        self.tk.Label(tools,textvariable=self.ai_status,bg=BG,fg=MUTED,font=(self.family,9)).pack(side='left',padx=6)
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
        self.numeric_row(self.sheet_frame,[('thickness','板厚 · mm'),('radius','内半径 · mm'),('angle','折弯角度 · °'),('k_factor','K 因子')])
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
        self.native_button=self.button(controls,'原生配方审核',self.native_review);self.native_button.pack(fill='x',pady=(8,0))

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
        if path:self.values[key].set(path)

    def append(self):
        if self.state['busy']:return
        from tkinter import messagebox
        try:
            job=build_desktop_job({k:v.get() for k,v in self.values.items()},ACTIONS.get(self.action.get(),'plan'),
                 confirmed=self.confirmed.get(),flip=self.flip.get(),allow_inferred=self.inferred.get())
            if not self.state['jobs']:
                for item in self.table.get_children():self.table.delete(item)
                self.row_ids=[]
            self.state['jobs'].append(job)
            source=job.get('config',job.get('source','目标包络'))
            item=self.table.insert('', 'end',values=(MODES[job['kind']][0],Path(source).name,'待运行'))
            self.row_ids.append(item);self.empty.place_forget();self.summary.set('任务已加入队列，准备好后点击运行。')
            self.queue_count.set(f"{len(self.state['jobs'])} 项待运行");self.status.set('就绪');self._sync_buttons()
            self.add_message('任务已加入队列',MODES[job['kind']][0]+' · '+Path(source).name+'\n准备好后，在任务队列中运行。')
        except (OSError,ValueError,KeyError) as exc:messagebox.showerror('请检查任务信息',str(exc),parent=self.root)

    def _sync_buttons(self):
        busy=self.state['busy'];has_jobs=bool(self.state['jobs'])
        self.queue_button.configure(text=f'任务队列 · {len(self.state["jobs"])}' if has_jobs else '任务队列')
        self.send_button.configure(state='disabled' if busy else 'normal',text='■' if self.ai_busy else '↑')
        self.add_button.configure(state='disabled' if busy else 'normal')
        self.start_button.configure(state='normal' if has_jobs and not busy else 'disabled')
        self.clear_button.configure(state='disabled' if busy or not self.table.get_children() else 'normal')
        self.stop_button.configure(state='normal' if busy else 'disabled')
        self.native_button.configure(state='disabled' if busy else 'normal')
        for button in self.nav_buttons.values():button.configure(state='disabled' if busy else 'normal')
        for widget,normal in self.inputs:widget.configure(state='disabled' if busy else normal)

    def start(self):
        if self.state['busy'] or not self.state['jobs']:return
        from project_workbench import run_batch,write_report
        jobs=list(self.state['jobs']);self.running_rows=list(self.row_ids);self.queue_running=True
        self.state['busy']=True;self.stop.clear();self._sync_buttons()
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
        self.stop.set();self.summary.set('已请求停止；等待当前任务结束，不强制关闭 SolidWorks。')

    def poll(self):
        self._poll_ai()
        try:
            while True:
                report,path=self.messages.get_nowait()
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
                content='\n'.join(STATUS_LABELS.get(row.get('status'),row.get('status','待复核'))+' · '+str(row.get('name',row.get('kind','任务'))) for row in rows)
                self.add_message('执行结果 · '+translated,content or str(report.get('error','请在运行详情中查看完整记录。')))
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
        self._sync_buttons()
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

    def add_message(self,title,body,*,request=None):
        self.welcome.place_forget()
        card=self.tk.Frame(self.conversation,bg=WHITE,pady=16);card.pack(fill='x',anchor='n')
        self.chat_cards.append(card)
        self.label(card,title,size=10,bold=True).pack(anchor='w',pady=(0,10))
        width=max(340,self.feed_canvas.winfo_width()-130)
        self.label(card,body,size=11,justify='left',anchor='w',wraplength=width).pack(anchor='w',fill='x')
        if request is not None:self.button(card,'保存审核请求',lambda:self.save_request(request)).pack(anchor='w',pady=(12,0))
        self.root.update_idletasks();self.feed_canvas.yview_moveto(1)

    def send_instruction(self):
        if self.state['busy']:return 'break'
        if self.ai_busy:
            self.ai_cancel.set();self.status.set('已请求停止，等待当前 API 调用结束。');return 'break'
        if self.placeholder_visible:return 'break'
        text=self.composer.get('1.0','end').strip()
        if not text:return 'break'
        if self.ai_session is not None:
            self._start_ai(text);return 'break'
        from engineering_intelligence.proposals import instruction_request
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
        from tkinter import messagebox
        win=self.tk.Toplevel(self.root);win.title('AI 连接');win.geometry('520x410');win.configure(bg=WHITE)
        win.columnconfigure(0,weight=1)
        self.label(win,'接入 OpenAI',size=18,bold=True).grid(row=0,column=0,sticky='w',padx=24,pady=(22,10))
        self.label(win,'发送输入文本和当前对话，不自动上传附件或 CAD 文件。',size=9,color=MUTED,wraplength=460,justify='left').grid(row=1,column=0,sticky='w',padx=24,pady=(0,14))
        env=AIConfig.from_env()
        model=self.tk.StringVar(value=self.ai_session.config.model if self.ai_session else env.model)
        key=self.tk.StringVar()
        self.label(win,'模型名称 · 使用账号可访问的模型',size=9,color=MUTED).grid(row=2,column=0,sticky='w',padx=24)
        self.ttk.Entry(win,textvariable=model).grid(row=3,column=0,sticky='ew',padx=24,pady=(5,12))
        self.label(win,'API 密钥 · 留空沿用当前连接或本机环境变量',size=9,color=MUTED).grid(row=4,column=0,sticky='w',padx=24)
        self.ttk.Entry(win,textvariable=key,show='*').grid(row=5,column=0,sticky='ew',padx=24,pady=(5,10))
        self.label(win,'密钥仅在本次进程内使用，不保存到项目或日志。配置完成后，首次对话再验证连接。',size=9,color=MUTED,wraplength=460,justify='left').grid(row=6,column=0,sticky='w',padx=24,pady=(0,14))
        actions=self.tk.Frame(win,bg=WHITE);actions.grid(row=7,column=0,sticky='ew',padx=24)
        def activate():
            if self.ai_busy:messagebox.showinfo('正在回复','请等待当前回复结束后再切换连接。',parent=win);return
            try:
                config=AIConfig(model=model.get().strip(),api_key=key.get().strip() or (self.ai_session.config.api_key if self.ai_session else env.api_key))
                session=AssistantSession(config)
            except AssistantError as exc:messagebox.showerror('配置未完成',str(exc),parent=win);return
            key.set('');self.ai_session=session;self.ai_generation+=1;self.ai_status.set('OpenAI 模式')
            self.status.set('OpenAI 已配置 · 首次对话验证连接');win.destroy()
        def local():
            if self.ai_busy:messagebox.showinfo('正在回复','请先停止或等待当前回复。',parent=win);return
            key.set('');self.ai_session=None;self.ai_generation+=1;self.ai_status.set('本地审核');self.status.set('已切换到本地审核');win.destroy()
        self.button(actions,'使用本地审核',local).pack(side='left')
        self.button(actions,'启用 OpenAI',activate,primary=True).pack(side='right')

    def _start_ai(self,text):
        self.ai_cancel=threading.Event();self.ai_generation+=1;token=self.ai_generation
        session=self.ai_session;cancel=self.ai_cancel
        self.ai_busy=True;self.add_message('你',text);self.status.set('正在请求 OpenAI…')
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
        from project_workbench import doctor,capabilities
        win=self.tk.Toplevel(self.root);win.title('环境与版本');win.geometry('790x570');win.configure(bg=WHITE)
        self.label(win,'运行环境',size=18,bold=True).pack(anchor='w',padx=24,pady=(22,10))
        self.label(win,'环境可用不代表模型或制造验收通过。',color=MUTED).pack(anchor='w',padx=24,pady=(0,12))
        text=self.tk.Text(win,relief='flat',bg='#F7F9FC',fg=INK,padx=20,pady=16,wrap='word')
        text.pack(fill='both',expand=True,padx=24,pady=(0,24));text.insert('end',json.dumps({'环境':doctor(),'功能':capabilities()},ensure_ascii=False,indent=2));text.configure(state='disabled')

    def native_review(self):
        from ql5050px.modeling_gui import open_review
        open_review(self.root,self.state,self.messages,self.stop)

    def close(self):
        from tkinter import messagebox
        if self.state['busy']:
            self.stop.set();messagebox.showinfo('等待当前任务结束','已停止后续排队。请等待当前任务结束再关闭，不会强制结束 CAD 进程。',parent=self.root)
        else:
            self.ai_cancel.set();self.ai_generation+=1
            self.root.after_cancel(self.poll_id);self.root.destroy()


def run():
    import tkinter as tk
    root=tk.Tk();Workbench(root);root.mainloop()
