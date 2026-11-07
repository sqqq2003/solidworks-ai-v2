"""Desktop daily-use workflow: text to form, remembered inputs, queue edits, history. No COM."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


@unittest.skipUnless(os.environ.get('DISPLAY') or os.name=='nt','desktop display unavailable; run with a virtual display or Windows')
class DesktopWorkflowTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        import desktop_ui
        from desktop_ui import Workbench
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup);self.tmp=Path(folder.name)
        self.settings=self.tmp/'desktop-settings.json';self.reports=self.tmp/'reports'
        for name,value in (('SETTINGS_FILE',self.settings),('REPORTS_DIR',self.reports)):
            patcher=patch.object(desktop_ui,name,value);patcher.start();self.addCleanup(patcher.stop)
        self.root=tk.Tk();self.view=Workbench(self.root);self.root.update()
        self.addCleanup(self.view.close)

    def send(self,text):
        self.view._composer_focus();self.view.composer.insert('1.0',text)
        self.view.send_instruction();self.root.update()
        return self.view.chat_cards[-1]

    def card_buttons(self,card):
        import tkinter as tk
        return {w.cget('text'):w for w in card.winfo_children() if isinstance(w,tk.Button)}

    def card_text(self,card):
        import tkinter as tk
        return '\n'.join(w.cget('text') for w in card.winfo_children() if isinstance(w,tk.Label))

    def test_sheet_text_fills_form_without_confirming_or_queueing(self):
        self.view.action.set('识别图纸')
        card=self.send('钣金件 板厚2.5 R1 K0.36 90度折弯 第2个轮廓 反向折弯')
        self.assertIn('板厚：2.5 mm',self.card_text(card))
        self.assertEqual(self.view.values['thickness'].get(),'')
        self.view.confirmed.set(True)
        self.card_buttons(card)['填入任务设置'].invoke();self.root.update()
        values={k:self.view.values[k].get() for k in ('kind','thickness','radius','angle','k_factor','profile')}
        self.assertEqual(values,{'kind':'sheet','thickness':'2.5','radius':'1','angle':'90','k_factor':'0.36','profile':'2'})
        self.assertTrue(self.view.flip.get())
        self.assertFalse(self.view.confirmed.get())
        self.assertEqual(self.view.action.get(),'生成计划')
        self.assertTrue(self.view.settings_open)
        self.assertEqual(self.view.state['jobs'],[])

    def test_unmentioned_fields_are_left_as_they_were(self):
        self.view.switch_mode('sheet');self.view.values['radius'].set('3')
        card=self.send('钣金 板厚2')
        self.assertIn('待确认',self.card_text(card))
        self.card_buttons(card)['填入任务设置'].invoke()
        self.assertEqual(self.view.values['thickness'].get(),'2')
        self.assertEqual(self.view.values['radius'].get(),'3')
        self.assertEqual(self.view.values['k_factor'].get(),'')

    def test_machine_envelope_text_fills_parametric_form(self):
        card=self.send('把 GT-ZX 整机改成 1800×900×1500 mm')
        self.card_buttons(card)['填入任务设置'].invoke()
        self.assertEqual(self.view.values['kind'].get(),'parametric')
        self.assertEqual([self.view.values[k].get() for k in ('machine','length','width','height')],
                         ['GT-ZX','1800','900','1500'])
        self.assertEqual(self.view.state['jobs'],[])

    def test_unrecognized_text_offers_no_form_change(self):
        card=self.send('帮我看看这个')
        self.assertNotIn('填入任务设置',self.card_buttons(card))
        self.assertIn('没有识别到任务类型',self.card_text(card))

    def test_apply_is_refused_while_running(self):
        from design_instruction import parse_design_text
        self.view.state['busy']=True
        self.assertFalse(self.view.apply_design(parse_design_text('钣金 板厚2')))
        self.assertEqual(self.view.values['thickness'].get(),'')
        self.view.state['busy']=False

    def test_solidworks_path_is_remembered_but_sheet_parameters_are_not(self):
        exe=self.tmp/'SLDWORKS.exe';exe.write_bytes(b'')
        self.view.values['thickness'].set('2.5');self.view.values['k_factor'].set('0.36')
        with patch('tkinter.filedialog.askopenfilename',return_value=str(exe)):
            self.view.choose('sw_exe')
        stored=json.loads(self.settings.read_text(encoding='utf-8'))
        self.assertEqual(stored,{'sw_exe':str(exe)})
        self.view.values['sw_exe'].set('')
        self.view.load_preferences()
        self.assertEqual(self.view.values['sw_exe'].get(),str(exe))
        self.assertEqual(self.view.values['thickness'].get(),'2.5')

    def test_invalid_or_missing_remembered_program_is_ignored(self):
        other=self.tmp/'notepad.exe';other.write_bytes(b'')
        for path in (str(other),str(self.tmp/'gone'/'SLDWORKS.exe')):
            self.settings.write_text(json.dumps({'sw_exe':path}),encoding='utf-8')
            self.view.values['sw_exe'].set('');self.view.load_preferences()
            self.assertEqual(self.view.values['sw_exe'].get(),'')

    def test_recent_files_are_listed_and_select_matching_mode(self):
        drawing=self.tmp/'part.dxf';drawing.write_bytes(b'0');config=self.tmp/'machine.json';config.write_text('{}')
        with patch('tkinter.filedialog.askopenfilename',return_value=str(drawing)):
            self.view.choose('source')
        self.view.use_recent(str(config))
        self.assertEqual(self.view.recent_entries(),[str(config),str(drawing)])
        self.assertEqual(self.view.values['kind'].get(),'ql5050px')
        self.view.use_recent(str(drawing))
        self.assertEqual(self.view.values['kind'].get(),'sheet')
        self.assertEqual(self.view.values['source'].get(),str(drawing))
        self.view.use_recent(str(self.tmp/'deleted.dxf'))
        self.assertEqual(self.view.values['source'].get(),str(drawing))
        self.assertEqual(self.view.state['jobs'],[])
        self.assertFalse(self.view.confirmed.get())

    def queue_three(self):
        self.view.switch_mode('parametric');self.view.values['machine'].set('GT-ZX')
        for length in ('1700','1800','1900'):
            self.view.values['length'].set(length);self.assertTrue(self.view.append())
        return [job['length'] for job in self.view.state['jobs']]

    def test_queue_items_can_be_reordered_and_removed(self):
        self.assertEqual(self.queue_three(),[1700.0,1800.0,1900.0])
        rows=list(self.view.row_ids)
        self.assertEqual(str(self.view.remove_button.cget('state')),'disabled')
        self.view.table.selection_set(rows[1]);self.root.update()
        self.assertEqual(str(self.view.up_button.cget('state')),'normal')
        self.view.move_selected(-1)
        self.assertEqual([j['length'] for j in self.view.state['jobs']],[1800.0,1700.0,1900.0])
        self.assertEqual(list(self.view.table.get_children()),[rows[1],rows[0],rows[2]])
        self.assertEqual(self.view.row_ids,[rows[1],rows[0],rows[2]])
        self.assertEqual(str(self.view.up_button.cget('state')),'disabled')
        self.view.move_selected(-1)
        self.assertEqual([j['length'] for j in self.view.state['jobs']],[1800.0,1700.0,1900.0])
        self.view.table.selection_set(rows[2]);self.root.update()
        self.assertEqual(str(self.view.down_button.cget('state')),'disabled')
        self.view.remove_selected()
        self.assertEqual([j['length'] for j in self.view.state['jobs']],[1800.0,1700.0])
        self.assertEqual(self.view.queue_count.get(),'2 项待运行')
        self.assertNotIn(rows[2],self.view.table.get_children())

    def test_queue_cannot_be_edited_while_running(self):
        self.queue_three();rows=list(self.view.row_ids)
        self.view.table.selection_set(rows[0]);self.view.state['busy']=True;self.view._sync_buttons()
        self.assertEqual(str(self.view.remove_button.cget('state')),'disabled')
        self.view.remove_selected();self.view.move_selected(1)
        self.assertEqual([j['length'] for j in self.view.state['jobs']],[1700.0,1800.0,1900.0])
        self.view.state['busy']=False

    def test_history_lists_saved_reports_read_only(self):
        import tkinter as tk
        from project_workbench import write_report
        artifact=self.tmp/'out'/'part.SLDPRT'
        path=write_report({'schema_version':1,'status':'review_required','counts':{'review_required':1},
            'results':[{'name':'plate.dxf','kind':'sheet','status':'review_required','artifact':{'path':str(artifact)},
                        'events':[{'event':'done','reopen':None}]}]},self.reports)
        (self.reports/('project-report-'+'0'*32+'.json')).write_text('{broken',encoding='utf-8')
        with patch('report_history.open_folder') as reveal:
            win=self.view.show_history();self.root.update()
            frame=next(w for w in win.winfo_children() if isinstance(w,tk.Frame) and any(isinstance(c,self.view.ttk.Treeview) for c in w.winfo_children()))
            table=next(c for c in frame.winfo_children() if isinstance(c,self.view.ttk.Treeview))
            detail=next(c for c in frame.winfo_children() if isinstance(c,tk.Text))
            rows=table.get_children();self.assertEqual(len(rows),2)
            states={table.item(row,'values')[1] for row in rows}
            self.assertEqual(states,{'待复核','无法读取'})
            good=next(row for row in rows if table.item(row,'values')[1]=='待复核')
            table.selection_set(good);self.root.update()
            text=detail.get('1.0','end')
            self.assertIn(str(path),text);self.assertIn(str(artifact),text)
            self.assertIn('重开验证尚未完成',text);self.assertIn('只供查看',text)
            top=win.winfo_children()[0]
            buttons={w.cget('text'):w for w in top.winfo_children() if isinstance(w,tk.Button)}
            buttons['打开报告文件夹'].invoke();reveal.assert_called_with(self.reports)
            buttons['打开输出所在文件夹'].invoke();reveal.assert_called_with(artifact.parent)
            bad=next(row for row in rows if row!=good);table.selection_set(bad);self.root.update()
            self.assertIn('无法读取',detail.get('1.0','end'))
            win.destroy()
        self.assertEqual(self.view.state['jobs'],[])

    def test_history_window_handles_empty_folder(self):
        import tkinter as tk
        win=self.view.show_history();self.root.update()
        frame=next(w for w in win.winfo_children() if isinstance(w,tk.Frame) and any(isinstance(c,tk.Text) for c in w.winfo_children()))
        detail=next(c for c in frame.winfo_children() if isinstance(c,tk.Text))
        self.assertIn('暂无历史报告',detail.get('1.0','end'))
        win.destroy()

    def test_queue_reports_are_written_to_history_folder(self):
        self.queue_three()
        with patch('project_workbench.run_batch',return_value={'status':'completed','results':[],'counts':{}}):
            self.view.start()
            import time
            deadline=time.monotonic()+5
            while self.view.state['busy'] and time.monotonic()<deadline:
                self.root.update();time.sleep(.02)
        self.assertEqual(len(list(self.reports.glob('project-report-*.json'))),1)


class ReportDetailTests(unittest.TestCase):
    def test_detail_for_unreadable_report_states_reason(self):
        from desktop_ui import format_report_detail
        text=format_report_detail({'written_at':'2026-11-07T21:00:00+08:00','path':'r.json','error':'报告格式无效'})
        self.assertIn('2026-11-07 21:00:00',text);self.assertIn('无法读取：报告格式无效',text)

    def test_detail_never_upgrades_result(self):
        from desktop_ui import format_report_detail
        entry={'written_at':'2026-11-07T21:00:00+08:00','path':'r.json','error':None,'artifacts':[]}
        text=format_report_detail(entry,{'status':'failed','counts':{'failed':1},
            'results':[{'name':'a.dxf','status':'failed','error':'boom'}]})
        self.assertIn('结果：失败',text);self.assertIn('原因：boom',text);self.assertNotIn('通过',text)


if __name__=='__main__':
    unittest.main()
