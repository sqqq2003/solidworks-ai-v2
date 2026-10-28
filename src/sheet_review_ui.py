"""Interactive manifest editor. Tk is imported only when opening the editor."""
from __future__ import annotations

import copy
from pathlib import Path

FIELDS = ('quantity', 'thickness', 'radius', 'angle', 'k_factor', 'scale', 'hole_policy')
LABELS = {'quantity': '数量', 'thickness': '板厚 mm', 'radius': '内半径 mm',
          'angle': '折弯角度 °', 'k_factor': '本单 K 因子', 'scale': '缩放倍数',
          'hole_policy': '圆孔策略'}
HOLE_POLICIES = {'孔槽同步缩放': 'scale_all', '仅圆孔孔径不变': 'preserve_circle_diameter'}


def open_review_editor(parent, manifest_path, *, on_queue=None):
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    from batch_review_manifest import (load_manifest, save_manifest, select_part,
                                      set_parameter, validate_manifest)
    document = load_manifest(manifest_path)
    if not isinstance(document, dict) or document.get('schema_version') != 1 or document.get('kind') != 'sheet_batch_review':
        raise ValueError('请选择本程序生成的钣金审核清单。')
    win = tk.Toplevel(parent)
    win.title('逐件审核 · 数量、尺寸与工艺')
    win.geometry('1040x700')
    win.minsize(900, 600)
    state = {'manifest': document, 'saved_path': Path(manifest_path), 'dirty': False,
             'current': None, 'loading': False, 'pending_edits': False}
    top = ttk.Frame(win, padding=14)
    top.pack(fill='x')
    ttk.Label(top, text='选择零件 → 填写并确认参数 → 另存审核清单 → 加入任务队列').pack(anchor='w')
    ttk.Label(top, text='识别结果是候选值；缩放不改变板厚。圆孔策略不适用于任意槽孔。').pack(anchor='w', pady=5)
    bar = ttk.Frame(win, padding=8)
    bar.pack(side='bottom', fill='x')
    content = ttk.Frame(win, padding=(14, 0))
    content.pack(fill='both', expand=True)
    table = ttk.Treeview(content, columns=('name', 'quantity', 'thickness', 'included', 'review'), show='headings', selectmode='browse')
    for key, label, width in [('name', '候选零件', 110), ('quantity', '数量候选', 80), ('thickness', '板厚候选', 80), ('included', '选择', 60), ('review', '审核', 95)]:
        table.heading(key, text=label)
        table.column(key, width=width)
    table.pack(side='left', fill='both', expand=True)
    editor = ttk.Frame(content, padding=(20, 0, 0, 0))
    editor.pack(side='right', fill='y')
    variables = {key: tk.StringVar() for key in FIELDS}
    actor, reason, included = tk.StringVar(), tk.StringVar(), tk.BooleanVar()
    description = tk.StringVar(value='先选择一个候选零件')
    ttk.Label(editor, textvariable=description, wraplength=390).grid(row=0, column=0, columnspan=2, sticky='w', pady=8)
    for row, key in enumerate(FIELDS, 1):
        ttk.Label(editor, text=LABELS[key]).grid(row=row, column=0, sticky='w', pady=1)
        if key == 'hole_policy':
            field = ttk.Combobox(editor, textvariable=variables[key], state='readonly', width=28,
                                 values=tuple(HOLE_POLICIES))
        else:
            field = ttk.Entry(editor, textvariable=variables[key], width=31)
        field.grid(row=row, column=1, sticky='ew', padx=(12, 0), pady=1)
    ttk.Label(editor, text='孔心位置随外形缩放；“孔径不变”仅适用于圆孔，槽孔仍随外形缩放。',
              wraplength=390).grid(row=8, column=0, columnspan=2, sticky='w', pady=2)
    for row, label, variable in [(9, '确认人', actor), (10, '选择/排除理由', reason)]:
        ttk.Label(editor, text=label).grid(row=row, column=0, sticky='w', pady=1)
        ttk.Entry(editor, textvariable=variable, width=31).grid(row=row, column=1, padx=(12, 0), pady=1)
    ttk.Checkbutton(editor, text='包含在本批次', variable=included).grid(row=11, column=0, columnspan=2, sticky='w', pady=2)
    status = tk.StringVar(value='尚未修改；所有候选都需要明确包含或排除。')

    def refresh():
        for item in table.get_children():
            table.delete(item)
        for part in state['manifest']['parts']:
            review = part.get('selection_review')
            parameters = part['ledger']['parameters']
            quantity = parameters.get('quantity')
            thickness = parameters.get('thickness')
            table.insert('', 'end', iid=part['id'], values=(part['label'],
                str(quantity['value']) if quantity else '未识别',
                str(thickness['value']) + ' mm' if thickness else '未识别',
                '包含' if part['included'] else '排除' if review else '未选择',
                '有记录，待检查' if review else '未确认'))

    def choose(_event=None):
        selection = table.selection()
        if not selection:
            return
        identity = selection[0]
        if state['pending_edits'] and identity != state['current']:
            if not messagebox.askyesno('本件输入未确认', '切换零件并放弃本件尚未确认的输入？', parent=win):
                table.selection_set(state['current'])
                return
        elif state['pending_edits'] and identity == state['current']:
            return
        state['loading'] = True
        state['current'] = identity
        part = next(p for p in state['manifest']['parts'] if p['id'] == identity)
        for key in FIELDS:
            raw = part['ledger']['parameters'].get(key)
            value = str(raw['value']) if raw else ''
            if key == 'hole_policy':
                value = next((label for label, code in HOLE_POLICIES.items() if code == value), '')
            variables[key].set(value)
        included.set(part['included'])
        prior = part.get('selection_review') or {}
        if prior.get('actor'):
            actor.set(prior['actor'])
        reason.set(prior.get('reason', ''))
        state.update(loading=False, pending_edits=False)
        parameters = part['ledger']['parameters']
        sources = []
        for key, label in [('quantity', '数量'), ('thickness', '板厚')]:
            entry = parameters.get(key)
            sources.append(label + '来源：' + (str(entry.get('source') or '未记录') if entry else '未识别'))
        description.set(part['label'] + (' · 疑似文字框，只能排除' if part['text_frame'] else '')
                        + f"\n外形：{part['bounds_mm']} mm；折弯线：{len(part['bend_indices'])}"
                        + '\n' + '；'.join(sources))
        status.set('修改输入后点击“确认本件”；切换零件不会自动保存输入。')

    def confirm_current():
        if not state['current']:
            return
        try:
            if not actor.get().strip() or not reason.get().strip():
                raise ValueError('请填写确认人和包含/排除的理由。')
            draft = copy.deepcopy(state['manifest'])
            part = next(p for p in draft['parts'] if p['id'] == state['current'])
            if included.get():
                for key in FIELDS:
                    text = variables[key].get().strip()
                    if not text:
                        continue  # The validator reports missing values; do not invent them.
                    value = HOLE_POLICIES[text] if key == 'hole_policy' else float(text)
                    prior = part['ledger']['parameters'].get(key, {})
                    set_parameter(draft, part['id'], key=key, value=value, actor=actor.get().strip(),
                        source='窗口人工确认；原来源：' + str(prior.get('source') or '用户填写'))
            select_part(draft, part['id'], included=included.get(), actor=actor.get().strip(), reason=reason.get().strip())
            state.update(manifest=draft, dirty=True, pending_edits=False)
            refresh()
            table.selection_set(part['id'])
            status.set('已记录本件确认，请继续审核其他候选并另存。')
        except (ValueError, KeyError, TypeError) as error:
            messagebox.showerror('本件未确认', str(error), parent=win)

    def check():
        try:
            report = validate_manifest(state['manifest'])
            blockers = report['blockers']
            messagebox.showinfo('审核清单检查', '\n'.join(blockers[:30]) if blockers
                                else '记录完整；尚未执行原生生成或工程验收。', parent=win)
        except (OSError, ValueError, KeyError, TypeError) as error:
            messagebox.showerror('清单不可用', str(error), parent=win)

    def save():
        if state['pending_edits']:
            messagebox.showwarning('本件输入未确认', '请先点击“确认本件参数与选择”，再另存清单。', parent=win)
            return False
        path = filedialog.asksaveasfilename(parent=win, title='另存审核清单（不覆盖旧文件）',
            defaultextension='.json', filetypes=[('审核清单', '*.json')])
        if not path:
            return False
        try:
            save_manifest(state['manifest'], path)
            state.update(saved_path=Path(path), dirty=False)
            status.set('已另存：' + path)
            return True
        except (OSError, ValueError, TypeError) as error:
            messagebox.showerror('未保存', str(error), parent=win)
            return False

    def queue():
        if on_queue is None:
            return
        if state['pending_edits']:
            messagebox.showwarning('本件输入未确认', '请先确认本件输入并另存清单。', parent=win)
            return
        if state['dirty'] and not save():
            return
        on_queue(str(state['saved_path']))

    def close():
        if (state['dirty'] or state['pending_edits']) and not messagebox.askyesno('未另存的确认记录', '关闭并放弃尚未另存的确认记录或输入？', parent=win):
            return
        win.destroy()

    ttk.Button(editor, text='确认本件参数与选择', command=confirm_current).grid(row=12, column=0, columnspan=2, sticky='ew', pady=3)
    ttk.Label(bar, textvariable=status, wraplength=680).pack(side='left')
    ttk.Button(bar, text='检查完整性', command=check).pack(side='right', padx=5)
    ttk.Button(bar, text='另存清单…', command=save).pack(side='right', padx=5)
    if on_queue is not None:
        ttk.Button(bar, text='加入生成队列…', command=queue).pack(side='right', padx=5)
    table.bind('<<TreeviewSelect>>', choose)
    def edited(*_args):
        if not state['loading'] and state['current']:
            state['pending_edits'] = True
            status.set('本件输入已改动，尚未确认或保存。')
    for variable in [*variables.values(), actor, reason, included]:
        variable.trace_add('write', edited)
    win.protocol('WM_DELETE_WINDOW', close)
    refresh()
    return win
